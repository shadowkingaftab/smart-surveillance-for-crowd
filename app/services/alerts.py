from __future__ import annotations
import logging
import requests
from app.core.config import settings
log = logging.getLogger(__name__)

class AlertService:
    def send(self, payload: dict) -> bool:
        if not settings.enable_alerts or not settings.alert_webhook_url:
            return False
        try:
            r = requests.post(settings.alert_webhook_url, json=payload, timeout=3)
            r.raise_for_status()
            return True
        except Exception as exc:
            log.error("alert delivery failed: %s", exc)
            return False
