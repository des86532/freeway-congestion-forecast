"""fcf build-dataset：tar → data/processed/corridor.parquet"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .calendar import is_holiday
from .corridor import SEG_IDS
from .tdcs import RAW_DIR, read_tar_rows

PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"
PARQUET = PROCESSED / "corridor.parquet"


def build_grid(rows: list[tuple]) -> pd.DataFrame:
    """rows=(ts,seg,speed,volume) → 完整 (ts × seg) 網格，僅涵蓋資料中出現的日期。"""
    df = pd.DataFrame(rows, columns=["ts", "seg", "speed", "volume"])
    df = df.drop_duplicates(["ts", "seg"], keep="last")
    days = sorted(df["ts"].dt.normalize().unique())
    ts_index = pd.DatetimeIndex(
        np.concatenate([pd.date_range(d, periods=288, freq="5min").values for d in days])
    )
    full = pd.MultiIndex.from_product([ts_index, SEG_IDS], names=["ts", "seg"])
    df = df.set_index(["ts", "seg"]).reindex(full).reset_index()
    df["speed"] = df.groupby("seg")["speed"].ffill(limit=3)
    df["is_holiday"] = df["ts"].dt.normalize().map(lambda d: int(is_holiday(d))).astype("int8")
    df["speed"] = df["speed"].astype("float32")
    df["volume"] = df["volume"].astype("float32")
    return df[["ts", "seg", "speed", "volume", "is_holiday"]]


def build_dataset() -> None:
    files = sorted(RAW_DIR.glob("M05A_*.tar.gz"))
    if not files:
        raise SystemExit("no tar files in data/raw; run fcf fetch-history first")
    seg_set = set(SEG_IDS)
    rows: list[tuple] = []
    for i, p in enumerate(files, 1):
        rows.extend(read_tar_rows(p, seg_set))
        if i % 20 == 0:
            print(f"[build-dataset] {i}/{len(files)}", flush=True)
    df = build_grid(rows)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET, index=False)
    print(f"rows={len(df)} days={df['ts'].dt.normalize().nunique()} -> {PARQUET}")
    print("speed 缺值率：")
    print(df.groupby("seg")["speed"].apply(lambda s: s.isna().mean()).round(4).to_string())
