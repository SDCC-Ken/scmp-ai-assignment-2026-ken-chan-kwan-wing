"""The attachments table on an existing database, and the cleanup helper for staged uploads."""

import os
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.db.models import Attachment
from app.db.session import Database, create_db_engine
from app.domain.clock import utcnow
from app.domain.enums import RequestType
from app.main import create_app
from app.seed import seed_demo_data
from app.services.attachments import cleanup_staged_uploads, link_to_request
from tests.attachments.conftest import CATHY
from tests.attachments.helpers import PNG, upload_ok
from tests.chat.helpers import Chat
from tests.conftest import CSRF_HEADERS, SEED_TODAY, get_user, login, make_settings


def test_a_pre_attachments_database_boots_and_gets_the_table(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'old.db'}"
    old = Database(url)
    old.init_db()
    with old.session_factory() as s:
        seed_demo_data(s, today=SEED_TODAY)
    with old.engine.begin() as conn:  # turn it into a database from before Phase 2b
        conn.execute(text("DROP TABLE attachments"))
    assert "attachments" not in inspect(old.engine).get_table_names()
    old.dispose()

    settings = make_settings(
        database_url=url, upload_dir=str(tmp_path / "uploads"), db_auto_seed=False
    )
    with TestClient(create_app(settings), headers=CSRF_HEADERS) as client:  # runs start-up
        login(client, CATHY)
        chat = Chat(client)
        info = upload_ok(client, chat.id)  # the new table works through the API
        assert client.get(f"/api/attachments/{info['id']}").content == PNG
        assert client.get(f"/api/chat/conversations/{chat.id}").status_code == 200

    engine = create_db_engine(url)
    inspector = inspect(engine)
    assert "attachments" in inspector.get_table_names()
    indexes = {ix["name"] for ix in inspector.get_indexes("attachments")}
    assert {
        "ix_attachments_conversation_id",
        "ix_attachments_owner_user_id",
        "ix_attachments_request",
    } <= indexes
    columns = {c["name"] for c in inspector.get_columns("attachments")}
    assert columns == {
        "id",
        "owner_user_id",
        "conversation_id",
        "message_id",
        "request_type",
        "request_id",
        "original_filename",
        "content_type",
        "size_bytes",
        "sha256",
        "storage_path",
        "extraction_json",
        "created_at",
    }
    engine.dispose()


def test_a_database_that_already_has_the_table_is_left_alone(seeded: Database) -> None:
    seeded.init_db()  # second start-up: create_all + sync_schema must be no-ops
    seeded.init_db()


def age(db: Database, attachment_id: int, delta: timedelta) -> None:
    with db.session_factory() as s:
        row = s.get(Attachment, attachment_id)
        assert row is not None
        row.created_at = utcnow() - delta
        s.commit()


def test_cleanup_removes_only_old_staged_uploads(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    old_staged = upload_ok(cathy, chat.id)["id"]
    fresh_staged = upload_ok(cathy, chat.id)["id"]
    old_attached = upload_ok(cathy, chat.id)["id"]
    old_linked = upload_ok(cathy, chat.id)["id"]
    cathy.post(
        f"/api/chat/conversations/{chat.id}/messages",
        json={"content": "", "attachment_ids": [old_attached]},
    )
    me = get_user(seeded, CATHY).id
    with seeded.session_factory() as s:
        link_to_request(s, [old_linked], RequestType.LEAVE, 1, me)
        s.commit()
    for attachment_id in (old_staged, old_attached, old_linked):
        age(seeded, attachment_id, timedelta(hours=25))
    age(seeded, fresh_staged, timedelta(hours=23))

    with seeded.session_factory() as s:
        paths = {i: s.get(Attachment, i).storage_path for i in (old_staged, fresh_staged)}  # type: ignore[union-attr]
        assert cleanup_staged_uploads(s, upload_dir) == 1
        remaining = {a.id for a in s.query(Attachment).all()}
    assert remaining == {fresh_staged, old_attached, old_linked}
    assert not (upload_dir / paths[old_staged]).exists()
    assert (upload_dir / paths[fresh_staged]).exists()


def test_cleanup_tolerates_a_file_that_is_already_gone(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    gone = upload_ok(cathy, chat.id)["id"]
    age(seeded, gone, timedelta(days=3))
    with seeded.session_factory() as s:
        row = s.get(Attachment, gone)
        assert row is not None
        (upload_dir / row.storage_path).unlink()
        assert cleanup_staged_uploads(s, upload_dir) == 1
        assert s.get(Attachment, gone) is None


def test_cleanup_uses_the_given_clock_and_age(
    cathy: TestClient, chat: Chat, seeded: Database, upload_dir: Path
) -> None:
    upload_ok(cathy, chat.id)
    with seeded.session_factory() as s:
        assert cleanup_staged_uploads(s, upload_dir) == 0
        assert cleanup_staged_uploads(s, upload_dir, now=utcnow() + timedelta(hours=25)) == 1


def test_cleanup_removes_stale_temp_files_of_dead_uploads(
    seeded: Database, upload_dir: Path
) -> None:
    incoming = upload_dir / ".incoming"
    incoming.mkdir(parents=True)
    stale, fresh = incoming / "old.part", incoming / "new.part"
    stale.write_bytes(b"x")
    fresh.write_bytes(b"x")
    long_ago = (utcnow() - timedelta(days=2)).timestamp()
    os.utime(stale, (long_ago, long_ago))
    with seeded.session_factory() as s:
        cleanup_staged_uploads(s, upload_dir)
    assert not stale.exists() and fresh.exists()
