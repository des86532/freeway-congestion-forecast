# 03 特徵與模型

對應原始碼：`src/fcf/features.py`、`src/fcf/model.py`

## 期間常數（`features.py`）

| 常數 | 值 | 用途 |
|---|---|---|
| `TRAIN` | 2026-04-01 ～ 2026-07-31 | 訓練、歷史平均 profile、capacity |
| `TEST` | 2026-08-01 ～ 2026-09-06 | 評估與重播（模型從未見過） |
| `HORIZONS` | 15、30、60 分鐘 | 預測時距 |
| `STEP_MIN` | 5 | 資料間隔 |
| `CLF_VALID` | 2026-07-01 ～ 2026-07-31 | TRAIN 內，用來選分類器門檻的驗證月 |

TRAIN／TEST 固定寫在程式碼以便重現；評估絕不使用 TEST 資料調整任何參數。

## 特徵工程（`build_features`）

訓練、評估、replay、live 共用 `build_features(df, profile)`，不得另寫特徵邏輯。

**`to_wide` 補缺口**：長表轉為「連續 5 分鐘 ts × 18 路段」寬表，缺少的日期／時間點以 NaN 補上。這樣 `shift(k)` 一定是往前 `k×5` 分鐘，不會因為中間缺日而跨日取到錯誤的值。

輸出每個 (ts, seg) 一列，index 為 `(ts_, seg_)`（同時保留 `ts`、`seg` 欄）。模型使用的欄位由 `feature_columns()` 決定：

| 特徵 | 定義 |
|---|---|
| `seg_idx` | 路段在 `SEGMENTS` 的索引（**類別特徵**） |
| `slot` | 一天中的 5 分鐘時段，`hour×12 + minute//5`（0–287） |
| `dow` | 星期幾（0=週一） |
| `is_holiday` | 辦公日曆放假（含補假／調整上班日） |
| `speed_lag0` … `speed_lag5` | 當下與前 1–5 步（5–25 分鐘前）的車速 |
| `speed_delta3` | `speed_lag0 − speed_lag3`（近 15 分鐘的變化） |
| `volume_lag0` … `volume_lag2` | 當下與前 2 步的流量 |
| `up_speed_lag0`、`up_speed_lag1` | 同路線上游路段當下與前 1 步車速 |
| `down_speed_lag0`、`down_speed_lag1` | 同路線下游路段當下與前 1 步車速 |
| `profile_speed` | 該 (路段, slot, is_holiday) 在 TRAIN 的平均車速 |

上游／下游由 `neighbors()` 決定；路線頭尾沒有鄰段時該特徵為 NaN。

**`compute_profile`**：只用 TRAIN 資料，去掉 `speed` 缺值後依 `(seg, slot, is_holiday)` 取平均，得到 `profile_speed`。它同時是模型特徵與評估的「歷史平均」基準線。

**`targets(df, h)`**：`t+h` 的實際車速（寬表 `shift(-h/5)`），index 與 `build_features` 輸出對齊，名稱 `target_{h}`。尾端或缺口處為 NaN。

## 迴歸模型（`model.py`）

`train()`：

1. 取 `slice_dates(load_dataset(), TRAIN)`。
2. 計算 profile → `models/profile.parquet`。
3. **capacity**：各路線入口路段在 TRAIN 的 `volume` 第 95 百分位 → `models/capacity.json`（`{"ground": ..., "elevated": ...}`），作為 BPR 的容量 `c`（見 05）。
4. 對每個 `h ∈ HORIZONS` 各訓練一個全域（18 路段共用）`HistGradientBoostingRegressor`：`max_iter=300, learning_rate=0.05, max_leaf_nodes=63, categorical_features=["seg_idx"], random_state=0`。只使用 `targets` 非 NaN 的列。
5. 存成 `models/h{h}.joblib`，內容 `{"model", "feature_names", "horizon"}`。

預測 `predict_from_features(feats, models)`：以 `feature_names` 取欄位預測，結果 `clip(0, 130)`，回傳 `{h: Series(name="pred_{h}")}`。

`model.predict(df_window, models, profile)` 是把 `build_features` 與 `predict_from_features` 串起來的便利函式，目前沒有任何呼叫者；實際流程都是分開呼叫。

## 壅塞機率分類器

迴歸模型以「預測車速 < 40」判斷壅塞，但迴歸傾向預測平均值，壅塞前預警的 Recall 偏低（見 [04-evaluation.md](04-evaluation.md)）。因此每個時距另外訓練一個直接預測「t+h 是否壅塞」的機率分類器，用較低的機率門檻換取 Recall。

- **標籤**：`y(t+h) < 40`（`CONGESTED_KMH`，與迴歸評估的壅塞定義相同）。只使用 `targets` 非 NaN 的列。
- **模型**：每個時距一個全域 `HistGradientBoostingClassifier`，參數與特徵和迴歸模型完全相同（共用 `_hgb_params()`，因此迴歸模型的訓練結果不受影響）。
- **門檻選定**（`CLF_VALID = 2026-07-01 ～ 2026-07-31`，仍在 TRAIN 內）：
  1. 先只用 `CLF_VALID` 之前（4–6 月）的列 fit 一個暫時分類器。
  2. 在 7 月、且當下車速 `speed_lag0 ≥ 40` 的列（與 evaluate 預警條件相同）預測機率，呼叫 `evaluate.choose_threshold`：在 `THRESHOLD_GRID`（0.05、0.10、…、0.95）中挑 F1 最大者；同分取較大門檻；F1 全為 `None` 時回傳 0.5。
  3. 門檻決定後，丟掉暫時分類器，以**整個 TRAIN** 重新 fit 最終分類器（TEST 資料完全不參與訓練與選門檻）。
- **產物**：`models/c{h}.joblib`，內容 `{"model", "feature_names", "horizon", "threshold"}`。
- **目前門檻**（`reports/metrics.json` 的 `classifier_threshold`）：15 分 0.20、30 分 0.20、60 分 0.25。
- **載入與預測**：`load_classifiers()`（任一 `c{h}.joblib` 不存在即 `SystemExit("models/c{h}.joblib not found; run `uv run fcf train`")`）；`predict_proba_from_features(feats, clfs)` 回傳 `{h: Series(name="prob_{h}")}`，值為壅塞機率。

分類器只用於「預警」（evaluate 的預警與起點指標、frame 的 `prob`／`alarm`、儀表板預警卡）；分流決策仍使用迴歸模型的 `pred["30"]`（見 [05-diversion.md](05-diversion.md)）。

## `models/` 內的產物

| 檔案 | 內容 |
|---|---|
| `h15.joblib`、`h30.joblib`、`h60.joblib` | 各時距的迴歸模型 |
| `c15.joblib`、`c30.joblib`、`c60.joblib` | 各時距的壅塞機率分類器與其門檻 |
| `profile.parquet` | TRAIN 歷史平均車速 |
| `capacity.json` | 各路線入口流量的 95 百分位 |

`models/` 在 `.gitignore` 內，不進版控；需執行 `uv run fcf train` 重建。
