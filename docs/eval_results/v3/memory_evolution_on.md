# 評測報告：memory_evolution

- 執行時間：2026-10-21 10:50:09　|　輸出目錄：`/Users/remote/.pland/eval_runs/memory_evolution-v3-mem-on-20261021-104648`
- 程式版本：`092349d`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=2、label=`v3-mem-on`
- 測試集說明：Memory-evolution suite: six tasks of the same kind — compute request statistics from a web/application log and write them in an exact five-line format. Each task uses a differently formatted log (nginx with seconds, JSON lines with float ms and broken lines, CSV with unit suffixes, logfmt mixed with non-request lines, Apache with microseconds, two rotated pipe-separated files). The numbers depend on seven team conventions (exclude health checks, only 5xx are errors, strip query strings, convert to whole ms, nearest-rank p95, skip unparseable lines, tie-break) that are revealed ONLY when the agent asks in task 1. From task 2 on, the simulated user refuses to repeat them, so later tasks can only succeed if the agent kept them (memory notes, experiences, skills) and re-applies them. Compare per-field check pass rates across the six tasks and against a `--memory off` run to see the effect of memory. Run the tasks in order in one suite run (memory: carry).

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 12（12） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **98.7%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 12 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 199.4s / 16.6s / 13.5s / 28.1s / 34.7s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 109 / 964,688（89.0%）/ 28,308 |
| 估算花費 | $0.0708 |
| HITL 請求 / 委派次數 | 1 / 0 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| memory | 12 | 100.0% | 98.7% | 16.6s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 100.0% | 98.7% | 16.6s |

## 多輪執行（記憶跨輪保留）

| 輪次 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| 第 1 輪 | 6 | 100.0% | 100.0% | 18.0s |
| 第 2 輪 | 6 | 100.0% | 97.4% | 15.2s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `memevo-01` | memory/single | 成功 | 7/7 | 21.05s | 11 | 9(0) | 1 | 0 | 0 |
| 2 | `memevo-02` | memory/single | 成功 | 6/6 | 11.6s | 7 | 5(0) | 0 | 0 | 1 |
| 3 | `memevo-03` | memory/single | 成功 | 6/6 | 12.11s | 7 | 5(0) | 0 | 0 | 2 |
| 4 | `memevo-04` | memory/single | 成功 | 6/6 | 14.83s | 8 | 6(0) | 0 | 0 | 3 |
| 5 | `memevo-05` | memory/single | 成功 | 6/6 | 34.73s | 18 | 15(1) | 0 | 0 | 3 |
| 6 | `memevo-06` | memory/single | 成功 | 7/7 | 13.88s | 7 | 5(0) | 0 | 0 | 3 |
| 7 | `memevo-01` (p2) | memory/single | 成功 | 6/7 | 13.67s | 8 | 6(0) | 0 | 0 | 3 |
| 8 | `memevo-02` (p2) | memory/single | 成功 | 6/6 | 12.42s | 7 | 5(0) | 0 | 0 | 3 |
| 9 | `memevo-03` (p2) | memory/single | 成功 | 6/6 | 11.05s | 6 | 4(0) | 0 | 0 | 3 |
| 10 | `memevo-04` (p2) | memory/single | 成功 | 6/6 | 13.42s | 8 | 6(0) | 0 | 0 | 3 |
| 11 | `memevo-05` (p2) | memory/single | 成功 | 6/6 | 28.09s | 15 | 12(2) | 0 | 0 | 3 |
| 12 | `memevo-06` (p2) | memory/single | 成功 | 7/7 | 12.56s | 7 | 5(0) | 0 | 0 | 3 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：11 個，目標完成率 100.0%；未取用的任務：1 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `memevo-01` | @default | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `memevo-02` | @default | 1/0 → 1/0 | 1 → 2（2/0/0） | 0 | 1 | 1 |
| `memevo-03` | @default | 1/0 → 1/0 | 2 → 3（3/0/0） | 0 | 1 | 2 |
| `memevo-04` | @default | 1/0 → 1/0 | 3 → 4（4/0/0） | 0 | 1 | 3 |
| `memevo-05` | @default | 1/0 → 2/0 | 4 → 5（5/0/0） | 0 | 1 | 3 |
| `memevo-06` | @default | 2/0 → 2/0 | 5 → 6（6/0/0） | 0 | 1 | 3 |
| `memevo-01` | @default | 2/0 → 2/0 | 6 → 7（7/0/0） | 0 | 1 | 3 |
| `memevo-02` | @default | 2/0 → 2/0 | 7 → 8（8/0/0） | 0 | 1 | 3 |
| `memevo-03` | @default | 2/0 → 2/0 | 8 → 9（9/0/0） | 0 | 1 | 3 |
| `memevo-04` | @default | 2/0 → 2/0 | 9 → 10（10/0/0） | 0 | 1 | 3 |
| `memevo-05` | @default | 2/0 → 2/0 | 10 → 11（11/0/0） | 0 | 1 | 3 |
| `memevo-06` | @default | 2/0 → 2/0 | 11 → 12（12/0/0） | 0 | 1 | 3 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
