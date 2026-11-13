from pathlib import Path
from ultralytics import YOLO
from app.core.config import settings

settings.model_dir.mkdir(parents=True, exist_ok=True)
for name in [settings.detector_model, settings.pose_model]:
    model = YOLO(name)
    source = Path(model.ckpt_path) if getattr(model, 'ckpt_path', None) else None
    target = settings.model_dir / name
    if source and source.exists():
        target.write_bytes(source.read_bytes())
        print(f"Saved {target}")
    else:
        print(f"Loaded {name}; place the weight file at {target} for fully offline startup.")
