from sqlalchemy.orm import Session
import models
from datetime import date


# --- Location CRUD ---

def create_location(db: Session, name: str, sub_location: str = None, parent_location_id: int = None):
    """Creates a new Location entry (rack/shelf/bin)."""
    db_location = models.Location(
        name=name,
        sub_location=sub_location,
        parent_location_id=parent_location_id,
    )
    db.add(db_location)
    db.commit()
    db.refresh(db_location)
    return db_location


def get_all_locations(db: Session):
    """Retrieves all locations."""
    return db.query(models.Location).order_by(models.Location.name).all()


def update_location(db: Session, location: models.Location, updates: dict):
    """Updates a location's editable fields."""
    for field, value in updates.items():
        setattr(location, field, value)
    db.commit()
    db.refresh(location)
    return location


def delete_location(db: Session, location: models.Location):
    """Deletes an empty leaf location."""
    db.delete(location)
    db.commit()


# --- WineEntry CRUD ---

def create_wine(db: Session, wine_data_dict: dict):
    """Creates a new wine entry in the database."""
    db_wine = models.WineEntry(**wine_data_dict)
    db.add(db_wine)
    db.commit()
    db.refresh(db_wine)
    return db_wine


def get_wine_by_qr_id(db: Session, qr_id: str):
    """Retrieves a specific wine using its unique QR ID."""
    return db.query(models.WineEntry).filter(models.WineEntry.qr_id == qr_id).first()


def get_wines_by_grapeminds_id(db: Session, grapeminds_id: str):
    """Retrieves all wine entries matching a specific Grapeminds ID."""
    return db.query(models.WineEntry).filter(models.WineEntry.grapeminds_id == grapeminds_id).all()


def get_all_wines(db: Session, skip: int = 0, limit: int = 100):
    """Retrieves a list of all wines, with pagination."""
    return db.query(models.WineEntry).offset(skip).limit(int(limit)).all()


def update_wine_status(db: Session, qr_id: str, new_status: models.WineStatus):
    """Marks a wine as removed/gifted/broken."""
    db_wine = get_wine_by_qr_id(db, qr_id)
    if not db_wine:
        return None
    db_wine.status = new_status
    db.commit()
    db.refresh(db_wine)
    return db_wine


# --- TastingNote CRUD ---

def create_tasting_note(
    db: Session,
    wine_entry_id: int,
    notes: str = None,
    tasting_date: date = None,
    tannin: float = 0.5,
    acidity: float = 0.5,
    body: float = 0.5,
    alcohol: float = 0.5,
    fruit_intensity: float = 0.5,
    aroma_tags: str = None,
    user_id: int = None,
    author_name: str = None,
):
    """Creates a tasting note linked to a specific wine."""
    db_note = models.TastingNote(
        wine_entry_id=wine_entry_id,
        notes=notes,
        tasting_date=tasting_date or date.today(),
        tannin=tannin,
        acidity=acidity,
        body=body,
        alcohol=alcohol,
        fruit_intensity=fruit_intensity,
        aroma_tags=aroma_tags,
        user_id=user_id,
        author_name=author_name,
    )
    db.add(db_note)
    db.commit()
    db.refresh(db_note)
    return db_note


# --- User & Account CRUD ---

def create_user_request(db: Session, username: str, email: str, password: str = None) -> models.User:
    """Creates a new pending user access request."""
    import auth
    hashed = auth.hash_password(password) if password else None
    user = models.User(
        username=username.strip(),
        email=email.strip().lower(),
        hashed_password=hashed,
        role=models.UserRole.USER,
        status=models.UserStatus.PENDING,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_user_by_id(db: Session, user_id: int) -> models.User | None:
    return db.get(models.User, user_id)


def get_user_by_username_or_email(db: Session, identifier: str) -> models.User | None:
    from sqlalchemy import func
    clean_id = identifier.strip().lower()
    return (
        db.query(models.User)
        .filter(
            (func.lower(models.User.username) == clean_id)
            | (func.lower(models.User.email) == clean_id)
        )
        .first()
    )


def list_users(
    db: Session,
    status: models.UserStatus = None,
    role: models.UserRole = None,
    skip: int = 0,
    limit: int = 100,
) -> list[models.User]:
    query = db.query(models.User)
    if status is not None:
        query = query.filter(models.User.status == status)
    if role is not None:
        query = query.filter(models.User.role == role)
    return query.order_by(models.User.created_at.desc()).offset(skip).limit(limit).all()


def approve_user(db: Session, user: models.User) -> models.User:
    from datetime import datetime, timezone
    user.status = models.UserStatus.APPROVED
    user.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def reject_user(db: Session, user: models.User) -> models.User:
    user.status = models.UserStatus.REJECTED
    db.commit()
    db.refresh(user)
    return user


def update_user_status(db: Session, user: models.User, new_status: models.UserStatus) -> models.User:
    user.status = new_status
    db.commit()
    db.refresh(user)
    return user


def update_user_role(db: Session, user: models.User, new_role: models.UserRole) -> models.User:
    user.role = new_role
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user: models.User) -> None:
    db.delete(user)
    db.commit()


def create_password_reset_token(
    db: Session, user_id: int, ttl_hours: int
) -> models.PasswordResetToken:
    import secrets
    from datetime import datetime, timedelta, timezone

    token_str = secrets.token_urlsafe(32)
    token_record = models.PasswordResetToken(
        user_id=user_id,
        token=token_str,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
        used=False,
    )
    db.add(token_record)
    db.commit()
    db.refresh(token_record)
    return token_record


def get_valid_reset_token(db: Session, token_str: str) -> models.PasswordResetToken | None:
    from datetime import datetime, timezone
    token_record = (
        db.query(models.PasswordResetToken)
        .filter(models.PasswordResetToken.token == token_str)
        .first()
    )
    if not token_record or token_record.used:
        return None

    now = datetime.now(timezone.utc)
    expires = token_record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        return None

    return token_record


def reset_password_with_token(
    db: Session, token_record: models.PasswordResetToken, new_password: str
) -> models.User:
    import auth
    user = token_record.user
    user.hashed_password = auth.hash_password(new_password)
    if user.status == models.UserStatus.PENDING:
        user.status = models.UserStatus.APPROVED
    token_record.used = True
    db.commit()
    db.refresh(user)
    return user
