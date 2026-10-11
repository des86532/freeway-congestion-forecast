import numpy as np

from fcf.evaluate import onset_leads

NAN = float("nan")


def _series():
    return np.array([80.0] * 20 + [30.0] * 6)


def test_onset_detected_with_lead():
    a = _series()
    p = {h: np.full(len(a), 80.0) for h in (15, 30, 60)}
    p[30][16] = 30.0  # onset(索引 20) 前 20 分鐘預測 t+30(索引 22) < 40
    assert onset_leads(a, p) == [(20, 20)]


def test_onset_missed_and_requires_stable_history():
    a = _series()
    p = {h: np.full(len(a), 80.0) for h in (15, 30, 60)}
    assert onset_leads(a, p) == [(20, None)]
    # 前 3 步未全部 ≥40 → 不是 onset
    a2 = np.array([80, 80, 30, 80, 30, 30, 30.0])
    assert onset_leads(a2, {15: np.full(7, 80.0)}) == []
