"""``reset-demo`` and ``seed --reset``: drop, reseed and delete the uploaded files (all offline)."""

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app import cli
from app.db.models import LeaveRequest, User
from app.db.session import Database
from app.seed import table_counts


@pytest.fixture
def tmp_db(tmp_path: Path):
    database = Database(f"sqlite:///{tmp_path / 'reset.db'}")
    yield database
    database.dispose()


@pytest.fixture
def uploads(tmp_path: Path) -> Path:
    return tmp_path / "uploads"


def run(argv: list[str], db: Database, uploads: Path | None) -> int:
    db.__dict__.pop("engine", None)  # main() disposes the engine
    db.__dict__.pop("session_factory", None)
    return cli.main(argv, database=db, upload_dir=uploads)


def counts(db: Database) -> dict[str, int]:
    db.__dict__.pop("engine", None)
    db.__dict__.pop("session_factory", None)
    with db.session_factory() as s:
        return table_counts(s)


def make_uploads(root: Path) -> list[Path]:
    """A tree like the app's: yyyy/mm/<hex>.ext, plus the .incoming temp directory."""
    files = [
        root / "2026" / "09" / "a1b2.pdf",
        root / "2026" / "09" / "c3d4.png",
        root / "2026" / "10" / "e5f6.jpg",
        root / ".incoming" / "partial.tmp",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fictional")
    return files


def dirty(db: Database) -> None:
    """Extra rows and a deleted seed row: a demo that has been played with."""
    with db.session_factory() as s:
        s.execute(text("DELETE FROM feedback"))
        s.execute(text("UPDATE users SET job_title = 'Changed' WHERE id = 1"))
        s.execute(
            text("DELETE FROM leave_requests WHERE id = (SELECT min(id) FROM leave_requests)")
        )
        s.commit()


def test_refuses_without_yes_and_changes_nothing(
    tmp_db: Database, uploads: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["seed"], tmp_db, uploads) == 0
    dirty(tmp_db)
    files = make_uploads(uploads)
    before = counts(tmp_db)
    capsys.readouterr()

    assert run(["reset-demo"], tmp_db, uploads) == 2
    out = capsys.readouterr().out
    assert "--yes" in out and "Refusing" in out
    assert counts(tmp_db) == before
    assert all(path.exists() for path in files)


def test_resets_a_database_with_extra_rows_and_attachments(
    tmp_db: Database, uploads: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["seed"], tmp_db, uploads) == 0
    pristine = counts(tmp_db)
    dirty(tmp_db)
    files = make_uploads(uploads)
    assert counts(tmp_db) != pristine
    capsys.readouterr()

    assert run(["reset-demo", "--yes"], tmp_db, uploads) == 0
    out = capsys.readouterr().out

    assert counts(tmp_db) == pristine  # the deleted and changed rows are back
    with tmp_db.session_factory() as s:
        assert s.get(User, 1).job_title != "Changed"
        assert s.scalar(select(func.count(LeaveRequest.id))) == 10
    assert not any(path.exists() for path in files)
    assert list(uploads.iterdir()) == []  # the directory stays, emptied
    assert "users: 6" in out
    assert "requests: 20 (10 leave, 10 claim)" in out
    assert "public holidays: 34" in out
    assert "uploaded files removed: 4" in out
    assert "amy.lau@example.com" in out and "eva.cheung@example.com" in out


def test_resets_an_empty_database_and_a_missing_upload_dir(
    tmp_db: Database, uploads: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert not uploads.exists()
    assert run(["reset-demo", "--yes"], tmp_db, uploads) == 0
    assert counts(tmp_db)["users"] == 6
    assert "uploaded files removed: 0" in capsys.readouterr().out
    assert not uploads.exists()  # nothing is created for it


def test_is_repeatable(tmp_db: Database, uploads: Path) -> None:
    for _ in range(3):
        make_uploads(uploads)
        assert run(["reset-demo", "--yes"], tmp_db, uploads) == 0
        assert counts(tmp_db)["users"] == 6
        assert list(uploads.iterdir()) == []


def test_symlinks_are_left_alone_and_nothing_outside_is_touched(
    tmp_db: Database, tmp_path: Path, uploads: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    precious = outside / "precious.txt"
    precious.write_text("keep me")
    nested = outside / "sub" / "nested.txt"
    nested.write_text("keep me too")

    uploads.mkdir()
    (uploads / "real.pdf").write_bytes(b"x")
    (uploads / "link-to-file").symlink_to(precious)
    (uploads / "link-to-dir").symlink_to(outside, target_is_directory=True)
    (uploads / "2026").mkdir()
    (uploads / "2026" / "deep-link").symlink_to(nested)
    (uploads / "2026" / "gone.png").write_bytes(b"x")
    capsys.readouterr()

    assert run(["reset-demo", "--yes"], tmp_db, uploads) == 0
    captured = capsys.readouterr()

    assert precious.read_text() == "keep me" and nested.read_text() == "keep me too"
    assert (outside / "sub").is_dir()
    assert not (uploads / "real.pdf").exists() and not (uploads / "2026" / "gone.png").exists()
    # links are skipped, not followed and not deleted; so is the directory that still holds one
    assert (uploads / "link-to-file").is_symlink()
    assert (uploads / "link-to-dir").is_symlink()
    assert (uploads / "2026" / "deep-link").is_symlink()
    assert "uploaded files removed: 2" in captured.out
    assert "could not be removed" in captured.err


def test_a_symlinked_upload_root_resolves_and_only_empties_its_target(
    tmp_db: Database, tmp_path: Path
) -> None:
    real = tmp_path / "volume" / "uploads"
    real.mkdir(parents=True)
    (real / "a.pdf").write_bytes(b"x")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    assert run(["reset-demo", "--yes"], tmp_db, alias) == 0
    assert real.is_dir() and list(real.iterdir()) == []


@pytest.mark.parametrize("where", ["root", "home", "home_parent"])
def test_refuses_dangerous_paths_before_touching_anything(
    where: str,
    tmp_db: Database,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home" / "ken"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (home / "notes.txt").write_text("mine")
    target = {"root": Path(os.sep), "home": home, "home_parent": home.parent}[where]

    assert run(["seed"], tmp_db, home) == 0
    before = counts(tmp_db)
    capsys.readouterr()

    assert run(["reset-demo", "--yes"], tmp_db, target) == 1
    assert "refusing" in capsys.readouterr().err
    assert counts(tmp_db) == before  # the database was not touched either
    assert (home / "notes.txt").read_text() == "mine"


def test_refuses_an_empty_upload_dir_setting(tmp_db: Database, capsys) -> None:
    assert run(["reset-demo", "--yes"], tmp_db, "  ") == 1
    assert "UPLOAD_DIR is empty" in capsys.readouterr().err


def test_an_upload_dir_that_is_a_file_is_refused(tmp_db: Database, tmp_path: Path, capsys) -> None:
    afile = tmp_path / "not-a-dir"
    afile.write_text("x")
    assert run(["reset-demo", "--yes"], tmp_db, afile) == 1
    assert "not a directory" in capsys.readouterr().err
    assert afile.read_text() == "x"


def test_seed_reset_also_clears_the_uploads(
    tmp_db: Database, uploads: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(["seed"], tmp_db, uploads) == 0
    files = make_uploads(uploads)
    capsys.readouterr()

    assert run(["seed", "--reset"], tmp_db, uploads) == 2  # still needs --yes
    assert all(path.exists() for path in files)

    assert run(["seed", "--reset", "--yes"], tmp_db, uploads) == 0
    out = capsys.readouterr().out
    assert not any(path.exists() for path in files)
    assert "Uploaded files removed: 4" in out and "users: 6" in out


def test_plain_seed_never_touches_uploads(tmp_db: Database, uploads: Path) -> None:
    files = make_uploads(uploads)
    assert run(["seed"], tmp_db, uploads) == 0
    assert run(["seed"], tmp_db, uploads) == 0
    assert all(path.exists() for path in files)


def test_the_upload_dir_comes_from_the_settings_by_default(
    tmp_db: Database, uploads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = make_uploads(uploads)
    monkeypatch.setattr(cli, "_configured_upload_dir", lambda: str(uploads))
    assert run(["reset-demo", "--yes"], tmp_db, None) == 0
    assert not any(path.exists() for path in files)
