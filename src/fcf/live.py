"""fcf live：輪詢高公局近期 M05A 檔，滾動預測並輸出 dashboard/data/live.json。"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .calendar import is_holiday
from .corridor import SEG_IDS
from .features import STEP_MIN, build_features
from .http import BASE, fetch
from .notify import send_line
from .replay import DASH_DATA, Lookup, corridor_json, make_frames
from .tdcs import parse_m05a_rows

WINDOW = 7  # 保留最近 7 個時間點
KEEP_FRAMES = 12
FILE_RE = re.compile(r"TDCS_M05A_(\d{8})_(\d{6})\.csv")
TZ = ZoneInfo("Asia/Taipei")
LIVE_PATH = DASH_DATA / "live.json"


def log(msg: str) -> None:
    print(f"[live {datetime.now(TZ):%H:%M:%S}] {msg}", file=sys.stderr, flush=True)


def _dir_url(t: datetime) -> str:
    return f"{BASE}/history/TDCS/M05A/{t:%Y%m%d}/{t:%H}/"


def _file_url(t: datetime) -> str:
    return f"{BASE}/history/TDCS/M05A/{t:%Y%m%d}/{t:%H}/TDCS_M05A_{t:%Y%m%d}_{t:%H%M}00.csv"


def find_latest(now: datetime) -> datetime | None:
    """列出目錄找最大檔名；該小時 404 或沒有檔案就查前一小時。"""
    for back in (0, 1):
        t = now - timedelta(hours=back)
        try:
            html = fetch(_dir_url(t)).decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        names = FILE_RE.findall(html)
        if names:
            d, hms = max(names)
            return datetime.strptime(d + hms, "%Y%m%d%H%M%S")
    return None


def fetch_slot(t: datetime) -> list[tuple]:
    text = fetch(_file_url(t)).decode("utf-8", "ignore")
    return parse_m05a_rows(text.splitlines(), set(SEG_IDS))


def to_df(slots: dict[datetime, list[tuple]]) -> pd.DataFrame:
    """滾動資料 → 與 dataset 同欄位的長表（含 ffill(limit=3)）。"""
    rows = [r for t in sorted(slots) for r in slots[t]]
    df = pd.DataFrame(rows, columns=["ts", "seg", "speed", "volume"]).drop_duplicates(["ts", "seg"], keep="last")
    idx = pd.date_range(min(slots), max(slots), freq=f"{STEP_MIN}min")
    full = pd.MultiIndex.from_product([idx, SEG_IDS], names=["ts", "seg"])
    df = df.set_index(["ts", "seg"]).reindex(full).reset_index()
    df["speed"] = df.groupby("seg")["speed"].ffill(limit=3)
    df["is_holiday"] = df["ts"].dt.normalize().map(lambda d: int(is_holiday(d))).astype("int8")
    return df


def run_live(push: bool = False, poll: int = 120) -> None:
    from .model import (load_capacity, load_classifiers, load_models, load_profile,
                        predict_from_features, predict_proba_from_features)

    models, profile, capacity = load_models(), load_profile(), load_capacity()
    clfs = load_classifiers()
    thresholds = {h: c["threshold"] for h, c in clfs.items()}
    slots: dict[datetime, list[tuple]] = {}
    frames: list[dict] = []
    last_push: datetime | None = None
    last_ts: datetime | None = None
    DASH_DATA.mkdir(parents=True, exist_ok=True)
    corridor = corridor_json()

    while True:
        try:
            now = datetime.now(TZ).replace(tzinfo=None)
            latest = find_latest(now)
            if latest is None:
                log("no files found")
            elif last_ts is None or latest > last_ts:
                # 冷啟動：最新檔往回 7 個；之後只補新檔
                t = latest - timedelta(minutes=STEP_MIN * (WINDOW - 1)) if last_ts is None \
                    else last_ts + timedelta(minutes=STEP_MIN)
                new_ts: list[datetime] = []
                while t <= latest:
                    try:
                        slots[t] = fetch_slot(t)
                        new_ts.append(t)
                    except urllib.error.HTTPError as e:
                        log(f"slot {t:%H:%M} HTTP {e.code}, skipped")
                    t += timedelta(minutes=STEP_MIN)
                for old in sorted(slots)[:-WINDOW]:
                    del slots[old]
                last_ts = latest
                if new_ts:
                    df = to_df(slots)
                    feats = build_features(df, profile)
                    lk = Lookup(feats, predict_from_features(feats, models),
                                predict_proba_from_features(feats, clfs), thresholds)
                    ts_list = [pd.Timestamp(x) for x in sorted(new_ts) if x in slots]
                    new_frames = make_frames(lk, capacity, ts_list, last_push)
                    for f in new_frames:
                        if f["decision"]["push"]:
                            last_push = datetime.strptime(f["ts"], "%Y-%m-%dT%H:%M")
                    frames = (frames + new_frames)[-KEEP_FRAMES:]
                    out = {"date": f"{now:%Y-%m-%d}", "generated_at": f"{now:%Y-%m-%dT%H:%M:%S}",
                           "corridor": corridor, "frames": frames}
                    LIVE_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
                    newest = new_frames[-1]
                    log(f"updated ts={newest['ts']} reason={newest['decision']['reason']}")
                    if push and newest["decision"]["push"]:
                        send_line(newest["decision"]["message"])
            else:
                log(f"no new file (latest {latest:%H:%M})")
        except Exception as e:  # noqa: BLE001  網路例外只記錄，迴圈繼續
            log(f"error: {type(e).__name__}: {e}")
        time.sleep(poll)
