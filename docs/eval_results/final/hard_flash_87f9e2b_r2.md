# 評測報告：hard

- 執行時間：2026-10-21 12:24:47　|　輸出目錄：`/Users/remote/.pland/eval_runs/hard-final-r2-20261021-120824`
- 程式版本：`87f9e2b`　|　模型：`deepseek-flash`
- 設定：backend=`local`、memory=`on`、passes=1、label=`final-r2`
- 測試集說明：Hard suite: 8 long, discriminating tasks, each fully specified by prompt + setup + simulated-user replies and verified only by objective checks: a thread-safe TTL/LRU cache with eviction callbacks and per-key factories (hidden tests, incl. concurrency), a debugging task with six interacting bugs in a 9-module package (one bug only visible to a hidden spec test), a data-cleaning script with many edge cases (encodings, BOM, CRLF, whitespace, time zones, units, half-up rounding, duplicates) re-run on unseen data, a research task combining endoflife.date and per-release PyPI metadata verified live at check time, a three-bot implement/review loop on a strict SemVer library with hidden tests, an under-specified payout run that needs two separate clarifications and an approved push, a cross-agent task where the needed price list lives only in another bot's private workspace, and a git merge with textual and semantic conflicts resolved by stated rules.

## 總覽

| 指標 | 數值 |
|---|---|
| 任務數（可驗證） | 8（8） |
| **整體目標完成率**（Goal Completion Rate） | **62.5%** |
| **子任務完成率**（Sub-task Completion Rate，按檢查項加權） | **84.8%** |
| 成功 / 部分完成 / 失敗 / 崩潰 / 逾時 | 5 / 3 / 0 / 0 / 0 |
| 致命崩潰率 | 0.0% |
| **執行時間**：總計 / 平均 / 中位數 / P90 / 最長 | 948.3s / 118.5s / 37.1s / 506.2s / 506.2s |
| 模型調用 / 輸入 tokens（快取命中率）/ 輸出 tokens | 305 / 7,931,927（91.2%）/ 218,520 |
| 估算花費 | $0.5142 |
| HITL 請求 / 委派次數 | 8 / 8 |

判定方式：每個任務的結果只由客觀檢查項（檔案、測試、git 紀錄、HITL/委派紀錄等）決定，不採信 Agent 自行宣稱完成；「成功」= 全部必要檢查項通過；執行時間 = 任務交付給系統到最終結果產生的牆鐘時間。

## 依類別

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| coding | 2 | 50.0% | 83.3% | 114.6s |
| files | 1 | 0.0% | 20.0% | 28.0s |
| git | 1 | 0.0% | 83.3% | 26.1s |
| hitl | 1 | 100.0% | 100.0% | 19.0s |
| team | 2 | 100.0% | 100.0% | 315.6s |
| web | 1 | 100.0% | 100.0% | 14.8s |

## 依模式

| 類別 | 任務數 | 目標完成率 | 子任務完成率 | 平均時間 |
|---|---|---|---|---|
| single | 6 | 50.0% | 78.8% | 52.9s |
| team | 2 | 100.0% | 100.0% | 315.6s |

## 任務明細

| # | 任務 | 類別/模式 | 結果 | 檢查 | 時間 | 調用 | 工具(錯誤) | HITL | 委派 | 取用經驗 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `hard-ttl-lru-cache` | coding/single | 部分完成 | 6/8 | 183.05s | 62 | 60(0) | 0 | 0 | 0 |
| 2 | `hard-debug-splitbill` | coding/single | 成功 | 4/4 | 46.16s | 26 | 24(0) | 0 | 0 | 1 |
| 3 | `hard-data-cleaning-shipments` | files/single | 部分完成 | 1/5 | 28.04s | 12 | 10(0) | 0 | 0 | 0 |
| 4 | `hard-research-django-matrix` | web/single | 成功 | 4/4 | 14.84s | 9 | 7(0) | 0 | 0 | 0 |
| 5 | `hard-team-semver-review` | team/team | 成功 | 9/9 | 506.19s | 135 | 125(7) | 5 | 7 | 9 |
| 6 | `hard-hitl-payout-run` | hitl/single | 成功 | 6/6 | 19.01s | 13 | 13(0) | 3 | 0 | 0 |
| 7 | `hard-team-private-pricing` | team/team | 成功 | 4/4 | 124.91s | 31 | 29(0) | 0 | 1 | 0 |
| 8 | `hard-git-merge-conflict` | git/single | 部分完成 | 5/6 | 26.09s | 17 | 23(0) | 0 | 0 | 0 |

## 失敗模式

| 失敗模式 | 次數 |
|---|---|
| wrong or incomplete result | 2 |
| max_iterations | 1 |

- `hard-ttl-lru-cache`（部分完成，max_iterations）
  - ✗ `hidden-get-or-set`：python check failed: ASSERTION FAILED: 8 concurrent get_or_set() calls ran the factory 8 times (results ['v', 'v', 'v', 'v', 'v', 'v', 'v', 'v'])
  - ✗ `agent-tests-pass`：python check failed: with lock: results.append(r) threads = [threading.Thread(target=worker) for _ in range(8)] for t in threads: t.start() for t in threads: t.join(5) > assert len(calls) == 1 E assert 8 == 1 E + where 8
- `hard-data-cleaning-shipments`（部分完成，wrong or incomplete result）
  - ✗ `shipments-exact`：python check failed: ASSERTION FAILED: shipments.csv must use \n line endings
  - ✗ `rejects-exact`：python check failed: ASSERTION FAILED: rejects.csv must use \n line endings
  - ✗ `summary-exact`：python check failed: ASSERTION FAILED: total_weight_kg = 3550.625, expected 2848.3
  - ✗ `rerun-unseen-data`：python check failed: ASSERTION FAILED: shipments.csv must use \n line endings
- `hard-git-merge-conflict`（部分完成，wrong or incomplete result）
  - ✗ `merge-commit`：python check failed: ASSERTION FAILED: first parent / previous main tip: shop/pricing.py differs from the original — wrong parents or rewritten history

**團隊內部的錯誤**（某個成員或受託者的運行失敗，但由主導者接手處理，任務結果仍以檢查項判定）：
- `hard-team-semver-review`（成功）：@reviewer: the last 6 tool results repeated earlier results (no progress)；@reviewer: the last 6 tool results repeated earlier results (no progress)

## 記憶與經驗演化

- 取用了過往經驗的任務：2 個，目標完成率 100.0%；未取用的任務：6 個，目標完成率 50.0%。

| 任務 | Agent | 記憶條目（memory/user） | 經驗數（成功/部分/失敗） | 技能數 | 本任務新增經驗 | 本任務取用經驗 |
|---|---|---|---|---|---|---|
| `hard-ttl-lru-cache` | @default | 0/0 → 1/0 | 0 → 1（0/1/0） | 0 | 1 | 0 |
| `hard-debug-splitbill` | @default | 1/0 → 1/0 | 1 → 2（1/1/0） | 0 | 1 | 1 |
| `hard-data-cleaning-shipments` | @default | 1/0 → 1/0 | 2 → 3（1/2/0） | 0 | 1 | 0 |
| `hard-research-django-matrix` | @default | 1/0 → 1/0 | 3 → 4（2/2/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @lead | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-semver-review` | @implementer | 0/0 → 0/0 | 0 → 3（3/0/0） | 0 | 3 | 3 |
| `hard-team-semver-review` | @reviewer | 0/0 → 3/0 | 0 → 4（4/0/0） | 0 | 4 | 6 |
| `hard-hitl-payout-run` | @default | 1/0 → 2/0 | 4 → 5（3/2/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @billing | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-team-private-pricing` | @catalog | 0/0 → 1/0 | 0 → 1（1/0/0） | 0 | 1 | 0 |
| `hard-git-merge-conflict` | @default | 2/0 → 2/0 | 5 → 6（3/3/0） | 0 | 1 | 0 |

經驗的結果欄位在任務驗證後以客觀結果覆寫（ground truth），被取用的經驗依驗證結果調整 helpful/unhelpful 計數，影響之後的檢索排序。
