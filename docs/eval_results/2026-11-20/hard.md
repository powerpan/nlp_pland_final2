# 評測報告：hard

- 執行時間：2026-11-21 00:08:12　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-refresh-20261120-234752`
- 程式版本：`7a4c0fd`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`refresh`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **87.5%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **82.6%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 7 / 0 / 1 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 1179.1s / 147.4s / 90.5s / 451.9s / 451.9s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 228 / 5,511,853（95.9%）/ 203,393 |
| 估算花費 | $0.3434 |
| HITL 請求 / 委派次數 | 11 / 3 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 50.0% | 33.3% | 66.0s |
| files | 1 | 100.0% | 100.0% | 200.2s |
| git | 1 | 100.0% | 100.0% | 29.0s |
| hitl | 1 | 100.0% | 100.0% | 50.4s |
| team | 2 | 100.0% | 100.0% | 366.2s |
| web | 1 | 100.0% | 100.0% | 34.9s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 83.3% | 75.8% | 74.4s |
| team | 2 | 100.0% | 100.0% | 366.2s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 失敗 | 0/8 | 1.4s | 2 | 0(0) | 0 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 130.62s | 19 | 24(0) | 0 | 0 | 1 |
| 3 | `hard-data-cleaning-shipments` | files/single | 成功 | 5/5 | 200.22s | 21 | 21(0) | 2 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 34.94s | 11 | 11(0) | 0 | 0 | 1 |
| 5 | `hard-team-semver-review` | team/team | 成功 | 9/9 | 451.92s | 80 | 78(0) | 4 | 3 | 1 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 50.44s | 16 | 18(0) | 3 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 成功 | 4/4 | 280.58s | 67 | 70(4) | 2 | 0 | 4 |
| 8 | `hard-git-merge-conflict` | git/single | 成功 | 6/6 | 28.99s | 12 | 16(0) | 0 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| deliverable missing | 1 |

- `hard-ttl-lru-cache`（失敗，deliverable missing）
  - ✗ `package-exists`：ttlcache/__init__.py is missing or empty
  - ✗ `hidden-basics`：python check failed: Traceback (most recent call last): File "<stdin>", line 32, in <module> File "<check>", line 1, in <module> File "<check>", line 2, in _check ModuleNotFoundError: No module named 'ttlcache'
  - ✗ `hidden-expiry`：python check failed: Traceback (most recent call last): File "<stdin>", line 32, in <module> File "<check>", line 1, in <module> File "<check>", line 2, in _check ModuleNotFoundError: No module named 'ttlcache'
  - ✗ `hidden-capacity`：python check failed: Traceback (most recent call last): File "<stdin>", line 32, in <module> File "<check>", line 1, in <module> File "<check>", line 2, in _check ModuleNotFoundError: No module named 'ttlcache'

## 記憶與經驗演化

- 取用了過往經驗的任務：4 個，目標完成率 100.0%；未取用的任務：4 個，目標完成率 75.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 0/0 | 0 → 1（0/0/1） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 0/0 → 1/0 | 1 → 2（1/0/1） | 0 | 1 | 1 |
| `hard-data-cleaning-shipments` | @default | 1/0 → 1/0 | 2 → 3（2/0/1） | 1 | 1 | 0 |
| `hard-research-django-matrix` | @default | 1/0 → 3/0 | 3 → 4（3/0/1） | 1 | 1 | 1 |
| `hard-team-semver-review` | @lead | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @reviewer | 0/0 → 3/0 | 0 → 2（2/0/0） | 1 | 2 | 1 |
| `hard-hitl-payout-run` | @default | 3/0 → 4/0 | 4 → 5（4/0/1） | 1 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 4/0 | 0 → 2（2/0/0） | 0 | 2 | 1 |
| `hard-team-private-pricing` | @catalog | 0/0 → 4/0 | 0 → 3（3/0/0） | 1 | 3 | 3 |
| `hard-git-merge-conflict` | @default | 4/0 → 4/0 | 5 → 6（5/0/1） | 1 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
