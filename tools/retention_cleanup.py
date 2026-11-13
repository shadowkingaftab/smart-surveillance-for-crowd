"""Run the configured privacy retention sweep once and exit.

Usage:
    python tools/retention_cleanup.py

Intended to be run on a schedule (cron / systemd timer / Windows Task
Scheduler) rather than continuously, so retention is enforced independent of
whether the capture pipeline is currently running.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.logging import configure_logging
from app.services.db import init_db
from app.services.privacy import run_retention_sweep


def main() -> None:
    configure_logging()
    init_db()
    summary = run_retention_sweep()
    print(summary)


if __name__ == "__main__":
    main()
