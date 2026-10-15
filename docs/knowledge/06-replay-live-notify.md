# 06 重播、即時模式、LINE 推播

對應原始碼：`src/fcf/replay.py`、`src/fcf/live.py`、`src/fcf/notify.py`

## replay.py

### `Lookup`

`Lookup(feats, preds, probs, thresholds)` 把 `build_features` 輸出與各時距預測轉成 `(ts × 18 路段)` 寬表（欄位順序依 `SEG_IDS`）：

| 屬性 | 來源 |
|---|---|
| `actual` | `speed_lag0`（當下實際車速） |
| `volume` | `volume_lag0` |
| `pred[h]` | `preds[h]` 的預測車速 |
| `prob[h]` | `probs[h]` 的壅塞機率 |
| `thresholds` | `{h: 分類器門檻}`（`c{h}.joblib` 內的 `threshold`），用來判斷 `alarm` |

### `make_frames(lk, capacity, ts_list, last_push=None)`

對 `ts_list` 的每個時間點產生一個 frame，並維護冷卻狀態：決策 `push` 為真時更新 `last_push`，供下一個時間點的冷卻判斷。evaluate 的分流模擬、replay、live 都走這個函式。

### frame JSON schema

| 欄位 | 型別 | 說明 |
|---|---|---|
| `ts` | string | `YYYY-MM-DDTHH:MM`（預測起點時刻） |
| `actual` | `{seg_id: number\|null}` | 當下實際車速，小數 1 位；NaN → `null` |
| `pred` | `{"15"\|"30"\|"60": {seg_id: number\|null}}` | 各時距預測車速（t+h），小數 1 位 |
| `route_tt.actual` | `{route: 秒\|null}` | 以實際車速估算的路線旅行時間（整數秒） |
| `route_tt.pred30` | `{route: 秒\|null}` | 以 30 分預測車速估算的路線旅行時間 |
| `decision` | object | `Decision.to_dict()`（見 05），欄位如下 |
| `prob` | `{"15"\|"30"\|"60": {seg_id: number\|null}}` | 各時距壅塞機率（t+h 車速 < 40），小數 2 位 |
| `alarm` | `{"15"\|"30"\|"60": [seg_id, ...]}` | 預警路段：`prob ≥ 該時距門檻` **且** 當下實際車速 `≥ 40`（已壅塞或車速缺值的路段不列入）；依 `SEG_IDS` 順序，沒有則為空 list |

`decision` 欄位：`push`、`reason`、`slow`、`fast`、`saving_naive_s`、`p_star`、`saving_quota_s`、`alt_tt_naive_s`、`alt_tt_quota_s`、`message`、`stay_message`、`tt_slow_s`、`tt_fast_s`、`sys_saving_quota_veh_s`、`sys_saving_naive_veh_s`。秒數欄位四捨五入到整數秒、`p_star` 到小數 2 位、NaN 為 `null`。

### `find_events(top=5)`

挑選分流效益最大的 TEST 上班日：以實際車速估各路線 TT（`actual_route_tt`，`max(speed, 5)`），取上班日 06:00–10:00 的 `平面 TT − 高架 TT` 最大值當作該日分數，列出前 `top` 天（同時印出該日國1平面「車速 < 40 的路段×時間點」總數）。

### `replay(date, start="06:00", end="10:00")`

1. 取資料 `[start − 1 小時, end]`（多 1 小時供 lag 使用）。無資料則結束。
2. `build_features` → `predict_from_features`（車速）與 `predict_proba_from_features`（壅塞機率）→ `Lookup`。
3. 只對 `[start, end]` 內的時間點產生 frame，冷卻狀態從當日起點重新開始。
4. 輸出 `{"date", "corridor", "frames"}`。`corridor` 為 `corridor_json()`（18 段的 id、route、order、distance_km、description、coords）。

### `write_replay`

寫入 `dashboard/data/replay-YYYYMMDD.json`（compact JSON），並把日期併入 `dashboard/data/index.json` 的 `replays`（排序、去重）。儀表板的資料下拉選單由 `index.json` 決定。

## live.py

`fcf live [--push] [--poll 秒]`：無窮迴圈，每 `poll` 秒（預設 120）檢查一次。

- `find_latest(now)`：列出 `/history/TDCS/M05A/YYYYMMDD/HH/` 目錄頁，取檔名（`TDCS_M05A_YYYYMMDD_HHMMSS.csv`）最大者；該小時 404 或沒有檔案就往前查一小時，最多兩個小時。
- **冷啟動**：第一次發現最新檔時，往回抓共 `WINDOW = 7` 個時間點（最新檔往前 6 步）。之後只補 `last_ts` 之後的新檔。單一時間點 HTTP 錯誤只記錄並略過。
- 只保留最近 7 個時間點（`slots`），組成長表並依 dataset 的規則補網格與 `ffill(limit=3)`（`to_df`）。
- 對新時間點產生 frame（沿用 `last_push` 冷卻），`frames` 只保留最後 `KEEP_FRAMES = 12` 個。
- 輸出 `dashboard/data/live.json`：`{"date", "generated_at", "corridor", "frames"}`。時區 `Asia/Taipei`。
- 最新 frame `decision.push` 為真且有 `--push` 才呼叫 `send_line`。
- **例外處理**：迴圈內任何例外只記錄 `error: ...`，不中斷，下個週期重試。
- 模型、分類器（`load_classifiers()`，缺檔即 `SystemExit`）與 profile、capacity 在迴圈外載入一次。
- `--push` 的行為不變：只推分流訊息（`decision.message`），`prob`／`alarm` 不推播。

## notify.py

`send_line(text)`：

- 環境變數 `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID` 缺任一 → dry-run，印出 `[DRY-RUN] LINE -> {text}`，不送出。
- 否則 POST `https://api.line.me/v2/bot/message/push`（text 訊息），非 200 或 HTTPError 丟 `RuntimeError`。

`notify_test()`：以固定範例（2026-08-12 07:30、平面→高架、「中壢-中豐」、28 km/h、節省 540 秒、`p* = 0.15`）呼叫 `format_message` 並送出。推播的文字內容見 [05-diversion.md](05-diversion.md)。
