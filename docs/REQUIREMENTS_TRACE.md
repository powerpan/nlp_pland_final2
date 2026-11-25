# 需求對照表

逐項對照 [需求文件](../Multi_Agent_Platform_Requirements.md) 與實作、驗證證據。
「測試」指 `pytest`（腳本化模型）；「評測」指以真實 DeepSeek API 執行的測試集（見 [測試與效能報告](EVALUATION_REPORT.md)）。

| 需求 | 實作 | 證據 |
|---|---|---|
| **§1 理解自然語言、規劃、工具調用、實際執行** | Agent 執行循環 `pland/agent.py`；`todo` 工作計畫；檔案／程式／網路／git 工具 | 評測 midterm、final 全部任務（以檔案、測試、git 紀錄驗證） |
| **§2.1 單 Agent 模式**：直接對話、工具、程式、檔案、記憶、請求澄清／授權；不強制進入多 Agent | `pland chat`（CLI）、網頁 Chats 分頁；預設 `default` Profile 單獨處理所有請求 | 評測中所有 single 任務；`tests/test_agent.py` |
| **§2.2 Bot Mode**：自建團隊、任意數量與職責的 Bot | Bot = Profile（`pland/profiles.py`）；網頁 New bot、CLI `pland profile create`；選用的範例團隊（`pland team apply requirements-team`／網頁 Templates，五個異構 Bot：不同工具、沙箱與思考強度） | `tests/test_server.py`（Profile CRUD）；`tests/test_composer_features.py::test_requirements_team_template`；瀏覽器實測 |
| Bot 保有自己的身份、會話、記憶、工作狀態 | 每個 Profile 自己的目錄、`state.db`、記憶、技能、工作區；永久 Bot Chat | `tests/test_team.py::test_delegation_runs_in_target_profile`（隔離） |
| 人類與單一 Agent 私聊 | 每個 Bot 的永久 Bot Chat（網頁、`pland chat -p <bot> --bot-chat`） | `tests/test_server.py`（bot-chat） |
| 多個 Agent 與人類的群組聊天 | 群組 Room（`pland/team/rooms.py`）：輪次、@提及、`[PASS]`、needs you | `tests/test_team.py`（room 測試）；評測 team 任務 |
| Bot 之間傳訊、共享資訊、協作 | `message_agent`、`delegate_task`、`share_file`、群組 `shared/`、任務看板 | `tests/test_team.py::test_message_agent`；評測 team 任務 |
| 切換模式不遺失持久狀態 | CLI 與網頁操作同一個 Profile／會話；狀態全部持久化在 SQLite | `tests/test_agent.py::test_recover_interrupted_and_resume` |
| CLI 與 Bot Mode 的邊界（不在 CLI 完整移植 Bot Mode） | 參考 Hermes：Bot Mode 在網頁；CLI 只到 Profile／會話層級 | 架構文件第 9 節 |
| **§2.3 拆解、分工、委派、協調、整合**；不是輪流回覆 | 主導者以看板拆解、`delegate_task` 委派（受託者在自己的 Profile 中真正執行）、並行、前置任務交接、整合驗證 | 評測：v2 輪次 8 次團隊任務中 7 次真正委派（共 19 次，5 個任務出現並行），最終版本 5 個團隊任務全部委派（共 14 次）；`tests/test_agent_features.py::test_prerequisites_gate_and_handoff` |
| **§3 HITL**：歧義時暫停詢問 | `ask_user`；規則「結果相依的未說明參數要詢問」 | 評測 `mid-hitl-clarify-temps`、`dev-hitl-greeting`、`final-hitl-crm-export`；`tests/test_agent.py::test_clarification_resumes_same_run` |
| 重要操作前請求授權、不可繞過 | 授權閘門（once/session/always/deny）、硬性封鎖、對外與破壞性操作一律問人、禁止繞過 | 評測 `mid-hitl-approve-delete`／`deny-delete`；`tests/test_agent.py::test_approval_deny_and_session_grant`、`test_hardline_block` |
| 獲得答覆後繼續，不重新開始 | 請求在工具呼叫內等待，答覆後同一運行繼續；程式中斷後 `resume()` 從紀錄續跑 | `tests/test_agent.py::test_clarification_resumes_same_run`、`test_resume_after_interrupted_tool_call` |
| **§4 每個 Agent 自己的記憶** | Profile 內的筆記、經驗庫、技能、會話全文檢索 | `tests/test_agent.py::test_memory_tool_and_snapshot` |
| 提煉成功案例、失敗原因、可重用方法並在後續利用 | 背景反思 → 經驗（教訓、流程）；BM25＋覆蓋率檢索；效用回饋；以驗證結果校正；信念修正 | 評測 memory_evolution（最終版本）：記憶開啟 12/12 vs 關閉 2/6 |
| 不因同一群組就共享私人記憶與檔案 | 只有四種顯式通道；檔案工具受 PathPolicy 限制；Seatbelt／Docker 執行隔離 | `tests/test_sandbox.py`；評測中沙箱擋下讀取 `state.db` 的嘗試 |
| 報告說明記憶如何變化、再利用與影響 | 評測報告第 7 節；每個任務的記憶快照與 `memory_events` | `docs/eval_results/*/memory_evolution_*.md` |
| **§5 獨立工作狀態、專屬檔案空間、可隔離的執行環境** | Profile 隔離；macOS Seatbelt 沙箱；Docker 容器（專用映像檔、能力全移除、資源限制）；每個對話可指定工作資料夾，沙箱只開放該資料夾（架構文件 6.1.1） | `tests/test_sandbox.py`（Seatbelt、Docker）、`tests/test_workspaces.py` |
| 區分邏輯隔離與執行隔離、如實記錄邊界 | 架構文件第 6 節（含「目前的邊界與待補強之處」） | — |
| 分階段：先借鑑 Hermes，再依測試結果加強 | 初版 local 後端 → 評測發現 Agent 讀取工作區外資料 → 加入 Seatbelt；Docker 評測發現三個問題 → 修正 | 評測報告第 4、8.4 節 |
| **§6 網路檢索** | `web_search`／`web_fetch`（DeepSeek Search／Fetch API 為主，失敗回報為失敗） | 評測 web 類任務；`pland doctor --probe` |
| 檔案讀寫刪 | `read_file`、`write_file`、`edit_file`、`delete_file`（授權）、`list_dir`、`search_files` | 評測 files 類任務 |
| 撰寫、測試、執行程式 | `run_python`、`run_shell`（沙箱） | 評測 coding 類任務（隱藏測試） |
| Git Commit 並 Push 到 GitHub | `git_status`、`git_commit`、`git_push`（主機端憑證、人類授權） | 評測 git 類任務（推送到 bare remote）；**實際推送到 GitHub 分支 `demo/agent-git-push`**（報告 9.3 節） |
| 文件限定 Markdown 與純文字 | 檔案工具拒絕 PDF／Office 文件格式；網頁抓取拒絕二進位文件 | `pland/tools/files.py` |
| **§7 只用 DeepSeek 或 HKGAI**，含所有輔助調用 | 唯一的模型客戶端與 `check_endpoint` 護欄；反思、壓縮、守門模型都走同一路徑；無第三方 SDK | `tests/test_providers.py` |
| **§8 介面**：對話、進度、結果、HITL；Bot 清單、群組 | CLI（任何資料夾一行 `pland` 啟動）；網頁（`pland desktop` App 視窗；名冊、群組、串流、工具卡片、計畫卡、看板、記憶、檔案瀏覽、HITL 卡片；單行輸入框：+ 上傳、模型與思考強度選單） | `tests/test_server.py`、`tests/test_composer_features.py`；瀏覽器實測 |
| **§9 Evaluation Harness**：標準化任務集、不依賴硬編碼 | `pland/eval/`：YAML／JSON／JSONL、欄位別名、15 種客觀檢查、檢查本身以參考解與錯誤解驗證 | `tests/test_eval.py`；`tools/suite_builder/validate.py` |
| Task Completion Rate（子任務與整體目標，識別未完成／失敗／崩潰） | 檢查項加權的子任務完成率、必要檢查決定的目標完成率；成功／部分／失敗／崩潰／逾時 | 各次 `report.md` |
| Execution Time | 交付到最終結果的牆鐘時間（反思在背景、不計入） | 各次 `report.md`；`pland eval aggregate` |
| 執行與狀態紀錄、失敗模式、協作與記憶分析 | 事件流、對話紀錄、工作區快照、帳本、失敗模式分類 | `~/.pland/eval_runs/*`；報告第 5–7 節 |
| 對中期、最終或其他批次分別執行 | `pland eval run midterm|final|<任意目錄>` | — |
| **§10 交付**：可執行的 repository、真實提交紀錄 | GitHub `victoryuanxichen/nlp_final_pland`，逐步提交 | `git log` |
| 系統架構說明（繁中） | [ARCHITECTURE.md](ARCHITECTURE.md) | — |
| 測試與效能報告（繁中） | [EVALUATION_REPORT.md](EVALUATION_REPORT.md) | — |
| **§11 閱讀 Hermes 並在決定架構前參考** | 閱讀官方 repository 與文件（Bot Mode、Profiles、Security、Delegation、Memory、Kanban、壓縮、技能…）；採用與差異見架構文件第 11 節 | — |
| **§12 不設置不必要的固定角色或流程** | 沒有預設 Bot；主導者依情境選出；協作是 Agent 的自主決策 | — |
