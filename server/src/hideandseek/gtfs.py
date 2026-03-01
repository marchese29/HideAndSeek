"""Reusable GTFS feed parser.

Reads standard GTFS zip files into typed dataclasses.
Pure-data module — no DB or SQLModel dependency.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field


@dataclass
class GtfsStop:
    stop_id: str
    stop_name: str
    stop_lat: float
    stop_lon: float
    parent_station: str | None


@dataclass
class GtfsRoute:
    route_id: str
    route_short_name: str
    route_long_name: str
    route_type: int
    route_color: str


@dataclass
class GtfsTrip:
    trip_id: str
    route_id: str
    shape_id: str


@dataclass
class GtfsStopTime:
    trip_id: str
    stop_id: str
    stop_sequence: int


@dataclass
class GtfsFeed:
    stops: dict[str, GtfsStop] = field(default_factory=dict)
    routes: dict[str, GtfsRoute] = field(default_factory=dict)
    shapes: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    trips: list[GtfsTrip] = field(default_factory=list)
    stop_times: list[GtfsStopTime] = field(default_factory=list)


def _read_csv(zf: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    """Read a CSV file from a zip archive, stripping BOM if present."""
    raw = zf.read(filename).decode('utf-8-sig')
    return list(csv.DictReader(io.StringIO(raw)))


def parse_gtfs(zip_path: str) -> GtfsFeed:
    """Parse a GTFS zip file into a GtfsFeed."""
    feed = GtfsFeed()

    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Stops
        for row in _read_csv(zf, 'stops.txt'):
            parent = row.get('parent_station', '').strip()
            feed.stops[row['stop_id']] = GtfsStop(
                stop_id=row['stop_id'],
                stop_name=row['stop_name'],
                stop_lat=float(row['stop_lat']),
                stop_lon=float(row['stop_lon']),
                parent_station=parent if parent else None,
            )

        # Routes
        for row in _read_csv(zf, 'routes.txt'):
            color = row.get('route_color', '').strip().lstrip('#')
            feed.routes[row['route_id']] = GtfsRoute(
                route_id=row['route_id'],
                route_short_name=row.get('route_short_name', ''),
                route_long_name=row.get('route_long_name', ''),
                route_type=int(row['route_type']),
                route_color=color,
            )

        # Shapes
        shape_points: dict[str, list[tuple[int, float, float]]] = {}
        for row in _read_csv(zf, 'shapes.txt'):
            shape_id = row['shape_id']
            seq = int(row['shape_pt_sequence'])
            lon = float(row['shape_pt_lon'])
            lat = float(row['shape_pt_lat'])
            shape_points.setdefault(shape_id, []).append((seq, lon, lat))

        for shape_id, points in shape_points.items():
            points.sort(key=lambda p: p[0])
            feed.shapes[shape_id] = [(lon, lat) for _, lon, lat in points]

        # Trips
        for row in _read_csv(zf, 'trips.txt'):
            feed.trips.append(
                GtfsTrip(
                    trip_id=row['trip_id'],
                    route_id=row['route_id'],
                    shape_id=row.get('shape_id', ''),
                )
            )

        # Stop times
        for row in _read_csv(zf, 'stop_times.txt'):
            feed.stop_times.append(
                GtfsStopTime(
                    trip_id=row['trip_id'],
                    stop_id=row['stop_id'],
                    stop_sequence=int(row['stop_sequence']),
                )
            )

    return feed
