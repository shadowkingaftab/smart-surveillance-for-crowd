# Security, privacy and deployment checklist

Before a real deployment:
- Use PostgreSQL with TLS and least-privilege credentials.
- Keep camera networks segmented from public networks.
- Authenticate every camera/edge worker.
- Encrypt evidence at rest and in transit.
- Define retention periods; avoid indefinite raw-video storage.
- Restrict access to identifiable footage and maintain audit logs.
- Keep normal operation metadata-only where possible; store clips around validated events.
- Add human review before high-impact action.
- Never treat facial expression as proof of mental state or intent.
- Never treat an object classification as proof that a person committed a crime.
- Test across lighting, camera angles, crowd density, occlusion and representative populations.
- Review every model/software license before commercial deployment.
- Establish incident response, backup and disaster-recovery procedures.
