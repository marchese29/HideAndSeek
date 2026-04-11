"""Tests for enriched hider location events and game state snapshot."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import patch

import fakeredis
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek.queries.game_state import build_hider_game_state
from hideandseek_core.logic.answer import (
    preview_answer,
    preview_matching,
    preview_measuring,
    preview_radar,
    preview_tentacles,
    preview_thermometer,
)
from hideandseek_core.logic.station import compute_candidate_station_ids, compute_not_in_zone
from hideandseek_models.question_params import FeatureQuestionParams, TentacleQuestionParams
from hideandseek_models.types import (
    FeatureCategory,
    GameStatus,
    PlayerColor,
    PlayerRole,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)
from tests.conftest import (
    TEST_SECRET,
    create_game,
    create_game_map,
    create_game_map_feature,
    create_location_update,
    create_map_feature,
    create_player,
    create_question,
    create_stop,
    create_transit_dataset,
)


def _headers(player_id: uuid.UUID) -> dict[str, str]:
    return {'X-Player-Id': str(player_id), 'X-Player-Secret': TEST_SECRET}


def _point(lng: float = 0.5, lat: float = 0.5) -> dict:
    return {'type': 'Point', 'coordinates': [lng, lat]}


# Stop at (0.5, 0.5), hider within ~110m at (0.501, 0.5).
# Default medium metric hiding zone radius = 500m ≈ 0.0045° at equator.
# So 0.001° ≈ 111m is well within 500m.
STOP_COORDS = Point(0.5, 0.5)
HIDER_NEAR_STOP = Point(0.501, 0.5)  # ~111m from stop — inside 500m zone
HIDER_FAR_FROM_STOP = Point(0.51, 0.5)  # ~1110m from stop — outside 500m zone


@pytest.fixture(autouse=True)
def _patch_redis_for_emit() -> Generator[None, None, None]:
    server = fakeredis.FakeServer()
    fake = fakeredis.FakeRedis(server=server)
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake):
        yield


def _create_game_with_stop(session: Session) -> tuple:
    """Create a hiding-phase game with a stop and hider + seeker.

    Returns (game, hider, seeker, stop).
    """
    ds = create_transit_dataset(session)
    gm = create_game_map(session, transit_dataset_id=ds.id)
    game = create_game(
        session,
        map_id=gm.id,
        status=GameStatus.hiding,
        hiding_started_at=datetime.now(UTC),
    )
    hider = create_player(
        session, game.id, name='Alice', role=PlayerRole.hider, color=PlayerColor.green
    )
    seeker = create_player(
        session, game.id, name='Bob', role=PlayerRole.seeker, color=PlayerColor.blue
    )
    stop = create_stop(session, ds.id, coordinates=STOP_COORDS)
    return game, hider, seeker, stop


# ── compute_candidate_station_ids ──────────────────────────────────────────


class TestComputeCandidateStationIds:
    def test_hider_near_stop_returns_candidate(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        create_location_update(session, hider.id, game.id, coordinates=HIDER_NEAR_STOP)

        candidates = compute_candidate_station_ids(game)
        assert stop.id in candidates

    def test_hider_far_from_stop_returns_empty(self, session: Session) -> None:
        game, hider, _seeker, _stop = _create_game_with_stop(session)
        create_location_update(session, hider.id, game.id, coordinates=HIDER_FAR_FROM_STOP)

        candidates = compute_candidate_station_ids(game)
        assert candidates == []

    def test_no_hider_locations_returns_empty(self, session: Session) -> None:
        game, _hider, _seeker, _stop = _create_game_with_stop(session)
        candidates = compute_candidate_station_ids(game)
        assert candidates == []

    def test_two_hiders_both_near(self, session: Session) -> None:
        game, hider1, _seeker, stop = _create_game_with_stop(session)
        hider2 = create_player(
            session, game.id, name='Charlie', role=PlayerRole.hider, color=PlayerColor.purple
        )
        create_location_update(session, hider1.id, game.id, coordinates=HIDER_NEAR_STOP)
        create_location_update(session, hider2.id, game.id, coordinates=Point(0.502, 0.5))

        candidates = compute_candidate_station_ids(game)
        assert stop.id in candidates

    def test_two_hiders_one_far(self, session: Session) -> None:
        game, hider1, _seeker, stop = _create_game_with_stop(session)
        hider2 = create_player(
            session, game.id, name='Charlie', role=PlayerRole.hider, color=PlayerColor.purple
        )
        create_location_update(session, hider1.id, game.id, coordinates=HIDER_NEAR_STOP)
        create_location_update(session, hider2.id, game.id, coordinates=HIDER_FAR_FROM_STOP)

        candidates = compute_candidate_station_ids(game)
        assert stop.id not in candidates


# ── compute_not_in_zone ───────────────────────────────────────────────────


class TestComputeNotInZone:
    def test_all_in_zone(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        session.flush()

        create_location_update(session, hider.id, game.id, coordinates=HIDER_NEAR_STOP)

        result = compute_not_in_zone(game)
        assert result == []

    def test_hider_outside_zone(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        session.flush()

        create_location_update(session, hider.id, game.id, coordinates=HIDER_FAR_FROM_STOP)

        result = compute_not_in_zone(game)
        assert hider.id in result

    def test_mixed_in_and_out(self, session: Session) -> None:
        game, hider1, _seeker, stop = _create_game_with_stop(session)
        hider2 = create_player(
            session, game.id, name='Charlie', role=PlayerRole.hider, color=PlayerColor.purple
        )
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        session.flush()

        create_location_update(session, hider1.id, game.id, coordinates=HIDER_NEAR_STOP)
        create_location_update(session, hider2.id, game.id, coordinates=HIDER_FAR_FROM_STOP)

        result = compute_not_in_zone(game)
        assert hider1.id not in result
        assert hider2.id in result

    def test_no_station_returns_empty(self, session: Session) -> None:
        game, hider, _seeker, _stop = _create_game_with_stop(session)
        create_location_update(session, hider.id, game.id, coordinates=HIDER_FAR_FROM_STOP)

        result = compute_not_in_zone(game)
        assert result == []


# ── Preview answer functions ──────────────────────────────────────────────


class TestPreviewRadar:
    def test_inside_radius(self, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        q = create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
        )
        # Default radar radius is 1.0 (metric convention → 1.0m → very small)
        # But the default radar params have radius=1.0 in convention units.
        # For metric, to_meters(1.0, metric) = 1.0m. So hider at same point = inside.
        hider_loc = Point(0.5, 0.5)
        assert preview_radar(q, hider_loc, game) == 'yes'

    def test_outside_radius(self, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        q = create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
        )
        # 0.001° ≈ 111m — well outside 1m radar radius
        hider_loc = Point(0.501, 0.5)
        assert preview_radar(q, hider_loc, game) == 'no'


class TestPreviewThermometer:
    def test_closer(self, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.thermometer,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
            seeker_location_end=Point(0.501, 0.5),
        )
        # Hider at (0.502, 0.5) — closer to end (0.501) than start (0.5)
        hider_loc = Point(0.502, 0.5)
        assert preview_thermometer(q, hider_loc) == 'closer'

    def test_farther(self, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.thermometer,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
            seeker_location_end=Point(0.501, 0.5),
        )
        # Hider at (0.49, 0.5) — farther from end (0.501) than start (0.5)
        hider_loc = Point(0.49, 0.5)
        assert preview_thermometer(q, hider_loc) == 'farther'


class TestPreviewMatching:
    def test_same_feature(self, session: Session) -> None:
        ds = create_transit_dataset(session)
        gm = create_game_map(session, transit_dataset_id=ds.id)
        # Create a feature near (0.5, 0.5)
        feat = create_map_feature(
            session,
            category=FeatureCategory.hospital,
            stable_id='hosp-1',
            name='Central Hospital',
            shape=Point(0.5, 0.5),
        )
        create_game_map_feature(session, gm.id, feat.id)
        game = create_game(
            session,
            map_id=gm.id,
            status=GameStatus.seeking,
            seeking_started_at=datetime.now(UTC),
        )
        seeker = create_player(session, game.id, role=PlayerRole.seeker, color=PlayerColor.blue)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.matching,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
        )
        session.add(
            FeatureQuestionParams(
                question_id=q.id,
                category=FeatureCategory.hospital,
                source='map_data',
                seeker_feature_id='hosp-1',
                seeker_feature_name='Central Hospital',
                seeker_distance=0.0,
            )
        )
        session.flush()
        session.refresh(q)

        # Hider at same location → resolves to same feature
        assert preview_matching(q, Point(0.5, 0.5), game) == 'yes'

    def test_different_feature(self, session: Session) -> None:
        ds = create_transit_dataset(session)
        gm = create_game_map(session, transit_dataset_id=ds.id)
        feat1 = create_map_feature(
            session,
            category=FeatureCategory.hospital,
            stable_id='hosp-1',
            name='Hospital A',
            shape=Point(0.5, 0.5),
        )
        feat2 = create_map_feature(
            session,
            category=FeatureCategory.hospital,
            stable_id='hosp-2',
            name='Hospital B',
            shape=Point(0.6, 0.5),
        )
        create_game_map_feature(session, gm.id, feat1.id)
        create_game_map_feature(session, gm.id, feat2.id)
        game = create_game(
            session,
            map_id=gm.id,
            status=GameStatus.seeking,
            seeking_started_at=datetime.now(UTC),
        )
        seeker = create_player(session, game.id, role=PlayerRole.seeker, color=PlayerColor.blue)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.matching,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
        )
        session.add(
            FeatureQuestionParams(
                question_id=q.id,
                category=FeatureCategory.hospital,
                source='map_data',
                seeker_feature_id='hosp-1',
                seeker_feature_name='Hospital A',
                seeker_distance=0.0,
            )
        )
        session.flush()
        session.refresh(q)

        # Hider near hospital B → different feature
        assert preview_matching(q, Point(0.6, 0.5), game) == 'no'


class TestPreviewMeasuring:
    def test_seeker_closer(self, session: Session) -> None:
        ds = create_transit_dataset(session)
        gm = create_game_map(session, transit_dataset_id=ds.id)
        feat = create_map_feature(
            session,
            category=FeatureCategory.hospital,
            stable_id='hosp-1',
            name='Central Hospital',
            shape=Point(0.5, 0.5),
        )
        create_game_map_feature(session, gm.id, feat.id)
        game = create_game(
            session,
            map_id=gm.id,
            status=GameStatus.seeking,
            seeking_started_at=datetime.now(UTC),
        )
        seeker = create_player(session, game.id, role=PlayerRole.seeker, color=PlayerColor.blue)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.measuring,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
        )
        session.add(
            FeatureQuestionParams(
                question_id=q.id,
                category=FeatureCategory.hospital,
                source='map_data',
                seeker_feature_id='hosp-1',
                seeker_feature_name='Central Hospital',
                seeker_distance=0.0,  # seeker is at the hospital
            )
        )
        session.flush()
        session.refresh(q)

        # Hider far from hospital → seeker closer
        assert preview_measuring(q, Point(0.6, 0.5), game) == 'closer'


class TestPreviewTentacles:
    def test_miss_outside_distance(self, session: Session) -> None:
        ds = create_transit_dataset(session)
        gm = create_game_map(
            session,
            transit_dataset_id=ds.id,
            tentacle_categories=[{'category': 'museum', 'distance': 500}],
        )
        feat = create_map_feature(
            session,
            category=FeatureCategory.museum,
            stable_id='museum-1',
            name='Art Museum',
            shape=Point(0.5, 0.5),
        )
        create_game_map_feature(session, gm.id, feat.id)
        game = create_game(
            session,
            map_id=gm.id,
            status=GameStatus.seeking,
            seeking_started_at=datetime.now(UTC),
        )
        seeker = create_player(session, game.id, role=PlayerRole.seeker, color=PlayerColor.blue)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.tentacles,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
        )
        # Replace default tentacle params with real ones
        tp = session.get(TentacleQuestionParams, q.id)
        assert tp is not None
        tp.poi_ids = ['museum-1']
        tp.poi_names = ['Art Museum']
        session.flush()
        session.refresh(q)

        # Hider far from seeker — outside 500m tentacle distance
        hider_loc = Point(0.51, 0.5)  # ~1110m
        assert preview_tentacles(q, hider_loc, game) == 'miss'

    def test_empty_pois_returns_miss(self, session: Session) -> None:
        ds = create_transit_dataset(session)
        gm = create_game_map(
            session,
            transit_dataset_id=ds.id,
            tentacle_categories=[{'category': 'museum', 'distance': 500}],
        )
        game = create_game(
            session,
            map_id=gm.id,
            status=GameStatus.seeking,
            seeking_started_at=datetime.now(UTC),
        )
        seeker = create_player(session, game.id, role=PlayerRole.seeker, color=PlayerColor.blue)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.tentacles,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
        )
        # Default tentacles params have empty poi_ids
        assert preview_tentacles(q, Point(0.5, 0.5), game) == 'miss'


class TestPreviewAnswer:
    def test_dispatches_to_radar(self, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        q = create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
        )
        assert preview_answer(q, Point(0.5, 0.5), game) == 'yes'

    def test_dispatches_to_thermometer(self, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.thermometer,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
            seeker_location_end=Point(0.501, 0.5),
        )
        assert preview_answer(q, Point(0.502, 0.5), game) == 'closer'


# ── Location endpoint enrichment ──────────────────────────────────────────


class TestLocationEnrichment:
    def test_hider_hiding_pending_includes_candidate_stations(
        self, client: TestClient, session: Session
    ) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        resp = client.post(
            f'/games/{game.id}/location',
            json={'coordinates': _point(0.501, 0.5), 'timestamp': '2026-02-11T10:00:00Z'},
            headers=_headers(hider.id),
        )
        assert resp.status_code == 204

    def test_seeker_location_returns_204(self, client: TestClient, session: Session) -> None:
        game, _hider, seeker, _stop = _create_game_with_stop(session)
        game.status = GameStatus.seeking
        game.seeking_started_at = datetime.now(UTC)
        session.flush()

        resp = client.post(
            f'/games/{game.id}/location',
            json={'coordinates': _point(0.5, 0.5), 'timestamp': '2026-02-11T10:00:00Z'},
            headers=_headers(seeker.id),
        )
        assert resp.status_code == 204


# ── Game state snapshot enrichment ─────────────────────────────────────────


class TestHiderGameStateEnrichment:
    def test_pending_election_includes_candidates(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        create_location_update(session, hider.id, game.id, coordinates=HIDER_NEAR_STOP)

        state = build_hider_game_state(game, hider)
        assert state.candidate_stations is not None
        assert stop.id in state.candidate_stations
        assert state.not_in_zone is None
        assert state.computed_answer is None

    def test_elected_station_includes_not_in_zone(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        session.flush()

        create_location_update(session, hider.id, game.id, coordinates=HIDER_FAR_FROM_STOP)

        state = build_hider_game_state(game, hider)
        assert state.candidate_stations is None
        assert state.not_in_zone is not None
        assert hider.id in state.not_in_zone
        assert state.computed_answer is None

    def test_elected_all_in_zone(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        session.flush()

        create_location_update(session, hider.id, game.id, coordinates=HIDER_NEAR_STOP)

        state = build_hider_game_state(game, hider)
        assert state.not_in_zone == []

    def test_answerable_question_includes_computed_answer(self, session: Session) -> None:
        game, hider, seeker, stop = _create_game_with_stop(session)
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        game.status = GameStatus.seeking
        game.seeking_started_at = datetime.now(UTC)
        session.flush()

        create_location_update(session, hider.id, game.id, coordinates=Point(0.5, 0.5))
        create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            seeker_location_start=Point(0.5, 0.5),
            answerable_at=datetime.now(UTC),
        )

        state = build_hider_game_state(game, hider)
        assert state.computed_answer is not None
        # Hider at same spot as seeker, radar radius 1m → 'yes'
        assert state.computed_answer == 'yes'

    def test_non_answerable_question_no_computed_answer(self, session: Session) -> None:
        game, hider, seeker, stop = _create_game_with_stop(session)
        game.hider_station_id = stop.id
        game.station_election_status = StationElectionStatus.elected
        game.status = GameStatus.seeking
        game.seeking_started_at = datetime.now(UTC)
        session.flush()

        create_location_update(session, hider.id, game.id, coordinates=Point(0.5, 0.5))
        create_question(
            session,
            game.id,
            status=QuestionStatus.in_progress,
            asked_by=seeker.id,
            question_type=QuestionType.thermometer,
        )

        state = build_hider_game_state(game, hider)
        assert state.computed_answer is None

    def test_no_hider_locations_empty_candidates(self, session: Session) -> None:
        game, hider, _seeker, _stop = _create_game_with_stop(session)
        state = build_hider_game_state(game, hider)
        assert state.candidate_stations == []

    def test_json_serializable_with_enrichment(self, session: Session) -> None:
        game, hider, _seeker, stop = _create_game_with_stop(session)
        create_location_update(session, hider.id, game.id, coordinates=HIDER_NEAR_STOP)

        state = build_hider_game_state(game, hider)
        data = state.model_dump(mode='json')
        assert isinstance(data['candidate_stations'], list)
        assert str(stop.id) in data['candidate_stations']
