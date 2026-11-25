# 評測報告：dev

- 執行時間：2026-10-21 10:02:21　|　輸出目錄：`/Users/remote/.pland/eval_runs/dev-docker1-20261021-100115`
- 程式版本：v1（v2 修正之前，見 docs/EVALUATION_REPORT.md 第 7 節）　|　模型：`deepseek-flash`
- 設定：backend=`docker`、memory=`on`、passes=1、label=`docker1`
- 測試集說明：Smoke tests for the evaluation harness (each task needs only a handful of agent steps): a file task, a small coding+test task, a clarification round-trip with the simulated user, and a 2-bot team task with one real delegation. Use it to check the harness end to end before running bigger suites.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 4（4） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **100.0%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 4 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 64.6s / 16.2s / 9.2s / 40.0s / 40.0s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 28 / 102,400（71.9%）/ 5,288 |
| 估算花費 | $0.0154 |
| HITL 請求 / 委派次數 | 1 / 1 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 1 | 100.0% | 100.0% | 11.2s |
| files | 1 | 100.0% | 100.0% | 6.3s |
| hitl | 1 | 100.0% | 100.0% | 7.1s |
| team | 1 | 100.0% | 100.0% | 40.0s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 3 | 100.0% | 100.0% | 8.2s |
| team | 1 | 100.0% | 100.0% | 40.0s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `dev-file-wordcount` | files/single | 成功 | 2/2 | 6.29s | 4 | 2(0) | 0 | 0 | 0 |
| 2 | `dev-code-clamp` | coding/single | 成功 | 3/3 | 11.19s | 5 | 4(0) | 0 | 0 | 0 |
| 3 | `dev-hitl-greeting` | hitl/single | 成功 | 3/3 | 7.12s | 5 | 3(0) | 1 | 0 | 0 |
| 4 | `dev-team-primes` | team/team | 成功 | 3/3 | 40.02s | 14 | 10(0) | 0 | 1 | 1 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：1 個，目標完成率 100.0%；未取用的任務：3 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `dev-file-wordcount` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `dev-code-clamp` | @default | 0/0 → 1/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `dev-hitl-greeting` | @default | 1/0 → 2/0 | 2 → 3（3/0/0） | 0 | 1 | 0 |
| `dev-team-primes` | @lead | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `dev-team-primes` | @coder | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
