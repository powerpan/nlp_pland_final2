# PlanD 系統架構說明

> 本文件說明 PlanD 多智能體協作平台的架構：Agent 執行循環、通訊與路由、任務分解與委派、記憶與經驗演化、
> 沙箱與隔離機制（以及**目前實際達到的邊界**）、Human-in-the-Loop、模型接入、使用者介面與評測框架。
> 程式碼路徑以 `pland/` 為根。設計上借鑑 [Hermes Agent](https://github.com/NousResearch/hermes-agent)
> （MIT License），但為獨立實作，未 fork 其程式碼；借用的設計與少量規則（危險指令模式）已在原始碼中標註出處。

---

## 1. 設計目標與總體思路

需求的核心是：**平時當作獨立 Agent 使用，需要時在 Bot Mode 自由組建團隊，讓 Agent 真正協作執行任務，並能以客觀指標驗證結果。**
據此確立了幾個原則：

1. **單 Agent 優先，多 Agent 按需。** 任何請求預設只由一個 Agent 處理（CLI `pland chat` 或網頁的 Chats 分頁）。
   多 Agent 不是固定流水線：只有當使用者建立 Bot / 群組，或 Agent 自己判斷需要時（`delegate_task`），協作才發生。
2. **沒有寫死的角色。** Bot 的數量、職稱、描述、人格（SOUL）、模型、工具全部由使用者建立時決定；群組中誰「主導」
   一個請求是依 @提及或群組設定動態決定的，任何 Bot 都可以是主導者。
3. **協作必須是「真的做事」。** 委派會在受託 Agent 自己的 Profile 中啟動完整的執行循環（自己的工具、記憶、工作區），
   結果以報告形式回傳並記錄在任務看板上；不是讓多個模型輪流發言。
4. **對話紀錄即狀態。** 每一則訊息（含工具呼叫與結果）都即時寫入 SQLite，因此 HITL 暫停、程式崩潰或重啟後都能從紀錄續跑。
5. **客觀驗證。** 評測只以可檢查的結果（檔案、測試、git 紀錄、HITL/委派紀錄）判定，不採信 Agent 的自我宣稱；
   驗證後的結果還會回寫到經驗庫，讓記憶從「事實」而非「自評」中學習。

### 1.1 模組總覽

```
┌──────────────────────────── 介面層 ────────────────────────────┐
│  CLI  pland chat / profile / memory / eval / doctor / serve     │  ← 單 Agent 日常使用
│  Web  pland serve → FastAPI + WebSocket + 靜態前端（Bot Mode）   │  ← Bot 名冊、私聊、群組、看板、HITL 卡片
└───────────────┬─────────────────────────────────────────────────┘
                │ Runtime（行程內單例）
┌───────────────▼──────────── 核心層 ─────────────────────────────┐
│ ProfileManager  每個 Agent 一個 Profile 目錄（身份/設定/記憶/工作區）│
│ Agent           執行循環：提示詞 → 模型（串流）→ 工具 → … → 回答 → 背景反思 │
│ Tools           files / code / web / git / memory / plan / hitl / delegation / team │
│ HITL            ask_user 澄清、操作授權（once/session/always/deny）│
│ Memory          有界筆記、經驗庫（BM25＋效用回饋）、技能、會話全文檢索 │
│ Team            delegate_task、message_agent、任務看板、群組 Room │
│ Sandbox         PathPolicy、Local（macOS Seatbelt）/ Docker 執行後端 │
│ Budget/Ledger   每次運行的調用與 token 上限、逐次調用記帳          │
│ EventBus        所有可觀測事件 → UI / CLI / 評測紀錄 / shared.db  │
└───────────────┬─────────────────────────────────────────────────┘
                │
┌───────────────▼──────────── 模型層 ─────────────────────────────┐
│ OpenAICompatClient（httpx 直連）→ DeepSeek（預設）或 HKGAI         │
│ guard.check_endpoint：拒絕 OpenAI / Anthropic 端點，無回退供應商   │
└─────────────────────────────────────────────────────────────────┘
```

| 路徑 | 職責 |
|---|---|
| `pland/config.py` | 設定與路徑（`PLAND_HOME`，預設 `~/.pland`）、供應商定義、`.env` 載入、全域預設 `settings.yaml`（優先序：明確指定 > Profile > 全域預設 > 環境變數 > 內建預設） |
| `pland/llm/` | 模型客戶端、供應商護欄、腳本化模型（測試用） |
| `pland/profiles.py`, `sessions.py`, `store.py` | Profile、會話、SQLite 持久化 |
| `pland/agent.py`, `prompts.py`, `reflection.py` | 執行循環、系統提示詞、任務後反思 |
| `pland/tools/` | 所有可被模型調用的工具 |
| `pland/hitl.py`, `approvals.py` | 人類澄清與授權 |
| `pland/memory.py` | 筆記、經驗、技能（`tools/memory_tools.py` 另含 `session_search`；`tools/plan.py` 為 `todo`） |
| `pland/team/` | 委派、Bot 間訊息、任務看板、群組 Room |
| `pland/sandbox/` | 檔案路徑政策、危險指令分類、Local/Docker 後端 |
| `pland/budget.py`, `llm/pricing.py` | 預算、調用帳本與分模型計價 |
| `pland/server/` | Web API 與前端（Bot Mode） |
| `pland/eval/` | Evaluation Harness 與測試集 |

---

## 2. Agent、Profile 與 Bot

**Profile 是身份與隔離的單位**（沿用 Hermes 的設計）。每個 Profile 是 `PLAND_HOME/profiles/<name>/` 下的一個目錄：

```
profiles/<name>/
├── profile.yaml      # 職稱、描述、是否為 Bot、頭像色、設定覆寫（模型、思考模式、沙箱後端、工具集…）
├── SOUL.md           # 人格與長期指示
├── memories/         # MEMORY.md（Agent 筆記）、USER.md（使用者輪廓）
├── skills/           # Agent 自己寫的可重用流程（*.md）
├── workspace/        # 私有工作區：所有相對路徑、指令都在這裡執行
└── state.db          # 私有資料庫：會話、訊息、經驗、記憶變更紀錄、永久授權規則
```

- **Bot 就是帶有名冊資訊（`bot: true`、職稱、頭像）並擁有一個永久「Bot Chat」會話的 Profile。**
  因此同一個 Bot 在 CLI 用 `pland chat -p <bot> --bot-chat` 打開的就是網頁上那個對話，兩種介面切換不會遺失任何持久狀態。
- `default` Profile 是單 Agent 模式的預設 Agent（不出現在 Bot 名冊）。
- 會話種類：`chat`（一般對話）、`bot_chat`（Bot 的永久對話）、`room_member`（Bot 在某群組中的私人視角）、
  `delegation`（受託執行的任務）、`subagent`（臨時子 Agent）。

### 2.1 執行循環（`pland/agent.py`）

```
使用者任務 ─► 檢索相關經驗（附在使用者訊息後）─► 模型 ─► 工具呼叫？──是──► 執行工具（含 HITL / 授權）─► 結果寫入紀錄 ─┐
                                                   │                                                            │
                                                   └──否──► 最終回答（立即回傳）                                  ◄───┘（迴圈）
                                                              └─► 背景反思：產生經驗紀錄、回饋被取用的經驗
```

- **規劃**：多步驟工作時，Agent 先用 `todo` 工具寫下工作計畫（每項 pending / in_progress / completed / cancelled），
  邊做邊更新；計畫存在會話中，上下文壓縮後會重新附上（參考 Hermes 的 todo 工具）。網頁介面會即時顯示。
  計畫由 Agent 自己勾選，系統不會代為追蹤：實際運行中 researcher 在第 1 步寫下 7 項後 55 步都沒更新（工作其實都做了），
  介面一直顯示 0/7。因此計畫仍有未完成項目、且超過 8 步沒更新時，會插入一次「請更新計畫」的提醒；介面也會在計畫旁標示
  「not updated · N calls」（距上次更新的工具呼叫數），運行結束仍有未完成項目時標示「run ended」。

- 系統提示詞在會話開始時建立一次並存為第一則訊息，之後**逐位元組不變**（記憶、技能、隊友名冊都是當時快照），
  對話只往後追加 —— 這讓 DeepSeek 的前綴快取能命中（實測群組任務快取命中率約 88%）。
- 每輪模型回應（含 DeepSeek 思考模式的 `reasoning_content`）與每個工具結果都即時寫入 `state.db`。
- 工具參數由模型產生、不可信：本地依 JSON Schema 驗證（丟棄多餘欄位、型別轉換、必填檢查）後才執行。
- **防失控護欄**：
  - 每個頂層運行有一個 `Budget`（預設 300 次模型調用、800 萬加權 token，快取命中按 0.1 計；群組的一次推進由多個 Agent 共用，
    預算為兩倍），所有委派出去的子 Agent 共用同一預算；用到 90% 時非根 Agent 停止、拒絕新委派，最後 10% 留給根 Agent 寫總結。
    起初沿用 DeepSeek 指南建議的 120 次／300 萬，但實際的 5 人程式庫審查用了推進預算 240 次中的 216 次、每位受託者都撞到步數上限，
    因此調高；以約 95% 快取命中估算，上限約相當於單次運行 1 美元、群組推進 2 美元（尖峰價），仍是硬性上限。
    任務後的反思（多半在背景進行）會記入 ledger 但不計入運行的上限，避免佔用任務本身的調用次數。根 Agent 用到 70% 時會收到一次
    「已用多少、剩多少」的提示，每個委派與私訊的結果也附上目前用量（`run_budget`）：實際運行中主導者在剩約 30 次時又開了一輪審查，
    受託者因 90% 規則停下、沒有結論。
  - 同一工具＋相同參數重複出現 3 次即警告、5 次即停止；工具結果連續與先前結果相同（無進展）時先提醒並暫時提高
    temperature 打破貪婪解碼的重複，連續 6 次則強制收尾並產出報告。成功的寫檔／編輯會改變工作區，其確認訊息
    （「Edited x (1 replacement)」）對同一檔案的每次編輯都相同，因此以「工具＋參數＋結果」判斷，不再被當成無進展
    （實際運行中 researcher 連續 6 次修正同一份筆記就被誤判為迴圈）。觸發停止的那次呼叫的結果仍會寫入紀錄（呼叫確實執行了），
    同一批中尚未執行的呼叫也會補上「未執行」的結果，紀錄保持完整。
  - **讀檔分頁**：所有工具結果上限 24,000 字元（超過時保留頭尾、刪去中段並說明）。`read_file` 每次最多回傳約 20,000 字元的完整行，
    其餘部分在結尾註明「從 offset=N 繼續」，不會再出現標頭寫著全檔行數、中段卻被刪去的情況。`search_files` 可直接搜尋單一檔案，
    路徑不存在時回報錯誤而不是「no matches」（過去對檔案路徑一律回傳 no matches，writer 據此做的自我檢查等於沒做）。
  - 每輪上限 80 步（評測中的 636 個 Agent 會話：中位數 6、p99 44、最多 61 步；實際程式庫審查每位受託者都超過 40 步）；
    群組中被 @ 的成員每輪最多 40 步、討論輪 6 步。用到 80% 時插入一次「步數檢查點」（參考 Hermes kanban worker 的檢查點）；
    工作規則也要求交付檔案及早建立、逐步補充。實測顯示只靠提醒不夠（受託者在 80 步中一直讀檔或做實驗），因此改為**強制**：
    委派時從 `expected_output` 取出要求的輸出檔路徑存在會話中；到檢查點時若這些檔案還不存在（沒有指定檔案時則看是否寫過任何檔案），
    接下來兩步只提供 `write_file`／`edit_file`，模型只能寫出交付物或直接給最終回答；到達步數上限時若仍缺檔，再給一步只能寫檔的
    「搶救」機會，把已做的工作存檔後才收尾（取代過去由主導者重新委派「只寫檔」）。隊友名冊也標示每位成員缺少的能力
    （例如 `[cannot run code; no web access]`），並提醒主導者把大型審查依範圍拆分、每份工作約在 80 步內可完成。
    到達上限時要求模型總結已完成與未完成的部分：此時仍提供工具定義但 `tool_choice="none"`（完全不給工具時，模型曾把下一個
    工具呼叫以 DeepSeek 的內部標記文字寫進報告）；報告中若仍出現這類標記會被移除，絕不會當成委派結果交給主導者。
  - **輸出上限**：每次回應最多 32,768 個輸出 token（DeepSeek 接受到 393,216；思考內容也計入）。回應在工具呼叫中途被截斷
    （`finish_reason=length`）時，該呼叫不會執行，改回覆「已被截斷，請分段寫入」；`write_file` 支援 `append=true` 分段寫入。
    純文字回答被截斷時，請模型從中斷處接續並把兩段合併。模型把工具呼叫寫成文字標記時，提醒它改用真正的工具呼叫（最多兩次）。
  - **兩階段上下文壓縮**（參考 Hermes ContextCompressor）：模型看到的對話超過預算（預設約 40 萬字元）時，
    第一階段不呼叫模型，只把保護尾段以外的舊工具輸出替換為「已清除，需要時重新執行」；仍超過預算才進入第二階段，
    把中段對話摺疊成結構化摘要（目標、限制與偏好、進度［完成／進行中／受阻］、關鍵決策、相關檔案、下一步、關鍵細節），
    並以「更新上一份摘要」的方式疊代。尾段從使用者訊息開始，工具呼叫與結果不會被拆開；儲存的原始紀錄不會被改寫。
- **串流**：模型回應以 SSE 串流接收（內容、`reasoning_content` 與工具呼叫片段在本地組裝），文字片段以 `assistant.delta`
  事件即時推送到網頁（批次化、不寫入事件紀錄）；只在尚未輸出任何內容前才會重試。
- **背景反思**（參考 Hermes background review）：最終回答先回傳，學習在背景進行。反思沿用該會話原本的系統提示詞、
  工具與歷史，只追加一則反思請求，因此能重用 DeepSeek 的前綴快取（實測反思調用的快取命中率由 2% 提高到 93%）；
  回覆不是有效 JSON 時才退回獨立的摘要提示詞。
- 每次模型調用都寫入 `shared.db` 的 `llm_calls` 帳本（運行 ID、Agent、用途、輸入/快取/輸出 token、耗時），不含訊息內容。

---

## 3. Agent 通訊與路由

PlanD 有四種、而且只有這四種跨 Agent 的資訊通道。除此之外，Agent 之間**不共享**任何記憶或檔案。

| 通道 | 機制 | 何時使用 |
|---|---|---|
| **委派** `delegate_task` | 在目標 Bot 的 Profile 中新建 `delegation` 會話並跑完整執行循環，回傳結構化報告 | 實質工作（寫程式、研究、撰寫文件） |
| **私訊** `message_agent` | 把訊息投遞到目標 Bot 的永久 Bot Chat，跑一輪後回傳回覆（同步） | 詢問、審閱、快速確認 |
| **群組 Room** | 人類與多個 Bot 共享的對話紀錄；每個 Bot 只看到自己上一輪之後的新訊息 | 討論、協商、由主導者推進 |
| **顯式檔案交換** | `share_file`（複製到對方工作區 `inbox/from-<我>/` 或群組的 `shared/`）、委派時附帶 `files` | 交付成果 |

### 3.1 路由規則

- **使用者 → Agent**：CLI 與網頁都是直接指定 Profile（預設 `default`）。群組中由 @提及決定收件者，
  `@all` / `@everyone` 或沒有提及時則是全體成員。
- **主導者（lead）選擇**：群組設定了 lead 且其在收件者中 → 由其主導；否則第一個被 @ 的 Bot；否則第一位成員。
  這是「依情境選出」而非固定角色。
- **Bot → Bot**：模型在系統提示詞中看得到隊友名冊（名稱、職稱、描述），自行決定 `delegate_task(to=…)`、
  `message_agent(target=…)` 或在群組中 `@name`。目標會依 Profile 名稱驗證，不存在時回傳可用名單。
- **循環防護**：每個運行帶有委派鏈（例如 `planner → coder`）。若目標已在鏈中（A→B→A），委派與私訊都會被拒絕，
  避免互相等待造成死鎖；委派深度上限預設為 2。

### 3.2 群組 Room 的發言輪次（`pland/team/rooms.py`）

沿用 Hermes 群組聊天「依序發言、可選擇不發言、有輪次上限」的做法，並調整成能導向真正的分工：

1. 人類發訊息後，**第 1 輪**：非主導的收件成員先發言，但這是**討論輪**——只能讀取/查詢，不能寫檔或執行
   （在呼叫時拒絕，工具清單不變以維持快取），內容限於「我適合哪部分、有什麼風險、我知道什麼」，沒有要補充就回 `[PASS]`。
   各成員的討論輪彼此獨立，因此**並行執行**，再依名冊順序貼出。
   接著主導者帶著隊友的意見行動：在看板上拆解任務、用 `delegate_task` 分派、整合並驗證成果。
2. **之後的輪次**：只有被 Bot 在訊息中 @ 到的成員獲得發言機會（他們此時有完整工具，可以修正或補做，但步數上限為 20；
   討論輪為 6 步——實測中曾有成員因為一句客套的 @ 而花 30 分鐘重新驗證已完成的工作）。
   提示詞要求只在真的需要對方行動時才 @，避免客套式提及造成多餘輪次。
3. 某輪無人發言、達到 3 輪或 12 則訊息、預算接近上限、或有 Bot 寫了 `@user`（需要人類）時，本次推進結束；
   `@user` 會在群組上亮起「needs you」標記。
4. 每個成員在每個群組有一個持久的 `room_member` 會話（它在該群組的私人視角），跨多次推進保留脈絡。

實測（3 個 Bot：planner / coder / writer，DeepSeek `deepseek-flash`）：planner 在看板建立 3 個任務，
**並行**委派 coder（實作＋測試）與 writer（README），整合時發現 README 範例數值錯誤並 @coder 修正，
最終 16 個測試通過；全程 78 次模型調用、194 秒、快取命中 89%、約 $0.05。

---

## 4. 任務分解與委派

### 4.1 分解：任務看板（`pland/team/board.py`）

看板是「目標如何被拆解、誰負責什麼」的顯式紀錄，存在 `shared.db`：

- 範圍（scope）：群組內是該群組 ID；群組外是委派者自己（`dm:<name>`）。
- 欄位：標題、描述、負責人、狀態（`todo / in_progress / done / failed / blocked`）、相依任務、結果。
- Agent 透過 `team_tasks` 工具新增/更新/列出；網頁右側面板即時顯示。

### 4.2 委派：`delegate_task`（`pland/team/delegation.py`）

```
delegate_task(tasks=[
  {to: "coder",  goal: "...", context: "...", files: ["spec.md"], task_id: "t_…"},
  {to: "writer", goal: "...", context: "..."},
  {goal: "..."}                        # 沒有 to：委派給自己的臨時子 Agent
])
```

- **委派給隊友**：在隊友的 Profile 內建立 `delegation` 會話，用隊友自己的人格、記憶、經驗、工具與私有工作區執行。
  受託者看不到委派者的對話，只會收到 goal / context / 附件 / 預期輸出，以及（在群組中）`shared/` 資料夾。
  受託者完成後回傳報告：做了什麼、證據（測試輸出、檔案路徑）、未解決的問題。
  **交付檔自動送回**：委派結束時，`expected_output` 指定的檔案與受託者這次寫過的檔案（最多 12 個、各 20 MB 內，群組 `shared/`
  與 `inbox/` 內的複本除外）會複製到委派者目前的資料夾 `inbox/from-<隊友>/`（保留相對路徑），結果中以 `files_in_your_folder`
  列出；受託者的任務說明也註明不必自己分享。過去主導者得再私訊每位隊友請它 `share_file`（一次就多花 16 次調用，且訊息進到
  使用者與該 Bot 的私人 Bot Chat）。
- **臨時子 Agent**（Hermes 的 subagent 模式）：同一 Profile、全新脈絡、共用工作區；不能詢問使用者、不能寫長期記憶、
  不參與團隊訊息，完成後只把摘要回傳給父 Agent。
- **並行**：同一次呼叫中的多個任務以執行緒池並行（預設最多 4 個），彼此獨立；有相依關係的任務由主導者依序委派。
- **與看板同步**：委派自動建立或連結看板任務，狀態隨執行更新為 `in_progress → done / failed`，結果欄存報告。
  因步數、迴圈護欄或預算提前停止、但要求的交付檔都已寫出時，記為 `done` 並在結果前註明「提前停止，請確認檔案完整」；
  已完成的任務再委派一次（例如再審一輪）若中途停止或被拒絕，維持 `done` 並保留原結果，不會被改成 `failed`。
- **前置任務交接**（參考 Hermes kanban 的 parent link）：連結到看板任務的委派，若其相依任務尚未完成就會被拒絕
  （同一批次中其他任務照常執行）；相依任務完成後，它們的結果會自動附在受託者的任務說明中，讓後續工作知道「為什麼」與「做了什麼」。
- **人類授權不會被繞過**：受託者觸發的澄清與授權請求，會以受託者的身份送到同一個人類通道。
- **可觀測**：每次委派都有 `delegation.started / finished` 事件、`deliveries` 紀錄，群組中也會顯示活動訊息。

### 4.3 協商

協商發生在群組的討論輪：成員表達能力與風險，主導者據此決定分工；之後成員可以在被 @ 時提出異議或補充。
主導者也可以用 `message_agent` 私下詢問某個隊友的意見再決定。這些都是模型的自主決策，系統只提供通道與規則。

---

## 5. 記憶與經驗演化（`pland/memory.py`, `pland/reflection.py`）

**每個 Agent 有自己的記憶，存在自己的 Profile 中**；身處同一群組不代表共享記憶。三個層次：

| 層次 | 儲存 | 寫入方式 | 使用方式 |
|---|---|---|---|
| 有界筆記 | `memories/MEMORY.md`（2,200 字元）、`USER.md`（1,375 字元），條目以 `§` 分隔 | Agent 用 `memory` 工具新增/替換/刪除；反思可補充少量持久事實 | 會話開始時以快照放入系統提示詞 |
| 經驗庫 | `state.db` 的 `experiences` 表 | 每個任務結束後的**反思**步驟自動產生 | 新任務開始前依相關度檢索前 3 筆，附在任務後面；也可用 `recall_experience` 主動查 |
| 技能 | `skills/<name>.md` | Agent 用 `skill_save` 寫下可重用流程 | 名稱與說明列在系統提示詞，需要時 `skill_view` 讀取 |

### 5.1 經驗的產生、使用與演化

1. **產生**：任務結束後，以同一個（DeepSeek）模型對精簡過的紀錄做反思，輸出 JSON：結果（success/partial/failure，
   要求依證據而非自我宣稱判斷）、摘要、最多 4 條可重用教訓、成功的步驟流程、檢索標籤。
2. **檢索**：BM25（英文詞＋中日韓二元組）計算相關度，再乘上該經驗的**效用權重**
   `0.5 + (helpful+1)/(helpful+unhelpful+2)`；失敗經驗同樣可被檢索（它帶有「不要這樣做」的資訊）。
3. **回饋**：被取用的經驗會依該次任務的結果增加 `helpful` 或 `unhelpful` 計數 → 持續帶來成功的經驗排名上升，
   常與失敗同時出現的經驗排名下降。這就是不需微調模型的「演化」迴圈。
4. **信念修正**：反思也會對照本次的證據檢查既有筆記，若有一則被明確推翻，可提出刪除或改寫（每次最多一則，
   經由一般的、有紀錄的記憶操作執行）——針對實測中 Agent 記下錯誤信念的情況。
5. **以事實校正**：在評測中，任務驗證後的**客觀結果**會覆寫經驗的結果欄位（並在摘要加註），
   且把先前依「自評」給出的 helpful/unhelpful 回饋改成依驗證結果計算 —— 避免 Agent 從自己錯誤的自信中學習。
6. **可追溯**：所有記憶寫入、檢索、回饋都記錄在 `memory_events` 表，評測報告逐任務列出記憶條目數、經驗數（依結果分類）、
   本任務新增與取用的經驗，並比較「有取用經驗 / 沒取用經驗」的任務完成率；`--memory off` 可做消融比較，
   `--passes N` 可觀察同一測試集多輪執行時的學習曲線。

### 5.2 會話全文檢索與技能

- **`session_search`**（參考 Hermes）：每個 Profile 的訊息都寫入 SQLite FTS5 全文索引（trigram 分詞，中文也能檢索），
  Agent 可以查「以前是不是做過／使用者當時怎麼說」：最佳結果附上前後文，其他結果精簡列出，再以訊息 ID 往前後捲動。
  只搜尋自己的 Profile；不需要模型調用。筆記只放關鍵事實，細節留在會話紀錄中按需檢索。
- **技能**：採 Hermes SKILL.md 的結構（When to Use／Procedure／Pitfalls／Verification），記錄每個技能的檢視與儲存次數，
  作為日後清理過時技能（Hermes curator 的做法）的依據；系統提示詞只列名稱與說明，需要時才讀取全文（漸進式揭露）。

### 5.3 已知限制

- Agent 自己寫入的筆記可能包含**錯誤的信念**。實測中 planner 把一次 shell 管線失敗誤記為「shell 輸出會被截斷」，
  這個誤解正是它反覆驗證、陷入重複迴圈的原因。目前的緩解：反思要求依證據判斷、評測以客觀結果校正經驗，
  以及無進展偵測；筆記內容本身尚無自動查證，使用者可在網頁的記憶面板檢視。
- 經驗檢索是詞彙層級（BM25＋覆蓋率門檻），沒有語意向量；換句話說的相同任務可能檢索不到
  （DeepSeek 沒有 embedding API，本專案也不使用其他供應商的模型）。

---

## 6. 執行環境、沙箱與隔離

需求明確要求區分**邏輯隔離**與**作業系統／容器層級的執行隔離**。PlanD 兩者都有，但保證程度不同，以下如實列出。

### 6.1 邏輯隔離（Profile / 會話 / 記憶）—— 預設即生效

| 對象 | 隔離方式 |
|---|---|
| 設定、人格、記憶、技能、經驗、會話 | 各自 Profile 目錄與各自的 `state.db`；程式碼中沒有任何「讀取其他 Profile 記憶」的工具 |
| 檔案工具 | `PathPolicy` 把路徑限制在本 Agent 的工作區（群組情境下再加上該群組的 `shared/`）；先解析符號連結再檢查，`../` 與指向外部的連結都會被拒絕；`.env`、`.ssh`、`state.db` 等憑證/狀態檔一律拒絕 |
| 協作資料 | 只有群組紀錄、看板、投遞紀錄、HITL 請求放在 `shared.db`，這些本來就是要共享的 |
| 環境變數 | 執行指令前清除名稱含 KEY/TOKEN/SECRET/PASSWORD 等的變數，`DEEPSEEK_API_KEY` 不會進入 Agent 執行的程式 |

### 6.1.1 對話的工作資料夾（`pland/workspace.py`）

預設每個 Agent 在自己的私有工作區工作；**每個對話也可以指定一個資料夾**（群組則可指定共享資料夾），
參考 Hermes 的 `agent/runtime_cwd.py`：同一個來源決定系統提示詞、檔案工具的 `PathPolicy` 根目錄、沙箱的可寫目錄、
上傳位置與網頁的檔案瀏覽器。資料夾存在會話的 meta（群組存在房間設定），是**系統狀態**而非模型記得的內容，
上下文壓縮、重新啟動或恢復對話後都不會遺失。

- **設定方式**：CLI 在專案資料夾內啟動 `pland` 即以該資料夾為新對話的工作資料夾（同 Hermes CLI 以啟動目錄工作）；
  `pland -w <資料夾>`／`-w default` 指定或改回私有工作區；對話中 `/workspace`。網頁：標題列的資料夾按鈕開啟資料夾選擇器
  （只列出資料夾名稱，不列檔案），群組標題列同樣可設定共享資料夾。恢復的對話與 Bot Chat 保留自己的資料夾。
- **拒絕的資料夾**：`/`、家目錄本身與其上層、`/Users`、`/tmp` 等過大的頂層資料夾、系統資料夾（`/System`、`/usr`、`/etc`…）、
  憑證資料夾（`~/.ssh`、`~/.aws`、`~/.config`、`~/Library`…），以及 PlanD 的資料夾 `PLAND_HOME`（其他 Bot 的私有狀態）。
  PlanD 自己的安裝目錄不會被當作啟動目錄的預設值（同 Hermes）。
- **執行隔離**：選定的資料夾取代私有工作區成為唯一可寫的根目錄；Seatbelt 的拒絕清單（`/Users`、家目錄、`PLAND_HOME`）不變，
  因此 Agent 只能存取這個資料夾，同層的其他資料夾與 `PLAND_HOME` 仍被擋下。沙箱的私有 HOME 仍放在 Bot 自己的工作區，
  不會在使用者的專案中留下 `.home`。Docker 後端為每個（Bot、資料夾）啟動各自的容器。
- **提示詞**：系統提示詞說明這是使用者的資料夾（先讀再改、刪除或覆寫非自己建立的檔案前先詢問），並告知 Agent 資料夾只能由
  使用者設定。對話途中更換資料夾時，下一輪會在對話中加入一則「[system] 工作資料夾已改為 …」，系統提示詞不改寫（保住前綴快取）。
- **資料夾消失**：若選定的資料夾已被刪除，執行直接以錯誤結束並說明，不會改到別處寫檔。
- **子 Agent** 沿用發起對話的資料夾；受託的隊友仍在自己的工作區工作，檔案以委派附件或群組共享資料夾交換。
- **Bot Chat：每個資料夾一個對話**。Bot 只有一個永久的 Bot Chat、沒有對話清單，若直接改資料夾，兩個專案的脈絡會混在同一段對話裡。
  因此 Bot 的 Bot Chat 依資料夾分開：在 Bot Chat 選擇資料夾即**切換**到該資料夾的 Bot Chat（第一次使用時建立，之後接續），
  各自有獨立的對話脈絡與壓縮摘要；Bot 的身份、記憶筆記、經驗、技能是 Bot 層級的，所有資料夾共用，必要時也能用
  `session_search` 查其他資料夾的對話。私有工作區的 Bot Chat 是「主 Bot Chat」，其他 Bot 以 `message_agent` 傳來的訊息送到這裡。
  打開 Bot 時顯示最近使用的那一個；選擇器上方列出這個 Bot 的所有資料夾對話可直接切換。若想把目前的脈絡帶過去，選「Move this
  conversation here」（保留脈絡並加入資料夾變更說明；目標資料夾已有自己的 Bot Chat 時會拒絕）。CLI：在專案資料夾執行
  `pland -p coder --bot-chat` 即開啟 coder 在該資料夾的 Bot Chat；`/workspace <資料夾>` 切換、`/workspace move <資料夾>` 搬移。
- **一般對話（Chats）**：可隨時開新對話，所以選資料夾是「這個對話改到該資料夾」（保留脈絡＋變更說明），也可選「在該資料夾開新對話」。
- **群組**：群組就是一段對話，改共享資料夾時成員保留各自的脈絡；系統在群組中張貼一則「共享資料夾已改為 …」的訊息，
  每位成員在下一輪會讀到（成員每輪都會收到上次之後的所有群組訊息），各自工作區的 `shared/` 連結也在下一輪自動指向新資料夾。
  實測：成員在 A 資料夾建立 `a.txt`，改到 B 後回報「現在在 B 工作，只有 notes-b.txt，a.txt 在先前的資料夾」。
  若希望每個專案有獨立的團隊脈絡，選擇器也能「以相同成員為該資料夾建立新群組」。

### 6.2 執行隔離

**Local 後端（預設）**：指令在 Agent 工作區中以子行程執行，有逾時（單一指令最多 600 秒，整個行程群組會被終止）、
CPU 時間與檔案大小上限，並清除機密環境變數。**行程屬於啟動它的運行**（同 Hermes）：指令返回時，它在背景留下的行程
（`cmd &`、nohup）會連同行程群組一併終止；運行被停止時，正在執行的指令每秒檢查一次停止旗標並立即被終止
（實測中曾有 Agent 在背景啟動暴力搜尋並以 `sleep` 等待，評測結束後仍殘留，因而加入）。**這不是作業系統沙箱**：被執行的程式仍擁有目前使用者的檔案讀寫權限，
因此搭配以下的授權層：

- **硬性封鎖**（任何模式、任何授權都不執行）：`rm -rf /`、刪除家目錄、fork bomb、`mkfs`、寫入原始磁碟、關機/重開機等。
- **需人類授權**：遞迴刪除、`sudo`、`curl … | sh`、`git push`、`git reset --hard`、改動 `/etc`、存取憑證目錄、
  SQL `DROP/TRUNCATE`、結束行程等；Python 程式碼也會掃描 `shutil.rmtree`、`subprocess`、`os.system` 等。
  （模式參考 Hermes `tools/approval_detection.py`，已註明出處。）
- **一律需授權的工具**：`delete_file`、`git_push`。

**Docker 後端（`sandbox.backend: docker`）**：每個 Profile 一個長駐容器（專用映像檔 `pland-sandbox:py3.11`，
由 `docker/sandbox.Dockerfile` 首次使用時自動建置：Python 3.11、git、pytest、curl；建置失敗時退回 `python:3.11-slim`），
`--cap-drop ALL`、`--security-opt no-new-privileges`、`--pids-limit 256`、記憶體與 CPU 上限、`/tmp` 為大小受限的 tmpfs，
可選 `--network none`；**只**掛載該 Agent 的工作區（群組情境再巢狀掛載 `shared/`）。實測容器內看不到主機的 `/Users`，
在 `--network none` 下無法連網。容器擋得住系統層級的破壞（sudo、chmod、結束行程、改系統設定），這些在容器內不再詢問；
但與 Hermes 不同，PlanD 把 Agent 真實的工作區掛載進容器，所以**破壞資料的操作**（遞迴刪除、`find -delete`、`git reset --hard`、
SQL DROP/DELETE/TRUNCATE）與對外動作（push、憑證、秘密、發布）在容器內仍然必須經人類授權——這是在 Docker 後端跑 midterm
時發現「拒絕刪除」的任務被直接刪除後修正的。
`git_*` 工具一律在主機端執行（才能使用使用者設定的 GitHub 憑證），並受路徑政策與 push 授權約束；
沙箱化的 shell（Seatbelt 或容器）沒有憑證，在其中執行 `git push` 會被拒絕並指示改用 `git_push`，
規則也明確禁止以腳本或其他 git 實作繞過（實測中 Agent 曾以 `dulwich` 繞過，已修正）。
群組的共享資料夾在容器內掛載於 `/shared`，工作區中的 `shared` 為指向它的符號連結。

### 6.3 目前的邊界與待補強之處（如實記錄）

1. Local 後端下，`run_shell` / `run_python` 執行的程式**可以讀取使用者帳號能讀的任何檔案**，包括其他 Agent 的工作區；
   檔案工具的限制只對檔案工具有效。需要強隔離時應使用 Docker 後端。
2. Local 後端下網路沒有限制；Docker 後端預設 `bridge` 網路，可改 `none`。
3. 容器內以 root 執行（能力已全部移除）；尚未做 user namespace 對應或 seccomp 自訂設定。
4. 危險指令偵測是規則式的，可能被刻意混淆的指令繞過；它是「防誤操作」而非「防惡意」。另外參考 Hermes 的內容層檢查：
   以 curl/wget 上傳秘密變數或憑證檔、指令中含不可見／雙向 Unicode 控制字元，也需要授權。網頁搜尋與抓取的結果會掃描
   常見的提示詞注入樣式（要求忽略先前指示、重新定義角色、HTML 註解中的指示、竊取秘密、curl|sh、不可見字元），
   命中時在結果前加上警告並發出安全事件，但不阻擋內容。
5. 同一個 Bot 同時在兩個群組工作時，Local 後端的 `shared` 連結會隨最近的群組切換（Docker 後端無此問題）。
6. 評測時若使用 Local 後端，Agent 的程式在技術上讀得到版本庫中的測試集 YAML（含檢查用的預期值）；
   Agent 不會被告知其位置，正式評測若需排除此可能，應使用 Docker 後端。
7. Local 後端（含 Seatbelt）執行指令時保留 `SSH_AUTH_SOCK`，而 Seatbelt 設定不限制 socket 與網路：若使用者的 ssh-agent 載有金鑰，
   沙箱內的指令可以用它連線或以 SSH 遠端推送（2026-10-24 稽核以真實 Seatbelt 確認 socket 可達；待修正——修正時只能在沙箱指令的
   環境中移除，主機端的 `git_push` 仍需要它）。
8. 評測的 `command` 與 `python` 檢查在主機上執行、不經沙箱（`python` 檢查把任務工作區加入 `sys.path`，會匯入 Agent 寫的模組）。
   對信任的題庫與腳本化使用者沒有問題，但這是一條邊界：對不受信任的模型或輸入執行封閉測試集時應留意。
9. 後續可補強：每個 Profile 一個作業系統使用者、容器使用非 root 使用者與唯讀根檔案系統、網路白名單、
   以容器執行 git 並注入受限的部署金鑰。

---

## 7. Human-in-the-Loop（`pland/hitl.py`, `pland/approvals.py`）

| 情境 | 機制 |
|---|---|
| 指令歧義、缺少關鍵資訊 | 模型呼叫 `ask_user(question, options)`；系統提示詞要求在不可逆或昂貴的工作前先確認 |
| 需要許可的操作 | 工具在執行前呼叫授權閘門；人類可選 **once / session / always / deny**；`always` 寫入 Profile 的永久規則 |
| 無人可回應（背景/無人值守） | 澄清回覆「目前無人，請自行做合理假設並說明」；授權預設拒絕 |
| 選用：smart 授權模式 | 參考 Hermes：被標記的 shell/Python 指令先交給一次「守門」模型調用（同一個 DeepSeek 模型、temperature 0、限 8 tokens），低風險直接核准、明顯危險直接拒絕、不確定才問人；指令中的註解先移除並以 `<command>` 包住當作不可信輸入。**刪除檔案、git push、憑證、發布、sudo 一律問人**；預設仍為 manual |

**續跑而不重來**：請求發生在工具呼叫「內部」，執行緒在該點等待；答覆抵達後工具回傳答案，**同一個運行**繼續往下，
不會重新開始任務。請求同時寫入 `shared.db`：若行程在等待中死掉，會話中留下「有呼叫、無結果」的工具呼叫，
`Agent.resume()` 會先補完這些呼叫（必要時重新詢問），再接著原來的紀錄繼續。

介面：CLI 直接在終端機詢問；網頁以卡片呈現（澄清有選項按鈕與自由輸入，授權有四個按鈕），並在名冊上標示待處理；
評測時由「模擬使用者」依任務定義的規則回答，所有互動都記錄在報告中。

---

## 8. 模型接入（`pland/llm/`）

- 僅支援 **DeepSeek**（預設，`deepseek-flash`；可改 `deepseek-v4-pro`）與 **HKGAI**（OpenAI 相容端點，URL/模型由使用者設定）。
- 客戶端直接以 httpx 實作 chat-completions，不依賴任何第三方 SDK，避免隱含的預設供應商或回退路徑。
- `check_endpoint` 在任何網路請求前執行：供應商必須是 `deepseek` / `hkgai`，主機若屬於 openai.com、anthropic.com 等即拒絕，
  DeepSeek 的 base URL 必須是 deepseek.com 網域。**主對話、反思、上下文壓縮、評測等所有調用都經由同一個客戶端與護欄**，
  系統中沒有其他模型呼叫路徑。
- DeepSeek 細節：思考模式**預設開啟**（hard 測試集上目標完成率由不開啟的平均 65.6%（4 次）提高到 87.5%（3 次），
  每次平均花費反而略低，主要因為較少陷入重複迴圈；代價是簡單任務的回應時間約增加 1.3–2 倍）。
  討論輪、授權守門、上下文壓縮等短呼叫逐次關閉思考；開啟且帶工具時，`reasoning_content` 會原樣回放；
  關閉思考時 temperature 預設 0；只重試 429/5xx/逾時（1、2、4 秒，最多 3 次）以及中途斷線的串流。
- 網路搜尋與抓取優先使用 DeepSeek 的 Search / Fetch API（同一把金鑰），其次 Tavily / SearXNG / DuckDuckGo / Bing；
  後端被封鎖或限流時回報「失敗」，不會偽裝成「沒有結果」。HKGAI 沒有搜尋與抓取 API，因此不論模型由哪個供應商執行，
  只要設定了 `DEEPSEEK_API_KEY` 就使用 DeepSeek 的 Search / Fetch；送出前同樣經過端點護欄，DeepSeek 金鑰只會送到 DeepSeek 的主機。
  設定頁切換到 HKGAI 時會說明網路工具改走哪裡；`pland doctor` 也會顯示。
- **思考強度**（`pland/llm/reasoning.py`，參考 Hermes 的 `agent/reasoning_effort.py` 與 DeepSeek provider profile）：
  使用者可選 `off`、`default`（不送 effort，由 DeepSeek 決定，評測即用此設定）、`low`、`medium`、`high`、`max`。
  內部採用 Hermes 的完整階梯（minimal…ultra），送出前**夾到供應商支援的層級**：支援就原樣送出，否則先查宣告的對應
  （`xhigh`/`ultra` → `max`），再取最接近的**較弱**層級，確保夾值不會提高成本；無法辨識的字一律拒絕。
  DeepSeek 每次請求都明確帶 `thinking` 開關，`reasoning_effort` 只在開啟思考時送出。2026-10-21 實測（deepseek-flash）：
  API 接受 none/minimal/low/medium/high/xhigh/ultra/max，其他值回 422；**`none` 並不會關閉思考**（只有 `thinking: disabled` 會），
  因此 `off` 一律以開關實作；同一題計數問題 low/medium/high 約思考 1.5–1.75k tokens、max 約 3k、不送約介於兩者之間。
  設定有三層，後者優先：Profile 預設（`pland setup`、`pland profile set --reasoning`、網頁 Bot 設定）→ 單一對話
  （CLI `/reasoning`、網頁輸入框右側的選單，存在會話 meta、下一輪生效，與 Hermes 的 session-scoped `/reasoning` 相同）→
  逐次呼叫（討論輪、守門、壓縮固定關閉）。臨時子 Agent 繼承發起對話的設定；受託的隊友使用自己 Profile 的設定。
  對話也能以 `/model` 或網頁的模型選單暫時改用另一個 DeepSeek 模型（同樣存在會話 meta）。評測可用 `--reasoning` 比較不同強度。
- **HKGAI 的思考強度**：2026-10-25 實測（t2_hkgai-v3_fp8_1m_e7）：HKGAI 沒有 `thinking` 開關（送了也被忽略），只靠
  `reasoning_effort`：接受 none/minimal/low/medium/high/xhigh/max，其他值回 400；**不送或送 `none` 都不思考**，送任何等級就思考。
  因此 HKGAI 提供 off / default / minimal / low / medium / high / xhigh / max：`off` 明確送 `none`，`default` 送 `medium`
  （否則預設開啟思考在 HKGAI 上等於沒開）。推理文字回在 `reasoning` 欄位（DeepSeek 是 `reasoning_content`），一般回應與串流都會讀取，
  帶工具時同樣回放。實測各等級都會思考，但思考長短與等級並不總是成正比（單次樣本，minimal 有時比 medium 長）。
  開啟思考時 HKGAI 的 JSON 模式曾回傳不合法的 JSON（3 次中 2 次），所以 JSON 模式的呼叫在 HKGAI 上一律關閉思考。
- `pland doctor --probe` 以數次小調用驗證：對話、原生工具、工具＋思考（含回放）、思考強度（max 有推理、off 沒有）、JSON 模式、Search、Fetch。

---

## 9. 使用者介面

參考 Hermes 的取捨：**Bot Mode 由圖形介面承載，CLI 只涵蓋 Profile 與會話層級的能力**。
Hermes 的 Bot Mode 是 Desktop 插件（名冊、群組、Routines 都是 UI 功能），CLI 可用 `-p <bot>` 操作同一個 Profile，
但沒有完整的 CLI Bot Mode。PlanD 同樣如此：

| 介面 | 內容 |
|---|---|
| CLI（`pland`／`pland chat`） | 單 Agent 對話（新對話預設在啟動的資料夾工作，`-w` 指定）、即時顯示工具/委派/經驗事件、終端機內處理 HITL、`/new` `/sessions` `/resume` `/memory` `/reasoning` `/model` `/workspace`；`-p <bot>` 與 Bot 對話；`pland profile …` 管理 Profile；`pland setup` 設定金鑰、模型、思考強度、沙箱與授權；`pland team apply` 加入範例團隊 |
| Web（`pland desktop`／`pland serve`） | 見下方 |

**啟動**（參考 Hermes 的 `hermes` 啟動器與 `hermes desktop`）：`scripts/install.sh` 建立 `.venv`、以 editable 模式安裝，
並在 `~/.local/bin/pland` 寫入一個 shell 啟動器，之後在任何資料夾都能用一行指令啟動。啟動器以 `python -I`（隔離模式）執行，
目前資料夾不會被加入 import 路徑，放在那裡的同名模組無法冒充 PlanD；`load_dotenv` 也只讀安裝目錄與 `PLAND_HOME` 的 `.env`，
不讀目前資料夾的 `.env`。`pland` 不帶參數即進入對話；`pland desktop` 若連接埠上已有 PlanD 伺服器就沿用，否則在背景啟動
（紀錄在 `PLAND_HOME/logs/server.log`），再以 Chromium 系瀏覽器的 `--app` 視窗（沒有分頁與網址列）開啟，找不到時退回預設瀏覽器；
`pland desktop --stop` 停止背景伺服器。PlanD 沒有 Electron 包裝，「桌面版」就是這個 App 視窗。

**Web 介面（`pland/server/`，FastAPI ＋ 原生 JavaScript，無建置步驟）**

- **側欄**：Chats（`default` Profile 的會話，單 Agent 模式）｜ Bots（Bot 名冊：頭像、職稱、最新訊息、執行中動畫、待處理 HITL 標記；
  群組列：成員頭像堆疊、人數、最新訊息、「needs you」標記）；「+ New bot」「+ New group」「Templates」（一鍵加入範例團隊，
  見 `pland/team_templates/`；角色只是資料，系統不依賴任何固定角色）。
- **對話區**：Markdown 呈現；工具呼叫卡片（名稱、參數、結果、成功/失敗、耗時，可展開）；即時狀態列
  （「@coder is thinking…」「@lead is waiting on teammates」「waiting for you」，包含為此對話工作的受託者）；
  輸入框為單行（參考 Hermes Desktop）：左側 **+** 上傳檔案（也可拖放、貼上），右側為模型與思考強度選單（只影響目前對話，
  可選「Use the bot's setting」還原）與送出鍵；Enter 送出、Shift+Enter 換行、支援中日文輸入法；執行中顯示 Stop。
- **上傳**：檔案以原始內容 POST 到 `/api/profiles/{name}/uploads` 或 `/api/rooms/{id}/uploads`，存到工作區或群組共享資料夾的
  `uploads/`；檔名只保留最後一段並清除不安全字元，同名不覆蓋（`name-2.ext`），單檔上限 20 MB，PDF / Office 文件拒收
  （文件類任務限 .md / .txt），路徑同樣經過 `PathPolicy`（拒絕 `.env` 等憑證檔名）。送出訊息時附上的路徑會被驗證，
  並以「[Attached files, saved in your workspace: `uploads/…`]」附在訊息後，Agent 用一般的檔案工具讀取。
- **群組**：發言者頭像與名稱、主導者星號、委派開始/完成/失敗的活動列（可展開報告）、@提及自動完成。
- **HITL**：澄清卡片（選項按鈕＋自由輸入）、授權卡片（摘要、細節、範圍、Allow once / Session / Always / Deny）；
  全域「N waiting」徽章與托盤，可在任何頁面處理所有待決請求。委派鏈中受託者發出的請求會追溯到人類發起的那個對話。
- **右側面板**：群組 → 任務看板（狀態統計、負責人、結果）、成員（私聊、設為主導者）、設定；
  Bot → 記憶（筆記與容量條、經驗的結果/使用次數/helpful/效用條、教訓與流程、技能、最近的記憶事件）、看板、會話、設定。
- **全寬看板**（`#/room/<id>/board`，群組標題列的 Chat / Board 切換）：五個狀態欄（To do、In progress、Blocked、Failed、Done），
  頂部是完成數、各狀態比例條、正在工作的成員與待你處理的請求。唯讀：任務由主導者建立、由委派推進。`task.updated` 事件帶著完整任務，
  前端直接更新卡片、不重新抓取；卡片依任務 ID 保留，只有任務改變時才重建，因此展開狀態與動畫不受其他更新影響。
  看板開啟時暫時收起右側面板，切回對話時恢復；對話內容在背景保持載入，切換不需重新讀取。
- **復原**：啟動時呼叫 `recover_interrupted()`，被中斷的會話顯示「Resume」橫幅。
- **設定頁**（參考 Hermes Desktop 的 Settings 與 settings manifest）：全視窗的設定面板，左側分類、可搜尋；所有設定列由前端的
  一份清單產生，搜尋與呈現使用同一份資料。外觀與版面存在瀏覽器（`localStorage`，`<head>` 內的小段程式在首次繪製前套用，避免閃爍）；
  模型、授權、沙箱與運行上限透過 `GET/PATCH /api/settings` 寫入 `PLAND_HOME/settings.yaml`（`pland/server/settings.py` 驗證範圍與選項，
  未知欄位與 `api_key` 一律拒絕，寫入為原子替換）。`Profile.settings()` 把 Profile 的覆寫疊在全域預設上，檔案依修改時間快取，
  改動在下一次運行生效、不需重啟；回應同時列出哪些 Profile 自己設定了該欄位。用量頁讀 `/api/usage` 的 `by_profile`、`by_day`
  （依模型分別計價後加總）。網頁的 Bot 設定只送出改過的欄位，未改的欄位繼續跟隨全域預設。
- **API 金鑰與供應商**（`pland/keys.py`）：設定頁可設定、測試、移除 DeepSeek／HKGAI 金鑰，切換 `PLAND_PROVIDER`，設定 HKGAI 的
  端點與模型。金鑰只存在 `.env`（與 `pland setup` 相同），寫入「目前提供該金鑰的檔案」：安裝目錄的 `.env` 優先於 `PLAND_HOME/.env`，
  寫到另一個檔案在重啟後會被蓋掉；`load_dotenv` 記錄每個變數的來源，從 shell 匯出的變數會提示重啟後以 shell 為準。寫入為原子替換、
  權限 600，並更新目前行程的環境變數，下一次運行即生效。回應永不包含金鑰；測試呼叫的錯誤訊息會遮蔽金鑰；「Save & test」先以
  關閉思考、8 個輸出 token 的真實調用驗證（401／403 不儲存，402 餘額不足則儲存並警告），並記入 ledger。這三個端點只接受
  loopback 用戶端、loopback 的 Host 標頭（防 DNS rebinding）、同源 Origin（防其他網頁跨站送出）與 JSON 內容。
  HKGAI 端點必須是 https 並通過端點護欄；護欄比對主機名稱前會先去掉結尾的點（`api.openai.com.` 不再能通過）。
- **版面**：側欄與右側面板可拖曳調整寬度（夾在 220–440 / 300–640 px，雙擊重設，方向鍵微調），側欄拖到幾乎合起即收起；
  ⌘B / ⌘. / ⌘, / ⇧⌘O 等快捷鍵（非 macOS 為 Ctrl）。設定頁開啟時主畫面設為 `inert`，Esc 關閉並把焦點還給原處。
- **視覺設計**：「工作日誌」風格——紙色底與墨色文字、襯線字體用於名稱與標題、等寬字用於機器產生的內容（模型、路徑、計數、狀態）、
  印章式的單一強調色（朱紅，另有群青、翡翠、石墨）；狀態以等寬字的「印章」標籤表示，工具呼叫像日誌行（左側色條表示成功/失敗/執行中）。
  顏色全部是 CSS 變數，深色模式在 `prefers-color-scheme` 與手動選擇下都重新定義。

**API**：`/api/status`、`/api/profiles[/{name}[/memory|/sessions|/bot-chat]]`、
`/api/profiles/{name}/sessions/{sid}/{messages|stop|resume}`、`/api/rooms[/{id}[/messages|/tasks|/stop]]`、
`/api/board/{scope}`、`/api/hitl[/{id}]`、`/api/usage`、`/api/interrupted`、`/api/profiles/{name}/uploads`、`/api/rooms/{id}/uploads`、
`/api/team-templates[/{id}/apply]`、`/api/settings`（全域預設，GET/PATCH）、`/api/settings/keys/{provider}`（PUT／DELETE）、`/api/settings/provider`、`/api/fs/dirs`（資料夾選擇器）、`/api/workspaces/recent`（`PATCH …/sessions/{sid}` 可設定該對話的
`reasoning`、`model` 與 `workspace`，`PATCH /api/rooms/{id}` 可設定群組共享資料夾；檔案瀏覽與上傳以 `?session=` 指定對話），以及 WebSocket `/api/events`
（工作執行緒的事件以 `call_soon_threadsafe` 轉入各連線的佇列）。所有執行都在背景執行緒，HTTP 不會被阻塞；
API 預設只綁定 127.0.0.1，沒有身分驗證，但只回應自己的頁面（`SameOriginGuard` 中介層，2026-10-24 加入）：綁定回送位址時
Host 必須是本機位址（防 DNS rebinding）；帶 Origin 的寫入請求與 WebSocket 握手必須與 Host 同源，`Sec-Fetch-Site: cross-site` 一律拒絕；
讀取與沒有這些標頭的請求（curl、測試）不受影響（跨來源讀取沒有 CORS 標頭，別的頁面本來就讀不到回應）。`pland serve --allowed-hosts`
可為反向代理加入允許的網域；綁定非回送位址（`--host 0.0.0.0`）時不檢查 Host，Origin 規則照舊。

---

## 10. 評測框架與可觀測性（`pland/eval/`）

- 測試集格式見 `pland/eval/SCHEMA.md`：任務可只有 `id` + `prompt`（適用事先未知的封閉測試集），
  也可附帶前置檔案、模擬使用者規則、團隊設定與 15 種客觀檢查（檔案、內容、指令/測試、Python 驗證碼、git 紀錄、
  HITL 次數、記憶內容、委派次數、看板任務等）。
- 每次測試集運行使用獨立的 `PLAND_HOME`（預設在 `~/.pland/eval_runs/`，不進版本庫），每個任務有乾淨的工作區與新的群組。
- **指標**：整體目標完成率（全部必要檢查通過）、子任務完成率（檢查項加權）、成功/部分/失敗/崩潰/逾時分布、
  執行時間（交付到最終結果的牆鐘時間：總計/平均/中位數/P90/最大）、模型調用與 token、快取命中率、估算花費。
- **紀錄**：每個任務保存事件流（`events.jsonl`）、完整對話（`transcript.md`）、檢查結果（`result.json`）與工作區快照；
  失敗模式自動分類（逾時、崩潰、預算、迴圈、HITL 行為錯誤、未真正委派、記憶未使用、交付物缺失、測試失敗…）。
- 命令：`pland eval run <suite> [--memory off] [--passes N] [--backend docker] [--model …]`、`pland eval list`、`pland eval report`。

---

## 11. 與 Hermes 的對照

| 主題 | Hermes | PlanD |
|---|---|---|
| Agent 身份 | Profile（`HERMES_HOME` 目錄） | Profile 目錄（相同概念，簡化） |
| Bot | Profile ＋ 名冊中繼資料 ＋ 永久 Bot Chat | 相同 |
| Bot 間訊息 | `message_agent`（非同步投遞、背景完成通知） | `message_agent`（同步、帶循環防護） |
| 群組 | 2–6 Bot、最多 3 輪、可 PASS、@user 求助 | 相同骨架；新增「討論輪 → 主導者委派」與提及紀律 |
| 子 Agent | `delegate_task`（全新脈絡、葉節點限制） | 相同，另可委派給**具名隊友**（在其 Profile 中執行）並與看板同步 |
| 記憶 | MEMORY.md / USER.md 有界筆記、技能、背景回顧 | 相同的筆記與技能；以**經驗庫＋效用回饋＋驗證校正**取代背景回顧 |
| 授權 | 危險指令模式、硬性封鎖、once/session/always/deny | 相同概念、精簡規則集 |
| 執行後端 | local / docker / ssh / modal… | local（macOS 上以 Seatbelt 限制檔案存取）/ docker |
| 會話檢索 | `session_search`（FTS5） | `session_search`（FTS5 trigram，支援中文） |
| 工作計畫 | `todo` 工具，壓縮後重新注入 | 相同 |
| 背景學習 | background review（沿用快取的分支） | 背景反思（沿用會話前綴）＋經驗庫 |
| 上下文壓縮 | 修剪舊工具輸出 → 結構化摘要、疊代更新 | 相同的兩階段設計 |
| 多 Agent 看板 | Kanban（parent link、worker 檢查點、review） | 任務看板＋前置任務交接、步數檢查點 |
| 智慧授權 | 輔助模型 APPROVE/DENY/ESCALATE | 相同（選用），對外與破壞性操作一律問人 |
| 介面 | CLI、TUI、Desktop、各種訊息平台 Gateway | CLI ＋ 輕量 Web（Bot Mode） |
| 設定頁與版面 | Desktop 的 Settings（settings manifest、可搜尋、profile 範圍）；側欄 237–360 px 可拖曳、⌘B 收合 | 全視窗設定頁（同樣由一份清單產生、可搜尋）；全域預設＋Profile 覆寫兩層；側欄 220–440 px 可拖曳、拖到底或 ⌘B 收合；右側面板可調寬 |
| 模型 | 多供應商 | 只允許 DeepSeek / HKGAI，有硬性護欄 |
| 思考強度 | `agent.reasoning_effort`（none…ultra 階梯，夾到各供應商支援的層級）；`hermes model` 選完模型後詢問；`/reasoning` 與 Desktop 輸入框的 reasoning pill 只改目前會話 | 相同的階梯與「夾到較弱層級」規則；`pland setup` 在選模型後詢問；`/reasoning` 與網頁輸入框選單只改目前對話；DeepSeek 的 `off` 以 `thinking` 開關實作 |
| 啟動 | 安裝程式寫入 `hermes` 啟動器（隔離模式的 Python）；`hermes desktop` 開啟 Electron App | `scripts/install.sh` 寫入 `pland` 啟動器（`python -I`）；`pland desktop` 啟動背景伺服器並開啟瀏覽器 App 視窗 |
| 工作目錄 | `agent/runtime_cwd.py` 單一來源；CLI 用啟動目錄，Desktop／Gateway 以 `_SESSION_CWD` 為每個會話固定工作目錄；Projects 為多資料夾工作區 | `pland/workspace.py` 單一來源；CLI 新對話用啟動目錄、`-w`、`/workspace`；網頁每個對話與群組可選資料夾；資料夾存在會話資料中，沙箱可寫根目錄隨之切換（沒有實作多資料夾 Projects） |
| Bot Chat 與資料夾 | 每個 Bot 一個 canonical Bot Chat；工作目錄是 Bot Profile 的 `terminal.cwd` 設定，換目錄不分開對話 | 每個（Bot、資料夾）一個 Bot Chat，切換資料夾即切換對話；記憶與技能仍是 Bot 層級共用；群組改共享資料夾時張貼系統訊息通知所有成員 |

未採用 fork 的原因：Hermes 規模龐大（數萬檔案、預設多供應商與隱含回退路徑），要確保「不使用 OpenAI/Anthropic」
需要全面審查；本專案需要的是其中的設計概念而非全部功能，因此選擇以其設計為參考重新實作精簡核心。
