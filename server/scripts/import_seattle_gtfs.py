"""Import Seattle-area transit data from the Puget Sound consolidated GTFS feed.

Downloads (or reads a local copy of) the GTFS feed, filters to target routes,
deduplicates stops, and writes TransitDataset/Route/Stop/RouteStop records.

Usage:
    cd server && uv run python scripts/import_seattle_gtfs.py
    cd server && uv run python scripts/import_seattle_gtfs.py --gtfs-path ~/Downloads/gtfs.zip
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

from shapely.geometry import LineString, Point
from sqlalchemy import select

from hideandseek.gtfs import parse_gtfs
from hideandseek_core.db import get_session, session_scope
from hideandseek_models.transit import Route, RouteStop, Stop, TransitDataset
from hideandseek_models.types import RouteType

GTFS_URL = 'https://gtfs.sound.obaweb.org/prod/gtfs_puget_sound_consolidated.zip'

# GTFS route_type: 0=tram/light rail, 2=rail, 3=bus
GTFS_ROUTE_TYPE_MAP = {
    0: RouteType.metro,  # Link light rail + streetcar
    2: RouteType.rail,  # Sounder commuter rail
    3: RouteType.bus,  # RapidRide + ST Express
}


@dataclass
class TargetRoute:
    name: str
    route_type: RouteType
    color: str


# 11 target routes: Link light rail, RapidRide BRT, ST 522, streetcars
TARGET_ROUTES: dict[str, TargetRoute] = {
    # Link Light Rail
    '100479': TargetRoute('1 Line', RouteType.metro, '28813F'),
    '2LINE': TargetRoute('2 Line', RouteType.metro, '007CAD'),
    # Sound Transit Express
    '100232': TargetRoute('Route 522', RouteType.bus, '2B376E'),
    # RapidRide
    '102576': TargetRoute('C Line', RouteType.bus, '9C182F'),
    '102581': TargetRoute('D Line', RouteType.bus, '9C182F'),
    '102615': TargetRoute('E Line', RouteType.bus, '9C182F'),
    '102619': TargetRoute('F Line', RouteType.bus, '9C182F'),
    '102736': TargetRoute('H Line', RouteType.bus, '9C182F'),
    '102745': TargetRoute('G Line', RouteType.bus, '9C182F'),
    # Streetcars
    '100340': TargetRoute('SLU Streetcar', RouteType.tram, 'F47836'),
    '102638': TargetRoute('First Hill Streetcar', RouteType.tram, 'F47836'),
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two lat/lon points."""
    r = 6_371_000
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


@dataclass
class CanonicalStop:
    stable_id: str
    name: str
    lon: float
    lat: float


def main() -> None:
    parser = argparse.ArgumentParser(description='Import Seattle GTFS transit data')
    parser.add_argument('--gtfs-path', help='Path to local GTFS zip (skips download)')
    args = parser.parse_args()

    # Check idempotency
    with session_scope():
        existing = (
            get_session()
            .scalars(select(TransitDataset).where(TransitDataset.region == 'Seattle'))
            .one_or_none()
        )
        if existing:
            print(
                f'TransitDataset for Seattle already exists (id={existing.id}). '
                'Delete the database and re-run to reimport.'
            )
            sys.exit(1)

    # Download or use local file
    if args.gtfs_path:
        zip_path = args.gtfs_path
        print(f'Using local GTFS file: {zip_path}')
    else:
        print(f'Downloading GTFS feed from {GTFS_URL}...')
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            urllib.request.urlretrieve(GTFS_URL, tmp.name)  # noqa: S310
            zip_path = tmp.name
        print(f'Downloaded to {zip_path}')

    # Parse
    print('Parsing GTFS feed...')
    feed = parse_gtfs(zip_path)
    print(
        f'  {len(feed.stops)} stops, {len(feed.routes)} routes, '
        f'{len(feed.trips)} trips, {len(feed.shapes)} shapes'
    )

    # Filter routes
    target_route_ids = set(TARGET_ROUTES.keys())

    # Build trip → route mapping for target routes
    trip_to_route: dict[str, str] = {}
    route_shape_ids: dict[str, set[str]] = defaultdict(set)
    for trip in feed.trips:
        if trip.route_id in target_route_ids:
            trip_to_route[trip.trip_id] = trip.route_id
            if trip.shape_id:
                route_shape_ids[trip.route_id].add(trip.shape_id)

    # Select best shape per route (most points)
    route_shapes: dict[str, LineString] = {}
    best_shape_id: dict[str, str] = {}
    for route_id, shape_ids in route_shape_ids.items():
        best_sid = max(shape_ids, key=lambda sid: len(feed.shapes.get(sid, [])))
        coords = feed.shapes[best_sid]
        route_shapes[route_id] = LineString(coords)
        best_shape_id[route_id] = best_sid

    # Collect used stop_ids from target trips
    used_stop_ids: set[str] = set()
    for st in feed.stop_times:
        if st.trip_id in trip_to_route:
            used_stop_ids.add(st.stop_id)

    print(f'  {len(used_stop_ids)} raw stops across {len(target_route_ids)} routes')

    # Deduplicate stops
    # Phase 1: parent station consolidation
    stop_id_mapping: dict[str, str] = {}  # original → canonical stable_id
    canonical_stops: dict[str, CanonicalStop] = {}  # stable_id → CanonicalStop

    parent_children: dict[str, list[str]] = defaultdict(list)
    parentless: list[str] = []

    for stop_id in used_stop_ids:
        stop = feed.stops.get(stop_id)
        if not stop:
            continue
        if stop.parent_station and stop.parent_station in feed.stops:
            parent_children[stop.parent_station].append(stop_id)
        else:
            parentless.append(stop_id)

    # Consolidate children under parent
    for parent_id, children in parent_children.items():
        parent = feed.stops[parent_id]
        canonical_stops[parent_id] = CanonicalStop(
            stable_id=parent_id,
            name=parent.stop_name,
            lon=parent.stop_lon,
            lat=parent.stop_lat,
        )
        for child_id in children:
            stop_id_mapping[child_id] = parent_id

    # Phase 2: same-name averaging for parentless stops
    name_groups: dict[str, list[str]] = defaultdict(list)
    for stop_id in parentless:
        stop = feed.stops[stop_id]
        name_groups[stop.stop_name].append(stop_id)

    max_distance_guard = 50.0  # meters

    for name, group_ids in name_groups.items():
        if len(group_ids) == 1:
            # Unique name — use as-is
            stop = feed.stops[group_ids[0]]
            canonical_stops[group_ids[0]] = CanonicalStop(
                stable_id=group_ids[0],
                name=name,
                lon=stop.stop_lon,
                lat=stop.stop_lat,
            )
            stop_id_mapping[group_ids[0]] = group_ids[0]
        else:
            # Multiple stops with same name — check distance
            stops = [feed.stops[sid] for sid in group_ids]
            avg_lat = sum(s.stop_lat for s in stops) / len(stops)
            avg_lon = sum(s.stop_lon for s in stops) / len(stops)

            # Check if all are within the guard distance of the average
            all_close = all(
                _haversine_m(s.stop_lat, s.stop_lon, avg_lat, avg_lon) <= max_distance_guard
                for s in stops
            )

            if all_close:
                # Merge: use first stop_id as canonical
                canonical_id = group_ids[0]
                canonical_stops[canonical_id] = CanonicalStop(
                    stable_id=canonical_id,
                    name=name,
                    lon=avg_lon,
                    lat=avg_lat,
                )
                for sid in group_ids:
                    stop_id_mapping[sid] = canonical_id
            else:
                # Too far apart — keep separate
                for sid in group_ids:
                    stop = feed.stops[sid]
                    canonical_stops[sid] = CanonicalStop(
                        stable_id=sid,
                        name=name,
                        lon=stop.stop_lon,
                        lat=stop.stop_lat,
                    )
                    stop_id_mapping[sid] = sid

    print(f'  Deduplicated to {len(canonical_stops)} canonical stops')

    # Build route-stop sequences
    # For each route, find the trip that uses the selected shape, get its stop_times
    trip_for_route: dict[str, str] = {}
    for trip in feed.trips:
        if (
            trip.route_id in target_route_ids
            and trip.shape_id == best_shape_id.get(trip.route_id)
            and trip.route_id not in trip_for_route
        ):
            trip_for_route[trip.route_id] = trip.trip_id

    route_stop_sequences: dict[str, list[str]] = {}
    for route_id, trip_id in trip_for_route.items():
        # Get stop_times for this trip, sorted by sequence
        trip_stop_times = sorted(
            [st for st in feed.stop_times if st.trip_id == trip_id],
            key=lambda st: st.stop_sequence,
        )

        # Map through dedup, deduplicate consecutive identical canonical stops
        sequence: list[str] = []
        for st in trip_stop_times:
            canonical_id = stop_id_mapping.get(st.stop_id, st.stop_id)
            if not sequence or sequence[-1] != canonical_id:
                sequence.append(canonical_id)

        route_stop_sequences[route_id] = sequence

    # Write to DB
    print('Writing to database...')
    with session_scope() as session:
        dataset = TransitDataset(
            name='Puget Sound',
            region='Seattle',
            source_url=GTFS_URL,
        )
        session.add(dataset)
        session.flush()

        # Create Stop records
        db_stops: dict[str, Stop] = {}
        for cs in canonical_stops.values():
            stop = Stop(
                stable_id=cs.stable_id,
                dataset_id=dataset.id,
                name=cs.name,
                coordinates=Point(cs.lon, cs.lat),
            )
            session.add(stop)
            db_stops[cs.stable_id] = stop
        session.flush()

        # Create Route and RouteStop records
        for route_id, target in TARGET_ROUTES.items():
            shape = route_shapes.get(route_id)
            if not shape:
                print(f'  WARNING: No shape for route {route_id} ({target.name}), skipping')
                continue

            route = Route(
                stable_id=route_id,
                dataset_id=dataset.id,
                name=target.name,
                color=target.color,
                route_type=target.route_type,
                shape=shape,
            )
            session.add(route)
            session.flush()

            stop_sequence = route_stop_sequences.get(route_id, [])
            for seq_num, canonical_id in enumerate(stop_sequence):
                db_stop = db_stops.get(canonical_id)
                if not db_stop:
                    continue
                route_stop = RouteStop(
                    route_id=route.id,
                    stop_id=db_stop.id,
                    sequence=seq_num,
                )
                session.add(route_stop)

        dataset_name = dataset.name
        dataset_region = dataset.region

    print(
        f'\nDone! Imported {len(TARGET_ROUTES)} routes and '
        f'{len(canonical_stops)} stops as dataset "{dataset_name}" '
        f'(region={dataset_region})'
    )


if __name__ == '__main__':
    main()
