"""Tests for gameplay state SSE endpoints and snapshot builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek.queries.game_state import (
    build_game_info,
    build_hider_game_state,
    build_seeker_game_state,
)
from hideandseek_core.broadcast.events import (
    QuestionAskedEvent,
    RadarEventParams,
    ThermometerEventParams,
    build_event_params,
)
from hideandseek_models.question_params import FeatureQuestionParams
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

# ── Helpers ──────────────────────────────────────────────────────────────────


def _create_active_game(session: Session) -> tuple:
    """Create a game in hiding phase with hider, seeker, and transit data.

    Returns (game, hider, seeker, transit_dataset).
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
    return game, hider, seeker, ds


# ── Hider Snapshot Tests ────────────────────────────────────────────────────


class TestBuildHiderGameState:
    """Tests for build_hider_game_state snapshot assembly."""

    def test_basic_fields(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        state = build_hider_game_state(game, hider)

        assert state.game_id == game.id
        assert state.phase == GameStatus.hiding
        assert state.hiding_started_at == game.hiding_started_at
        assert state.seeking_started_at is None
        assert state.self_player_id == hider.id
        assert state.station_election_status == StationElectionStatus.pending
        assert state.hider_station_id is None

    def test_players_with_locations(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)

        create_location_update(session, hider.id, game.id, coordinates=Point(-122.3, 47.6))
        create_location_update(session, seeker.id, game.id, coordinates=Point(-122.4, 47.7))

        state = build_hider_game_state(game, hider)

        # Hider sees all players with locations
        assert len(state.hiders) >= 1
        assert len(state.seekers) >= 1

        hider_entry = next(h for h in state.hiders if h.id == hider.id)
        assert hider_entry.coordinates is not None
        assert hider_entry.timestamp is not None

        seeker_entry = next(s for s in state.seekers if s.id == seeker.id)
        assert seeker_entry.coordinates is not None

    def test_players_without_locations(self, session: Session) -> None:
        game, hider, _seeker, _ds = _create_active_game(session)
        state = build_hider_game_state(game, hider)

        hider_entry = next(h for h in state.hiders if h.id == hider.id)
        assert hider_entry.coordinates is None
        assert hider_entry.timestamp is None

    def test_no_active_question(self, session: Session) -> None:
        game, hider, _seeker, _ds = _create_active_game(session)
        state = build_hider_game_state(game, hider)
        assert state.active_question is None
        assert state.question_history == []

    def test_active_question_with_deadline(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        answerable_at = datetime.now(UTC)
        q = create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            answerable_at=answerable_at,
            slot_index=2,
        )

        state = build_hider_game_state(game, hider)
        assert state.active_question is not None
        assert state.active_question.question_id == q.id
        assert state.active_question.asked_by == seeker.id
        assert state.active_question.slot_index == 2
        assert state.active_question.question_deadline is not None
        # DB stores UTC but may return naive — compare without timezone
        expected_deadline = answerable_at.replace(tzinfo=None) + timedelta(
            minutes=game.base_question_delay_min
        )
        actual_deadline = state.active_question.question_deadline.replace(tzinfo=None)
        assert abs((actual_deadline - expected_deadline).total_seconds()) < 1

    def test_thermometer_no_deadline_before_lockin(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            question_type=QuestionType.thermometer,
            status=QuestionStatus.in_progress,
            asked_by=seeker.id,
            answerable_at=None,
        )

        state = build_hider_game_state(game, hider)
        assert state.active_question is not None
        assert state.active_question.question_deadline is None

    def test_question_history(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            sequence=1,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='yes',
            slot_index=0,
        )
        create_question(
            session,
            game.id,
            sequence=2,
            status=QuestionStatus.vetoed,
            asked_by=seeker.id,
            answer=None,
            slot_index=1,
        )

        state = build_hider_game_state(game, hider)
        assert len(state.question_history) == 2
        assert state.question_history[0].answer == 'yes'
        assert state.question_history[1].answer is None
        assert state.question_history[1].status == QuestionStatus.vetoed

    def test_history_excludes_active_question(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            sequence=1,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='no',
        )
        create_question(
            session,
            game.id,
            sequence=2,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
        )

        state = build_hider_game_state(game, hider)
        assert len(state.question_history) == 1
        assert state.active_question is not None


# ── Static Game Info Tests ──────────────────────────────────────────────────


class TestBuildGameInfo:
    """Tests for build_game_info static snapshot assembly."""

    def test_static_fields(self, session: Session) -> None:
        game, _hider, _seeker, _ds = _create_active_game(session)
        info = build_game_info(game)

        assert info.game_id == game.id
        assert info.hiding_time_min == game.hiding_time_min
        assert info.base_question_delay_min == game.base_question_delay_min
        assert info.distance_convention == game.game_map.convention
        assert info.boundary is not None
        assert info.boundary.type == 'MultiPolygon'
        assert isinstance(info.districts, list)

    def test_stops_populated(self, session: Session) -> None:
        game, _hider, _seeker, ds = _create_active_game(session)
        create_stop(session, ds.id, coordinates=Point(0.5, 0.5), name='Central Station')

        info = build_game_info(game)
        assert len(info.stops) == 1
        assert info.stops[0].name == 'Central Station'

    def test_json_serializable(self, session: Session) -> None:
        game, _hider, _seeker, ds = _create_active_game(session)
        create_stop(session, ds.id, coordinates=Point(0.5, 0.5))

        info = build_game_info(game)
        data = info.model_dump(mode='json')
        assert isinstance(data, dict)
        assert data['game_id'] == str(game.id)
        assert 'boundary' in data
        assert 'stops' in data
        assert 'routes' in data

    def test_features_empty_by_default(self, session: Session) -> None:
        game, _hider, _seeker, _ds = _create_active_game(session)
        info = build_game_info(game)
        assert info.features == []

    def test_features_populated(self, session: Session) -> None:
        game, _hider, _seeker, _ds = _create_active_game(session)
        feat = create_map_feature(
            session,
            category=FeatureCategory.hospital,
            name='Test Hospital',
            shape=Point(0.5, 0.5),
        )
        create_game_map_feature(session, game.map_id, feat.id)

        info = build_game_info(game)
        assert len(info.features) == 1
        f = info.features[0]
        assert f.stable_id == feat.stable_id
        assert f.name == 'Test Hospital'
        assert f.category == 'hospital'
        assert f.feature_class is None
        assert f.location.type == 'Point'

    def test_features_multiple_categories(self, session: Session) -> None:
        game, _hider, _seeker, _ds = _create_active_game(session)
        feat_h = create_map_feature(session, category=FeatureCategory.hospital, name='Hospital A')
        feat_p = create_map_feature(session, category=FeatureCategory.park, name='Park B')
        create_game_map_feature(session, game.map_id, feat_h.id)
        create_game_map_feature(session, game.map_id, feat_p.id)

        info = build_game_info(game)
        assert len(info.features) == 2
        categories = [f.category for f in info.features]
        assert 'hospital' in categories
        assert 'park' in categories


# ── Seeker Snapshot Tests ───────────────────────────────────────────────────


class TestBuildSeekerGameState:
    """Tests for build_seeker_game_state snapshot assembly."""

    def test_hiders_have_no_location(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        create_location_update(session, hider.id, game.id, coordinates=Point(-122.3, 47.6))

        state = build_seeker_game_state(game, seeker)

        assert len(state.hiders) >= 1
        hider_entry = next(h for h in state.hiders if h.id == hider.id)
        # RosterPlayer has no coordinates or timestamp fields
        assert not hasattr(hider_entry, 'coordinates')
        assert not hasattr(hider_entry, 'timestamp')

    def test_seekers_have_locations(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        create_location_update(session, seeker.id, game.id, coordinates=Point(-122.4, 47.7))

        state = build_seeker_game_state(game, seeker)
        seeker_entry = next(s for s in state.seekers if s.id == seeker.id)
        assert seeker_entry.coordinates is not None

    def test_inventory_populated(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        state = build_seeker_game_state(game, seeker)

        # Game has inventory slots from create_game
        assert len(state.inventory) > 0
        slot = state.inventory[0]
        assert slot.question_type is not None
        assert slot.ask_count == 0

    def test_total_exclusion_empty(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        state = build_seeker_game_state(game, seeker)
        assert state.total_exclusion is None

    def test_seeker_active_question_no_asked_by(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            answerable_at=datetime.now(UTC),
            slot_index=0,
        )

        state = build_seeker_game_state(game, seeker)
        assert state.active_question is not None
        # SeekerActiveQuestion has no asked_by field
        assert not hasattr(state.active_question, 'asked_by')

    def test_seeker_history_has_exclusion_fields(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='yes',
        )

        state = build_seeker_game_state(game, seeker)
        assert len(state.question_history) == 1
        entry = state.question_history[0]
        # SeekerQuestionHistoryEntry has exclusion fields
        assert hasattr(entry, 'exclusion')
        assert hasattr(entry, 'total_exclusion')

    def test_self_player_id(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        state = build_seeker_game_state(game, seeker)
        assert state.self_player_id == seeker.id

    def test_json_serializable(self, session: Session) -> None:
        """Ensure the full snapshot can be serialized to JSON."""
        game, hider, seeker, ds = _create_active_game(session)
        create_stop(session, ds.id, coordinates=Point(0.5, 0.5))
        create_location_update(session, seeker.id, game.id, coordinates=Point(0.5, 0.5))
        create_question(
            session,
            game.id,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='no',
        )

        hider_state = build_hider_game_state(game, hider)
        seeker_state = build_seeker_game_state(game, seeker)

        # model_dump(mode='json') is what the SSE stream uses
        hider_data = hider_state.model_dump(mode='json')
        seeker_data = seeker_state.model_dump(mode='json')

        assert isinstance(hider_data, dict)
        assert isinstance(seeker_data, dict)
        assert hider_data['game_id'] == str(game.id)
        assert seeker_data['game_id'] == str(game.id)


# ── Enriched History Tests ─────────────────────────────────────────────────


class TestHiderHistoryEnrichment:
    """Tests for enriched fields on HiderQuestionHistoryEntry."""

    def test_answered_at_populated(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        answered_at = datetime.now(UTC)
        create_question(
            session,
            game.id,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='yes',
            answered_at=answered_at,
            hider_location=Point(-122.3, 47.6),
        )

        state = build_hider_game_state(game, hider)
        entry = state.question_history[0]
        assert entry.answered_at is not None
        assert entry.hider_location is not None
        assert entry.hider_location.type == 'Point'

    def test_hider_feature_resolution_on_matching(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.matching,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='yes',
            answered_at=datetime.now(UTC),
        )
        # create_question auto-creates RadarParams for radar only;
        # for matching we need to create FeatureQuestionParams manually
        session.add(
            FeatureQuestionParams(
                question_id=q.id,
                category=FeatureCategory.park,
                source='map_data',
                seeker_feature_id='park-1',
                seeker_feature_name='Green Park',
                seeker_distance=0.5,
                hider_feature_id='park-2',
                hider_feature_name='Blue Park',
                hider_distance=1.2,
            )
        )
        session.flush()
        session.refresh(q)

        state = build_hider_game_state(game, hider)
        entry = state.question_history[0]
        assert entry.hider_feature_id == 'park-2'
        assert entry.hider_feature_name == 'Blue Park'
        assert entry.hider_distance == 1.2

    def test_hider_resolution_null_for_radar(self, session: Session) -> None:
        game, hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='no',
        )

        state = build_hider_game_state(game, hider)
        entry = state.question_history[0]
        assert entry.hider_feature_id is None
        assert entry.hider_feature_name is None
        assert entry.hider_distance is None


class TestSeekerHistoryEnrichment:
    """Tests for enriched fields on SeekerQuestionHistoryEntry."""

    def test_answered_at_populated(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        answered_at = datetime.now(UTC)
        create_question(
            session,
            game.id,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='yes',
            answered_at=answered_at,
        )

        state = build_seeker_game_state(game, seeker)
        entry = state.question_history[0]
        assert entry.answered_at is not None

    def test_no_hider_fields(self, session: Session) -> None:
        """SeekerQuestionHistoryEntry must not expose hider-privileged data."""
        game, _hider, seeker, _ds = _create_active_game(session)
        create_question(
            session,
            game.id,
            status=QuestionStatus.answered,
            asked_by=seeker.id,
            answer='yes',
        )

        state = build_seeker_game_state(game, seeker)
        entry = state.question_history[0]
        assert not hasattr(entry, 'hider_location')
        assert not hasattr(entry, 'hider_feature_id')
        assert not hasattr(entry, 'hider_feature_name')
        assert not hasattr(entry, 'hider_distance')


# ── Event Construction Tests ───────────────────────────────────────────────


class TestQuestionAskedEvent:
    """Tests for QuestionAskedEvent.from_question() enrichment."""

    def test_enriched_fields(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        now = datetime.now(UTC)
        q = create_question(
            session,
            game.id,
            status=QuestionStatus.answerable,
            asked_by=seeker.id,
            sequence=3,
            ask_count=2,
            answerable_at=now,
        )

        event = QuestionAskedEvent.from_question(
            q, base_question_delay_min=game.base_question_delay_min
        )
        assert event.sequence == 3
        assert event.ask_count == 2
        assert event.asked_at == q.asked_at
        assert event.seeker_location_start.type == 'Point'
        assert isinstance(event.parameters, RadarEventParams)
        assert event.parameters.radius == 1.0
        assert event.question_deadline is not None
        assert q.answerable_at is not None
        assert event.question_deadline == q.answerable_at + timedelta(
            minutes=game.base_question_delay_min
        )


class TestBuildEventParams:
    """Tests for build_event_params across question types."""

    def test_radar(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        q = create_question(session, game.id, asked_by=seeker.id)
        params = build_event_params(q)
        assert isinstance(params, RadarEventParams)
        assert params.radius == 1.0

    def test_thermometer(self, session: Session) -> None:
        game, _hider, seeker, _ds = _create_active_game(session)
        q = create_question(
            session,
            game.id,
            question_type=QuestionType.thermometer,
            asked_by=seeker.id,
        )
        params = build_event_params(q)
        assert isinstance(params, ThermometerEventParams)
        assert params.min_travel == 0.5
