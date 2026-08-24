# forge — a fault-tolerant CI system with an AI failure analyzer

A lightweight, from-scratch CI platform: connect a Git repository, define a
YAML pipeline, run it across a pool of independent workers inside isolated
Docker containers, watch logs stream live, and get an AI-generated (but
clearly-labeled-as-a-suggestion) analysis whenever a build fails.

This is a portfolio/systems-design project. It's built to demonstrate the
distributed-systems mechanics that make CI infrastructure hard — leases,
heartbeats, dead-worker recovery, bounded retries with backoff, at-least-once
execution semantics — rather than to compete with Jenkins or GitHub Actions
on features.

```
Developer
    │
    ▼
React Dashboard  ──REST/WS──►  FastAPI CI Server
                                 ├── API
                                 ├── Scheduler (reaper: leases, dead workers, retries)
                                 ├── Job Manager
                                 ├── Worker Manager
                                 └── AI Failure Analyzer
                                       │
                        ┌──────────────┼──────────────┐
                        ▼              ▼               │
                   PostgreSQL       Redis               │
                 (durable state)  (queue/lease/pubsub)  │
                                       │                 │
                              ┌────────┼────────┐        │
                              ▼        ▼         ▼        │
                          Worker    Worker    Worker      │
                              │        │         │        │
                              ▼        ▼         ▼        │
                          Docker containers (isolated)     │
                              │                            │
                              └───── failure logs ─────────┘
```

## Why this architecture

**Workers pull, the server doesn't push.** A worker calls
`POST /api/workers/{id}/claim` when it's ready for work. This means the
server never needs a live picture of "which workers have capacity right
now" — it just needs a queue and a lease table. Simpler failure modes.

**Postgres is the source of truth; Redis is disposable.** The queue,
delayed-retry set, and pub/sub channels all live in Redis, but every fact
that matters for correctness (job status, attempt history, lease
ownership) is in Postgres. If Redis were flushed, the worst case is some
`QUEUED` jobs need to be manually re-enqueued — not silent data loss.

**A job and an attempt are different things.** `Job` is "run this commit's
pipeline." `JobAttempt` is "one worker's one try at it." This split is what
makes bounded retries, exponential backoff, and attempt-level log/AI-analysis
history possible without conflating retries with the job itself.

**At-least-once, not exactly-once.** If a worker finishes a job but dies
before its HTTP report reaches the server, the lease eventually expires and
the job gets requeued — meaning the same commands might run twice. This is
called out explicitly rather than glossed over; the [`complete_attempt`](backend/app/scheduler/lease_manager.py)
function ignores late reports whose lease token no longer matches, which is
what keeps a zombie worker from corrupting a reassigned attempt's state.

**Permanent failures are never retried.** A failing `pytest` run is real
information about the commit — retrying it wastes compute and hides signal.
Only failures the system itself classifies as infrastructure problems
(container failed to start, checkout failed, lease expired) count against
the retry budget. See [`docker_executor.py`](backend/app/worker/docker_executor.py)
for where that classification happens.

## AI Failure Analyzer

When an attempt finishes as `failed` or `infra_error`, the server:

1. Truncates the log to the most recent N characters (the failure is almost
   always near the end) — [`context_extractor.py`](backend/app/ai/context_extractor.py).
2. Scans the log for file paths referenced in tracebacks/compiler
   diagnostics and reads *just those files* from the checkout, instead of
   sending the whole repo.
3. Sends a structured request to an LLM provider behind a small interface
   ([`providers/base.py`](backend/app/ai/providers/base.py)) — swap providers
   with one config value, `CI_AI_PROVIDER=mock|anthropic`.
4. Validates the response against a strict Pydantic schema
   ([`ai/schemas.py`](backend/app/ai/schemas.py)). Anything that isn't valid
   JSON matching the schema is stored as `status=invalid` and shown as such
   on the dashboard — never guessed at, never silently coerced.
5. Stores the result against the specific `JobAttempt`, so re-running a job
   doesn't overwrite the analysis of a previous attempt.

The CI job's pass/fail verdict is decided *before* any of this runs and is
never touched by it. If the LLM provider is down, misconfigured, or returns
garbage, the job is still correctly marked failed — the dashboard just shows
"analysis unavailable" instead of a suggestion. The default provider
(`mock`) needs no API key and uses simple log-pattern heuristics so the
whole stack runs out of the box; set `CI_AI_PROVIDER=anthropic` and
`CI_AI_API_KEY` for real analysis.

This is explicitly **not** an autonomous coding agent — it never touches
the repository, never opens a PR, and the dashboard labels every analysis
as a suggestion a human should evaluate.

## Running it locally

```bash
git clone <this repo>
cd ci-system
docker compose up --build --scale worker=3
```

- Dashboard: http://localhost:5173
- API docs (Swagger): http://localhost:8000/docs
- Register a project, trigger a build, watch the logs stream, and (if a
  step fails) check the AI Analysis panel on the job page.

To trigger builds via GitHub push events instead of the "Trigger build"
button, point a repo's webhook at the URL shown on the project page
(`/api/webhooks/github/{project_id}?token=...`).

## Running the tests

```bash
# backend: scheduling, concurrency, worker failure, lease expiry, retries,
# pipeline execution, AI response validation
cd backend
pip install -r requirements.txt
pytest -v

# frontend: type-check + build
cd frontend
npm install
npx tsc -b && npm run build

# e2e (requires the full stack running via docker compose)
cd frontend
npx playwright install --with-deps chromium
npx playwright test
```

## Project layout

```
backend/
  app/
    models.py, schemas.py, config.py, database.py, pipeline.py
    scheduler/     lease manager, reaper loop, job creation
    worker/        docker executor, worker agent process
    ai/            analyzer orchestrator, schemas, context extraction,
                    swappable LLM providers (mock, anthropic)
    api/           REST routers + websocket log/status streaming
  tests/           scheduling, worker failure, retries, pipeline exec,
                    AI validation
frontend/
  src/
    pages/         Dashboard, ProjectDetail, JobDetail, Workers
    components/     PipelineRail (attempt-history visualization),
                    LiveLogs (terminal), AIAnalysisPanel, JobList, WorkerStatus
  tests/e2e/        Playwright smoke tests
docker-compose.yml  postgres, redis, ci-server, worker (scalable), frontend
.github/workflows/ci.yml
```

## Resume bullets

Use these four bullets on a placement resume. Replace the technology or test
counts only if you change the implementation.

- Built **Forge**, a fault-tolerant CI platform with FastAPI, PostgreSQL,
  Redis, React, and Docker, supporting repository registration, YAML pipelines,
  worker orchestration, live logs, and build history.
- Designed a pull-based scheduler with Redis priority queues, PostgreSQL-backed
  job attempts, lease tokens, heartbeats, dead-worker recovery, and bounded
  exponential retries for at-least-once execution.
- Implemented isolated Docker pipeline execution with CPU/memory limits,
  network controls, GitHub checkout, sequential step exit-code tracking,
  timeout enforcement, streamed logs, and permanent-vs-infrastructure failure
  classification.
- Added a structured AI failure analyzer with mock and Anthropic providers,
  Pydantic response validation, truncated log/context extraction, persisted
  attempt-level suggestions, plus 27 backend and 5 browser end-to-end tests.

## Project explanation for interviews

Forge is a small CI system. A user registers a public Git repository and a
YAML pipeline in the React dashboard. The FastAPI server validates the YAML,
stores the project in PostgreSQL, and creates a job with an immutable pipeline
snapshot. The job ID is placed in a Redis priority queue.

Workers are independent pull-based processes. Each worker registers, sends
heartbeats, polls Redis through the server, and receives a lease token when it
claims a job. The worker starts a temporary Docker container, checks out the
requested commit, executes each pipeline step, streams logs, renews its lease,
and reports the final exit code. The server records every attempt and exposes
the result to the dashboard through REST and WebSockets.

The scheduler reaper handles failure: it detects stale heartbeats, expires
leases, requeues infrastructure failures with exponential backoff, and avoids
retrying genuine test or build failures. The guarantee is at-least-once, not
exactly-once: a worker may execute a command twice if it dies after execution
but before reporting completion.

When an attempt fails, the AI analyzer receives bounded log context and a
strictly structured request. Its response is validated and stored as a
suggestion. AI never changes the CI verdict and is unavailable safely when a
provider fails.

## File-by-file guide

### Repository root

- `docker-compose.yml`: Defines PostgreSQL, Redis, the FastAPI server, scalable
  workers, and the nginx frontend, including health checks and the Docker socket
  mount required for sibling job containers.
- `README.md`: Architecture, setup, design decisions, interview material, and
  limitations.
- `.env.example`: Documents configurable local environment variables.
- `.gitignore`: Excludes Python/Node environments, build output, test reports,
  caches, and local secrets.
- `.github/workflows/ci.yml`: Runs backend tests, frontend build checks, and
  the browser smoke-test workflow in CI.

### Backend application

- `backend/Dockerfile`: Builds the API image from Python 3.11, installs Git and
  curl, installs requirements, and starts Uvicorn.
- `backend/Dockerfile.worker`: Builds the worker image and installs its Python
  dependencies and Git client.
- `backend/requirements.txt`: Pins FastAPI, SQLAlchemy, Redis, Docker SDK,
  Pydantic, AI providers, HTTP client, and test dependencies.
- `app/main.py`: Creates the FastAPI application, initializes tables, mounts
  routers, and starts the scheduler/reaper lifecycle.
- `app/config.py`: Loads CI settings such as database/Redis URLs, lease and
  retry durations, and AI provider configuration.
- `app/database.py`: Creates the SQLAlchemy engine/session dependency and
  provides the declarative base used by the models.
- `app/models.py`: Defines Project, Job, JobAttempt, Worker, and AIAnalysis
  tables plus their status enums and relationships.
- `app/schemas.py`: Defines Pydantic request and response contracts for REST
  endpoints, worker leases, attempt reports, and AI analysis.
- `app/pipeline.py`: Parses and validates YAML pipelines, including image,
  positive timeout/CPU values, supported network modes, and required steps.
- `app/redis_client.py`: Encapsulates Redis priority queue, delayed retry,
  status publication, and log publication operations.

### Backend API

- `app/api/projects.py`: Creates projects, lists projects, reads a project, and
  validates pipeline updates.
- `app/api/jobs.py`: Creates manual jobs, lists jobs, returns attempts, and
  exposes AI analysis retrieval/retry endpoints.
- `app/api/attempts.py`: Accepts lease-authenticated logs, renewals, and
  completion reports; it also triggers non-blocking-in-correctness AI analysis.
- `app/api/workers.py`: Registers workers, handles heartbeats, and returns
  claims from the scheduler.
- `app/api/webhooks.py`: Validates GitHub webhook tokens and converts push
  events into jobs.
- `app/api/websocket.py`: Streams stored/live attempt logs and job status
  events to the frontend.

### Scheduling and execution

- `app/scheduler/job_manager.py`: Creates jobs, snapshots pipeline YAML, creates
  the first attempt, and enqueues work.
- `app/scheduler/lease_manager.py`: Owns claim, lease renewal, completion,
  stale-report rejection, retries, delayed promotion, and lease reaping.
- `app/scheduler/scheduler.py`: Runs periodic promotion and dead-worker/lease
  cleanup in the server lifecycle.
- `app/worker/worker.py`: Implements worker registration retry, heartbeat and
  lease-renewal threads, polling, pipeline parsing, log forwarding, and result
  reporting.
- `app/worker/docker_executor.py`: Pulls images, starts constrained temporary
  containers, performs Git checkout, executes steps, streams output, enforces
  wall-clock timeouts, and cleans up containers.

### AI subsystem

- `app/ai/analyzer.py`: Orchestrates log truncation, source-context extraction,
  provider invocation, validation, and persistence of analysis results.
- `app/ai/context_extractor.py`: Extracts likely source paths from failure logs
  and limits the amount of context sent for analysis.
- `app/ai/schemas.py`: Defines the allowed structured failure categories and
  required AI response fields.
- `app/ai/providers/base.py`: Defines the provider interface and provider error
  boundary.
- `app/ai/providers/mock_provider.py`: Provides deterministic local heuristics
  so the full stack works without an API key.
- `app/ai/providers/anthropic_provider.py`: Adapts the Anthropic API to the
  internal provider interface.

### Frontend

- `frontend/index.html`: Browser HTML entry point.
- `frontend/src/main.tsx`: Mounts the React application.
- `frontend/src/App.tsx`: Defines routes for projects, project details, jobs,
  and workers.
- `frontend/src/types.ts`: TypeScript models matching backend responses.
- `frontend/src/api/client.ts`: Centralizes REST requests and JSON handling.
- `frontend/src/styles.css`: Defines the dashboard layout, responsive styles,
  status badges, log terminal, and pipeline rail.
- `frontend/src/pages/Dashboard.tsx`: Lists projects and creates a project with
  the default Python pipeline.
- `frontend/src/pages/ProjectDetail.tsx`: Shows repository/pipeline metadata,
  webhook URL, recent jobs, and the manual trigger form.
- `frontend/src/pages/JobDetail.tsx`: Shows job status, attempts, logs, and AI
  analysis for a selected job.
- `frontend/src/pages/Workers.tsx`: Displays the worker fleet and heartbeat
  status.
- `frontend/src/components/JobList.tsx`: Renders project job summaries.
- `frontend/src/components/PipelineRail.tsx`: Visualizes attempt history and
  distinguishes success, infrastructure, and permanent failures.
- `frontend/src/components/LiveLogs.tsx`: Displays persisted and live logs.
- `frontend/src/components/AIAnalysisPanel.tsx`: Displays completed, invalid,
  and unavailable AI analysis states.
- `frontend/src/components/WorkerStatus.tsx`: Renders worker health and
  capacity details.
- `frontend/src/hooks/useWebSocket.ts`: Provides reconnecting log/status
  WebSocket hooks.
- `frontend/Dockerfile`: Builds the Vite application with Node and serves the
  result through nginx.
- `frontend/nginx.conf`: Serves the single-page app and proxies `/api/` and
  `/ws/` requests to the FastAPI server.
- `frontend/package.json`: Defines frontend dependencies and build/test scripts.
- `frontend/vite.config.ts`: Configures Vite development server and proxying.
- `frontend/tsconfig.json`: Enables strict TypeScript project compilation.
- `frontend/playwright.config.ts`: Configures browser tests and base URL.

### Tests

- `backend/tests/conftest.py`: Provides isolated SQLite, fakeredis, project,
  worker, and database fixtures.
- `backend/tests/test_pipeline_execution.py`: Tests YAML validation and mocked
  Docker success, checkout failure, allowed failure, and command failure.
- `backend/tests/test_scheduler.py`: Tests priority, FIFO order, empty queues,
  and duplicate-claim protection.
- `backend/tests/test_retries.py`: Tests permanent-failure handling, retry
  limits, and exponential backoff.
- `backend/tests/test_worker_failure.py`: Tests lease expiry, dead workers,
  immediate lease expiration, and stale completion rejection.
- `backend/tests/test_ai_validation.py`: Tests valid, malformed, unavailable,
  and schema-invalid AI responses.
- `frontend/tests/e2e/dashboard.spec.ts`: Tests the dashboard, project form,
  project creation, job trigger, and workers page against the live stack.

## How to run and demonstrate

### Prerequisites

Install Docker Desktop, enable Linux containers, and ensure Docker is running.
Node.js and Python are only needed when running checks outside containers.

### Start the full system

From the repository root:

```powershell
docker compose up --build --scale worker=3
```

Open `http://localhost:5173`. The API documentation is at
`http://localhost:8000/docs`, and the health endpoint is
`http://localhost:8000/api/health`.

### Demonstrate a public GitHub build

1. Open the dashboard and click **New project**.
2. Enter a public repository URL such as
   `https://github.com/octocat/Hello-World.git`.
3. Use a pipeline with `network: bridge` and at least one valid step:

```yaml
image: python:3.11-slim
timeout_seconds: 600
network: bridge
steps:
  - name: verify
    run: python --version
```

4. Open the project and click **Trigger build**.
5. Confirm the job changes from `queued` to `running` and then `succeeded` or
   `failed`, with logs visible on the job page.

For a Python repository with `requirements.txt` and tests, use:

```yaml
image: python:3.11-slim
timeout_seconds: 600
network: bridge
steps:
  - name: install
    run: pip install -r requirements.txt
  - name: test
    run: pytest -q
```

### Inspect and stop the system

```powershell
docker compose ps
docker compose logs -f worker
docker compose down
```

Use `docker compose down -v` only when you also want to delete PostgreSQL
data and start with a completely empty database.


### Run checks without Docker

```powershell
cd backend
python -m pip install -r requirements.txt
python -m pytest -v

cd ..\frontend
npm install
npm run build
```

The backend tests use fake Redis and fake Docker, so they validate scheduling
logic without a daemon. They do not replace the full-stack Docker test.

### Run browser tests

With the full stack running:

```powershell
cd frontend
npx playwright install chromium
npx playwright test
```

## Interview questions and answers

### Architecture

**Why separate Job and JobAttempt?** A Job is the desired execution of a
commit. An Attempt is one worker's try. This gives retries, attempt-specific
logs, leases, and AI analysis without overwriting history.

**Why PostgreSQL plus Redis?** PostgreSQL is the durable source of truth for
correctness. Redis is optimized for queue ordering, delayed retries, and
Pub/Sub. Losing Redis should not change the recorded job facts, although a
reconciliation mechanism is needed to restore missing queue entries.

**Why do workers pull instead of the server pushing?** A worker asks for work
when it is ready. This avoids maintaining a central live capacity map and
handles elastic workers naturally.

**What happens when a worker dies?** Heartbeats become stale, the reaper marks
the worker dead and expires its lease, and the attempt is retried as an
infrastructure failure if the retry budget remains.

### Distributed systems

**What is a lease token?** It is an unguessable ownership token attached to an
attempt. Renewal, log writes, and completion require the matching token, so a
stale worker cannot update a reassigned or terminal attempt.

**Is execution exactly once?** No. It is at-least-once. A worker can complete
the command and die before the completion request, so the server may retry it.
Pipeline commands should therefore be idempotent where possible.

**Can Redis pop and PostgreSQL claim be atomic together?** Not in this design.
Redis removal and database commit are separate operations. A production version
could use a PostgreSQL outbox/reconciliation process or make PostgreSQL the
claim authority and Redis only a wake-up queue.

**Why are test failures not retried?** A failed test usually represents the
commit's actual behavior. Retrying wastes resources and can hide signal. Docker
failure, checkout failure, timeout, and lease expiry are infrastructure
failures and are retryable.

**Why use a priority score?** Redis sorts by a score that combines negative
priority and enqueue time. Higher priority comes first; equal priorities remain
FIFO.

### Docker and security

**Why use Docker siblings instead of Docker-in-Docker?** The worker talks to
the host Docker daemon through the mounted socket and launches job containers
beside itself. This avoids nested daemon complexity, though the socket is a
high-privilege capability and needs stronger isolation in production.

**Why is the default network bridge?** Remote Git checkout needs network access.
Users can select `none` for offline pipelines, but an offline pipeline cannot
clone a remote repository unless source is provided another way.

**How are commands isolated?** Each run gets a temporary container, explicit
CPU/memory limits, a working directory, a configured network mode, a deadline,
and cleanup in a `finally` block.

**What are the risks of accepting arbitrary YAML commands?** Pipeline authors
can execute shell commands inside the job container. The Docker socket and
network policy are security boundaries, not complete sandboxing. A production
system would use stronger isolation, image allowlists, credentials management,
resource quotas, and authenticated APIs.

### AI and frontend

**Can AI mark a build successful?** No. The server finalizes the CI status
before analysis. AI output is schema-validated, stored per attempt, and shown
only as a suggestion.

**Why truncate logs and extract paths?** Sending the full repository or full
log is expensive and noisy. The analyzer sends bounded recent logs and likely
relevant source files.

**How does live logging work?** The worker posts chunks to the API. The API
persists them in PostgreSQL and publishes them through Redis Pub/Sub. A
WebSocket forwards those chunks to the browser while REST provides job state.

**What would you improve next?** Add authenticated APIs, private-repository
credentials, an outbox/reconciliation queue, row-level claim guards, worker
capacity enforcement, cancellation, asynchronous AI jobs, Alembic migrations,
real PostgreSQL/Redis integration tests, and stronger sandboxing.

## Known limitations (by design, for a portfolio project)

- Auth is intentionally minimal (a webhook token per project); there's no
  user/org model. A localized change to add JWT-based auth would slot into
  the existing `jwt_secret` config value and a dependency on the API routers.
- Table creation uses `Base.metadata.create_all` rather than Alembic
  migrations, so the stack runs with zero setup steps. A real deployment
  would use versioned migrations instead.
- The AI analysis call runs synchronously inside the `/complete` request
  handler for simplicity. A production system would push it onto a
  background task queue so a slow LLM call can never add latency to the
  worker's completion report.
