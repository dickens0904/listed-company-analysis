# listed-company-analysis · 依赖与打包清单（2026-10-22 审计）

> 目的：确保本 skill 打包复制到另一台装有 WorkBuddy 的电脑后，能正确声明依赖、不泄露凭据、不在 import 阶段崩溃。
> 本文件由 `listed-company-analysis` 维护。改依赖务必同步改 `requirements.txt` / `setup.py` / `.gitignore` / SKILL.md 的「依赖与打包须知」章节。

---

## 一、🔌 MCP 连接器依赖（最关键，本机不内嵌）

本 skill **自身不调用 MCP server**。它的工作方式是：
1. `analyze.py` 第 23 步用 `mcp_bridge.build_mcp_plan()` 生成 `data/mcp_plan.json`（含数十个调用）；
2. **由宿主 WorkBuddy 的 Agent 按 plan 调对应 MCP 连接器**，结果落 `data/mcp_data/*.json`；
3. `apply_backfill()` 把结果合并进 `findings`。

因此：目标机器上的 WorkBuddy **必须已连接并授权以下 4 个 MCP 连接器**，否则 `apply_backfill` 只会产生缺口（分析仍跑，但财务/股东/质押/穿透/高管/公告/K线/估值等"T1/T0"数据缺失）。

| 连接器 (server) | 角色 | 典型工具 | 缺失后果 |
|---|---|---|---|
| `wind-finance` | 主力源（A/港/美） | get_stock_fundamentals / get_stock_equity_holders / get_stock_basicinfo / get_stock_kline / get_stock_price_indicators / get_company_announcements | 三表、机构股东、行业、K线、估值全缺 |
| `dzh-mcp` | T1 备选（大智慧） | getF10HolderDetailsData / getF10GsjsData / getStockCorpProfit / getQuoteDyna / getQuoteKline | Wind 缺项时无兜底 |
| `qcc-company` | 工商/股权穿透 | get_actual_controller / get_beneficial_owners / get_key_personnel / get_stock_pledge_info / get_equity_pledge_info | 实控人穿透、UBO、高管、质押缺失 |
| `alphapai-lite-mcp` | 公告解析+MinerU+IR | search_announcements / download_announcement_parsing(MinerU) / recall_knowledge(roadShow_ir) / query_financial_data | 公告全文抽取、IR 路演、自然语言财务查询失效 |

🔴 **MinerU 不是独立服务**，是 `alphapai-lite-mcp.download_announcement_parsing` 工具（由该连接器负责），无需本机安装。
🔴 `data_source_registry.py` 中 `'wind-finance': 'connected'` 等是**静态文档标记，无运行时连通性探测**；目标机若未连接，代码不会报错、只产生数据缺口。

---

## 二、📦 Python 包依赖（pip）

### 必需（代码真实 import）
| 包 | 用途 | 备注 |
|---|---|---|
| `requests` | HTTP 抓取 | 多文件 |
| `pandas` | 表格处理（仅 hk_financial 等少数） | ⚠️ 原 `requirements.txt` 写 `pandas==3.0.2`（不存在），已改为 `pandas>=2.0,<3` |
| `PyMuPDF` (import 名 `fitz`) | PDF 全文提取 | 多文件 |
| `pdfplumber` | PDF 表格 | annual_report_extractor / related_deals |
| `PyPDF2` | PDF 备选 | announcements |
| `akshare` | CSRC/港股等兜底数据 | 体量大，建议装 |
| `openai` | AI 分析师（SenseNova 客户端） | ai_*.py / llm_config |
| `beautifulsoup4` (import 名 `bs4`) | HTML 解析 | ⚠️ **原声明遗漏，已补** |
| `httpx` | mx_data_provider 用 | ⚠️ **原声明遗漏，已补** |
| `matplotlib` | 结构图 | 可选 |

### 可选 / 外部二进制（非必需，缺则降级）
| 包 / 程序 | 用途 | 缺失后果 |
|---|---|---|
| `cloakbrowser` | gsxt_crawler 反检测浏览器 | gsxt 工商爬虫不可用（已 try 降级） |
| `playwright` + `playwright-stealth` | hkex_announcements / gsxt_crawler | 港股公告、工商爬虫不可用（已 try 降级） |
| `thsdk`（同花顺 SDK，私有包非 PyPI） | thsdk_provider | ⚠️ 路径写死 `I:\QClaw\...`，非主流程；已改为读 `THSDK_PATH` 环境变量+路径存在才插入 |
| 通达信(TDX) 客户端 | tdx_provider | analyze 第 0 步已 try 包裹，缺则跳过 |
| `tushare` | 旧兜底源 | 需 `TUSHARE_TOKEN` |

### 声明文件差异（已对齐）
- `requirements.txt` 与 `setup.py` 此前不一致：requirements 有 openai/cloakbrowser/playwright，setup 没有；pandas 版本号错误。已统一。
- `setup.py` 的 `python_requires='>=3.8'`；本机实际用 Python 3.14 跑通（f-string / typing 均兼容）。

---

## 三、🔑 环境变量 / 凭据（目标机必须重设，禁止打包带走）

| 变量 | 说明 | 获取方式 | 是否机密 |
|---|---|---|---|
| `TUSHARE_TOKEN` | Tushare 兜底数据 | 环境变量 **或** skill 根 `.tushare_token` 文件 | 是 |
| `EM_API_KEY` | 东方财富 AI SaaS | 环境变量 **或** skill 根 `.em_api_key` 文件 | 是 |
| `SENSENOVA_API_KEY` | SenseNova LLM（AI 分析师） | 环境变量 | 是 |
| `THSDK_PATH` | 同花顺 SDK 路径覆盖（可选） | 环境变量 | 否 |
| `LLM_SYNC` | 设 `1` 时阻塞等 WorkBuddy IPC 回写 | 环境变量 | 否 |

🔴 **打包纪律**：
- `.tushare_token` 已在 `.gitignore`（git 归档不会带出）；`.em_api_key` 也已加入 `.gitignore`。
- 若用「文件夹整体复制 / zip」打包，**务必手动剔除** `.tushare_token` 与 `.em_api_key`，否则凭据泄露。
- 推荐打包方式：`git archive --format=zip HEAD > lca.zip`（自动尊重 .gitignore）。

---

## 四、🧩 内部模块依赖 / 运行上下文

- **模块互相引用用 `from scripts.xxx import ...`**（200+ 处）。Windows 上 pywin32 的 `win32\scripts` 会与本 skill 的 `scripts` 包名冲突，已由 `_ctxfix.py` 垫片在 `import scripts` 时纠正。
  🔴 **正确运行方式**：从 skill 根目录执行 `python scripts/analyze.py <code>`，**不要** `cd scripts && python -c "..."`。
- `tmp_paths.py` 原本从 skill 根「往上 4 级」找宿主的 `tmp/manager.py`（≈ `~/.workbuddy/tmp/manager.py`），打包到其他机器找不到会 `ImportError`。已加**本地兜底**：找不到时改用 skill 根 `.tmp/` 作缓存目录，import 不再崩溃（仅 peer_discovery 等用到 `PDF_CACHE_DIR` 的功能受影响，自动走本地缓存）。
- `llm_config.py` 的 AI 分析走两种后端：① `SENSENOVA_API_KEY` 直连；② 无 key 时写 `output/_llm_requests.jsonl` 等 WorkBuddy 助手回写（**依赖 WorkBuddy 运行时的助手回路**，纯裸机无此机制会降级为"无 AI 润色"）。

---

## 五、📋 打包检查清单（复制到新机前逐项核对）

- [ ] 目标 WorkBuddy 已连接并授权 4 个 MCP：`wind-finance` / `dzh-mcp` / `qcc-company` / `alphapai-lite-mcp`
- [ ] `pip install -r requirements.txt`（含已补的 beautifulsoup4 / httpx，pandas 版本已修正）
- [ ] 设置 `TUSHARE_TOKEN` / `EM_API_KEY` / `SENSENOVA_API_KEY`（按需）
- [ ] 用 `git archive` 打包，确认 `.tushare_token` / `.em_api_key` / `output/` / `__pycache__/` 不在包内
- [ ] 运行 `python scripts/analyze.py <code>`（从 skill 根目录，非 cd scripts）
- [ ] 若用 thsdk：设 `THSDK_PATH` 指向目标机的同花顺 SDK site-packages
- [ ] 可选：浏览器类功能需 `playwright install chromium`
