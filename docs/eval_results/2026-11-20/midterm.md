# 評測報告：midterm

- 執行時間：2026-11-20 23:28:17　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-refresh-20261120-232008`
- 程式版本：`7a4c0fd`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`refresh`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 15（15） |
| **整體目標完成率**（Goal Completion Rate） | **93.3%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **96.8%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 14 / 1 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 424.5s / 28.3s / 12.8s / 96.4s / 120.8s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 174 / 1,469,331（86.6%）/ 70,875 |
| 估算花費 | $0.1517 |
| HITL 請求 / 委派次數 | 5 / 5 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 50.0% | 85.7% | 12.8s |
| files | 1 | 100.0% | 100.0% | 9.0s |
| git | 2 | 100.0% | 100.0% | 27.9s |
| hitl | 3 | 100.0% | 100.0% | 10.1s |
| memory | 2 | 100.0% | 85.7% | 10.3s |
| team | 3 | 100.0% | 100.0% | 85.1s |
| web | 2 | 100.0% | 100.0% | 14.0s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 91.7% | 95.5% | 14.1s |
| team | 3 | 100.0% | 100.0% | 85.1s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-files-sales-report` | files/single | 成功 | 4/4 | 9.04s | 6 | 4(0) | 0 | 0 | 0 |
| 2 | `mid-coding-roman` | coding/single | 成功 | 4/4 | 12.73s | 6 | 5(0) | 0 | 0 | 0 |
| 3 | `mid-debug-stats` | coding/single | 部分完成 | 2/3 | 12.82s | 7 | 10(0) | 0 | 0 | 0 |
| 4 | `mid-web-example-title` | web/single | 成功 | 2/2 | 11.27s | 7 | 5(0) | 0 | 0 | 0 |
| 5 | `mid-web-pypi-versions` | web/single | 成功 | 2/2 | 16.67s | 8 | 9(0) | 0 | 0 | 0 |
| 6 | `mid-git-textutils` | git/single | 成功 | 6/6 | 34.74s | 19 | 19(0) | 0 | 0 | 0 |
| 7 | `mid-git-push-bare` | git/single | 成功 | 6/6 | 21.08s | 13 | 11(1) | 1 | 0 | 1 |
| 8 | `mid-hitl-clarify-temps` | hitl/single | 成功 | 2/2 | 15.98s | 8 | 6(0) | 1 | 0 | 2 |
| 9 | `mid-hitl-approve-delete` | hitl/single | 成功 | 4/4 | 6.56s | 5 | 3(0) | 1 | 0 | 1 |
| 10 | `mid-hitl-deny-delete` | hitl/single | 成功 | 4/4 | 7.89s | 6 | 4(1) | 1 | 0 | 3 |
| 11 | `mid-memory-pref-set` | memory/single | 成功 | 3/4 | 9.09s | 6 | 6(0) | 0 | 0 | 1 |
| 12 | `mid-team-textkit` | team/team | 成功 | 6/6 | 96.36s | 29 | 29(0) | 1 | 2 | 2 |
| 13 | `mid-team-http-clients` | team/team | 成功 | 6/6 | 37.99s | 16 | 13(0) | 0 | 1 | 0 |
| 14 | `mid-team-payroll` | team/team | 成功 | 6/6 | 120.85s | 32 | 28(0) | 0 | 2 | 0 |
| 15 | `mid-memory-pref-recall` | memory/single | 成功 | 3/3 | 11.44s | 6 | 4(0) | 0 | 0 | 3 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 1 |

- `mid-debug-stats`（部分完成，wrong or incomplete result）
  - ✗ `hidden-behaviour`：python check failed: Traceback (most recent call last): File "<stdin>", line 32, in <module> File "<check>", line 1, in <module> File "<check>", line 19, in _check TypeError: bad operand type for unary -: 'str'

## 記憶與經驗演化

- 取用了過往經驗的任務：7 個，目標完成率 100.0%；未取用的任務：8 個，目標完成率 87.5%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-files-sales-report` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-coding-roman` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-debug-stats` | @default | 0/0 → 1/0 | 2 → 3（2/1/0） | 0 | 1 | 0 |
| `mid-web-example-title` | @default | 1/0 → 1/0 | 3 → 4（3/1/0） | 0 | 1 | 0 |
| `mid-web-pypi-versions` | @default | 1/0 → 2/0 | 4 → 5（4/1/0） | 0 | 1 | 0 |
| `mid-git-textutils` | @default | 2/0 → 3/0 | 5 → 6（5/1/0） | 0 | 1 | 0 |
| `mid-git-push-bare` | @default | 3/0 → 5/0 | 6 → 7（6/1/0） | 0 | 1 | 1 |
| `mid-hitl-clarify-temps` | @default | 5/0 → 5/0 | 7 → 8（7/1/0） | 0 | 1 | 2 |
| `mid-hitl-approve-delete` | @default | 5/0 → 5/0 | 8 → 9（8/1/0） | 0 | 1 | 1 |
| `mid-hitl-deny-delete` | @default | 5/0 → 6/0 | 9 → 10（9/1/0） | 0 | 1 | 3 |
| `mid-memory-pref-set` | @default | 6/0 → 6/2 | 10 → 11（10/1/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @planner | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @coder | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-textkit` | @tester | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-http-clients` | @writer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @planner | 2/0 → 3/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @analyst | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @reviewer | 0/0 → 2/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-memory-pref-recall` | @default | 6/2 → 6/2 | 11 → 12（11/1/0） | 0 | 1 | 3 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
