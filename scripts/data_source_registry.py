# -*- coding: utf-8 -*-
"""
data_source_registry.py - 数据源注册表（MCP 优先架构）
=====================================================

背景（2026-10-16 审计结论）：
    本 Skill 早期编程未考虑 MCP 接口，A股/港股/美股各维度几乎全部依赖
    东方财富逆向 API、巨潮爬虫、Bing CN 网页搜索、问财(iwencai)等
    **不可靠数据源**，导致"分析出来的内容有问题"。

本模块是数据源层的单一事实来源（Single Source of Truth）：
    每个分析维度 → 首选数据源 → 备选 → 已废弃源 + MCP 替换目标。

架构分层（优先级从高到低）：
    Tier 1  MCP         结构化金融 MCP（dzh-mcp / alphapai-lite-mcp）
    Tier 2  OFFICIAL    官方一手接口（SEC XBRL、交易所官网）
    Tier 3  API         结构化 API（东方财富逆向接口、Tushare、THSDK）
    Tier 4  CRAWLER     爬虫（巨潮 PDF、港交所 Playwright）
    Tier 5  WEBSEARCH   搜索引擎摘要（最不可靠，仅作线索发现）
    Tier 6  IWENCAI     第三方 AI 搜索聚合（问财，二手中的二手）

铁律（对应五段式输出协议"缺口不得写成结论"）：
    1. 任何维度优先走 Tier 1/2；Tier 3 起须在结果 _meta.source 标注层级。
    2. Tier 5/6 结果**不得**作为财务数字、股权结构、估值等关键结论来源。
    3. 所有数据源均失败 → 返回 {'error': ...}，**禁止**用默认值填充。
    4. 代码格式必须按目标源转换（见 CODE_FORMATS）。

用法：
    from data_source_registry import (SOURCE_REGISTRY, DEPRECATED_SOURCES,
                                      to_dzh_code, to_alphapai_code,
                                      get_plan_for_dim, is_deprecated)
"""

from __future__ import annotations
from typing import Dict, List, Optional

# ============================================================
# 层级定义
# ============================================================
TIER_LABELS = {
    0: 'T0-COMPOSITE',
    1: 'T1-MCP',
    2: 'T2-OFFICIAL',
    3: 'T3-API',
    4: 'T4-CRAWLER',
    5: 'T5-WEBSEARCH',
    6: 'T6-IWENCAI',
}

# ============================================================
# 代码格式转换
# ============================================================
def to_dzh_code(code: str, market: str = 'a') -> str:
    """6位/裸代码 → 大智慧标准格式：SH600000 / SZ000001 / BJ920262 / HK00669"""
    code = str(code).strip().upper().replace('.SH', '').replace('.SZ', '').replace('.BJ', '').replace('.HK', '')
    if market in ('a', 'cn', 'bse'):
        if code.startswith('6'):
            return f'SH{code}'
        if code.startswith(('8', '4', '920')):
            return f'BJ{code}'
        return f'SZ{code}'
    if market in ('hk',):
        return f'HK{code.zfill(5)}'
    if market in ('us',):
        # 🔴 大智慧美股必须带交易所前缀（2026-10-21 实测：getUsProfitData 要 NSAAPL）：
        #    NS=纳斯达克 / NY=纽交所 / AM=美交所。裸 ticker 默认补 NS，NYSE 标的不命中时改 NY。
        if code.startswith(('NS', 'NY', 'AM')) and len(code) > 2:
            return code
        return f'NS{code}'
    return code


def to_alphapai_code(code: str, market: str = 'a') -> str:
    """6位/裸代码 → Alpha派格式：600519.SH / 000001.SZ / 00700.HK / MSFT.US / 830799.BJ

    北交所（market='bse' 或代码前缀 8/4/920）统一生成 .BJ 后缀，供 Wind MCP 调用。
    """
    code = str(code).strip().upper()
    if '.' in code:  # 已是标准格式
        return code
    if market in ('a', 'cn', 'bse'):
        if code.startswith('6'):
            return f'{code}.SH'
        if code.startswith(('8', '4', '920')):
            return f'{code}.BJ'
        return f'{code}.SZ'
    if market in ('hk',):
        return f'{code.zfill(5)}.HK'
    if market in ('us',):
        return f'{code}.US'
    return code


# 美股 Wind 后缀：.O=NASDAQ / .N=NYSE / .A=AMEX
US_WIND_EXCHANGE_SUFFIXES = ('.O', '.N', '.A', '.OQ', '.NQ', '.AM')


def to_wind_code(code: str, market: str = 'a') -> str:
    """股票代码 → Wind windcode：600519.SH / 000001.SZ / 830799.BJ / 00700.HK / AAPL.O

    与 to_alphapai_code 的差异（2026-10-21 港美股接入时确立）：
      - A股/北交所/港股：完全一致（Wind 沿用 .SH/.SZ/.BJ/.HK）。
      - **美股**：Wind 要交易所后缀 .O(NASDAQ)/.N(NYSE)/.A(AMEX)，不是 .US。
        裸 ticker 默认补 .O（纳斯达克占多数），NYSE 标的不命中时须改 .N —— 见
        mcp_plan.json 该调用的 note。已带后缀的（AAPL.O / BRK.A）原样透传。
    """
    code = str(code).strip().upper()
    if market in ('us',):
        if code.endswith(US_WIND_EXCHANGE_SUFFIXES):
            return code  # 已显式带交易所后缀（AAPL.O / BRK.B.N）
        return f'{code}.O'  # 裸 ticker 或 类别股（BRK.B → BRK.B.O）默认补 .O
    return to_alphapai_code(code, market)


# ============================================================
# MCP 连接器状态（2026-10-19 实测：蟹老板已 OAuth 授权；wind-finance 2026-10-21 实测可用）
# ============================================================
# 调用特性注意：
#   - wind-finance（万得，2026-10-21 起设为主力源）：机构级 T1 数据源，覆盖行情快照
#       (get_stock_price_indicators，含 PE/PB/PS(TTM)/总市值/主力净流入)、分钟量价
#       (get_stock_quote)、K线(get_stock_kline)、财务+衍生估值(get_stock_fundamentals)、
#       股东结构(get_stock_equity_holders)、公司档案(get_stock_basicinfo)、公告原文
#       (get_company_announcements)。代码格式 600519.SH（= to_alphapai_code）。
#       → 2026-10-21 实测 688585.SH 返回与东财完全一致（价112.90 / PE -293.14 / PB 38.69 /
#         总市值455.4亿），数据权威，接管原 dzh-mcp 主场的财务/行情/估值/股东/公告/档案维度。
#   - dzh-mcp：快、稳；自 2026-10-21 起降为 Wind 之后的 T1 备选（财务/行情/估值/股东/公告/
#       档案维度作 Wind 失败兜底，研报/龙虎榜/融资融券/分时资金流仍为其独有主场）。
#   - alphapai-lite-mcp：慢（单次 30~60s）+ 偶发 504 Gateway Timeout。
#        → 一律作 T1 备选（fallback），Agent 侧须设长超时并失败重试 1 次，
#          不得作为关键财务/估值主源（避免 504 触发红灯误杀）。
#   - qcc-company：工商 T+0，权威；但检索键必须是「企业精确全称 / 18位统一社会信用代码」，
#       不是股票代码。无匹配时返回 {'无匹配项':...} 或 {'匹配结果':'多候选'}（干净报错，
#       不崩）。Agent 侧须先用量价/quote 维度确认公司全称，或用 get_company_by_query 解析。
MCP_STATUS = {
    'dzh-mcp': 'connected',              # 大智慧金融 MCP，24 工具（2026-10-21 起降为 Wind 之后的 T1 备选）
    'alphapai-lite-mcp': 'connected',    # Alpha派 Lite，公告解析+结构化数据+会议纪要
    'qcc-company': 'connected',          # 企查查，工商/股权穿透/实控人/UBO/高管/风险扫描/知产
    'wind-finance': 'connected',         # 万得金融 MCP（2026-10-21 实测可用，设为主力源）
    'tdx-connector': 'disabled',
}


def mcp_available() -> List[str]:
    """返回当前可用的 MCP 连接器名（供 analyze.py 决定走 MCP 还是降级报错）"""
    return [k for k, v in MCP_STATUS.items() if v == 'connected']


# ============================================================
# 数据源注册表：dim → 源链
# ============================================================
# 每个维度：
#   mcp_primary:   [(connector, tool, note), ...]   Tier1 首选
#   mcp_fallback:  [...]                             Tier1 备选
#   legacy:        [(module, tier, note), ...]      Tier3-6 传统源（将被逐步替换）
#   deprecated:    [module, ...]                    已判定不可靠、禁止作主源
SOURCE_REGISTRY: Dict[str, dict] = {

    # ---------- A股 ----------
    'financial': {
        'label': '财务报表（三大表）',
        'mcp_primary': [
            ('wind-finance', 'get_stock_fundamentals', '三大表+财务比率+衍生估值（Wind 主力，自然语言问报表科目）'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getStockCorpProfit', '利润表'),
            ('dzh-mcp', 'getBalanceSheetMetrics', '资产负债表'),
            ('dzh-mcp', 'getStockXjllData', '现金流量表'),
            ('alphapai-lite-mcp', 'query_financial_data', 'A股财务指标自然语言查询'),
        ],
        'legacy': [
            ('scripts.financials', 3, '东方财富 datacenter-web 逆向 API'),
            ('scripts.pdf_download', 4, '年报 PDF 提取'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'structure': {
        'label': '股权结构 / 实控人穿透',
        'mcp_primary': [
            ('wind-finance', 'get_stock_equity_holders', '十大股东/控股股东/实控人详情（Wind 主力）'),
            ('qcc-company', 'get_actual_controller', '实控人穿透（T+0 工商，比十大股东更权威）'),
            ('qcc-company', 'get_beneficial_owners', '受益所有人 UBO（AML 口径）'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getF10HolderDetailsData', '十大股东/十大流通股东（一层）'),
            ('alphapai-lite-mcp', 'query_financial_data', '股东结构自然语言查询'),
        ],
        'legacy': [],
        'deprecated': [
            ('scripts.iwencai_provider', 6, '问财 AI 聚合，二手且接口易变'),
            ('scripts.iwencai_adapter', 6, '问财适配层'),
        ],
        'critical': True,
    },
    'pledge': {
        'label': '股权质押 / 冻结明细',
        'mcp_primary': [
            ('qcc-company', 'get_stock_pledge_info', '上市公司股权质押（质权人/股数/市值/状态/公告日，T+0）'),
            ('qcc-company', 'get_equity_pledge_info', '企业当前在册出质记录（出质人/质权人/数额/登记日）'),
        ],
        'mcp_fallback': [],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },
    'announcements': {
        'label': '公告全景',
        'mcp_primary': [
            ('wind-finance', 'get_company_announcements', '官方披露原文检索（Wind 主力）'),
            ('dzh-mcp', 'getF10TbGgMoData', '公司公告列表（标题/日期/PDF链接）'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'search_announcements', '公告检索（可按类型/报告期筛选）'),
        ],
        'legacy': [
            ('scripts.announcements', 3, '东方财富 np-anotice-stock 逆向 API'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'annual_pdf': {
        'label': '年报/公告正文（PDF解析）',
        'mcp_primary': [
            ('alphapai-lite-mcp', 'search_announcements', '先检索拿 announcementId'),
            ('alphapai-lite-mcp', 'download_announcement_parsing', 'MinerU 解析正文 markdown'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getF10TbGgMoData', '公告列表含 PDF 链接'),
        ],
        'legacy': [
            ('scripts.pdf_download', 4, '巨潮/上交所/北交所 PDF 爬虫'),
            ('scripts.hkex_announcements', 4, '港交所披露易 Playwright'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'executives': {
        'label': '高管动态 / 董监高',
        'mcp_primary': [
            ('dzh-mcp', 'getF10GsjsData', '公司简况（含董监高、工商、治理信息）'),
            ('qcc-company', 'get_key_personnel', '董监高 T+0 工商口径'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'query_financial_data', '高管信息自然语言查询'),
        ],
        'legacy': [
            ('scripts.executives', 3, '东方财富公告关键词抓取'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'industry': {
        'label': '行业 / 主营构成',
        'mcp_primary': [
            ('wind-finance', 'get_stock_basicinfo', 'WIND行业分类/概念/主营/上市板（Wind 主力）'),
            ('dzh-mcp', 'getF10BusiinfoData', '主营产品/行业/地区收入'),
            ('dzh-mcp', 'getBlockIndustryObj', '行业板块成分股（做同业对比）'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'query_financial_data', '行业分类与收入结构'),
        ],
        'legacy': [
            ('scripts.industry', 3, '东方财富 F10 行业分类'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'share_history': {
        'label': '分红送转 / 股本变动',
        'mcp_primary': [
            ('dzh-mcp', 'getF10DividentsData', '历年分红方案/除权日/股利支付率'),
        ],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.share_history', 3, '东方财富 + Tushare 分红/解禁'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'institutional': {
        'label': '机构持仓 / 机构调研',
        'mcp_primary': [
            ('dzh-mcp', 'getF10HolderDetailsData', '十大股东（含机构）'),
            ('dzh-mcp', 'getTrs0031Data', '机构调研记录'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'recall_knowledge', 'recallType=roadShow_ir 官方IR路演'),
        ],
        'legacy': [
            ('scripts.institutional', 3, '东方财富机构持仓'),
        ],
        'deprecated': [
            ('scripts.iwencai_provider', 6, '问财 AI 聚合'),
        ],
        'critical': False,
    },
    'quote': {
        'label': '实时行情',
        'mcp_primary': [
            ('wind-finance', 'get_stock_price_indicators', '实时行情快照（Wind 主力，含PE/PB/市值/主力净流入）'),
            ('wind-finance', 'get_stock_quote', '分钟级量价序列'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getQuoteDyna', 'A股实时行情（支持批量）'),
        ],
        'legacy': [
            ('scripts.thsdk_search', 3, 'THSDK 游客账号'),
            ('scripts.bse_price', 3, '东方财富行情逆向 API'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'kline': {
        'label': 'K线 / 历史行情',
        'mcp_primary': [
            ('wind-finance', 'get_stock_kline', '日K/周K/月K（Wind 主力，复权可选）'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getQuoteKline', 'A股K线（多周期/复权）'),
            ('dzh-mcp', 'getGmQuoteKline', '港美股K线'),
        ],
        'legacy': [
            ('scripts.thsdk_search', 3, 'THSDK K线'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'valuation': {
        'label': '估值（PE/PB/市值）',
        'mcp_primary': [
            ('wind-finance', 'get_stock_price_indicators', 'PE/PB/PS(TTM)/总市值/流通市值（Wind 主力）'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getQuoteDyna', '实时价+市值+PE/PB'),
            ('alphapai-lite-mcp', 'query_financial_data', '估值指标（A/H股）'),
        ],
        'legacy': [
            ('scripts.valuation', 3, '东方财富 + THSDK'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'research_report': {
        'label': '机构研报 / 评级 / 目标价',
        'mcp_primary': [
            ('dzh-mcp', 'getFfjgrgYbmxData', '机构研报（评级/目标价/原文链接）'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'recall_knowledge', 'recallType=report 研报召回'),
        ],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },
    'news': {
        'label': '新闻舆情',
        'mcp_primary': [
            ('dzh-mcp', 'getNewsTextStockData', '个股新闻舆情（标题/摘要/正文/来源）'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'search_wechat_articles', '公众号文章'),
        ],
        'legacy': [],
        'deprecated': [
            ('scripts.websearch', 5, 'Bing CN 网页搜索摘要，非结构化二手'),
        ],
        'critical': False,
    },
    'capital_flow': {
        'label': '资金流向',
        'mcp_primary': [
            ('wind-finance', 'get_stock_price_indicators', '主力净流入/近5·10·20日（Wind 主力）'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getCapitalinflowMin', '分时资金流向（小/中/大/特大单）'),
        ],
        'legacy': [
            ('scripts.thsdk_search', 3, 'THSDK DDE'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'concept': {
        'label': '题材概念',
        'mcp_primary': [
            ('wind-finance', 'get_stock_basicinfo', '概念标签（Wind 主力）'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getF10Information', '股票题材概念'),
        ],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },
    'margin_trading': {
        'label': '融资融券',
        'mcp_primary': [
            ('dzh-mcp', 'getFinanceRzrq', '融资融券余额/买入偿还'),
        ],
        'mcp_fallback': [],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },
    'dragon_tiger': {
        'label': '龙虎榜',
        'mcp_primary': [
            ('dzh-mcp', 'getF10LhbGpmxData', '龙虎榜个股明细'),
        ],
        'mcp_fallback': [],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },

    # ---------- 法律 / 合规风险（qcc 权威源，替代 cross_validator 正则启发式） ----------
    # 审计结论（2026-10-16）：原 cross_validator 靠中文关键词+正则下"实锤"定性，
    # 对正常公司可能误判 + 合规声誉风险。qcc 提供工商 T+0 权威法律/风险数据，
    # 应先取 qcc 再交叉，且不得用 qcc 单源直接下"实锤"，须 ≥2 独立信号（见 cross_validator 护栏）。
    'legal_risk': {
        'label': '法律/合规风险（质押/诉讼/失信/处罚/风险扫描）',
        'mcp_primary': [
            ('qcc-company', 'get_company_risk_scan', '35项风险因子一键分诊'),
            ('qcc-company', 'get_stock_pledge_info', '股票质押（上市公司）'),
            ('qcc-company', 'get_equity_pledge_info', '股东股权质押'),
            ('qcc-company', 'get_case_filing_info', '立案/诉讼'),
            ('qcc-company', 'get_judgment_debtor_info', '被执行人'),
            ('qcc-company', 'get_dishonest_info', '失信'),
            ('qcc-company', 'get_company_related_risk_scan', '关联方风险传导'),
        ],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.cross_validator', 3, '正则启发式风险探测（仅作交叉印证，不得单独下"实锤"结论）'),
        ],
        'deprecated': [
            ('scripts.iwencai_provider', 6, '问财 AI 聚合'),
        ],
        'critical': False,
    },
    'intellectual_property': {
        'label': '知识产权（专利/商标）',
        'mcp_primary': [
            ('qcc-company', 'get_patent_info', '专利'),
            ('qcc-company', 'get_trademark_info', '商标'),
        ],
        'mcp_fallback': [],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },

    # ---------- 港股 ----------
    # 2026-10-21：Wind 升为港美股行情/估值/K线主力源（实测 00700.HK 可用）；
    # dzh 港股三大表（getHk*）与港美股行情（getGm*）作 T1 备选/结构化兜底。
    'hk_financial': {
        'label': '港股财务',
        'mcp_primary': [
            ('wind-finance', 'get_stock_fundamentals', '港股财务+衍生指标（Wind 主力源，保留原币种）'),
            ('dzh-mcp', 'getHkIncomeStatementData', '港股利润表（最新报告期，结构化字段）'),
            ('dzh-mcp', 'getHkBalanceSheetData', '港股资产负债表（最新报告期）'),
            ('dzh-mcp', 'getHkCashFlowStatementData', '港股现金流量表（最新报告期）'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'query_financial_data', '港股财务指标自然语言查询（慢，须长超时+重试1次）'),
        ],
        'legacy': [
            ('scripts.hk_financial', 3, 'AKShare 港股财务（库易失效）'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'hk_quote': {
        'label': '港股行情 / 估值 / K线',
        'mcp_primary': [
            ('wind-finance', 'get_stock_price_indicators', '港股行情+PE/PB/市值/52周（Wind 主力源）'),
            ('wind-finance', 'get_stock_kline', '港股日K线（Wind 主力源）'),
            ('dzh-mcp', 'getGmQuoteDyna', '港美股实时行情（备选）'),
            ('dzh-mcp', 'getGmQuoteKline', '港美股K线（备选）'),
        ],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.thsdk_search', 3, 'THSDK 港股行情'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'hk_meeting_minutes': {
        'label': '港股/美股会议纪要',
        'mcp_primary': [
            ('alphapai-lite-mcp', 'search_meeting_minutes', 'HK/US 业绩会纪要列表'),
            ('alphapai-lite-mcp', 'get_meeting_minutes_detail', '纪要正文 ai_note'),
        ],
        'mcp_fallback': [],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },
    'hk_structure': {
        'label': '港股股东结构',
        # 港美股不走 qcc（企查查只覆盖境内工商主体），股东以 Wind 为主、dzh F10 兜底
        'mcp_primary': [
            ('wind-finance', 'get_stock_equity_holders', '港股股东结构/实控人/解禁（Wind 主力源）'),
            ('dzh-mcp', 'getF10HolderDetailsData', '港股十大股东（备选）'),
        ],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.hkex_announcements', 2, '港交所披露易（股权披露，PDF 解析）'),
        ],
        'deprecated': [],
        'critical': False,
    },
    # ---------- 港股股权质押 ----------
    # 🔴 企查查只覆盖境内工商主体（A股/北交所），不覆盖港股；qcc 股权质押工具对港股无数据。
    #   港股质押/股份抵押以港交所披露易官方披露为准（scripts.hkex_announcements T2 crawler，
    #   当前未接通专用 MCP）。故 mcp_primary 留空，apply_backfill 统一标 gap 由人工补。
    'hk_pledge': {
        'label': '港股股权质押 / 冻结',
        'mcp_primary': [],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.hkex_announcements', 2, '港交所披露易「股份抵押」股权披露（官方，最权威；当前为 crawler 未 MCP 化）'),
        ],
        'deprecated': [],
        'critical': False,
    },

    # ---------- 美股 ----------
    'us_financial': {
        'label': '美股财务',
        'mcp_primary': [
            ('wind-finance', 'get_stock_fundamentals', '美股财务+衍生指标（Wind 主力源，单位美元）'),
            ('dzh-mcp', 'getUsProfitData', '美股利润表（最新报告期；符号需 NSAAPL 交易所前缀）'),
            ('dzh-mcp', 'getUsBalanceSheetData', '美股资产负债表（最新报告期）'),
            ('dzh-mcp', 'getUsCashFlowData', '美股现金流量表（最新报告期）'),
        ],
        'mcp_fallback': [
            ('alphapai-lite-mcp', 'query_financial_data', '美股财务自然语言查询（慢，须长超时+重试1次）'),
        ],
        'legacy': [
            ('scripts.sec_xbrl_api', 2, 'SEC XBRL 官方一手接口（保留，本就是T2）'),
            ('scripts.us_financial', 2, 'SEC EDGAR 官方'),
        ],
        'deprecated': [],
        'critical': True,
    },
    'us_quote': {
        'label': '美股行情 / 估值 / K线',
        'mcp_primary': [
            ('wind-finance', 'get_stock_price_indicators', '美股行情+PE/PB/市值（Wind 主力源；代码 AAPL.O）'),
            ('wind-finance', 'get_stock_kline', '美股日K线（Wind 主力源）'),
            ('dzh-mcp', 'getGmQuoteDyna', '美股实时行情（备选）'),
            ('dzh-mcp', 'getGmQuoteKline', '美股K线（备选）'),
        ],
        'mcp_fallback': [],
        'legacy': [],
        'deprecated': [],
        'critical': False,
    },
    'us_structure': {
        'label': '美股股东结构',
        'mcp_primary': [
            ('wind-finance', 'get_stock_equity_holders', '美股股本/主要股东（Wind 主力源）'),
            ('dzh-mcp', 'getF10HolderDetailsData', '美股主要股东（备选）'),
        ],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.us_governance', 2, 'SEC DEF 14A / 13F 机构持仓（官方，最权威）'),
        ],
        'deprecated': [],
        'critical': False,
    },
    # ---------- 美股股权质押 ----------
    # 🔴 同上：企查查不覆盖美股；美股质押/股权变动以 SEC 官方披露为准（13D/13G/Form 4）。
    #   当前 skill 未接通专用 MCP，mcp_primary 留空，apply_backfill 统一标 gap 由人工补。
    'us_pledge': {
        'label': '美股股权质押 / 股权变动',
        'mcp_primary': [],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.us_governance', 2, 'SEC 13D/13G/Form 4 股权变动披露（官方，最权威；当前为 crawler 未 MCP 化）'),
        ],
        'deprecated': [],
        'critical': False,
    },

    # ---------- 港美股：行业 / 主营 / 概念（2026-10-21 新增）----------
    # 原 `industry` 维度是东财 F10 A 股口径，港美股静默返空；改由 Wind 公司档案接管。
    'hk_industry': {
        'label': '港股行业 / 主营 / 概念',
        'mcp_primary': [
            ('wind-finance', 'get_stock_basicinfo',
             'Wind 公司档案：WIND行业明细/概念板块/主营收入构成/经营范围/风险警示'),
        ],
        'mcp_fallback': [
            ('dzh-mcp', 'getF10BusiinfoData', '港股主营构成（备选）'),
        ],
        'legacy': [
            ('scripts.industry', 3, '东方财富F10行业（A股口径，港股常空）'),
        ],
        'deprecated': [],
        'critical': False,
    },
    'us_industry': {
        'label': '美股行业 / 主营 / 概念',
        'mcp_primary': [
            ('wind-finance', 'get_stock_basicinfo',
             'Wind 公司档案：WIND行业明细/概念/主营/经营范围/风险警示'),
        ],
        'mcp_fallback': [],
        'legacy': [
            ('scripts.industry', 3, '东方财富F10行业（A股口径，美股必空）'),
            ('scripts.sec_xbrl_api', 2, 'SEC SIC 行业分类（官方，较粗）'),
        ],
        'deprecated': [],
        'critical': False,
    },
}


# ============================================================
# 按市场取维度清单（analyze.py 生成 mcp_plan.json 时用）
# ============================================================
MARKET_DIMS: Dict[str, List[str]] = {
    'a': ['quote', 'financial', 'structure', 'pledge', 'industry', 'concept',
          'announcements', 'kline', 'valuation', 'capital_flow'],
    'bse': ['quote', 'financial', 'structure', 'pledge', 'industry', 'concept',
          'announcements', 'kline', 'valuation', 'capital_flow'],
    # 港美股：行情/估值/K线（Wind 主力）+ 财务（Wind + dzh 三表）+ 股东结构 + 行业 + 会议纪要
    #   + 质押（hk_pledge/us_pledge：企查查不覆盖，标 gap 由人工补官方源）
    'hk': ['hk_quote', 'hk_financial', 'hk_structure', 'hk_pledge', 'hk_industry', 'hk_meeting_minutes'],
    'us': ['us_quote', 'us_financial', 'us_structure', 'us_pledge', 'us_industry'],
}


def get_dim_spec(dim: str, market: str = 'a') -> Optional[dict]:
    """取某维度在某市场的源规格。

    港美股已有专属维度（hk_financial / us_quote …），直接用；若调用方误传通用维度
    （如 market='us' 传 'financial'），自动映射到该市场的专属维度，避免拿到 A 股源。
    """
    if market in ('hk', 'us') and not dim.startswith(market + '_'):
        mapped = f'{market}_{dim}'
        if mapped in SOURCE_REGISTRY:
            return SOURCE_REGISTRY.get(mapped)
    return SOURCE_REGISTRY.get(dim)

# ============================================================
# 全局废弃源清单（任何维度都不得作为主源）
# ============================================================
DEPRECATED_SOURCES: Dict[str, dict] = {
    'scripts.websearch': {
        'reason': 'Bing CN 网页搜索摘要，非结构化二手内容；无时间戳/口径保证',
        'replacement': 'dzh-mcp.getNewsTextStockData / alphapai-lite-mcp.search_announcements',
        'tier': 5,
    },
    'scripts.iwencai_provider': {
        'reason': '问财是第三方 AI 搜索聚合（抓取东财等），接口易变、结果可能过时错配',
        'replacement': 'dzh-mcp.getF10HolderDetailsData / getF10GsjsData',
        'tier': 6,
    },
    'scripts.iwencai_adapter': {
        'reason': '问财适配层，同上',
        'replacement': '同上',
        'tier': 6,
    },
    'scripts.free_data_provider': {
        'reason': '免费数据聚合爬虫，无稳定性与溯源保证',
        'replacement': 'dzh-mcp / alphapai-lite-mcp',
        'tier': 4,
    },
    'scripts.gsxt_crawler': {
        'reason': '企查查爬虫；反爬强、无稳定保证；现已有 qcc-company MCP（T1）替代',
        'replacement': 'qcc-company（get_company_registration_info / get_actual_controller / get_shareholder_info）',
        'tier': 4,
    },
}


def is_deprecated(module: str) -> bool:
    """判断某模块是否已列入废弃清单"""
    return module in DEPRECATED_SOURCES or any(
        module in s for s in DEPRECATED_SOURCES
    )


def get_plan_for_dim(dim: str) -> Optional[dict]:
    """取某维度的数据源计划；不存在返回 None"""
    return SOURCE_REGISTRY.get(dim)


def format_registry_table() -> str:
    """生成 Markdown 数据源映射表（供报告/文档引用）"""
    lines = [
        '\n\n---\n\n## 📡 数据源映射表（MCP 优先架构 · 2026-10-19）\n',
        '| 维度 | T1 首选（MCP） | T1 备选 | 传统源（层级） | 已废弃 | 核心维度 |',
        '|---|---|---|---|---|:---:|',
    ]
    for dim, spec in SOURCE_REGISTRY.items():
        prim = '<br>'.join(f'`{t}`' for _, t, _ in spec['mcp_primary']) or '—'
        fb = '<br>'.join(f'`{t}`' for _, t, _ in spec['mcp_fallback']) or '—'
        legacy = '<br>'.join(
            f'`{m.split(".")[-1]}` ({TIER_LABELS.get(t, t)})' for m, t, _ in spec['legacy']
        ) or '—'
        dep = '<br>'.join(f'`{m.split(".")[-1]}`' for m, _, _ in spec['deprecated']) or '—'
        crit = '🔴' if spec.get('critical') else ''
        lines.append(f"| {spec['label']} | {prim} | {fb} | {legacy} | {dep} | {crit} |")
    lines.append('')
    lines.append('> T1-MCP 结构化金融MCP / T2-OFFICIAL 官方接口 / T3-API 逆向API / '
                 'T4-CRAWLER 爬虫 / T5-WEBSEARCH 搜索摘要 / T6-IWENCAI 问财聚合')
    return '\n'.join(lines)


# ============================================================
# CLI
# ============================================================
if __name__ == '__main__':
    print(f"已注册维度: {len(SOURCE_REGISTRY)}")
    print(f"废弃源: {len(DEPRECATED_SOURCES)}")
    print(f"当前可用 MCP: {mcp_available() or '（无，需先 OAuth 授权）'}")
    print()
    for code, mkt in [('600519', 'a'), ('000001', 'a'), ('00700', 'hk'), ('AAPL', 'us')]:
        print(f"  {code}({mkt}) → dzh:{to_dzh_code(code, mkt)}  alphapai:{to_alphapai_code(code, mkt)}")
    print()
    print(format_registry_table())
