"""重播：逐 5 分鐘產生 frame（實際／預測／路線 TT／分流決策），輸出儀表板用 JSON。"""
from __future__ import annotations

import json
import math
from datetime import datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .corridor import ENTRY_SEGMENT, ROUTES, SEG_IDS, SEGMENTS, route_segments
from .diversion import CONGESTED_KMH, MIN_SPEED_FOR_TT, decide, route_travel_time
from .features import HORIZONS, TEST, build_features
from .http import BASE

ROOT = Path(__file__).resolve().parents[2]
DASH_DATA = ROOT / "dashboard" / "data"
GEOM_PATH = ROOT / "data" / "static" / "corridor_geometry.json"


def _num(x, nd: int = 1):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else round(x, nd)


def _row(wide: pd.DataFrame, ts) -> dict[str, float | None]:
    return {s: _num(v) for s, v in wide.loc[ts].items()}


class Lookup:
    """由 build_features 輸出與 predict 結果建立的 (ts × seg) 寬表。
    probs 為各時距的壅塞機率，thresholds 為各時距的預警門檻。"""

    def __init__(self, feats: pd.DataFrame, preds: dict[int, pd.Series],
                 probs: dict[int, pd.Series], thresholds: dict[int, float]):
        self.actual = feats["speed_lag0"].unstack("seg_")[SEG_IDS]
        self.volume = feats["volume_lag0"].unstack("seg_")[SEG_IDS]
        self.pred = {h: p.unstack("seg_")[SEG_IDS] for h, p in preds.items()}
        self.prob = {h: p.unstack("seg_")[SEG_IDS] for h, p in probs.items()}
        self.thresholds = thresholds


def _clean_speeds(d: dict[str, float | None]) -> dict[str, float]:
    return {k: (math.nan if v is None else v) for k, v in d.items()}


def make_frames(lk: Lookup, capacity: dict[str, float], ts_list: list[pd.Timestamp],
                last_push: datetime | None = None) -> list[dict]:
    frames = []
    for ts in ts_list:
        actual = _row(lk.actual, ts)
        pred = {str(h): _row(w, ts) for h, w in lk.pred.items()}
        vols = {ENTRY_SEGMENT[r]: float(lk.volume.at[ts, ENTRY_SEGMENT[r]]) for r in ROUTES}
        a, p30 = _clean_speeds(actual), _clean_speeds(pred["30"])
        dec = decide(ts.to_pydatetime(), a, p30, vols, capacity, last_push)
        if dec.push:
            last_push = ts.to_pydatetime()
        dd = dec.to_dict()
        prob = {str(h): {s: _num(v, 2) for s, v in w.loc[ts].items()} for h, w in lk.prob.items()}
        raw_actual = lk.actual.loc[ts]
        alarm = {  # 當下未壅塞且壅塞機率達門檻的路段（依 SEG_IDS 順序）
            str(h): [s for s in SEG_IDS
                     if raw_actual[s] >= CONGESTED_KMH and w.at[ts, s] >= lk.thresholds[h]]
            for h, w in lk.prob.items()
        }
        for k in ("saving_naive_s", "saving_quota_s", "alt_tt_naive_s", "alt_tt_quota_s", "tt_slow_s", "tt_fast_s",
                  "sys_saving_quota_veh_s", "sys_saving_naive_veh_s"):
            dd[k] = _num(dd[k], 0)
        dd["p_star"] = _num(dd["p_star"], 2)
        frames.append({
            "ts": ts.strftime("%Y-%m-%dT%H:%M"),
            "actual": actual,
            "pred": pred,
            "route_tt": {
                "actual": {r: _num(route_travel_time(a, r), 0) for r in ROUTES},
                "pred30": {r: _num(route_travel_time(p30, r), 0) for r in ROUTES},
            },
            "decision": dd,
            "prob": prob,
            "alarm": alarm,
        })
    return frames


def corridor_json() -> dict:
    geom = json.loads(GEOM_PATH.read_text())
    return {"segments": [
        {"id": s.id, "route": s.route, "order": s.order, "distance_km": s.distance_km,
         "description": s.description, "coords": geom.get(s.id, [])}
        for s in SEGMENTS
    ]}


def _parse_hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def replay(date, start: str = "06:00", end: str = "10:00") -> Path:
    from .model import (load_capacity, load_classifiers, load_dataset, load_models, load_profile,
                        predict_from_features, predict_proba_from_features)

    t0 = datetime.combine(date, _parse_hm(start))
    t1 = datetime.combine(date, _parse_hm(end))
    df = load_dataset()
    df = df[(df["ts"] >= t0 - timedelta(hours=1)) & (df["ts"] <= t1)]
    if df.empty:
        raise SystemExit(f"no data for {date}")
    feats = build_features(df, load_profile())
    preds = predict_from_features(feats, load_models())
    clfs = load_classifiers()
    probs = predict_proba_from_features(feats, clfs)
    lk = Lookup(feats, preds, probs, {h: c["threshold"] for h, c in clfs.items()})
    ts_list = [ts for ts in lk.actual.index if t0 <= ts.to_pydatetime() <= t1]
    frames = make_frames(lk, load_capacity(), ts_list)
    out = {"date": str(date), "corridor": corridor_json(), "frames": frames}
    return write_replay(out, date)


def write_replay(out: dict, date) -> Path:
    DASH_DATA.mkdir(parents=True, exist_ok=True)
    p = DASH_DATA / f"replay-{date:%Y%m%d}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    idx_p = DASH_DATA / "index.json"
    idx = json.loads(idx_p.read_text()) if idx_p.exists() else {"replays": []}
    idx["replays"] = sorted(set(idx["replays"]) | {str(date)})
    idx_p.write_text(json.dumps(idx, ensure_ascii=False))
    n_push = sum(1 for f in out["frames"] if f["decision"]["push"])
    print(f"wrote {p} frames={len(out['frames'])} push_frames={n_push}")
    return p


def actual_route_tt(df: pd.DataFrame) -> pd.DataFrame:
    """實際車速估算的各路線 TT（秒），index=ts，columns=ROUTES。任一段缺值為 NaN。"""
    w = df.pivot(index="ts", columns="seg", values="speed")[SEG_IDS]
    out = {}
    for r in ROUTES:
        tt = 0.0
        for s in route_segments(r):
            tt = tt + s.distance_km / w[s.id].clip(lower=MIN_SPEED_FOR_TT) * 3600
        out[r] = tt
    return pd.DataFrame(out)


def find_events(top: int = 5) -> list[str]:
    from .model import load_dataset, slice_dates

    df = slice_dates(load_dataset(), TEST)
    tt = actual_route_tt(df)
    diff = tt["ground"] - tt["elevated"]
    hol = df.drop_duplicates("ts").set_index("ts")["is_holiday"]
    sel = (hol.reindex(diff.index) == 0) & (diff.index.hour >= 6) & (diff.index.hour < 10)
    diff = diff[sel]
    w = df.pivot(index="ts", columns="seg", values="speed")
    ground_ids = [s.id for s in route_segments("ground")]
    cong = (w[ground_ids] < 40).sum(axis=1).reindex(diff.index)
    rows = []
    for d, g in diff.groupby(diff.index.date):
        if g.dropna().empty:
            continue
        pk = g.idxmax()
        rows.append((d, pk, g.max() / 60, int(cong[g.index].sum())))
    rows.sort(key=lambda r: -r[2])
    print("date        peak   diff_min  ground<40 segment-steps")
    for d, pk, m, c in rows[:top]:
        print(f"{d}  {pk:%H:%M}  {m:8.1f}  {c}")
    return [str(r[0]) for r in rows[:top]]
