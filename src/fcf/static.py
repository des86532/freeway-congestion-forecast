"""fcf fetch-static：路段幾何與辦公日曆。"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET

from .calendar import CALENDAR_PATH, CALENDAR_URL
from .corridor import SEG_IDS
from .http import BASE, fetch

GEOM_PATH = CALENDAR_PATH.parent / "corridor_geometry.json"
ETAGPAIR_URL = f"{BASE}/history/motc20/ETagPair.xml"


def parse_wkt(wkt: str) -> list[list[float]]:
    m = re.search(r"LINESTRING\s*\((.*)\)", wkt)
    if not m:
        return []
    pts = []
    for pair in m.group(1).split(","):
        lon, lat = pair.split()[:2]
        pts.append([float(lat), float(lon)])
    return pts


def fetch_static() -> int:
    root = ET.fromstring(fetch(ETAGPAIR_URL))
    geom: dict[str, list[list[float]]] = {}
    for el in root.iter():
        if el.tag.split("}")[-1] != "ETagPair":
            continue
        fields = {c.tag.split("}")[-1]: (c.text or "") for c in el}
        pid = fields.get("ETagPairID", "")
        if pid in SEG_IDS and pid not in geom:
            pts = parse_wkt(fields.get("Geometry", ""))
            if len(pts) >= 2:
                geom[pid] = pts
    missing = [s for s in SEG_IDS if s not in geom]
    if missing:
        print(f"missing segments: {missing}", file=sys.stderr)
        return 1
    GEOM_PATH.parent.mkdir(parents=True, exist_ok=True)
    GEOM_PATH.write_text(json.dumps({s: geom[s] for s in SEG_IDS}, ensure_ascii=False))
    print(f"wrote {GEOM_PATH} ({len(geom)} segments)")

    CALENDAR_PATH.write_bytes(fetch(CALENDAR_URL, min_interval=0))
    print(f"wrote {CALENDAR_PATH}")
    return 0
