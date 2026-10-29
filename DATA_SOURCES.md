# 数据源参考手册（listed-company-analysis）

> 本文件是 `SKILL.md` 的**参考 companion**，收录各数据源的 CLI / Python 调用细节、代码规则、能力边界。
> 这些属于"查的时候再看"的文档，**不进 SKILL.md 主指令**，避免每次调用 skill 时加载过厚。
> 决策逻辑与铁律仍在 `SKILL.md`（MCP 优先架构、回填规则、qcc 纪律等）。

---

## 数据源架构铁律（回顾，详见 SKILL.md）

- **MCP 优先**：`wind-finance`（主力）/ `dzh-mcp`（备选）/ `alphapai-lite-mcp`（公告+MinerU+IR）/ `qcc-company`（工商穿透）。
- **Python 无法直接调 MCP**：`analyze.py` 生成 `data/mcp_plan.json` → Agent 按计划调 MCP → 落 `data/mcp_data/*.json` → `apply_backfill` 合并。未回填=缺口，禁止默认值顶替。
- 已废弃源（任何维度不得作主源）：`websearch`(Bing)、`iwencai_provider`、`free_data_provider`、`gsxt_crawler`。

---

## Tushare 数据源（补充）

**文件**：`scripts/tushare_data.py`

**用途**：补充分红送股、解禁时间表数据（东方财富 API 没有的历史数据）

**使用方法**：
```bash
# 测试分红数据
python scripts/tushare_data.py --stock 000001 --dividend

# 测试解禁数据
python scripts/tushare_data.py --stock 000001 --float

# 全部数据
python scripts/tushare_data.py --stock 000001 --all
```

**Python 调用**：
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
| 东方财富 API | 近10年 | 近1年 | 实时更新 |
| Tushare | 上市以来 | 未来1年 | 历史完整 |

**Token 配置**：注册 https://tushare.pro 获取免费版 Token（120积分/日），存 `skills/listed-company-analysis/.tushare_token`（已加 `.gitignore`）或设环境变量 `TUSHARE_TOKEN`。
权限：✅ daily/dividend/share_float/company；❌ 财务三表、PE/PB 估值、资金流向、概念板块。

---

## THSDK 数据源（同花顺 SDK v2 — 实时行情+自然语言选股+美股）

**文件**：`scripts/thsdk_search.py` **v2**

**用途**：实时行情（A股30+字段/港股/美股）、K线（含分钟级）、板块数据、自然语言选股、DDE 大单流向、五档盘口、分红历史、竞价异动、资讯快讯

**安装**：`pip install --upgrade thsdk`（当前 v1.7.18，游客账号免费可用）

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

### THS 代码规则

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

> `code_to_ths()` 自动转换6位代码→THS代码，`quote_us()` 自动搜索获取正确的 THS 代码，无需手动拼。

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
- 美股K线不可用（THS代码格式不兼容：UNQQAAPL 不符合"4位市场+6位数字"规则）
- 美股买1/卖1价量在游客模式下返回 int32 最大值（无效）
- 美股 depth/call_auction 超时不可用
- 正式账号配置：`THS({'username': '...', 'password': '...', 'mac': '...'})`

---

## TDX 数据源（通达信官方 API — 公司信息+股本结构+高管+资金流向+热点题材）

**文件**：`scripts/tdx_provider.py`

**用途**：公司基本信息（完整公司介绍/产品构成/行业/高管）、股本结构（历史总股本/流通股本/限售股变动）、董监高信息、资金流向、热点题材板块族谱等

**API 地址**：`http://tdxhub.icfqs.com:7615/TQLEX`

**Token 配置**：通过环境变量 `TDX_API_TOKEN` 配置（`os.environ.get("TDX_API_TOKEN", "")`，**无内置硬编码 token**）。

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

| 数据维度 | 东方财富/巨潮 | THSDK | Tushare | **通达信 TDX** |
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
- **缓存 key**：`tdx_{code}_{type}.json`

### 限制
- 仅支持**A股**（市场代码为沪市6位代码或深市6位代码）
- Token 内置但可能有频率限制（0.5秒/次）
- 部分 API 参数固定为特定值（固定查询）
- 非实时行情数据（主要用于公司基本面/结构信息）
- 如需实时行情，仍推荐使用 THSDK

---

## 专利情报追踪模块（patent_tracker）

对任意公司进行专利情报追踪，支持 A股/港股/美股/未上市企业。

### 数据源实测可访问性

| 数据源 | 域名 | 状态 | 备注 |
|--------|------|------|------|
| CNIPA主站 | `www.cnipa.gov.cn` | ✅ 可访问 | 官方入口 |
| CNIPA公共服务平台 | `ggfw.cnipa.gov.cn` | ✅ 可访问 | 专利公布公告等 |
| CNIPA旧检索系统 | `pss-system.cnipa.gov.cn` | ❌ DNS屏蔽 | 不可用 |
| CNIPA新检索系统 | `cpquery.cponline.cnipa.gov.cn` | ⚠️ JS需登录 | 需等待渲染 |
| SooPAT | `www.soopat.com` | ✅ 可访问 | 第三方搜索，推荐 |
| Patentics | `www.patentics.com` | ✅ DNS可用 | 全球专利 |
| 大为 Innojoy | `www.innojoy.com` | ✅ DNS可用 | 全球专利 |
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
- **中国专利局**：CNIPA 公共服务平台入口、SooPAT 搜索地址
- **全球专利**：Patentics 替代 Google Patents
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

### 数据源实测可访问性

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

对于需要 JS 渲染或登录的数据源，使用 xbrowser Skill 进行浏览器自动化。

### 专利数据自动化流程

```bash
# 1. 打开CNIPA公共服务平台
xb open https://ggfw.cnipa.gov.cn/home
# 2. 截图确认页面加载
xb snapshot
xb screenshot
# 3. 点击"专利检索及分析系统"（导航栏菜单，需先用 xb snapshot -i 获取元素引用）
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
# 找到DRAM价格相关链接并点击，截图记录当前价格

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
| `xb snapshot -i` | 获取带元素引用的快照（用于后续 click/type） |
| `xb screenshot` | 截图 |
| `xb screenshot --full-page` | 全页面截图 |
| `xb act click ref:<id>` | 点击元素 |
| `xb act type ref:<id> text:<text>` | 输入文本 |
| `xb wait <ms>` | 等待毫秒 |
