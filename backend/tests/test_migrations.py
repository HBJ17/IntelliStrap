from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app import db, models  # noqa: F401


def test_migration_matches_models(tmp_path):
    engine = db.configure(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    db.init_db()
    with engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"compare_type": False})
        diff = compare_metadata(mc, db.Base.metadata)
    assert diff == []
    tables = set(inspect(engine).get_table_names())
    assert {"owners", "shops", "items", "straps", "events", "list_items", "orders", "app_settings"} <= tables
