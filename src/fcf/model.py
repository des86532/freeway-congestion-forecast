"""模型訓練與預測。每個 horizon 一個全域 HistGradientBoostingRegressor（車速）與一個 Classifier（壅塞機率）。"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

from .corridor import ENTRY_SEGMENT, ROUTES
from .dataset import PARQUET
from .diversion import CONGESTED_KMH
from .evaluate import choose_threshold
from .features import CLF_VALID, HORIZONS, TRAIN, build_features, compute_profile, feature_columns, targets

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
MAX_ITER = 300


def load_dataset() -> pd.DataFrame:
    return pd.read_parquet(PARQUET)


def slice_dates(df: pd.DataFrame, period: tuple[str, str]) -> pd.DataFrame:
    d = df["ts"].dt.normalize()
    return df[(d >= pd.Timestamp(period[0])) & (d <= pd.Timestamp(period[1]))]


def _hgb_params() -> dict:
    return dict(max_iter=MAX_ITER, learning_rate=0.05, max_leaf_nodes=63,
                categorical_features=["seg_idx"], random_state=0)


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
        model = HistGradientBoostingRegressor(**_hgb_params())
        model.fit(feats.loc[mask, cols], y[mask])
        joblib.dump({"model": model, "feature_names": cols, "horizon": h}, MODELS / f"h{h}.joblib")
        print(f"trained h={h} on {int(mask.sum())} rows")

        # 壅塞機率分類器：4–6 月 fit、7 月（CLF_VALID）選門檻，再以整個 TRAIN 重新 fit
        label = (y < CONGESTED_KMH).to_numpy()
        day = feats["ts"].dt.normalize()
        fit_m = (mask & (day < CLF_VALID[0])).to_numpy()
        val_m = (mask & (day >= CLF_VALID[0]) & (day <= CLF_VALID[1])
                 & (feats["speed_lag0"] >= CONGESTED_KMH)).to_numpy()
        probe = HistGradientBoostingClassifier(**_hgb_params())
        probe.fit(feats.loc[fit_m, cols], label[fit_m])
        thr = choose_threshold(label[val_m], probe.predict_proba(feats.loc[val_m, cols])[:, 1])
        clf = HistGradientBoostingClassifier(**_hgb_params())
        clf.fit(feats.loc[mask, cols], label[mask])
        joblib.dump({"model": clf, "feature_names": cols, "horizon": h, "threshold": thr},
                    MODELS / f"c{h}.joblib")
        print(f"classifier h={h} threshold={thr}")


def load_models() -> dict[int, dict]:
    return {h: joblib.load(MODELS / f"h{h}.joblib") for h in HORIZONS}


def load_classifiers() -> dict[int, dict]:
    for h in HORIZONS:
        if not (MODELS / f"c{h}.joblib").exists():
            raise SystemExit(f"models/c{h}.joblib not found; run `uv run fcf train`")
    return {h: joblib.load(MODELS / f"c{h}.joblib") for h in HORIZONS}


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


def predict_proba_from_features(feats: pd.DataFrame, clfs: dict[int, dict]) -> dict[int, pd.Series]:
    """各 horizon 在每個 (ts, seg) 的 t+h 壅塞（車速 < 40）機率。"""
    out = {}
    for h, c in clfs.items():
        p = c["model"].predict_proba(feats[c["feature_names"]])[:, 1]
        out[h] = pd.Series(p, index=feats.index, name=f"prob_{h}")
    return out


def predict(df_window: pd.DataFrame, models: dict[int, dict], profile: pd.DataFrame) -> dict[int, pd.Series]:
    """各 horizon 在每個 (ts, seg) 的預測車速，clip 到 [0, 130]。"""
    return predict_from_features(build_features(df_window, profile), models)
