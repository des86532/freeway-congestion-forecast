# 08 指令與工作流速查

對應原始碼：`src/fcf/cli.py`

本文件整理本專案所有命令列指令、參數定義、輸入輸出產物與常用工作流場景。

---

## 常用場景與工作流

### 場景 1：快速啟動與檢視視覺化儀表板
不需要重新抓取資料或訓練模型，直接使用 repository 內建的歷史重播與指標資料：

```bash
# 1. 安裝環境依賴
uv sync

# 2. 啟動本機靜態伺服器
uv run python -m http.server 8000 -d dashboard
```
瀏覽器開啟 `http://localhost:8000` 即可檢視地圖、路段車速曲線與分流決策。

---

### 場景 2：重播特定歷史壅塞事件
找出測試集（2026-08-01 ～ 2026-09-06）中最嚴重的壅塞日並產出重播檔：

```bash
# 1. 找出平面與高架旅行時間差最大的前 5 名工作日
uv run fcf find-events --top 5

# 2. 針對特定日期進行早上通勤時段（06:00 ~ 10:00）回放運算
uv run fcf replay --date 2026-08-12

# 3. 開啟儀表板檢視該日回放
uv run python -m http.server 8000 -d dashboard
```

---

### 場景 3：啟動即時路況監控與 LINE 推播
每 2 分鐘定期抓取高公局最新資料，計算預測並輸出至儀表板，符合條件時推播分流建議：

```bash
# 1. （可選）設定 LINE 推播環境變數，若未設定則為 dry-run 模式
export LINE_CHANNEL_ACCESS_TOKEN="<你的 Channel Access Token>"
export LINE_USER_ID="<你的 LINE User ID>"

# 2. 測試 LINE 推播連線與卡片文字
uv run fcf notify-test

# 3. 啟動即時監控迴圈（每 120 秒輪詢一次高公局資料庫）
uv run fcf live --poll 120 --push
```

---

### 場景 4：從原始資料重建整個模型與評估報告
從零開始下載原始檔案、特徵工程、模型訓練到產出指標：

```bash
# 1. 下載基礎靜態幾何與 2026 辦公日曆
uv run fcf fetch-static

# 2. 爬取歷史 M05A 車速原始資料（內建 41 秒防封鎖節流，可中斷續傳）
uv run fcf fetch-history --start 2026-04-01 --end 2026-09-06

# 3. 建立網格化特徵資料集
uv run fcf build-dataset

# 4. 訓練迴歸模型、壅塞機率分類器與歷史基準線
uv run fcf train

# 5. 在測試集上計算各項預警指標與分流模擬效益
uv run fcf evaluate

# 6. 執行測試確認所有邏輯正常
uv run pytest -q
```

---

## 所有 CLI 子指令詳細說明

所有子指令皆透過 `uv run fcf <子指令>` 執行，程式碼入口為 `src/fcf/cli.py`。

### 1. `fetch-static`
* **用途**：下載走廊路段幾何圖資與 2026 行政院辦公日曆。
* **參數**：無。
* **來源**：高公局 `ETagPair.xml`、行政院人事行政總處日曆 CSV。
* **產出**：
  * `data/static/corridor_geometry.json`（供 Dashboard 繪製路網經緯度座標）。
  * `data/static/calendar_2026.csv`（判定平日/假日的基準）。
* **注意事項**：若有任何路段缺少幾何資訊，程式將印出警告並終止，不會寫入損壞檔案。

---

### 2. `fetch-history`
* **用途**：下載高公局歷史 M05A 車速與流量整日壓縮檔。
* **參數**：
  * `--start`（必填，格式 `YYYY-MM-DD`）：開始日期。
  * `--end`（必填，格式 `YYYY-MM-DD`）：結束日期。
  * `--min-interval`（選填，預設 `41.0`）：兩次 HTTP 請求間的最小等待秒數。
* **來源**：高公局交通資料庫 `https://tisvcloud.freeway.gov.tw/history/TDCS/M05A/`。
* **產出**：`data/raw/M05A_YYYYMMDD.tar.gz`。
* **注意事項**：
  * 高公局要求同一 host 請求間隔須大於 40 秒，因此預設節流 41 秒。
  * 已完整下載的日期會自動略過，中斷後可直接重新執行續傳。單日失敗不會中斷整個流程，最後會統整印出 `failed dates`。

---

### 3. `build-dataset`
* **用途**：解析歷史 tar.gz 原始檔並轉換為乾淨的時空網格特徵檔。
* **參數**：無。
* **來源**：`data/raw/M05A_*.tar.gz`、`data/static/calendar_2026.csv`。
* **產出**：`data/processed/corridor.parquet`。
* **處理邏輯**：
  * 僅保留小客車（`VehicleType == "31"`）且屬於本走廊 18 個路段之記錄。
  * 建立連續 5 分鐘的時間網格（每日 288 個時段 × 18 路段）。
  * 針對車速缺值最多向前補齊 3 步（15 分鐘）；流量不填補。
  * 整合辦公日曆產出 `is_holiday` 欄位。

---

### 4. `train`
* **用途**：訓練機器學習模型與建立基準線。
* **參數**：無。
* **來源**：`data/processed/corridor.parquet`（固定使用 TRAIN 期間：2026-04-01 ～ 2026-07-31）。
* **產出**：
  * `models/h{15,30,60}.joblib`：15、30、60 分鐘後的車速迴歸模型（`HistGradientBoostingRegressor`）。
  * `models/c{15,30,60}.joblib`：15、30、60 分鐘後的壅塞機率分類器（`HistGradientBoostingClassifier`）與最佳判定門檻。
  * `models/profile.parquet`：依 (路段, 時段, 是否放假) 計算的歷史平均車速。
  * `models/capacity.json`：各路段道路容量估計值（供 BPR 函數計算分流配額）。

---

### 5. `evaluate`
* **用途**：在 TEST 測試集（2026-08-01 ～ 2026-09-06）評估各項模型指標。
* **參數**：無。
* **來源**：`data/processed/corridor.parquet`、`models/`。
* **產出**：
  * `reports/metrics.json` 與 `reports/metrics.md`（完整報告）。
  * `dashboard/data/metrics.json`（供 Dashboard 指標卡讀取）。
* **評估項目**：
  * 車速預測 MAE（對照 Naive 前期值、歷史平均 Profile）。
  * 壅塞前預警指標（Precision, Recall, F1）。
  * 壅塞起點偵測率與提前量（中位數分鐘）。
  * 系統最佳分流模擬節省之車輛·秒數。

---

### 6. `find-events`
* **用途**：掃描 TEST 期間平日上班尖峰（06:00 ～ 10:00），找出分流效益最高或壅塞最嚴重的事件日。
* **參數**：
  * `--top`（選填，預設 `5`）：列出排名前 N 名的事件日。
* **來源**：`data/processed/corridor.parquet`。
* **輸出**：於終端機印出日期表格，包含平面與高架旅行時間差（秒）以及平面嚴重壅塞路段數。

---

### 7. `replay`
* **用途**：回放指定日期指定時段的車速預測與分流決策歷程。
* **參數**：
  * `--date`（必填，格式 `YYYY-MM-DD`）：指定回放日期。
  * `--start`（選填，預設 `06:00`）：回放開始時間。
  * `--end`（選填，預設 `10:00`）：回放結束時間。
* **來源**：`data/processed/corridor.parquet`、`models/`。
* **產出**：
  * `dashboard/data/replay-YYYYMMDD.json`（包含每 5 分鐘的時間序列 frame）。
  * 自動將日期加入 `dashboard/data/index.json` 的下拉清單。

---

### 8. `notify-test`
* **用途**：驗證 LINE Messaging API 推播連線與訊息排版樣式。
* **參數**：無。
* **相關環境變數**：
  * `LINE_CHANNEL_ACCESS_TOKEN`：LINE Messaging API 的 Channel Access Token。
  * `LINE_USER_ID`：接收推播的目標 User ID（以 `U` 開頭）。
* **行為**：
  * 若環境變數齊全，送出測試改道卡片訊息至指定 LINE 帳號。
  * 若未設定環境變數，以 dry-run 模式於終端機印出推播 JSON 與排版文字。

---

### 9. `live`
* **用途**：啟動常駐即時監控迴圈。
* **參數**：
  * `--poll`（選填，預設 `120`）：向高公局查詢最新 M05A 檔案的輪詢週期（秒）。
  * `--push`（選填 flag，預設關閉）：當達到分流條件時，是否真正透過 LINE 送出推播。
* **來源**：高公局即時 M05A 檔案、`models/`。
* **產出**：
  * `dashboard/data/live.json`（供 Dashboard 即時模式讀取，每 60 秒刷新）。
* **行為**：抓取最新車速 → 滾動計算特徵與預測 → 判定是否達到分流門檻（`saving ≥ 300s`）且脫離 30 分鐘冷卻期 → 符合則輸出決策並可選擇推播。

---

## 輔助指令

| 指令 | 說明 |
|---|---|
| `uv run python -m http.server 8000 -d dashboard` | 啟動靜態網頁伺服器（連接埠 8000） |
| `uv run pytest -q` | 執行測試套件（安靜輸出模式） |
| `uv run pytest tests/test_diversion.py` | 執行單一測試檔案 |
