# DeepSeek 接入方式與實際調用規範

本文件給這個項目的開發者（包括 AI 編程助手）看：怎麼接 DeepSeek，以及什麼時候該用真實 API、用多少。
內容沿用上一個項目 MACP（`../final planc`）實際跑通並測量過的做法，2026-10-19～20 實測。

一句話：**真實調用是正常開發的一部分，不需要迴避；但每次都要有明確目的和上限。** 按下面的實測數字，
正常驗證的花費只有幾美分。真正要防的是失控的循環和沒有目的的重複，不是正常使用。

---

## 1. 密鑰

- 密鑰在項目根目錄的 `.env`：`DEEPSEEK_API_KEY=...`，權限 600，已被 `.gitignore` 忽略。
- 代碼從環境變量讀取（例如 `python-dotenv` 加載 `.env`），不要寫死在代碼裡。
- **絕不**列印、記錄日誌或提交密鑰。這個倉庫連著 GitHub，提交前檢查改動裡沒有 `sk-` 開頭的字串。
- 找不到密鑰時，停下來告訴使用者，不要用假結果冒充真實調用。
- 同一把密鑰可用於對話模型、Search API 和 Fetch API。

## 2. 接入方式（OpenAI 相容格式）

| 項目 | 做法 |
|---|---|
| 端點 | `POST https://api.deepseek.com/chat/completions`，標頭 `Authorization: Bearer $DEEPSEEK_API_KEY` |
| 模型 | 預設 `deepseek-flash`（快、便宜，MACP 全部實測都用它）；`deepseek-v4-pro` 更強，只在 flash 明確不夠用時才換 |
| 思考模式 | `"thinking": {"type": "enabled"}` 或 `"disabled"`；開啟時可加 `"reasoning_effort": "low" \| "high" \| "max"`。回應裡有 `reasoning_content`。關閉思考時設 `temperature: 0` |
| 工具調用 | 原生 `tools`（OpenAI function 格式）＋ `"tool_choice": "auto"`。模型給的參數可能不是合法 JSON，或帶多餘欄位，**一定要本地校驗** |
| **reasoning 回放** | 帶 `tools` 且思考模式開啟時，之前每一條 assistant 訊息的 `reasoning_content` 都要原樣送回。文件說缺了會回 400；實測回了 200，但仍然要回放 |
| JSON 模式 | `"response_format": {"type": "json_object"}`，提示詞裡要明確要求輸出 JSON |
| 串流 | `"stream": true` ＋ `"stream_options": {"include_usage": true}`；增量裡分別有 `reasoning_content`、`content` 和 tool call 片段 |
| 用量與快取 | `usage` 裡有 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`。前綴快取實測命中 78–93% |
| 錯誤處理 | 429、5xx、逾時：退避重試（1、2、4 秒，最多 3 次）。401/402/403 和 400：直接失敗，不重試。逾時設 300 秒左右 |
| 上下文 | 1M tokens，但每次調用都會重送整段對話，長對話仍要壓縮（見第 4 節） |

**讓快取生效（省錢的關鍵）**：系統提示詞和工具列表保持逐字節不變；對話只往後追加，不要改寫前面的訊息。
改寫一次，後面整段都會變成未命中。

**搜索與抓取**（同一把密鑰）：

- 搜索：`POST https://api.deepseek.com/v1/tools/search`，body `{"query": "...", "count": 1-50, "need_content": false}`。
  每條結果帶給模型用的摘要、相關度和日期。
- 抓取：`POST https://api.deepseek.com/v1/tools/fetch`，body `{"url": "https://..."}`，回傳 `content`（Markdown）。
- 計費：2026-11-01 起每 1,000 次成功請求 $0.75，失敗和空結果不收費。
- 失敗（被擋、限流）要報告為「失敗」，不能當成「沒有結果」。

最小示例（Python，`openai` SDK 指向 DeepSeek）：

```python
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url="https://api.deepseek.com")
resp = client.chat.completions.create(
    model="deepseek-flash",
    messages=[{"role": "user", "content": "hello"}],
    extra_body={"thinking": {"type": "disabled"}},
)
print(resp.choices[0].message.content, resp.usage)
```

MACP 裡的完整實現可直接參考：`../final planc/src/macp/providers/openai_compat.py`（請求、回放、串流、錯誤）、
`../final planc/src/macp/gateways/search.py`（Search/Fetch）、`../final planc/src/macp/config/defaults.yaml`（參數）。

## 3. 什麼時候用真實 API

### 直接用，不需要再問

1. **接入後先做一次能力探測**：對話、原生工具、工具＋思考、JSON 模式、串流各試一次（MACP 的 `doctor --probe`，只需幾次小調用）。
2. **改了協議層之後**（請求格式、reasoning 回放、串流解析）：mock 測試通過後，再做一次簡短的真實驗證。
3. **功能完成後的端到端驗收**：用固定評測案例各跑 1 次；比較兩種配置（例如單 agent 對多 agent）時各跑 3 次。
4. **重現使用者在真實對話裡遇到的問題**，以及驗證對應的修復。
5. **只有真實運行才看得到的效果**：token 用量、快取命中、壓縮對答案品質的影響。有針對性地跑幾次，比較改動前後。

### 不要用

- 單元測試、CI、預設的 `pytest`：一律用腳本化（scripted/mock）模型，不聯網、不需要密鑰。
- 腳本化模型就能重現的邏輯問題。
- 沒有目的的重複：不要每個小改動都把完整評測重跑一遍，也不要「先跑跑看」。
- 無上限的重試循環。

### 規模參考（MACP 實測）

| 場景 | 用量 | 估算花費 |
|---|---|---|
| 一次大型多 agent 團隊運行（5 個子任務，大倉庫） | 114 次調用，3.02M tokens（89% 快取命中） | 約 $0.22 |
| 測試項目到目前為止的全部 21 個 workflow | 299 次調用，4.8M 輸入 tokens（90% 命中） | 約 $0.41 |
| 小型評測案例，單 agent | 每次約 13 秒、30k tokens | 不到 1 美分 |
| 小型評測案例，多 agent | 每次約 65 秒、180k tokens | 約 1–2 美分 |

花費按 MACP 配置的估價計算（每 1M tokens：快取命中 $0.006、未命中 $0.30、輸出 $1.20）；以官網價格為準。
結論：**正常的探測、驗收和問題重現，花費都在幾美分以內，不必為了省錢而不做真實驗證。**

## 4. 必須有的護欄

- **每次運行設上限**。MACP 預設值可直接沿用：
  - 每個 workflow 最多 120 次模型調用、3M tokens，快取命中按 0.1 個 token 計；
  - 每個任務最多 40 次調用，每個問答回覆最多 6 次；
  - 最後 10% 的預算留給協調者寫總結；超限就停，不要靜默繼續。
- **每次調用都記帳**：調用 ID、所屬任務、輸入/輸出/快取 tokens、耗時，花了多少隨時查得到。
- **只重試暫時性錯誤**（429、5xx、逾時），帶退避，次數有上限；每次運行有逾時。
- **防循環**：同一個工具調用、同樣參數重複出現就停。
- **長對話要壓縮**：舊的大型工具結果換成「如何重新讀取」的短提示，並且要很少、但一次壓縮夠多，以保住快取。
  實測發現：剛被壓縮掉的內容不要再次壓縮，否則 agent 會反覆重讀。
- **異常就停下來查**：如果某次運行遠超預期（例如單個任務超過 1M tokens），先查原因，不要直接重跑。

## 5. 協作規則（沿用之前對 AI 助手的要求）

- 密鑰不列印、不提交；缺密鑰就停下來說明。
- 如實報告：哪些結果來自真實 API，哪些來自腳本化模型，哪些沒驗證。
- 只有使用者要求時才 commit / push；提交前做一次密鑰掃描。
- 真實運行產生的狀態和日誌放在倉庫外（例如 `~/.<項目名>/`），不要提交。
