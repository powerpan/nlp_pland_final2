# 評測報告：hard

- 執行時間：2026-10-21 12:19:52　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-final-r1-20261021-120824`
- 程式版本：`87f9e2b`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`final-r1`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **62.5%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **84.8%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 5 / 3 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 658.2s / 82.3s / 42.0s / 363.1s / 363.1s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 297 / 6,583,054（95.2%）/ 130,206 |
| 估算花費 | $0.2895 |
| HITL 請求 / 委派次數 | 4 / 1 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 42.0s |
| files | 1 | 0.0% | 40.0% | 79.5s |
| git | 1 | 100.0% | 100.0% | 14.6s |
| hitl | 1 | 100.0% | 100.0% | 19.6s |
| team | 2 | 0.0% | 69.2% | 224.1s |
| web | 1 | 100.0% | 100.0% | 12.2s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 83.3% | 90.9% | 35.0s |
| team | 2 | 0.0% | 69.2% | 224.1s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 成功 | 8/8 | 59.79s | 19 | 19(0) | 0 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 24.27s | 12 | 10(0) | 1 | 0 | 1 |
| 3 | `hard-data-cleaning-shipments` | files/single | 部分完成 | 2/5 | 79.47s | 28 | 26(4) | 0 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 12.19s | 6 | 5(0) | 0 | 0 | 1 |
| 5 | `hard-team-semver-review` | team/team | 部分完成 | 6/9 | 363.12s | 167 | 158(12) | 0 | 1 | 1 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 19.61s | 13 | 11(0) | 3 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 部分完成 | 3/4 | 85.12s | 43 | 38(1) | 0 | 0 | 1 |
| 8 | `hard-git-merge-conflict` | git/single | 成功 | 6/6 | 14.59s | 9 | 12(0) | 0 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 2 |
| no real delegation / task tracking | 1 |

- `hard-data-cleaning-shipments`（部分完成，wrong or incomplete result）
  - ✗ `shipments-exact`：python check failed: ASSERTION FAILED: shipments.csv: 16 data rows (expected 15); ['EU10010', '2026-09-26', 'Eva Novak', 'AT', '125.000'] != expected ['EU10011', '2026-09-27', 'Tom Baker', 'GB', '1000.250']; ['EU10011', 
  - ✗ `rejects-exact`：python check failed: ASSERTION FAILED: rejects.csv: 22 data rows (expected 23); ['eu_shipments.csv', '15', 'bad_date'] != expected ['eu_shipments.csv', '13', 'bad_weight']; ['eu_shipments.csv', '16', 'unknown_country'] !
  - ✗ `summary-exact`：python check failed: ASSERTION FAILED: summary.json valid = 16, expected 15
- `hard-team-semver-review`（部分完成，no real delegation / task tracking）
  - ✗ `review-findings`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpfwthvf9g/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `delegated-implementer`：0 delegation(s) to implementer (need ≥1)
  - ✗ `delegated-reviewer`：0 delegation(s) to reviewer (need ≥1)
- `hard-team-private-pricing`（部分完成，wrong or incomplete result）
  - ✗ `quotes-exact`：python check failed: ASSERTION FAILED: ['ORD-3001', 'Nordlicht GmbH', '587.50', '35.55', '5.90', '557.85'] != expected ['ORD-3001', 'Nordlicht GmbH', '587.50', '35.54', '5.90', '557.86']

**團隊內部的錯誤**（某個成員或受託者的運行失敗，但由主導者接手處理，任務結果仍以檢查項判定）：
- `hard-team-semver-review`（部分完成）：@implementer: the same run_shell call was repeated 5 times with identical arguments；@lead: the same run_shell call was repeated 5 times with identical arguments；@reviewer: max_iterations

## 記憶與經驗演化

- 取用了過往經驗的任務：4 個，目標完成率 50.0%；未取用的任務：4 個，目標完成率 75.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 1 |
| `hard-data-cleaning-shipments` | @default | 0/0 → 1/0 | 2 → 3（2/1/0） | 0 | 1 | 0 |
| `hard-research-django-matrix` | @default | 1/0 → 1/0 | 3 → 4（3/1/0） | 0 | 1 | 1 |
| `hard-team-semver-review` | @lead | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 1/0 | 0 → 2（0/2/0） | 0 | 2 | 1 |
| `hard-team-semver-review` | @reviewer | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-hitl-payout-run` | @default | 1/0 → 2/0 | 4 → 5（4/1/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 2/0 | 0 → 2（0/2/0） | 0 | 2 | 0 |
| `hard-team-private-pricing` | @catalog | 0/0 → 2/0 | 0 → 2（0/2/0） | 0 | 2 | 1 |
| `hard-git-merge-conflict` | @default | 2/0 → 2/0 | 5 → 6（5/1/0） | 0 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
