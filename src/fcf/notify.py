"""LINE Messaging API push。缺 token / userId 時 dry-run。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .http import SSL_CTX

PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send_line(text: str) -> None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user = os.environ.get("LINE_USER_ID")
    if not token or not user:
        print(f"[DRY-RUN] LINE -> {text}")
        return
    body = json.dumps({"to": user, "messages": [{"type": "text", "text": text}]}).encode()
    req = urllib.request.Request(
        PUSH_URL, data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            if resp.status != 200:
                raise RuntimeError(f"LINE push failed {resp.status}: {resp.read().decode()}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LINE push failed {e.code}: {e.read().decode()}") from e
    print("[LINE] sent")


def notify_test() -> None:
    from datetime import datetime

    from .diversion import format_message

    text = format_message(datetime(2026, 8, 12, 7, 30), "ground", "elevated",
                          "中壢-中豐", 28, 540, 0.15)
    send_line(text)
