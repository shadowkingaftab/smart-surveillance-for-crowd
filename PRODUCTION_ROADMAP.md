# Production rollout roadmap

## Phase 1 — single edge machine
- One camera/webcam.
- PostgreSQL.
- Detection + ByteTrack + adaptive pose.
- Event review dashboard.
- Benchmark latency and false alerts.

## Phase 2 — multi-camera
- Camera registry.
- One worker per camera/group.
- UTC timestamps and camera health.
- Shared PostgreSQL + object storage.

## Phase 3 — distributed processing
- Add Redis/Kafka only after measured queue pressure.
- GPU worker pool.
- Model version registry.
- Metrics and tracing.

## Phase 4 — validated incident models
- Build labelled datasets for each incident class.
- Train/evaluate temporal models.
- Calibrate thresholds per environment.
- Human verification workflow.

## Phase 5 — hardening
- TLS, secrets manager, RBAC, audit logs.
- Backup/restore.
- Monitoring and alert delivery retries.
- Privacy/retention controls.
- Security and legal review.
