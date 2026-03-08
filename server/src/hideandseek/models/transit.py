from __future__ import annotations

import uuid
from datetime import UTC, datetime

from shapely.geometry import LineString, Point
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hideandseek.models.base import Base
from hideandseek.models.geo_types import ShapelyGeography
from hideandseek.models.types import RouteType


class TransitDataset(Base):
    __tablename__ = 'transit_dataset'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    region: Mapped[str]
    source_url: Mapped[str | None] = mapped_column(default=None)
    imported_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    stops: Mapped[list[Stop]] = relationship(back_populates='dataset')
    routes: Mapped[list[Route]] = relationship(back_populates='dataset')


class Stop(Base):
    __tablename__ = 'stop'
    __table_args__ = (UniqueConstraint('stable_id', 'dataset_id'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stable_id: Mapped[str]
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('transit_dataset.id'))
    name: Mapped[str]
    coordinates: Mapped[Point] = mapped_column(ShapelyGeography('POINT', srid=4326))

    dataset: Mapped[TransitDataset] = relationship(back_populates='stops')
    route_stops: Mapped[list[RouteStop]] = relationship(back_populates='stop')


class Route(Base):
    __tablename__ = 'route'
    __table_args__ = (UniqueConstraint('stable_id', 'dataset_id'),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stable_id: Mapped[str]
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('transit_dataset.id'))
    name: Mapped[str]
    color: Mapped[str]
    route_type: Mapped[RouteType]
    shape: Mapped[LineString] = mapped_column(ShapelyGeography('LINESTRING', srid=4326))

    dataset: Mapped[TransitDataset] = relationship(back_populates='routes')
    route_stops: Mapped[list[RouteStop]] = relationship(back_populates='route')


class RouteStop(Base):
    __tablename__ = 'route_stop'

    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('route.id'), primary_key=True)
    stop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('stop.id'), primary_key=True)
    sequence: Mapped[int] = mapped_column(primary_key=True)

    route: Mapped[Route] = relationship(back_populates='route_stops')
    stop: Mapped[Stop] = relationship(back_populates='route_stops')
