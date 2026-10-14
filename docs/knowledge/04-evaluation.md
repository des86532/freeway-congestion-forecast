# 04 評估

對應原始碼：`src/fcf/evaluate.py`、`tests/test_evaluate.py`；輸出 `reports/metrics.md`、`reports/metrics.json`（同時複製到 `dashboard/data/metrics.json`）

## 資料切分與子集

- 只評估 `TEST`（2026-08-01 ～ 2026-09-06）。為了讓第一天有足夠的 lag，載入資料時多帶前一天，指標只統計 `ts` 落在 TEST 內的列。
- 子集 `all`：TEST 內全部列。
- 子集 `am_peak`：上班日（`is_holiday == 0`）且 `06:00 ≤ 預測起點時刻 < 10:00`（以起點 `ts` 判斷，不是 `t+h`）。

只有 `y`（t+h 實際車速）、`speed_lag0`、`profile_speed` 都不是 NaN 的列才納入（`ok`）。

## 車速誤差

對每個時距、每個子集計算 MAE、RMSE，並與兩個基準線比較：

- **持續法**（persistence）：直接用 `speed_lag0` 當作 t+h 的預測。
- **歷史平均**（profile）：用 `profile_speed`。

## 壅塞前預警（Precision／Recall／F1）

目的：在還沒壅塞時提早預測壅塞。

- 壅塞定義：車速 `< 40 km/h`（`CONGESTED = 40.0`）。
- **只取當下車速 `speed_lag0 ≥ 40` 的列**（已經壅塞的不算「預警」）。
- 正例：`y(t+h) < 40`。預測為正：回歸模型 `pred < 40`；歷史平均 `profile_speed < 40`；分類器 `prob ≥ 門檻`（門檻於 TRAIN 內的驗證月決定，見 [03-features-and-models.md](03-features-and-models.md)，評估時不得依 TEST 調整）。
- `_prf` 計算 TP／FP／FN，Precision = TP/(TP+FP)、Recall = TP/(TP+FN)、F1 為兩者調和平均；分母為 0 時為 `None`（報表顯示「–」）。`n_pos` 為實際壅塞數。

## 壅塞起點提前量（`onset_leads`）

針對單一路段的實際車速序列，找出「壅塞起點」並判斷預警是否提前命中，以及提前多久。`onset_leads(actual, alarms)` 收 bool 預警陣列，不直接看預測值。

1. **起點 `o`**：`actual[o] < 40`，且 `actual[o-3 .. o-1]` 全部 `≥ 40`（先連續 3 步通暢才算新的起點）。
2. 在 `t = o + off`，`off` 從 −12 到 −1 步（即 o 之前 60 分到 5 分，由最早的開始）逐一檢查。
3. 該 `t` 當下車速須 `≥ 40`。
4. 對每個時距 `h`：若 `t+h` 落在 `[o−10 分, o+10 分]`（即 `off + h/5` 介於 −2 到 +2 步）且 `alarms[h][t]` 為真，視為命中。`alarms[h]` 是 bool 陣列，由呼叫端決定「預警」的定義：回歸模型為 `pred_h < 40`，分類器為 `prob_h ≥ 門檻`。
5. **取最早命中的 `t`**，提前量 = `−off × 5` 分鐘；都沒命中則為 `None`。

回傳 `[(o, 提前分鐘或 None), ...]`。

數字範例（`tests/test_evaluate.py`）：序列 = 20 步 80 km/h 後 6 步 30 km/h，起點 `o = 20`。令 30 分預測在索引 16 為 30（< 40），即 `t=16`、`off=−4`；`t+30分 = 索引 22 = o+2 步`，落在 ±2 步內，命中。這是最早的命中，所以提前量 = 4 × 5 = **20 分鐘**，回傳 `[(20, 20)]`。若預測全是 80，回傳 `[(20, None)]`。

整體彙總（`metrics["onset"]`）：對 18 路段逐一計算，只計入 `o` 落在 TEST 內者，輸出事件數 `n`、偵測數 `detected`、偵測率、提前量中位數。回歸模型（`metrics["onset"]["regressor"]`）與分類器（`["classifier"]`）各算一次，共用內部函式 `_onset_summary`；兩者的起點事件數相同。

## 分流模擬

在 TEST 內每個上班日的 06:00–10:00，每 5 分鐘走一次 `replay.make_frames`（即與重播／live 完全相同的 `diversion.decide` 路徑，含冷卻），統計：

- 推播事件數、決策原因分布。
- 平均預估節省（naive、配額）、替代路線 TT 增加、平均 `p*`、配額生效（`p* < 0.30`）的推播數。
- **系統車輛時間節省（車輛小時）**：每次推播的 `sys_saving_*_veh_s`（輛·秒／5 分鐘流量）加總後 `× 6 / 3600`。
  - 由來：`sys_saving` 以入口 5 分鐘流量計，假設推播之後的 30 分鐘冷卻期內條件不變，30 分鐘 = 6 個 5 分鐘，因此 ×6；再除以 3600 由秒換算為小時。
  - 只含小客車，屬估算值，不是實測。

## 如何閱讀 `metrics.md`

| 區塊 | 看什麼 |
|---|---|
| 車速誤差 | 模型 MAE 是否低於持續法／歷史平均；時距越長差距越大 |
| 壅塞前預警 | 回歸模型 Precision 約 73–83%、Recall 只有 17–39%（`am_peak` 30 分：Recall 31.3%、F1 45.3%）。分類器用較低的機率門檻換 Recall：`am_peak` 30 分 Recall 63.9%、Precision 54.8%、F1 59.0%（`all` 30 分：Recall 53.4%、Precision 46.3%） |
| 壅塞起點提前量 | 回歸模型偵測率 47.3%（167／353）、提前量中位數 10 分；分類器偵測率 86.4%（305／353）、中位數 30 分 |
| 分流模擬 | 推播 151 次、平均節省（配額）9.3 分、車輛小時節省 2024（估算）；與分類器無關，數字不變 |

取捨：分類器 Recall 明顯提高，代價是 Precision 下降（誤報增加）。起點偵測率只計「有沒有提早命中」，不懲罰誤報，因此比較兩種方法時必須搭配預警表的 Precision 一起看；越容易發出警報，起點偵測率與提前量越好看。

以上為 `reports/metrics.md` 目前的數字；重新評估後以最新 `metrics.md` 為準。
