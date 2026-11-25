# 評測報告：midterm

- 執行時間：2026-10-21 11:07:25　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-v3-docker-fix-20261021-110452`
- 程式版本：`eee3f13-dirty`　|　模型：`deepseek-flash`
- 設定：backend=`docker`、memory=`on`、passes=1、label=`v3-docker-fix`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 5（5） |
| **整體目標完成率**（Goal Completion Rate） | **100.0%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **92.3%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 5 / 0 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 140.0s / 28.0s / 27.1s / 60.7s / 60.7s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 83 / 516,234（86.5%）/ 16,778 |
| 估算花費 | $0.0438 |
| HITL 請求 / 委派次數 | 2 / 3 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| git | 1 | 100.0% | 66.7% | 37.4s |
| hitl | 2 | 100.0% | 100.0% | 7.4s |
| team | 2 | 100.0% | 100.0% | 43.9s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 3 | 100.0% | 85.7% | 17.4s |
| team | 2 | 100.0% | 100.0% | 43.9s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-git-push-bare` | git/single | 成功 | 4/6 | 37.39s | 23 | 21(0) | 0 | 0 | 0 |
| 2 | `mid-hitl-approve-delete` | hitl/single | 成功 | 4/4 | 8.86s | 7 | 5(0) | 1 | 0 | 0 |
| 3 | `mid-hitl-deny-delete` | hitl/single | 成功 | 4/4 | 5.98s | 5 | 3(1) | 1 | 0 | 0 |
| 4 | `mid-team-http-clients` | team/team | 成功 | 6/6 | 27.13s | 18 | 13(1) | 0 | 1 | 1 |
| 5 | `mid-team-payroll` | team/team | 成功 | 6/6 | 60.67s | 30 | 23(0) | 0 | 2 | 2 |

## 失敗模式

無。

## 記憶與經驗演化

- 取用了過往經驗的任務：2 個，目標完成率 100.0%；未取用的任務：3 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-git-push-bare` | @default | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-hitl-approve-delete` | @default | 2/0 → 2/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-hitl-deny-delete` | @default | 2/0 → 2/0 | 2 → 3（3/0/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @writer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @planner | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @analyst | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @reviewer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
