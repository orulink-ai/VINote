from contextlib import contextmanager

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def _create_engine():
    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def init_db():
    from app import db_models  # noqa: F401
    from app.models import feishu_destination, mcp_connections, workspace, workspace_generation_claim, workspace_attachment, local_file, content_plugins  # noqa: F401

    if settings.workspace_cloud_runtime:
        from app.services.workspace_bootstrap import protect_api_tables
        # Create and revoke direct client access in one transaction. Supabase
        # default grants must not expose tables between separate commits.
        with engine.begin() as connection:
            Base.metadata.create_all(bind=connection)
            protect_api_tables(connection, Base.metadata.tables.values())
        return
    Base.metadata.create_all(bind=engine)
    _ensure_note_share_columns()
    _ensure_note_workspace_columns()
    _ensure_note_evidence_columns()
    _ensure_note_origin_column()
    _ensure_local_file_purpose_column()


def _ensure_local_file_purpose_column():
    inspector = inspect(engine)
    if "local_files" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("local_files")}
    if "purpose" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE local_files ADD COLUMN purpose VARCHAR(16) NOT NULL DEFAULT 'unassigned'"
            )


def _ensure_note_origin_column():
    columns = {column["name"] for column in inspect(engine).get_columns("notes")}
    if "generation_client" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE notes ADD COLUMN generation_client VARCHAR(16)")


def _ensure_note_share_columns():
    inspector = inspect(engine)
    if "notes" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notes")}
    statements: list[str] = []

    if "share_token" not in columns:
        statements.append("ALTER TABLE notes ADD COLUMN share_token VARCHAR(64)")
    if "share_enabled" not in columns:
        statements.append("ALTER TABLE notes ADD COLUMN share_enabled BOOLEAN NOT NULL DEFAULT 0")
    if "share_created_at" not in columns:
        statements.append("ALTER TABLE notes ADD COLUMN share_created_at TIMESTAMP")

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_notes_share_token ON notes (share_token)"
        )


def _ensure_note_workspace_columns():
    inspector = inspect(engine)
    if "notes" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notes")}
    statements: list[str] = []

    if "scope" not in columns:
        statements.append("ALTER TABLE notes ADD COLUMN scope VARCHAR(16) NOT NULL DEFAULT 'personal'")
    if "team_id" not in columns:
        statements.append("ALTER TABLE notes ADD COLUMN team_id VARCHAR(36)")

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_notes_team_id ON notes (team_id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_notes_scope_created_at ON notes (scope, created_at)"
        )


def _ensure_note_evidence_columns():
    inspector = inspect(engine)
    if "notes" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("notes")}
    if "structured_json" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE notes ADD COLUMN structured_json TEXT")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
