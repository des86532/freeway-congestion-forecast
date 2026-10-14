import numpy as np

from fcf.evaluate import choose_threshold, onset_leads


def _series():
    return np.array([80.0] * 20 + [30.0] * 6)


def _alarms(n):
    return {h: np.zeros(n, bool) for h in (15, 30, 60)}


def test_onset_detected_with_lead():
    a = _series()
    p = _alarms(len(a))
    p[30][16] = True  # onset(索引 20) 前 20 分鐘預警 t+30(索引 22) 壅塞
    assert onset_leads(a, p) == [(20, 20)]


def test_onset_missed_and_requires_stable_history():
    a = _series()
    assert onset_leads(a, _alarms(len(a))) == [(20, None)]
    # 前 3 步未全部 ≥40 → 不是 onset
    a2 = np.array([80, 80, 30, 80, 30, 30, 30.0])
    assert onset_leads(a2, {15: np.zeros(7, bool)}) == []


def test_choose_threshold():
    # 0.55–0.7 的 F1 都是 1.0，同分取較大門檻
    assert choose_threshold(np.array([True, True, False, False]), np.array([0.9, 0.7, 0.5, 0.1])) == 0.7
    # 沒有正例 → F1 全為 None → 預設 0.5
    assert choose_threshold(np.zeros(4, bool), np.full(4, 0.3)) == 0.5
