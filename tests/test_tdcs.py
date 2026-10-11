import math
from datetime import datetime

from fcf.tdcs import parse_m05a_rows

SEGS = {"01F0492N-01F0467N", "01F0750N-01F0699N"}

CSV = """2026/10/01 07:55,01F0492N,01F0467N,31,25,185
2026/10/01 07:55,01F0492N,01F0467N,32,60,40
2026/10/01 08:00,01F0492N,01F0467N,31,0,0
2026/10/01 08:00,01F0000N,01F0001N,31,90,10
2026/10/01 08:05,01F0750N,01F0699N,31,88,0
""".splitlines()


def test_parse_filters_and_values():
    rows = parse_m05a_rows(CSV, SEGS)
    assert len(rows) == 3  # 32 型與走廊外路段被濾掉
    assert rows[0] == (datetime(2026, 10, 1, 7, 55), "01F0492N-01F0467N", 25.0, 185.0)
    ts, seg, speed, vol = rows[1]
    assert ts == datetime(2026, 10, 1, 8, 0)
    assert math.isnan(speed)
    assert vol == 0.0  # Volume=0 合法，保留
    assert rows[2][2] == 88.0 and rows[2][3] == 0.0
