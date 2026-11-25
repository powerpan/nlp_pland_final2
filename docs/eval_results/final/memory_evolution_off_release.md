# 評測報告：memory_evolution

- 執行時間：2026-10-21 12:49:29　|　輸出目錄：`/Users/remote/.pland/eval_runs/memory_evolution-release-mem-off-20261021-124555`
- 程式版本：`44fa24a`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`off`、passes=1、label=`release-mem-off`
- 測試集說明：Memory-evolution suite: six tasks of the same kind — compute request statistics from a web/application log and write them in an exact five-line format. Each task uses a differently formatted log (nginx with seconds, JSON lines with float ms and broken lines, CSV with unit suffixes, logfmt mixed with non-request lines, Apache with microseconds, two rotated pipe-separated files). The numbers depend on seven team conventions (exclude health checks, only 5xx are errors, strip query strings, convert to whole ms, nearest-rank p95, skip unparseable lines, tie-break) that are revealed ONLY when the agent asks in task 1. From task 2 on, the simulated user refuses to repeat them, so later tasks can only succeed if the agent kept them (memory notes, experiences, skills) and re-applies them. Compare per-field check pass rates across the six tasks and against a `--memory off` run to see the effect of memory. Run the tasks in order in one suite run (memory: carry).

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 6（6） |
| **整體目標完成率**（Goal Completion Rate） | **33.3%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **47.4%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 2 / 4 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 213.3s / 35.6s / 35.0s / 47.0s / 47.0s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 60 / 499,046（91.7%）/ 36,758 |
| 估算花費 | $0.0592 |
| HITL 請求 / 委派次數 | 7 / 0 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| memory | 6 | 33.3% | 47.4% | 35.6s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 33.3% | 47.4% | 35.6s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `memevo-01` | memory/single | 成功 | 7/7 | 24.58s | 9 | 9(0) | 1 | 0 | 0 |
| 2 | `memevo-02` | memory/single | 部分完成 | 1/6 | 30.3s | 10 | 9(0) | 1 | 0 | 0 |
| 3 | `memevo-03` | memory/single | 部分完成 | 1/6 | 41.55s | 9 | 9(0) | 1 | 0 | 0 |
| 4 | `memevo-04` | memory/single | 部分完成 | 2/6 | 46.97s | 11 | 12(0) | 1 | 0 | 0 |
| 5 | `memevo-05` | memory/single | 部分完成 | 1/6 | 33.89s | 11 | 10(0) | 1 | 0 | 0 |
| 6 | `memevo-06` | memory/single | 成功 | 6/7 | 36.02s | 10 | 9(0) | 2 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 4 |

- `memevo-02`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '58', expected 53
  - ✗ `errors`：python check failed: ASSERTION FAILED: errors: got '11', expected 3
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 18.97%, expected 5.66%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2143', expected 861
- `memevo-03`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '56', expected 51
  - ✗ `errors`：python check failed: ASSERTION FAILED: errors: got '7', expected 3
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 12.50%, expected 5.88%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '1755', expected 604
- `memevo-04`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '54', expected 49
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 7.41%, expected 8.16%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2312', expected 1163
  - ✗ `slowest-endpoint`：python check failed: ASSERTION FAILED: slowest_endpoint: got '/healthz', expected '/api/exports/csv'
- `memevo-05`（部分完成，wrong or incomplete result）
  - ✗ `requests`：python check failed: ASSERTION FAILED: requests: got '56', expected 51
  - ✗ `errors`：python check failed: ASSERTION FAILED: errors: got '11', expected 4
  - ✗ `error-rate`：python check failed: ASSERTION FAILED: error_rate: got 19.64%, expected 7.84%
  - ✗ `p95-ms`：python check failed: ASSERTION FAILED: p95_ms: got '2133', expected 900

## 記憶與經驗演化

- 取用了過往經驗的任務：0 個，目標完成率 —；未取用的任務：6 個，目標完成率 33.3%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `memevo-01` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-02` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-03` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-04` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-05` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `memevo-06` | @default | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
