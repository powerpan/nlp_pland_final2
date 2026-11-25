# 評測報告：hard

- 執行時間：2026-10-21 12:01:36　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-official-r1-20261021-113232`
- 程式版本：`5e79c4b`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`official-r1`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **62.5%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **82.6%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 5 / 3 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 1716.8s / 214.6s / 37.9s / 1092.9s / 1092.9s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 252 / 11,762,737（94.2%）/ 610,999 |
| 估算花費 | $1.0038 |
| HITL 請求 / 委派次數 | 6 / 3 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 100.0% | 100.0% | 37.9s |
| files | 1 | 0.0% | 20.0% | 427.3s |
| git | 1 | 100.0% | 100.0% | 23.6s |
| hitl | 1 | 100.0% | 100.0% | 17.8s |
| team | 2 | 0.0% | 69.2% | 579.5s |
| web | 1 | 100.0% | 100.0% | 13.3s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 83.3% | 87.9% | 93.0s |
| team | 2 | 0.0% | 69.2% | 579.5s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 成功 | 8/8 | 49.07s | 16 | 14(0) | 0 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 26.81s | 13 | 11(0) | 1 | 0 | 1 |
| 3 | `hard-data-cleaning-shipments` | files/single | 部分完成 | 1/5 | 427.31s | 51 | 48(19) | 0 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 13.35s | 9 | 7(0) | 0 | 0 | 0 |
| 5 | `hard-team-semver-review` | team/team | 部分完成 | 6/9 | 1092.93s | 108 | 106(42) | 0 | 2 | 0 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 17.75s | 12 | 10(0) | 3 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 部分完成 | 3/4 | 65.98s | 30 | 25(1) | 1 | 1 | 1 |
| 8 | `hard-git-merge-conflict` | git/single | 成功 | 6/6 | 23.59s | 13 | 11(0) | 1 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 2 |
| no real delegation / task tracking | 1 |

- `hard-data-cleaning-shipments`（部分完成，wrong or incomplete result）
  - ✗ `shipments-exact`：python check failed: ASSERTION FAILED: shipments.csv must use \n line endings
  - ✗ `rejects-exact`：python check failed: ASSERTION FAILED: rejects.csv must use \n line endings
  - ✗ `summary-exact`：python check failed: ASSERTION FAILED: total_weight_kg = 3550.625, expected 2848.3
  - ✗ `rerun-unseen-data`：python check failed: ASSERTION FAILED: shipments.csv must use \n line endings
- `hard-team-semver-review`（部分完成，no real delegation / task tracking）
  - ✗ `hidden-parse`：python check failed: ASSERTION FAILED: 1 problem(s): parse('1.2.3\n') accepted an invalid version
  - ✗ `review-findings`：python check failed: Traceback (most recent call last): File "/var/folders/q6/s34w02z9295__96xgt4y86nh0000gq/T/tmpglxpknyc/check.py", line 27, in <module> exec(compile(_tree, "<check>", "exec"), _ns) File "<check>", line
  - ✗ `delegated-reviewer`：0 delegation(s) to reviewer (need ≥1)
  - 錯誤：run budget exhausted (108/120 calls, 1643210/3000000 weighted tokens)
- `hard-team-private-pricing`（部分完成，wrong or incomplete result）
  - ✗ `quotes-exact`：python check failed: ASSERTION FAILED: ['ORD-3001', 'Nordlicht GmbH', '587.50', '35.54', '5.90', '663.85'] != expected ['ORD-3001', 'Nordlicht GmbH', '587.50', '35.54', '5.90', '557.86']; ['ORD-3002', 'Café Lumière SARL'

## 記憶與經驗演化

- 取用了過往經驗的任務：2 個，目標完成率 50.0%；未取用的任務：6 個，目標完成率 66.7%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 0/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 0/0 → 0/0 | 1 → 2（2/0/0） | 0 | 1 | 1 |
| `hard-data-cleaning-shipments` | @default | 0/0 → 1/0 | 2 → 3（2/1/0） | 0 | 1 | 0 |
| `hard-research-django-matrix` | @default | 1/0 → 1/0 | 3 → 4（3/1/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @lead | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @reviewer | 0/0 → 0/0 | 0 → 0（0/0/0） | 0 | 0 | 0 |
| `hard-hitl-payout-run` | @default | 1/0 → 2/0 | 4 → 5（4/1/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @catalog | 0/0 → 1/0 | 0 → 2（0/2/0） | 0 | 2 | 1 |
| `hard-git-merge-conflict` | @default | 2/0 → 3/0 | 5 → 6（5/1/0） | 0 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
