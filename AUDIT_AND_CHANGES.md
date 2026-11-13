# Audit & Change Log

## What was audited first
The uploaded project (`Intelligent_Video_Intelligence`) was a working **single-camera**
reference pipeline (~640 lines) with real strengths that were preserved, not rewritten:

- `app/services/detection.py` — YOLO + ByteTrack, already multi-class (no class filter),
  so "person / car / dog / ..." classification already existed at the detector level.
- `app/services/pose.py` — visibility-tiered pose analysis (FULL_BODY / UPPER_BODY /
  FACE_ONLY / PARTIAL / UNKNOWN) — exactly the "don't guess from missing data" principle
  the brief asks for. **Kept as-is.**
- `app/services/fusion.py` — temporal evidence accumulator, refuses to alert on a single
  frame or a single signal (sitting/lying alone never trips an alert). **Kept, extended.**
- `app/services/face.py` — face analysis only runs when the face is large enough; emotion
  is explicitly "context only," never a standalone trigger. **Kept as-is.**
- `app/services/scene.py` — pairwise proximity/IoU relationship detector. **Kept, extended
  for crowd density.**
- `app/services/db.py` — SQLAlchemy models, Postgres-capable via `DATABASE_URL`. **Kept,
  extended with new tables.**

## What was missing against the brief, and what was added
| Gap vs. brief | New file(s) |
|---|---|
| Multi-camera / multi-device concurrent input | `app/services/input_manager.py` |
| Explicit human/animal/vehicle/other classification layer | `app/services/classification.py` |
| Incident-type taxonomy (accident, violence, robbery/intrusion, dangerous activity, crowd anomaly, vehicle incident) | `app/services/incidents.py` |
| Crowd/multi-person simultaneous analysis with anomaly baseline | `app/services/scene.py` (extended) |
| Cross-camera track linking (non-claiming, confidence-scored) | `app/services/reid.py` |
| Async per-camera workers, bounded queues, reconnect/backoff, graceful shutdown | `app/services/worker.py`, `run_multi.py` |
| Non-blocking alert delivery | `app/services/alerts.py` (extended with worker thread) |
| Privacy retention/deletion controls | `app/services/privacy.py`, `tools/retention_cleanup.py` |
| Production Postgres schema as explicit migration | `db/migrations/0001_init.sql` |
| Multi-camera config format | `config/cameras.example.yaml` |
| Camera/incident/retention API surface | `app/api/main.py` (extended) |
| Dashboard: per-camera, per-incident-type breakdown | `dashboard.py` (extended) |

## What was explicitly *not* changed
- The core "don't guess" philosophy (`UNKNOWN`/`INSUFFICIENT_DATA` instead of invented
  classifications) — this was already correct and is now applied consistently through the
  new classification/incident layers.
- The temporal fusion thresholds — extended with new signals, not replaced.
- SQLite remains the zero-setup local fallback; PostgreSQL remains the production target.

## Known, stated limitations (not silently hidden)
- Cross-camera re-identification uses a color-histogram similarity score, not a learned
  ReID embedding. It is deliberately conservative: below the confidence threshold it stores
  tracks as **separate**, never merges identities on weak evidence.
- True OS-level multi-process isolation per camera (for hard fault isolation and full CPU
  parallelism) is supported via running `run_multi.py --camera-id <id>` once per process
  (e.g., one per docker-compose service) in addition to the in-process threaded mode used by
  default for the single-machine demo.
- "Violence/fight" and "dangerous activity" detection are heuristic (sustained high relative
  motion + sustained proximity between people), not a trained action-recognition model. The
  architecture isolates this in `incidents.py` so a trained classifier can be dropped in
  without touching the rest of the pipeline.

---

## Second pass: audit of the "FINAL" package itself

Before changing anything, this package was audited against its own claims above,
per the brief's "audit first, do not assume" requirement. Result: **the project
as packaged could not run.**

### Critical bugs found and fixed
| Bug | Impact | Fix |
|---|---|---|
| `app/services/pipeline.py` was missing from the new `app/services/` tree (only existed in the old nested `Intelligent_Video_Intelligence/` copy) | `run.py` crashed on import — the entrypoint could not start at all | Rebuilt `pipeline.py`, now wiring detection → classification → tracking → pose/face → scene/crowd/zone → fusion → incident classification → cross-camera linking → DB, per camera |
| `requirements.txt` missing `pyyaml` | `app/core/config.py` imports `yaml` unconditionally — any import of config (i.e. almost everything) crashed with `ModuleNotFoundError` | Added `pyyaml>=6,<7` |
| `app/services/worker.py`, `run_multi.py`, `db/migrations/0001_init.sql`, `config/cameras.example.yaml` were documented above as delivered but were **not present in the package** | No multi-camera entrypoint existed at all despite `input_manager.py` and `reid.py` being fully built for it | All four written: `worker.py` (per-camera thread, resilient per-frame error handling, correct pre/post evidence capture), `run_multi.py` (multi-camera entrypoint, tiled display, single-key/signal shutdown, periodic status logging + GC), the SQL migration, the example YAML config |

### Also added in this pass
- `DEMO_MODE` (synthetic detector/pose/face in `detection.py`/`pose.py`/`face.py`, selected via new `build_detector()`/`build_pose_analyzer()`/`build_face_analyzer()` factories) — the brief's "testing/demo mode" requirement, lets the full pipeline be exercised with zero ML dependencies, GPU, or camera hardware.
- `app/api/main.py`: added `/cameras`, `/incidents` (filterable by camera/type), `POST /retention/run` — these were promised but not actually added to the API in the previous pass.
- `dashboard.py`: camera health table, incidents-by-type and incidents-by-camera charts.
- `recorder.py`/`worker.py`: fixed an evidence-clip timing bug — the previous design would have saved whatever was in the *live* rolling pre-buffer at the moment the post-event window ended (by then overwritten with post-event frames), rather than the actual pre-event frames. `EvidenceRecorder.snapshot()` now captures the pre-buffer the instant an incident fires; `save()` accepts that snapshot explicitly.
- `.env.example`: added every setting `config.py` actually reads that was missing from the example file (`DEMO_MODE`, `CAMERAS_CONFIG`, performance/retention/re-ID/crowd settings).
- Removed the redundant nested `Intelligent_Video_Intelligence/` copy of the original single-camera project from the final package — it duplicated (and partially conflicted with) the top-level `app/`, and keeping both was itself a source of the missing-`pipeline.py` bug. Its working logic was reviewed and folded into the new `app/services/pipeline.py`; nothing in it is lost.

### Verified this pass (what could and could not be executed here)
`cv2`, `numpy`, `pyyaml`, and `python-dotenv` were available in the audit sandbox; `sqlalchemy`, `fastapi`, `ultralytics`, `deepface`, and `requests` were not (no network access to install them). So:
- **Executed directly:** every `*.py` file compiles (`py_compile`) with zero errors; `tests/test_fusion.py`'s two cases pass; and a standalone script ran the full non-DB chain end-to-end in demo mode — synthetic detection → classification (human/animal/vehicle correctly separated) → tracking → scene relationships/crowd baseline → zone-intrusion check → pose/face (demo) → multi-signal fusion → incident typing → cross-camera candidate linking → evidence clip writing (actual `.mp4` file produced and verified on disk).
- **Verified by interface tracing, not execution:** every call into `db.py` (`init_db`, `add_incident`, `add_observations`, `list_cameras`, `list_incidents`, retention functions) and the FastAPI/SQLAlchemy/Ultralytics/DeepFace-backed code paths, by checking each call site's arguments against each function's actual signature.
- **Recommended before relying on this in production:** `pip install -r requirements.txt` in a networked environment, then run `pytest`, `DEMO_MODE=true python run_multi.py --no-display` for a few minutes, and a short real-camera smoke test, in that order.
