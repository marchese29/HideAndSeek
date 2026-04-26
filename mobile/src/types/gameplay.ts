/**
 * Gameplay type aliases — thin wrappers around auto-generated schema types.
 *
 * GeoJSON and SSE event types are re-aliased here so consumers can use short
 * names (e.g. `GeoJSONPoint`, `PlayerLocationDelta`) rather than the verbose
 * `components['schemas']['Point']` accessor.  The generated schema in
 * `@/api/schema.d.ts` is the single source of truth.
 *
 * Union types (QuestionEventParams, GeoJSONGeometry) are derived from schema
 * types via indexed access — they auto-update when the server adds new
 * question types or geometry variants.
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

/** GeoJSON geometry union — derived from the schema's GeometryCollection members. */
export type GeoJSONGeometry = S['GeometryCollection']['geometries'][number];

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
export type GameEndedDelta = S['GameEndedEvent'];
export type StationElectionDelta = S['StationElectionEvent'];
export type HidingZoneExpandedDelta = S['HidingZoneExpandedEvent'];
export type ProximityEscalatedDelta = S['ProximityEscalatedEvent'];
export type ProximityDeescalatedDelta = S['ProximityDeescalatedEvent'];
export type FoundClaimDelta = S['FoundClaimEvent'];
export type FoundClaimRejectedDelta = S['FoundClaimRejectedEvent'];
export type FoundClaimExpiredDelta = S['FoundClaimExpiredEvent'];
export type PhotoSubmittedDelta = S['PhotoSubmittedEvent'];
export type PhotoRejectedDelta = S['PhotoRejectedEvent'];
export type PhotoEventParams = S['PhotoEventParams'];

// ── Question Event Parameters ───────────────────────────────────────────────

/** Discriminated union of all question parameter types — derived from QuestionAskedEvent.parameters. */
export type QuestionEventParams = S['QuestionAskedEvent']['parameters'];
export type ThermometerEventParams = S['ThermometerEventParams'];

// ── Active Questions ─────────────────────────────────────────────────────────

/** Server schema extended with mobile-only fields populated from question_asked / question_answerable deltas. */
export type HiderActiveQuestion = S['HiderActiveQuestion'] & {
  /** Present from question_asked delta. Absent after SSE reconnection. */
  parameters?: QuestionEventParams;
  /** Present from question_asked delta. Absent after SSE reconnection. */
  seeker_location_start?: GeoJSONPoint;
  /** Present from question_answerable delta (thermometer only). Absent after SSE reconnection. */
  seeker_location_end?: GeoJSONPoint;
};
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

// ── Endgame Exclusions ─────────────────────────────────────────────────────

export type EndgameExclusionsResponse = S['EndgameExclusionsResponse'];
export type EndgameExclusionEntryResponse = S['EndgameExclusionEntryResponse'];

// ── Question Preview (mobile-only UI state) ─────────────────────────────────

export interface PreviewQuestion {
  question_type: string;
  slot_index: number;
  parameters: QuestionEventParams;
  custom_distance?: number;
}
