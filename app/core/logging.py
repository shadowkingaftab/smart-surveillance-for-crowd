import logging
from pathlib import Path
from .config import settings


def configure_logging() -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.logs_dir / "system.log", encoding="utf-8"),
        ],
        force=True,
    )
