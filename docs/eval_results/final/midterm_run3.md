# 評測報告：midterm

- 執行時間：2026-10-21 11:45:12　|　輸出目錄：`/Users/remote/.pland/eval_runs/midterm-official-r3-20261021-113819`
- 程式版本：`29c1225`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`official-r3`
- 測試集說明：Midterm suite: 15 tasks that cover every required capability at least once — file processing with computed values, coding with hidden tests, debugging, web fetch/search (verified live at check time), git commits and a push to a local bare remote, HITL clarification and approval (approved and denied), cross-session memory reuse (task 11 states a standing preference, task 15 relies on it without restating it) and three team tasks in group rooms with real delegation. Run in file order; tasks 11 and 15 must stay in the same suite run.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 15（15） |
| **整體目標完成率**（Goal Completion Rate） | **93.3%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **93.5%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 14 / 1 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 378.6s / 25.2s / 7.3s / 37.5s / 232.0s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 224 / 2,288,327（88.8%）/ 83,463 |
| 估算花費 | $0.1889 |
| HITL 請求 / 委派次數 | 4 / 5 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 7.1s |
| files | 1 | 100.0% | 100.0% | 9.2s |
| git | 2 | 100.0% | 100.0% | 11.0s |
| hitl | 3 | 100.0% | 100.0% | 5.7s |
| memory | 2 | 100.0% | 100.0% | 7.3s |
| team | 3 | 66.7% | 77.8% | 96.9s |
| web | 2 | 100.0% | 100.0% | 5.3s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 12 | 100.0% | 100.0% | 7.3s |
| team | 3 | 66.7% | 77.8% | 96.9s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `mid-files-sales-report` | files/single | 成功 | 4/4 | 9.21s | 7 | 5(0) | 0 | 0 | 0 |
| 2 | `mid-coding-roman` | coding/single | 成功 | 4/4 | 6.94s | 4 | 3(0) | 0 | 0 | 0 |
| 3 | `mid-debug-stats` | coding/single | 成功 | 3/3 | 7.31s | 6 | 4(0) | 0 | 0 | 1 |
| 4 | `mid-web-example-title` | web/single | 成功 | 2/2 | 6.97s | 6 | 4(0) | 0 | 0 | 0 |
| 5 | `mid-web-pypi-versions` | web/single | 成功 | 2/2 | 3.63s | 4 | 2(0) | 0 | 0 | 0 |
| 6 | `mid-git-textutils` | git/single | 成功 | 6/6 | 10.75s | 8 | 9(0) | 0 | 0 | 0 |
| 7 | `mid-git-push-bare` | git/single | 成功 | 6/6 | 11.32s | 9 | 7(1) | 1 | 0 | 1 |
| 8 | `mid-hitl-clarify-temps` | hitl/single | 成功 | 2/2 | 6.71s | 6 | 4(0) | 1 | 0 | 1 |
| 9 | `mid-hitl-approve-delete` | hitl/single | 成功 | 4/4 | 5.15s | 5 | 3(0) | 1 | 0 | 1 |
| 10 | `mid-hitl-deny-delete` | hitl/single | 成功 | 4/4 | 5.38s | 5 | 3(1) | 1 | 0 | 1 |
| 11 | `mid-memory-pref-set` | memory/single | 成功 | 4/4 | 8.37s | 6 | 5(0) | 0 | 0 | 0 |
| 12 | `mid-team-textkit` | team/team | 部分完成 | 2/6 | 232.04s | 108 | 97(11) | 0 | 2 | 4 |
| 13 | `mid-team-http-clients` | team/team | 成功 | 6/6 | 21.16s | 16 | 12(0) | 0 | 1 | 1 |
| 14 | `mid-team-payroll` | team/team | 成功 | 6/6 | 37.55s | 28 | 21(0) | 0 | 2 | 2 |
| 15 | `mid-memory-pref-recall` | memory/single | 成功 | 3/3 | 6.14s | 6 | 4(0) | 0 | 0 | 3 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| no real delegation / task tracking | 1 |

- `mid-team-textkit`（部分完成，no real delegation / task tracking）
  - ✗ `team-tests-pass`：python check failed: oms/room_4b94492e6828/shared/textkit: ......F....... [100%] =================================== FAILURES =================================== ___________ test_truncate_width_equals_suffix_length_retur
  - ✗ `readme`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmplmldl6yu/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `delegated`：1 delegation(s) (need ≥2)
  - ✗ `board`：1 board task(s) with status done (need ≥2)
  - 錯誤：the same run_shell call was repeated 5 times with identical arguments

## 記憶與經驗演化

- 取用了過往經驗的任務：9 個，目標完成率 88.9%；未取用的任務：6 個，目標完成率 100.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `mid-files-sales-report` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-coding-roman` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 0 |
| `mid-debug-stats` | @default | 0/0 → 0/0 | 2 → 3（3/0/0） | 0 | 1 | 1 |
| `mid-web-example-title` | @default | 0/0 → 0/0 | 3 → 4（4/0/0） | 0 | 1 | 0 |
| `mid-web-pypi-versions` | @default | 0/0 → 0/0 | 4 → 5（5/0/0） | 0 | 1 | 0 |
| `mid-git-textutils` | @default | 0/0 → 0/0 | 5 → 6（6/0/0） | 0 | 1 | 0 |
| `mid-git-push-bare` | @default | 0/0 → 1/0 | 6 → 7（7/0/0） | 0 | 1 | 1 |
| `mid-hitl-clarify-temps` | @default | 1/0 → 1/0 | 7 → 8（8/0/0） | 0 | 1 | 1 |
| `mid-hitl-approve-delete` | @default | 1/0 → 1/0 | 8 → 9（9/0/0） | 0 | 1 | 1 |
| `mid-hitl-deny-delete` | @default | 1/0 → 1/0 | 9 → 10（10/0/0） | 0 | 1 | 1 |
| `mid-memory-pref-set` | @default | 1/0 → 1/1 | 10 → 11（11/0/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @planner | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `mid-team-textkit` | @coder | 0/0 → 2/0 | 0 → 3（0/3/0） | 0 | 3 | 3 |
| `mid-team-textkit` | @tester | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 1 |
| `mid-team-http-clients` | @writer | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `mid-team-http-clients` | @researcher | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @planner | 1/0 → 1/0 | 1 → 2（1/1/0） | 0 | 1 | 0 |
| `mid-team-payroll` | @analyst | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-team-payroll` | @reviewer | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 1 |
| `mid-memory-pref-recall` | @default | 1/1 → 1/1 | 11 → 12（12/0/0） | 0 | 1 | 3 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
