/**
 * Gameplay type aliases — thin wrappers around auto-generated schema types.
 *
 * GeoJSON and SSE event types are re-aliased here so consumers can use short
 * names (e.g. `GeoJSONPoint`, `PlayerLocationDelta`) rather than the verbose
 * `components['schemas']['Point']` accessor.  The generated schema in
 * `@/api/schema.d.ts` is the single source of truth.
 *
 * `PreviewQuestion` is mobile-only (UI state, no server counterpart).
 */

import type { components } from '@/api/schema';

type S = components['schemas'];

// ── GeoJSON ──────────────────────────────────────────────────────────────────

export type GeoJSONPoint = S['Point'];
export type GeoJSONPolygon = S['Polygon'];
export type GeoJSONLineString = S['LineString'];
export type GeoJSONMultiLineString = S['MultiLineString'];
export type GeoJSONMultiPolygon = S['MultiPolygon'];

/** Flexible GeoJSON geometry (Polygon, MultiPolygon, etc.) */
export type GeoJSONGeometry = Record<string, unknown>;

// ── Players ──────────────────────────────────────────────────────────────────

export type GamePlayer = S['GamePlayer'];
export type RosterPlayer = S['RosterPlayer'];

// ── SSE Delta Events ────────────────────────────────────────────────────────

export type PlayerLocationDelta = S['PlayerLocationEvent'];
export type QuestionAskedDelta = S['QuestionAskedEvent'];
export type QuestionAnswerableDelta = S['QuestionAnswerableEvent'];
export type HiderQuestionAnsweredDelta = S['HiderQuestionAnsweredEvent'];
export type SeekerQuestionAnsweredDelta = S['SeekerQuestionAnsweredEvent'];
export type QuestionVetoedDelta = S['QuestionVetoedEvent'];
export type QuestionAbandonedDelta = S['QuestionAbandonedEvent'];
export type PhaseChangedDelta = S['PhaseChangedEvent'];
export type PlayerLeftDelta = S['GamePlayerLeftEvent'];
export type HostChangedDelta = S['GameHostChangedEvent'];
export type GameDissolvedDelta = S['GameDissolvedEvent'];

// ── Question Event Parameters ───────────────────────────────────────────────

export type RadarEventParams = S['RadarEventParams'];
export type ThermometerEventParams = S['ThermometerEventParams'];
export type FeatureEventParams = S['FeatureEventParams'];
export type TentacleEventParams = S['TentacleEventParams'];
export type QuestionEventParams =
  | RadarEventParams
  | ThermometerEventParams
  | FeatureEventParams
  | TentacleEventParams;

// ── Question Parameters (history entries) ───────────────────────────────────

export type RadarParamsResponse = S['RadarParamsResponse'];
export type ThermometerParamsResponse = S['ThermometerParamsResponse'];
export type FeatureParamsResponse = S['FeatureParamsResponse'];
export type TentacleParamsResponse = S['TentacleParamsResponse'];
export type FeatureResolution = S['FeatureResolution'];
export type QuestionParamsResponse =
  | RadarParamsResponse
  | ThermometerParamsResponse
  | FeatureParamsResponse
  | TentacleParamsResponse;

// ── Active Questions ─────────────────────────────────────────────────────────

export type HiderActiveQuestion = S['HiderActiveQuestion'];
/** Server schema extended with mobile-only fields populated from question_asked delta. */
export type SeekerActiveQuestion = S['SeekerActiveQuestion'] & {
  /** Present from question_asked delta for thermometer questions. Absent after SSE reconnection. */
  parameters?: QuestionEventParams;
  /** Present from question_asked delta for thermometer questions. Absent after SSE reconnection. */
  seeker_location_start?: GeoJSONPoint;
};

// ── Question History ─────────────────────────────────────────────────────────

export type HiderQuestionHistoryEntry = S['HiderQuestionHistoryEntry'];
export type SeekerQuestionHistoryEntry = S['SeekerQuestionHistoryEntry'];

// ── Stops & Routes ──────────────────────────────────────────────────────────

export type StopResponse = S['StopResponse'];
export type RouteResponse = S['RouteResponse'];

// ── Inventory ───────────────────────────────────────────────────────────────

export type InventorySlotResponse = S['InventorySlotResponse'];

// ── Static Game Info ────────────────────────────────────────────────────────

export type GameInfo = S['GameInfoResponse'];

// ── Game State Snapshots ─────────────────────────────────────────────────────

export type HiderGameState = S['HiderGameStateResponse'];
export type SeekerGameState = S['SeekerGameStateResponse'];

// ── Question Preview ────────────────────────────────────────────────────────

export type TentaclePOIPreviewResponse = S['TentaclePOIPreviewResponse'];

// ── Question Preview (mobile-only UI state) ─────────────────────────────────

export interface PreviewQuestion {
  question_type: string;
  slot_index: number;
  parameters: QuestionEventParams;
  custom_distance?: number;
}
