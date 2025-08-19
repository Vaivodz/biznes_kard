from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Session, create_engine


DATABASE_URL = "sqlite:///app/database.db"


class UserBase(SQLModel):
    email: str
    name: str
    role: str = Field(default="user", description="admin|user")


class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    password_hash: str


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int


class OrderBase(SQLModel):
    title: str
    description: str = ""
    status: str = Field(default="pending", description="pending|in_progress|shipped|completed|cancelled")
    deadline: datetime
    type: str = Field(default="topography", description="topography|as_built_survey|engineering_geodesy")
    cadastre_id: Optional[str] = None
    location_address: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None


class Order(OrderBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    assignee_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_by_id: Optional[int] = Field(default=None, foreign_key="user.id")


class OrderCreate(OrderBase):
    assignee_id: Optional[int] = None


class OrderUpdate(SQLModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[datetime] = None
    assignee_id: Optional[int] = None
    type: Optional[str] = None
    cadastre_id: Optional[str] = None
    location_address: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None


class NoteBase(SQLModel):
    content: str


class Note(NoteBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id")
    user_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NoteCreate(NoteBase):
    order_id: int
    user_id: int


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, echo=False)
    return _engine


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(get_engine())