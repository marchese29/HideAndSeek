"""Shapely-transparent column types for PostGIS Geometry and Geography.

Write path: shapely object → from_shape() → WKBElement → parent bind processor → EWKT string
Read path: raw DB value → parent result processor → WKBElement → to_shape() → shapely
"""

from __future__ import annotations

from collections.abc import Callable

from geoalchemy2 import Geography, Geometry, WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy.engine.interfaces import Dialect

_SRID = 4326


class _ShapelyProcessors:
    """Mixin that adds transparent shapely ↔ WKBElement conversion to any spatial type."""

    srid: int  # provided by Geometry / Geography

    def _shapely_bind(
        self,
        parent_processor: Callable[..., object] | None,
    ) -> Callable[[BaseGeometry | None], object]:
        def process(value: BaseGeometry | None) -> object:
            if value is None:
                return None
            wkb = from_shape(value, srid=self.srid or _SRID)
            return parent_processor(wkb) if parent_processor else wkb

        return process

    def _shapely_result(
        self,
        parent_processor: Callable[..., object] | None,
    ) -> Callable[[object], BaseGeometry | None]:
        def process(value: object) -> BaseGeometry | None:
            if value is None:
                return None
            result = parent_processor(value) if parent_processor else value
            if isinstance(result, WKBElement):
                return to_shape(result)
            return result  # type: ignore[return-value]

        return process


class ShapelyGeometry(_ShapelyProcessors, Geometry):
    """Geometry column with transparent shapely conversion.

    Use for topological operations (ST_Contains, ST_Covers on exclusion zones).
    """

    cache_ok = True

    def bind_processor(  # type: ignore[override]
        self,
        dialect: Dialect,
    ) -> Callable[[BaseGeometry | None], object]:
        return self._shapely_bind(Geometry.bind_processor(self, dialect))

    def result_processor(  # type: ignore[override]
        self,
        dialect: Dialect,
        coltype: object,
    ) -> Callable[[object], BaseGeometry | None]:
        return self._shapely_result(Geometry.result_processor(self, dialect, coltype))


class ShapelyGeography(_ShapelyProcessors, Geography):
    """Geography column with transparent shapely conversion.

    Use for distance/proximity columns — ST_Distance, ST_DWithin, ST_Buffer
    return meters natively without explicit casts.
    """

    cache_ok = True

    def bind_processor(  # type: ignore[override]
        self,
        dialect: Dialect,
    ) -> Callable[[BaseGeometry | None], object]:
        return self._shapely_bind(Geography.bind_processor(self, dialect))

    def result_processor(  # type: ignore[override]
        self,
        dialect: Dialect,
        coltype: object,
    ) -> Callable[[object], BaseGeometry | None]:
        return self._shapely_result(Geography.result_processor(self, dialect, coltype))
