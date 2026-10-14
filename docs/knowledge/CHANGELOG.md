# 知識文件更新紀錄

由新到舊。每次功能或行為變更，在最上方新增一筆：日期、變更摘要、修改到的知識文件。

## 2026-10-15 — 壅塞機率分類器（提升預警 Recall）

變更摘要：

- 每個時距新增 `HistGradientBoostingClassifier`（標籤 t+h 車速 < 40），機率門檻在 TRAIN 內的 2026-07 驗證月選定（`CLF_VALID`），再以整個 TRAIN 重新訓練；產物 `models/c{h}.joblib`。迴歸模型與分流決策不變。
- `evaluate` 新增分類器的預警與起點指標；`onset_leads` 改收 bool 預警陣列；`metrics.json` 新增 `classifier_threshold`、`period.clf_valid`、`warning.*.classifier`，`onset` 拆成 `regressor`／`classifier`。
- replay／live 的 frame 新增 `prob`、`alarm`；`Lookup` 新增 `probs`、`thresholds` 參數。
- 儀表板新增「壅塞預警」卡、預測模式 tooltip 的壅塞機率、指標區的方法欄。

Recall 前後對照（`am_peak`，取自 `reports/metrics.md`）：

| 時距 | 回歸模型 Recall／F1／Precision | 分類器 Recall／F1／Precision |
|---|---|---|
| 15 分 | 38.9% ／ 51.9% ／ 77.8% | 62.5% ／ 58.7% ／ 55.4% |
| 30 分 | 31.3% ／ 45.3% ／ 81.8% | 63.9% ／ 59.0% ／ 54.8% |
| 60 分 | 28.0% ／ 41.9% ／ 83.0% | 61.2% ／ 59.9% ／ 58.7% |

壅塞起點偵測率：回歸模型 47.3%（中位提前 10 分）→ 分類器 86.4%（中位提前 30 分）。取捨：Precision 由約 78–83% 降至約 55–59%，起點偵測率不懲罰誤報，須與預警表一併解讀。

修改到的知識文件：`01-system-overview.md`、`03-features-and-models.md`、`04-evaluation.md`、`05-diversion.md`、`06-replay-live-notify.md`、`07-dashboard.md`；另更新 `docs/proposal.md` §5、§6.2、§6.3、§11。

## 2026-10-14 — 建立知識文件（描述 PR #1 MVP 現況）

新增檔案：

- `docs/knowledge/README.md`
- `docs/knowledge/01-system-overview.md`
- `docs/knowledge/02-data-pipeline.md`
- `docs/knowledge/03-features-and-models.md`
- `docs/knowledge/04-evaluation.md`
- `docs/knowledge/05-diversion.md`
- `docs/knowledge/06-replay-live-notify.md`
- `docs/knowledge/07-dashboard.md`
- `docs/knowledge/CHANGELOG.md`
- `AGENTS.md`（repo root：要求功能變更同步更新知識文件）
