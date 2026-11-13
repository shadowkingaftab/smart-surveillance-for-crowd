# Architecture

1. Input: CCTV/IP camera/webcam/body/vehicle camera.
2. Ingestion: bounded frame loop with target FPS and graceful shutdown.
3. Detection/classification: YOLO model returns human/animal/vehicle/object classes and confidence.
4. Tracking: ByteTrack via Ultralytics keeps multiple entities active simultaneously.
5. Adaptive analysis: pose and face analysis run only when applicable and at lower frequencies.
6. Temporal fusion: per-track evidence history prevents one-frame decisions.
7. Incident classification: only sustained multi-signal evidence reaches REVIEW/INCIDENT_CANDIDATE.
8. Evidence: pre-event ring buffer + post-event recording can be attached to an event store.
9. Persistence: PostgreSQL for metadata/events; object storage for video in production.
10. API/dashboard: FastAPI serves the JSON API and the static operations console (`frontend/`); Streamlit remains an optional secondary dashboard.

For scale, run independent edge workers per camera group and introduce Redis/Kafka between ingestion and analysis when throughput requires it. Do not add a broker merely for appearance; operational simplicity is preferable until measured load requires it.
