# 知識庫索引

本資料夾記錄系統「現在實際怎麼運作」，內容只描述程式碼已實作的行為，數字一律引用 [`reports/metrics.md`](../../reports/metrics.md)。
對外的提案與效益論述在 [`docs/proposal.md`](../proposal.md)；本知識庫面向開發與維護者，說明設計決策、公式、檔案格式與限制。

## 閱讀順序

| 檔案 | 主題 |
|---|---|
| [01-system-overview.md](01-system-overview.md) | 問題定義、走廊、整體資料流、模組地圖、CLI 子指令 |
| [02-data-pipeline.md](02-data-pipeline.md) | 從高公局 M05A 原始檔到 `corridor.parquet` 的資料處理 |
| [03-features-and-models.md](03-features-and-models.md) | 特徵、模型訓練、產物 `models/` |
| [04-evaluation.md](04-evaluation.md) | 評估指標的定義與計算方式，如何閱讀 `metrics.md` |
| [05-diversion.md](05-diversion.md) | 系統最佳分流：旅行時間、BPR、配額、推播判斷 |
| [06-replay-live-notify.md](06-replay-live-notify.md) | 重播、即時模式、LINE 推播與 frame JSON 格式 |
| [07-dashboard.md](07-dashboard.md) | 靜態儀表板的資料來源與顯示規則 |
| [CHANGELOG.md](CHANGELOG.md) | 知識文件更新紀錄（由新到舊） |

每份文件開頭的「對應原始碼」列出該文件描述的檔案；程式碼與文件不一致時，以程式碼為準，並請修正文件。

## 維護規則

- 任何功能或行為變更，必須在同一個 PR 更新相關主題檔，並在 [CHANGELOG.md](CHANGELOG.md) 新增一筆（最上方）。
- 文件中的指標數字必須取自 `reports/metrics.md`／`metrics.json`，不得自行估算；重新評估後同步更新。
- 知識文件使用繁體中文；程式碼符號、檔名、指令維持原文。
- 新增主題時以 `NN-主題.md` 命名，並加入本索引。
