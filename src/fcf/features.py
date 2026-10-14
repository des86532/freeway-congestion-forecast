"""特徵工程。訓練、評估、replay、live 共用 build_features，不得另寫特徵邏輯。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .calendar import is_holiday
from .corridor import SEG_IDS, SEG_INDEX, neighbors

STEP_MIN = 5
HORIZONS = (15, 30, 60)
N_SPEED_LAGS = 6  # speed_lag0 .. speed_lag5
N_VOLUME_LAGS = 3
TRAIN = ("2026-04-01", "2026-07-31")
CLF_VALID = ("2026-07-01", "2026-07-31")  # TRAIN 內的分類器門檻驗證月
TEST = ("2026-08-01", "2026-09-06")

_NONE = "__none__"


def to_wide(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """長表 → (連續 5 分鐘 ts × seg) 寬表；缺日以 NaN 補齊，使 shift 不跨缺口取錯值。"""
    w = df.pivot(index="ts", columns="seg", values=col)
    idx = pd.date_range(w.index.min(), w.index.max(), freq=f"{STEP_MIN}min")
    return w.reindex(index=idx, columns=SEG_IDS).astype("float32")


def _neighbor_view(w: pd.DataFrame, which: int) -> pd.DataFrame:
    cols = [neighbors(s)[which] or _NONE for s in w.columns]
    out = w.reindex(columns=cols)
    out.columns = w.columns
    return out


def _flat(w: pd.DataFrame) -> np.ndarray:
    return w.to_numpy(dtype="float32").ravel()  # row-major: ts 外層、seg 內層


def build_features(df: pd.DataFrame, profile: pd.DataFrame) -> pd.DataFrame:
    sp = to_wide(df, "speed")
    vo = to_wide(df, "volume").reindex(index=sp.index)
    idx = sp.index
    n_t, n_s = sp.shape

    ts_col = np.repeat(idx.values, n_s)
    seg_col = np.tile(np.array(SEG_IDS), n_t)
    cols: dict[str, np.ndarray] = {
        "ts": ts_col,
        "seg": seg_col,
        "seg_idx": np.tile(np.array([SEG_INDEX[s] for s in SEG_IDS]), n_t),
        "slot": np.repeat((idx.hour * 12 + idx.minute // STEP_MIN).to_numpy(), n_s),
        "dow": np.repeat(idx.dayofweek.to_numpy(), n_s),
    }
    hol_by_date = {d: int(is_holiday(d)) for d in idx.normalize().unique()}
    cols["is_holiday"] = np.repeat(idx.normalize().map(hol_by_date).to_numpy(), n_s)

    for k in range(N_SPEED_LAGS):
        cols[f"speed_lag{k}"] = _flat(sp.shift(k))
    cols["speed_delta3"] = cols["speed_lag0"] - cols["speed_lag3"]
    for k in range(N_VOLUME_LAGS):
        cols[f"volume_lag{k}"] = _flat(vo.shift(k))
    up, down = _neighbor_view(sp, 0), _neighbor_view(sp, 1)
    cols["up_speed_lag0"] = _flat(up)
    cols["up_speed_lag1"] = _flat(up.shift(1))
    cols["down_speed_lag0"] = _flat(down)
    cols["down_speed_lag1"] = _flat(down.shift(1))

    out = pd.DataFrame(cols)
    out["ts"] = pd.to_datetime(out["ts"])
    out = out.merge(profile, on=["seg", "slot", "is_holiday"], how="left")
    out["profile_speed"] = out["profile_speed"].astype("float32")
    return out.set_index(["ts", "seg"], drop=False).rename_axis(index=["ts_", "seg_"])


def compute_profile(df_train: pd.DataFrame) -> pd.DataFrame:
    d = df_train.dropna(subset=["speed"]).copy()
    d["slot"] = d["ts"].dt.hour * 12 + d["ts"].dt.minute // STEP_MIN
    # is_holiday 欄位由 dataset 提供
    g = d.groupby(["seg", "slot", "is_holiday"], as_index=False)["speed"].mean()
    return g.rename(columns={"speed": "profile_speed"})


def targets(df: pd.DataFrame, horizon_min: int) -> pd.Series:
    """t+h 的實際車速，index 與 build_features 輸出對齊（ts_, seg_）。"""
    sp = to_wide(df, "speed")
    s = sp.shift(-(horizon_min // STEP_MIN))
    return pd.Series(_flat(s), index=pd.MultiIndex.from_arrays(
        [np.repeat(s.index.values, s.shape[1]), np.tile(np.array(SEG_IDS), s.shape[0])],
        names=["ts_", "seg_"]), name=f"target_{horizon_min}")


def feature_columns() -> list[str]:
    cols = ["seg_idx", "slot", "dow", "is_holiday"]
    cols += [f"speed_lag{k}" for k in range(N_SPEED_LAGS)] + ["speed_delta3"]
    cols += [f"volume_lag{k}" for k in range(N_VOLUME_LAGS)]
    cols += ["up_speed_lag0", "up_speed_lag1", "down_speed_lag0", "down_speed_lag1", "profile_speed"]
    return cols
