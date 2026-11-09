import enum
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Date,
    Boolean,
    Enum as SAEnum,
    JSON,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import datetime


class WineType(str, enum.Enum):
    """Canonical wine categories — used for both DB storage and API validation."""
    RED = "Red"
    WHITE = "White"
    ROSE = "Rosé"
    CHAMPAGNE = "Champagne"
    FORTIFIED = "Fortified"
    DESSERT = "Dessert"


class WineStatus(str, enum.Enum):
    """Lifecycle states for a bottle in the cellar."""
    IN_CELLAR = "in_cellar"
    REMOVED = "removed"
    GIFTED = "gifted"
    BROKEN = "broken"


class WindowStatus(str, enum.Enum):
    """Computed drinking-window state for a bottle relative to today."""
    TOO_YOUNG = "too_young"
    IN_WINDOW = "in_window"
    PAST_PEAK = "past_peak"
    UNKNOWN = "unknown"


class UserRole(str, enum.Enum):
    """Roles for multi-user authorization."""
    ADMIN = "admin"
    USER = "user"


class UserStatus(str, enum.Enum):
    """Access states for user accounts."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


class User(Base):
    """
    Account record for multi-user cellar access.
    The 'cellar' account is the designated root admin.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)
    role = Column(SAEnum(UserRole), default=UserRole.USER, nullable=False)
    status = Column(SAEnum(UserStatus), default=UserStatus.PENDING, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)
    last_login = Column(DateTime(timezone=True), nullable=True)

    reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class PasswordResetToken(Base):
    """
    Time-limited token for password recovery and account activation.
    """
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(128), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reset_tokens")


class Location(Base):
    """
    Level 1: The physical location hierarchy.
    Supports nested structure: Rack A → Shelf 3 → Bin 12.
    """
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)            # e.g., "Rack A"
    sub_location = Column(String, nullable=True)     # e.g., "Shelf 3"

    # Self-referencing FK for nesting (Bin 12 sits inside Shelf 3 sits inside Rack A)
    parent_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)

    # Relationship: a Location can contain many child Locations
    children = relationship(
        "Location",
        backref="parent",
        remote_side=[id]
    )

    # Relationship: a Location can hold many WineEntries
    wines = relationship("WineEntry", back_populates="location")


class WineEntry(Base):
    """
    Level 2: The permanent identity of a bottle.
    """
    __tablename__ = "wine_entries"

    id = Column(Integer, primary_key=True, index=True)
    qr_id = Column(String, unique=True, index=True, nullable=False)

    name = Column(String, nullable=True)
    vintage = Column(Integer, nullable=True)
    winery = Column(String, nullable=True)
    region = Column(String, nullable=True)
    country_of_origin = Column(String, nullable=True)
    grape_type = Column(String, nullable=True)
    color = Column(String, nullable=True)
    grape_varieties = Column(JSON, nullable=True)
    description = Column(JSON, nullable=True)
    pairing = Column(JSON, nullable=True)
    grapeminds_tasting_notes = Column(JSON, nullable=True)
    flavor_profile = Column(JSON, nullable=True)
    grapeminds_id = Column(String(64), nullable=True, index=True)

    # Sprint 2 additions
    comment = Column(String, nullable=True)
    status = Column(SAEnum(WineStatus), default=WineStatus.IN_CELLAR, nullable=False)
    photo_path = Column(String, nullable=True)       # Server-side path to the label image
    purchase_price = Column(Float, nullable=True)
    market_price = Column(Float, nullable=True)
    is_verified = Column(Boolean, default=False)  # HITL flag — only True after user confirmation

    # Relationship to Location
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
    location = relationship("Location", back_populates="wines")

    purchase_date = Column(Date, nullable=True)
    checkout_date = Column(Date, nullable=True)
    drink_from = Column(Integer, nullable=True)
    drink_until = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationship to TastingNotes (One-to-Many)
    tasting_notes = relationship(
        "TastingNote",
        back_populates="wine_entry",
        cascade="all, delete-orphan",
    )


class TastingNote(Base):
    """
    Level 3: A consumption event for a specific bottle.
    One WineEntry can have many TastingNotes (e.g., one per bottle drunk from a case).
    """
    __tablename__ = "tasting_notes"

    id = Column(Integer, primary_key=True, index=True)
    wine_entry_id = Column(Integer, ForeignKey("wine_entries.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    author_name = Column(String(64), nullable=True)

    tasting_date = Column(Date, default=datetime.date.today, nullable=False)
    notes = Column(String, nullable=True)

    # Sensory Sliders (0.0 to 1.0 scale)
    tannin = Column(Float, default=0.5)
    acidity = Column(Float, default=0.5)
    body = Column(Float, default=0.5)
    alcohol = Column(Float, default=0.5)
    fruit_intensity = Column(Float, default=0.5)

    # Sprint 2 addition: comma-separated aroma descriptors (e.g., "Oak,Cherry,Earth")
    aroma_tags = Column(String, nullable=True)

    wine_entry = relationship("WineEntry", back_populates="tasting_notes")
