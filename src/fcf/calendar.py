"""2026 辦公日曆（行政院人事行政總處）。未涵蓋的日期以週六日判定。"""
from __future__ import annotations

import csv
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

CALENDAR_PATH = Path(__file__).resolve().parents[2] / "data" / "static" / "calendar_2026.csv"
CALENDAR_URL = (
    "https://www.dgpa.gov.tw/FileConversion?filename=dgpa/files/202506/"
    "a52331bd-a189-466b-b0f0-cae3062bbf74.csv&nfix=&name=115.csv"
)


@lru_cache(maxsize=1)
def _load() -> dict[str, bool]:
    if not CALENDAR_PATH.exists():
        return {}
    out: dict[str, bool] = {}
    with CALENDAR_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            out[row["西元日期"].strip()] = row["是否放假"].strip() == "2"
    return out


def is_holiday(d: date | datetime) -> bool:
    if isinstance(d, datetime):
        d = d.date()
    cal = _load()
    key = d.strftime("%Y%m%d")
    if key in cal:
        return cal[key]
    return d.weekday() >= 5
