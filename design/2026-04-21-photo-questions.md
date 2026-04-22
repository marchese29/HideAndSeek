# Photo Questions

> Status: **Draft**
> Last updated: 2026-04-21
> Depends on: `2026-04-04-question-flow-mobile.md` (belt takeover, Question Banner), `2026-04-19-aws-deployment.md` (AWS infra)
> Corresponds to: HideAndSeek-z32

A new question type where the seeker requests a photo of a specific subject (tree, building, sign, etc.), the hider uploads an image from their camera roll, and the seekers accept or reject the submission. **Photo questions are structurally disjoint from every existing question type**: the answer is a binary blob instead of a geometry-deriving string, there is no exclusion zone, and resolution is a multi-step async flow (ask → submit → review) instead of a single atomic "answer."

The strategic value is qualitative, not geometric. A photo of a grocery store aisle, a widest street, or a tallest-building-in-sightline lets seekers reason about urban density, terrain, signage, and architecture in ways no existing question can. The flip side: seekers cannot shrink their search area via a map overlay — they have to interpret.

---

## 1. Mechanic

**"Send a photo of [subject]."**

1. **Ask** (seeker) — picks a subject from the game's photo inventory. No location preview, no boundary line.
2. **Submit** (hider) — opens the system photo picker (iOS/Android native), selects an image, then chooses to submit immediately or queue it for auto-submission at the deadline. They can also submit a *null* answer ("can't photograph this from my position"), which is a legitimate game outcome.
3. **Review** (seeker) — once the photo arrives, the seekers have a short window to accept or reject. Auto-accept on timeout. On reject, the question loops back to step 2.

The hider never uses a built-in camera — external blurring/editing is part of the rulebook, and rolling our own tooling for that is scope creep. Using the system picker means hiders can edit in whatever app they like before submitting.

### Why this question type is distinctive

- **Binary-blob answer.** The "answer" is an image stored in S3, referenced by a GUID. The existing `Question.answer: str | None` column holds the object key.
- **No new exclusion geometry.** `Question.exclusion` is always `NULL` for photo questions. `Question.total_exclusion` is carried forward from the prior question via the existing null-exclusion handler (same path used by `unclear` / null-answer outcomes). The map overlay doesn't change on resolution, but the running-total stays correct.
- **Multi-phase async flow.** Radar is instant; thermometer has two phases; photo has three (ask → submit → review) and any phase can timeout.
- **First question type that can fail to answer.** If the hider submits nothing and nothing is queued, the submit timer expires with no answer. Handled short-term by marking `abandoned`; long-term by a future game-timer-pause mechanic (separate bead).
- **First question type requiring blob storage.** Adds an S3 bucket to the infra stack.

---

## 2. Subject Vocabulary

Fixed enum. Each subject has a minimum map size — subjects are unlocked as the playable area grows.

| Subject | Min size |
|---|---|
| `tree` | small |
| `sky` | small |
| `selfie` | small |
| `widest_street` | small |
| `tallest_structure_in_sightline` | small |
| `any_building_from_station` | small |
| `tallest_building_from_station` | medium |
| `nearest_street_trace` | medium |
| `two_buildings` | medium |
| `restaurant_interior` | medium |
| `train_platform` | medium |
| `park` | medium |
| `grocery_aisle` | medium |
| `place_of_worship` | medium |
| `half_mile_streets_traced` | large |
| `tallest_mountain_from_station` | large |
| `biggest_body_of_water` | large |
| `five_buildings` | large |

Labels (for display) and min-size gates are code-level constants — no DB storage, no rulebook text on the wire. The physical rulebook is the source of truth for *how* to take the photo; the app only enforces *what* subject is asked.

```python
class PhotoSubject(StrEnum):
    tree = 'tree'
    sky = 'sky'
    selfie = 'selfie'
    # ... (full list above)

PHOTO_SUBJECT_META: dict[PhotoSubject, PhotoSubjectMeta] = {
    PhotoSubject.tree: PhotoSubjectMeta(label='A Tree', min_size=MapSize.small),
    PhotoSubject.sky: PhotoSubjectMeta(label='The Sky', min_size=MapSize.small),
    # ...
}

def subjects_for_size(size: MapSize) -> list[PhotoSubject]:
    """Return subjects whose min_size is ≤ the given map size."""
```

### Availability

Subject availability is derived from `Game.size` (the game-level size override, per the existing convention). No per-map config, no JSON column on `GameMap`. This is simpler than tentacles' `tentacle_categories` because photo subjects are universal: any geography has buildings, streets, sky, etc. `MapSize.special` is never user-selectable for gameplay (422), so it does not gate subjects.

---

## 3. Lifecycle

States and transitions:

- `asked` → `submitted`: hider commits a photo (or null answer).
- `submitted` → `answered`: seeker accepts (or auto-accept on review timer expiry).
- `submitted` → `asked`: seeker rejects; submit timer resets to a fresh window.
- `asked` → `abandoned`: submit timer expires with no queued photo.
- Any non-terminal state → `vetoed` / `randomized` / `abandoned`: standard powerup or seeker-abandon actions.

Rejection loops a photo question back to `asked`. The slot is **not** re-consumed — the same `Question` row stays alive, `params.photo_object_key` / `submitted_at` / `submitted_by` are nulled out, and a new submit deadline is scheduled. The ask is only "consumed" on terminal transition.

### Statuses

New `QuestionStatus` value:

- `submitted` — hider has committed a photo; seekers are reviewing.

Reused:

- `asked` — initial state; hider is browsing for a photo. Photo questions skip `answerable`/`in_progress` — they are immediately actionable.
- `answered` — terminal, on accept (seeker action or auto-accept).
- `abandoned` — terminal, on submit-timer expiry with no queued photo.
- `vetoed` / `randomized` — terminal, as with any question type.

### Timers

Two new game-level timer columns (both with size-based defaults, matching the existing `hiding_time_min` / `base_question_delay_min` pattern):

| Column | Unit | Default | Meaning |
|---|---|---|---|
| `Game.photo_submit_min` | minutes | 10 (S/M), 20 (L) | Max time from `asked` to `submitted` |
| `Game.photo_review_sec` | seconds | 30 | Max time from `submitted` to accept/reject |

`photo_review_sec` is in seconds because 30s is the expected scale — seekers should act quickly. Defaults follow the existing three-level fallback: request → map → code default. `GameMap` gains two optional columns for map-level overrides (`default_photo_submit_min`, `default_photo_review_sec`).

### Queue semantics

The "queue" affordance is a UX convenience — the hider picks a photo but defers the actual submission to the submit-deadline. The **backend does not distinguish queued from picked**: both states have `params.photo_object_key` populated and `submitted_at` null. When the submit-timer fires:

- If `params.photo_object_key` (or `is_null_answer`) is populated → auto-submit (transition to `submitted`, schedule review timer).
- Otherwise → mark as `abandoned`.

This piggybacks on the existing reconciler-driven auto-answer pattern — the submit-deadline is a new overdue-timer dimension, but the mechanism is identical.

The hider can swap the queued photo freely before the deadline. Replacing the photo uploads a new object to S3; the old key is orphaned (kept forever per §10).

Seekers have no visibility into the queue state. They see `asked` then `submitted` — no `queued` intermediate.

---

## 4. Data Model

### 4.1 Enums

**`QuestionType`** — add `photo`:

```python
class QuestionType(StrEnum):
    radar = 'radar'
    thermometer = 'thermometer'
    matching = 'matching'
    measuring = 'measuring'
    tentacles = 'tentacles'
    photo = 'photo'  # new
```

**`QuestionStatus`** — add `submitted`.

**`PhotoSubject`** — the 18-value fixed vocabulary (§2).

**`PhotoReviewDecision`**:

```python
class PhotoReviewDecision(StrEnum):
    accepted = 'accepted'
    rejected = 'rejected'
    auto_accepted = 'auto_accepted'
```

### 4.2 Tables

**`PhotoQuestionParams`** — one-to-one with `Question`:

```python
class PhotoQuestionParams(Base):
    __tablename__ = 'photo_question_params'

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('question.id'), primary_key=True)
    subject: Mapped[PhotoSubject]
    photo_object_key: Mapped[str | None] = mapped_column(default=None)
    is_null_answer: Mapped[bool] = mapped_column(default=False)
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('player.id'), default=None
    )
    review_decision: Mapped[PhotoReviewDecision | None] = mapped_column(default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey('player.id'), default=None
    )

    question: Mapped[Question] = relationship(back_populates='photo_params')
```

- `photo_object_key` is the S3 object key (UUID string). `NULL` means no photo selected yet.
- `is_null_answer` is true when the hider explicitly declared "can't photograph this." Submissions are either photo or null; the flag distinguishes the two.
- `submitted_at` transitioning non-null advances the question from `asked` to `submitted`.
- On reject, the loop-back nulls `photo_object_key` / `is_null_answer` / `submitted_at` / `submitted_by` but leaves `reviewed_*` untouched — those reflect the *last* review. A full audit trail would require a separate `photo_review_history` table; deferred.

**`Question`** — new relationship:

```python
photo_params: Mapped[PhotoQuestionParams | None] = relationship(
    back_populates='question',
    uselist=False,
)
```

**`Game`** — new timer columns:

```python
photo_submit_min: Mapped[int | None] = mapped_column(default=None)
photo_review_sec: Mapped[int | None] = mapped_column(default=None)
```

Nullable because defaults cascade from map → code via `effective_photo_submit_min(game)` / `effective_photo_review_sec(game)` helpers (pattern matches `effective_hiding_zone_radius_m`).

**`GameMap`** — optional defaults:

```python
default_photo_submit_min: Mapped[int | None] = mapped_column(default=None)
default_photo_review_sec: Mapped[int | None] = mapped_column(default=None)
```

### 4.3 Inventory

One `InventorySlot` per available photo subject at game creation. Slots are re-askable (`ask_count` increments on each ask) — same pattern as radar / thermometer / tentacles.

```python
InventorySlot(
    question_type=QuestionType.photo,
    slot_index=...,
    photo_subject=PhotoSubject.tree,
)
```

`InventorySlot` gains a nullable `photo_subject: PhotoSubject | None` column. `conventions.get_default_inventory` expands to include one photo slot per subject available at the game's size.

---

## 5. S3 Storage

### 5.1 Bucket

One regional S3 bucket, `hideandseek-photos-<env>`, managed by the CDK `DataStack`. Fully private — no public read, no presigned URLs, no CloudFront in front of it. All access flows through the server as a proxy.

- **Lifecycle:** none for now. Photos are kept forever. Cleanup is a separate future bead.
- **Versioning:** off.
- **Encryption:** SSE-S3 (AWS-managed keys). Sufficient for hobby scale.
- **IAM:** the app task role gets `s3:GetObject` + `s3:PutObject` + `s3:DeleteObject` on `arn:aws:s3:::hideandseek-photos-<env>/*`. No public policy.

### 5.2 Object keys

```
<env>/<game_id>/<uuid4>.jpg
```

The `game_id` prefix helps manual debugging and enables future per-game lifecycle rules. The `<env>` prefix keeps local/dev/prod objects separable if they ever share a bucket.

MIME type is validated on upload: JPEG and PNG only. No re-encoding, no EXIF stripping — the native photo picker produces reasonable sizes, and a transform pipeline is scope creep. If photo sizes become a problem, that's a future optimization.

No max upload size for now. The native picker produces reasonable sizes and this is a hobby-scale friend-group game; bounding bytes is scope creep until someone's upload actually hurts us.

### 5.3 Upload and fetch

Both routes proxied through the server. No presigned URLs.

**Upload / submit** — `POST /games/{game_id}/questions/{question_id}/photo`

A single endpoint covers both photo upload and null answer — one transition ("the hider committed something"), one route. Dispatch by content type:

- *Photo path* (multipart/form-data):
  - `file`: image bytes (JPEG or PNG).
  - `submit`: `'true'` | `'false'` — `true` means "submit now," `false` means "queue for auto-submit at deadline."
- *Null path* (application/json): `{"null": true}` — an implicit "submit=true." Queueing a null answer is not a meaningful distinction.

Server:
1. Auth: hider-in-game.
2. Validate: question is `photo` type, in `asked` state, owned by this game.
3. *Photo path:* generate UUID, upload bytes to S3. If `params.photo_object_key` is already set, leave the old key in S3 (orphan — kept forever). Set `params.photo_object_key` to the new UUID, clear `is_null_answer`. Emit `PhotoQueuedEvent` to hiders (§6.7).
4. *Null path:* set `is_null_answer = true`, clear `photo_object_key`.
5. If `submit=true` (photo path) or null path: call the submit logic (§6.2). Photo path with `submit=false` leaves the question in `asked` state with a queued photo.
6. Return 204.

**Fetch** — `GET /games/{game_id}/questions/{question_id}/photo`

Server streams the S3 object back to the client. Auth is state-sensitive:

- `asked` (photo queued but not submitted): **hiders only**. Lets hiders see the queued photo so they can replace it (§7 / §8.3). Seekers have no reason to see a queued photo and shouldn't — the review flow starts at `submitted`.
- `submitted`, `answered`, `vetoed`, `randomized`, `abandoned`: **any player in the game** (hiders and seekers). Seekers need to review under `submitted`; everybody can revisit under terminal states.

Rule of thumb: hiders can see the photo at any time there's one to see; seekers gain visibility the moment the hider hits submit.

Response:

- `Content-Type`: `image/jpeg` or `image/png`.
- `Content-Length`: from S3.
- Body: streamed bytes.
- `Cache-Control: private, max-age=3600` — safe because the key is immutable per question.

This model trades bandwidth for simplicity: photo bytes traverse the server on every view. At hobby scale this is fine. It buys:

1. Central auth (reuses `get_player_in_game` / `get_seeker_in_game`).
2. Fully private bucket — the only attack surface is the app.
3. Future encryption-at-app-layer without a URL-signing refactor.
4. Stable URLs for question history — no expiring presigned links to refresh on SSE reconnect.

### 5.4 LocalStack

LocalStack's S3 support is mature. The dev bucket is bootstrapped by `infra/localstack/init-aws.sh` (same hook that creates the SNS platform apps). `S3_BUCKET_NAME` env var selects the bucket; `AWS_ENDPOINT_URL` (existing) routes boto3 to LocalStack.

### 5.5 CDK

New construct in `DataStack`:
- `aws_s3.Bucket` (private, SSE-S3, versioning off).
- `bucket.grant_read_write(app_task_role)`.
- Output: bucket name → passed to `AppStack` as env var `S3_BUCKET_NAME`.

No CloudFront, no public policy, no lifecycle rules. Minimal.

### 5.6 Config

New `S3Config` in `core/config.py`:

```python
@dataclass(frozen=True)
class S3Config:
    bucket_name: str
    endpoint_url: str | None  # LocalStack; None in prod

def load_s3_config() -> S3Config | None:
    """Return None if S3_BUCKET_NAME is missing — photo endpoints 500 in that state."""
```

Follows the `SnsConfig` pattern. Unlike push, there's no useful no-op mode for S3 — if the bucket is missing, photo questions cannot function, and the server returns 500 on photo endpoints.

---

## 6. Server

### 6.1 Ask flow

**`ask_photo()`** in `logic/ask.py`:

```python
def ask_photo(
    game: Game,
    player: Player,
    seeker_location: Point,
    slot: InventorySlot,
) -> Question:
    """Create a photo question. Immediately asked; submit timer starts now."""
    assert slot.photo_subject is not None
    slot.ask_count += 1

    question = register(
        Question(
            game=game,
            sequence=get_question_count(game) + 1,
            question_type=QuestionType.photo,
            status=QuestionStatus.asked,
            asked_by=player.id,
            seeker_location_start=seeker_location,
            ask_count=slot.ask_count,
            slot_index=slot.slot_index,
            answerable_at=datetime.now(UTC),  # submit timer anchor
            photo_params=PhotoQuestionParams(subject=slot.photo_subject),
        )
    )
    _log_question_asked(game, player, question)
    return question
```

`answerable_at` doubles as the submit-timer anchor — the reconciler checks `answerable_at + photo_submit_min` for overdue submission.

Router: `POST /games/{game_id}/questions/photo` — mirrors the existing per-type ask endpoints. Body is the standard `AskQuestionRequest` with `slot_index`. No `custom_distance`; no location-sensitive params beyond the seeker's current position (logged for the record).

### 6.2 Submit flow

One endpoint, hider-in-game: **`POST /games/{game_id}/questions/{question_id}/photo`** (§5.3). Multipart for photo upload (optionally immediate-submit via `submit=true`), JSON `{"null": true}` for null answer. A separate null endpoint is overkill — the transition is the same.

If the photo-path arrives with `submit=false`, the upload lands in S3 and `params.photo_object_key` is set but the question stays in `asked`. The hider (or any other hider) can replace it up until either a subsequent call with `submit=true`, the null path is taken, or the submit-deadline fires (§6.4).

If the photo-path arrives with `submit=true` or the null path is taken, `_submit_photo_question(question, player)` runs:

```python
def _submit_photo_question(question: Question, player: Player) -> None:
    """Transition asked → submitted. Locks out other hiders."""
    params = question.photo_params
    assert params is not None
    assert question.status == QuestionStatus.asked
    # Either is_null_answer or photo_object_key must be set by the caller.
    params.submitted_at = datetime.now(UTC)
    params.submitted_by = player.id
    question.status = QuestionStatus.submitted
    logger.info(
        'photo_submitted',
        game_id=str(question.game_id),
        question_id=str(question.id),
        null=params.is_null_answer,
        submitted_by=str(player.id),
    )
```

**Submission lock.** Once `question.status == submitted`, another hider's attempt to upload or submit-null returns 409 ("a photo is already under review"). The lock releases on reject (status loops back to `asked`).

### 6.3 Review flow

**`POST /games/{game_id}/questions/{question_id}/accept`** (seeker-in-game):

```python
def accept_photo(question: Question, player: Player) -> None:
    params = question.photo_params
    assert params is not None
    assert question.status == QuestionStatus.submitted
    params.review_decision = PhotoReviewDecision.accepted
    params.reviewed_at = datetime.now(UTC)
    params.reviewed_by = player.id
    question.status = QuestionStatus.answered
    question.answered_at = params.reviewed_at
    question.answer = params.photo_object_key if not params.is_null_answer else 'null'
    question.exclusion = None
    # total_exclusion carries forward from prior question via the existing
    # null-exclusion handler — photo questions add no new geometry.
    apply_null_exclusion(question)
    _log_question_answered(question)
```

**`POST /games/{game_id}/questions/{question_id}/reject`** (seeker-in-game):

```python
def reject_photo(question: Question, player: Player) -> None:
    params = question.photo_params
    assert params is not None
    assert question.status == QuestionStatus.submitted
    params.review_decision = PhotoReviewDecision.rejected
    params.reviewed_at = datetime.now(UTC)
    params.reviewed_by = player.id
    # Loop back: null the submission so another attempt can take over.
    params.photo_object_key = None
    params.is_null_answer = False
    params.submitted_at = None
    params.submitted_by = None
    question.status = QuestionStatus.asked
    question.answerable_at = datetime.now(UTC)  # reset submit timer
    logger.info(
        'photo_rejected',
        game_id=str(question.game_id),
        question_id=str(question.id),
        reviewed_by=str(player.id),
    )
```

Resetting `answerable_at` gives the hider a fresh `photo_submit_min` window. The reconciler picks up the new deadline on its next tick.

**Action race.** First seeker to act wins. The validator checks `question.status == submitted` under the request's transaction boundary and 409s otherwise. No explicit lock needed.

### 6.4 Auto-accept / auto-submit (reconciler + worker)

The reconciler gains two new overdue-queries:

1. **Overdue submit deadlines** — `question_type == photo`, `status == asked`, `answerable_at + photo_submit_min < now`. Enqueues `auto_resolve_photo_submit` with task id `photo_submit:<question_id>`.
2. **Overdue review deadlines** — `question_type == photo`, `status == submitted`, `photo_params.submitted_at + photo_review_sec < now`. Enqueues `auto_accept_photo` with task id `photo_review:<question_id>`.

Worker tasks in `worker/tasks/game_timers.py`:

- **`auto_resolve_photo_submit(question_id)`** — if `question.status != asked`, no-op. If `params.photo_object_key` set OR `is_null_answer` true → auto-submit (set `submitted_at`, `submitted_by = NULL` sentinel for auto). Otherwise mark `abandoned` and emit `QuestionAbandonedEvent`.
- **`auto_accept_photo(question_id)`** — if `question.status != submitted`, no-op. Set `params.review_decision = auto_accepted`, `reviewed_at = now`, `reviewed_by = NULL`, flip status to `answered`, emit answered events.

The reconciler's task-id convention (log-grep observability, not revocation) carries through — state changes naturally eliminate overdue rows from the query.

### 6.5 Veto, randomize, abandon

All three powerups apply to photo questions.

- **Veto** — hider uses `POST /questions/{id}/veto` while `status ∈ {asked, submitted}`. Marks `vetoed`, terminal. Distinct from null answer: null is "I can see nothing of that subject" (game-legal submission); veto is "I refuse to engage with this question" (spends a veto card).
- **Randomize** — replaces the current photo question with a random eligible photo slot. `randomize_question()` dispatch in `logic/ask.py` adds a case for `QuestionType.photo` that calls `ask_photo`.
- **Abandon** (seeker) — `POST /questions/{id}/abandon` while status is any non-terminal photo state. Terminal, ask consumed.

None of these require new events — existing `QuestionVetoedEvent` / `QuestionAbandonedEvent` / `QuestionAskedEvent` (for randomized replacement) suffice.

### 6.6 No preview wiring

Photo questions do **not** register with `preview_question()` in `logic/preview.py`. The seeker belt UX skips the preview step (§7). If the preview endpoint is called with `question_type=photo`, return 422.

### 6.7 Events

**`PhotoEventParams`** — new param model in `broadcast/events.py`:

```python
class PhotoEventParams(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: Literal['photo'] = 'photo'
    subject: PhotoSubject
```

Minimal — the subject is all the client needs. Labels are looked up client-side.

**`QuestionEventParams` union** — add `PhotoEventParams`. **`build_event_params(question)`** — dispatch case for `QuestionType.photo`.

**`PhotoQueuedEvent`** — new, **hider channel only**:

```python
class PhotoQueuedEvent(GameplayEventSchema):
    question_id: uuid.UUID
    sequence: int
    queued_by: uuid.UUID   # the hider who uploaded
    uploaded_at: datetime
    # photo_object_key is intentionally omitted — hiders fetch via GET
```

Emitted whenever a hider uploads a photo with `submit=false` (queue), including a *replacement* upload on top of an existing queued photo. All hiders (including the one who queued it) get the event so their UI can pull the updated thumbnail via `GET /photo` and decide whether to replace. Seekers never see queued photos, so this event does not go to the seeker channel.

**`PhotoSubmittedEvent`** — new, **both channels** (hider + seeker):

```python
class PhotoSubmittedEvent(GameplayEventSchema):
    question_id: uuid.UUID
    sequence: int
    status: QuestionStatus  # always 'submitted'
    submitted_at: datetime
    submitted_by: uuid.UUID | None  # NULL if auto-submitted from queue
    is_null_answer: bool
    review_deadline: datetime
    # photo_object_key is intentionally omitted — clients fetch via GET, never from the event
```

Role-specific effects:
- **Seeker** client transitions its banner from "waiting for photo" to "review" and starts the countdown from `review_deadline`. Renders the photo by calling `GET /games/{id}/questions/{qid}/photo`.
- **Hider** client — including hiders who did not submit — transitions its banner to "submitted — awaiting review" and disables the picker, enforcing the submission lock (§6.2) at the UI layer.

**`PhotoRejectedEvent`** — new, both channels:

```python
class PhotoRejectedEvent(GameplayEventSchema):
    question_id: uuid.UUID
    sequence: int
    reviewed_by: uuid.UUID
    rejected_at: datetime
    new_submit_deadline: datetime
```

Hider banner returns to "submit a photo." Seeker banner returns to "waiting for photo."

**Accept** reuses the existing `HiderQuestionAnsweredEvent` + `SeekerQuestionAnsweredEvent` pair. `question.answer` is the photo object key (or the string `'null'` for null answers), and both `exclusion` / `total_exclusion` are `None`. The client detects `question_type == photo` to render the photo viewer instead of a map delta.

### 6.8 Push notifications

New `PushEventType` values:

- `photo_submitted` — to seekers, when the hider submits.
- `photo_rejected` — to hiders, when the seeker rejects.

Accept reuses `question_answered`. Submit timeout (`abandoned`) reuses `question_abandoned`. Auto-accept on review timeout reuses `question_answered`.

### 6.9 SSE snapshot and history

`HiderGameStateResponse` and `SeekerGameStateResponse` include `question_history`. Photo entries fit the existing shape: `parameters` carries `PhotoEventParams`, `answer` carries the object key or `'null'`, `status` indicates the terminal state.

For `submitted` photo questions (still live on reconnect), the snapshot's active-question carries enough fields to reconstruct the review banner: subject, submitted_at, is_null_answer, review_deadline. `HiderActiveQuestion` / `SeekerActiveQuestion` gain optional fields (`submitted_at`, `is_null_answer`, `review_deadline`) that are populated for photo questions in `submitted` state and null otherwise.

---

## 7. Mobile: Seeker Experience

### 7.0 Visual identity

Photo questions get a dedicated color in the mobile palette (used for belt buttons, banner accents, question-history rows, and anywhere else the question type is visually distinguished):

| Usage | RGB |
|---|---|
| Normal | `rgb(156, 190, 208)` |
| Dimmed (disabled/locked) | `rgb(199, 216, 225)` |

Camera icon on top of this palette. Registered alongside the existing per-`QuestionType` color map in `mobile/src/theme/questionColors.ts` (or wherever the existing five types are registered).

### 7.1 Belt takeover — type selection

Photo is a sixth button in the belt takeover's type selection:

| Button | Icon | Label |
|--------|------|-------|
| Photo | `camera` | Photo |

Visible only if the game has photo inventory (effectively always, unless `Game.size == special`).

### 7.2 Parameter selection — subject list

The belt zone shows a scrollable picker of subject slots from the inventory. Each item:
- Subject label (e.g., "A Tree", "Grocery Store Aisle").
- `ask_count` (e.g., "x2" if asked twice before).

Tapping a subject highlights it. **No map preview** — photo questions have no spatial overlay. The banner slides up with just "Ask photo: [subject]?" confirmation.

### 7.3 Active question banner

While status is `asked` (waiting for hider to submit):
- Icon + "Photo: [subject]"
- Status: "Waiting for hider to submit..."
- Countdown (submit timer) + Abandon button.

While status is `submitted`:
- Icon + "Photo: [subject]"
- Photo thumbnail (lazy-loaded from `GET /questions/{id}/photo`) OR "null answer — hider reports nothing to photograph"
- Accept button (primary) + Reject button (destructive-tinted, with confirmation "Reject this photo? The hider will have to resubmit.")
- Countdown (review timer)

### 7.4 Resolution

On `HiderQuestionAnsweredEvent` / `SeekerQuestionAnsweredEvent` for a photo question:
- Banner slides down.
- Entry added to question history (HideAndSeek-qpr) as a photo row.
- No map overlay update (no exclusion).

On `PhotoRejectedEvent`:
- Banner returns to the "waiting for hider" state with a fresh countdown.
- Toast: "Photo rejected — hider will resubmit."

### 7.5 Photo viewer

Tapping the thumbnail in the banner or in question history opens a full-screen viewer:
- Full-resolution image from `GET /questions/{id}/photo`.
- Pinch-to-zoom.
- Subject label + submitter name + timestamp.
- Dismiss tap.

Photo bytes are cached by the HTTP client (response has `Cache-Control: private, max-age=3600`). No app-level image cache management.

---

## 8. Mobile: Hider Experience

### 8.1 Active question banner — asked state

When a `QuestionAskedEvent` with `PhotoEventParams` arrives:
- Icon + "Photo request: [subject]"
- Countdown (submit timer).
- **Pick Photo** button (primary) — opens the system photo picker (`expo-image-picker.launchImageLibraryAsync`).
- **Null Answer** button (secondary) — with confirmation "Submit null? Seekers will be told you can't photograph this."
- **Power-up** button (veto / randomize).

### 8.2 Photo picker flow

1. Hider taps **Pick Photo** → system photo picker opens.
2. Hider selects an image → app shows a preview card inside the banner:
   - Thumbnail of selected photo.
   - **Submit Now** button — immediate upload + submit.
   - **Queue** button — upload + queue (auto-submits at deadline).
   - **Replace** button — re-opens the picker.
   - **Cancel** button — discards selection locally; does not upload.

The upload always happens when a photo is "committed" (Submit Now or Queue) — not on initial selection. This avoids uploading abandoned picks.

### 8.3 Queued state

A "queued" banner state is triggered by `PhotoQueuedEvent` (§6.7), **not** by local action — the event is authoritative, so every hider converges on the same view regardless of who uploaded. The banner shows:

- Thumbnail of the queued photo (fetched via `GET /photo`).
- "Queued by [hider name] — will auto-submit at [deadline time]."
- **Submit Now** button — fires immediate submit without re-upload (photo is already in S3).
- **Replace** button — opens picker; on new selection, uploads the new photo with `submit=false`. The resulting `PhotoQueuedEvent` fans out to all hiders, updating their thumbnails.
- **Unqueue** button — discards the queued photo. Calls `DELETE /games/{id}/questions/{qid}/photo` to clear the key on the server; returns to the pre-pick state.
- **Null** and **Power-up** buttons remain available.

The "Queue" action in §8.2 is therefore really "upload with `submit=false`"; the UI state change follows from the server's echoed event, not from local commit. A small latency bubble is acceptable — the picker UI can optimistically show a spinner while waiting for the event round-trip.

### 8.4 Submitted state

After Submit Now OR auto-submit fires:
- Banner shows "Submitted — waiting for seeker review..."
- Countdown (review timer, from `review_deadline` in `PhotoSubmittedEvent`).
- No actions — the hider waits.

### 8.5 On reject

`PhotoRejectedEvent` arrives → banner returns to asked-state with a fresh picker flow. Toast: "Seeker rejected your photo — try again."

### 8.6 On accept

`HiderQuestionAnsweredEvent` arrives with `question_type=photo` → banner slides down. No map delta. Toast: "Seeker accepted your photo."

### 8.7 Multi-hider lock

The submission lock (§6.2) translates to the UI: while `status == submitted`, all hider clients show the "Submitted — waiting for review" state, not the picker. No hider can swap the photo under review.

If a hider is mid-pick when another hider submits, the first-in-queue's pick-phase is interrupted: next tap on Submit/Queue returns 409 (photo already submitted), and the banner rehydrates from the current state.

---

## 9. Interactions

### 9.1 Question history (HideAndSeek-qpr)

Photo questions appear in question history with:
- Subject label + photo thumbnail (or "null answer" placeholder).
- Review decision (accepted / rejected / auto-accepted).
- No exclusion delta — scrubbing past a photo question shows no map change.

The shared `QuestionHistoryRow` component (planned in qpr) renders a photo row differently: thumbnail + caption instead of geometry summary. Tap opens the full-screen viewer (§7.5). For the seeker scrubber (HideAndSeek-0r6), the current-question card for a photo shows the photo + subject with no exclusion overlay on the scrubber map.

### 9.2 Endgame

Null answers are especially informative in endgame — "can't see a tree from the hiding spot" meaningfully narrows zone characterization. Photo questions are fully available during endgame, same timer dynamics.

The hider is frozen in endgame, so all photos must be from the hiding spot. This matches the rulebook's "visible from station" requirement wording for the multi-building subjects.

### 9.3 Found claim

Unrelated. Photo questions and found-claim are independent flows.

### 9.4 Proximity tier / freeze

Unrelated.

### 9.5 Dissolution / host end

Standard cleanup — terminal game status hides photo questions from the UI. Photos are not deleted. The bucket accumulates.

---

## 10. Resolved Decisions

- **No in-app camera.** Use the system photo picker exclusively. Blurring/editing happens in external apps per the rulebook.
- **No rule text on the wire.** Subjects are enum-identified; the physical rulebook is the source of truth for *how* to photograph.
- **Subjects are size-gated, not map-configured.** No JSON column on `GameMap` — availability derives from `Game.size` via a code-level meta table.
- **Inventory draw costs are handled by the existing mechanic.** Re-asks get more expensive via the shared `ask_count` pattern; photo doesn't need or introduce anything new, and mobile doesn't have to model the cost curve.
- **Two new timers.** `photo_submit_min` (minutes, size-default 10/10/20) and `photo_review_sec` (seconds, default 30). Both game-level with map-level override following the three-level fallback pattern.
- **Rejection loops back with a fresh submit window.** The `Question` row stays alive; `photo_object_key` / `submitted_at` / `submitted_by` null out; `answerable_at` resets. Ask is not re-consumed.
- **Rejection exploitability is known and deferred.** A hider could submit bad photos repeatedly to burn seeker time. The planned mitigation is a game-timer-pause mechanic (separate bead) that freezes the seeking clock during open photo questions.
- **Null answer is first-class.** Explicit "can't photograph this" option. Seekers still accept/reject; null is strategically informative.
- **One submit/upload endpoint.** Photo upload and null answer share `POST .../questions/{id}/photo` (multipart for photo, JSON for null). A dedicated null endpoint is overkill; the transition is one transition.
- **Submission lock.** Once submitted, no other hider can swap. Lock releases on reject.
- **First-action-wins on both sides.** First hider to submit, first seeker to accept/reject — no unanimous vote.
- **No new exclusion geometry; running total carries forward.** `exclusion` is `NULL`; `total_exclusion` is inherited from the prior question via the existing null-exclusion handler. No custom logic — reuse what `unclear`/null answers already do.
- **No preview endpoint wiring.** Photo questions skip the preview step entirely.
- **Private S3 bucket, server-proxy fetch.** No presigned URLs. Bucket is fully private; the app is the sole access path.
- **State-sensitive photo-read auth.** Queued (pre-submit) photos are hider-only; submitted and terminal photos are visible to any player in the game. See §5.3.
- **Queued photos fan out to hiders via `PhotoQueuedEvent`.** Every hider sees queued uploads and can replace them. The server event is authoritative; the UI does not optimistically lock queued state to the uploader.
- **Photos kept forever.** No lifecycle rules, no dedup, no cleanup. Revisit when bucket cost becomes non-trivial.
- **No EXIF stripping, no re-encoding, no upload size cap.** System picker produces reasonable sizes; transform pipelines and size limits are scope creep until someone's upload hurts us.
- **Dedicated palette entry for photo questions.** `rgb(156, 190, 208)` normal / `rgb(199, 216, 225)` dimmed (§7.0).
- **Veto + randomize apply normally.** Veto is distinct from null (veto spends a card; null is a legitimate submission).

---

## 11. Open Questions / Future Work

- **Game-timer-pause mechanic.** Separate bead (§12). Unblocks the real mitigation for hider stalling / bad-photo-spam.
- **Photo cleanup lifecycle.** Separate future bead. Likely S3 lifecycle rules keyed on game status (terminal + N days), possibly with a tombstone column to avoid reading every game at sweep time.
- **Re-encoding / EXIF stripping / upload size enforcement.** Revisit if we see large uploads or metadata leaks.
- **Photo review audit trail.** The current model keeps only the *last* review decision on params. If disputes arise, a separate `photo_review_history` table preserves every reject → resubmit cycle.
- **CDN / CloudFront in front of the bucket.** Not now — server proxy is cheap enough at hobby scale.
- **Moderation for inappropriate content.** Not a concern for a trusted friend-group game. A public deployment would need it.
- **Playtest questions.** Does qualitative photo info overshadow geometric question types? Is the review step fun or a chore? Does null feel balanced, or trivialized? All tuning-dial questions (timers, subject list) — no structural rework needed to adjust.

---

## 12. Beads to File

Two new beads, filed after this design lands:

1. **Game-timer-pause mechanic** (standalone epic). General infrastructure for pausing the seeking clock during certain question states. No dependency on z32.
2. **Apply timer-pause to photo questions** (task). Depends on both z32 and the timer-pause epic. Wires the pause into the photo question lifecycle to eliminate the stalling exploit.

Plus the implementation children of z32 itself:

- models + Alembic migration (enums, `PhotoQuestionParams`, `Game` columns, `GameMap` columns, `InventorySlot.photo_subject`)
- `S3Config` + upload/fetch plumbing in core
- ask + submit + review logic (core)
- event schemas (core broadcast)
- push event types (core)
- server routers (`/photo`, `/submit-null`, `/accept`, `/reject`, `GET /photo`)
- reconciler queries + worker tasks (submit timeout + review timeout)
- CDK S3 bucket in `DataStack`
- LocalStack bootstrap
- mobile: belt picker, seeker banner (asked / submitted / rejected states), hider banner (picker / queue / submitted states), photo viewer, review UI
- question history row (photo variant)
- seed script update (photo inventory for Seattle)
