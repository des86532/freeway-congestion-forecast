# 07 儀表板

對應原始碼：`dashboard/index.html`、`dashboard/app.js`、`dashboard/style.css`

純靜態頁面（Leaflet 地圖 + Chart.js），啟動方式：`uv run python -m http.server 8000 -d dashboard`，開 `http://localhost:8000`。外部依賴由 unpkg／jsdelivr CDN 載入，地圖底圖為 OpenStreetMap。

## 資料來源檔（`dashboard/data/`）

| 檔案 | 產生者 | 用途 |
|---|---|---|
| `index.json` | `fcf replay` | 重播日期清單，填入「資料」下拉選單 |
| `replay-YYYYMMDD.json` | `fcf replay` | 重播資料（schema 見 06） |
| `live.json` | `fcf live` | 即時資料（`.gitignore` 排除） |
| `metrics.json` | `fcf evaluate` | 「模型評估指標」區 |

「資料」下拉選單：每個重播日期一項，最後一項「即時」。選擇重播時，slider 預設停在第一個 `decision.push` 的 frame，沒有則停在起點。

## 地圖

- 上方切換鈕：「實際車速」顯示 `frame.actual`；「預測 +30 分」顯示 `frame.pred["30"]`。
- 路段顏色（對照 `index.html` 圖例）：

| 車速 km/h | 顏色 |
|---|---|
| ≥ 80 | 綠 `#2e9e4f` |
| 60–79 | 黃 `#e6c229` |
| 40–59 | 橘 `#ef8a1e` |
| < 40 | 紅 `#d6372f` |
| 無資料（null） | 灰 `#9aa0a6` |

- 國1平面與五楊高架在地圖上幾乎重疊，因此高架畫粗線（9px、半透明）在底，平面畫細線（4px）在上。
- Tooltip：路線名稱、路段描述、車速（無資料顯示「無資料」）。在「預測 +30 分」模式且 frame 有 `prob` 時，多一行「+30 分壅塞機率 N%」（該路段機率為 null 時不顯示）。
- 時間軸 slider 逐 frame 移動，右側顯示該 frame 的 `ts`。

## 推播卡（`renderPush`）

- `decision.push` 為真：顯示「推播」徽章、入選改道用戶的訊息（`message`）、未入選用戶訊息（`stay_message`，若有），以及情境表（全部訂閱用戶改道 naive 30%、配額分流 `p*`）：替代路線預測 TT、相對增加、節省。底下註明慢路線預測比快路線多幾分鐘。
- 否則：顯示「不推播」與 `REASON_ZH[reason]` 的中文原因，若有 `saving_naive_s` 一併顯示兩路線預測差。

## 壅塞預警卡（`renderAlarm`）

位於「推播」卡之後，標題「壅塞預警（未來 15／30／60 分）」。依 `["15","30","60"]` 各一列：`+{h} 分：` 後接 `frame.alarm[h]` 的每個路段「路線名 路段描述（壅塞機率%）」，以「、」連接；沒有則顯示「無」。路段名稱由 `data.corridor.segments` 依 id 查找，機率取 `frame.prob[h][id]`。若 frame 沒有 `alarm` 欄位（舊的 replay／live 檔），顯示「此資料無預警欄位：請重新執行 uv run fcf replay」。

## 路線旅行時間圖

Chart.js 折線圖：國1平面／五楊高架各兩條——實際（`route_tt.actual`，實線）與預測 +30（`route_tt.pred30`，虛線），單位分鐘，垂直虛線標示目前 slider 所在 frame。

## 指標區（`renderMetrics`）

讀取 `data/metrics.json`，顯示：期間、車速預測誤差 MAE（最小值標 `better`）、壅塞前預警（每個時距×子集各兩列：`回歸模型` 讀 `r.model`、`分類器` 讀 `r.classifier`；欄位 Precision／Recall／F1／實際壅塞數）、壅塞起點提前量（讀 `m.onset.regressor`／`m.onset.classifier`，各一列）、分流模擬。缺檔時顯示「尚無評估指標：請先執行 uv run fcf evaluate」。舊版 `metrics.json`（沒有 `classifier` 欄位）無法顯示，需重新執行 `fcf evaluate`。

## 即時更新

選擇「即時」時載入 `data/live.json`，之後每 60 秒重新載入一次（失敗則保留舊資料）；原本停在最後一個 frame 時，會跟著停在新的最後一個 frame。
