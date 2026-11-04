"""Optional alerts: set TRADEBOT_WEBHOOK_URL to a Slack/Discord-compatible webhook."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)


def notify(text: str) -> None:
    log.info("NOTIFY: %s", text)
    url = os.environ.get("TRADEBOT_WEBHOOK_URL")
    if not url:
        return
    body = json.dumps({"text": text, "content": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as exc:
        log.warning("webhook failed: %s", exc)
