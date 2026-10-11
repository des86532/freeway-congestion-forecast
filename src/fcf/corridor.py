"""走廊定義：北上 湖口 → 高公局，國1平面與五楊高架兩條平行路線。
ID 與距離取自 ETagPair.xml。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    id: str
    route: str
    order: int
    distance_km: float
    description: str


def _mk(route: str, rows: list[tuple[str, float, str]]) -> list[Segment]:
    return [Segment(i, route, n, km, d) for n, (i, km, d) in enumerate(rows, 1)]


_GROUND = [
    ("01F0750N-01F0699N", 5.1, "湖口-校前路"),
    ("01F0699N-01F0681N", 1.8, "校前路-楊梅"),
    ("01F0681N-01F0664N", 1.7, "楊梅-幼獅"),
    ("01F0664N-01F0633N", 3.1, "幼獅-平鎮系統"),
    ("01F0633N-01F0616N", 1.7, "平鎮系統-中壢"),
    ("01F0616N-01F0584N", 3.2, "中壢-中豐"),
    ("01F0584N-01F0557N", 2.7, "中豐-內壢"),
    ("01F0557N-01F0532N", 2.5, "內壢-中壢服務區"),
    ("01F0532N-01F0511N", 2.1, "中壢服務區-機場系統"),
    ("01F0511N-01F0492N", 1.9, "機場系統-桃園(49B)"),
    ("01F0492N-01F0467N", 2.5, "桃園(49B)-桃園(49A)"),
    ("01F0467N-01F0413N", 5.4, "桃園(49A)-林口(文化北路)"),
    ("01F0413N-01F0376N", 3.7, "林口(文化北路)-林口(文化一路)"),
    ("01F0376N-01F0340N", 3.6, "林口(文化一路)-高公局"),
]
_ELEVATED = [
    ("01F0750N-01H0608N", 14.2, "湖口-校前路"),
    ("01H0608N-01H0579N", 2.9, "校前路-中豐"),
    ("01H0579N-01H0447N", 13.2, "中豐-機場系統"),
    ("01H0447N-01F0340N", 10.7, "機場系統-高公局"),
]

SEGMENTS: list[Segment] = _mk("ground", _GROUND) + _mk("elevated", _ELEVATED)
ROUTES = ("ground", "elevated")
ROUTE_NAMES = {"ground": "國1平面", "elevated": "五楊高架"}
ENTRY_SEGMENT = {"ground": "01F0750N-01F0699N", "elevated": "01F0750N-01H0608N"}

SEG_BY_ID: dict[str, Segment] = {s.id: s for s in SEGMENTS}
SEG_IDS: list[str] = [s.id for s in SEGMENTS]
SEG_INDEX: dict[str, int] = {s.id: i for i, s in enumerate(SEGMENTS)}


def route_segments(route: str) -> list[Segment]:
    return [s for s in SEGMENTS if s.route == route]


def neighbors(seg_id: str) -> tuple[str | None, str | None]:
    seg = SEG_BY_ID[seg_id]
    rs = route_segments(seg.route)
    i = seg.order - 1
    up = rs[i - 1].id if i > 0 else None
    down = rs[i + 1].id if i < len(rs) - 1 else None
    return up, down
