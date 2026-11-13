# Intelligent Video Intelligence Platform

Production-oriented reference implementation for multi-camera, multi-entity video analysis.

## What it does
- Accepts webcam, local video, or RTSP input.
- Detects humans, animals, vehicles and other configured objects.
- Tracks multiple entities simultaneously with persistent track IDs.
- Uses visibility-aware pose analysis: full body, upper body, face-only, partial, unknown.
- Runs face-expression analysis only when face quality is sufficient; expression is contextual evidence, never a standalone danger decision.
- Uses temporal evidence accumulation instead of single-frame alerts.
- Classifies candidate incidents such as fall, collision, violent interaction and crowd disturbance using multi-signal fusion.
- Stores only entity observations and confirmed/candidate events by default; event clips use pre/post buffers.
- PostgreSQL is the production metadata database. Local SQLite is available only for development fallback.
- FastAPI exposes health, camera, entity and event APIs, and serves a dependency-free operations console at `/`.
- Streamlit dashboard provides monitoring and event review.
- Graceful shutdown, bounded queues, FPS throttling, camera-health monitoring and structured logging are included.

## Important production statement
This is a production-oriented architecture and runnable reference implementation, not a certified safety-critical or law-enforcement product. Before deployment, validate model performance on representative data, review model/software licenses, perform security/privacy/legal review, and establish human verification procedures.

## Quick start

1. Python 3.11 recommended.
2. Install dependencies:
   `python -m pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and keep `DATABASE_URL` as SQLite for the first local test, or configure PostgreSQL (see `docker-compose.yml` for a local Postgres container).
4. Download model weights once (optional — they also auto-download on first run):
   `python tools/download_models.py`

### Single camera (legacy/simple mode)
`python run.py --source 0`

### Multiple cameras (production mode)
1. Edit `config/cameras.example.yaml` (or copy it to `config/cameras.yaml`) with your camera sources.
2. Point `.env`'s `CAMERAS_CONFIG` at that file.
3. `python run_multi.py` — starts one capture thread + one processing worker per camera, tiles all feeds into one window. Press **`q`** in the window, or **Ctrl+C**, to shut down everything cleanly.
   - `--no-display` for headless/server operation.
   - `--camera-id CAM-01` to run only one camera in this process — use this once per process (e.g. one per `docker-compose` service) if you want OS-level fault isolation between cameras instead of the default in-process threaded mode.

### Testing/demo mode (no GPU, no model weights, no camera needed)
Set `DEMO_MODE=true` in `.env` (or `DEMO_MODE=true python run.py` / `run_multi.py`). A synthetic detector/pose/face layer feeds realistic-looking moving entities through the *real* classification → tracking → fusion → incident → DB pipeline, so you can verify the whole system end-to-end — dashboard, API, DB rows — without any ML dependencies or hardware. **Never use demo mode as evidence the detection itself works on real footage** — it only exercises the pipeline around the detector.

### Web console and API
FastAPI serves the operations console in `frontend/` at the root, so there is no Node build step or separate web server:
- Start: `uvicorn app.api.main:app --host 127.0.0.1 --port 8000`, then open <http://127.0.0.1:8000/>.
- Views: overview (KPIs, 24h activity, incident-type mix, camera fleet), incident queue with search/type/camera/severity/time filters and a reasoning + metadata drawer, camera health grid, and system health/retention controls. It refreshes every 5 seconds and shows an offline banner instead of breaking when the API is down.
- Preview the console with representative data, no camera or model weights required: `python tools/seed_demo_data.py --reset` (SQLite only; refuses to clear PostgreSQL without `--force`).
- **Live camera**: the topbar camera button opens this laptop's webcam and draws a box around each detected face — green for neutral/happy/surprised, red for angry/sad/fearful/disgusted — with a live expression readout. Detection runs entirely inside the browser tab using the vendored `@vladmandic/face-api` tiny detector and expression model in `frontend/vendor/face-api/` (license note alongside); frames are never uploaded, stored, or sent to the API. It needs camera permission and a secure origin (`127.0.0.1`/`localhost` counts), and uses hardware WebGL when available, falling back to CPU otherwise.
- The same server exposes the API:
  - `GET /health`, `GET /cameras`, `GET /incidents?camera_id=&incident_type=&limit=`, `GET /events` (deprecated alias), `POST /retention/run`
  - `GET /docs` for interactive OpenAPI documentation
- The original Streamlit dashboard remains available as an alternative: `streamlit run dashboard.py`.

### Database migration (explicit, for review/CI)
`init_db()` (SQLAlchemy `create_all`) creates tables automatically on first run. `db/migrations/0001_init.sql` is the same schema expressed explicitly, for teams that want to review/apply it through a migration tool: `psql "$DATABASE_URL" -f db/migrations/0001_init.sql`.

### Retention
Run once (cron/systemd timer/Task Scheduler): `python tools/retention_cleanup.py`, or trigger on demand via `POST /retention/run`.

The first Ultralytics/DeepFace model initialization may download model weights. After weights are present in `data/models`, inference can be performed without internet access.

## Production deployment shape
Camera/IP stream -> Input manager (per-camera capture thread, bounded queue, reconnect/backoff) -> per-camera worker (detection -> classification -> tracking -> selective pose/face -> temporal fusion -> incident classification -> alert) -> shared PostgreSQL + evidence storage -> alert adapter/API/dashboard.

`run_multi.py` runs all configured cameras as threads in one process by default — appropriate for a single edge machine. For OS-level process isolation per camera, run `run_multi.py --camera-id <id>` once per process (one per `docker-compose` service, say), all pointed at the same PostgreSQL instance. Redis/Kafka can be introduced as the message bus when throughput requires it; the included system deliberately starts without a mandatory broker so it remains easy to deploy on one edge machine.

## Known, stated limitations
- Cross-camera re-identification (`app/services/reid.py`) uses a color-histogram similarity score, not a learned ReID embedding model. It is deliberately conservative — below threshold it never merges identities, only stores tracks as separate.
- "Violence/fight" and "dangerous activity" detection (`app/services/incidents.py`) are heuristic (sustained close contact + sustained elevated motion across multiple frames), not a trained action-recognition model. The architecture isolates this so a trained classifier can be dropped in without touching the rest of the pipeline.
- The live camera's expression readout is a coarse 7-class facial-expression estimate, not a diagnosis of mood, mental health, or intent; lighting, pose, occlusion and cultural differences all affect it.
- The in-process multi-camera mode (default `run_multi.py`) gives thread-level, not full OS-process-level, fault isolation between cameras; use `--camera-id` per process if you need the latter.
