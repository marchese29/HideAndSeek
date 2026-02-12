from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from hideandseek.models.types import RouteType


class TransitDataset(SQLModel, table=True):
    __tablename__ = 'transit_dataset'  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    region: str
    source_url: str | None = None
    imported_at: datetime = Field(default_factory=datetime.utcnow)

    stops: list[Stop] = Relationship(back_populates='dataset')
    routes: list[Route] = Relationship(back_populates='dataset')


class Stop(SQLModel, table=True):
    __tablename__ = 'stop'  # type: ignore[assignment]
    __table_args__ = (sa.UniqueConstraint('stable_id', 'dataset_id'),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    stable_id: str
    dataset_id: uuid.UUID = Field(foreign_key='transit_dataset.id')
    name: str
    coordinates: dict = Field(sa_type=sa.JSON)  # GeoJSON Point

    dataset: TransitDataset = Relationship(back_populates='stops')
    route_stops: list[RouteStop] = Relationship(back_populates='stop')


class Route(SQLModel, table=True):
    __tablename__ = 'route'  # type: ignore[assignment]
    __table_args__ = (sa.UniqueConstraint('stable_id', 'dataset_id'),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    stable_id: str
    dataset_id: uuid.UUID = Field(foreign_key='transit_dataset.id')
    name: str
    color: str
    route_type: RouteType
    shape: dict = Field(sa_type=sa.JSON)  # GeoJSON LineString

    dataset: TransitDataset = Relationship(back_populates='routes')
    route_stops: list[RouteStop] = Relationship(back_populates='route')


class RouteStop(SQLModel, table=True):
    __tablename__ = 'route_stop'  # type: ignore[assignment]

    route_id: uuid.UUID = Field(foreign_key='route.id', primary_key=True)
    stop_id: uuid.UUID = Field(foreign_key='stop.id', primary_key=True)
    sequence: int

    route: Route = Relationship(back_populates='route_stops')
    stop: Stop = Relationship(back_populates='route_stops')
