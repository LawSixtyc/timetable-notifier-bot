from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrackedGroup(Base):
    __tablename__ = "tracked_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    ruz_group_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    faculty_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    faculty_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    study_form: Mapped[str | None] = mapped_column(String(50), nullable=True)
    degree: Mapped[str | None] = mapped_column(String(50), nullable=True)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", "tracked_group_id", name="uq_user_tracked_group"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tracked_group_id: Mapped[int] = mapped_column(ForeignKey("tracked_groups.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduleSnapshot(Base):
    __tablename__ = "schedule_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_group_id: Mapped[int] = mapped_column(ForeignKey("tracked_groups.id"), index=True)
    week_start: Mapped[Date] = mapped_column(Date, index=True)
    week_end: Mapped[Date] = mapped_column(Date, index=True)
    hash: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_group_id: Mapped[int] = mapped_column(ForeignKey("tracked_groups.id"), index=True)
    old_hash: Mapped[str] = mapped_column(String(64))
    new_hash: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())