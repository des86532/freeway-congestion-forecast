"""HTTP 存取。所有對 tisvcloud 的請求都必須經過 fetch()：
SSL 修正 + 同 host 請求間隔 > 40 秒（高公局交通資料庫注意事項第 10 條）。"""
from __future__ import annotations

import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

THROTTLED_HOST = "tisvcloud.freeway.gov.tw"
BASE = f"https://{THROTTLED_HOST}"

SSL_CTX = ssl.create_default_context()
# Python 3.13 預設 strict 會因 Missing Subject Key Identifier 驗證失敗
SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT

_last_request: dict[str, float] = {}


def _throttle(host: str, min_interval: float) -> None:
    if host != THROTTLED_HOST:
        return
    last = _last_request.get(host)
    if last is not None:
        wait = min_interval - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    _last_request[host] = time.monotonic()


def fetch(url: str, *, min_interval: float = 41.0) -> bytes:
    host = urlparse(url).hostname or ""
    req = urllib.request.Request(url, headers={"User-Agent": "fcf/0.1"})
    last_exc: Exception | None = None
    for attempt in range(3):
        _throttle(host, min_interval)
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:  # 不重試
                raise
            last_exc = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as e:
            last_exc = e
        print(f"[http] retry {attempt + 1}/3 {url}: {last_exc}", file=sys.stderr)
    assert last_exc is not None
    raise last_exc
