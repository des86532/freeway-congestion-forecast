"""系統最佳分流：以配額限制改道比例，避免替代道路二次壅塞。"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from .corridor import ENTRY_SEGMENT, ROUTE_NAMES, ROUTES, SEG_BY_ID, route_segments

PENETRATION = 0.30  # App 用戶佔車流比例
MIN_SAVING_S = 300
COOLDOWN_MIN = 30
P_STEP = 0.05
CONGESTED_KMH = 40
MIN_SPEED_FOR_TT = 5
MIN_QUOTA_SAVING_S = 60

SOURCE = "資料來源：交通部高速公路局「交通資料庫」"

REASON_ZH = {
    "ok": "符合推播條件",
    "missing_data": "資料不足，無法預測",
    "below_saving": "兩路線預測差距不足 5 分鐘，不推播",
    "missing_volume": "入口流量缺漏，無法估算分流",
    "no_benefit": "分流後替代道路無實質效益，不推播",
    "cooldown": "冷卻期內（30 分鐘），不重複推播",
}


def route_travel_time(speeds: dict[str, float], route: str) -> float | None:
    """Σ distance / max(speed, 5) × 3600（秒）；任一段缺值回傳 None。
    簡化：以同一時刻車速估整條路線，不做時變行進模擬。"""
    total = 0.0
    for s in route_segments(route):
        v = speeds.get(s.id)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        total += s.distance_km / max(v, MIN_SPEED_FOR_TT) * 3600
    return total


def bpr(v: float, c: float) -> float:
    return 1 + 0.15 * (v / c) ** 4


def optimal_split(tt_slow: float, tt_fast: float, v_slow: float, v_fast: float,
                  c_slow: float, c_fast: float) -> dict:
    best_p, best_total = 0.0, math.inf
    steps = int(round(PENETRATION / P_STEP))
    for i in range(steps + 1):
        p = round(i * P_STEP, 10)
        total = _split_point(p, tt_slow, tt_fast, v_slow, v_fast, c_slow, c_fast)[2]
        if total < best_total - 1e-9:  # 同分取較小 p
            best_p, best_total = p, total
    ts_, tf_, tot_q = _split_point(best_p, tt_slow, tt_fast, v_slow, v_fast, c_slow, c_fast)
    ts_n, tf_n, tot_n = _split_point(PENETRATION, tt_slow, tt_fast, v_slow, v_fast, c_slow, c_fast)
    tot_0 = v_slow * tt_slow + v_fast * tt_fast
    return {
        "p_star": best_p,
        "saving_quota_s": ts_ - tf_,
        "alt_tt_quota_s": tf_,
        "alt_tt_naive_s": tf_n,
        "saving_naive_after_s": ts_n - tf_n,
        "sys_saving_quota_veh_s": tot_0 - tot_q,  # 系統總車輛時間節省（輛·秒 / 5 分鐘流量）
        "sys_saving_naive_veh_s": tot_0 - tot_n,
    }


def _split_point(p, tt_slow, tt_fast, v_slow, v_fast, c_slow, c_fast):
    vs = v_slow * (1 - p)
    vf = v_fast + p * v_slow
    ts_ = tt_slow * bpr(vs, c_slow) / bpr(v_slow, c_slow)
    tf_ = tt_fast * bpr(vf, c_fast) / bpr(v_fast, c_fast)
    return ts_, tf_, vs * ts_ + vf * tf_


@dataclass
class Decision:
    push: bool = False
    reason: str = "missing_data"
    slow: str | None = None
    fast: str | None = None
    saving_naive_s: float | None = None
    p_star: float | None = None
    saving_quota_s: float | None = None
    alt_tt_naive_s: float | None = None
    alt_tt_quota_s: float | None = None
    message: str | None = None
    stay_message: str | None = None
    tt_slow_s: float | None = None
    tt_fast_s: float | None = None
    sys_saving_quota_veh_s: float | None = None
    sys_saving_naive_veh_s: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def format_message(ts: datetime, slow: str, fast: str, worst_desc: str, worst_speed: float,
                   saving_quota_s: float, p_star: float) -> str:
    t = (ts + timedelta(minutes=30)).strftime("%H:%M")
    return (
        f"【國道壅塞預警】預測 {t} 起{ROUTE_NAMES[slow]}「{worst_desc}」時速將降至 {round(worst_speed)} km/h。"
        f"建議改走{ROUTE_NAMES[fast]}，預估可省 {round(saving_quota_s / 60)} 分鐘。"
        f"為避免替代道路回堵，本次僅建議 {round(p_star / PENETRATION * 100)}% 訂閱用路人改道。{SOURCE}"
    )


def format_stay_message(slow: str, saving_naive_s: float) -> str:
    return (
        f"【國道壅塞預警】{ROUTE_NAMES[slow]}預計延誤 {round(saving_naive_s / 60)} 分鐘，"
        f"替代道路已分流其他用路人，建議您維持原路線以免回堵。{SOURCE}"
    )


def select_for_reroute(user_id: str, date: str, share: float) -> bool:
    h = int(hashlib.sha256(f"{user_id}|{date}".encode()).hexdigest()[:8], 16)
    return h % 1000 < round(share * 1000)


def decide(ts: datetime, actual_speeds: dict[str, float], pred30_speeds: dict[str, float],
           volumes: dict[str, float], capacity: dict[str, float],
           last_push_ts: datetime | None) -> Decision:
    d = Decision()
    tt = {r: route_travel_time(pred30_speeds, r) for r in ROUTES}
    if any(v is None for v in tt.values()):
        d.reason = "missing_data"
        return d
    slow, fast = (ROUTES[0], ROUTES[1]) if tt[ROUTES[0]] >= tt[ROUTES[1]] else (ROUTES[1], ROUTES[0])
    d.slow, d.fast = slow, fast
    d.tt_slow_s, d.tt_fast_s = tt[slow], tt[fast]
    d.saving_naive_s = tt[slow] - tt[fast]
    if d.saving_naive_s < MIN_SAVING_S:
        d.reason = "below_saving"
        return d

    v = {r: volumes.get(ENTRY_SEGMENT[r]) for r in ROUTES}
    if any(x is None or math.isnan(x) or x <= 0 for x in v.values()):
        d.reason = "missing_volume"
        return d

    sp = optimal_split(tt[slow], tt[fast], v[slow], v[fast], capacity[slow], capacity[fast])
    d.p_star = sp["p_star"]
    d.saving_quota_s = sp["saving_quota_s"]
    d.alt_tt_naive_s = sp["alt_tt_naive_s"]
    d.alt_tt_quota_s = sp["alt_tt_quota_s"]
    d.sys_saving_quota_veh_s = sp["sys_saving_quota_veh_s"]
    d.sys_saving_naive_veh_s = sp["sys_saving_naive_veh_s"]
    if d.p_star == 0 or d.saving_quota_s < MIN_QUOTA_SAVING_S:
        d.reason = "no_benefit"
        return d
    if last_push_ts is not None and ts - last_push_ts < timedelta(minutes=COOLDOWN_MIN):
        d.reason = "cooldown"
        return d

    worst = min(route_segments(slow), key=lambda s: pred30_speeds[s.id])
    d.push, d.reason = True, "ok"
    d.message = format_message(ts, slow, fast, SEG_BY_ID[worst.id].description,
                               pred30_speeds[worst.id], d.saving_quota_s, d.p_star)
    if d.p_star < PENETRATION:  # 配額未涵蓋全部訂閱用戶時，才有「未入選」者
        d.stay_message = format_stay_message(slow, d.saving_naive_s)
    return d
