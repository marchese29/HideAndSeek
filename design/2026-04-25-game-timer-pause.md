# Game Timer Pause

> Status: **Draft**
> Last updated: 2026-04-25
> Corresponds to: HideAndSeek-m8r (epic), HideAndSeek-nah (photo-question consumer)
> Depends on: `2026-02-15-background-jobs.md` (reconciler + Celery split), `2026-03-29-gameplay-state.md` (gameplay SSE channels), `2026-04-21-photo-questions.md` (first consumer)

A general-purpose mechanic for freezing the seeking-phase game clock — and every clock that derives from it — without ending the phase. Engaged by features that need to "stop time" (photo questions waiting on hider review, future host-controlled pauses, future rest-period mechanics, future curses), released by the same features when the blocking condition clears.

## Implementation Cycles

1. **Models + Alembic** — pause columns on `Game`, future-dated deadline columns on `Game` / `Question` / (later) `PhotoQuestionParams`, `PauseReason` enum, backfill for in-flight games.
2. **Core: pause primitive** — `pause_game(game, reason)` / `resume_game(game, reason)` in `core/logic/pause.py`, deadline-shift fan-out, helper accessors, `GameTimerPausedEvent` / `GameTimerResumedEvent` schemas, `emit_gameplay` routing.
3. **Core: anchor-write migration** — switch every site that reads `*_started_at + duration` for deadline math to read the new deadline columns; switch every write site to stamp the new column at creation.
4. **Reconciler** — overdue queries collapse to `deadline_col <= now() AND paused_at IS NULL`.
5. **Mobile: universal affordances** — `paused` flag in `GameplayStore`, frozen timer treatment, banner host, category dispatch, disable list for "starts a new clock" actions.
6. **Photo-question wiring** (HideAndSeek-nah) — call `pause_game` on photo `submitted`, `resume_game` on every terminal/reject transition; `PhotoSubmittedEvent`'s `review_deadline` becomes a stored column.
7. **Tests** — pause/resume idempotence, multi-reason ref-counting, reconciler-respects-pause, deadline-shift correctness, photo-loop covers the rejection cycle.

Host-pause and rest-period UX are **separate epics** that consume this primitive — see § Out of Scope.

---

## 1. Motivation

The current timer model is naively wall-clock. Every clock that the reconciler fires is computed as `<start_anchor> + <duration> ≤ now()` (`core/logic/timers.py`); every client-visible deadline (`question_deadline` on question events, the hiding belt countdown, the found-claim countdown) is computed the same way from the same anchors. There is no concept of "time stopped."

Several near-term and medium-term mechanics need that concept:

- **Photo questions** (HideAndSeek-z32 / nah) — a hider can stall the seeker's clock indefinitely by submitting bad photos in a loop. The fix is to freeze the seeking clock while a photo is mid-review. Documented as deferred in `design/2026-04-21-photo-questions.md` § 10.
- **Host-controlled pause** (future) — the host calls a recess for any out-of-game reason; players need a non-dismissable modal and the host needs Resume / End controls.
- **Rest periods** (TBD design) — built-in scheduled pauses where strategizing is forbidden; auto-resume on a deadline.
- **Possibly future** — curses, on-foot challenges, negotiated truces.

The mechanism needs to be a primitive: a single feature-agnostic pair of operations that any feature can opt into. The UX layer interprets *why* the pause exists; the timing layer just freezes clocks.

---

## 2. The Future-Deadline Reframe

### Motivation for the schema shape

Two designs were considered:

**Option A — Accumulator on Game.** A `Game.accumulated_pause_duration_sec` column plus `Game.paused_at`, with all deadline math reading `<start_anchor> + accumulated + duration ± live-pause`. Rejected because a single game-wide accumulator misattributes pre-existing pauses to later-created timers (a question created at t=20 after a 5-second pause at t=10 sees `accumulated=5` despite no pause having occurred during *its* lifetime). Per-row offset snapshots fix it but spread pause-awareness across every timer-bearing model.

**Option B — Shift the anchor at resume.** Mutate `seeking_started_at` and every active question's `answerable_at` forward by the pause duration on resume. Mathematically clean (each timer gets shifted only by pauses during its own lifetime), but column names lie: `seeking_started_at` is no longer when seeking actually started after one or more pauses.

**Adopted: future-deadline reframe.** Store deadline columns (future-dated) for everything the reconciler fires. While a deadline is in the future, mutating it is honest — we haven't promised it will fire then. Once it elapses, it freezes (the row terminates and isn't read for deadline math anymore). Existing `*_started_at` / `*_at` columns stay as immutable audit timestamps; they stop being read for deadline math.

### Anchor → deadline mapping

| Today (start anchor + duration) | Reframed (future deadline) |
|---|---|
| `Game.hiding_started_at` + `hiding_time_min` | `Game.hiding_ends_at` |
| `Question.answerable_at` + `base_question_delay_min` | `Question.deadline_at` |
| `Game.found_claim_at` + `120s` | `Game.found_claim_expires_at` |
| (z32.5) `submitted_at` + `photo_review_sec` | `PhotoQuestionParams.review_deadline_at` |
| (z32.5) `answerable_at` + `photo_submit_min` | `PhotoQuestionParams.submit_deadline_at` |

The original columns stay. They retain audit value (the rulebook needs to know "when did the seeking phase actually start," not "what's the effective seeking-clock anchor after pauses"). They also remain useful for in-app history displays. The duration columns (`hiding_time_min`, `base_question_delay_min`, `photo_*_min/sec`) also stay — they're configuration for the *initial* deadline stamp at creation, plus display ("the hiding phase is 60 minutes").

`validators.py`'s "is a found-claim active?" check, currently `found_claim_at IS NOT NULL`, becomes `found_claim_expires_at IS NOT NULL`. Same semantics, the new field name encodes "live future event."

### The seeking-phase elapsed carve-out

Seeking has no natural deadline — it ends on `found` / `host_ended` / `dissolved`, never on a clock — so it can't be reframed into a future-date column. The seeking belt timer counts *up*, not down.

Solution: a single dedicated accumulator. `Game.seeking_pause_accumulated_sec: int` increments by the pause duration on each resume. Mobile's seeking belt timer reads:

```
elapsed = now - seeking_started_at
        - seeking_pause_accumulated_sec
        - (paused ? now - paused_at : 0)
```

This is the **only place** pause-aware math lives client-side, and it's purely a UI value — never consumed by the reconciler.

---

## 3. Pause Primitive

### Data model additions on `Game`

```python
paused_at: datetime | None = None             # non-null while paused
active_pause_reasons: list[str] = []          # JSON; PauseReason enum values
seeking_pause_accumulated_sec: int = 0        # carve-out for seeking elapsed
```

`active_pause_reasons` is treated as a **set** semantically — pause adds, resume removes, duplicates are no-ops. Multi-reason ref-counting falls out for free: a pause stays alive until every reason that put it there has been released. The transition from empty → non-empty stamps `paused_at`; non-empty → empty clears it and shifts deadlines.

### `PauseReason` enum (initial values)

```python
class PauseReason(StrEnum):
    photo_question_open = 'photo_question_open'   # in-scope first consumer
    host = 'host'                                  # future epic
    rest_period = 'rest_period'                    # future epic, TBD
```

The enum lives in `models/types.py` alongside `GameStatus` etc. New reasons add values without schema changes.

### Operations

```
pause_game(game, reason):
    if reason in game.active_pause_reasons: return  # idempotent
    if game.active_pause_reasons was empty:
        game.paused_at = now()
    game.active_pause_reasons.add(reason)
    emit GameTimerPausedEvent(...)

resume_game(game, reason):
    if reason not in game.active_pause_reasons: return  # idempotent
    game.active_pause_reasons.remove(reason)
    if game.active_pause_reasons is now empty:
        delta = now() - game.paused_at
        for d in [game.hiding_ends_at,
                  game.found_claim_expires_at,
                  *open_questions.deadline_at,
                  *photo_submit_deadline_at,
                  *photo_review_deadline_at]:
            if d is not None:
                d += delta
        if game.seeking_started_at is not None:
            # Carve-out semantics: the accumulator is consumed only by the
            # count-up seeking timer. Pre-seeking pauses already shift
            # hiding_ends_at; double-counting them here would make the
            # seeking timer start negative and clamp at 00:00:00 forever.
            game.seeking_pause_accumulated_sec += delta
        game.paused_at = None
        emit GameTimerResumedEvent(...)
```

Both operations are idempotent on reason and live in `core/logic/pause.py`. They're called by feature logic (e.g., `core/logic/photo.py` on submit/reject/terminal transitions) — not by routers. Routers never need to know about pause directly.

### Transaction safety

The resume path mutates several columns; the reconciler reads them in a separate transaction. Order matters:

1. Compute `delta`.
2. Shift every applicable deadline column in `game` and joined open-question rows.
3. Update `seeking_pause_accumulated_sec` — only when `seeking_started_at` is non-null (pre-seeking pauses contribute 0; the reconciler can't transition mid-pause, so the entire pause is always in one phase).
4. **Last:** clear `paused_at`.
5. Commit.

The reconciler's overdue queries filter `paused_at IS NULL`, so its visibility of the resume is atomic at the commit boundary: it either sees "still paused" (skip everything) or "unpaused with already-shifted deadlines" (fire normally). No intermediate state is observable.

By construction, every shifted deadline at resume is `>= now()`. Proof: during pause the reconciler skipped the row, so the row's deadline did not fire. At pause-start time `paused_at`, the deadline `d` was `>= paused_at`. At resume time, `d_new = d_old + (now - paused_at) >= paused_at + (now - paused_at) = now`. The new deadline is at worst due-immediately, never overdue.

### What the reconciler doesn't fire

A pause **does not** suppress its own auto-resume — the rest-period reason needs that, but it's the only carve-out. The first cut of m8r ships *without* it (rest periods are deferred). When rest-period lands, it adds:

- `Game.rest_period_ends_at: datetime | None` (future deadline column, like the others, but lives *outside* the global `paused_at IS NULL` filter).
- A fourth reconciler query: `WHERE rest_period_ends_at <= now()` (no pause filter) — fires a worker task that calls `resume_game(game, PauseReason.rest_period)`.

This is the only deadline that needs to fire while paused. All other pause reasons resolve via feature events (photo accept, host tap, etc.).

---

## 4. Reconciler

The three current overdue queries collapse from `<start_anchor> + <duration> <= now()` to `<deadline_col> <= now()`, plus the pause filter:

```python
# find_overdue_hiding_games
WHERE Game.status == hiding
  AND Game.hiding_ends_at IS NOT NULL
  AND Game.hiding_ends_at <= now()
  AND Game.paused_at IS NULL

# find_overdue_answerable_questions
WHERE Game.status == seeking
  AND Question.status == answerable
  AND Question.deadline_at IS NOT NULL
  AND Question.deadline_at <= now()
  AND Game.paused_at IS NULL

# find_overdue_found_claims
WHERE Game.status IN (hiding, seeking)
  AND Game.found_claim_expires_at IS NOT NULL
  AND Game.found_claim_expires_at <= now()
  AND Game.paused_at IS NULL
```

The cycle z32.5 follow-on adds `find_overdue_photo_submit_deadlines` and `find_overdue_photo_review_deadlines` to the same shape.

The reconciler stays poll-based at 1s tick; no scheduled-task state to manage. Pausing a game with timers in flight requires no cancellation work — the next tick simply skips the paused row.

---

## 5. Pause Categories & UX

The pause primitive is feature-agnostic. The mobile UX layer dispatches on **category**, derived from the reason set + the player's role + whether the player is host. Three structural categories:

### Category 1 — Role-targeted (banner UX)

The clock is waiting on a specific role's action. The mechanism is gameplay-natural — the role being waited on resolves the pause through the same affordance they'd use normally.

| Element | Treatment |
|---|---|
| Banner | Non-interrupting top banner naming the wait (e.g., "Paused — waiting on Alice's photo"). Persistent until resume. |
| Belt timer (count-up) | Frozen value, muted/grayscale background. |
| Active-question countdown | Frozen value, dimmed. |
| Found-claim countdown | Frozen value, dimmed (modal stays open, see Universal Affordances). |
| Waited-on role's resolving action | **Live.** This is the whole point. |
| Other role's "start a new clock" actions | **Disabled** (ask new question, initiate found-claim). |
| Other role's strategizing affordances | Live (preview endpoints, history modals, map exploration, location reporting). |

### Category 2 — Universal pause, host-initiated (modal UX)

The host has invoked a pause for an out-of-game reason. No deadline; resolution is a host action.

| Element | Treatment |
|---|---|
| Modal | Non-dismissable on every client. Title: "The host has paused the game." Body: who paused, no countdown. |
| All gameplay actions | Disabled. |
| Host's modal | Same as everyone else, but additionally exposes **Resume** and **End Game** buttons. End ends the game from this point (existing `EndReason.host_ended` path). |

### Category 3 — Universal pause, rest period (modal w/ countdown UX)

Built-in scheduled pause; auto-resume when the rest-period deadline elapses.

| Element | Treatment |
|---|---|
| Modal | Non-dismissable on every client. Body shows a countdown to auto-resume, sourced from `rest_period_ends_at`. |
| All gameplay actions | Disabled. |
| Resolution | Server-driven via reconciler firing the auto-unpause task. |

Detailed rest-period mechanics are deferred to that feature's own design doc.

### Category dispatch

Mobile derives the category from the active reason set:

- Any reason in `{host, rest_period}` present → modal (Category 2 or 3 depending on which).
- Otherwise → banner (Category 1).

Stacked pauses are possible (host invokes a pause while a photo question is mid-review). The strictest category present wins — the banner is hidden by the modal until the modal's reason clears.

### Universal affordances during any pause

These hold regardless of category:

- Belt timer color: muted/grayscale (overrides green-when-connected).
- Belt timer value (count-up): frozen.
- Question deadline countdown: frozen.
- Found-claim countdown: frozen.
- Found-claim **resolution** (confirm / reject): **live**. Resolves an existing in-flight clock; the principle "actions that resolve a clock stay live" applies. *Initiating* a new found-claim is disabled.
- Map pan/zoom, location reporting, history modals, endgame scrubber: live. Pausing the *clock* doesn't pause the *world* — other players are still moving and reporting.
- Banner / modal copy: reason-only, no elapsed-pause display (avoids anxiety; the user can't act on the duration).

### The resolution-action principle

"Actions that resolve the pause stay live; actions that start a new clock are disabled." This single rule drives the per-action decisions:

- During `photo_question_open`: the hider's photo submit/answer flow is the resolution → live. The seeker's "ask question" button starts a new clock → disabled (already disabled by the active-question gate, but pause keeps it that way).
- During a hypothetical "waiting on seeker" pause: the seeker's resolving action stays live. The hider's answer flow on a non-resolving question would freeze.
- During Category 2/3 (universal): no role-specific resolution action exists, so everything except found-claim resolution is disabled.

---

## 6. First Consumer: `photo_question_open`

The photo question lifecycle from `2026-04-21-photo-questions.md` is `asked → submitted → answered`, with reject looping `submitted → asked`. The pause envelope:

```
ask_photo: status=answerable, no pause
hider queues photo: no state change
hider submits photo: status=submitted, pause_game(game, photo_question_open)
seeker accepts: status=answered, resume_game(game, photo_question_open)
seeker rejects: status=asked, resume_game(game, photo_question_open)
review timer expires: status=answered (auto-accept), resume_game(game, photo_question_open)
```

The pause begins on `submitted`, ends on every terminal transition AND on every reject. The seeker's review window (`review_deadline_at`) is itself a paused-aware deadline — when the pause is engaged, the seeker has the full window without the seeking clock advancing.

The submit-deadline window (between `asked` and `submitted`) is **not** paused. A hider stalling there is bounded by `photo_submit_min`; the design accepts that bounded stalling. The pause exists specifically to close the unbounded reject-loop exploit.

### Mobile during `photo_question_open`

- **Seeker**: banner reads "Paused — reviewing photo from \<hider\>". The photo review modal (which already exists from cycle z32.5) stays interactive — accept, reject, view fullscreen. The "Questions" entry point on the belt was already gated by the active question; no functional change there. The frozen-timer treatment is the only new visual.
- **Hider**: banner reads "Paused — your photo is under review." Power-up affordances (currently expand-hiding-zone) are disabled — a one-shot power that's not connected to seeking-clock progress, but it's still a meta-action and shouldn't fire while time is frozen. The submit/queue/null-answer flow stays live for the case where the hider wants to swap a queued photo before the review concludes (consistent with the pre-pause queueing semantics).

The banner replaces the transient toast queue while it's active; toasts that arrive during pause are queued and shown after resume.

---

## 7. Events & Schema Additions

### New gameplay events

```python
class GameTimerPausedEvent(GameplayEventSchema):
    type: Literal['game_timer_paused'] = 'game_timer_paused'
    paused_at: datetime
    active_pause_reasons: list[PauseReason]

class GameTimerResumedEvent(GameplayEventSchema):
    type: Literal['game_timer_resumed'] = 'game_timer_resumed'
    resumed_at: datetime
    active_pause_reasons: list[PauseReason]            # empty if fully resumed
    seeking_pause_accumulated_sec: int                 # post-resume value
    hiding_ends_at: datetime | None                    # if shifted
    found_claim_expires_at: datetime | None            # if shifted
    question_deadlines: dict[uuid.UUID, datetime]      # question_id → new deadline_at
```

Both events fan out to **both** SSE channels (lobby has no use for them; these are gameplay-only). Routed by `emit_gameplay()` per the existing pattern in `core/broadcast/emit.py`.

A pause that adds a second reason while one is already active emits a `paused` event with the updated `active_pause_reasons` so mobile re-evaluates category. Removing a reason that doesn't fully empty the set emits a `paused` event (not `resumed`) with the reduced list. `resumed` only fires when the set actually transitions to empty.

### Snapshot fields

Both `HiderGameStateResponse` and `SeekerGameStateResponse` gain:

```python
paused: bool                                    # equiv to paused_at is not None
paused_at: datetime | None
active_pause_reasons: list[PauseReason]
seeking_pause_accumulated_sec: int
hiding_ends_at: datetime | None                # replaces hiding deadline math on the wire
found_claim_expires_at: datetime | None        # exposed for client countdown
```

`HiderActiveQuestion.question_deadline` and `SeekerActiveQuestion.question_deadline` already exist; they now source from `Question.deadline_at` instead of `answerable_at + base_question_delay_min`.

### Existing events that change

- `QuestionAskedEvent` and `QuestionAnswerableEvent` — `question_deadline` is now read from `Question.deadline_at` directly. The `from_question(question, *, base_question_delay_min=...)` constructor signatures lose the kwarg.
- `PhaseChangedEvent` — gains `hiding_ends_at` (nullable; only set when transitioning into hiding) so the hiding belt timer can switch to a `useCountdownTimer` with a stable future ISO.
- `PhotoSubmittedEvent` — `review_deadline` is no longer transiently computed in the router. Sourced from `PhotoQuestionParams.review_deadline_at`.

---

## 8. Mobile Changes

### Store additions (`gameplayStore.ts`)

```typescript
type GameplayState = {
  ...
  paused: boolean;
  pauseReasons: PauseReason[];
  pausedAt: string | null;
  seekingPauseAccumulatedSec: number;
  hidingEndsAt: string | null;
  foundClaimExpiresAt: string | null;
};

// New actions
applyGameTimerPaused: (delta: GameTimerPausedDelta) => void;
applyGameTimerResumed: (delta: GameTimerResumedDelta) => void;
```

`applyGameTimerResumed` walks `delta.question_deadlines` and patches `state.active_question.question_deadline` if it's in the dict (and any other places we track per-question deadlines, e.g. an open question history entry — though terminal questions don't shift).

### Hooks

- `useCountdownTimer` — unchanged; gains a `paused` argument that short-circuits the 1s tick.
- `useGameTimer` — collapses. The hiding branch becomes a `useCountdownTimer(hidingEndsAt, paused)` consumer. The seeking branch retains custom math:
  ```typescript
  const elapsedMs = Date.now()
    - parseUtc(seekingStartedAt)
    - seekingPauseAccumulatedSec * 1000
    - (paused ? Date.now() - parseUtc(pausedAt!) : 0);
  ```
  Plus the same `paused` short-circuit on the tick (no need to re-render once per second when frozen).

### New components

- `<PauseBanner />` — top-of-screen non-interrupting banner, reason-driven copy, persistent. Shown when `paused && !isUniversalCategory(reasons)`. Replaces the toast host visually while active (toasts queue underneath until resume).
- `<PauseModal />` — non-dismissable modal, dispatches sub-views by reason:
  - `host` → "The host has paused the game." Plus Resume / End Game for the host (own-id check against `host_player_id`).
  - `rest_period` → countdown to `rest_period_ends_at` (future cycle).
  Shown when `paused && isUniversalCategory(reasons)`. Mounts inside `app/game/[game_id].tsx` next to `<FoundClaimModal />`.

### Disable matrix

A small `usePauseDisable()` hook returns a discriminator object:
```typescript
{
  asking: boolean;       // can ask a new question
  initiateClaim: boolean; // can POST /found
  powers: boolean;       // hider power-ups
  resolution: 'photo' | 'claim' | null; // which resolution action stays live
}
```

Components consume the relevant flag rather than each one re-deriving from the reason set.

### What doesn't change

- Map rendering, location tracking (foreground + background), all SSE event handlers besides the two new ones, history modals, endgame scrubber, lobby flow.
- The toast store.
- TanStack Query caches.

---

## 9. Open Questions / Future Work

1. **Hiding-phase pause** — out of scope. Hiding is a fixed countdown with no in-flight question state; nothing in scope today needs to freeze it. The schema supports it for free (`hiding_ends_at` shifts on resume) — a future feature can opt in without migration.
2. **Found-claim pause edge cases** — if a pause begins while a found-claim is mid-flight, the claim's `found_claim_expires_at` shifts on resume so the seeker doesn't lose review window. Confirm/reject buttons stay live during the pause (resolution action). If host pauses *while* a claim is mid-flight, the universal modal supersedes the claim modal visually, but the underlying state survives.
3. **Toast behavior during pause** — first cut: queue toasts during pause, flush on resume. Open question whether some toast classes should still display through a pause (e.g., proximity-tier changes the hider needs to know about right away). Defer until we see it in practice.
4. **`PauseReason` extensibility cost** — every new reason adds a string to the enum and a banner copy decision. No schema change. Categories are derived in mobile, not the server, so server-side additions don't require a category column.
5. **Rest period mechanics** — full design deferred. Likely shape: `Game.rest_period_ends_at`, a fourth reconciler query unfiltered by `paused_at`, an auto-unpause Celery task.
6. **Host pause epic** — separate epic. Plan-task placeholder filed under the m8r umbrella so the work doesn't get lost.

---

## 10. Out of Scope

- Per-player freezing (the endgame hider freeze is self-contained, not a clock-pause mechanic).
- Manual host pause UX (separate epic).
- Rest period mechanics (separate epic).
- Pausing during hiding phase (no current need).
- Pause initiation by mobile (today's only initiator is server-side feature logic; the host-pause epic adds a route).
