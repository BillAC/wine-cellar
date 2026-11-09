from sqlalchemy import create_engine, event, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from env_settings import get_settings

_SETTINGS = get_settings()
_SETTINGS.data_dir.mkdir(parents=True, exist_ok=True)
SQLALCHEMY_DATABASE_URL = _SETTINGS.database_url

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


WINE_METADATA_COLUMNS = {
    "color": "VARCHAR",
    "country_of_origin": "VARCHAR",
    "grape_varieties": "JSON",
    "description": "JSON",
    "pairing": "JSON",
    "grapeminds_tasting_notes": "JSON",
    "flavor_profile": "JSON",
    "grapeminds_id": "VARCHAR(64)",
    "created_by_user_id": "INTEGER",
    "comment": "VARCHAR",
    "checkout_date": "DATE",
    "drink_from": "INTEGER",
    "drink_until": "INTEGER",
    "market_price": "FLOAT",
}

TASTING_NOTE_COLUMNS = {
    "user_id": "INTEGER",
    "author_name": "VARCHAR(64)",
}


def migrate_wine_metadata_columns(database_engine=engine):
    """Add wine metadata and multi-user columns to existing SQLite cellar databases."""
    inspector = inspect(database_engine)
    table_names = inspector.get_table_names()

    if "wine_entries" in table_names:
        existing_wine_columns = {
            column["name"] for column in inspector.get_columns("wine_entries")
        }
        with database_engine.begin() as connection:
            for name, column_type in WINE_METADATA_COLUMNS.items():
                if name not in existing_wine_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE wine_entries ADD COLUMN {name} {column_type}"
                    )
            if "type" in existing_wine_columns:
                connection.exec_driver_sql(
                    """
                    UPDATE wine_entries
                    SET color = CASE UPPER(TRIM(type))
                        WHEN 'RED' THEN 'Red'
                        WHEN 'WHITE' THEN 'White'
                        WHEN 'ROSE' THEN 'Rosé'
                        WHEN 'ROSÉ' THEN 'Rosé'
                        WHEN 'CHAMPAGNE' THEN 'Champagne'
                        WHEN 'FORTIFIED' THEN 'Fortified'
                        WHEN 'DESSERT' THEN 'Dessert'
                        ELSE type
                    END
                    WHERE (color IS NULL OR TRIM(color) = '')
                      AND type IS NOT NULL
                      AND TRIM(type) != ''
                    """
                )
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_wine_entries_grapeminds_id ON wine_entries (grapeminds_id)"
            )

    if "tasting_notes" in table_names:
        existing_note_columns = {
            column["name"] for column in inspector.get_columns("tasting_notes")
        }
        with database_engine.begin() as connection:
            for name, column_type in TASTING_NOTE_COLUMNS.items():
                if name not in existing_note_columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE tasting_notes ADD COLUMN {name} {column_type}"
                    )


def init_admin_user(database_engine=engine):
    """Ensure the root 'cellar' administrator account exists and is approved."""
    import auth
    from models import User, UserRole, UserStatus
    from datetime import datetime, timezone

    inspector = inspect(database_engine)
    if "users" not in inspector.get_table_names():
        return

    auth.validate_configuration()
    settings = get_settings()
    admin_username = settings.cellar_username
    admin_password = settings.cellar_password
    admin_email = settings.cellar_admin_email

    with SessionLocal() as db:
        admin_user = (
            db.query(User)
            .filter(User.username.ilike(admin_username))
            .first()
        )
        if not admin_user:
            admin_user = User(
                username=admin_username,
                email=admin_email,
                hashed_password=auth.hash_password(admin_password),
                role=UserRole.ADMIN,
                status=UserStatus.APPROVED,
                approved_at=datetime.now(timezone.utc),
            )
            db.add(admin_user)
            db.commit()
        else:
            changed = False
            if admin_user.role != UserRole.ADMIN:
                admin_user.role = UserRole.ADMIN
                changed = True
            if admin_user.status != UserStatus.APPROVED:
                admin_user.status = UserStatus.APPROVED
                changed = True
            if changed:
                db.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
