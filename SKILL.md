---
{}

---

# 上市公司深度评论引擎（listed-company-analysis）

> **本质**：头号交付物是**一篇通俗易懂的深度评论文章**——用专业判断把年报、公告、投资者关系里的事实，讲成「这家公司发生了什么、为什么、现在值多少、风险在哪」。
> 🔴 **不是公告台账。不是时间线罗列。不是「XX 份公告佐证」的堆砌。** 数据采集（36 维度、MCP、PDF 全文、三幕叙事）全部是**论据底座**，服务于文章观点；正文里一个数字都不该是"为了证明我查得多"，而应是"为了支撑这个判断"。

**配套文档**：数据源调用细节见 `DATA_SOURCES.md`；审计/补强/bug 历史见 `CHANGELOG.md`；打包与 MCP 环境清单见 `DEPENDENCIES.md`。

---

## 🔌 依赖与打包须知（MCP / 环境）

本 skill **不内嵌任何 MCP server**，必须运行在已连接 4 个 MCP 连接器的 WorkBuddy 中（详见 `DEPENDENCIES.md`）。要点：

1. **必备 MCP 连接器（目标机须已连接+授权）**：`wind-finance`（主力）/`dzh-mcp`（备选）/`qcc-company`（工商穿透）/`alphapai-lite-mcp`（公告+MinerU+IR）。缺任一，`apply_backfill` 只产生数据缺口不报错。
2. **pip 依赖**：`requirements.txt` 已对齐真实 import（`beautifulsoup4`/`httpx`/`pandas>=2.0,<3` 等）。
3. **凭据**：`TUSHARE_TOKEN`/`EM_API_KEY`/`SENSENOVA_API_KEY` 用环境变量或 skill 根 `.tushare_token`/`.em_api_key` 文件（已进 `.gitignore`，`git archive` 打包不带密）。
4. **运行方式**：从 skill 根目录 `python scripts/analyze.py <code>`，勿 `cd scripts` 后跑（`_ctxfix.py` 已处理 pywin32 `scripts` 包名冲突）。
5. **环境铁律**：跑 `analyze.py`/`dispatcher` 须用 `C:/Python314/python.exe`（托管 Python 3.13 未装 `requests`）；纯解析模块（`qcc_dimensions`/`joint_action_narrative`/`mcp_bridge`）托管 Python 可跑。
6. **写死路径地雷已修**：`thsdk_provider` 的 `I:\` 改为读 `THSDK_PATH`+存在才插入；`tmp_paths.py` 缺失时回退 skill 本地 `.tmp/`，import 不再崩。

---

## 🔴 铁律汇总（执行前必读）

### 采集前 3 防线
| 防线 | 规则 | 防什么 |
|---|---|---|
| ① 标的校验 | `analyze.py <code>`（跑前**人工核对代码↔简称**） | 凭印象填错代码（曾把法狮龙填成 603001 白跑） |
| ② 输出防覆盖 | 目标目录已有时**换新目录，勿覆盖** | 同目录重复跑覆盖既有成果 |
| ③ 公司名实时解析 | `get_company_name()` 取实时简称，禁止写死旧名 | 002180 已更名「奔图科技」，写死「纳思达」全链路用错名 |

> 当前 CLI **无** `--expect`/`--name`/`--force` 开关，"只给代码"场景靠 `get_company_name()` 实时简称 + 跑前人工核对兜底。同名/多代码易混标的（如法狮龙 605318 曾被误填 603001）务必先核代码再跑。

### 数据引用 4 纪律
1. **市值/PE/PB/PS 必须当日自取，禁止引用二手资料**（自媒体时点市值常差数倍）。工具：`python scripts/peer_snapshot.py <code...>`（自动提示市值排序 vs 营收排序是否背离）。
2. **`peer_compare` 维度是申万/证监会大类，不等于同业**——写行业对比必须自己指定同细分赛道可比公司，不用 peer_compare 均值做论据。
3. **凡是"总记录数"默认视为历史累计**，在册数要另取明细工具（股权质押"总记录 46 条"里在押仅 7 条）。
4. **公司简称一律用实时值，禁止凭记忆写**（奥普科技 603551 已于 2024-06 由"奥普家居"更名；联翔股份 603272 现简称已 `*ST联翔`）。

### 多层持股必须自己算穿透
公告只平铺单层比例（"顾望金华：法狮龙 60%、屹华科创 40%"），读者要的是"上市公司到底占多少"——必须**逐层相乘**并把关联方每层份额**加总**。规律：上市公司出钱、关联方持股反而更高，这类结构只穿透才发现。写作纪律：讲不对称必须同时写对冲安排，只讲一半=选择性叙述。

### 没有投资者关系记录表时怎么办（替代源优先级）
1. 《对外投资设立子公司/增资》公告（新业务官方口径+股权结构）
2. 年报「经营情况讨论与分析」（新业务进展+财务口径）
3. 上证 e 互动/深交所互动易 投资者问答（管理层被追问原话，比公告真实；⚠️ 无 MCP 接口，需人工或 WebSearch，脚注标注来源与日期，区分"公司答复"与"你的解读"）
4. 业绩说明会记录、机构调研纪要

### 三条线必须同时扫（缺一即漏关键内容）
| 维度 | 扫什么 | 漏了会怎样 |
|---|---|---|
| **经营** | 营收/利润/毛利/现金流、分业务拆解 | 只会讲"这公司亏了多少钱" |
| **业务** | 新客户/新产品/新赛道/技术对标 | 漏掉市场真正在买的（实例：漏"芯片供货宇树"） |
| **资本** | 分拆/买壳/再融资/控制权/更名 | 漏掉改变估值方法的大事（实例：漏"港股买壳+子公司分拆 IPO"） |

> 业务线金矿在 **IR 记录**；资本线金矿在 **公告标题关键词全扫**（分拆/借壳/要约/再融资/更名/境外上市），且 **A 股没公告≠没发生**（子公司动作可能只在港股披露或 IR 问答）。

### 交付形态铁律（最高优先级）
| 项 | 要求 |
|---|---|
| **形态** | 一篇 2000–3500 字评论文章（Markdown + 杂志风 HTML 双份） |
| **禁止** | 公告逐条列举、事件清单表格、「N 份公告佐证」、按日期排流水账 |
| **必须** | 有明确观点与结论、有因果链、有可验证数字、说人话 |
| **数字使用** | 每个数字都要为观点服务；不服务的数字删掉 |
| **专业度** | 术语要用但要解释（如"商誉"→"多付的那部分钱"） |
| **结构** | 结论先行 → 这家公司是干什么的 → 关键转折 → 现在的账 → 风险 → 估值 → 一句话判断 |

**文章骨架（推荐）**：标题（有信息量）→ 导语（3 行说清讲什么/结论）→ 一、这家公司是干什么的 → 二、决定性的一件事 → 三、现在的账 → 四、悬着的问题 → 五、怎么估值 → 六、我的判断 → 数据来源（一行标口径）。

**反面清单（见到即返工）**：❌「2020-03-02 收购某某·已完成交割（88 份公告佐证）」；❌ 一整页表格列 20 条公告标题；❌「本报告覆盖 37 个维度、1478 条公告」；❌ 每段都以「根据公告」「据披露」开头。✅「2023 年公司亏了 61.85 亿——当年 A 股最惨亏损之一」。

### 行文顺序铁律：首次出现即交代
读者从上往下读，第一次遇到某份文件/简称就必须知道它是什么。三类必须首次交代：
- **泛指文件词**（预案/报告书/草案/说明书）：首次给《文件名》+披露日期
- **英文缩写/技术对标**：首次给中文全称或用途（德州仪器 TI、DSP 数字信号处理器）
- **公司简称**：首次给身份关系（旗下芯片公司极海微、控股股东赛纳科技）

补充：时间跳转要标出来（讲 2016 整合却引 2025 文件，须用"这一点在…才被说透"体现先后）；估值倍数要交代分母口径（剥离类公司 PS 差一倍）；引号只用于原文引用，强调一律用加粗。程序化门禁：`article_checklist.py` 的 **H 组**校验"泛指文件词首现是否带《》或日期"。

### P0+P1 铁律（股权穿透/质押/高管/财务红旗）
1. **qcc `searchKey` 必须精确全称或 USCC**：简称被拒，须用全称或 USCC；`build_mcp_plan` 已自动前置 `get_company_by_query` 解析填 `__USCC__` 占位。
2. **qcc 聚合终值逐字引用**：实控人/UBO 持股比例禁止用各层相乘重构（AI 多位小数乘法不可靠）。
3. **质押"无记录"≠缺口**：qcc 返回"未发现任何记录"应标 `no_record`，写"全量扫描无在册质押"，不写"未核查"。
4. **红旗不替代人工 + 多市场阈值**：`redflag` 只报数字异常+核查方向，不给定罪结论；本福定律/关联交易需附注级明细，本地 records 不提供→显式 data_gap。阈值按市场分：A股/北交所严口径（营收同比±50%、毛利率>80% 报异常），港股/美股成长·高毛利行业常见故放宽（营收±80%、毛利率>90% 仅提示），避免误报。
5. **港美股质押=显式 gap**：企查查不覆盖港美股，自动标 `gap` 并注明须官方源（港股披露易/美股 SEC）；不得写"无质押"或套用 A股 qcc 逻辑。

### 数据源纪律（兜底）
1. URL 一律 https（本机代理拦截 http）；2. 核心维度必须多源+重试；3. 禁止静默吞异常（`silenced_errors.record_result()` 登记）；4. 禁止硬编码绝对路径（用环境变量+相对路径）；5. 第三方接口字段位置必须实测+量级交叉验证；6. 批量改代码必须三件套（AST 校验+备份+试运行）。

### 收口红线门禁（`redline_gate.py`）
核心维度失败/数据不足时（A股：`financial`/`structure`/`quote`/`valuation`）：报告顶部强制插入 🔴 红灯章节（列缺口+MCP 补齐路径）；**跳过 AI 投资建议/目标价/评级**；溯源表对应维度标 ❌。两条硬纪律：**缺口不得写成结论**、**路由严格锚定+异常即停**。

### Agent 撰写层纪律
- 凡数值必须回查 evidence_pack 的「数字台账/原文摘录」引用，不得凭记忆写。
- 凡「已知缺口」清单内维度，**禁止编造**——只写已公告事实或显式标注"该维度本次未取到"。
- 同一证据包可出多篇文章（长评/短评/特定角度），骨架复用、素材全量开放。
- 写完后必须跑校验层；I 组「缺口守门」自动核对文章是否编造了缺口清单里的维度。

---

## 🧱 三层架构：基座 → 证据包 → Agent 撰写

```
① 采集层（基座）  analyze.py <stock> [--market a|hk|us|bse] [--output DIR]  → 全维度 results.json（默认即全维度）
                   ├ 第22步 原文深挖：年报附注抽取（关联交易/商誉/诉讼/担保）+ 美股 SEC 8-K/DEF 14A 清单
                   └ 第23步 自动落 data/mcp_plan.json（按市场取 MARKET_DIMS，Wind 主力源计划）
② 证据包层        article_brief.py <data_dir>               → evidence_pack（Agent 可读、可溯源、全量开放）
③ Agent 撰写层   本会话直接读取 evidence_pack 生成文章        → 不另搭 LLM API，由本会话 Agent 按纪律写
④ 校验层         article_checklist.py <data> --article <md> → 45+ 项硬门禁（含 I 组缺口守门）
⓪ MCP 回填（贯穿） Agent 按 mcp_plan.json 调 Wind/dzh/qcc → save_mcp_result → mcp_bridge.py --apply 合并
```

🔴 **基座必须保留**（底层全维度扫描＝基座，在基座上生成深度评论）。🔴 **第三层不另搭 LLM API**（生成器就是本会话 Agent 本身）。证据包**降噪不降维**——保留 7 节拍叙事骨架，把底层素材原样摊开（原文摘录+页码 / 数字台账带口径 / 最新报告期台账 / 实体索引 / 赛道曝光 / 营收剧变归因 / 已知缺口），杜绝"信息黑洞"导致编造。

**证据包关键件**：
- **赛道曝光信号层**：扫描统一语料池（年报+半年报+季报+公告+IR+权益变动）按新质生产力赛道聚合领域名词出现次数+代表原文句+出处；🔴 只聚合不判断（绝不贴"新质生产力"等价值标签）。
- **最新报告期台账**：自动取数据源 `REPORTDATE` 最大的报告期。🔴 累计口径铁律：A 股中报/三季报营收净利是"年初至报告期末累计"非单季，直接年化会翻倍，呈现一律用累计值。TTM=最近完整年报−上年同期累计+本期累计；全年预测=本期累计×(上年全年/上年同期累计)，显式标注"非承诺"。
- **营收剧变归因托底**：最新报告期营收同比 |Δ|≥25% 自动触发，扫 MD&A 抠归因句（合并范围变更/处置子公司/会计口径变更），只列证据不下结论，找不到明确归因→显式缺口。

---

## 🔴 强制交付流程（不可跳步）

```
① 采集    analyze.py <stock> [--output DIR]  → 全维度数据（默认即全维度，无 --full）
② 证据包  article_brief.py <data_dir>        → evidence_pack.json + .md
②b 定位   pdf_grep.py <pdf> <关键词>         → 5000 字预览取不到的章节
②c 同业   peer_snapshot.py <代码...>          → 当日市值/估值+年报财务对照表
②c-0 发现 peer_discovery.py --code X --stage A|B|C   ← 名单从年报里挖（见下）
②c-1 注入 peer_discovery.py --code X --inject f.json ← 年报没写对手时兜底（四道守卫）
③ 撰写    Agent 读取 evidence_pack 写 2000–3500 字
④ 回归    test_regex_guards.py               → 13 项解析坑回归（改代码后必跑）
⑤ 检查    article_checklist.py <data> --article <md>  ← 🔴 45+ 项硬门禁（含 I 组缺口守门）
⑥ 排版    Agent 生成 HTML 或 present_files 交付 .md
⑦ 交付    present_files
```

> 运行时用带 PyMuPDF 的 venv：`C:/Python314/python.exe scripts/article_brief.py <data_dir>`，否则页码提取降级（留空注明"需 PyMuPDF"）。

**第 ⑤ 步 `article_checklist.py` 是硬门禁**（45 项，FAIL 未清零不得交付）：

| 组 | 查什么 | 为什么 |
|---|---|---|
| **A 决策动因** | 重大交易是否取「背景和目的」、有无标的财务数据、对价口径 | 只写"卖了"不写"为什么卖"=财复试述 |
| **B 业务亮点** | IR 记录有无点名客户/产品型号/体外资产（无则降级扫投资/年报类公告） | 财报看不见、市场最关心；IR 全市场 0 份时不降级=放弃检查 |
| **C 资本运作** | 分拆/买壳/再融资/更名是否扫到 | 改变的是估值方法 |
| **D 数字口径** | 商誉期初期末、质押在册vs累计、DCF 回退默认、MA 评分矛盾、关联占比臆造 | 实测踩过的坑，防改代码回退 |
| **E 文章覆盖度** | 数据里有的实体文章里有没有写 | 关键词命中≠内容覆盖 |
| **F 技术对标** | 「可覆盖/对标/全球首款」句式供人工判定；引号内容须回溯原文 | 技术对错程序判不了但能定位；引号=原文不能转述冒充 |
| **G 数字一致性** | 正文+表格商誉/营收/净利/市值逐项比对（含正负号） | E 组查"有没有"，这里查"对不对" |
| **H 首次提及出处** | 泛指文件词首次出现是否带《文件名》或披露日期 | 防行文倒错 |
| **I 缺口守门** | 文章若在「已知缺口」维度出现量化表述或推断动因→WARN；透明外推（全年预测/TTM/非承诺）已加白名单 | 守死"禁编造"红线 |

**验证方法（缺一不可）**：E 组用已知有遗漏的旧稿跑必须 FAIL（全 PASS=检查器失效）；G 组故意注入 bug（期末商誉改期初/净利改符号）必须 FAIL；H 组把"预案里直白（无出处）"注回去必须 FAIL。

**引号使用规范（G/F 组强制）**：「」只用于原文引用（内容须能在数据源找到，F2 逐条回溯）；强调/比喻/自创提法一律用加粗；违反=F2 FAIL（转述加引号=造假）。

---

## 🔌 数据源架构（MCP 优先）

> 早期几乎全依赖逆向 API/爬虫/网页搜索导致内容不可靠，已重构为 MCP 优先。相关文件：`scripts/data_source_registry.py`（注册表）、`scripts/mcp_bridge.py`（计划+回填）、`scripts/redline_gate.py`（红线门禁）。

### 分层（优先级高→低）
| 层级 | 含义 | 可否作主源 |
|---|---|:---:|
| **T1-MCP** | `wind-finance`(主力)/`dzh-mcp`/`alphapai-lite-mcp`/`qcc-company` | ✅ |
| **T2-OFFICIAL** | SEC XBRL、交易所官网 | ✅ |
| **T3-API** | 东方财富、Tushare、THSDK | ✅（须标层级） |
| **T4-CRAWLER** | 巨潮 PDF、港交所 Playwright | ⚠️ 仅文档原文 |
| **T5-WEBSEARCH** | Bing CN | ❌ 仅线索 |
| **T6-IWENCAI** | 问财 | ❌ 禁止作主源 |

### 可用的金融 MCP
| MCP | 代码格式 | 覆盖 |
|---|---|---|
| **wind-finance**（🌟主力） | A/北：`600519.SH`/`830799.BJ`；港：`00700.HK`；美：`AAPL.O`（`.O`=NASDAQ/`.N`=NYSE/`.A`=AMEX，非 `.US`） | 行情快照/分钟量价/K线/财务+衍生估值/股东结构/公司档案/公告原文 |
| **dzh-mcp**（备选，24 工具） | A：`SH600000`/`SZ000001`/北：`BJ830799`/港：`HK00669`/美：`NSAAPL` | 三大报表/十大股东/主营构成/分红/公告/研报/调研/资金流/龙虎榜/融资融券；港美股六表 `getHk*/getUs*`（参数名 `symbol`） |
| **alphapai-lite-mcp** | `600519.SH`/`00700.HK` | 公告检索+正文解析(MinerU)/结构化金融/研报路演/港美股纪要；单次 30~60s 偶发 504，须失败重试 |
| **qcc-company** | 企业精确全称/18 位 USCC | 工商/股权穿透/UBO/董监高/对外投资/法律合规风险/股权质押/诉讼/专利商标；**检索键须精确全称或信用代码** |

> 四个 MCP 均须已授权（connected）。`wind-finance` 主力（财务/行情/估值/股东/公告/档案优先走 Wind）；`alphapai` 慢且偶 504，作 T1 备选须失败重试 1 次；`qcc-company` 须先确认**精确全称**（可用 `get_company_by_query` 解析，多候选须人工消歧，严禁猜测）。MCP 未授权时计划标 `blocked_mcp_not_connected`，相关维度走传统源或触发 🔴 红灯。

### Python 无法直接调 MCP —— "指令文件 + 回填"
```
analyze.py ──生成──→ data/mcp_plan.json（每维度 MCP 工具/参数/代码格式）
                         ↓ AI Agent 按计划调 MCP
analyze.py ←──读取── data/mcp_data/<dim>__<tool>.json（MCP 原始返回，原样落盘）
```
- Agent 侧回填：`from mcp_bridge import save_mcp_result`；analyze 侧读取：`load_mcp_results(data_dir)` → `{'source':'mcp:<tool>','tier':'T1-MCP'}`。
- **未回填=数据缺口**，`redline_gate` 标 🔴，禁止默认值顶替。
- 合并规则（`apply_backfill`）：不删原生数据（腾讯/东财/AKShare/SEC 存 `quote._native`，Wind 覆盖数值字段并打 `_source`/`_tier`/`_currency`）；原生缺失才升主；合并面 `quote`/`kline`/`financial`/`announcements`/`structure._mcp_holders`；港股 `tencent_quote` 常空→用 Wind「证券简称」补 `quote.name`。

### 已废弃源（任何维度不得作主源）
`scripts/websearch`(Bing)、`scripts/iwencai_provider`/`iwencai_adapter`(问财)、`scripts.free_data_provider`、`scripts.gsxt_crawler`(企查查爬虫，反爬强，已由 qcc-company 替代)。

### 公司名实时解析纪律
**铁律：公司名一律以「实时证券简称为唯一权威名」，禁止写死旧名/凭记忆给名**（002180 于 2026-04-18 由「纳思达」更名「奔图科技」，代码不变）。`analyze.py` 启动先用 `get_company_name(stock)` 解析存入 `results['company_name_resolved']` 贯穿全链路；企查查 `searchKey` 必须用 USCC（计划自动前置 `get_company_by_query` 解析填 `__USCC__`，多候选用 `pick_listed_entity()` 锁定上市母公司）。Agent 手动调 MCP 同样禁止把旧名当常量。

### 同业名单发现 + 外部注入（`peer_discovery.py`）
年报确实写了竞争对手但口径很脏（对手/客户/供应商/伙伴混写、称谓不统一、同名歧义），故用三段流水线：A Python 切窗 → B **Agent** 判语义 → C Python 反查代码+取数。
```bash
python scripts/peer_discovery.py --code 688585 --stage A        # 切窗
python scripts/peer_discovery.py --code 688585 --stage B        # 打印给 Agent 的请求契约
python scripts/peer_discovery.py --code 688585 --stage C --md    # 反查代码+快照+出表
python scripts/peer_discovery.py --code 688585 --apply-quotes wind_quotes.json  # 并入 Wind 补的估值
```
年报零对手时可 `--inject peers.json` 交 Agent 给名单，但须配**四道守卫**：①代码归一必达（未上市/退市/名称错→❌未验证，不得进名单）②近名碰撞≥0.6（AI 音近形近写错专名）③ST/退市警示 ④亏损+规模离散（PE 均值失真须剔除后取中位数）。🔴 负 PE 必须写「亏损」而非 -8.65；🔴 币种必须标注（Wind 港美股返回美元/港元，与 A 股人民币不可直接比）；🔴 `--auto` 规则版禁止进客户材料（只当线索，带 `method='regex_heuristic'` 红标）。**口径红线**：本工具产出="发行人自己披露的对手名单"≠分析师按细分赛道选的可比公司；仍无法程序化的是"行业同业性"——须人工或 Agent 调 Wind `get_stock_basicinfo` 背书。

---

## 使用方法

```bash
# 安装依赖（目标机）
pip install requests pdfplumber pandas -q

# A股全维度分析（默认即全维度，无需 --full）
python analyze.py --stock 002180
python analyze.py --stock 600519

# 港股 / 美股 / 北交所
python analyze.py --stock 00700 --market hk
python analyze.py --stock AAPL --market us
python analyze.py --stock 830799 --market bse

# 指定输出目录
python analyze.py --stock 002180 --output output/002180_20261019

# 联合动作三幕叙事（头号交付物，须在 analyze.py 之后跑）
python scripts/joint_action_narrative.py 002180 --market a \
    --data-dir output/002180_20261019/data --company 奔图科技

# 价值链分析（默认全维度采集后从 results.json['value_chain'] 取数）
python scripts/value_chain_analysis.py 002180 a output/002180_20260530/data

# THSDK 自然语言选股 / 专利 / 供应链（详见 DATA_SOURCES.md）
python scripts/thsdk_search.py nlp "人工智能概念选股"
python scripts/patent_tracker.py --company "小米集团" --stock 01810.HK --market hk
python scripts/supply_cost_tracker.py --industry "消费电子" --company "小米集团"
```

> CLI 仅 `analyze.py <stock> [--market a|hk|us|bse] [--output DIR]`，**无** `--full`/`--dims`/`--expect`/`--name`/`--force`，默认即全维度采集。

---

## 分析维度说明

### A股全维度（默认即全维度）
| 维度 | 简称 | 维度 | 简称 |
|------|------|------|------|
| 公告全景 | `announcements` | 综合风险 | `risk` |
| 财务报表 | `financial` | 同业对比 | `peer_compare` |
| 高管动态 | `executives` | 多年财务趋势 | `multi_year_trend` |
| 资金动作 | `capital` | 盈利预测 | `earnings_forecast` |
| 子公司分拆 | `subsidiary` | 估值分析 | `valuation` |
| 关联方运作 | `related` | 公司治理 | `governance` |
| 监管历史 | `regulatory` | 股本融资历史 | `share_history` |
| 股权结构 | `structure` | 机构持仓 | `institutional` |
| 行业竞争 | `industry` | 实时行情 | `quote` |
| 股权质押 | `pledge` | 年报 PDF | `annual_pdf` |
| 价值链分析 | `value_chain` | 联网搜索 | `websearch` |

年报 PDF 章节覆盖 22 章（审计意见/利润分配/前五客户/前五供应商/实控人/前十股东/或有事项/日后事项/重大诉讼/研发投入/产销量/产能/主要子公司/担保/在建工程/商誉/长期股权投资/政府补助/新设子公司/换所 + 新增 `litigation_detail`/供应商章节扩展）。上交所 PDF 用上交所 API（JS 反爬 cookie 流程，xbrowser）。

### 港股维度（--market hk）
公告(东财港股+港交所)/财务(`hk_records` 对齐 A 股 records，Wind `get_stock_fundamentals` 主 + dzh 港三表备)/行情估值K线(Wind `get_stock_price_indicators`+`get_stock_kline` 主)/股东(Wind `get_stock_equity_holders` 主，港美股**不走 qcc**)/年报 PDF(港交所披露易纯 HTTP)/行业(Wind `get_stock_basicinfo`)/会议纪要(alphapai)/重大事项(SEC 8-K/SC 13D/G 清单)/高管(SEC DEF 14A 清单)/关联交易商誉诉讼担保(年报附注抽取)/监管(SEC 执法 RSS)。**质押**：企查查不覆盖港股，`hk_pledge` 维度自动标 `gap`，须人工以港交所披露易「股份抵押」补充，不得写"无质押"。

### 美股维度（--market us）
财务(SEC XBRL→`us_records`，Wind `get_stock_fundamentals` 主 + dzh `getUs*` 备)/行情估值K线(必靠 Wind 回填，脚本源无价无估值)/股东(SEC DEF 14A/13F)/行业(东财 F10 美股必空，Wind `get_stock_basicinfo` 主)/年报(SEC EDGAR)/关联交易商誉诉讼担保(年报附注抽取)/监管(HKEXnews 标题扫描)。**质押/股权变动**：企查查不覆盖美股，`us_pledge` 维度自动标 `gap`，须人工以 SEC 13D/13G/Form 4 补充。

> 🔴 港美股「Wind 主力」≠全维度替代：公告/年报 PDF 仍走港交所/SEC；美股 13F 必须 SEC。Wind 接管行情/估值/K线/财务/股东/行业概念六类结构化数据。🔴 美股 windcode 后缀必须对：`.O`=NASDAQ/`.N`=NYSE/`.A`=AMEX，裸 ticker 默认补 `.O`，查无数据先改 `.N`；类别股写全 `BRK.B.N`。🔴 SEC XBRL 必经 `us_records.attach_records()` 转 A 股同构 `financial['records']`（只取 CYyyyy 年度 frame，置 `IS_ANNUAL=True`），不转="有数据但读不到"。

### 北交所维度（--market bse）
无独立采集逻辑，内部归一化 `market='a'` 后复用 A 股全链路。🔴 **必过迁码层**：代码从 `8xxxxx/4xxxxx` 迁到 `920xxx`，东财新接口只认 920 段（老代码实测全 0），`scripts/bse_migrate.py` 腾讯行情取简称→东财反查 920 代码。报告须同时标原代码与迁码后代码。

---

## 新增模块详解
- **multi_year_trend**：营收/净利 5 年 CAGR、毛利率趋势、ROE+净利率(杜邦)、经营现金流/净利(现金流质量)、财务预警(连续下滑/毛利率异常/ROE 负/连续亏损)。
- **earnings_forecast**：历史 3 期增速推三档情景(乐观×1.2/中性×0.8/悲观×0.5)、3 年预测利润表、关键驱动因素。
- **valuation**：PE(TTM)/动态/ PB/PS、历史 PE 分位数、简化 DCF(WACC/永续/g/FCF/终值)、敏感性矩阵、综合结论。
- **governance**：股权集中度(CR1/5/10)、质押比例/方/状态、管理层、独董有效性、审计信息、内控、治理评分 0-100。
- **share_history**：IPO/分红(10 年)/定增/股本变动/解禁时间表。
- **institutional**：北向资金、股东户数趋势、机构持仓明细(基/保/社/信/券)。
- **value_chain**：上游(供应商集中度/关联交易占比/原材料成本/议价)、中游(产能利用率/技术壁垒/研发 Capex)、下游(客户集中度/销售模式/渠道/品牌溢价)，综合评分 0-100（🟢≥70/🟡50-69/🔴<50）。

---

## 报告章节结构（完整 23 章）
1.执行摘要(含风险等级) 2.公告全景 3.实时行情 4.财务报表分析 5.高管动态 6.资金动作 7.子公司分拆/IPO 追踪 8.关联方资本运作 9.监管历史 10.股权结构分析 11.行业竞争格局 12.同业财务对比 13.研发与利润归因 14.综合风险评级 15.多年财务趋势 16.盈利预测与情景分析 17.估值分析 18.公司治理深度分析 19.股本变动与融资历史 20.机构持仓与筹码分析 21.战略意图综合分析 22.年报 PDF 分析 23.信息缺失清单

---

## 输出规范（五段式协议）

每个分析维度与最终报告均须遵循"五段式"，确保结论可复核、可追责、可行动：
1. **结论**：核心判断+置信度（🔴高/🟡中/🟢低），无明确判断不得交付。
2. **证据**：支持结论的关键证据，须注**时间**与**一手来源**（巨潮/交易所公告编号、年报页码、接口与日期）。
3. **拆解表**：表格拆解关键要素、假设前提与计算口径（估值 WACC/g/情景、风险权重、同业去极值法）。
4. **风险与数据缺口**：列主风险；缺失数据说明缺口影响+替代口径，并下调置信度。
5. **下一步验证**：可执行验证路径、所需数据、时间表。

与 23 章报告映射：第 1 章=结论+风险收口；第 14/23 章=风险与数据缺口(逐项标替代口径+置信度折减)；各维度章=证据+拆解表主体。两条硬纪律：**缺口不得写成结论**（缺数据须说明影响+替代口径，禁编造/默认填充）；**路由严格锚定+异常即停**（脚本异常/缺失须停止引入人工决策，禁模拟数据/Plan B）。收口核验：核对单位/期间/时间/口径一致性，跨年跨期不得拼接；未通过验证用 🔴 红灯列出。

---

## 联合动作三幕叙事（写作前素材梳理 · 非对外交付物）

采集境内外联合动作（并购/合资/引战/出海/股权变动/技术合作）海量数据，用叙事手法讲「过往→现状→下一步」。原有 23 章/五段式/红灯门禁作证据底座保留。模块入口 `scripts/joint_action_narrative.py`。

- **事件模型** `JointActionEvent`：日期/大类/子类/标题/对手方/地域(境内·境外跨境)/金额/来源模块/数据层级/置信度。
- **四类采集矩阵**：并购重组(`related_deals`/`ma_deep`)/合资战略合作(`related_deals`+公告)/融资引战定增(`related_deals`/`financing_structure`/`share_history`)/出海股权技术(`cross_market_discovery`/`structure`/`patent_tracker`)。地域判定：标题含境外/海外/HK/美国/新加坡/开曼/BVI/国际/全球→`境外·跨境`。
- **头号交付物** `joint_action_narrative.html`（人类阅读首选），同源 `.md`/`.json`。事实完全一致仅呈现媒介不同，HTML 不引入新事实（同守"缺口不编结论"）。
- **为什么主交付物是 HTML**：Markdown 人读要滚几十屏看不出层次；三幕叙事需版式承载。能力：顶部指标卡/三幕色带(蓝过往绿现状琥珀下一步)/时间线/证据脚注/风险底盘框/推断卡/@media print A4/完全离线(0 外部资源)。
- **配色纪律**：刻意不用任何品牌色（通用分析工具非某机构出品），中性低饱和学术色（`#3d5a80`/`#2f6b5f`/`#8a6520`）。
- **安全纪律**：HTML 所有插值必须过 `_esc()`/`_esc_t()`（公告原文不可信输入），严禁结构字段直接 f-string 注入。
- **结构固定三幕**：第一幕·过往(动作编年+时间线)/第二幕·现状(最近动作+境内外版图+战略定位+风险资产底盘)/第三幕·下一步(公司既定计划[年报 MD&A 展望优先] + 财中视角资本运作推断[标注"非公司披露仅供参考"] + 待验证缺口)。
- **capital_operation_inference 读取**：AI 推断在 `findings['ai_analysis']['capital_operation_inference']`（第②落点），旧版只读第①落点→第三幕永远拿不到 LLM 推断；`extract_caizhong_inference()` 按优先级合并三源(②优先、①③兜底)。
- **证据纪律**：每笔动作带 `_[源:模块 · 置信]_` 脚注；缺口不编结论；核心维度缺失触发 🔴 红灯；LLM 仅可选润色且严格基于已抽取事件，禁生发新事实。

```bash
# 在 analyze.py 跑完、产出同一 data 目录后装配
python scripts/joint_action_narrative.py 002180 --market a \
    --data-dir output/002180_20261019/data --company 奔图科技
# 产物：<data_dir>/joint_action_narrative.{html,md,json}；--no-open 禁用自动打开
```

---

## 输出文件
```
output/{股票代码}_{日期}/
├── report.md              # 深度研究报告（含23章节）
├── timeline.md            # 重大事件时间线
├── warnings.md            # 风险信号清单
└── data/
    ├── multi_year_trend.json / valuation.json / governance.json / share_history.json
    ├── institutional.json / earnings_forecast.json / financials.json
    ├── announcements.json / annual_report_sections.json
```

---

## 依赖环境
- Python 3.8+；`requests`/`pdfplumber`/`pandas`/`akshare`（可选 `matplotlib`）；`thsdk`/`tushare` 见 `DATA_SOURCES.md`。
- 网络：能访问东方财富、巨潮资讯、证监会官网、Yahoo Finance（港股/美股估值）。
- **Tushare Token**：注册 https://tushare.pro 获取，存 `.tushare_token`（已 gitignore）或环境变量 `TUSHARE_TOKEN`。权限：daily/dividend/share_float/company 可用；财务三表/PE·PB/资金流/概念板不足。

---

## 核心 API 使用技巧（重要）
**巨潮年报 PDF 搜索**：CNINFO fulltext API 的 `stock` 参数不生效，必须用 `searchkey`！
```python
data = {'tabName':'fulltext','category':'category_ndbg_szsh','plate':'sz',
        'searchkey':'股票代码或公司名'}  # 不是 stock 参数！
```

---

## 维护工具（改动本 skill 后必跑）
```bash
python scripts/audit_imports.py        # 全量导入体检
python scripts/test_actionability.py    # 公告洪水分类器回归（25 用例）
python scripts/silenced_errors.py       # 静默降级登记表自测
```
改动任何数据源或降级路径后，按序验证：导入体检 → 相关单测 → 全维度实跑（`analyze.py <stock>` 默认即全维度）→ 才允许用于正式交付。

---

## 公告全文抽取：降级链与边界
四路降级链（前 3 路 Python 自动，第 4 路 Agent 回填）：① PDF 缓存(0.01s) ② 巨潮直连+PyMuPDF 4 并发(主源，7.3s/条) ③ MCP MinerU 深解析 ④ 东财/新浪 HTML。
🔴 **MCP MinerU 只覆盖近期公告**（2026 命中 2/2，2020 命中 0/4），**不能替代自建 PDF 链路**，只作第 3 路兜底；`mcp_mineru_bridge` 只登记近期(≥2024-01-01)公告。其他 MCP：`search_announcements` 可补全清单；`get_announcement_detail` 只有元数据无正文；`download_announcement_pdf` 历史 PDF 也能下。MCP 正文必须过事实抽取（`_extract_facts_by_type`）否则下游拿不到标的名/金额。详细实测见 `CHANGELOG.md`。

---

> 审计/补强/bug 修复/一次性验证数据见 **`CHANGELOG.md`**；各数据源 CLI/Python 调用细节见 **`DATA_SOURCES.md`**；打包与 MCP 环境清单见 **`DEPENDENCIES.md`**。

---

## 🧩 泛化复用模板（对标"智数分析专家团"研究范式）

本 skill 本质是**一套可迁移的上市公司深度研究引擎**，不绑定单一分析主题。换公司、换主题、换素材，研究管线（采集→语义量化→证据包→理论框架→撰写→门禁）原样不动，只改占位符。以下模板仿官网案例范式，把"换主题只是换镜头"制度化。

### 泛化提示词模板（给 Agent 的总指令）
```
对 {公司名称}（股票代码：{股票代码}）在 {分析区间，如 2015–2025} 的 {数据来源，如历年年报}
开展全面的 {分析主题，如数字化转型叙事分析}，生成一份 {交付形态，如咨询报告/评论文章}。

## 分析维度
{分析维度：文本语义量化(MD&A词频/LDA/叙事强度) + 财务指标 + 数字化投入；
 换主题可替换为：运营效率/销售结构/人力资源效能/财务质量/ESG}

## 理论框架
引入 {理论框架，如 MBA 战略与数字化转型相关理论} 作为分析骨架，理论与实践紧密结合。

## 交付形态
{形态A 通俗评论 2000–3500 字 | 形态B 咨询报告（指标卡+问题卡片+雷达图+附录）}

## 技术规范
- 采集走 MCP 优先数据源（wind-finance/dzh-mcp/qcc-company/alphapai）
- MD&A 文本语义量化走 scripts/mda_semantic.py，中间计算落盘可复现
- 所有结论须回查 evidence_pack，缺口维度禁编造
- 跑 article_checklist.py 45+ 门禁，FAIL 未清零不得交付
```

### 主题模板库（只改 {分析维度} + {理论框架} 两处）
| 主题 | 分析维度侧重 | 理论框架 |
|---|---|---|
| 数字化转型叙事 | MD&A 词频/LDA/叙事强度 + 研发强度 | 动态能力/RBV/数字化成熟度/平台战略与网络效应 |
| ESG 表现 | 环保/社会/治理披露 + 碳排/员工结构 | 利益相关者理论/可持续发展理论 |
| 运营效率 | 产能利用率/成本结构/供应链 | 精益生产/价值链分析 |
| 销售与营销 | 渠道/客户结构/区域分布 | STP/4P/客户生命周期 |
| 人力资源 | 员工结构/人均效能/激励 | 人力资本理论/激励理论 |
| 财务质量 | 现金流/偿债/减值风险 | 盈余管理/信号理论 |

🔴 **复用铁律**：换主题只改 `{分析维度}`+`{理论框架}`，采集层与证据包基座不动；换公司改 `{代码}`+`{区间}`；换素材改 `{数据来源}`（招股书/ESG 报告/业绩说明会纪要均可）。「所有中间计算以脚本保存」这条硬要求**务必保留**——它是可复查、可复算的关键。

---

## 📊 咨询报告模式（--format report）

🔴 **双形态并存**：形态 A（现状，通俗评论文章 2000–3500 字）与形态 B（咨询报告，结构化+图表+理论框架+附录）面向不同场景——MBA/尽调/课程答辩用 B，快速观点输出用 A。撰写层按 `--format` 切换，**基座与门禁完全一致**。

### 形态 B 结构（对标案例 HTML 咨询报告）
1. 执行摘要 + 6 张核心指标卡（营收 CAGR/毛利率/研发强度/人均效能/叙事强度峰值/关键相关系数）
2. 六理论框架整合（动态能力/RBV·VRIO/波特价值链/数字化成熟度/平台战略与网络效应/TAM），每框架附实证数据
3. 核心问题卡片（严重程度 + 理论依据 + 实证数据）
4. 战略举措与改善建议
5. 图表：趋势图 / 对比柱状图 / 雷达图（数字化成熟度五维）/ 词频热力图（MD&A 关键词×年）
6. 附录 A–D：缩略语表 / 数据来源 / 脚本说明 / 口径说明

### 触发方式
```bash
# 形态 B 自动化生成（report_advisory.py，离线单文件 HTML，含上列 1–6 全部章节）：
# 先跑三层产出 → article_brief 生成 evidence_pack → report_advisory 出报告
python scripts/mda_semantic.py --corpus ./annual_pdfs --years 2019,2020,2021,2022,2023 \
    --lexicon digital_transform.json --financial-json financials.json --output mda_semantic_out
python scripts/theoretical_framework.py --financial-json financials.json \
    --mda-out mda_semantic_out --company {公司名} --output theoretical_framework_out
python scripts/article_brief.py <data_dir>          # 产出 evidence_pack.json
python scripts/report_advisory.py <data_dir> --output consulting_report.html   # 形态 B 报告
```
🔴 形态 B 报告由 `report_advisory.py` 直接生成（执行摘要/指标卡/六理论整合+雷达图/问题卡片/战略建议/图表/附录 A–D），**内容全部来自落盘产物、不现算、不编造**；若需定制措辞，再交 Agent 在报告骨架上改写。雷达图/热力图/叙事轨迹为内联 SVG，双击离线可开。

### 配色纪律（继承 joint_action_narrative）
刻意不用任何品牌色（通用分析工具非某机构出品），中性低饱和学术色（`#3d5a80`/`#2f6b5f`/`#8a6520`）；雷达图/热力图数据来自 `mda_semantic_out/` 落盘文件，不现算。

### 理论框架层（`theoretical_framework.py` ✅ 已落地）
6 大 MBA 理论（动态能力 / RBV·VRIO / 波特价值链 / 数字化成熟度 / 平台战略与网络效应 / TAM）已做成「维度→指标→打分」映射，每个框架附实证数据锚定，产出 `theoretical_framework.json` + `theoretical_framework_integration.md`。可用维度 < 2 的框架整体标 `data_gap`，不硬套。运行见下方「文本语义量化」之后的独立章节与 `SKILL_CASE_FUSION_PLAN.md` 阶段三。

---

## 🆕 文本语义量化（mda_semantic.py）

补足 skill 此前缺失的「MD&A 文本语义量化」：词频矩阵 / LDA 主题模型 / 叙事强度轨迹 / 叙事 vs 事实偏离检测（Pearson）。**基座已能抽取 MD&A 全文，本模块在其上做系统量化**，全部落盘供复算。详见 `SKILL_CASE_FUSION_PLAN.md`。

```bash
# 从年报 PDF 取 MD&A 并量化（年份与 PDF 顺序对齐）
python scripts/mda_semantic.py 2020.pdf 2021.pdf 2022.pdf --years 2020,2021,2022
# 目录批量
python scripts/mda_semantic.py --corpus ./annual_pdfs --years 2019,2020,2021,2022,2023
# 已抽取好的 {year: text}
python scripts/mda_semantic.py --mdaa-json mdaa_by_year.json
# 完整：自定义词典 + 财务年序列触发偏离检测
python scripts/mda_semantic.py --corpus ./pdfs --years 2020,2021,2022 \
    --lexicon digital_transform.json --financial-json financials.json --lda 4
```

🔴 **纪律**：jieba 缺失时自动正则 2-gram 降级（仅作线索，客户材料禁用降级结果）；sklearn 缺失时 `lda_topics.json` 显式标 `data_gap` 不伪装；偏离检测年数 < 3 或指标缺失标 `data_gap`，**缺口不得写成结论**。输出：`word_freq_matrix.csv` / `narrative_intensity.json` / `lda_topics.json` / `narrative_vs_fact.json` / `mda_semantic_report.md`。

---

## 🤝 专家团模式（orchestrate_expert_team.py）

🔴 **单 Agent → 多角色编排**：面对「跨多年 / 理论重 / 咨询级交付」的复杂诉求，把撰写层拆成 **5 角色专家团**并行/串行编排（对标官网案例「智数分析专家团」）。本模式**不另搭 LLM API**——`orchestrate_expert_team.py` 只产出一份「角色分工 + 执行顺序 + 门禁」清单（manifest JSON + dispatch markdown），由**本会话 Agent** 按清单逐角色执行，全程复用下方既有脚本。基座（MCP 优先数据源）与门禁（45+ 项 `article_checklist.py`）与单 Agent 模式**完全一致**，仅在「人手分工」上升级。

### 五角色与职责
| 角色 | 职责 | 对应模块 |
|---|---|---|
| ① 首席数据编排师 | 把诉求翻译成采集-分析计划（定源优先级 / analyze 参数 / 输出目录 / 门禁） | `analyze.py`（规划） |
| ② 知识检索专家 | 一手信源检索：公告全文 / 行业研报 / 同业 / 新闻监管，标注源层级 T1–T6 | `peer_discovery.py` / 网页搜索 / `business_fetch.py` |
| ③ 数据科学工程师 | 跑通采集与三层量化，落盘全产物 + 证据包 | `analyze.py` + `mda_semantic.py` + `theoretical_framework.py` + `article_brief.py` |
| ④ 洞察报告撰写师 | 基于证据包写最终交付物（形态 A / B） | 本会话 Agent 按证据包撰写 |
| ⑤ 可视化分析设计师 | 据落盘数据出图表（雷达图/热力图/趋势图）回填形态 B | `visualization.py` / `chart_renderer.py` |

### 触发方式
```bash
# 产出 5 角色派工清单（不跑分析，只规划分工；之后由 Agent 逐角色执行）
python scripts/orchestrate_expert_team.py --company 某公司 --code 600000 \
    --years 2019,2020,2021,2022,2023 --topic 数字化转型叙事分析 --format b
# 产物：<output>/expert_team_manifest.json（结构化清单）+ expert_team_dispatch.md（可读派工板）
```

### 执行次序（Agent 按此逐角色推进）
1. ① 编排师 → `data_plan`（源/参数/输出目录/门禁）
2. ② 检索专家 → 一手信源清单（可与 ① 并行启动，并入需等 data_plan）
3. ③ 数据工程师 → `analyze` + `mda_semantic` + `theoretical_framework` + `article_brief`，落盘全产物
4. ④ 撰写师 → 按 `--format` 写 `article.md` / `report.md`
5. ⑤ 可视化 → 出雷达图/热力图/趋势图，回填形态 B
6. 收口 → `article_checklist.py` 全组（含 J 叙事解耦、K 理论框架），FAIL 未清零不得交付

🔴 **角色纪律**：每角色只消费上游落盘产物、只产出自己的落盘产物，禁止跨角色凭印象补数；理论评级须有六维打分、叙事背离须有 pearson_r，缺口维度一律 `data_gap`，与单 Agent 模式同铁律。
