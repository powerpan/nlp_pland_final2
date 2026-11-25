# 重複執行統計：hard（3 次）

| 指標 | 平均 ± 標準差 |
|---|---|
| 整體目標完成率（%） | 87.5 ± 12.5 |
| 子任務完成率（%） | 94.9 ± 4.5 |
| 總執行時間（s） | 1557.8 ± 385.1 |
| 每任務平均時間（s） | 194.7 ± 48.1 |
| 模型調用 | 284.7 ± 50.6 |
| 估算花費（美分） | 51.2 ± 12.4 |
| 快取命中率（%） | 97.0 ± 0.3 |

使用的運行：`hard-thinking-20261021-113232`（5e79c4b）、`hard-final-thinking-20261021-120824`（87f9e2b）、`hard-release-20261021-124204`（44fa24a）

## 逐任務成功次數

| 任務 | 成功 | 平均時間 | 失敗模式 |
|---|---|---|---|
| `hard-ttl-lru-cache` | 3/3 | 253.2 ± 49.4s | — |
| `hard-debug-splitbill` | 3/3 | 250.2 ± 98.9s | — |
| `hard-data-cleaning-shipments` | 1/3 | 128.0 ± 9.9s | wrong or incomplete result |
| `hard-research-django-matrix` | 3/3 | 21.3 ± 1.7s | — |
| `hard-team-semver-review` | 2/3 | 600.8 ± 384.6s | no real delegation / task tracking |
| `hard-hitl-payout-run` | 3/3 | 59.8 ± 33.2s | — |
| `hard-team-private-pricing` | 3/3 | 215.9 ± 155.5s | — |
| `hard-git-merge-conflict` | 3/3 | 28.6 ± 0.6s | — |
