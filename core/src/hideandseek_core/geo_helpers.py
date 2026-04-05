"""Shapely-to-GeoJSON conversion helpers."""

from __future__ import annotations

from geojson_pydantic import Point as GeoJSONPoint
from geojson_pydantic.geometries import Geometry as GeoJSONGeometry
from pydantic import TypeAdapter
from shapely.geometry import mapping

_geojson_adapter: TypeAdapter[GeoJSONGeometry] = TypeAdapter(GeoJSONGeometry)


def geom_or_none(geom: object) -> GeoJSONGeometry | None:
    if geom is None:
        return None
    return _geojson_adapter.validate_python(mapping(geom))  # type: ignore[arg-type]


def point_or_none(val: object) -> GeoJSONPoint | None:
    """Convert a shapely Point (or None) to a GeoJSON Point."""
    if val is None:
        return None
    return GeoJSONPoint(**mapping(val))  # type: ignore[arg-type]
