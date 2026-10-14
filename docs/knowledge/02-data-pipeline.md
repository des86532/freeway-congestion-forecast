# 02 資料管線

對應原始碼：`src/fcf/http.py`、`src/fcf/tdcs.py`、`src/fcf/dataset.py`、`src/fcf/calendar.py`、`src/fcf/static.py`

## http.py：唯一的對外出口

所有對 `tisvcloud.freeway.gov.tw` 的請求都必須經過 `fetch(url, min_interval=41.0)`。

- **SSL 修正**：`SSL_CTX` 關閉 `VERIFY_X509_STRICT`。Python 3.13 預設 strict 會因為「Missing Subject Key Identifier」驗證失敗。
- **節流**：高公局交通資料庫注意事項要求同一 host 請求間隔大於 40 秒，因此預設 41 秒。`_throttle` 以 `time.monotonic()` 記錄上次請求時間，只對 `THROTTLED_HOST` 生效（其他 host，例如 DGPA 日曆，不節流；`fetch_static` 對日曆用 `min_interval=0`）。
- **重試**：最多 3 次；HTTP 404 直接丟出不重試；`URLError`、逾時、連線錯誤、`SSLError` 會重試，三次都失敗則丟出最後一個例外。每次重試前同樣經過節流。

## tdcs.py：M05A 解析與下載

M05A 為**無表頭** CSV，欄位依序為 `TimeStamp, GantryFrom, GantryTo, VehicleType, Speed, Volume`。

`parse_m05a_rows(lines, seg_ids)` 回傳 `(ts, seg, speed, volume)`：

- 欄位少於 6 或 `VehicleType != "31"` 的列略過。**只取 `31`（小客車）**。
- 路段 ID = `f"{GantryFrom}-{GantryTo}"`，不在 `seg_ids` 內略過。
- 時間格式 `%Y/%m/%d %H:%M`；時間或數值解析失敗的列略過。
- `speed <= 0` → NaN（M05A 以 0 表示無資料）；`volume < 0` → NaN。

`fetch_history(start, end)`：逐日下載 `{BASE}/history/TDCS/M05A/M05A_YYYYMMDD.tar.gz` 到 `data/raw/`。

- 已存在且 `_readable`（能以 `tarfile` 開啟並 `getmembers()`）的檔案會跳過，因此中斷後可續傳。
- 下載後若 tar 不可讀會刪除並視為失敗。單日失敗只記錄、不中斷，最後回傳失敗日期清單，由 CLI 印出。

`read_tar_rows(p, seg_ids)`：讀 tar 內所有檔案，逐檔解析。

## dataset.py：建立完整網格

`build_grid(rows)` 把解析後的列轉成完整的 (ts × seg) 長表：

1. `drop_duplicates(["ts", "seg"], keep="last")`。
2. 對資料中出現的每一天，補齊 288 個 5 分鐘時間點 × 18 路段（`reindex`）；缺漏的點為 NaN。只涵蓋資料中出現過的日期。
3. `speed` 依路段 `ffill(limit=3)`：最多往後填 3 步（15 分鐘）。`volume` 不填補。
4. 加上 `is_holiday`（`int8`），`speed`／`volume` 轉 `float32`。

輸出 `data/processed/corridor.parquet`，欄位：`ts`、`seg`、`speed`、`volume`、`is_holiday`。`build_dataset` 另印出各路段 speed 缺值率。

> 注意：`live.py` 的 `to_df` 以同樣的規則（`drop_duplicates`、`ffill(limit=3)`、`is_holiday`）處理滾動資料，兩處必須保持一致。

## calendar.py：辦公日曆

- 資料檔 `data/static/calendar_2026.csv`（行政院人事行政總處，`fetch-static` 下載）。讀取欄位 `西元日期`、`是否放假`，值為 `2` 視為放假。
- `is_holiday(d)`：日期在日曆內就用日曆；日曆未涵蓋（含檔案不存在）則以週六日判定。
- 日曆載入以 `lru_cache` 快取。

## static.py：路段幾何與日曆

`fetch_static()`：

1. 下載 `ETagPair.xml`，取出 `ETagPairID` 屬於走廊 18 段的 `Geometry`（WKT `LINESTRING`，經緯度順序轉為 `[lat, lon]`）。
2. 若有任何路段缺幾何，印出缺漏並回傳 1，不寫檔。
3. 寫入 `data/static/corridor_geometry.json`（依 `SEG_IDS` 順序），再下載辦公日曆。

幾何僅供儀表板畫地圖（`replay.corridor_json` 讀取），與模型無關。
