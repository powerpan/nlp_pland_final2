# 評測比較

| 指標 | v2 | v3 |
|---|---|---|
| 任務數 | 8 | 8 |
| 整體目標完成率 | 100.0% | 100.0% |
| 子任務完成率 | 100.0% | 100.0% |
| 成功/部分/失敗/崩潰/逾時 | 8/0/0/0/0 | 8/0/0/0/0 |
| 總執行時間 | 497.3s | 477.5s |
| 平均 / 中位數執行時間 | 62.2s / 21.5s | 59.7s / 25.4s |
| 模型調用 | 160 | 161 |
| 輸入 / 輸出 tokens | 1,511,724 / 79,472 | 2,242,190 / 101,401 |
| 快取命中率 | 85.4% | 90.0% |
| 估算花費 | $0.1694 | $0.2010 |
| 取用經驗的任務數 | 4 | 4 |

## 逐任務

| 任務 | v2 | v3 |
|---|---|---|
| `final-calc-evaluator` | 成功 6/6 · 153.81s · 18 calls | 成功 6/6 · 48.79s · 23 calls |
| `final-data-pipeline` | 成功 5/5 · 22.87s · 8 calls | 成功 5/5 · 28.36s · 10 calls |
| `final-debug-invoicing` | 成功 4/4 · 11.91s · 6 calls | 成功 4/4 · 13.0s · 6 calls |
| `final-git-release` | 成功 7/7 · 10.72s · 6 calls | 成功 7/7 · 22.51s · 14 calls |
| `final-research-python-support` | 成功 5/5 · 10.65s · 6 calls | 成功 5/5 · 10.01s · 5 calls |
| `final-hitl-crm-export` | 成功 3/3 · 20.04s · 10 calls | 成功 3/3 · 15.91s · 8 calls |
| `final-team-logkit` | 成功 8/8 · 189.73s · 73 calls | 成功 8/8 · 247.87s · 61 calls |
| `final-team-deps-audit` | 成功 5/5 · 77.53s · 33 calls | 成功 5/5 · 91.08s · 34 calls |
