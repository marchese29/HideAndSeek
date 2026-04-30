# EventBridge Timers

> Status: **Draft**
> Last updated: 2026-04-29
> Depends on: `2026-02-15-background-jobs.md` (reconciler + Celery split), `2026-04-19-aws-deployment.md` (Aurora Serverless v2 min=0), `2026-04-25-game-timer-pause.md` (future-deadline columns)

Replace the production polling reconciler with **EventBridge Scheduler** so that game-timer firing becomes event-driven instead of poll-driven. The polling reconciler stays in place for local development (`docker compose`) and tests, gated by an env-driven `TimerScheduler` abstraction.

---

## 1. Motivation

The reconciler today (`reconciler/src/hideandseek_reconciler/__main__.py`) ticks every 1 second, opens a session, and runs five overdue queries against Postgres. Locally that's free. In production it pins Aurora Serverless v2 to a permanent non-zero ACU floor — which directly defeats `serverlessV2MinCapacity: 0` (`infra/cdk/lib/data-stack.ts:58`), the single largest hobby-cost win in our deployment design.

The cost concern isn't query CPU. It's that **any** poll keeps the cluster from auto-pausing. Idle is supposed to mean idle.

What we want:
- Timers fire on time without Postgres being awake.
- Pause/resume semantics from the timer-pause epic (`2026-04-25-game-timer-pause.md`) keep working.
- Local development stays no-AWS-required.
- One-second granularity preserved (no Lambda cold-start in the hot path).

---

## 2. Why EventBridge Scheduler

The shape of the problem: per-deadline one-shot fires, max ~3h ahead (longest game timer), ~five categories of timer, low total volume.

### Considered and rejected

| Option | Rejected because |
|---|---|
| Postgres `LISTEN/NOTIFY` | Holds an open session; same auto-pause defeat as polling. |
| Adaptive sleep (`MIN(deadline)` then `event.wait`) | Still polls Postgres on every wake; better than 1Hz but doesn't get to true zero. |
| SQS `DelaySeconds` / message timer | Capped at 15min; hiding timer is up to 180min. |
| Step Functions Wait state | Heavy; per-state-transition pricing. |
| EventBridge Bus scheduled rules | The classic "scheduled rules" product is cron-based and minute-grained — wrong primitive for one-shot timers. |
| Celery ETA tasks (status quo before reconciler) | Original architecture; rejected in `2026-02-15-background-jobs.md` because a worker crash loses the in-memory timer. |

### Why EventBridge Scheduler wins

- **One-shot `at(<timestamp>)` schedules** with second-level granularity.
- **Self-cleaning** via `ActionAfterCompletion: DELETE` — no janitor.
- **Per-schedule retry policy + DLQ** — a 60s deploy gap or ALB hiccup is absorbed by the retry layer.
- **$1 per million invocations** — at hobby scale this rounds to free.
- **No standing process required** — the scheduler is fully managed; nothing on our side holds connections or polls.

---

## 3. Target: HTTPS to the server, not Lambda

EventBridge Scheduler can target Lambda, SQS, SNS, Step Functions, or any HTTPS endpoint via an EventBridge **API destination** (a connection + an HTTPS endpoint registered as an event target).

We choose **HTTPS to the server's ALB**:

- One-second timer granularity makes Lambda cold starts (~100ms in steady state, multi-second on cold) unattractive.
- Coupling timer firing to server uptime is acceptable: the server is `desiredCount: 1` always-on Fargate (`AppStack` § Service Sizing); a deploy or restart is absorbed by EventBridge's retry policy (default ~185 retries over 24h with exponential backoff).
- Server already has `apply_async` wired up and the Celery task bodies. The endpoint is a thin authenticated dispatcher.

### Endpoint shape

```
POST /internal/timers/fire
Headers:
  Authorization: Bearer <shared secret from Secrets Manager>
Body:
  { "task": "transition_hiding_to_seeking" | "auto_answer_question" | ... ,
    "id":   "<game_id or question_id>" }
```

The handler validates the bearer token (constant-time compare against a secret pulled at startup), maps `task` → Celery task object, and calls `apply_async(args=[id], task_id=f'<task>:{id}')`. The task body's existing idempotency check (status-on-entry, no-op if state has advanced) keeps a duplicate fire harmless.

The route is **not** in the OpenAPI spec — it's an internal/private boundary used only by EventBridge. Mounted under a `/internal/...` path that the ALB ingress could later restrict via an SG rule scoped to EventBridge's IP ranges if we want belt-and-suspenders, though the bearer secret is sufficient.

### Why not a separate dedicated subdomain or path-only ingress

Lower complexity wins. The server already accepts ALB traffic on :8000; one more authenticated route is cheaper than a second listener / target group / DNS record. If we ever want hard isolation we can add a second ALB target later.

---

## 4. The `TimerScheduler` abstraction

A single seam at the deadline-write site, with two implementations selected by env (`TIMER_BACKEND=eventbridge|reconciler`).

```python
# core/timers/scheduler.py (new module)
class TimerScheduler(Protocol):
    def schedule(self, *, name: str, fire_at: datetime, task: TimerTask, target_id: UUID) -> None: ...
    def cancel(self, *, name: str) -> None: ...
    def reschedule(self, *, name: str, fire_at: datetime, task: TimerTask, target_id: UUID) -> None: ...
```

`TimerTask` is an enum mirroring the five Celery task names. `name` is deterministic per timer (`hiding:{game_id}`, `answer_deadline:{question_id}`, `found_claim:{game_id}`, `photo_submit:{question_id}`, `photo_review:{question_id}`) — same naming convention the reconciler already uses for `task_id`s.

### Implementations

**`EventBridgeTimerScheduler`** (production)
- `schedule` → `scheduler:CreateSchedule` with `at(fire_at)`, target = the API destination, payload = `{task, id}`, `ActionAfterCompletion: DELETE`, `FlexibleTimeWindow.Mode: OFF`.
- `cancel` → `scheduler:DeleteSchedule` by name; ignores `ResourceNotFoundException` (already-fired or already-deleted is fine).
- `reschedule` → `scheduler:UpdateSchedule` (or delete + create — TBD, depends on whether updating an `at()` schedule that's mid-retry is safe; planning task).

**`NoopTimerScheduler`** (local dev, tests, fallback)
- Every method is a `pass`. The deadline column write into Postgres is enough — the polling reconciler picks it up.

Selection happens once at process startup, wired via dependency injection where the logic layer needs it.

### Where it's called

The five sites that write a deadline column today (after the timer-pause epic lands; pre-pause they're the equivalent start anchors):

| Write site | Schedule call |
|---|---|
| `core/logic/lobby.start_game` | `schedule(name='hiding:{game_id}', fire_at=hiding_ends_at, task=TRANSITION_HIDING, target_id=game_id)` |
| `core/logic/ask.create_question` (or photo equivalent) | `schedule(name='answer_deadline:{question_id}', fire_at=deadline_at, ...)` |
| `core/logic/found_claim.open_claim` | `schedule(name='found_claim:{game_id}', fire_at=found_claim_expires_at, ...)` |
| `core/logic/photo.submit_window_starts` | `schedule(name='photo_submit:{question_id}', fire_at=submit_deadline_at, ...)` |
| `core/logic/photo.submit_received` | `schedule(name='photo_review:{question_id}', fire_at=review_deadline_at, ...)` |

Pause/resume sites in `core/logic/pause.py` (per `2026-04-25-game-timer-pause.md`) call `cancel` on pause and `schedule` on resume with the shifted deadline.

---

## 5. Write ordering and consistency

**Decision: schedule before commit.** The handler calls `scheduler.schedule(...)` *before* `session.commit()`. If the AWS call raises, the transaction rolls back and the request errors out — the user sees a 5xx and retries. Both writes succeed or neither does.

Rationale (decided in conversation 2026-04-29):
- The two-write coordination problem reduces to one ordering decision.
- Schedule-before-commit means a successful response **guarantees** the timer is set.
- Idempotency on retry is preserved: deterministic schedule names mean a retry of the same request hits `ConflictException` (already exists) — handler treats that as success and proceeds to commit.

The mirror failure mode — schedule succeeds, DB commit fails, schedule fires for a non-existent deadline — is harmless because the Celery task body's status-on-entry check no-ops on advanced/missing state.

### No production reconciler backstop

Skipped on first cut, per the same conversation. Defenses:
- **Schedule-before-commit** eliminates the "DB has deadline, schedule doesn't exist" failure mode by construction.
- **EventBridge DLQ** with a CloudWatch alarm catches the rare case where the schedule exists but the API destination invocation fails past all retries. The alarm tells us the assumption is breaking; we add a sweep then.
- **Local-dev reconciler is the same code path** — if a structural bug makes us drop schedules, the dev environment will surface it before prod does.

If the alarm ever fires in practice, the cost of bringing the polling reconciler back as an hourly sweep is small — it's all already written.

---

## 6. Local development

`docker-compose.yml`'s reconciler service stays exactly as it is. The `TIMER_BACKEND` env var defaults to `reconciler` in the dev compose file and is set to `eventbridge` by AppStack on the prod server task definition. The reconciler container reads its own `TIMER_BACKEND` (also `reconciler`) and runs its 1Hz tick as today.

**Why not LocalStack EventBridge Scheduler:** LocalStack's Scheduler endpoint accepts API calls but doesn't execute them — it's mocked-only and gated behind paid tiers. Verified 2026-04-29.

Tests use the `NoopTimerScheduler` against the testcontainers Postgres — same as today, since the reconciler's overdue queries already exercise the timer path in the server test suite.

---

## 7. Infrastructure (CDK)

New resources in `AppStack` (or a new `TimersStack` if it grows):

- **EventBridge `Connection`** — auth type `API_KEY`, secret stored in Secrets Manager, header name `Authorization`. Value generated at deploy time, mounted into the server task as a Secret.
- **EventBridge `ApiDestination`** — `https://hideandseek.marchese.dev/internal/timers/fire`, `POST`, references the Connection.
- **`SchedulerInvocationRole`** — IAM role assumed by EventBridge Scheduler with `events:InvokeApiDestination` on the destination ARN, plus `sqs:SendMessage` to the DLQ.
- **DLQ** — SQS queue with a 14-day retention, `CloudWatch Alarm` on `ApproximateNumberOfMessagesVisible > 0` for 5 minutes.
- **Server task role policy additions**:
  - `scheduler:CreateSchedule`, `scheduler:UpdateSchedule`, `scheduler:DeleteSchedule`, `scheduler:GetSchedule` scoped to `arn:aws:scheduler:<region>:<account>:schedule/default/hideandseek-*`.
  - `iam:PassRole` on the `SchedulerInvocationRole` ARN.
- **`ReconcilerService` removal** — `desiredCount: 0` in prod, or remove from `AppStack` entirely. Decision deferred to the planning task.

CloudWatch metrics + dashboards: `Invocations`, `InvocationsFailedToBeSentToDeadLetterQueue`, `TargetErrorCount` per schedule group. Set the alarm thresholds during the implementation cycle.

---

## 8. Aurora vs RDS (deferred)

The polling-cost concern that motivates this design is specifically a property of Aurora Serverless v2 with `min=0`. Switching to a fixed-size RDS instance would erase the concern but cost ~$13/mo of always-on instead of the current ~$5/mo idle.

Crossover is roughly 9 active ACU-hours/day; below that, Serverless wins. Decision: **stay on Serverless**. Re-evaluate when CloudWatch's `ServerlessDatabaseCapacity` flatlines at non-zero — at that point the auto-pause feature has stopped paying for itself and a `db.t4g.micro` becomes the cheaper option. Migration in that direction is a snapshot-restore, not a data-model change.

---

## 9. Out of scope

- **Replacing Celery as the worker pool.** EventBridge fires the trigger; Celery still executes the task body. No churn to `worker/`.
- **Migrating off the polling reconciler in tests.** Tests use the `Noop` scheduler and the existing reconciler queries; no test rewrites.
- **EventBridge Pipes / cross-account.** Unnecessary at hobby scale.
- **Backstop sweep in prod.** Skipped on first cut; revisit only if the DLQ alarm fires.

---

## 10. Implementation cycles (sketch)

To be expanded by the planning task under the epic. First-pass decomposition:

1. **`TimerScheduler` abstraction** in `core/timers/`, two implementations, `Noop` selected for tests.
2. **Server endpoint** `/internal/timers/fire` with bearer auth, dispatching to the existing Celery tasks.
3. **CDK** — Connection, ApiDestination, SchedulerInvocationRole, DLQ, alarm, server task role additions, env wiring.
4. **Wire `schedule()` calls** at the five deadline-write sites; `cancel()` at pause sites; `reschedule()` (or cancel + schedule) at resume sites.
5. **Decommission prod reconciler** — `desiredCount: 0` (or remove) once cycles 1–4 are merged and verified in prod.
6. **Docs + dashboards** — CloudWatch dashboard for the five timer types, README updates, CLAUDE.md updates per package.
