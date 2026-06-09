# 上市公司全景深度分析 Skill

## 功能简介

对**A股/港股/美股**上市公司进行全方位深度研究，自动完成从**数据采集→趋势分析→盈利预测→估值建模→公司治理→风险评级**全链路，输出结构化 Markdown 深度研究报告。

---

## 使用方法

```bash
# A股全维度分析（含新增深度模块）
python analyze.py --stock 002180 --full

# 港股分析
python analyze.py --stock 00700 --market hk --full

# 美股分析
python analyze.py --stock AAPL --market us --full

# 指定维度（可组合）
python analyze.py --stock 002180 --dims multi_year_trend,valuation,governance
```

---

## 分析维度说明

### A股全维度（--full 或 --dims all）

| 维度 | 简称 | 说明 |
|------|------|------|
| 公告全景 | `announcements` | 近12个月重大公告分类整理 |
| 财务报表 | `financial` | 年报关键指标、审计意见、商誉减值 |
| 高管动态 | `executives` | 辞职/新任/薪酬/股权激励变动 |
| 资金动作 | `capital` | 募资变更/套保/补充流动资金 |
| 子公司分拆 | `subsidiary` | 拟分拆IPO子公司的辅导进度 |
| 关联方运作 | `related` | 收购/出售/私有化/关联交易 |
| 监管历史 | `regulatory` | 问询函/处罚/核查意见历史 |
| 股权结构 | `structure` | 上市公司→子公司→关联方全图 |
| 行业竞争 | `industry` | 证监会行业/主营构成/可比公司 |
| 综合风险 | `risk` | 多维度综合风险评分（0-100） |
| 同业对比 | `peer_compare` | 申万行业横向对比（robust均值去极值） |
| 多年财务趋势 | `multi_year_trend` | 5年CAGR、毛利率趋势、杜邦分析、现金流质量 |
| 盈利预测 | `earnings_forecast` | 三档情景预测（乐观/中性/悲观）、3年预测利润表 |
| 估值分析 | `valuation` | PE/PB历史分位、DCF框架、敏感性矩阵 |
| 公司治理 | `governance` | 股权集中度、质押风险、独董有效性、内控评分 |
| 股本融资历史 | `share_history` | 分红历史(10年)、解禁时间表、IPO/定增记录 |
| 机构持仓 | `institutional` | 基金/保险/社保持仓、股东户数趋势、北向资金 |
| 实时行情 | `quote` | 当前股价、涨跌幅、成交量 |
| 年报PDF | `annual_pdf` | 下载+提取年报全文关键章节（**新增诉讼详情+客户供应商章节扩展**）|
| 联网搜索 | `websearch` | 从CNINFO搜索年报PDF链接 |
| **价值链分析** | `value_chain` | **NEW** 上/中/下游价值链分析、供应商集中度、产能利用率、客户集中度、评分0-100 |

**年报PDF章节覆盖（共22章节，新增2个）**：
- 原有20章：审计意见、利润分配、前五客户、前五供应商、实际控制人、前十股东、或有事项、日后事项、重大诉讼、研发投入、产销量、产能、主要子公司、担保、在建工程、商誉、长期股权投资、政府补助、新设子公司、换所
- **新增**：`litigation_detail`（诉讼仲裁详情与金额）、供应商章节扩展至8KB（含关联关系标注）
- **上交所PDF**：沪市股票（6xxxx）使用上交所API，支持JS反爬cookie流程（xbrowser）

### 港股维度（--market hk）

| 维度 | 简称 | 说明 |
|------|------|------|
| 公告全景 | `announcements` | 东方财富港股公告 |
| 港股财务 | `hk_financial` | AKShare，含4期36字段财务指标、估值、分红 |
| 行业竞争 | `industry` | 东方财富F10行业分类 |
| 综合风险 | `risk` | 综合风险评分 |

---

## 新增模块详解

### 多年财务趋势（multi_year_trend）
- 营收/净利润 **5年CAGR**
- 毛利率趋势（与5年均值对比）
- ROE + 净利率趋势（杜邦简化分析）
- 经营现金流/净利润比率（现金流质量）
- 财务预警：连续下滑、毛利率异常波动、ROE为负、连续亏损

### 盈利预测（earnings_forecast）
- 基于历史3期增速自动推算三档情景：
  - **乐观**：历史均值×1.2，毛利率改善
  - **中性**：历史均值×0.8，毛利率略降
  - **悲观**：历史均值×0.5，毛利率明显下降
- 3年预测利润表（营收/毛利润/净利润/EPS）
- 3年累计营收/净利润汇总
- 关键驱动因素清单

### 估值分析（valuation）
- 当前估值：PE(TTM)/PE(动态)/PB/PS
- **历史PE分位数**：当前PE在近3年/5年的百分位
- **简化DCF框架**：WACC/永续增长率/FCF预测/终值
- **敏感性矩阵**：WACC±1% × 永续增长率±1% → 估值区间
- 综合估值结论（低估/合理/偏高）

### 公司治理（governance）
- 股权集中度：**CR1/CR5/CR10**，判断一股独大风险
- 股份质押：最新质押比例、质押方、质押状态
- 管理层：董事长/总经理/CFO/董秘
- 独董有效性：人数/占比、会计/法律背景评估
- 审计信息：审计机构/费用/年限
- 内控评价：自评结论 + 内控审计意见
- **治理评分**（0-100）

### 股本融资历史（share_history）
- IPO信息：上市日期/发行价/募资金额
- 分红历史：近10年每股派息/送股/转增
- 定增记录：日期/发行价/募资/目的
- 股本变动：变动原因/变动前后股本
- 限售股解禁时间表

### 机构持仓（institutional）
- 北向资金：持股数量/占流通股/趋势判断
- 股东户数趋势：筹码集中/分散信号
- 机构持仓明细：基金/保险/社保/信托/券商

### 价值链分析（value_chain） ← NEW
- **上游分析**：供应商集中度（前五占比）、关联交易供应商占比、原材料成本占比、议价能力评估
- **中游分析**：产能利用率、技术壁垒、研发投入强度、Capex强度
- **下游分析**：客户集中度（前五占比）、销售模式（直销/经销）、渠道掌控力、品牌溢价指数
- **综合评分**：0-100分，🟢强(≥70) / 🟡中(50-69) / 🔴弱(<50)

**使用方法**：
```bash
# 单独运行价值链分析
python scripts/value_chain_analysis.py 002180 a output/002180_20260530/data

# 指定维度分析
python analyze.py --stock 002180 --dims value_chain
```

**Python调用**：
```python
from scripts.value_chain_analysis import ValueChainAnalyzer, fetch_value_chain

# 方式1：直接调用
result = fetch_value_chain('002180', 'a', data_dir)

# 方式2：使用分析器
analyzer = ValueChainAnalyzer(annual_sections, financials)
report = analyzer.analyze()
print(report['summary'])
print(f"评分：{report['value_chain_score']}/100")
```

---

## Tushare 数据源（补充）

**文件**：`scripts/tushare_data.py`

**用途**：补充分红送股、解禁时间表数据（东方财富API没有的历史数据）

**使用方法**：
```bash
# 测试分红数据
python scripts/tushare_data.py --stock 000001 --dividend

# 测试解禁数据
python scripts/tushare_data.py --stock 000001 --float

# 全部数据
python scripts/tushare_data.py --stock 000001 --all
```

**Python调用**：
```python
from scripts.tushare_data import TushareData
ts = TushareData()

# 获取分红历史（10年）
div = ts.get_dividend('000001.SZ', years=10)
# 返回: {'success': True, 'data': [...], 'stats': {...}}

# 获取解禁时间表（未来1年）
unlock = ts.get_share_float('000001.SZ', days=365)
# 返回: {'success': True, 'data': [...], 'stats': {...}}
```

**数据对比**：
| 数据源 | 分红历史 | 解禁时间表 | 优势 |
|--------|----------|------------|------|
| 东方财富API | 近10年 | 近1年 | 实时更新 |
| Tushare | 上市以来 | 未来1年 | 历史完整 |

---

## THSDK 数据源（同花顺SDK v2 — 实时行情+自然语言选股+美股）

**文件**：`scripts/thsdk_search.py` **v2**

**用途**：实时行情（A股30+字段/港股/美股）、K线（含分钟级）、板块数据、自然语言选股、DDE大单流向、五档盘口、分红历史、竞价异动、资讯快讯

**安装**：`pip install --upgrade thsdk`（当前v1.7.18，游客账号免费可用）

### CLI 使用

```bash
# 自然语言选股（核心新能力）
python scripts/thsdk_search.py nlp "连续3天涨停"
python scripts/thsdk_search.py nlp "PE<20且市值>100亿的半导体股"
python scripts/thsdk_search.py nlp "人工智能概念股" --max 30

# 证券模糊搜索（A股/港股/美股通用）
python scripts/thsdk_search.py search "茅台"
python scripts/thsdk_search.py search "AAPL"

# A股实时行情（30+字段：PE TTM/主力净流入/委比/量比/涨停跌停价/流通市值等）
python scripts/thsdk_search.py quote 600519

# 港股实时行情（基础数据+财务指标）
python scripts/thsdk_search.py quote_hk 00700

# 美股实时行情（基础数据+财务指标+52周高低点）
python scripts/thsdk_search.py quote_us AAPL
python scripts/thsdk_search.py quote_us TSLA

# K线数据（支持分钟级）
python scripts/thsdk_search.py kline 300033 --interval day --count 30
python scripts/thsdk_search.py kline 300033 --interval 5m --count 20
python scripts/thsdk_search.py kline 300033 --interval week --count 20 --adjust qfq

# 板块数据
python scripts/thsdk_search.py block --type industry          # 行业板块列表
python scripts/thsdk_search.py block --type concept --name AI  # 概念板块筛选
python scripts/thsdk_search.py constituents 886099              # AI智能体成分股

# 分红送转
python scripts/thsdk_search.py dividend 300033

# DDE大单流向（逐笔成交+买卖方向）
python scripts/thsdk_search.py dde 300033 --max 50

# 五档盘口
python scripts/thsdk_search.py depth 300033

# 分时数据
python scripts/thsdk_search.py intraday 300033

# 集合竞价
python scripts/thsdk_search.py call_auction 300033

# 竞价异动（涨停试盘/跌停试盘）
python scripts/thsdk_search.py auction USZA

# IPO排队
python scripts/thsdk_search.py ipo

# 7x24资讯
python scripts/thsdk_search.py news --max 20
```

### Python 调用

```python
from thsdk_search import ThsdkSearch

with ThsdkSearch() as ts:
    # A股实时行情（30+字段）
    q = ts.quote("600519")
    print(q['data']['价格'], q['data']['市盈率TTM'], q['data']['主力净流入'])
    
    # 港股实时行情
    hk = ts.quote_hk("00700")
    print(hk['data']['价格'], hk['data']['市盈率TTM'])
    
    # 美股实时行情
    us = ts.quote_us("AAPL")
    print(us['data']['价格'], us['data']['52周最高'], us['data']['52周最低'])
    
    # 自然语言选股
    r = ts.nlp("PE<20且市值>100亿的半导体股")
    print(r['total'], r['data'][:5])
    
    # DDE大单流向
    dde = ts.dde("300033")
    
    # 五档盘口
    depth = ts.depth("300033")
    print(depth['bids'], depth['asks'])
```

### THS代码规则

| 市场 | 前缀 | 示例 | 说明 |
|------|------|------|------|
| 沪A | USHA | USHA600519 | 4位市场+6位数字 |
| 深A | USZA | USZA300033 | 4位市场+6位数字 |
| 北交 | USZA | USZA920262 | 4位市场+6位数字 |
| 港股 | UHKMHK | UHKMHK0700 | **4位数字**（不是5位！）|
| 美股(纳斯达克) | UNQQ | UNQQAAPL | 4位市场+字母symbol |
| 美股(纽交所) | UNYN | UNYNJPM | 4位市场+字母symbol |
| 行业板块 | URFI | URFI881165 | 4位市场+6位数字 |
| 概念板块 | URFI | URFI885779 | 4位市场+6位数字 |

> `code_to_ths()` 自动转换6位代码→THS代码，`quote_us()` 自动搜索获取正确的THS代码，无需手动拼

### 数据源分工

| 数据需求 | 首选 | 备选 |
|----------|------|------|
| A股实时行情(30+字段) | **THSDK** | 东方财富API |
| 港股实时行情 | **THSDK** | AKShare |
| 美股实时行情 | **THSDK** | Yahoo Finance |
| K线数据(含分钟级) | **THSDK** | AKShare |
| 自然语言选股 | **THSDK** | 无 |
| 板块/概念列表 | **THSDK** | AKShare |
| DDE大单流向 | **THSDK** | 无 |
| 五档盘口 | **THSDK** | 无 |
| 分时数据 | **THSDK** | 无 |
| 集合竞价 | **THSDK** | 无 |
| 分红送转 | **THSDK** | Tushare |
| 竞价异动 | **THSDK** | 无 |
| IPO排队 | **THSDK** | 无 |
| 资讯快讯 | **THSDK** | 无 |
| 财务报表 | 东方财富API | AKShare |
| 公告/年报PDF | 巨潮资讯 | 上交所 |
| 解禁时间表 | Tushare | 东方财富 |
| 估值指标 | 东方财富API | Tushare |
| 美股深度(盘前盘后/期权/资金流) | Futu API | — |

### 限制
- 游客账号：稳定但可能限频（20ms/次）
- `market_data_cn('行情数据'/'财务数据')` 游客权限不可用
- 美股K线不可用（THS代码格式不兼容：UNQQAAPL不符合"4位市场+6位数字"规则）
- 美股买1/卖1价量在游客模式下返回int32最大值（无效）
- 美股depth/call_auction超时不可用
- 正式账号配置：`THS({'username': '...', 'password': '...', 'mac': '...'})`

---

## TDX 数据源（通达信官方API — 公司信息+股本结构+高管+资金流向+热点题材）

**文件**：`scripts/tdx_provider.py`

**用途**：公司基本信息（完整公司介绍/产品构成/行业/高管）、股本结构（历史总股本/流通股本/限售股变动）、董监高信息、资金流向、热点题材板块族谱等

**API地址**：`http://tdxhub.icfqs.com:7615/TQLEX`

**Token配置**：代码中内置了测试Token（`TDX-60c8102255a6ce8f611560c82896f36d`）

### 核心能力

| 信息类型 | 说明 | 返回字段 |
|----------|------|---------|
| **公司基本信息** | 公司名称/注册地/主营业务/高管/审计机构/联系方式/公司简介/经营范围等 | 35+字段，含产品构成（如茅台酒84%+系列酒14%） |
| **股本结构** | 历史总股本/流通股本/限售股本变动（2018年至今） | 日期/总股本/流通股本/限售股本 |
| **高管信息** | 董事/监事/高级管理人员 | 姓名/职务/任职日期 |
| **资金流向** | 主力资金净流入/流出情况 | 金额/方向 |
| **热点题材** | 公司所属概念板块/主题投资机会 | 题材/板块代码 |

### CLI 使用

```bash
# 公司基本信息（含产品构成、高管、简介）
python scripts/tdx_provider.py 600519 basic

# 股本结构
python scripts/tdx_provider.py 600519 gbjg

# 股本变动历史
python scripts/tdx_provider.py 600519 gbbd

# 限售股解禁时间
python scripts/tdx_provider.py 600519 xslt

# 董监高信息
python scripts/tdx_provider.py 600519 executives

# 资金流向
python scripts/tdx_provider.py 600519 zjlx

# 涨停分析
python scripts/tdx_provider.py 600519 ztfx

# 热点题材
python scripts/tdx_provider.py 600519 zttzbkz

# 综合信息（一次性获取全部）
python scripts/tdx_provider.py 600519 overview
```

### Python 调用

```python
from scripts.tdx_provider import tdxp

# 公司基本信息（含产品构成）
info = tdxp.company_info('600519', 'basic')
print(info['company_name'])           # 贵州茅台酒股份有限公司
print(info['main_business'])          # 茅台酒及系列酒的生产与销售
print(info['controlling_shareholder']) # 中国贵州茅台酒厂（集团）有限责任公司
print(info['chairman'])               # 陈华
print(info['registered_capital'])     # 125008.1601 万元
print(info['employee_count'])         # 34992 人

# 股本结构（历史变动）
structure = tdxp.share_structure('600519', 'gbjg')
for item in structure['data']:
    print(f"{item['T002']}: 总股本={item['T003']}, 流通股本={item['N010']}")

# 资金流向
capital = tdxp.trading_info('600519', 'zjlx')
for flow in capital['data']:
    print(f"{flow.get('date', '')}: 主力净流入={flow.get('main_net_inflow', '')}")

# 热点题材
topics = tdxp.trading_info('600519', 'zttzbkz')
for topic in topics['data']:
    print(f"题材: {topic.get('topic_name', topic.get('T002', ''))}")

# 简化接口
from scripts.tdx_provider import get_company_info, get_share_structure, get_trading_info
info = get_company_info('600519', 'basic')
structure = get_share_structure('600519', 'gbjg')
trading = get_trading_info('600519', 'zjlx')
```

### 在分析流程中的位置

在 `analyze.py` 中，通达信数据源作为 **第19步（最后一步）** 运行，补充以下维度的高质量数据：

- **公司信息**：补充更完整的公司介绍、产品构成、审计机构、联系方式等
- **股本结构**：补充历史股本变动，验证融资/扩股情况
- **高管信息**：补充董监高背景，与第7步的"高管动态"交叉验证
- **资金流向**：补充近期资金流入流出，与第8步的"资金动作"对比分析
- **热点题材**：补充所属概念板块，与第13步的"行业竞争"对比

### 与其他数据源的对比

| 数据维度 | 东方财富/巨潮 | THSDK | Tushare | **通达信TDX** |
|---------|--------------|-------|---------|----------------|
| **公司简介** | 短摘要 | 有限 | 基础 | **详尽（公司介绍/产品/行业/高管）** |
| **股本结构** | 近期 | 实时 | 历史 | **完整历史（2018至今）** |
| **高管信息** | 有限 | 有限 | 基础 | **完整董监高** |
| **资金流向** | 基础 | **详细** | 无 | 专题数据 |
| **热点题材** | 基础 | 概念板块 | 无 | **专题族谱** |
| **审计机构** | 年报中提取 | 无 | 无 | **直接返回** |
| **联系方式** | 有限 | 无 | 基础 | **完整（电话/邮箱/地址）** |

### 缓存机制

- **基本信息**：24小时缓存（`~/.qclaw/cache/tdx/`）
- **股本结构**：24小时缓存
- **交易信息**：2小时缓存（资金流向/热点题材等实时性数据）
- **缓存key**：`tdx_{code}_{type}.json`

### 限制

- 仅支持**A股**（市场代码为沪市6位代码或深市6位代码）
- Token内置但可能有频率限制（0.5秒/次）
- 部分API参数固定为特定值（固定查询）
- 非实时行情数据（主要用于公司基本面/结构信息）
- 如需实时行情，仍推荐使用 THSDK（第1步实时行情）

---

## 输出文件

```
output/{股票代码}_{日期}/
├── report.md              # 深度研究报告（含23章节）
├── timeline.md            # 重大事件时间线
├── warnings.md            # 风险信号清单
└── data/
    ├── multi_year_trend.json    # 多年财务趋势原始数据
    ├── valuation.json          # 估值分析原始数据
    ├── governance.json        # 公司治理原始数据
    ├── share_history.json     # 股本融资原始数据
    ├── institutional.json     # 机构持仓原始数据
    ├── earnings_forecast.json # 盈利预测原始数据
    ├── financials.json        # 财务报表原始数据
    ├── announcements.json     # 公告原始数据
    └── annual_report_sections.json  # 年报章节提取
```

---

## 依赖环境

- Python 3.8+
- requests, pdfplumber, pandas, akshare, matplotlib（可选）
- **thsdk**：pip install thsdk（实时行情/K线/自然语言选股/板块数据）
- **tushare**：pip install tushare（分红/解禁数据补充）
- 网络：能访问东方财富、巨潮资讯、证监会官网、Yahoo Finance（港股/美股估值）

### Tushare Token 配置

免费版Token（120积分/日）获取：
1. 注册 https://tushare.pro
2. 个人中心获取Token
3. 存储到 `skills/listed-company-analysis/.tushare_token`（推荐，已加.gitignore）
4. 或设置环境变量 `TUSHARE_TOKEN`

权限说明：
- ✅ 可用：daily(日线)、dividend(分红)、share_float(解禁)、company(公司信息)
- ❌ 权限不足：财务三表、PE/PB估值、资金流向、概念板块

---

## 核心API使用技巧（重要）

### 巨潮资讯年报PDF搜索

**关键发现**：CNINFO fulltext API 的 `stock` 参数不生效，必须用 `searchkey`！

```python
# 正确用法
data = {
    'tabName': 'fulltext',
    'category': 'category_ndbg_szsh',  # 年报
    'plate': 'sz',
    'searchkey': '股票代码或公司名',  # 不是 stock 参数！
}
```

---

## 报告章节结构（完整23章）

1. 执行摘要（含风险等级）
2. 公告全景
3. 实时行情
4. 财务报表分析
5. 高管动态
6. 资金动作
7. 子公司分拆/IPO追踪
8. 关联方资本运作
9. 监管历史
10. 股权结构分析
11. 行业竞争格局
12. 同业财务对比
13. 研发与利润归因
14. 综合风险评级
15. **多年财务趋势** ← NEW
16. **盈利预测与情景分析** ← NEW
17. **估值分析** ← NEW
18. **公司治理深度分析** ← NEW
19. **股本变动与融资历史** ← NEW
20. **机构持仓与筹码分析** ← NEW
21. 战略意图综合分析
22. 年报PDF分析
23. 信息缺失清单

---

## 快速开始

python analyze.py --stock 06939 --market hk --full
```

---

## 专利情报追踪模块（patent_tracker）

对任意公司进行专利情报追踪，支持A股/港股/美股/未上市企业。

### 数据源实测可访问性（2026-04-29）

| 数据源 | 域名 | 状态 | 备注 |
|--------|------|------|------|
| CNIPA主站 | `www.cnipa.gov.cn` | ✅ 可访问 | 官方入口 |
| CNIPA公共服务平台 | `ggfw.cnipa.gov.cn` | ✅ 可访问 | 专利公布公告等 |
| CNIPA旧检索系统 | `pss-system.cnipa.gov.cn` | ❌ DNS屏蔽 | 不可用 |
| CNIPA新检索系统 | `cpquery.cponline.cnipa.gov.cn` | ⚠️ JS需登录 | 需等待渲染 |
| SooPAT | `www.soopat.com` | ✅ 可访问 | 第三方搜索，推荐 |
| Patentics | `www.patentics.com` | ✅ DNS可用 | 全球专利 |
| 大为Innojoy | `www.innojoy.com` | ✅ DNS可用 | 全球专利 |
| Google Patents | `patents.google.com` | ❌ 网络屏蔽 | ERR_CONNECTION_TIMEOUT |

### 使用方法

```bash
# 按公司名称查询（中文/英文均可）
python scripts/patent_tracker.py --company "小米集团"

# 指定股票代码（自动补充公告数据）
python scripts/patent_tracker.py --company "小米" --stock 01810.HK --market hk

# A股公司
python scripts/patent_tracker.py --company "纳思达" --stock 002180 --market a
```

### 输出内容

- **中国专利局**：CNIPA公共服务平台入口、SooPAT搜索地址
- **全球专利**：Patentics替代Google Patents
- **专利诉讼**：东方财富公告（A股）或巨潮资讯（港股）搜索"专利/侵权/知识产权"关键词
- **风险评级**：低/中/高三档，综合专利诉讼数量

### 输出文件

```
output/patent_tracker/
├── patent_tracker_{公司名}.json    # 原始数据JSON
└── patent_tracker_{公司名}.md      # 格式化Markdown报告
```

---

## 全球供应链成本追踪模块（supply_cost_tracker）

追踪关键原材料/零部件价格趋势，支持任意行业/公司。

### 数据源实测可访问性（2026-04-29）

| 数据源 | 域名 | 状态 | 备注 |
|--------|------|------|------|
| DRAMeXchange | `www.dramexchange.com` | ✅ xbrowser可打开 | **推荐**，DRAM/存储芯片价格 |
| LME | `www.lme.com` | ✅ xbrowser可打开 | 实时价格需登录注册 |
| SHFE | `www.shfe.com.cn` | ⚠️ 被WAF拦截 | 需登录 |
| SMM API | `www.smm.cn` | ❌ API返回404 | 需浏览器访问 |
| 百川盈孚 | `www.baiinfo.com` | ⚠️ 需验证码 | 登录验证 |

### 使用方法

```bash
# 消费电子行业供应链成本
python scripts/supply_cost_tracker.py --industry "消费电子"

# 指定公司+行业
python scripts/supply_cost_tracker.py --company "小米集团" --industry "消费电子"

# 指定关键组件
python scripts/supply_cost_tracker.py --components "DRAM,NAND,OLED面板,锂电池"

# 获取DRAMeXchange价格（最推荐方式）
# 1. 用xbrowser打开 https://www.dramexchange.com/
# 2. 导航到DRAM/存储芯片价格页面
# 3. 截图或提取数据
```

### 行业组件映射

| 行业 | 关键组件 |
|------|----------|
| 消费电子 | DRAM、NAND、OLED面板、锂电池、铜、铝 |
| 新能源汽车 | 动力电池、锂、钴、镍 |
| 半导体 | 硅片、靶材、光刻胶、电子气体 |
| 锂电池 | 碳酸锂、氢氧化锂、钴酸锂 |

---

## 浏览器自动化（xbrowser）

对于需要JS渲染或登录的数据源，使用 xbrowser Skill 进行浏览器自动化。

### 专利数据自动化流程

```bash
# 1. 打开CNIPA公共服务平台
xb open https://ggfw.cnipa.gov.cn/home

# 2. 截图确认页面加载
xb snapshot
xb screenshot

# 3. 点击"专利检索及分析系统"（导航栏菜单）
# 需要先用 xb snapshot -i 获取元素引用

# 4. 在搜索框输入公司名称
xb act click ref:xxx
xb act type ref:xxx text:小米

# 5. 点击搜索按钮
xb act click ref:yyy

# 6. 等待结果加载后截图
xb wait 3000
xb screenshot
```

### 大宗商品价格自动化流程

```bash
# DRAMeXchange 价格抓取
xb open https://www.dramexchange.com/
xb snapshot -i
# 找到DRAM价格相关链接并点击
# 截图记录当前价格

# LME 金属价格
xb open https://www.lme.com/en/Metals
xb snapshot -i
# 查找铜/铝/锌等品种价格
```

### xbrowser 关键命令

| 命令 | 说明 |
|------|------|
| `xb status` | 查看浏览器状态 |
| `xb open <url>` | 打开URL |
| `xb snapshot` | 获取页面快照 |
| `xb snapshot -i` | 获取带元素引用的快照（用于后续click/type） |
| `xb screenshot` | 截图 |
| `xb screenshot --full-page` | 全页面截图 |
| `xb act click ref:<id>` | 点击元素 |
| `xb act type ref:<id> text:<text>` | 输入文本 |
| `xb wait <ms>` | 等待毫秒 |

---

## 快速开始

```bash
# 安装依赖
pip install requests pdfplumber pandas -q

# 完整深度分析（推荐）
python analyze.py --stock 600519 --full

# 核心估值分析
python analyze.py --stock 002180 --dims multi_year_trend,valuation,earnings_forecast

# 港股深度分析
python analyze.py --stock 06939 --market hk --full

# THSDK 自然语言选股
python scripts/thsdk_search.py nlp "人工智能概念股"
python scripts/thsdk_search.py quote 600519

# 专利情报追踪
python scripts/patent_tracker.py --company "小米集团" --stock 01810.HK --market hk

# 供应链成本分析
python scripts/supply_cost_tracker.py --industry "消费电子" --company "小米集团"
```
