/**
 * Gameplay SSE state types — manually defined because the server SSE endpoints
 * use include_in_schema=False (not in the OpenAPI spec or schema.d.ts).
 *
 * These mirror server/src/hideandseek/schemas/response.py and params.py.
 * UUIDs, datetimes, and enums are represented as strings (wire types).
 */

// ── GeoJSON ──────────────────────────────────────────────────────────────────

export interface GeoJSONPoint {
  type: 'Point';
  coordinates: [number, number];
}

export interface GeoJSONPolygon {
  type: 'Polygon';
  coordinates: number[][][];
}

export interface GeoJSONLineString {
  type: 'LineString';
  coordinates: [number, number][];
}

export interface GeoJSONMultiLineString {
  type: 'MultiLineString';
  coordinates: [number, number][][];
}

export interface GeoJSONMultiPolygon {
  type: 'MultiPolygon';
  coordinates: number[][][][];
}

/** Flexible GeoJSON geometry for exclusion zones (Polygon, MultiPolygon, etc.) */
export type GeoJSONGeometry = Record<string, unknown>;

// ── Players ──────────────────────────────────────────────────────────────────

/** A player with optional location — visible to roles that can see this player. */
export interface GamePlayer {
  id: string;
  name: string;
  color: string;
  role: 'hider' | 'seeker' | null;
  coordinates: GeoJSONPoint | null;
  timestamp: string | null;
}

/** A player in the roster — identity only, no location fields. */
export interface RosterPlayer {
  id: string;
  name: string;
  color: string;
  role: 'hider' | 'seeker' | null;
}

// ── SSE Delta Events ────────────────────────────────────────────────────────

/** Wire format of a player_location SSE delta event. */
export interface PlayerLocationDelta {
  id: string;
  name: string;
  color: string;
  role: 'hider' | 'seeker';
  coordinates: GeoJSONPoint;
  timestamp: string;
}

// ── Question Event Parameters ───────────────────────────────────────────────

export interface RadarEventParams {
  radius: number;
}

export interface ThermometerEventParams {
  min_travel: number;
}

export interface FeatureEventParams {
  category: string;
  feature_class: number | null;
  source: string;
  seeker_feature_id: string;
  seeker_feature_name: string;
  seeker_distance: number;
}

export type QuestionEventParams = RadarEventParams | ThermometerEventParams | FeatureEventParams;

// ── Question SSE Delta Events ───────────────────────────────────────────────

/** Wire format of a question_asked SSE delta event. */
export interface QuestionAskedDelta {
  question_id: string;
  question_type: string;
  status: string;
  asked_by: string;
  slot_index: number;
  parameters: QuestionEventParams;
  seeker_location_start: GeoJSONPoint;
  asked_at: string;
  ask_count: number;
  sequence: number;
  question_deadline: string | null;
}

/** Wire format of a question_answerable SSE delta event (thermometer lock-in). */
export interface QuestionAnswerableDelta {
  question_id: string;
  question_type: string;
  status: string;
  seeker_location_end: GeoJSONPoint;
  question_deadline: string;
}

/** Wire format of a question_answered SSE delta event (hider channel). */
export interface HiderQuestionAnsweredDelta {
  question_id: string;
  question_type: string;
  status: string;
  answer: string;
  slot_index: number;
  asked_by: string;
  answered_at: string | null;
  hider_location: GeoJSONPoint | null;
  hider_feature_id: string | null;
  hider_feature_name: string | null;
  hider_distance: number | null;
}

/** Wire format of a question_answered SSE delta event (seeker channel). */
export interface SeekerQuestionAnsweredDelta {
  question_id: string;
  question_type: string;
  status: string;
  answer: string;
  slot_index: number;
  asked_by: string;
  exclusion: GeoJSONGeometry | null;
  total_exclusion: GeoJSONGeometry | null;
  answered_at: string | null;
}

/** Wire format of a question_vetoed SSE delta event. */
export interface QuestionVetoedDelta {
  question_id: string;
  question_type: string;
  slot_index: number;
}

/** Wire format of a question_abandoned SSE delta event. */
export interface QuestionAbandonedDelta {
  question_id: string;
  question_type: string;
  slot_index: number;
}

// ── Question Preview (populated by selection UI) ────────────────────────────

/** Seeker preview state — set by question selection UI, read by banner. */
export interface PreviewQuestion {
  question_type: string;
  slot_index: number;
  parameters: QuestionEventParams;
  custom_distance?: number;
}

// ── Stops ────────────────────────────────────────────────────────────────────

export interface StopResponse {
  id: string;
  stable_id: string;
  name: string;
  coordinates: GeoJSONPoint;
}

// ── Routes ──────────────────────────────────────────────────────────────────

export interface RouteResponse {
  id: string;
  stable_id: string;
  name: string;
  color: string;
  route_type: string;
  shape: GeoJSONLineString | GeoJSONMultiLineString;
  stop_ids: string[];
}

// ── Question Parameters ──────────────────────────────────────────────────────

export interface RadarParamsResponse {
  type: 'radar';
  radius: number;
}

export interface ThermometerParamsResponse {
  type: 'thermometer';
  min_travel: number;
}

export interface FeatureResolution {
  feature_id: string;
  name: string;
  distance: number;
}

export interface FeatureParamsResponse {
  type: 'matching' | 'measuring';
  category: string;
  feature_class: number | null;
  source: string;
  seeker_resolution: FeatureResolution;
  hider_resolution: FeatureResolution | null;
}

export type QuestionParamsResponse =
  | RadarParamsResponse
  | ThermometerParamsResponse
  | FeatureParamsResponse;

// ── Active Questions ─────────────────────────────────────────────────────────

export interface HiderActiveQuestion {
  question_id: string;
  question_type: string;
  status: string;
  asked_by: string;
  slot_index: number;
  question_deadline: string | null;
}

export interface SeekerActiveQuestion {
  question_id: string;
  question_type: string;
  status: string;
  slot_index: number;
  question_deadline: string | null;
  /** Present from question_asked delta for thermometer questions. Absent after SSE reconnection. */
  parameters?: QuestionEventParams;
  /** Present from question_asked delta for thermometer questions. Absent after SSE reconnection. */
  seeker_location_start?: GeoJSONPoint;
}

// ── Question History ─────────────────────────────────────────────────────────

export interface HiderQuestionHistoryEntry {
  question_id: string;
  sequence: number;
  question_type: string;
  status: string;
  ask_count: number;
  asked_by: string;
  asked_at: string;
  slot_index: number;
  parameters: QuestionParamsResponse;
  seeker_location_start: GeoJSONPoint;
  seeker_location_end: GeoJSONPoint | null;
  answer: string | null;
  answered_at: string | null;
  hider_location: GeoJSONPoint | null;
  hider_feature_id: string | null;
  hider_feature_name: string | null;
  hider_distance: number | null;
}

export interface SeekerQuestionHistoryEntry {
  question_id: string;
  sequence: number;
  question_type: string;
  status: string;
  ask_count: number;
  asked_by: string;
  asked_at: string;
  slot_index: number;
  answer: string | null;
  exclusion: GeoJSONGeometry | null;
  total_exclusion: GeoJSONGeometry | null;
  answered_at: string | null;
}

// ── Phase Transition ────────────────────────────────────────────────────────

export interface PhaseChangedDelta {
  phase: string;
  seeking_started_at: string;
  station_election_status: string;
  hider_station_id: string | null;
}

// ── Inventory ────────────────────────────────────────────────────────────────

export interface InventorySlotResponse {
  question_type: string;
  slot_index: number;
  distance: number | null;
  category: string | null;
  feature_class: number | null;
  ask_count: number;
}

// ── Game State Snapshots ─────────────────────────────────────────────────────

export interface HiderGameState {
  game_id: string;
  phase: string;
  hiding_time_min: number;
  hiding_started_at: string | null;
  seeking_started_at: string | null;
  base_question_delay_min: number;
  distance_convention: string;
  boundary: GeoJSONPolygon;
  districts: unknown[];
  stops: StopResponse[];
  routes: RouteResponse[];
  self_player_id: string;
  host_player_id: string;
  hiders: GamePlayer[];
  seekers: GamePlayer[];
  station_election_status: string;
  hider_station_id: string | null;
  active_question: HiderActiveQuestion | null;
  question_history: HiderQuestionHistoryEntry[];
}

export interface SeekerGameState {
  game_id: string;
  phase: string;
  hiding_time_min: number;
  hiding_started_at: string | null;
  seeking_started_at: string | null;
  base_question_delay_min: number;
  distance_convention: string;
  boundary: GeoJSONPolygon;
  districts: unknown[];
  stops: StopResponse[];
  routes: RouteResponse[];
  self_player_id: string;
  host_player_id: string;
  hiders: RosterPlayer[];
  seekers: GamePlayer[];
  active_question: SeekerActiveQuestion | null;
  question_history: SeekerQuestionHistoryEntry[];
  total_exclusion: GeoJSONGeometry | null;
  inventory: InventorySlotResponse[];
}

// ── Player / Game Lifecycle Deltas ──────────────────────────────────────────

export interface PlayerLeftDelta {
  player_id: string;
}

export interface HostChangedDelta {
  new_host_player_id: string;
}

export interface GameDissolvedDelta {
  reason: string;
}
