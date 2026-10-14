# 05 系統最佳分流

對應原始碼：`src/fcf/diversion.py`；測試 `tests/test_diversion.py`

## 常數

| 常數 | 值 | 意義 |
|---|---|---|
| `PENETRATION` | 0.30 | App 用戶佔車流比例；可改道比例上限 |
| `MIN_SAVING_S` | 300 | 兩路線預測 TT 差至少 5 分鐘才考慮推播 |
| `COOLDOWN_MIN` | 30 | 推播冷卻期 |
| `P_STEP` | 0.05 | 掃描 `p` 的步長 |
| `CONGESTED_KMH` | 40 | 壅塞車速門檻 |
| `MIN_SPEED_FOR_TT` | 5 | 計算旅行時間時車速下限（避免除以接近 0） |
| `MIN_QUOTA_SAVING_S` | 60 | 配額分流後至少省 1 分鐘 |

## 旅行時間

`route_travel_time(speeds, route)` = Σ 各段 `distance_km / max(speed, 5) × 3600`（秒）。任一段缺值（None／NaN）回傳 `None`。簡化：以同一時刻車速估整條路線，不做時變行進模擬。

分流決策使用的是 **30 分鐘後的預測車速** `pred["30"]`。

## BPR 與配額

`bpr(v, c) = 1 + 0.15 (v/c)^4`，`v` 為流量（5 分鐘），`c` 為 capacity（`capacity.json`，見 03）。

`_split_point(p, ...)`：令 `slow` 路線有比例 `p` 的流量改道到 `fast`：

- 流量：`vs = v_slow(1−p)`、`vf = v_fast + p·v_slow`。
- TT 依 BPR 比例縮放：`ts = tt_slow · bpr(vs, c_slow)/bpr(v_slow, c_slow)`、`tf = tt_fast · bpr(vf, c_fast)/bpr(v_fast, c_fast)`。
- 總車輛時間 `vs·ts + vf·tf`。

`optimal_split`：

- 掃描 `p = 0, 0.05, …, 0.30`（共 7 個），挑總車輛時間最小者；**同分（差距 ≤ 1e-9）取較小的 p**。
- 輸出 `p_star`、配額下的節省 `saving_quota_s = ts − tf`、替代路線 TT `alt_tt_quota_s`；以及全部訂閱用戶（`p = 0.30`）改道的 naive 對照 `alt_tt_naive_s`、`saving_naive_after_s`。
- `sys_saving_*_veh_s` = 改道前總車輛時間 `v_slow·tt_slow + v_fast·tt_fast` 減去改道後（配額 / naive）。

## 推播判斷 `decide`

`decide(ts, actual_speeds, pred30_speeds, volumes, capacity, last_push_ts)` 依序檢查，任一條成立就停止並設 `reason`：

| 順序 | `reason` | 條件 | 相關常數 |
|---|---|---|---|
| 1 | `missing_data` | 任一路線 TT 無法計算（預測缺值） | – |
| 2 | `below_saving` | 慢路線 − 快路線的預測 TT < 300 秒 | `MIN_SAVING_S` |
| 3 | `missing_volume` | 任一入口流量缺漏、NaN 或 ≤ 0 | – |
| 4 | `no_benefit` | `p_star == 0` 或 `saving_quota_s < 60` | `MIN_QUOTA_SAVING_S` |
| 5 | `cooldown` | 距上次推播 < 30 分鐘 | `COOLDOWN_MIN` |
| 6 | `ok` | 全部通過 → `push = True` | – |

- 慢／快路線以預測 TT 大者為慢（相同時 `ground` 為慢）。
- `ok` 時產生訊息，「最差路段」為慢路線上 `pred30` 最低的路段。
- `p_star < PENETRATION` 時（配額未涵蓋所有訂閱用戶，有人「未入選」）才額外產生 `stay_message`。
- `decide` 的 `actual_speeds` 參數目前未被使用（保留於介面）；判斷只依 `pred30_speeds`、`volumes`、`capacity` 與冷卻狀態。

`Decision` dataclass 的欄位即 frame 的 `decision`（見 06）。

## 訊息

- `format_message`：`【國道壅塞預警】預測 {ts+30 分 HH:MM} 起{慢路線}「{最差路段}」時速將降至 {x} km/h。建議改走{快路線}，預估可省 {配額節省/60 取整} 分鐘。為避免替代道路回堵，本次僅建議 {p*/0.30 ×100 取整}% 訂閱用路人改道。{資料來源}`
- `format_stay_message`：`【國道壅塞預警】{慢路線}預計延誤 {naive 節省/60 取整} 分鐘，替代道路已分流其他用路人，建議您維持原路線以免回堵。{資料來源}`
- 資料來源標示：`資料來源：交通部高速公路局「交通資料庫」`（對外必須標示）。

## 入選雜湊 `select_for_reroute`

`select_for_reroute(user_id, date, share)`：`sha256(f"{user_id}|{date}")` 前 8 個十六進位字元轉整數，`% 1000 < round(share × 1000)` 則入選。同一用戶同一天結果固定；`share` 傳入 `p_star / PENETRATION` 即得到「該用戶是否收到改道建議」。目前系統內沒有任何地方呼叫它（只有 `tests/test_diversion.py` 測試），推播目前只送給單一 LINE 收件人。
