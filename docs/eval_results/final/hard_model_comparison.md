# 評測比較

| 指標 | flash | flash+thinking | v4-pro |
|---|---|---|---|
| 任務數 | 8 | 8 | 8 |
| 整體目標完成率 | 62.5% | 75.0% | 62.5% |
| 子任務完成率 | 82.6% | 91.3% | 91.3% |
| 成功/部分/失敗/崩潰/逾時 | 5/3/0/0/0 | 6/2/0/0/0 | 5/2/0/1/0 |
| 總執行時間 | 1716.8s | 1226.5s | 1362.7s |
| 平均 / 中位數執行時間 | 214.6s / 37.9s | 153.3s / 127.3s | 170.3s / 54.8s |
| 模型調用 | 252 | 232 | 223 |
| 輸入 / 輸出 tokens | 11,762,737 / 610,999 | 5,955,515 / 257,187 | 4,190,812 / 205,719 |
| 快取命中率 | 94.2% | 96.7% | 92.5% |
| 估算花費 | $1.0038 | $0.4023 | $1.3985 |
| 取用經驗的任務數 | 2 | 1 | 3 |

## 逐任務

| 任務 | flash | flash+thinking | v4-pro |
|---|---|---|---|
| `hard-ttl-lru-cache` | 成功 8/8 · 49.07s · 16 calls | 成功 8/8 · 300.11s · 35 calls | 部分完成 7/8 · 59.04s · 15 calls |
| `hard-debug-splitbill` | 成功 4/4 · 26.81s · 13 calls | 成功 4/4 · 143.86s · 32 calls | 成功 4/4 · 71.73s · 26 calls |
| `hard-data-cleaning-shipments` | 部分完成 1/5 · 427.31s · 51 calls | 部分完成 2/5 · 117.74s · 17 calls | 部分完成 2/5 · 118.69s · 34 calls |
| `hard-research-django-matrix` | 成功 4/4 · 13.35s · 9 calls | 成功 4/4 · 21.73s · 10 calls | 成功 4/4 · 17.29s · 7 calls |
| `hard-team-semver-review` | 部分完成 6/9 · 1092.93s · 108 calls | 部分完成 8/9 · 379.14s · 60 calls | 崩潰 9/9 · 968.34s · 83 calls |
| `hard-hitl-payout-run` | 成功 6/6 · 17.75s · 12 calls | 成功 6/6 · 98.02s · 17 calls | 成功 6/6 · 35.03s · 15 calls |
| `hard-team-private-pricing` | 部分完成 3/4 · 65.98s · 30 calls | 成功 4/4 · 136.81s · 48 calls | 成功 4/4 · 50.47s · 21 calls |
| `hard-git-merge-conflict` | 成功 6/6 · 23.59s · 13 calls | 成功 6/6 · 29.05s · 13 calls | 成功 6/6 · 42.11s · 22 calls |
