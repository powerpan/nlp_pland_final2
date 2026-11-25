# 評測報告：dev

- 執行時間：2026-11-20 22:28:08　|　輸出目錄：`/private/tmp/claude-503/-Users-remote-ericpan-study-project-NLP-final-pland/7aa311b1-c19a-4115-8581-a8163cd37e78/scratchpad/evalruns/dev-review-hkgai-20261120-222440`
- 程式版本：`8b25b6e`　|　模型：`t2_hkgai-v3_fp8_1m_e7`
- 設定：backend=`local`、memory=`on`、passes=1、label=`review-hkgai`
- 測試集說明：Smoke tests for the evaluation harness (each task needs only a handful of agent steps): a file task, a small coding+test task, a clarification round-trip with the simulated user, and a 2-bot team task with one real delegation. Use it to check the harness end to end before running bigger suites.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 4（4） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **100.0%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 4 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 184.4s / 46.1s / 23.8s / 118.4s / 118.4s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 34 / 224,480（80.4%）/ 8,370 |
| 估算花費 | $0.0243 |
| HITL 請求 / 委派次數 | 2 / 2 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 1 | 100.0% | 100.0% | 18.4s |
| files | 1 | 100.0% | 100.0% | 24.6s |
| hitl | 1 | 100.0% | 100.0% | 23.0s |
| team | 1 | 100.0% | 100.0% | 118.4s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 3 | 100.0% | 100.0% | 22.0s |
| team | 1 | 100.0% | 100.0% | 118.4s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `dev-file-wordcount` | files/single | 成功 | 2/2 | 24.62s | 5 | 3(0) | 0 | 0 | 0 |
| 2 | `dev-code-clamp` | coding/single | 成功 | 3/3 | 18.41s | 4 | 3(0) | 0 | 0 | 0 |
| 3 | `dev-hitl-greeting` | hitl/single | 成功 | 3/3 | 22.96s | 5 | 3(0) | 1 | 0 | 0 |
| 4 | `dev-team-primes` | team/team | 成功 | 3/3 | 118.4s | 20 | 18(0) | 1 | 2 | 1 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：1 個，目標完成率 100.0%；未取用的任務：3 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `dev-file-wordcount` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `dev-code-clamp` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `dev-hitl-greeting` | @default | 0/0 → 1/0 | 2 → 3（3/0/0） | 0 | 1 | 0 |
| `dev-team-primes` | @lead | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `dev-team-primes` | @coder | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
