# 变更日志 / 过程记录（listed-company-analysis）

> 本文件收录 skill 演进过程中的**审计、补强、bug 修复与一次性验证数据**，供回溯用。
> 这些属于"历史过程"，已从 `SKILL.md` 主指令中剥离（规则已去日期并入 SKILL.md，参考细节见 `DATA_SOURCES.md`）。
> 验证数据（如某只股票跑通的实控人比例）会随标的过时，**不可作为通用结论引用**。

---

## 2026-10-19 — 数据源可靠性审计 + MCP 优先重构

早期各维度几乎全部依赖东方财富逆向 API、巨潮爬虫、Bing 网页搜索、问财聚合等不可靠源，导致"分析出来的内容有问题"。本日完成审计并重构为 MCP 优先架构（`data_source_registry.py` / `mcp_bridge.py` / `redline_gate.py`）。

**企查查（qcc-company）接入的衍生调整**：T+0 工商权威数据修补了审计中最弱两处——
1. 新增维度 `legal_risk`：由 `get_company_risk_scan`（35 项风险因子一键分诊）、`get_stock_pledge_info`、`get_equity_pledge_info`、`get_case_filing_info`、`get_judgment_debtor_info`、`get_dishonest_info`、`get_company_related_risk_scan` 组成，替代原 `cross_validator` 的"正则启发式+中文关键词"薄弱判定。
2. 新增维度 `intellectual_property`：`get_patent_info` / `get_trademark_info`。
3. `structure` 升级：`get_actual_controller`（实控人穿透）、`get_beneficial_owners`（UBO）、`executives` 新增 `get_key_personnel`。

**`legal_risk` / `intellectual_property` 端到端接线**（解析器 `scripts/qcc_dimensions.py`，链路 `dispatcher._dispatch_dim` → `mcp_bridge.load_mcp_results` → `report.py` 专章）：

| 项 | 说明 |
|---|---|
| `load_mcp_results` 多工具聚合（关键修复） | 旧版单值覆盖→同维度多工具互相覆盖只剩 1 个；现返回 `tools{tool:{result,error,fetched_at}}` 全量 |
| 诉讼角色拆分 | 立案 37 条≠37 起被诉；按当事人拆"被告/被上诉人(🔴真实被诉)" vs "原告/上诉人(🟢主动维权)" |
| 质押在押/已解除拆分 | 按状态拆"质押中"与"已解除"，按亿/万解析在押股数合计 |
| IP 法律状态分布 | "有 766 条专利"≠"有 766 项在权壁垒"；输出 `in_force_count` / `abandoned_or_terminated_count` |
| 工具截断口径警示 | qcc 带"已展示前 N 条"；解析器用 `_tool_truncated`/`_tool_total` 识别，严禁把展示条数当总量 |
| qcc AI 数据纪律 | 风险因子计数逐字引用、绝不跨维加总；scan 仅分诊→`needs_corroboration`；35 项全 0 措辞"结构化风险维度无在册记录，不等于无风险" |
| 单源不得实锤 | ≥2 独立信号才 `corroborated=True` |
| 缺口→红灯 | legal_risk 缺数据 ⛔ 不得出"合规干净/无重大诉讼处罚"；IP 缺数据 ⛔ 不得据专利商标做技术壁垒判断 |
| 未回填即显式缺口 | 无 qcc 回填时 `status='not_backfilled'`，渲染 🔴 缺口章节，绝不返回 `{}` 静默通过 |

**公告全文抽取：降级链与实测边界**：
四路降级链（前 3 路由 Python 自动，第 4 路需 Agent 回填）：① PDF 缓存 0.01s；② 巨潮直连+PyMuPDF 4 并发（主源，7.3s/条→并发提速 2.8×）；③ MCP MinerU 深解析；④ 东财/新浪 HTML。
性能实测：巨潮 PDF 下载 7.3s/条（占 99.8%），PyMuPDF 解析 15ms/条（比 pdfplumber 快 11.4×）。
🔴 MCP MinerU 时间边界：`download_announcement_parsing` 只覆盖近期公告（2026 命中 2/2，2020 命中 0/4），**不能替代自建 PDF 链路**，只作第 3 路兜底；`mcp_mineru_bridge` 只登记近期（≥2024-01-01）公告。
其他 MCP：`search_announcements` 002180 返回 1958 条；`get_announcement_detail` 只有元数据无正文；`download_announcement_pdf` 历史 PDF 也能下。

**数据源纪律（全量审计确立）**：① URL 一律 https（本机代理拦截 http）；② 核心维度必须多源+重试；③ 禁止静默吞异常（`silenced_errors.record_result()`）；④ 禁止硬编码绝对路径（用环境变量+相对路径）；⑤ 第三方接口字段位置必须实测+量级交叉验证；⑥ 批量改代码必须三件套（AST 校验+备份+试运行）。

---

## 2026-10-20 — 本质校准 + 事故防线

用户明确要求：头号交付物是**一篇通俗易懂的深度评论文章**，不是公告台账/时间线罗列；数据采集（36 维度、MCP、PDF 全文、三幕叙事）全部是论据底座。

由此确立：采集前 3 防线（标的校验/输出防覆盖/公司名实时解析）、数据引用 3 纪律（市值 PE 当日自取/peer_compare≠同业/总记录数默认历史累计/简称用实时值）、强制交付流程、行文顺序铁律（首次出现即交代）。

---

## 2026-10-21 — 三层架构 + 证据包 + Wind 升主力 + 基座 bug 修复

确立三层架构（基座→证据包→Agent 撰写），不另搭 LLM API。证据包新增第五/六/七件（赛道曝光/最新报告期台账/营收剧变归因）。

**Wind 升为主力源**：`MCP_STATUS['wind-finance']`→connected；9 维度把 Wind 工具置顶 `mcp_primary`，dzh 降入 `mcp_fallback`；`mcp_bridge` 新增 Wind 分支 + 4 个自然语言 question 构造函数。实测 688585.SH 返回与东财一致（价 112.90/PE -293.14/PB 38.69/总市值 455.4 亿）。

**Wind 港美股主力源 + dzh 六表接入**：新增 `to_wind_code()`（美股 `.O/.N/.A`，类别股 `BRK.B.N`）、`to_dzh_code()`；`hk_financial/hk_quote/hk_structure/us_financial/us_quote/us_structure` 六维度重写；新增 `MARKET_DIMS`+`get_dim_spec()`；`mcp_bridge` 新增 `apply_backfill()`/`wind_tabular_to_dicts()`+CLI `--apply`；`analyze.py` 新增第 22 步。实测 00700.HK 与 AAPL.O 行情；港股端到端 4m24s 跑通。

**已修复的基座 bug（填坑记录）**：

| Bug | 根因 | 修复 |
|---|---|---|
| `periodic_reports` 三份定期报告正文提取全失败 | `pdf_download.py` 调用从未定义的 `extract_sections`/`extract_text` → NameError 被吞 | 在 `pdf_download.py` 用 PyMuPDF 补上两函数 |
| 证据包只吃 2025 年报 | 写作层未贯通基座已采到的最新半年报/季报 | 新增「最新报告期台账」+赛道扩料 |
| 公告 `date` 整数型误判"过老" | 时间过滤用字符串比较，整数 `20260825` 字典序错判 | `_revenue_change_attribution` 加日期归一守卫 |
| 估值段台账市值/PS 取空（688585 暴露） | `valuation.current` 常 None → 台账全空 | 优先读 `f['quote']` 并自动算 PS(TTM) |
| 半年报下载崩溃（688585 暴露） | `from scripts.safe_request import safe_get` ModuleNotFoundError | 容错导入 |
| `announcements.py` 双运行上下文崩溃 | `from scripts.safe_request import ...` 函数内多处，cd scripts 直跑必崩 | 文件头注入 sys.modules |
| Wind 返回双层嵌套被当「一条记录」 | 旧 `wind_tabular_to_dicts` 只剥一层 data | 重写为递归展开 |
| 北交所代码迁移→全维度空 | 东财 2026 后接口只认 920 段；830799→0，920799→20 期 | 新增 `bse_migrate.py` 迁码 |
| BSE 官网年报接口失效 | `companyCd` 服务端忽略 | 新增 `_get_bse_annual_from_em()` |
| 美股财务"有数据但读不到" | `KEY_ITEMS` 5 个 US-GAAP tag 写错 + 下游读 `records` 为空 | `KEY_ITEMS` 改候选列表 + 新增 `us_records.py` |
| 非 A 股 peer/SOTP 返回假数据 | `peers=[自己]`→港美股 count=1；SOTP 吐 0 | `_is_a_share()` 守卫 + skipped |
| `scripts` 包名被 pywin32 抢占 | `site-packages\win32\scripts` 占住 `scripts` 名 | 新增 `_ctxfix.py` |
| 年报 PDF 落技能目录而非 `--output` | `save_dir` vs `output_dir` 探测错 | 探测 `save_dir` 优先 |
| 港美股/北交所总股本回落 A 股默认值→EPS 放大十倍 | `total_shares` 只取通达信（港美股空）→回落 12.5e8 | 取值链改 Wind→us_records→通达信→占位置 None |
| SOTP 无子公司返回 0 被读成"估值为 0" | `calculate_sotp` 无分部仍输出 0 | 无子公司时置 None + note |
| 盈利预测被 A 股老链路挡死 | 第 17 步只喂 `multi_year_trend`，北交所/港美股返空 | 通用兜底喂 `financial.records` |
| 港股年报 PDF 恒为空 `{}` | Playwright 无头返回空 | 新增 `fetch_hkex_annual_http()` 纯 HTTP 三跳 |
| 美股 10-K 恒返回 None | ticker 传给只接受 CIK 的接口 | 新增 `_resolve_cik()` + `get_us_10k_detail()` |
| 港股财务 `records` 恒 0 | `hk_financial` 无 `records` | 新增 `hk_records.py` |
| 港美股证据包「摘录 0 条」 | 摘录依赖 A 股 23 章节，港美股无 | `_excerpts_annual_by_keywords()` + `_excerpts_us_10k()` |
| 目标价"数据不足"误报 | 只读旧源 `earnings_forecast.target_price.average` | 两个来源都查 |
| 港美股监管维度「空且无说明」 | `regulatory.py` 只有 A 股东财通道 | 按市场分流 HKEXnews/SEC RSS |
| SEC 执法 RSS 覆盖极窄（局限非 bug） | 各只含最近约 25 条 | 显式声明窗口，未命中输出人工核验链接 |
| 机构股东被截断到 10 条 | `apply_backfill` `[:10]` | 不截断，全量写入 + `institutional_holder_count` |
| 主营收入构成没解析 | Wind 字符串未结构化 | 解析成 `income_structure=[{name,ratio_pct}]` |
| 回填缺失被当成"没有数据" | 未回填为空且无说明 | 新增回填门禁 `_mcp_backfill` |
| 年报附注抽取把表格行当章节 | 行长判标题误判 | 章节候选评分 + 黑名单 |
| 10-K 附注抽取永远"无命中" | 依赖证据包阶段下载的缓存，analyze 早于证据包 | 抽取器自己现下并写缓存 |
| 同业名单只有"白酒"能出来 | `PEER_MAP` 写死仅白酒 | 新增 `peer_discovery.py` 三段流水线 |

**代码↔文档对齐记录（实跑 688585 后订正）**：
1. 真实 CLI 仅 `analyze.py <stock> [--market a|hk|us|bse] [--output DIR]`；**不存在** `--full`/`--dims`/`--expect`/`--name`/`--force`，当前默认即全维度采集（24+ 维度，results.json≈2.9MB）。标的校验/维度选择/名称交叉验证靠 `get_company_name()` 实时简称+跑前人工核对。
2. 年报 PDF 落点不一致（落在 `scripts/output/` 而非 `--output`），临时 `cp` 规避待修。
3. `valuation.current` 实测为 None，市值/PS/PB 全来自 `quote`；`check_numbers.py` G 组不对市值/PS/PB 做槽位校验。
4. `md2article.py` 当前不在 `scripts/`。
5. 北交所正式开关已加 argparse `choices`，内部归一化 `bse→'a'`，`results.json` 标记真实 `market='bse'`；美股公告仍 SKIP。

---

## 2026-10-22 — 依赖与打包审计 + P0+P1 补强 + 同业发现

**依赖与打包审计**：skill 自身不内嵌 MCP server，须运行在已连接 4 个连接器的 WorkBuddy；修了两处写死路径（`thsdk_provider` 的 `I:\`、`tmp_paths` 的往上 4 级 `tmp/manager.py`）、补全 `requirements.txt`（`beautifulsoup4`/`httpx`，修正不存在的 `pandas==3.0.2`）、凭据进 `.gitignore`。打包用 `git archive`，新增 `DEPENDENCIES.md` 与 `package_skill.py`（"同步到龙头计划里"= 覆盖 `项目库\龙头计划\listed-company-analysis.zip`）。

**P0+P1 补强：股权穿透 / 质押 / 高管 / 财务红旗**（实测标的 688585 上纬新材）：

| 维度 | 改动 | 实测 |
|---|---|---|
| 股权穿透 | `apply_backfill` 新增 5c 段，合并 `get_actual_controller`/`get_beneficial_owners`/`get_external_investments` → `findings['structure']['qcc_penetration']` | 实控人 **邓泰华 38.6783%**，逐字引用不重算 |
| 质押 | 注册 `pledge` 维度（A股/北交所）；`apply_backfill` 新增 5.5 段合并 `get_stock_pledge_info` | **无在册质押**（qcc 返回"未发现记录"→`no_record`） |
| 高管 | 第 7 段从"只标 _gap"改为合并 `get_key_personnel`/`getF10GsjsData` → `findings['executives']['mcp_detail']` | **10 名主要人员**（彭志辉董事长等） |
| 行业背书 | `industry` 合并 Wind `get_stock_basicinfo`；`peer_discovery` 加 `--industry` | 行业=基础化工–合成树脂；主营构成清晰 |
| 财务红旗 | 新增 `scripts/redflag.py`（纯本地）；`analyze.py` 第 22.5 步调用 | 6 类红旗 + 本福定律/关联交易标 data_gap |

**同业名单发现 `peer_discovery.py`**：年报确实写了竞争对手但口径很脏——830799 命中 9 次"竞争" 100% 自述零对手名；688585 点名"欧林"但同页还列客户/合作方。真实原因不是取不到而是分不清（对手/客户/供应商混写、称谓不统一、同名歧义"欧林"=OLN 也=A 股 688319）。三段流水线：A Python 切窗 → B Agent 判语义 → C Python 反查代码+取数。

**`--inject` 外部注入通路**：年报零对手时可交 Agent 给名单，但须配四道守卫（代码归一必达/近名碰撞≥0.6/ST退市警示/亏损+规模离散）。实测 Agent 提 12 家银行 IT 对手 11 家能反查代码，但"查得到代码"不构成验证。注入名单法律边界：年报点名可写"公司披露的主要竞争对手"；Agent 指定只能写"我们按细分赛道选取的可比公司"且 `rationale` 必填。

**仍无法程序化的最后一关：行业同业性**——脚本侧无稳定行业源，必须人工或 Agent 调 Wind `get_stock_basicinfo` 背书。

---

## 2026-10-23 — 港美股质押维度 + redflag 多市场阈值

**港美股股权质押维度补齐（诚实标 gap，不假装覆盖）**：
- `data_source_registry.py` 新增 `hk_pledge`/`us_pledge` 维度，`mcp_primary` 留空（企查查只覆盖 A股/北交所，港美股无 qcc 质押数据）；`MARKET_DIMS['hk']`/`['us']` 纳入。
- `mcp_bridge.apply_backfill` 5.5 段 `_pick_slot` 扩展为 `('pledge','hk_pledge','us_pledge')`，港美股质押自动标 `findings['pledge']['_mcp']={'status':'gap'}` 并注明须官方源（港股披露易「股份抵押」/美股 SEC 13D/13G/Form 4）；A股无质押源时维持静默不误标。

**redflag 接多市场阈值（避免港美股误报）**：
- `scripts/redflag.py` `scan_redflags(records, opts)` 新增 `market` 参数：A股/北交所严口径（营收同比±50%、毛利率>80%、毛利率跳变>20pct、负债率骤升>15pct）；港股/美股放宽（营收±80%、毛利率>90% 仅提示且措辞改"港股/美股高毛利行业常见"、跳变>25pct、负债率骤升>20pct）。
- `analyze.py` 22.5 步调用改为 `scan_redflags(_recs, {'market': orig_market})`。

**验证**：合成样本确认 A股营收+60%报异常而港股同样本不报；港股毛利率92%报 high 且措辞含"港股/美股"；apply_backfill 港股/美股质押自动标 gap、A股静默。

**年报 PDF 表格 None 噪音修复（全景报告可读性，2026-10-23）**：用户反馈 `report.html` 排版无法阅读、列表大量 `None`（300168 实测 1401 处）。根因：年报 PDF 表格抽取（pandas→markdown）把多行压进一格（如 `None 应收账款 合同资产…`）、数字被换行截断（`1,251,609,572.4` + `6 320,…`）、空值直接渲染为 `None`；`report.py` 的 `_section_annual_pdf` 对 `content` 直接 `append` 未清洗。修复：① `report.py` 新增 `_clean_md_tables()` / `_clean_table_block()`——合并表格续行（续行以数字开头且上行以数字结尾时**直接黏合**以还原被截断的数字）、格内 `None/NaN/null` 做 token 级删除（正则前后加 `(?<![A-Za-z0-9_])` 边界，避免误伤单词）、**单格 ≥3 个数字串或有效列 >12 的「行列错位表」隐藏并提示查年报原文**、其余去全空行列 + 超宽单元格截断 + 长表截断加注；② `report_html._render_table` 的 `parse_row` 增加 `None/NaN/null → ''` 兜底。效果：300168 全景报告 `None` **1401 → 0**，25 张错位表隐藏并标注「未结构化，请查原文」，18 张可读表保留（HTML 均包在 `.table-wrapper` 内横向滚动）；23 个年报小节内容完整性校验全部 OK。

**财务预测三处逻辑 bug（2026-10-23 实测 300168 发现并修复）**：
1. **`latest_rev` 取到最旧年**：`financial_projection.py` 对 `annual` 未排序，而东财 `records` 是**降序**（最新在前）→ `annual[-5:]` 取到的是**最旧 5 期**、`latest_rev = hist_revenue[-1]` 取到**最旧年**（2021 年 35.13 亿，实际 2025 年 20.26 亿），导致 CAGR 与三年预测方向全反（营收连降四年被算成正增长）。修复：`annual.sort(key=DATAYEAR/REPORTDATE)`，扁平格式分支 `fy.sort()` 同步。
2. **单位重复除 1e8**：`historical.revenue_yi = [round(r/1e8,2) for r in hist_revenue]`，但 `hist_revenue` 进入函数时已 `/1e8`（亿元）→ 历史序列全为 0.0。修复：直接 `round(r,2)`（`net_income_yi` 同）。
3. **负 EPS 目标价为负**：`target_price = eps[-1] * pe_target` 在亏损公司恒为负（实测 -10.8 元）。修复：`eps[-1] < 0` 时 `target_price=None` 并写 `target_price_note`（提示改用 PS/PB/EV-Sales）。

验证（300168）：`latest_rev=20.26`、`hist_revenue=[35.13,32.24,24.59,20.11,20.26]`、`CAGR 3y/5y=-14.3%/-12.9%`、`EPS=[-0.57,-0.58,-0.60]`、`target_price=null + note`。

**全景报告三项可用性修复（2026-10-23 用户反馈后）**：
1. **`No module named 'scripts.financials'`**：`report.py` 顶部在 `import scripts` 失败时注册指向 `scripts/` 的伪包，`_call_module_section` 的 `importlib` 失败时回退裸模块名；`product_line_intro` 章节改用 `spec_from_file_location` **按文件路径加载**（绕过运行时包名解析差异）。
2. **前五名客户/供应商改为规范表格**：新增 `_parse_top5()` 解析 PDF 竖排文本（序号/名称/金额/占比 各一行 → 4 行一组），输出 `| 序号 | 名称 | 金额 | 占比 |` + 合计行。实测 300168：客户合计 3.776 亿 / 18.63%、供应商合计 9350 万 / 6.61%，数值正确。
3. **未还原表不再只给「已隐藏」**：源 PDF 无清晰框线 → pdfplumber 把多行并进一格，**列边界客观上不可还原**；改为保留**原文数据行**（`- 单元格 · 单元格`，最多 24 行）供阅读，并明示「PDF 行列结构未能还原」，能解析的表（前五名/费用）解析成表。另：`<td>None</td>` 兜底此前误落在 `_generate_warnings`，已移到 `generate_report` 写盘前。

效果（300168）：`No module named` **0**、`生成失败` **0**、`None` **0**；前五名客户/供应商为规范表（含合计）；15 张不可还原表以数据行呈现。

**PDF 错位表的视觉重建（截图 → 读图 → 重建表格，2026-10-23）**：对 pdfplumber 无法还原列边界的表格（源 PDF 无清晰框线），改用 `fitz` 按标注页码渲染 PNG（180 DPI）→ 人/AI 读图理解行列 → 逐行重建 markdown → 写入 `findings['annual_pdf']['_visual_tables']`；`report.py` 的 `_section_annual_pdf` **优先采用 `_visual_tables[key]`**（跳过文本清洗与降级），成为可复用机制（任何公司只需产出该字典）。本次重建 5 章 / 7 张表：
- `dividend`：资产构成重大变动（13 行，含短期借款占比 22.60%→35.90% 的债务短期化提示）+ 以公允价值计量资产；
- `production_sales`：营业收入和营业成本（主营毛利率仅 3.6%）+ 收入分解（软件 43.4%/运营 31.6%/集成 24.9%）；
- `rd_spending`：研发费用（2.83 亿，-10.2%）/销售费用（0.94 亿，-24.5%）/财务费用（0.56 亿）；
- `capacity`：重要联营企业财务信息（上海浦江/武威天马/国菱金达，软件企业无产能表）；
- `top10_shareholders`：Wind 十大股东（国寿两账户合计 20.35%）。

效果：300168 报告「行列结构未能还原」由 **15 → 0**，全部为规范表格。截图存 `output/300168_20261023/_pdf_pages/`（15 张 180DPI PNG），重建脚本 `_apply_visual.py`。

**报告可读性第二轮（2026-10-23，用户反馈"好多还是不行"）**：体检发现 6.6 万字报告中大量是 **PDF 原文逐行碎片**（实际控制人 608 行/3033 字、重大诉讼 723 行、担保 505 行、在建工程 426 行、主要控股参股 414 行）+ AI 全景叙事 1.75 万字 + 重复章节 + 内容错误。修复八项：
1. **碎片章节降级**：平均行长 <15 字且 >60 行的 PDF 原文不再铺正文，只给「本章为年报原文逐行碎片（N 行），见年报第 X 页」（top5 白名单除外，仍解析成表）；
2. **去重** `litigation_detail`（与 `litigation` 内容重复）；
3. **AI 全景叙事**截断至 1500 字；
4. **补 8 张结构化内容**：诉讼汇总（原告已决 1.47 亿/未决 1.10 亿、被告已决 1.30 亿/未决 0.46 亿）、担保（无违规）、在建工程、实控人+董事、审计意见、商誉明细（9.74 亿=复高 5.11+金唐 4.21）、长期股权投资、p48 子公司表（12 家 + 处置 5 家）；
5. **审计意见不得由财务指标推断**：原 `_infer_audit_opinion` 按"EPS<0 且 ROE<0 → 非标准无保留意见"推断，把**标准无保留**的 300168 误标成非标——改为返回 None，上层用年报真实值或标"未取到"，禁止编造；
6. **估值回退**：SOTP 不成立（market_cap=0）时回退行情快照（股价/市值/PE/PB），消除"暂无行情数据"；
7. **产品章节去重**：dims 循环跳过 `product_line_intro`（已在正文前专门渲染）；
8. **占位符清理**：行情表 `?` / `❓` → 「—」。

效果（300168）：碎片指引 **6 → 0**、`None` **0**、审计误判 **0**、`暂无行情数据` **0**、产品章节 **1 次**、生成失败 **0**；总字数 6.6 万 → 5.0 万（新增结构化表后）。
