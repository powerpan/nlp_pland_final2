# PlanD — 多智能體協作平台

PlanD 是一個能理解自然語言指令、透過規劃與工具調用**實際完成任務**的 AI Agent 平台：

- **平時是一個獨立 Agent**：在終端機或網頁和它對話，它會讀寫檔案、執行與測試程式、搜尋網路、提交並推送 git。
- **需要時進入 Bot Mode**：自行建立任意數量、任意職責的 Bot，和單一 Bot 私聊，或把多個 Bot 與自己放進群組；
  Bot 之間會真正分工、委派、交換資訊並整合成果。
- **一行指令啟動**：安裝後在任何資料夾輸入 `pland` 即可對話，`pland desktop` 以獨立視窗開啟網頁介面。
- **對話的工作資料夾**：每個對話可以指定自己的資料夾（在專案資料夾內啟動 `pland`、`-w`、`/workspace` 或網頁標題列的資料夾按鈕），
  資料夾存在對話資料中、不靠模型記憶；Bot 的 Bot Chat 每個資料夾一個，不同專案的脈絡不會混在一起。
- **設定頁與版面**：網頁按 ⌘,（或側欄底部的 Settings）開啟設定頁：外觀、模型、Agent 行為、沙箱與資料夾、運行上限、用量、
  快捷鍵與關於，可搜尋所有設定。在 Model 頁可直接貼上 DeepSeek／HKGAI 的 API 金鑰（先以一次小調用驗證，只寫入 `.env`、
  之後不再顯示）、切換供應商、設定 HKGAI 端點與模型。模型、思考強度、授權、沙箱與上限是所有 Bot 共用的**全域預設**（`~/.pland/settings.yaml`），
  Bot 自己設定過的值優先；側欄可拖曳調整寬度、⌘B 隱藏，右側面板同樣可調寬。
- **介面風格**：「工作日誌」式設計：紙色底、襯線標題、等寬字標示模型/路徑/狀態、印章式強調色；可切換淺色/深色、四種強調色與字級。
- **思考強度**：每個 Bot 可設定思考強度，每個對話也能在輸入框右側的選單或 `/reasoning` 臨時切換。DeepSeek 為 off / default / low / medium / high / max；
  HKGAI 為 off / default / minimal / low / medium / high / xhigh / max（HKGAI 不送等級就不思考，所以 default 送 medium）。
- **Human-in-the-Loop**：指令不清楚或缺少會影響結果的資訊時會先問你；刪檔、`git push` 等重要操作前會請你授權
  （once / session / always / deny，另有選用的 smart 模式以守門模型分流低風險指令）；答覆後從中斷處繼續，程式中斷後也能恢復。
- **規劃與記憶**：多步驟工作會寫下 `todo` 工作計畫；每個 Agent 有自己的有界筆記、經驗庫（任務後背景反思、依驗證結果演化）、
  技能，以及可全文檢索（含中文）的過往對話。
- **長任務與團隊協作的護欄**：每次運行最多 80 步、300 次模型調用／800 萬加權 token（群組推進加倍），單次回應最多
  32,768 個輸出 token；有重複迴圈偵測。受託者在步數用到 80% 時若還沒寫出指定的交付檔，只會拿到寫檔工具，步數用盡時
  再給一步存檔；回應在工具呼叫中途被截斷時不會執行，而是要求分段寫入。隊友寫出的檔案在委派結束時自動送回委派者的
  `inbox/from-<隊友>/`；每個委派結果都附上目前的預算用量，用到 70% 時主導者會收到提示；工作計畫久未更新時會提醒。
- **隔離**：每個 Agent 有自己的 Profile、資料庫與私有工作區（或目前對話選定的資料夾）；macOS 上指令在 Seatbelt 沙箱中執行，
  在使用者家目錄與 PlanD 資料夾內只能存取這個工作區；也可改用 Docker 容器。邊界與尚未修正的問題見「[已知限制](#已知限制)」。
- **客觀評測**：內建 Evaluation Harness，以可驗證的檢查自動計算任務完成率與執行時間。
- **模型**：只使用 DeepSeek（預設 `deepseek-flash`）或 HKGAI；系統中有硬性護欄，拒絕任何 OpenAI / Anthropic 端點。
  HKGAI 沒有搜尋與抓取 API，所以改用 HKGAI 時，網路搜尋與抓取仍走 DeepSeek 的 Search／Fetch API（需要 `DEEPSEEK_API_KEY`）。

文件：[使用導覽](docs/USAGE.md) · [需求對照表](docs/REQUIREMENTS_TRACE.md) · [系統架構說明](docs/ARCHITECTURE.md) · [測試與效能報告](docs/EVALUATION_REPORT.md) · [評測任務格式](pland/eval/SCHEMA.md) · [需求文件](Multi_Agent_Platform_Requirements.md)

## 安裝

需要 Python 3.10+（開發時使用 3.11）、git；Docker 為選用。

```bash
git clone https://github.com/victoryuanxichen/nlp_final_pland.git && cd nlp_final_pland
bash scripts/install.sh     # 建立 .venv、安裝套件，並把啟動器寫到 ~/.local/bin/pland
pland setup                 # API 金鑰（存到 ~/.pland/.env）、模型、思考強度、沙箱、授權模式；也可在網頁 Settings → Model 設定金鑰
pland doctor --probe        # 以數次小調用確認：對話、工具調用、思考強度、JSON、Search、Fetch
```

`scripts/install.sh` 不會修改你的 shell 設定；若 `~/.local/bin` 不在 PATH 中，它會印出要加入的那一行。
啟動器以隔離模式（`python -I`）執行，所在資料夾的檔案不會影響 PlanD；PlanD 也不讀取目前資料夾的 `.env`，
只讀取安裝目錄與 `PLAND_HOME` 的 `.env`。也可以不安裝啟動器，直接使用 `.venv/bin/pland`。

執行時的所有狀態（Profile、記憶、會話、工作區、評測紀錄）都在 `PLAND_HOME`（預設 `~/.pland`），不會寫進版本庫。

## 使用

### 單 Agent（CLI）

```bash
pland                                     # 互動對話（等同 pland chat；/help 查看指令），在目前的資料夾工作
pland -w ~/projects/app                   # 指定這個對話的工作資料夾；-w default 為 Bot 自己的私有工作區
pland chat -q "寫一個計算質數的模組並測試"    # 單次提問
pland chat -c                             # 繼續最近的對話
pland memory                              # 查看記憶與經驗
```

**工作資料夾**：在專案資料夾內啟動 `pland`，新對話就在那個資料夾讀寫檔案、執行指令（沙箱只開放這個資料夾）；
從家目錄或 PlanD 安裝目錄啟動時改用 Bot 的私有工作區。資料夾存在對話資料中，恢復對話時不變；對話中可用 `/workspace <資料夾>` 更換。
Bot 的 Bot Chat 則是**每個資料夾一個**：`pland -p coder --bot-chat` 在專案資料夾內執行就開啟 coder 在該專案的對話，換資料夾即換對話，
不會把不同專案的脈絡混在一起（記憶、經驗、技能仍由 Bot 共用）。

對話中可用 `/reasoning [off|default|minimal|low|medium|high|xhigh|max|reset]` 與 `/model [deepseek-flash|deepseek-v4-pro|reset]`
只改變目前對話的思考強度與模型；所有 Bot 共用的預設值在網頁的設定頁調整（存於 `~/.pland/settings.yaml`），
單一 Bot 的值用網頁的 Bot 設定、`pland setup` 或 `pland profile set <名稱> --reasoning high` 設定，優先於全域預設。
步數與預算上限（`max_iterations`、`max_run_calls`、`max_run_tokens`、`model.max_tokens`）同樣在設定頁的 Run limits，或在 Profile 的 `profile.yaml` 針對單一 Bot 覆寫。

### Bot Mode（網頁）

```bash
pland desktop            # 啟動（或沿用）背景伺服器，並以獨立 App 視窗開啟；pland desktop --stop 停止
pland serve              # 或在前景執行伺服器，自行開啟 http://127.0.0.1:8765
```

- **Chats**：單 Agent 對話。標題列的資料夾按鈕可為這個對話選擇工作資料夾（群組則是共享資料夾）。輸入框為單行：左側 **+** 上傳檔案（也可拖放或貼上），右側為模型與思考強度選單（只影響目前對話）。
- **Bots & groups**：建立 Bot（名稱、職稱、描述、人格、模型、思考強度、沙箱後端），與 Bot 私聊；建立群組並指定主導者。
  **Templates** 可一鍵加入範例團隊（見下）。
- **Settings**（⌘,）：外觀、API 金鑰與供應商、全域預設（模型、授權、沙箱、運行上限）、用量與快捷鍵；側欄可拖曳調寬或以 ⌘B 隱藏。
- 群組中用 `@名稱` 指定對象，`@all` 對全體；在群組上傳的檔案放在共享資料夾 `shared/uploads/`，所有成員都能讀取。
  Bot 需要你時群組會出現 **needs you** 標記。
- 右側面板顯示任務看板、Bot 的記憶與經驗、工作區檔案；澄清與授權請求以卡片顯示在對話中。
- 群組標題列的 **Chat / Board** 切換到全寬看板（`#/room/<id>/board`）：To do、In progress、Blocked、Failed、Done 五欄，
  卡片顯示編號、相依任務、負責人與結果摘要，點開看完整說明與結果；隊友正在處理的卡片會標示目前動作。看板唯讀，隨團隊工作即時更新。
- 輸入框上方顯示 Agent 與正在工作的隊友的工作計畫（`todo`）；計畫久未更新時標示 **not updated · N calls**，
  運行結束仍有未完成項目時標示 **run ended**。委派給隊友的交付檔會出現在委派者資料夾的 `inbox/from-<隊友>/`。

### 範例團隊（依需求文件設計）

```bash
pland team list
pland team apply requirements-team      # 或在網頁側欄 Bots & groups → Templates
```

| Bot | 職責 | 思考強度 | 工具 | 沙箱 |
|---|---|---|---|---|
| `lead` | 拆解目標、在看板上委派、整合並驗證、提交 git | high | 檔案、程式、git、記憶、計畫、詢問、委派、團隊 | local |
| `researcher` | 從一手來源查證最新資訊，寫附來源的 Markdown | low | 網路、檔案、記憶、計畫、詢問、團隊（不能執行程式） | local |
| `coder` | 撰寫並以 pytest 測試 Python | default | 檔案、程式、git、記憶、計畫、詢問、委派、團隊 | local |
| `reviewer` | 獨立測試與審查，給出 PASS / FAIL | max | 檔案、程式、記憶、計畫、團隊 | docker |
| `writer` | 只寫 `.md` / `.txt` 文件 | low | 檔案、記憶、計畫、詢問、團隊 | local |

同時建立兩個群組：**Build team**（五人，主導者 `lead`）與 **Research desk**（`researcher`、`writer`）。
這些角色只是範本資料（`pland/team_templates/requirements-team.yaml`），系統本身不依賴任何固定角色。

也可以用 CLI 管理 Bot（它們就是 Profile）：

```bash
pland profile create coder --title "Coder" --description "Writes and tests Python code" --reasoning high
pland profile list
pland chat -p coder --bot-chat        # 與網頁上相同的 Bot Chat
```

### 評測

```bash
pland eval list
pland eval run dev                     # 快速冒煙測試
pland eval run midterm
pland eval run final
pland eval run memory_evolution --passes 2          # 記憶跨輪保留
pland eval run midterm --memory off --label nomem   # 記憶消融
pland eval run path/to/closed_set/                  # 任意目錄（YAML / JSON / JSONL）
```

每次運行輸出 `report.md`（繁體中文）、`results.json` 與每個任務的事件流、對話紀錄與工作區快照。

最終版本（`deepseek-flash`＋思考模式，真實 DeepSeek API）的結果，詳見[測試與效能報告](docs/EVALUATION_REPORT.md)：

| 測試集 | 任務 | 整體目標完成率 | 子任務完成率 | 總時間 | 估算花費 |
|---|---|---|---|---|---|
| midterm | 15 | 100% | 100% | 379s | $0.15 |
| final | 8 | 100% | 100% | 1183s | $0.40 |
| hard | 8 | 87.5% | 93.5% | 1980s | $0.65 |
| memory_evolution 記憶開啟／關閉 | 12／6 | 100%／33.3% | 98.7%／47.4% | 190s／213s | $0.08／$0.06 |

## 已知限制

以下是目前的實際邊界，其中標「待修正」的是 2026-10-21 團隊審查發現、經程式碼確認但尚未修正的問題
（同次審查發現的模型端點護欄「結尾點主機名稱」問題已於 2026-10-22 修正）：

- **Local 後端的範圍**：Seatbelt 只限制使用者家目錄與 `PLAND_HOME` 內的檔案存取；`/tmp` 等其他位置仍可讀寫，網路也不受限。
  Linux 上沒有 Seatbelt，Local 後端執行的程式可以讀寫使用者帳號能存取的任何檔案。需要強隔離時請用 Docker 後端。
- **git 工具在沙箱外執行（待修正）**：`git_status`、`git_commit`、`git_push` 在主機上執行 git，而 Agent 可以修改倉庫的
  `.git/config`；git 會依設定執行指令（例如 `core.fsmonitor`），因此 Agent 有機會藉此在沙箱外執行程式。在完成修正前，
  請只在信任的倉庫中使用 git 工具，或改用 Docker 後端並避免讓 Agent 使用 git 工具。
- **推送授權是規則比對（待修正）**：`git push` 會要求授權，但 `git -c … push`、`git send-pack` 等寫法不會觸發。macOS 上沙箱化的
  shell 使用私有 HOME，拿不到 HTTPS 的憑證助手；但 **`SSH_AUTH_SOCK` 仍會傳進沙箱**（2026-10-24 稽核以真實 Seatbelt 確認），
  若使用者的 ssh-agent 載有金鑰，Agent 仍可能透過 SSH 遠端推送或連線。Linux 的 Local 後端則會直接使用使用者的憑證。
- **工作計畫是 Agent 自己維護的清單**：系統不會依實際的工具呼叫自動勾選項目。計畫久未更新時會提醒 Agent 並在介面標示，
  但顯示的進度仍可能落後於實際完成的工作；以交付檔與看板狀態為準。
- 其他邊界（容器以 root 執行、危險指令偵測可被刻意混淆繞過等）見[架構文件 6.3 節](docs/ARCHITECTURE.md)。

## 開發

```bash
.venv/bin/python -m pytest -q          # 184 項，全部使用腳本化模型，不需金鑰、不連網（Docker 測試在無 Docker 時跳過）
```

GitHub Actions（`.github/workflows/ci.yml`）在 Python 3.10 與 3.12 上執行 `ruff check`（pyflakes 規則）與同一組測試；
`requirements.lock` 記錄開發時實測通過的套件版本，需要完全重現環境時可用 `.venv/bin/pip install -r requirements.lock`。

| 目錄 | 內容 |
|---|---|
| `pland/agent.py` | Agent 執行循環（步數檢查點、截斷與標記處理、交付檔強制、迴圈與無進展護欄、計畫提醒、預算提示） |
| `pland/workspace.py` | 對話與群組的工作資料夾（驗證、單一來源） |
| `pland/llm/` | DeepSeek／HKGAI 客戶端、端點護欄、思考強度（`reasoning.py`）、價格 |
| `pland/tools/` | 檔案、程式執行、網路、git、記憶、HITL、委派與團隊工具 |
| `pland/team/` | 委派、Bot 間訊息、任務看板、群組 Room、團隊範本 |
| `pland/team_templates/` | 範例團隊（`requirements-team.yaml`） |
| `pland/memory.py`, `reflection.py` | 筆記、經驗庫、技能、任務後反思 |
| `pland/server/` | FastAPI 伺服器、全域設定 API（`settings.py`）、網頁介面（`static/`，原生 JS，無建置步驟） |
| `pland/keys.py` | API 金鑰與供應商設定（只寫入 `.env`、不回傳金鑰、只接受本機同源請求） |
| `pland/sandbox/` | 路徑政策、危險指令分類、Local / Docker 後端 |
| `pland/eval/` | Evaluation Harness 與測試集 |
| `scripts/install.sh` | 安裝與 `~/.local/bin/pland` 啟動器 |
| `.github/workflows/ci.yml` | CI：lint（ruff，pyflakes 規則）與單元測試 |
| `pland-promo/` | 產品介紹短片的程式化渲染專案（Node + three.js，與平台本體無關；`node_modules/` 與輸出不進版本庫） |

## 授權

MIT License，全文與第三方程式碼的授權聲明見 [LICENSE](LICENSE)。

## 部署與啟動（給取得此倉庫的開發者）

需要 macOS 或 Linux（Windows 未測試，可用 WSL）、Python 3.10 以上、git，以及 DeepSeek API 金鑰（或 HKGAI 的金鑰、端點與模型）；
Docker 為選用。

```bash
git clone https://github.com/victoryuanxichen/nlp_final_pland.git
cd nlp_final_pland
bash scripts/install.sh     # 建立 .venv、安裝套件，並把啟動器寫到 ~/.local/bin/pland（不在 PATH 時會印出要加入的那一行）
pland setup                 # 貼上 DeepSeek API 金鑰（存到 ~/.pland/.env），選擇模型與思考強度
pland desktop               # 在背景啟動伺服器並開啟網頁介面 http://127.0.0.1:8765
```

- 也可以直接 `pland desktop`，在網頁 **Settings → Model** 貼上金鑰；終端機對話則在專案資料夾內執行 `pland`。
- 停止伺服器：`pland desktop --stop`。更新程式：`git pull`，依賴有變時執行 `bash scripts/install.sh --reinstall`，再停止並重新啟動伺服器。
  `pland doctor --probe` 可確認金鑰與模型連線正常。
- 執行時的資料都在 `~/.pland`（可用 `PLAND_HOME` 改到其他位置），不會寫進倉庫；`.env` 已被 git 忽略，不要提交金鑰。
- 伺服器預設只綁定本機（127.0.0.1）且沒有登入驗證，請勿用 `--host 0.0.0.0` 直接開放到網路；需要給他人使用時，
  請放在有身分驗證的反向代理之後。
- 伺服器只回應自己的頁面：綁定本機位址時，Host 必須是本機（防 DNS rebinding）；帶 Origin 的寫入請求與 WebSocket 連線必須同源，
  `Sec-Fetch-Site: cross-site` 一律拒絕；沒有這些標頭的請求（curl、腳本）與讀取不受影響。放在反向代理之後時，
  以 `pland serve --allowed-hosts <對外網域>` 允許該網域作為 Host 與 Origin。
- 想用 Docker 沙箱：安裝並啟動 Docker，在 Settings → Sandbox & folders 選 Docker，第一次使用時會自動建置映像。
- 開發與測試：`.venv/bin/pip install -e ".[dev]"`，再執行 `.venv/bin/python -m pytest -q`（不需金鑰、不連網）。
