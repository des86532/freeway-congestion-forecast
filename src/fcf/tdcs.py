"""高公局 TDCS M05A 解析與歷史下載。
CSV 無表頭：TimeStamp,GantryFrom,GantryTo,VehicleType,Speed,Volume"""
from __future__ import annotations

import math
import tarfile
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

from .http import BASE, fetch

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
NAN = math.nan


def parse_m05a_rows(lines: Iterable[str], seg_ids: set[str]) -> list[tuple]:
    """回傳 (ts, seg, speed, volume)。speed<=0 → NaN；volume<0 → NaN。"""
    out: list[tuple] = []
    for line in lines:
        parts = line.strip().split(",")
        if len(parts) < 6 or parts[3] != "31":
            continue
        seg = f"{parts[1]}-{parts[2]}"
        if seg not in seg_ids:
            continue
        try:
            ts = datetime.strptime(parts[0], "%Y/%m/%d %H:%M")
            speed = float(parts[4])
            volume = float(parts[5])
        except ValueError:
            continue
        out.append((ts, seg, speed if speed > 0 else NAN, volume if volume >= 0 else NAN))
    return out


def tar_path(d: date) -> Path:
    return RAW_DIR / f"M05A_{d:%Y%m%d}.tar.gz"


def _readable(p: Path) -> bool:
    if not p.exists():
        return False
    try:
        with tarfile.open(p) as tf:
            tf.getmembers()
        return True
    except (tarfile.ReadError, EOFError, OSError):
        return False


def fetch_history(start: date, end: date, min_interval: float = 41.0) -> list[date]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    failed: list[date] = []
    d = start
    while d <= end:
        p = tar_path(d)
        if _readable(p):
            d += timedelta(days=1)
            continue
        url = f"{BASE}/history/TDCS/M05A/M05A_{d:%Y%m%d}.tar.gz"
        try:
            data = fetch(url, min_interval=min_interval)
            p.write_bytes(data)
            if not _readable(p):
                p.unlink(missing_ok=True)
                raise tarfile.ReadError("unreadable tar")
            print(f"[fetch-history] ok {d}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[fetch-history] FAIL {d}: {e}", flush=True)
            failed.append(d)
        d += timedelta(days=1)
    return failed


def read_tar_rows(p: Path, seg_ids: set[str]) -> list[tuple]:
    rows: list[tuple] = []
    with tarfile.open(p) as tf:
        for m in tf:
            if not m.isfile():
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            rows.extend(parse_m05a_rows(f.read().decode("utf-8", "ignore").splitlines(), seg_ids))
    return rows
