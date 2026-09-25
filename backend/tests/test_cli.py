from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app import cli
from app.db.models import PublicHoliday, User
from app.db.session import Database
from app.domain.enums import HolidaySource
from app.seed import table_counts

BUNDLED = Path(__file__).resolve().parents[1] / "app" / "data" / "hk_public_holidays_1823.ics"


@pytest.fixture(autouse=True)
def _isolated_upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``seed --reset`` empties the upload directory: never point a test at real data."""
    monkeypatch.setattr(cli, "_configured_upload_dir", lambda: str(tmp_path / "uploads"))


@pytest.fixture
def tmp_db(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'cli.db'}")
    yield database
    database.dispose()


def run(argv: list[str], db: Database) -> int:
    # main() disposes the engine; the cached_property recreates it on next use.
    db.__dict__.pop("engine", None)
    db.__dict__.pop("session_factory", None)
    return cli.main(argv, database=db)


def counts(db: Database) -> dict[str, int]:
    db.__dict__.pop("engine", None)
    db.__dict__.pop("session_factory", None)
    with db.session_factory() as s:
        return table_counts(s)


def test_init_db(tmp_db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["init-db"], tmp_db) == 0
    assert counts(tmp_db)["users"] == 0
    assert "up to date" in capsys.readouterr().out


def test_seed_is_idempotent(tmp_db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["seed"], tmp_db) == 0
    first = counts(tmp_db)
    assert first["users"] == 6 and first["public_holidays"] == 34
    capsys.readouterr()
    assert run(["seed"], tmp_db) == 0
    assert "already exist" in capsys.readouterr().out
    assert counts(tmp_db) == first


def test_reset_requires_yes(tmp_db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    run(["seed"], tmp_db)
    with tmp_db.session_factory() as s:
        s.execute(text("DELETE FROM feedback"))
        s.commit()
    assert run(["seed", "--reset"], tmp_db) == 2
    assert "--yes" in capsys.readouterr().out
    assert counts(tmp_db)["feedback"] == 0  # untouched


def test_reset_with_yes_rebuilds(tmp_db: Database) -> None:
    run(["seed"], tmp_db)
    with tmp_db.session_factory() as s:
        s.execute(text("DELETE FROM feedback"))
        s.commit()
    assert run(["seed", "--reset", "--yes"], tmp_db) == 0
    assert counts(tmp_db)["feedback"] == 2


def test_import_holidays_from_file(tmp_db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["import-holidays", "--file", str(BUNDLED), "--year", "2026"], tmp_db) == 0
    assert "17 inserted, 0 updated" in capsys.readouterr().out
    with tmp_db.session_factory() as s:
        rows = s.scalars(select(PublicHoliday)).all()
        assert len(rows) == 17
        assert {r.source for r in rows} == {HolidaySource.ICS_1823}
    # second run: nothing changes
    assert run(["import-holidays", "--file", str(BUNDLED), "--year", "2026"], tmp_db) == 0
    assert "0 inserted, 0 updated, 17 unchanged" in capsys.readouterr().out


def test_import_holidays_overwrites_seed_source(tmp_db: Database) -> None:
    run(["seed"], tmp_db)
    assert run(["import-holidays", "--file", str(BUNDLED), "--year", "2026", "2027"], tmp_db) == 0
    with tmp_db.session_factory() as s:
        assert s.scalar(select(func.count(User.id))) == 6
        sources = {h.source for h in s.scalars(select(PublicHoliday))}
        assert sources == {HolidaySource.ICS_1823}
        assert s.scalar(select(func.count(PublicHoliday.id))) == 34


def test_import_missing_year_fails_clearly(
    tmp_db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["import-holidays", "--file", str(BUNDLED), "--year", "2031"], tmp_db) == 1
    err = capsys.readouterr().err
    assert "2031" in err and "3 years ahead" in err


def test_import_bad_file(
    tmp_db: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["import-holidays", "--file", str(tmp_path / "nope.ics")], tmp_db) == 1
    empty = tmp_path / "empty.ics"
    empty.write_text("BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    assert run(["import-holidays", "--file", str(empty)], tmp_db) == 1


def test_import_from_url_uses_fetch(
    tmp_db: Database, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return BUNDLED.read_text(encoding="utf-8")

    monkeypatch.setattr(cli, "fetch_1823_ics", lambda url: fake_fetch(url))
    assert (
        run(["import-holidays", "--year", "2027", "--url", "https://example.com/x.ics"], tmp_db)
        == 0
    )
    assert calls == ["https://example.com/x.ics"]
    assert "17 inserted" in capsys.readouterr().out


def test_import_fetch_failure_exit_code(
    tmp_db: Database, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(url: str) -> str:
        raise cli.HolidayFetchError("offline")

    monkeypatch.setattr(cli, "fetch_1823_ics", boom)
    assert run(["import-holidays"], tmp_db) == 1
    assert "offline" in capsys.readouterr().err


def test_unknown_command_exits() -> None:
    with pytest.raises(SystemExit):
        cli.main(["bogus"])
