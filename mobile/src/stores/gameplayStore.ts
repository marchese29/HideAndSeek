import { create } from 'zustand';

import type {
  GamePlayer,
  GeoJSONPoint,
  HiderActiveQuestion,
  HiderGameState,
  HiderQuestionAnsweredDelta,
  HiderQuestionHistoryEntry,
  PhaseChangedDelta,
  PreviewQuestion,
  QuestionAnswerableDelta,
  QuestionAskedDelta,
  SeekerActiveQuestion,
  SeekerGameState,
  SeekerQuestionAnsweredDelta,
  SeekerQuestionHistoryEntry,
  StationElectionDelta,
} from '@/types/gameplay';

interface SelfLocation {
  coordinates: GeoJSONPoint;
  timestamp: string;
}

type GameplayData =
  | { status: 'connecting'; role?: undefined; state?: undefined }
  | { status: 'connected'; role: 'hider'; state: HiderGameState }
  | { status: 'connected'; role: 'seeker'; state: SeekerGameState };

interface GameplayActions {
  hydrate: (role: 'hider' | 'seeker', data: HiderGameState | SeekerGameState) => void;
  reset: () => void;
  updateSelfLocation: (coordinates: GeoJSONPoint, timestamp: string) => void;
  updatePlayerLocation: (playerId: string, coordinates: GeoJSONPoint, timestamp: string) => void;
  setActiveQuestion: (delta: QuestionAskedDelta) => void;
  updateQuestionAnswerable: (delta: QuestionAnswerableDelta) => void;
  clearActiveQuestion: () => void;
  applyQuestionAnswered: (delta: HiderQuestionAnsweredDelta | SeekerQuestionAnsweredDelta) => void;
  applyPhaseChanged: (delta: PhaseChangedDelta) => void;
  setPreviewQuestion: (preview: PreviewQuestion | null) => void;
  updateCandidateStations: (candidates: string[] | null) => void;
  applyStationElection: (delta: StationElectionDelta) => void;
  removePlayer: (playerId: string) => void;
  setHostPlayerId: (hostPlayerId: string) => void;
}

type GameplayStore = GameplayData & {
  selfLocation: SelfLocation | null;
  previewQuestion: PreviewQuestion | null;
} & GameplayActions;

const initialState: GameplayData & {
  selfLocation: SelfLocation | null;
  previewQuestion: PreviewQuestion | null;
} = {
  status: 'connecting',
  selfLocation: null,
  previewQuestion: null,
};

/** Shallow-compare two string arrays (or nulls). */
function candidatesEqual(a: string[] | null, b: string[] | null): boolean {
  if (a === b) return true;
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/** Remove a player from an array by ID. Returns the same reference if not found. */
function withoutPlayer<T extends { id: string }>(players: T[], playerId: string): T[] {
  const filtered = players.filter((p) => p.id !== playerId);
  return filtered.length === players.length ? players : filtered;
}

/** Patch a single player's coordinates in a GamePlayer array. */
function patchPlayer(
  players: GamePlayer[],
  playerId: string,
  coordinates: GeoJSONPoint,
  timestamp: string,
): GamePlayer[] {
  let changed = false;
  const result = players.map((p) => {
    if (p.id !== playerId) return p;
    changed = true;
    return { ...p, coordinates, timestamp };
  });
  return changed ? result : players;
}

/**
 * Find the self player's timestamp from a freshly hydrated state snapshot.
 * Searches both hiders and seekers arrays for the self_player_id.
 */
function findSelfTimestamp(
  role: 'hider' | 'seeker',
  data: HiderGameState | SeekerGameState,
): string | null {
  const allPlayers: GamePlayer[] =
    role === 'hider' ? [...(data as HiderGameState).hiders, ...data.seekers] : data.seekers;

  const self = allPlayers.find((p) => p.id === data.self_player_id);
  return self?.timestamp ?? null;
}

/** Build a hider history entry from asked + answered delta data. */
function buildHiderHistoryEntry(
  asked: HiderActiveQuestion,
  delta: HiderQuestionAnsweredDelta,
): HiderQuestionHistoryEntry {
  return {
    question_id: delta.question_id,
    sequence: 0, // Not available from deltas; corrected on next hydrate
    question_type: delta.question_type,
    status: delta.status,
    ask_count: 0, // Not available from deltas; corrected on next hydrate
    asked_by: delta.asked_by,
    asked_at: '', // Not available from deltas; corrected on next hydrate
    slot_index: delta.slot_index,
    parameters: { type: 'radar', radius: 0 } as never, // Placeholder; corrected on next hydrate
    seeker_location_start: { type: 'Point', coordinates: [0, 0] },
    seeker_location_end: null,
    answer: delta.answer,
    answered_at: delta.answered_at,
    hider_location: delta.hider_location,
    hider_feature_id: delta.hider_feature_id,
    hider_feature_name: delta.hider_feature_name,
    hider_distance: delta.hider_distance,
  };
}

/** Build a seeker history entry from asked + answered delta data. */
function buildSeekerHistoryEntry(
  asked: SeekerActiveQuestion,
  delta: SeekerQuestionAnsweredDelta,
): SeekerQuestionHistoryEntry {
  return {
    question_id: delta.question_id,
    sequence: 0,
    question_type: delta.question_type,
    status: delta.status,
    ask_count: 0,
    asked_by: delta.asked_by,
    asked_at: '',
    slot_index: delta.slot_index,
    answer: delta.answer,
    exclusion: delta.exclusion,
    total_exclusion: delta.total_exclusion,
    answered_at: delta.answered_at,
  };
}

export const useGameplayStore = create<GameplayStore>()((set) => ({
  ...initialState,

  hydrate: (role, data) => {
    set((prev) => {
      // Clear selfLocation if SSE has caught up
      let selfLocation = prev.selfLocation;
      if (selfLocation) {
        const sseTimestamp = findSelfTimestamp(role, data);
        if (sseTimestamp && sseTimestamp >= selfLocation.timestamp) {
          selfLocation = null;
        }
      }

      if (role === 'hider') {
        return {
          status: 'connected',
          role: 'hider',
          state: data as HiderGameState,
          selfLocation,
          previewQuestion: null,
        };
      }
      return {
        status: 'connected',
        role: 'seeker',
        state: data as SeekerGameState,
        selfLocation,
        previewQuestion: null,
      };
    });
  },

  reset: () => set({ ...initialState }),

  updateSelfLocation: (coordinates, timestamp) => {
    set({ selfLocation: { coordinates, timestamp } });
  },

  updatePlayerLocation: (playerId, coordinates, timestamp) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;

      if (prev.role === 'hider') {
        const state = prev.state;
        const hiders = patchPlayer(state.hiders, playerId, coordinates, timestamp);
        const seekers = patchPlayer(state.seekers, playerId, coordinates, timestamp);
        if (hiders === state.hiders && seekers === state.seekers) return prev;
        return { ...prev, state: { ...state, hiders, seekers } };
      }

      // Seeker state: hiders is RosterPlayer[] (no coordinates), only patch seekers
      const state = prev.state;
      const seekers = patchPlayer(state.seekers, playerId, coordinates, timestamp);
      if (seekers === state.seekers) return prev;
      return { ...prev, state: { ...state, seekers } };
    });
  },

  setActiveQuestion: (delta) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;

      if (prev.role === 'hider') {
        const activeQuestion: HiderActiveQuestion = {
          question_id: delta.question_id,
          question_type: delta.question_type,
          status: delta.status,
          asked_by: delta.asked_by,
          slot_index: delta.slot_index,
          question_deadline: delta.question_deadline,
        };
        return {
          ...prev,
          state: { ...prev.state, active_question: activeQuestion },
          previewQuestion: null,
        };
      }

      const activeQuestion: SeekerActiveQuestion = {
        question_id: delta.question_id,
        question_type: delta.question_type,
        status: delta.status,
        slot_index: delta.slot_index,
        question_deadline: delta.question_deadline,
        parameters: delta.parameters,
        seeker_location_start: delta.seeker_location_start,
      };
      // Update ask_count on the matching inventory slot
      const inventory = prev.state.inventory.map((slot) =>
        slot.question_type === delta.question_type && slot.slot_index === delta.slot_index
          ? { ...slot, ask_count: delta.ask_count }
          : slot,
      );
      return {
        ...prev,
        state: { ...prev.state, active_question: activeQuestion, inventory },
        previewQuestion: null,
      };
    });
  },

  updateQuestionAnswerable: (delta) => {
    set((prev) => {
      if (prev.status !== 'connected' || !prev.state.active_question) return prev;

      if (prev.role === 'hider') {
        const activeQuestion: HiderActiveQuestion = {
          ...prev.state.active_question,
          status: delta.status,
          question_deadline: delta.question_deadline,
        };
        return { ...prev, state: { ...prev.state, active_question: activeQuestion } };
      }

      const activeQuestion: SeekerActiveQuestion = {
        ...prev.state.active_question,
        status: delta.status,
        question_deadline: delta.question_deadline,
      };
      return { ...prev, state: { ...prev.state, active_question: activeQuestion } };
    });
  },

  clearActiveQuestion: () => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;
      if (prev.role === 'hider') {
        return { ...prev, state: { ...prev.state, active_question: null }, previewQuestion: null };
      }
      return { ...prev, state: { ...prev.state, active_question: null }, previewQuestion: null };
    });
  },

  applyQuestionAnswered: (delta) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;

      if (prev.role === 'hider') {
        const state = prev.state;
        const hiderDelta = delta as HiderQuestionAnsweredDelta;
        const history = state.active_question
          ? [...state.question_history, buildHiderHistoryEntry(state.active_question, hiderDelta)]
          : state.question_history;
        return {
          ...prev,
          state: { ...state, active_question: null, question_history: history },
        };
      }

      const seekerDelta = delta as SeekerQuestionAnsweredDelta;
      const history = prev.state.active_question
        ? [
            ...prev.state.question_history,
            buildSeekerHistoryEntry(prev.state.active_question, seekerDelta),
          ]
        : prev.state.question_history;
      return {
        ...prev,
        state: {
          ...prev.state,
          active_question: null,
          question_history: history,
          total_exclusion: seekerDelta.total_exclusion ?? prev.state.total_exclusion,
        },
      };
    });
  },

  applyPhaseChanged: (delta) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;
      if (prev.role === 'hider') {
        return {
          ...prev,
          state: {
            ...prev.state,
            phase: delta.phase,
            seeking_started_at: delta.seeking_started_at,
            station_election_status: delta.station_election_status,
            hider_station_id: delta.hider_station_id,
          },
        };
      }
      return {
        ...prev,
        state: {
          ...prev.state,
          phase: delta.phase,
          seeking_started_at: delta.seeking_started_at,
        },
      };
    });
  },

  setPreviewQuestion: (preview) => {
    set({ previewQuestion: preview });
  },

  updateCandidateStations: (candidates) => {
    set((prev) => {
      if (prev.status !== 'connected' || prev.role !== 'hider') return prev;
      if (candidatesEqual(prev.state.candidate_stations, candidates)) return prev;
      return { ...prev, state: { ...prev.state, candidate_stations: candidates } };
    });
  },

  applyStationElection: (delta) => {
    set((prev) => {
      if (prev.status !== 'connected' || prev.role !== 'hider') return prev;
      const elected =
        delta.station_election_status === 'elected' ||
        delta.station_election_status === 'auto_assigned';
      return {
        ...prev,
        state: {
          ...prev.state,
          station_election_status: delta.station_election_status,
          hider_station_id: delta.hider_station_id,
          candidate_stations: elected ? null : prev.state.candidate_stations,
        },
      };
    });
  },

  removePlayer: (playerId) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;

      if (prev.role === 'hider') {
        const state = prev.state;
        const hiders = withoutPlayer(state.hiders, playerId);
        const seekers = withoutPlayer(state.seekers, playerId);
        if (hiders === state.hiders && seekers === state.seekers) return prev;
        return { ...prev, state: { ...state, hiders, seekers } };
      }

      const state = prev.state;
      const hiders = withoutPlayer(state.hiders, playerId);
      const seekers = withoutPlayer(state.seekers, playerId);
      if (hiders === state.hiders && seekers === state.seekers) return prev;
      return { ...prev, state: { ...state, hiders, seekers } };
    });
  },

  setHostPlayerId: (hostPlayerId) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;

      if (prev.role === 'hider') {
        return { ...prev, state: { ...prev.state, host_player_id: hostPlayerId } };
      }
      return { ...prev, state: { ...prev.state, host_player_id: hostPlayerId } };
    });
  },
}));
