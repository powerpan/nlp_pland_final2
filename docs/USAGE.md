# PlanD 使用導覽

本文件帶你在 10 分鐘內體驗 PlanD 的主要能力。安裝見 [README](../README.md)：執行一次 `bash scripts/install.sh` 之後，
在任何資料夾都能用 `pland` 啟動。所有執行狀態都在 `PLAND_HOME`（預設 `~/.pland`）；想要乾淨的示範環境可以先設定
`export PLAND_HOME=/tmp/pland-demo`。

## 1. 單 Agent（CLI）

```bash
pland            # 等同 pland chat
```

可以試：

- `寫一個 is_prime 函式和 pytest 測試，執行測試並回報結果` —— 觀察它先寫 `todo` 計畫、建立檔案、執行測試、回報證據。
- `建立 prices.txt，放五個價格，然後換算成另一種貨幣` —— 指令缺少關鍵資訊時，它會先**詢問**你，而不是猜測。
- `建立 build 資料夾放兩個檔案，然後把整個資料夾刪掉` —— 刪除前會請你授權（once / session / always / deny）；選 deny，它會說明無法刪除。
- `記住：以後的報告都放在 reports/，第一行寫 Owner: Dana` —— 寫入記憶；開新會話（`/new`）再請它寫報告，它會套用。
- 在自己的專案資料夾裡執行 `pland`（或 `pland -w ~/projects/app`）：這個對話就在那個資料夾工作，`/workspace` 可查看或更換。
- `/reasoning` 查看並切換這個對話的思考強度（`/reasoning off` 最快、`/reasoning max` 最深、`/reasoning reset` 回到 Profile 設定）；
  `/model deepseek-v4-pro` 讓這個對話改用較強的模型。
- `/memory` 查看筆記與經驗；`/sessions`、`/resume <id>` 管理會話。

Profile 的預設值（模型、思考強度、沙箱、授權模式）用 `pland setup` 設定，與 `hermes setup` 一樣在選完模型後詢問思考強度。

## 2. Bot Mode（網頁）

```bash
pland desktop    # 以獨立視窗開啟；伺服器在背景執行，pland desktop --stop 停止
```

**工作資料夾**：標題列的資料夾按鈕（預設顯示「@default's workspace」）可為這個對話選擇資料夾；群組標題列的按鈕則設定共享資料夾。
選擇器只顯示資料夾，家目錄本身、系統資料夾與 PlanD 的資料夾不能選。
- **與 Bot 私聊時**：Bot 每個資料夾有一個獨立的 Bot Chat。選資料夾 = 切換到那個資料夾的對話（選擇器上方列出所有資料夾對話，可隨時切回）；
  想把目前的脈絡帶過去，選「Move this conversation here」。
- **群組**：改共享資料夾後，群組中會出現一則系統訊息，每位成員下一輪都會讀到；若想讓每個專案有獨立的團隊脈絡，選「Start a new group with the same bots for this folder」。

**輸入框**是一行：左側 **+** 上傳檔案（也可以拖放或貼上），右側依序是模型、思考強度與送出鍵。模型與思考強度只影響目前的對話，
選單最下方的「Use the bot's setting」可還原；在群組中每個 Bot 使用自己的設定，所以這兩個選單不會出現。

**設定頁與版面**（參考 Hermes Desktop 的設定與側欄）：

- **⌘,**（Windows/Linux 為 Ctrl+,）或側欄底部的 **Settings** 開啟設定頁，左側分類、上方可搜尋所有設定：
  - **Appearance**：淺色/深色/跟隨系統、強調色、對話字級、思考區塊顯示或隱藏、側欄密度與寬度、右側面板預設開關與寬度（只存在這個瀏覽器）。
  - **Model / Agent / Sandbox & folders / Run limits**：所有 Bot 共用的**全域預設**，改動立即寫入 `~/.pland/settings.yaml`、下一次運行生效；
    已自行設定的 Bot 會列在該列下方（點名稱可前往）。每列的「reset」回到內建預設。
  - **Model → Provider and keys**：貼上 API 金鑰後按 **Save & test**，先以一次很小的真實調用確認金鑰有效（被拒絕就不會儲存），
    再寫入原本存放金鑰的 `.env`（安裝目錄的 `.env` 或 `~/.pland/.env`，權限 600），伺服器立即使用、不需重啟；金鑰之後不會再顯示，
    頁面只標示「key set」與來源檔案。也可移除金鑰、切換供應商（DeepSeek／HKGAI；HKGAI 需先填金鑰、https 端點與模型）。
    這些變更只接受來自本機、同一頁面的請求。
  - **Usage**：今天/7 天/30 天/全部的調用次數、token、快取命中、花費，每日花費長條與各 Bot 明細（來自 ledger，不含對話內容）。
  - **Keyboard**、**About**（版本、資料夾、Docker/Seatbelt 狀態、常用指令）。
- **側欄**：拖曳右緣調整寬度（雙擊恢復預設），拖到幾乎合起即隱藏；**⌘B** 或側欄右上角的按鈕隱藏/顯示。右側面板（**⌘.**）同樣可拖曳左緣調寬。
- 其他快捷鍵：**⇧⌘O** 新對話、**/** 跳到輸入框、**Esc** 關閉設定頁與選單。

### 2.1 一鍵加入範例團隊

側欄 **Bots & groups → Templates → Add team**（或 `pland team apply requirements-team`）會加入依需求文件設計的五個 Bot 與兩個群組：

| Bot | 職責 | 思考強度 | 沙箱 |
|---|---|---|---|
| `lead` | 拆解目標、在看板上委派、整合並驗證、提交 git | high | local |
| `researcher` | 從一手來源查證最新資訊，寫附來源的 Markdown（不能執行程式） | low | local |
| `coder` | 撰寫並以 pytest 測試 Python | default | local |
| `reviewer` | 在 Docker 容器中獨立測試與審查，給出 PASS / FAIL | max | docker |
| `writer` | 只寫 `.md` / `.txt` 文件（不能上網、不能執行程式） | low | local |

群組 **Build team**（五人，主導者 `lead`）與 **Research desk**（`researcher`、`writer`，主導者 `researcher`）。
可以試（每一項對應需求文件的一個重點）：

| 在哪裡 | 輸入 | 觀察 |
|---|---|---|
| Build team | `在共享資料夾建立 Python 模組 unitconv：長度、重量、溫度換算，附 pytest 測試、獨立審查與 README.md 使用範例，最後用 git 提交。` | 任務拆解與看板、並行委派、reviewer 在容器內獨立測試、writer 寫文件、lead 整合驗證、git 授權（§2.3、§3、§6） |
| Research desk | `比較 Python、Node.js、Go 目前最新穩定版與發布日期，只用官方來源，寫成 shared/versions.md 並附連結。` | 網路搜尋與抓取、來源標註、成員分工（§6） |
| Research desk | 用 **+** 上傳一個 CSV，輸入 `摘要這份資料，寫成 shared/summary.md` | 上傳到共享資料夾，成員以檔案工具讀取 |
| Build team | `清理共享資料夾` | 指令不明確時先詢問；刪除前請求授權（§3） |
| 與 `lead` 私聊 | `記住：我們團隊的報告第一行一律寫 Owner: Dana`，之後在 Build team 請它寫報告 | 每個 Bot 有自己的記憶，之後的任務會套用（§4） |

### 2.2 自己建立 Bot 與群組

1. **+ New bot**：名稱、職稱、描述會影響分工；思考強度可選 Off / Default / Low / Medium / High / Max（HKGAI 另有 Minimal 與 Extra high）。
2. 點任一 Bot 進入它的 **Bot Chat**（與它私聊）；右側面板可看它的記憶、經驗、技能、工作區檔案與設定。
3. **+ New group** 建立群組並選主導者，送出目標後觀察：討論輪 → 主導者在 **Board** 建立任務 → 委派（活動列顯示開始/完成）
   → 受託者在各自的工作區工作 → 主導者整合、驗證後回報。右側 **Files** 可查看 `shared/` 中的成果。
   標題列切到 **Board** 可全寬檢視看板：五個狀態欄，卡片隨委派即時移動；點卡片展開完整說明與結果，切回 **Chat** 繼續對話。
4. 在群組中用 `@名稱 ...` 指定對象；Bot 需要你時群組會出現 **needs you**，澄清與授權以卡片顯示在對話中。

CLI 也能和同一個 Bot 對話：`pland chat -p coder --bot-chat`（就是網頁上那個 Bot Chat）。

## 3. 評測

```bash
pland eval list
pland eval run dev                       # 約 1 分鐘、約 $0.02
pland eval run midterm                   # 約 6 分鐘、約 $0.15
pland eval run memory_evolution --passes 2
pland eval run midterm --backend docker  # 以 Docker 容器執行指令
pland eval run hard --reasoning max      # 比較不同思考強度
```

每次運行在 `~/.pland/eval_runs/<suite>-<時間>/` 產生 `report.md`（繁體中文）、`results.json`，
以及每個任務的事件流、對話紀錄與工作區快照。`pland eval compare A=<dir> B=<dir>` 可並排比較兩次運行。

## 4. 常用設定

設定有兩層：**全域預設**（網頁設定頁，存於 `~/.pland/settings.yaml`，所有 Bot 共用）與 **Profile 覆寫**（`profiles/<名稱>/profile.yaml` 的 `settings`，
只影響該 Bot，優先於全域預設）。兩者使用相同的欄位：

| 設定 | 說明 |
|---|---|
| `model.model` | `deepseek-flash`（預設）或 `deepseek-v4-pro` |
| `model.thinking`、`model.reasoning_effort` | 思考強度：`pland setup` / `pland profile set <名稱> --reasoning <off\|default\|minimal\|low\|medium\|high\|xhigh\|max>` 會寫入這兩個欄位；預設為 default（開啟思考、不指定強度；HKGAI 送 medium） |
| `sandbox.backend` | `local`（macOS 上自動以 Seatbelt 限制檔案存取）或 `docker` |
| `approvals.mode` | `manual`（預設）、`smart`（守門模型分流低風險指令）、`off` |
| `toolsets` | 例如移除 `web` 讓某個 Bot 不能上網 |
| `max_iterations`、`max_run_calls`、`max_run_tokens` | 步數與預算上限（預設 80 步、每次運行 300 次調用／800 萬加權 token，群組推進加倍）；`model.max_tokens` 為單次回應輸出上限（預設 32,768） |

網頁設定頁可調整全域預設；Bot 的右側面板 → Settings 調整單一 Bot（只會寫入你改過的欄位，其他欄位繼續跟隨全域預設）。
