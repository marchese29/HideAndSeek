"""ShapelyGeometry — a geoalchemy2 Geometry subclass with transparent shapely conversion."""

from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry.base import BaseGeometry

_SRID = 4326


class ShapelyGeometry(Geometry):
    """Geometry column that transparently converts between shapely and WKBElement.

    Write path: shapely object → from_shape() → WKBElement → parent bind processor → EWKT string
    Read path: raw DB value → parent result processor → WKBElement → to_shape() → shapely
    """

    cache_ok = True

    def bind_processor(self, dialect):  # type: ignore[override]  # noqa: ANN001, ANN201
        parent_processor = super().bind_processor(dialect)

        def process(value: BaseGeometry | None) -> object:
            if value is None:
                return None
            wkb = from_shape(value, srid=self.srid or _SRID)
            return parent_processor(wkb) if parent_processor else wkb

        return process

    def result_processor(self, dialect, coltype):  # noqa: ANN001, ANN201
        parent_processor = super().result_processor(dialect, coltype)

        def process(value: object) -> BaseGeometry | None:
            if value is None:
                return None
            wkb = parent_processor(value) if parent_processor else value
            if isinstance(wkb, WKBElement):
                return to_shape(wkb)
            return wkb  # type: ignore[return-value]

        return process
