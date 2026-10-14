# 國道壅塞預測與系統最佳分流（MVP）

以高公局 M05A（5 分鐘站間中位數車速）預測國 1 湖口 → 高公局（北上）走廊的壅塞，並以「分流配額」避免所有用戶改走同一條替代道路。
走廊：國1平面（14 段）與五楊高架（4 段），各 41.0 km。提案文件見 [`docs/proposal.md`](docs/proposal.md)，評估數字見 [`reports/metrics.md`](reports/metrics.md)。

資料來源：交通部高速公路局「交通資料庫」（https://tisvcloud.freeway.gov.tw/）。對外提供須標示出處；重複擷取間隔須大於 40 秒（`fcf.http.fetch` 預設 41 秒節流）。

## 安裝

```bash
uv sync
```

## 完整流程

```bash
uv run fcf fetch-static                                   # 路段幾何、2026 辦公日曆
uv run fcf fetch-history --start 2026-04-01 --end 2026-09-06   # 約 1.8 小時（41 秒節流），可中斷續傳
uv run fcf build-dataset                                  # data/processed/corridor.parquet
uv run fcf train                                          # models/
uv run fcf evaluate                                       # reports/metrics.{json,md}
uv run fcf find-events --top 5                            # 挑壅塞事件日
uv run fcf replay --date 2026-08-12                       # dashboard/data/replay-*.json
uv run python -m http.server 8000 -d dashboard            # http://localhost:8000
uv run fcf notify-test                                    # LINE 推播測試
uv run fcf live --poll 120 [--push]                       # 即時模式，輸出 dashboard/data/live.json
uv run pytest -q
```

TEST 期間與 TRAIN 期間固定寫在 `src/fcf/features.py`，以便重現。

## LINE 推播設定

未設定環境變數時為 dry-run，只印出訊息。要實際推播：

1. 到 [LINE Developers Console](https://developers.line.biz/console/) 建立 Provider，新增 **Messaging API** channel。
2. 在 channel 的 **Messaging API** 分頁，Issue 一組 **Channel access token (long-lived)**。
3. 在 **Basic settings** 分頁最下方取得 **Your user ID**，並用手機掃描 Messaging API 分頁的 QR code 加該 bot 為好友。
4. 設定環境變數後執行：

```bash
export LINE_CHANNEL_ACCESS_TOKEN=...
export LINE_USER_ID=U...
uv run fcf notify-test
```

## 結構

| 檔案 | 說明 |
|---|---|
| `src/fcf/http.py` | SSL 修正與 tisvcloud 節流，所有對高公局的請求都經過 `fetch` |
| `src/fcf/corridor.py` | 18 個路段 ID 與距離的唯一來源 |
| `src/fcf/features.py` | 訓練、評估、replay、live 共用的特徵路徑 |
| `src/fcf/diversion.py` | 系統最佳分流配額與推播決策 |
| `src/fcf/evaluate.py` | 車速誤差、壅塞前預警、提前量、分流模擬 |
| `dashboard/` | 純靜態儀表板（Leaflet + Chart.js） |
