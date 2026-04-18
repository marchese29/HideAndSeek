/**
 * Gap-detection helper for SSE event streams.
 *
 * The server sets each event's SSE `id:` field to a monotonically increasing
 * per-channel sequence number. A client that consumes events out of order
 * (or misses one entirely — e.g. a silently dropped Redis pub/sub message)
 * detects the gap and triggers a resync by disconnecting. The next reconnect
 * delivers a fresh `game_state` snapshot, which resets the baseline.
 */

type EventWithId = { lastEventId?: string | null };

export interface SequenceTracker {
  /** Wrap an SSE listener so the handler only fires for strictly-next-in-sequence events. */
  wrap<E extends EventWithId>(handler: (event: E) => void): (event: E) => void;
  /** Clear the tracked baseline (call on connection open/error). */
  reset(): void;
}

export interface SequenceTrackerOptions {
  /** Called when a gap is detected (expected === last + 1, got something larger). */
  onGap: (info: { expected: number; got: number }) => void;
  /** Called when the event has no parseable lastEventId. Treated as a fatal decode error. */
  onInvalid: (info: { lastEventId: string | null | undefined }) => void;
  /** Called when an out-of-order (past) event arrives — logged, handler skipped. */
  onStale?: (info: { last: number; got: number }) => void;
}

export function createSequenceTracker(options: SequenceTrackerOptions): SequenceTracker {
  let lastSeq: number | null = null;

  return {
    wrap<E extends EventWithId>(handler: (event: E) => void): (event: E) => void {
      return (event: E) => {
        const raw = event.lastEventId;
        if (raw == null || raw === '') {
          options.onInvalid({ lastEventId: raw });
          return;
        }
        const seq = Number.parseInt(raw, 10);
        if (!Number.isFinite(seq)) {
          options.onInvalid({ lastEventId: raw });
          return;
        }

        if (lastSeq === null) {
          // First event of the connection establishes the baseline (normally the
          // server-sent `game_state` snapshot carrying the current channel seq).
          lastSeq = seq;
          handler(event);
          return;
        }

        if (seq === lastSeq + 1) {
          lastSeq = seq;
          handler(event);
          return;
        }

        if (seq <= lastSeq) {
          options.onStale?.({ last: lastSeq, got: seq });
          return;
        }

        // seq > lastSeq + 1 — gap detected.
        options.onGap({ expected: lastSeq + 1, got: seq });
      };
    },
    reset() {
      lastSeq = null;
    },
  };
}
