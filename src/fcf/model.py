"""模型訓練與預測。每個 horizon 一個全域 HistGradientBoostingRegressor。"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .corridor import ENTRY_SEGMENT, ROUTES
from .dataset import PARQUET
from .features import HORIZONS, TRAIN, build_features, compute_profile, feature_columns, targets

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
MAX_ITER = 300


def load_dataset() -> pd.DataFrame:
    return pd.read_parquet(PARQUET)


def slice_dates(df: pd.DataFrame, period: tuple[str, str]) -> pd.DataFrame:
    d = df["ts"].dt.normalize()
    return df[(d >= pd.Timestamp(period[0])) & (d <= pd.Timestamp(period[1]))]


def train() -> None:
    df = slice_dates(load_dataset(), TRAIN)
    MODELS.mkdir(exist_ok=True)

    profile = compute_profile(df)
    profile.to_parquet(MODELS / "profile.parquet", index=False)

    cap = {}
    for r in ROUTES:
        v = df.loc[df["seg"] == ENTRY_SEGMENT[r], "volume"].dropna()
        cap[r] = float(v.quantile(0.95))
    (MODELS / "capacity.json").write_text(json.dumps(cap))
    print("capacity:", cap)

    feats = build_features(df, profile)
    cols = feature_columns()
    for h in HORIZONS:
        y = targets(df, h)
        mask = y.notna().to_numpy()
        model = HistGradientBoostingRegressor(
            max_iter=MAX_ITER, learning_rate=0.05, max_leaf_nodes=63,
            categorical_features=["seg_idx"], random_state=0,
        )
        model.fit(feats.loc[mask, cols], y[mask])
        joblib.dump({"model": model, "feature_names": cols, "horizon": h}, MODELS / f"h{h}.joblib")
        print(f"trained h={h} on {int(mask.sum())} rows")


def load_models() -> dict[int, dict]:
    return {h: joblib.load(MODELS / f"h{h}.joblib") for h in HORIZONS}


def load_profile() -> pd.DataFrame:
    return pd.read_parquet(MODELS / "profile.parquet")


def load_capacity() -> dict[str, float]:
    return json.loads((MODELS / "capacity.json").read_text())


def predict_from_features(feats: pd.DataFrame, models: dict[int, dict]) -> dict[int, pd.Series]:
    out = {}
    for h, m in models.items():
        p = m["model"].predict(feats[m["feature_names"]]).clip(0, 130)
        out[h] = pd.Series(p, index=feats.index, name=f"pred_{h}")
    return out


def predict(df_window: pd.DataFrame, models: dict[int, dict], profile: pd.DataFrame) -> dict[int, pd.Series]:
    """各 horizon 在每個 (ts, seg) 的預測車速，clip 到 [0, 130]。"""
    return predict_from_features(build_features(df_window, profile), models)
