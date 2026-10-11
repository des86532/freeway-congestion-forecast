from datetime import datetime, timedelta

from fcf.corridor import ENTRY_SEGMENT, SEG_IDS, SEGMENTS
from fcf.diversion import PENETRATION, decide, optimal_split, select_for_reroute

CAP = {"ground": 200.0, "elevated": 200.0}
VOL = {ENTRY_SEGMENT["ground"]: 200.0, ENTRY_SEGMENT["elevated"]: 150.0}
TS = datetime(2026, 8, 12, 7, 30)


def speeds(ground: float, elevated: float) -> dict[str, float]:
    return {s.id: (ground if s.route == "ground" else elevated) for s in SEGMENTS}


def test_optimal_split_bounds():
    r = optimal_split(2400, 1500, 200, 150, 200, 200)
    assert 0 < r["p_star"] <= PENETRATION
    assert r["alt_tt_quota_s"] <= r["alt_tt_naive_s"]


def test_below_saving():
    d = decide(TS, speeds(80, 80), speeds(80, 82), VOL, CAP, None)
    assert not d.push and d.reason == "below_saving"


def test_push_then_cooldown():
    pred = speeds(45, 85)
    d1 = decide(TS, speeds(80, 85), pred, VOL, CAP, None)
    assert d1.push and d1.reason == "ok" and "建議改走五楊高架" in d1.message and "%" in d1.message
    d2 = decide(TS + timedelta(minutes=10), speeds(80, 85), pred, VOL, CAP, TS)
    assert not d2.push and d2.reason == "cooldown"
    d3 = decide(TS + timedelta(minutes=30), speeds(80, 85), pred, VOL, CAP, TS)
    assert d3.push


def test_missing_data_and_volume():
    pred = speeds(45, 85)
    pred[SEG_IDS[0]] = float("nan")
    assert decide(TS, speeds(80, 85), pred, VOL, CAP, None).reason == "missing_data"
    vol = {**VOL, ENTRY_SEGMENT["ground"]: float("nan")}
    assert decide(TS, speeds(80, 85), speeds(45, 85), vol, CAP, None).reason == "missing_volume"


def test_select_for_reroute_share_and_determinism():
    sel = [select_for_reroute(f"user{i}", "2026-08-12", 0.5) for i in range(10000)]
    assert 0.47 <= sum(sel) / len(sel) <= 0.53
    assert sel == [select_for_reroute(f"user{i}", "2026-08-12", 0.5) for i in range(10000)]
