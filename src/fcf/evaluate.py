"""fcf evaluate：TEST 期間的車速誤差、壅塞前預警、壅塞起點提前量、分流模擬。"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from .corridor import ENTRY_SEGMENT, ROUTES, SEG_IDS
from .features import HORIZONS, STEP_MIN, TEST, TRAIN, build_features, targets
from .replay import Lookup, make_frames

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
CONGESTED = 40.0


def onset_leads(actual: np.ndarray, preds: dict[int, np.ndarray]) -> list[tuple[int, int | None]]:
    """單一路段序列。onset = 連續 ≥3 步 ≥40 後首次 <40 的時間點。
    在 [o-60, o-5] 分內找最早的 t（當下車速 ≥40），使存在 h 滿足 t+h ∈ [o-10, o+10] 且 pred_h(t) < 40。
    回傳 (onset 索引, 提前分鐘)；未偵測為 None。"""
    out: list[tuple[int, int | None]] = []
    n = len(actual)
    for o in range(3, n):
        if not (actual[o] < CONGESTED and np.all(actual[o - 3:o] >= CONGESTED)):
            continue
        lead = None
        for off in range(-60 // STEP_MIN, -5 // STEP_MIN + 1):  # t = o + off
            t = o + off
            if t < 0 or not (actual[t] >= CONGESTED):
                continue
            hit = False
            for h, p in preds.items():
                tgt_off = off + h // STEP_MIN
                if -10 // STEP_MIN <= tgt_off <= 10 // STEP_MIN and p[t] < CONGESTED:
                    hit = True
                    break
            if hit:
                lead = -off * STEP_MIN
                break
        out.append((o, lead))
    return out


def _err(y: np.ndarray, p: np.ndarray) -> dict:
    e = p - y
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))), "n": int(len(y))}


def _prf(y_pos: np.ndarray, p_pos: np.ndarray) -> dict:
    tp = int(np.sum(y_pos & p_pos))
    fp = int(np.sum(~y_pos & p_pos))
    fn = int(np.sum(y_pos & ~p_pos))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    return {"precision": prec, "recall": rec, "f1": f1, "n_pos": int(y_pos.sum()), "n_pred_pos": tp + fp}


def evaluate() -> None:
    from .model import (load_capacity, load_dataset, load_models, load_profile,
                        predict_from_features)

    t_start, t_end = pd.Timestamp(TEST[0]), pd.Timestamp(TEST[1])
    full = load_dataset()
    d = full["ts"].dt.normalize()
    df = full[(d >= t_start - pd.Timedelta(days=1)) & (d <= t_end)]
    profile, capacity = load_profile(), load_capacity()
    feats = build_features(df, profile)
    preds = predict_from_features(feats, load_models())

    ts = feats["ts"]
    in_test = ((ts >= t_start) & (ts < t_end + pd.Timedelta(days=1))).to_numpy()
    work = (feats["is_holiday"] == 0).to_numpy()
    am = work & (ts.dt.hour >= 6).to_numpy() & (ts.dt.hour < 10).to_numpy()
    subsets = {"all": in_test, "am_peak": in_test & am}

    metrics: dict = {"period": {"train": TRAIN, "test": TEST}, "capacity": capacity}
    speed_err: dict = {}
    warn: dict = {}
    for h in HORIZONS:
        y = targets(df, h).reindex(feats.index).to_numpy()
        lag0 = feats["speed_lag0"].to_numpy()
        prof = feats["profile_speed"].to_numpy()
        mp = preds[h].to_numpy()
        ok = ~np.isnan(y) & ~np.isnan(lag0) & ~np.isnan(prof)
        for name, sub in subsets.items():
            m = ok & sub
            speed_err.setdefault(str(h), {})[name] = {
                "model": _err(y[m], mp[m]),
                "persistence": _err(y[m], lag0[m]),
                "profile": _err(y[m], prof[m]),
            }
            w = m & (lag0 >= CONGESTED)  # 只取當下未壅塞的點
            yp = y[w] < CONGESTED
            warn.setdefault(str(h), {})[name] = {
                "model": _prf(yp, mp[w] < CONGESTED),
                "profile": _prf(yp, prof[w] < CONGESTED),
            }
    metrics["speed_error"] = speed_err
    metrics["warning"] = warn

    # 壅塞起點提前量
    sp_w = feats["speed_lag0"].unstack("seg_")[SEG_IDS]
    pr_w = {h: preds[h].unstack("seg_")[SEG_IDS] for h in HORIZONS}
    in_idx = (sp_w.index >= t_start) & (sp_w.index < t_end + pd.Timedelta(days=1))
    leads: list[int | None] = []
    for seg in SEG_IDS:
        a = sp_w[seg].to_numpy()
        leads += [l for o, l in onset_leads(a, {h: pr_w[h][seg].to_numpy() for h in HORIZONS}) if in_idx[o]]
    det = [l for l in leads if l is not None]
    metrics["onset"] = {
        "n": len(leads), "detected": len(det),
        "detection_rate": len(det) / len(leads) if leads else None,
        "median_lead_min": float(np.median(det)) if det else None,
    }

    # 分流模擬：TEST 期間每個上班日 06:00–10:00
    lk = Lookup(feats, preds)
    decisions = []
    for day, idx in pd.Series(lk.actual.index, index=lk.actual.index).groupby(lk.actual.index.normalize()):
        if day < t_start or day > t_end:
            continue
        hol = int(feats.loc[idx.iloc[0], "is_holiday"].iloc[0])
        if hol:
            continue
        ts_list = [t for t in idx if 6 <= t.hour < 10]
        decisions += [f["decision"] for f in make_frames(lk, capacity, ts_list)]
    pushes = [x for x in decisions if x["push"]]
    reasons = pd.Series([x["reason"] for x in decisions]).value_counts().to_dict()

    def mean_min(vals):
        return float(np.mean(vals)) / 60 if vals else None

    metrics["diversion"] = {
        "steps": len(decisions),
        "reasons": reasons,
        "push_events": len(pushes),
        "mean_saving_naive_min": mean_min([x["saving_naive_s"] for x in pushes]),
        "mean_saving_quota_min": mean_min([x["saving_quota_s"] for x in pushes]),
        "mean_alt_increase_naive_min": mean_min([x["alt_tt_naive_s"] - x["tt_fast_s"] for x in pushes]),
        "mean_alt_increase_quota_min": mean_min([x["alt_tt_quota_s"] - x["tt_fast_s"] for x in pushes]),
    }

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    (REPORTS / "metrics.md").write_text(render_md(metrics))
    dash = ROOT / "dashboard" / "data"
    dash.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPORTS / "metrics.json", dash / "metrics.json")
    print((REPORTS / "metrics.md").read_text())


def _f(x, nd=2, pct=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x * 100:.1f}%" if pct else f"{x:.{nd}f}"


def render_md(m: dict) -> str:
    L = ["# 評估結果", ""]
    L += [f"- 訓練期間：{m['period']['train'][0]} ～ {m['period']['train'][1]}",
          f"- 測試期間：{m['period']['test'][0]} ～ {m['period']['test'][1]}",
          "- 走廊：湖口 → 高公局（北上），國1平面（14 段）與五楊高架（4 段），各 41.0 km",
          "- 資料：高公局 M05A 站間中位數車速（小客車），5 分鐘；壅塞定義：車速 < 40 km/h",
          "- `am_peak`：上班日 06:00 ≤ 預測起點時刻 < 10:00", ""]
    L += ["## 車速誤差（km/h，MAE／RMSE）", "",
          "| 時距 | 子集 | 樣本數 | 模型 MAE | 持續法 MAE | 歷史平均 MAE | 模型 RMSE | 持續法 RMSE | 歷史平均 RMSE |",
          "|---|---|---|---|---|---|---|---|---|"]
    for h, subs in m["speed_error"].items():
        for name, r in subs.items():
            L.append(f"| {h} 分 | {name} | {r['model']['n']} | {_f(r['model']['mae'])} | {_f(r['persistence']['mae'])} | "
                     f"{_f(r['profile']['mae'])} | {_f(r['model']['rmse'])} | {_f(r['persistence']['rmse'])} | "
                     f"{_f(r['profile']['rmse'])} |")
    L += ["", "## 壅塞前預警（當下車速 ≥ 40，預測 t+h 是否 < 40）", "",
          "| 時距 | 子集 | 方法 | Precision | Recall | F1 | 實際壅塞數 |", "|---|---|---|---|---|---|---|"]
    for h, subs in m["warning"].items():
        for name, r in subs.items():
            for meth, label in (("model", "模型"), ("profile", "歷史平均")):
                x = r[meth]
                L.append(f"| {h} 分 | {name} | {label} | {_f(x['precision'], pct=True)} | {_f(x['recall'], pct=True)} | "
                         f"{_f(x['f1'], pct=True)} | {x['n_pos']} |")
    o = m["onset"]
    L += ["", "## 壅塞起點提前量", "",
          "| 起點事件數 | 提前偵測數 | 偵測率 | 提前量中位數（分） |", "|---|---|---|---|",
          f"| {o['n']} | {o['detected']} | {_f(o['detection_rate'], pct=True)} | {_f(o['median_lead_min'], 1)} |"]
    dv = m["diversion"]
    L += ["", "## 分流模擬（TEST 期間上班日 06:00–10:00，含 30 分鐘冷卻）", "",
          "| 項目 | 數值 |", "|---|---|",
          f"| 模擬步數（5 分鐘） | {dv['steps']} |",
          f"| 推播事件數 | {dv['push_events']} |",
          f"| 平均預估節省（個人最快路線 naive，未考慮回堵，分鐘） | {_f(dv['mean_saving_naive_min'], 1)} |",
          f"| 平均預估節省（配額分流，分鐘） | {_f(dv['mean_saving_quota_min'], 1)} |",
          f"| 替代路線 TT 增加（全部訂閱用戶改道 naive，分鐘） | {_f(dv['mean_alt_increase_naive_min'], 1)} |",
          f"| 替代路線 TT 增加（配額，分鐘） | {_f(dv['mean_alt_increase_quota_min'], 1)} |", "",
          "決策原因分布：" + "、".join(f"{k}={v}" for k, v in sorted(dv["reasons"].items())), ""]
    return "\n".join(L)
