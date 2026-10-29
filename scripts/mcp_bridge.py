# -*- coding: utf-8 -*-
"""
mcp_bridge.py - MCP 调用桥（指令文件 + 回填模式）
=================================================

问题：本 Skill 是 Python 脚本（analyze.py），**无法直接调用 MCP 工具**——
MCP 工具只在 AI Agent 侧可用（dzh-mcp / alphapai-lite-mcp / qcc-company）。

方案：采用"指令文件 + 回填"模式（与 scripts/llm_config.py 的 WorkBuddy
文件 IPC 模式同构）：

    ┌──────────────┐  1. 生成 mcp_plan.json  ┌──────────────┐
    │  analyze.py  │ ───────────────────────→ │  AI Agent    │
    │  (Python)    │                         │  (WorkBuddy) │
    │              │ ←─────────────────────── │              │
    └──────────────┘  3. 读 mcp_data/*.json  └──────────────┘
                             ↑ 2. Agent 按计划调 MCP 并落盘

铁律（对应五段式输出协议）：
    1. 计划里的每个调用都必须被执行；**未回填 = 数据缺口，不得用默认值顶替**。
    2. Agent 回填时必须原样保留 MCP 返回值，不得改写/补数。
    3. MCP 调用失败 → 在回填文件写 {'error': ..., 'mcp': tool}，
       analyze.py 据此标 🔴 红灯，而不是静默降级到爬虫。

用法：
    # analyze.py 侧
    from mcp_bridge import build_mcp_plan, load_mcp_results, save_mcp_result
    plan = build_mcp_plan(stock='002180', market='a', dims=['financial','structure'],
                          company_name='纳思达股份有限公司')
    # → output/xxx/data/mcp_plan.json

    # AI Agent 侧（按 plan 调 MCP 后）
    save_mcp_result(data_dir, 'financial', 'dzh-mcp', 'getStockCorpProfit',
                    {...MCP原始返回...})
"""

from __future__ import annotations
import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional

from data_source_registry import (
    SOURCE_REGISTRY, MCP_STATUS, mcp_available, MARKET_DIMS, get_dim_spec,
    to_dzh_code, to_alphapai_code, to_wind_code, TIER_LABELS,
)

MCP_PLAN_FILE = 'mcp_plan.json'
MCP_DATA_SUBDIR = 'mcp_data'


# ============================================================
# 计划生成
# ============================================================
def build_mcp_plan(stock: str, market: str, dims: List[str],
                   extra: dict = None, company_name: str = None) -> dict:
    """
    为本次分析生成 MCP 调用计划。

    Args:
        company_name: 公司精确全称 / 统一社会信用代码（qcc-company 检索键，非股票代码）。
                      若未知，Agent 须先用 get_company_by_query 解析后再回填 qcc 调用。

    Returns:
        {
          'stock': ..., 'market': ..., 'company_name': ..., 'created_at': ...,
          'available_mcp': [...],
          'calls': [ {'id', 'dim', 'connector', 'tool', 'params', 'note'}, ... ]
        }
    """
    available = mcp_available()
    calls: List[dict] = []
    # 凡涉及 qcc 的维度，统一前置一条"解析全称/USCC"调用，
    # 后续 qcc 数据调用的 searchKey 用 __USCC__ 占位，须用解析结果回填。
    seen_qcc_resolve = False

    for dim in dims:
        spec = get_dim_spec(dim, market)  # 港美股自动映射到 hk_*/us_* 专属维度
        if not spec:
            continue
        # T1 首选 + 备选都进计划，Agent 按可用性取
        for connector, tool, note in (spec['mcp_primary'] + spec['mcp_fallback']):
            # 企查查：优先在首个 qcc 调用前插入"名称解析"步骤（仅一次）
            if connector == 'qcc-company' and not seen_qcc_resolve and 'qcc-company' in available:
                calls.append({
                    'id': 'qcc:get_company_by_query',
                    'dim': dim,
                    'connector': 'qcc-company',
                    'tool': 'get_company_by_query',
                    'params': {'searchKey': company_name or f'<<{stock} 实时证券简称>>'},
                    'note': ('解析企业精确全称 + 统一社会信用代码(USCC)。'
                             '若返回"多候选"，用 pick_listed_entity() 锁定与证券简称同名且含'
                             '"股份"的上市母公司，排除子公司/分公司/地域变体。'),
                    'status': 'pending',
                    'is_resolve_step': True,
                })
                seen_qcc_resolve = True
            # qcc 数据调用：searchKey 用 USCC 占位（避免证券简称多候选歧义）
            if connector == 'qcc-company':
                params = _build_params(tool, stock, market,
                                      company_name='__USCC__',  # 由解析步骤回填
                                      resolve_mode=True)
                qcc_note = (note + ' ｜ searchKey 须填 get_company_by_query 解析出的'
                            '「统一社会信用代码」，勿用证券简称或旧名。')
            else:
                params = _build_params(tool, stock, market, company_name=company_name)
                qcc_note = note
                if connector == 'wind-finance' and market == 'us' and 'windcode' in params:
                    qcc_note += (' ｜ 美股 windcode 后缀须与交易所匹配：.O=NASDAQ / .N=NYSE / '
                                 '.A=AMEX；默认按 .O 生成，若返回空先改 .N 重试再判缺口。')
            if connector not in available:
                # MCP 未授权：计划里仍记录，但标记 blocked，Agent 一眼看到缺口
                calls.append({
                    'id': f'{dim}:{tool}',
                    'dim': dim,
                    'connector': connector,
                    'tool': tool,
                    'params': params,
                    'note': qcc_note,
                    'status': 'blocked_mcp_not_connected',
                })
                continue
            calls.append({
                'id': f'{dim}:{tool}',
                'dim': dim,
                'connector': connector,
                'tool': tool,
                'params': params,
                'note': qcc_note,
                'status': 'pending',
            })

    plan = {
        'stock': stock,
        'market': market,
        'company_name': company_name,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'available_mcp': available,
        'mcp_status': MCP_STATUS,
        'calls': calls,
    }
    if extra:
        plan.update(extra)
    return plan


def pick_listed_entity(secu_abbr: str, qcc_query_result: dict) -> dict:
    """
    从企查查 get_company_by_query 的"多候选"结果中，锁定上市母公司。

    规则（2026-10-19 新增，针对 002180 由"纳思达"更名"奔图科技"类场景）：
      - 优先选 企业名称 == 证券简称 或 以证券简称为前缀 且包含 "股份" 的主体
        （股份有限公司 = 上市母公司；"珠海奔图打印科技"等子公司/分公司排除）
      - 排除：名称含 "分公司" / 明显地域前缀变体（如"新疆/上海/山东奔图"）且非股份主体
      - 返回 {name, uscc, reason}；若唯一命中直接返回
    """
    if not isinstance(qcc_query_result, dict):
        return {'name': None, 'uscc': None, 'reason': 'qcc返回非dict'}
    if qcc_query_result.get('匹配结果') == '唯一':
        ent = qcc_query_result.get('企业信息', [{}])[0] if qcc_query_result.get('企业信息') else {}
        return {'name': ent.get('企业名称'), 'uscc': ent.get('统一社会信用代码'),
                'reason': 'qcc唯一命中'}
    cands = qcc_query_result.get('企业信息') or []
    if not cands:
        return {'name': None, 'uscc': None, 'reason': 'qcc无候选'}

    abbr = (secu_abbr or '').strip()
    best, fallback = None, None
    for c in cands:
        name = c.get('企业名称', '')
        uscc = c.get('统一社会信用代码')
        # 含"股份"且名称与证券简称相关（相等或以证券简称为前缀）
        if '股份' in name and (name == abbr or name.startswith(abbr)):
            best = {'name': name, 'uscc': uscc,
                    'reason': f'含"股份"且与证券简称[{abbr}]同名/前缀匹配，判为上市母公司'}
            break
        # 兜底：名称含证券简称且无地域/分公司歧义
        if (abbr and abbr in name and '分公司' not in name
                and not any(p in name for p in ('新疆', '上海', '山东', '珠海', '北京', '广东', '深圳', '浙江', '江苏'))):
            if fallback is None:
                fallback = {'name': name, 'uscc': uscc,
                            'reason': f'名称含证券简称[{abbr}]且无地域/分公司歧义（兜底）'}
    return best or fallback or {
        'name': None, 'uscc': None,
        'reason': '无法自动锁定，请人工从候选中选择上市母公司',
        'candidates': [c.get('企业名称') for c in cands],
    }



def _build_params(tool: str, stock: str, market: str, company_name: str = None,
                  resolve_mode: bool = False) -> dict:
    """按工具构造参数（代码格式已按目标源转换）"""
    # 企查查：以「企业精确全称 / 18位统一社会信用代码」为检索键（不是股票代码）
    # Agent 侧若 company_name 未知，须先用 get_company_by_query 解析，严禁猜测。
    # resolve_mode=True 时 company_name 应为 __USCC__ 占位，由解析步骤回填。
    QCC_TOOLS = (
        'get_company_registration_info', 'get_shareholder_info', 'get_actual_controller',
        'get_beneficial_owners', 'get_key_personnel', 'get_external_investments',
        'get_company_risk_scan', 'get_company_related_risk_scan', 'get_stock_pledge_info',
        'get_equity_pledge_info', 'get_case_filing_info', 'get_judgment_debtor_info',
        'get_dishonest_info', 'get_patent_info', 'get_trademark_info', 'get_listing_info',
        'get_change_records', 'get_branches', 'get_contact_info', 'get_tax_invoice_info',
    )
    if tool in QCC_TOOLS:
        return {'searchKey': company_name or f'<<{stock} 对应公司精确全称或统一社会信用代码>>'}

    # ── Wind 主力源（2026-10-21 接入；A股/北交所/港股 600519.SH/830799.BJ/00700.HK；
    #    美股须交易所后缀 AAPL.O=NASDAQ、BRK.B.N=NYSE → 见 to_wind_code）──
    WIND_PRICE_INDEXES = (
        '最新成交价,前收盘价,今日开盘价,今日最高价,今日最低价,成交量,成交额,涨跌幅,'
        '换手率,振幅,量比,市盈率(TTM),市盈率(LYR),市净率,市净率(LF),总市值1,流通市值,'
        '总股本,当日主力净流入额,当日主力净流入占比,近5日主力净流入额,近10日主力净流入额,'
        '近20日主力净流入额,年初至今涨跌幅,52周最高,52周最低,股息率'
    )
    if tool == 'get_stock_price_indicators':
        return {'windcode': to_wind_code(stock, market), 'indexes': WIND_PRICE_INDEXES}
    if tool == 'get_stock_quote':
        return {'windcode': to_wind_code(stock, market)}
    if tool == 'get_stock_kline':
        _end = datetime.now().strftime('%Y-%m-%d')
        _begin = (datetime.now().replace(year=datetime.now().year - 1)).strftime('%Y-%m-%d')
        return {'windcode': to_wind_code(stock, market),
                'begin_date': _begin, 'end_date': _end, 'period': '10', 'aftype': '0'}
    if tool == 'get_stock_fundamentals':
        return {'question': _wind_financial_question(stock, market)}
    if tool == 'get_stock_equity_holders':
        return {'question': _wind_equity_question(stock, market)}
    if tool == 'get_stock_basicinfo':
        return {'question': _wind_basicinfo_question(stock, market)}
    if tool == 'get_company_announcements':
        return {'query': _wind_announcement_query(stock, market), 'top_k': 10}

    # 大智慧港美股三大表（2026-10-21 接入）：参数名是 symbol，不是 stockCode。
    #   港股：HK00700；美股：NSAAPL（NS=纳斯达克 / NY=纽交所 / AM=美交所）。
    if tool in ('getHkBalanceSheetData', 'getHkIncomeStatementData',
                'getHkCashFlowStatementData',
                'getUsBalanceSheetData', 'getUsProfitData', 'getUsCashFlowData'):
        return {'symbol': to_dzh_code(stock, market)}

    if tool in ('getStockCorpProfit', 'getBalanceSheetMetrics', 'getStockXjllData',
                'getF10HolderDetailsData', 'getF10GsjsData', 'getF10BusiinfoData',
                'getF10DividentsData', 'getF10Information', 'getF10TbGgMoData',
                'getFfjgrgYbmxData', 'getNewsTextStockData', 'getCapitalinflowMin',
                'getTrs0031Data', 'getF10LhbGpmxData', 'getFinanceRzrq'):
        return {'stockCode': to_dzh_code(stock, market)}
    if tool in ('getQuoteDyna', 'getGmQuoteDyna'):
        return {'stockCode': [to_dzh_code(stock, market)]}
    if tool in ('getQuoteKline', 'getGmQuoteKline'):
        return {'stockCode': to_dzh_code(stock, market), 'period': 'DAY_1', 'start': '-20'}
    if tool == 'getBlockIndustryObj':
        return {'industry': '证监会行业', 'block': ''}
    if tool == 'search_announcements':
        return {'stockCode': to_alphapai_code(stock, market), 'market': _ap_market(market),
                'pageSize': 20, 'sortBy': 'actual_publish_time', 'sortOrder': 'desc'}
    if tool == 'download_announcement_parsing':
        return {'documentType': 'announcement', 'downloadType': 'markdown',
                'documentId': '<<search_announcements 返回的 announcementId>>'}
    if tool == 'query_financial_data':
        return {'question': _financial_question(stock, market)}
    if tool == 'recall_knowledge':
        return {'query': stock, 'recallType': 'roadShow_ir'}
    if tool == 'search_meeting_minutes':
        return {'meetingMarketType': 'HK' if market == 'hk' else 'US',
                'stockCombSymbol': to_alphapai_code(stock, market), 'pageSize': 10}
    if tool == 'search_wechat_articles':
        return {'stock': to_alphapai_code(stock, market), 'pageSize': 10}
    return {}


def _ap_market(market: str) -> str:
    return {'a': 'A', 'cn': 'A', 'hk': 'HK', 'us': 'US'}.get(market, 'A')


def _financial_question(stock: str, market: str) -> str:
    """构造 query_financial_data 的自然语言问题（遵循 Alpha派提问模板）"""
    code = to_alphapai_code(stock, market)
    if market in ('a', 'cn'):
        return (f'查询{stock}（{code}）最近5个已披露年报的营业收入、归母净利润、'
                f'毛利率、ROE、经营现金流，采用合并报表口径，单位为元，按报告期升序。')
    if market == 'hk':
        return (f'查询{stock}（{code}）最近5个已披露财年的营业收入、净利润、'
                f'毛利率、ROE，采用合并报表口径，保留原币种，按财年升序。')
    return (f'查询{stock}（{code}）最近5个已披露财年的营业收入、净利润、毛利率、ROE，'
            f'采用合并报表口径，单位为美元，按财年升序。')


def _wind_financial_question(stock: str, market: str) -> str:
    """构造 Wind get_stock_fundamentals 的自然语言问题（覆盖三大表+财务比率+衍生估值）"""
    code = to_alphapai_code(stock, market)
    if market in ('a', 'cn'):
        return (f'查询{stock}（{code}）最近5个报告期的营业收入、归母净利润、毛利率、'
                f'ROE、经营现金流净额、资产负债率、总资产、净资产、每股收益，'
                f'采用合并报表口径，按报告期升序。')
    if market == 'hk':
        return (f'查询{stock}（{code}）最近5个财年的营业收入、净利润、毛利率、ROE，'
                f'采用合并报表口径，保留原币种，按财年升序。')
    return (f'查询{stock}（{code}）最近5个财年的营业收入、净利润、毛利率、ROE，'
            f'采用合并报表口径，单位为美元，按财年升序。')


def _wind_equity_question(stock: str, market: str) -> str:
    """构造 Wind get_stock_equity_holders 的自然语言问题（股东结构/实控人/解禁）"""
    code = to_alphapai_code(stock, market)
    return (f'查询{stock}（{code}）的最新报告期总股本、流通A股、限售股、前十大股东、'
            f'前十大流通股东、机构股东持股、实际控制人及限售解禁时间表。')


def _wind_basicinfo_question(stock: str, market: str) -> str:
    """构造 Wind get_stock_basicinfo 的自然语言问题（行业/概念/主营/上市板）"""
    code = to_alphapai_code(stock, market)
    return (f'查询{stock}（{code}）的上市板块、上市日期、WIND行业分类、所属概念板块、'
            f'主营业务简介、经营范围、是否风险警示（ST/退市）。')


def _wind_announcement_query(stock: str, market: str) -> str:
    """构造 Wind get_company_announcements 的自然语言检索（官方披露原文）"""
    code = to_alphapai_code(stock, market)
    return (f'查询{stock}（{code}）最近一年与重大事项相关的官方披露公告，'
            f'包括年报、季报、并购重组、要约收购、控制权变更、分红派息、'
            f'限售解禁及风险提示类公告。')


# ============================================================
# 计划读写
# ============================================================
def write_mcp_plan(data_dir: str, plan: dict) -> str:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, MCP_PLAN_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return path


def read_mcp_plan(data_dir: str) -> Optional[dict]:
    path = os.path.join(data_dir, MCP_PLAN_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# ============================================================
# 回填写入 / 读取（Agent 侧调用 save，analyze.py 侧调用 load）
# ============================================================
def save_mcp_result(data_dir: str, dim: str, connector: str, tool: str,
                    result, error: str = None) -> str:
    """
    Agent 调完 MCP 后把原始结果落盘。

    Args:
        result: MCP 原始返回（dict/list/str），原样保存不改写
        error:  调用失败时的错误说明；有 error 时 result 应为 None
    """
    subdir = os.path.join(data_dir, MCP_DATA_SUBDIR)
    os.makedirs(subdir, exist_ok=True)
    payload = {
        'dim': dim,
        'connector': connector,
        'tool': tool,
        'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'error': error,
        'result': result if error is None else None,
    }
    path = os.path.join(subdir, f'{dim}__{tool}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    return path


def load_mcp_results(data_dir: str) -> Dict[str, dict]:
    """
    读取所有已回填的 MCP 结果。

    ⚠️ 2026-10-19 修复：同一维度可能有**多个工具**回填（如 legal_risk 有
    get_company_risk_scan / get_stock_pledge_info / get_case_filing_info 等 7 个
    qcc 工具）。旧版用 out[dim] 单值覆盖，只留 fetched_at 最新的一份 → 其余工具
    的数据被静默丢弃，legal_risk 只剩 1/7 的信息。现改为：
        out[dim] = {
            'tools': {tool_name: {'result':…, 'fetched_at':…, 'error':…}},  # 全量
            'data':  单工具时=该结果；多工具时={tool: result} 合并视图（向后兼容）
            'errors': {tool: error},   # 仅失败工具
            'source': 'mcp:<tool1>+<tool2>'（多工具时列出全部）,
        }

    Returns:
        {dim: {...}}
        未回填的维度不在返回字典中（调用方据此判定缺口）。
    """
    subdir = os.path.join(data_dir, MCP_DATA_SUBDIR)
    out: Dict[str, dict] = {}
    if not os.path.isdir(subdir):
        return out
    for fn in sorted(os.listdir(subdir)):
        if not fn.endswith('.json'):
            continue
        try:
            with open(os.path.join(subdir, fn), 'r', encoding='utf-8') as f:
                p = json.load(f)
        except Exception:
            continue
        dim = p.get('dim')
        if not dim:
            continue
        slot = out.setdefault(dim, {'tools': {}, 'errors': {}, 'fetched_at': ''})
        tool = p.get('tool') or 'unknown'
        prev = slot['tools'].get(tool)
        # 同一工具多次回填，保留 fetched_at 最新的一份
        if prev and str(prev.get('fetched_at', '')) >= str(p.get('fetched_at', '')):
            continue
        slot['tools'][tool] = {
            'result': p.get('result'),
            'error': p.get('error'),
            'fetched_at': p.get('fetched_at'),
        }
        if p.get('error'):
            slot['errors'][tool] = p['error']
        if str(p.get('fetched_at', '')) > str(slot['fetched_at']):
            slot['fetched_at'] = p.get('fetched_at')

    for dim, slot in out.items():
        tools = slot['tools']
        ok_tools = {t: v for t, v in tools.items() if not v.get('error')}
        # data：单工具=裸结果；多工具={tool: result}
        if len(tools) == 1:
            only = next(iter(tools.values()))
            slot['data'] = only.get('result')
        else:
            slot['data'] = {t: v.get('result') for t, v in tools.items()}
        slot['tool'] = next(iter(ok_tools), next(iter(tools)))
        slot['source'] = ('mcp:' + '+'.join(ok_tools) if ok_tools
                          else 'mcp_error:' + '+'.join(slot['errors']))
        slot['error'] = None if ok_tools else '; '.join(slot['errors'].values())
        slot['tier'] = TIER_LABELS[1] if ok_tools else None
        slot['tool_count'] = len(tools)
        slot['ok_tool_count'] = len(ok_tools)
    return out


def mcp_coverage_report(data_dir: str, dims: List[str]) -> dict:
    """
    生成本次分析的 MCP 覆盖报告：哪些维度已回填、哪些仍是缺口。

    Returns:
        {'filled': [...], 'missing': [...], 'errored': [...], 'plan_calls': N}
    """
    results = load_mcp_results(data_dir)
    filled, missing, errored = [], [], []
    for dim in dims:
        if dim not in results:
            missing.append(dim)
        elif results[dim].get('error'):
            errored.append(dim)
        else:
            filled.append(dim)
    plan = read_mcp_plan(data_dir) or {}
    return {
        'filled': filled,
        'missing': missing,
        'errored': errored,
        'plan_calls': len(plan.get('calls', [])),
    }


def format_coverage_markdown(cov: dict) -> str:
    lines = ['\n\n---\n\n## 🔌 MCP 数据回填覆盖\n']
    lines.append(f"- 计划调用数：{cov['plan_calls']}")
    lines.append(f"- ✅ 已回填：{', '.join(cov['filled']) or '无'}")
    lines.append(f"- ❌ 缺口（未回填，报告须标 🔴）：{', '.join(cov['missing']) or '无'}")
    lines.append(f"- ⚠️ 调用失败（报告须标 🔴）：{', '.join(cov['errored']) or '无'}")
    lines.append('')
    return '\n'.join(lines)


# ============================================================
# 回填应用：把 MCP 回填结果合并进 findings（Wind 主力源生效点）
# ============================================================
# 设计铁律（2026-10-21 确立）：
#   1. **不删除原生数据**：脚本源（东财/腾讯/AKShare/SEC）结果原样留存于 `_native`，
#      Wind 只覆盖数值字段并打 `_source`/`_tier` 溯源，便于交叉验证与回退。
#   2. **原生缺失才升主**：脚本源为空/失败时，Wind 或 dzh 才升为 `_fallback_primary`，
#      避免"两个源都有一半数据"时互相覆盖成四不像。
#   3. 未回填 = 缺口，不进默认值（沿用 mcp_bridge 总铁律）。
WIND_QUOTE_FIELD_MAP = {
    '最新成交价': 'price', '前收盘价': 'prev_close',
    '今日开盘价': 'open', '今日最高价': 'high', '今日最低价': 'low',
    '成交量': 'volume', '成交额': 'amount',
    '涨跌幅': 'change_pct', '换手率': 'turnover_rate',
    '市盈率(TTM)': 'pe_ttm', '市盈率(LYR)': 'pe_lyr',
    '市净率(LF)': 'pb', '市净率': 'pb',
    '总市值1': 'mcap', '流通市值': 'float_mcap', '总股本': 'total_shares',
    '52周最高': 'w52_high', '52周最低': 'w52_low', '股息率': 'dividend_yield',
    '年初至今涨跌幅': 'ytd_change_pct',
}

CURRENCY_BY_MARKET = {'a': 'CNY', 'bse': 'CNY', 'hk': 'HKD', 'us': 'USD'}

# 美股 Wind 交易所后缀（.N 兜底提示）
_DZH_HK_US_TOOLS = ('getHkIncomeStatementData', 'getHkBalanceSheetData',
                    'getHkCashFlowStatementData', 'getUsProfitData',
                    'getUsBalanceSheetData', 'getUsCashFlowData')


def _to_float(v):
    """'3.58068e+12' / '1,234' / 3.5 → float；失败返回 None（不猜数）"""
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(',', '').strip())
    except Exception:
        return None


def _cap_text(s, n: int = 1200) -> str:
    """压空白 + 截断（MCP 正文常含大量换行/空格）"""
    t = re.sub(r'[ \t\u3000]+', ' ', str(s or '')).strip()
    t = re.sub(r'\n{2,}', '\n', t)
    return t[:n]


def wind_tabular_to_dicts(payload) -> List[dict]:
    """把 MCP 返回归一成 [ {列名: 值}, ... ]（递归展开多层嵌套容器）。

    实测形态（2026-10-21）：
      - 行情/K线：{'data': {'columns': [...], 'rows': [[...]], 'unit': {...}}}
      - 基本面  ：{'data': {'data': [ {'columns': [...], 'rows': [...]} ]}}   ← 双层！
      - 股东    ：{'data': {'data': [ {表1…}, {表2…} ]}}                      ← 多表！
      - dzh    ：{'data': [ {...记录...} ]}
    旧版只剥一层 data，会把"表容器"本身当记录（基本面/股东全错），故改为递归展开 +
    按列名映射行 + 丢弃全空行。
    """
    out: List[dict] = []

    def walk(node, depth=0):
        if node is None or depth > 4:
            return
        if isinstance(node, list):
            for x in node:
                walk(x, depth + 1)
            return
        if not isinstance(node, dict):
            return
        cols = node.get('columns')
        if isinstance(cols, list) and isinstance(node.get('rows'), list):
            names = [(c.get('name') if isinstance(c, dict) else str(c)) for c in cols]
            for row in node['rows']:
                if isinstance(row, dict):
                    out.append(row)
                elif isinstance(row, (list, tuple)):
                    out.append({names[i]: row[i]
                                for i in range(min(len(names), len(row)))})
            return
        for key in ('data', 'result', 'items', 'list'):
            if key in node:
                walk(node[key], depth + 1)
                return
        if node:  # 叶节点 = 一条记录（dzh 的扁平 dict）
            out.append(node)

    walk(payload)
    # 丢弃占位空行：除「名次/序号」外全为空的行（股东表常见第 9/10 名空占位）
    _IGNORE_KEYS = ('名次', '序号', 'rank', 'RANK')

    def _meaningful(r: dict) -> bool:
        return any(v not in (None, '') for k, v in r.items()
                   if k not in _IGNORE_KEYS)

    return [r for r in out if _meaningful(r)]


def _pick_slot(mcp_results: Dict[str, dict], *dims):
    """按候选维度名取第一个有成功回填的槽位"""
    for d in dims:
        slot = mcp_results.get(d)
        if slot and not slot.get('error'):
            return slot
    return None


def _collect_tool_rows(slot: dict, tools_wanted) -> Dict[str, List[dict]]:
    """从槽位中按工具名收集归一后的行（只取成功的）"""
    got: Dict[str, List[dict]] = {}
    if not slot:
        return got
    for tool, hit in (slot.get('tools') or {}).items():
        if tool not in tools_wanted or not hit or hit.get('error'):
            continue
        rows = wind_tabular_to_dicts(hit.get('result'))
        if rows:
            got[tool] = rows
    return got


def _backfill_status(findings: dict, market: str, applied: list, no_data: bool = False) -> dict:
    """生成回填门禁状态（原生已有数据的维度不算缺口）"""
    _q = findings.get('quote') or {}
    _fin = findings.get('financial') or {}
    _st = findings.get('structure') or {}
    _ind = findings.get('industry') or {}
    _ann = findings.get('announcements') or {}
    _has_native = {
        'quote': bool(_q.get('price')),
        'kline': bool(findings.get('kline') or findings.get('kline_bars')),
        'financial': bool(_fin.get('records')),
        'structure': bool(_st.get('top_shareholders')),
        'industry': bool(_ind.get('industry_class')),
        'announcements': bool(_ann.get('count')),
    }
    _dims = ('quote', 'kline', 'financial', 'structure', 'industry', 'announcements')
    _miss = [d for d in _dims
             if not any(str(a).startswith(d) for a in (applied or []))
             and not _has_native.get(d)]
    st = {
        'required': bool(_miss),
        'status': ('not_backfilled' if no_data else ('partial' if _miss else 'complete')),
        'market': market,
        'missing': _miss,
        'applied': applied or [],
        'native_ok': [d for d in _dims if _has_native.get(d)],
        'note': ('部分维度未回填，空缺不等于"没有该数据"' if _miss
                 else '已全部回填或原生已有数据'),
    }
    if no_data:
        st['action'] = '按 data/mcp_plan.json 调 Wind/dzh 后 save_mcp_result，再 --apply'
    findings['_mcp_backfill'] = st
    return st


def apply_backfill(findings: dict, data_dir: str, market: str = 'a') -> dict:
    """把 `data/mcp_data/*.json` 回填结果合并进 findings（Wind 主力源生效点）。

    合并面：quote（行情+估值快照）/ kline / financial（Wind 基本面 + dzh 港美三表）/
    announcements（北交所、美股公告缺口）/ structure（股东）。

    Returns:
        {'applied': [...], 'promoted': [...], 'missing': [...], 'detail': {...}}
    """
    report = {'applied': [], 'promoted': [], 'missing': [], 'detail': {}}
    results = load_mcp_results(data_dir)
    if not results:
        report['missing'].append('all(mcp_data 为空：Agent 未回填)')
        # 🔴 回填门禁（2026-10-22）：港美股/北交所大量维度的脚本源本身不覆盖，
        # "空"不代表"没有"。不打这个标，报告会把空当成"无数据/无风险"。
        if market in ('hk', 'us', 'bse'):
            _backfill_status(findings, market, [], no_data=True)
        return report

    cur = CURRENCY_BY_MARKET.get(market, 'CNY')

    # ── 1. 行情 + 估值快照（Wind price indicators 优先，dzh 兜底）──
    quote_slot = _pick_slot(results, 'quote', 'hk_quote', 'us_quote')
    q_rows = _collect_tool_rows(quote_slot,
                               ('get_stock_price_indicators', 'get_stock_quote',
                                'getQuoteDyna', 'getGmQuoteDyna'))
    if q_rows:
        tool = 'get_stock_price_indicators' if 'get_stock_price_indicators' in q_rows else next(iter(q_rows))
        row = q_rows[tool][0]
        norm, unit_cols = {}, {}
        for k, v in row.items():
            key = WIND_QUOTE_FIELD_MAP.get(str(k).strip())
            if not key:
                continue
            fv = _to_float(v)
            norm[key] = fv if fv is not None else v
        unit = {}
        raw = (quote_slot.get('tools', {}).get(tool, {}).get('result') or {})
        if isinstance(raw, dict) and isinstance(raw.get('data'), dict):
            unit = raw['data'].get('unit') or {}
        base = findings.get('quote') or {}
        if not isinstance(base, dict):
            base = {}
        if '_native' not in base:
            base['_native'] = {k: v for k, v in base.items() if not str(k).startswith('_')}
        base.update({k: v for k, v in norm.items() if v is not None})
        # 市值统一补「亿」口径（现有台账/文章都按 亿 读）
        if isinstance(base.get('mcap'), (int, float)):
            base['mcap_yi'] = round(base['mcap'] / 1e8, 2)
        if isinstance(base.get('float_mcap'), (int, float)):
            base['float_mcap_yi'] = round(base['float_mcap'] / 1e8, 2)
        base['_source'] = f'wind-finance:{tool}' if tool.startswith('get_stock') else f'dzh-mcp:{tool}'
        base['_tier'] = 'T1'
        base['_currency'] = cur
        base['_unit'] = unit
        findings['quote'] = base
        report['applied'].append('quote')
        # 估值快照旁挂到 valuation（不覆盖 SOTP 模型结论）
        val = findings.get('valuation')
        if not isinstance(val, dict):
            val = {}
        val['mcp_snapshot'] = {
            'price': base.get('price'), 'pe_ttm': base.get('pe_ttm'),
            'pb': base.get('pb'), 'mcap_yi': base.get('mcap_yi'),
            'currency': cur, 'source': base['_source'],
        }
        findings['valuation'] = val
        report['detail']['quote'] = {k: base.get(k) for k in
                                    ('price', 'pe_ttm', 'pb', 'mcap_yi')}

    # ── 2. K线（Wind get_stock_kline 主力，dzh getGmQuoteKline 兜底）──
    k_rows = {}
    for slot in results.values():
        k_rows.update(_collect_tool_rows(slot, ('get_stock_kline', 'getGmQuoteKline')))
    if k_rows:
        tool = 'get_stock_kline' if 'get_stock_kline' in k_rows else next(iter(k_rows))
        bars = k_rows[tool]
        findings['kline'] = {
            'bars': bars, 'count': len(bars),
            'begin': bars[0].get('TIME') or bars[0].get('time'),
            'end': bars[-1].get('TIME') or bars[-1].get('time'),
            '_source': f'wind-finance:{tool}' if tool == 'get_stock_kline' else f'dzh-mcp:{tool}',
            '_tier': 'T1',
        }
        report['applied'].append('kline')
        report['detail']['kline'] = {'count': len(bars)}
        # 用K线补 52 周高低（Wind 快照没返回时才补）
        q = findings.get('quote') or {}
        if isinstance(q, dict) and not q.get('w52_high'):
            highs = [_to_float(b.get('HIGH') or b.get('high')) for b in bars]
            lows = [_to_float(b.get('LOW') or b.get('low')) for b in bars]
            highs = [x for x in highs if x is not None]
            lows = [x for x in lows if x is not None]
            if highs:
                q['w52_high'] = max(highs)
            if lows:
                q['w52_low'] = min(lows)

    # ── 3. 财务（Wind fundamentals + dzh 港美股三大表）──
    fin_slot = _pick_slot(results, 'financial', 'hk_financial', 'us_financial')
    wind_fin = _collect_tool_rows(fin_slot, ('get_stock_fundamentals',))
    dzh_parts = {t: rows for t, rows in
                 _collect_tool_rows(fin_slot, _DZH_HK_US_TOOLS).items()}
    native_fin = findings.get('financial')
    native_empty = not isinstance(native_fin, dict) or not native_fin
    if wind_fin or dzh_parts:
        fin = native_fin if isinstance(native_fin, dict) else {}
        if '_native' not in fin and fin:
            fin['_native'] = True
        if wind_fin:
            fin['_wind_fundamentals'] = {
                'rows': next(iter(wind_fin.values())),
                'source': 'wind-finance:get_stock_fundamentals', 'tier': 'T1',
            }
        if dzh_parts:
            fin[f'_dzh_{market}_statements'] = dzh_parts
        if native_empty:
            fin['_fallback_primary'] = ('wind-finance:get_stock_fundamentals'
                                        if wind_fin else 'dzh-mcp:' + '+'.join(dzh_parts))
            report['promoted'].append('financial')
        findings['financial'] = fin
        report['applied'].append('financial')
        report['detail']['financial'] = {
            'wind_rows': len(next(iter(wind_fin.values()))) if wind_fin else 0,
            'dzh_statements': list(dzh_parts),
        }

    # ── 3.5 名称兜底：Wind 行情快照不含证券简称（港股 tencent_quote 常整条空），
    #     从 Wind 基本面/SEC 名称类字段补，避免文章出现"None"公司名。
    qt = findings.get('quote')
    if isinstance(qt, dict) and not qt.get('name'):
        for rows in (wind_fin or {}).values():
            for _r in rows:
                _nm = (_r.get('证券简称') or _r.get('公司名称') or _r.get('name'))
                if _nm:
                    qt['name'] = _nm
                    break
            if qt.get('name'):
                break

    # ── 4. 公告（北交所/美股脚本源覆盖不到 → Wind 补；A股/港股作同源补充）──
    ann_slot = _pick_slot(results, 'announcements')
    a_rows = _collect_tool_rows(ann_slot, ('get_company_announcements', 'getF10TbGgMoData'))
    if a_rows:
        tool = next(iter(a_rows))
        rows = a_rows[tool]
        ann = findings.get('announcements')
        if not isinstance(ann, dict):
            ann = {}
        # 归一成统一字段（Wind 返回 title/date/url/doc_type/content）
        norm = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            title = (r.get('title') or r.get('公告标题') or r.get('TITLE') or '').strip()
            if not title:
                continue
            norm.append({
                'title': title,
                'date': str(r.get('date') or r.get('notice_date') or r.get('DATE') or '')[:10],
                'url': r.get('url') or r.get('adjunctUrl') or '',
                'type': r.get('doc_type') or 'announcement',
                # 正文摘要（Wind 公告带 content 全文，截断保留，供证据包引用）
                'content_preview': _cap_text(r.get('content') or r.get('content_preview') or '', 1200),
            })
        if norm:
            src = (f'wind-finance:{tool}' if tool == 'get_company_announcements'
                   else f'dzh-mcp:{tool}')
            if not ann.get('count'):
                ann['items'] = norm
                ann['count'] = len(norm)
                ann['_source'] = src
                ann['_tier'] = 'T1'
                ann['_note'] = ('脚本源未覆盖该市场公告，由 MCP 回填补齐'
                                '（标题/日期以原文为准；content_preview 为原文摘要）')
                report['applied'].append('announcements')
            else:
                # 已有脚本源公告 → 保留原文，MCP 结果旁挂，便于交叉验证
                ann.setdefault('_mcp_supplement', {})['items'] = norm
                ann['_mcp_supplement']['source'] = src
                report['applied'].append('announcements(+mcp补充)')
            ann['_mcp_supplement_count'] = len(norm)
            findings['announcements'] = ann
            report['detail']['announcements'] = {'count': len(norm)}

    # ── 5. 股东结构（Wind equity holders）──
    st_slot = _pick_slot(results, 'structure', 'hk_structure', 'us_structure')
    s_rows = _collect_tool_rows(st_slot, ('get_stock_equity_holders', 'getF10HolderDetailsData',
                                          'getF10GsjsData'))
    if s_rows:
        st = findings.get('structure')
        if not isinstance(st, dict):
            st = {}
        st['_mcp_holders'] = {
            'source': 'wind-finance:get_stock_equity_holders' if 'get_stock_equity_holders' in s_rows
                      else 'dzh-mcp',
            'tables': s_rows,
            'row_count': sum(len(v) for v in s_rows.values()),
        }
        # 5b. 映射成下游标准字段（港美股原生 top_shareholders 恒空，此前必须靠人工看原始表）
        if not st.get('top_shareholders'):
            top, inst = [], []
            for rows in s_rows.values():
                for r in rows:
                    nm_key = next((k for k in r if '股东名称' in str(k)), None)
                    if not nm_key or not str(r.get(nm_key) or '').strip():
                        continue
                    item = {
                        'rank': r.get('名次'),
                        'name': str(r.get(nm_key)).strip(),
                        'shares': next((r.get(k) for k in r if '持股数量' in str(k)), None),
                        'ratio_pct': next((r.get(k) for k in r if '持股比例' in str(k)), None),
                    }
                    # 美股机构股东表带「报告期」（如 Q3 FY2026），保留供口径说明
                    _period = next((r.get(k) for k in r if '报告期' in str(k)), None)
                    if _period:
                        item['report_period'] = _period
                    (inst if '机构' in str(nm_key) else top).append(item)
            if top:
                st['top_shareholders'] = sorted(
                    top, key=lambda x: (x.get('rank') or 99))[:10]
                st['_holders_source'] = st['_mcp_holders']['source']
            if inst:
                # 🔴 机构股东**不截断**：Wind 美股实测返回 100+ 家（13F 聚合），
                # 截到 10 家等于把最有价值的部分丢掉（A股仅 10 大股东，港美股反而更深）。
                inst_sorted = sorted(inst, key=lambda x: (x.get('rank') or 999))
                st['institutional_holders'] = inst_sorted
                st['institutional_holder_count'] = len(inst_sorted)
            # 总股本 / 实控人（若表里带）
            _cap_shares = next((r.get(k) for rows in s_rows.values() for r in rows
                                for k in r if '总股本' in str(k)), None)
            if _cap_shares:
                st['total_shares'] = _cap_shares
            _ctrl = next((r.get(k) for rows in s_rows.values() for r in rows
                          for k in r if '实际控制人' in str(k)), None)
            if _ctrl:
                st['actual_controller'] = _ctrl
        if st.get('_mcp_holders', {}).get('tables'):
            report['detail']['structure'] = {
                'holders': sum(len(v) for v in s_rows.values()),
                'mapped_top': len(st.get('top_shareholders') or []),
            }
        findings['structure'] = st
        report['applied'].append('structure')

    # ── 5c. qcc 实控人穿透 / 受益所有人 / 对外投资（独立于 Wind 股东，必执行）──
    st_slot = _pick_slot(results, 'structure', 'hk_structure', 'us_structure')
    _qcc_rows = _collect_tool_rows(st_slot, ('get_actual_controller',
                                             'get_beneficial_owners',
                                             'get_external_investments'))
    if _qcc_rows:
        _st = findings.get('structure') or {}
        if not isinstance(_st, dict):
            _st = {}
        _st['qcc_penetration'] = {
            'source': 'qcc-company', 'tier': 'T1',
            'actual_controller': (_qcc_rows.get('get_actual_controller') or [None])[0],
            'beneficial_owners': (_qcc_rows.get('get_beneficial_owners') or [None])[0],
            'external_investments': _qcc_rows.get('get_external_investments'),
            'note': ('qcc 服务端已聚合穿透终值，须逐字引用，禁止用各层比例相乘'
                     '重构穿透路径，禁止臆测中间层主体'),
        }
        findings['structure'] = _st
        report['applied'].append('structure(+qcc穿透)')
        report['detail'].setdefault('structure', {})['qcc_penetration'] = True

    # ── 5.5 股权质押 / 冻结明细（qcc T+0）──
    # 🔴 港美股：企查查不覆盖，hk_pledge/us_pledge 维度无 mcp_primary → 此处统一标 gap（不假装覆盖）
    pl_slot = _pick_slot(results, 'pledge', 'hk_pledge', 'us_pledge')
    p_rows = _collect_tool_rows(pl_slot, ('get_stock_pledge_info', 'get_equity_pledge_info'))
    if p_rows:
        pledge = findings.get('pledge') or {}
        norm, no_record = [], False
        for tool, rows in p_rows.items():
            for r in rows:
                if not isinstance(r, dict):
                    continue
                _sr = str(r.get('搜索结果') or r.get('结果') or r.get('message') or '')
                if any(w in _sr for w in ('未发现', '未匹配', '无记录', '不存在', '未查询到')):
                    no_record = True
                    continue
                def _g(*keys):
                    for k, v in r.items():
                        if any(x in str(k) for x in keys) and v not in (None, ''):
                            return v
                    return None
                norm.append({
                    'tool': tool,
                    'pledgor': _g('质押人', '出质人', '股东'),
                    'pledgee': _g('质权人', '质押权人'),
                    'shares': _g('质押股份', '出质股权数额', '持股数'),
                    'mcap': _g('质押股份市值', '市值'),
                    'status': _g('状态', '出质状态'),
                    'reg_date': _g('登记日期', '公告日期', '出质日期'),
                    'raw': r,
                })
        if norm:
            pledge['_mcp'] = {
                'source': 'qcc-company',
                'tier': 'T1',
                'items': norm,
                'count': len(norm),
                'active': sum(1 for x in norm if any(
                    w in str(x.get('status') or '') for w in ('押', '在', '效'))),
                'note': 'qcc T+0 在册出质记录；历史已解押需 get_historical_equity_pledge',
            }
            findings['pledge'] = pledge
            report['applied'].append('pledge')
            report['detail']['pledge'] = {'count': len(norm)}
        elif no_record:
            pledge['_mcp'] = {'source': 'qcc-company', 'tier': 'T1',
                              'status': 'no_record',
                              'note': 'qcc 全量扫描未发现在册股权质押记录（T+0 核验）'}
            findings['pledge'] = pledge
            report['applied'].append('pledge(no_record)')
            report['detail']['pledge'] = {'count': 0, 'status': 'no_record'}
    else:
        # 无 qcc 质押工具返回：A股/北交所静默（可能 qcc 未连接）；港美股显式标 gap
        if market in ('hk', 'us'):
            _pl = findings.setdefault('pledge', {})
            _pl['_mcp'] = {
                'source': None, 'tier': None, 'status': 'gap',
                'note': ('港美股股权质押不在企查查覆盖内；当前 skill 未接通港交所披露易/SEC 官方'
                         '股权披露专用 MCP，须人工以目标市场官方披露源补充'
                         '（港股：披露易「股份抵押」；美股：SEC 13D/13G/Form 4）'),
            }
            report['applied'].append('pledge(gap_hkus)')
            report['detail']['pledge'] = {'status': 'gap', 'reason': 'hk/us 无 qcc 质押源'}

    # ── 6. 行业 / 主营 / 概念（Wind basicinfo；港美股原 industry 恒空）──
    ind_slot = _pick_slot(results, 'industry', 'hk_industry', 'us_industry')
    i_rows = _collect_tool_rows(ind_slot, ('get_stock_basicinfo', 'getF10BusiinfoData'))
    if i_rows:
        tool = next(iter(i_rows))
        row = i_rows[tool][0]

        def _pick(*keys):
            for k, v in row.items():
                if any(x in str(k) for x in keys) and v not in (None, ''):
                    return v
            return None

        ind = findings.get('industry')
        if not isinstance(ind, dict):
            ind = {}
        if not ind.get('industry_class'):
            ind['industry_class'] = _pick('WIND行业', '行业')
        for fld, src in (('listing_board', ('上市板',)),
                         ('listing_date', ('上市日期',)),
                         ('business_scope', ('经营范围',)),
                         ('risk_warning', ('风险警示',))):
            if not ind.get(fld):
                v = _pick(*src)
                if v:
                    ind[fld] = v
        if not ind.get('main_business'):
            ind['main_business'] = _pick('主营', '经营范围')
        # 主营收入构成：'增值服务:48.48%;金融科技及企业服务:29.95%' → 结构化列表
        # （A 股的 income_structure 是带金额的明细，这里给占比版，下游按同一字段读）
        if not ind.get('income_structure'):
            _raw_inc = _pick('主营收入构成', '主营构成')
            if _raw_inc:
                _items = []
                for seg in str(_raw_inc).split(';'):
                    seg = seg.strip()
                    if not seg or ':' not in seg:
                        continue
                    _n, _p = seg.rsplit(':', 1)
                    _pv = _to_float(str(_p).replace('%', ''))
                    _items.append({'name': _n.strip(),
                                   'ratio_pct': round(_pv, 4) if _pv is not None else None})
                if _items:
                    ind['income_structure'] = _items
                    ind['income_structure_basis'] = '占比口径（Wind 主营收入构成）'
        # 概念板块：'[HK]数字孪生;[HK]AI算力;…' → 去前缀的标签列表
        if not ind.get('concepts'):
            raw = _pick('概念板块')
            if raw:
                tags = []
                for t in str(raw).split(';'):
                    t = t.strip()
                    if not t:
                        continue
                    t = t.split(']')[-1] if t.startswith('[') else t
                    if t:
                        tags.append(t)
                ind['concepts'] = tags
                ind['concept_count'] = len(tags)
        ind['_source'] = (f'wind-finance:{tool}' if tool == 'get_stock_basicinfo'
                          else f'dzh-mcp:{tool}')
        ind['_tier'] = 'T1'
        findings['industry'] = ind
        report['applied'].append('industry')
        report['detail']['industry'] = {
            'industry_class': ind.get('industry_class'),
            'concepts': ind.get('concept_count'),
        }

    # ── 7. 高管（董监高名单 + 任职，合并 qcc/dzh MCP 结果）──
    ex_slot = _pick_slot(results, 'executives')
    ex_rows = _collect_tool_rows(ex_slot, ('get_key_personnel', 'getF10GsjsData'))
    ex = findings.get('executives')
    if not isinstance(ex, dict):
        ex = {}
    if ex_rows:
        def _g(r, *keys):
            for k, v in r.items():
                if any(x in str(k) for x in keys) and v not in (None, ''):
                    return v
            return None
        people = []
        for tool, rows in ex_rows.items():
            for r in rows:
                if not isinstance(r, dict):
                    continue
                # qcc get_key_personnel：{企业名称, 主要人员信息:[{姓名,职务}]}
                _persons = r.get('主要人员信息') or r.get('主要人员') or []
                if _persons:
                    for pp in _persons:
                        if isinstance(pp, dict) and pp.get('姓名'):
                            people.append({'tool': tool, 'name': str(pp.get('姓名')).strip(),
                                           'title': pp.get('职务'), 'raw': pp})
                    continue
                nm = _g(r, '姓名', '人员名称', '董事', '高管')
                if not nm:
                    continue
                people.append({'tool': tool, 'name': str(nm).strip(),
                               'title': _g(r, '职务', '职位'), 'raw': r})
        if people:
            ex['mcp_detail'] = {
                'source': 'qcc-company+dzh-mcp', 'tier': 'T1',
                'people': people, 'count': len(people),
                'note': ('董监高名单（一层）；个人履历/薪酬/兼职轨迹需 qcc '
                         'get_executive_* 按人深挖，本工具未覆盖 → 标缺口'),
            }
            ex.pop('_gap', None)
            findings['executives'] = ex
            report['applied'].append('executives')
            report['detail']['executives'] = {'count': len(people)}
    if isinstance(ex, dict) and not ex.get('mcp_detail') and not ex.get('changes'):
        ex.setdefault('_gap', '高管变动明细：Wind 无此接口；A 股走东财 F10，'
                              '港美股需人工/港交所权益披露，禁止编造变动事项')
        findings['executives'] = ex

    # 缺口清单
    for d in ('quote', 'kline', 'financial'):
        if d not in report['applied']:
            report['missing'].append(d)
    # 回填状态（部分回填也要标，便于报告区分"没做"与"做了但缺"）
    if market in ('hk', 'us', 'bse'):
        _backfill_status(findings, market, report['applied'])
    return report


def format_backfill_report(rep: dict) -> str:
    """回填应用报告（analyze.py 打印用）"""
    if not rep:
        return ''
    lines = []
    if rep.get('applied'):
        lines.append(f"✅ MCP 回填已合并：{', '.join(rep['applied'])}")
    if rep.get('promoted'):
        lines.append(f"⬆️ 原生源缺失，升为主源：{', '.join(rep['promoted'])}")
    if rep.get('missing'):
        lines.append(f"🔴 未回填（缺口，报告须标注，不得猜数）：{', '.join(rep['missing'])}")
    det = rep.get('detail') or {}
    if det.get('quote'):
        d = det['quote']
        lines.append(f"   行情快照：价 {d.get('price')} / PE(TTM) {d.get('pe_ttm')} / "
                     f"PB {d.get('pb')} / 市值 {d.get('mcap_yi')} 亿")
    return '\n'.join(lines)


# ============================================================
# CLI
# ============================================================
if __name__ == '__main__':
    import argparse
    import sys as _sys
    ap = argparse.ArgumentParser(description='MCP 计划生成 / 回填合并（Wind 主力源）')
    ap.add_argument('stock', nargs='?', default='002180', help='股票代码')
    ap.add_argument('--market', '-m', default='a', choices=['a', 'hk', 'us', 'bse'])
    ap.add_argument('--data-dir', '-d', help='data 目录（mcp_plan.json 落点）')
    ap.add_argument('--company-name', default=None, help='公司精确全称（qcc 检索键）')
    ap.add_argument('--dims', default=None, help='逗号分隔；默认按市场取 MARKET_DIMS')
    ap.add_argument('--apply', action='store_true',
                    help='把 data/mcp_data/*.json 回填结果合并进 results.json')
    _args = ap.parse_args()

    if _args.apply:
        if not _args.data_dir:
            ap.error('--apply 需要 --data-dir')
        _p = os.path.join(_args.data_dir, 'results.json')
        with open(_p, 'r', encoding='utf-8') as _f:
            _results = json.load(_f)
        _rep = apply_backfill(_results.get('findings', {}), _args.data_dir, _args.market)
        with open(_p, 'w', encoding='utf-8') as _f:
            json.dump(_results, _f, ensure_ascii=False, indent=2, default=str)
        print(format_backfill_report(_rep) or '无回填数据（data/mcp_data 为空）')
        _sys.exit(0)

    _dims = ([x.strip() for x in _args.dims.split(',') if x.strip()]
             if _args.dims else MARKET_DIMS.get(_args.market, MARKET_DIMS['a']))
    _plan = build_mcp_plan(_args.stock, _args.market, _dims,
                           company_name=_args.company_name)
    if _args.data_dir:
        _path = write_mcp_plan(_args.data_dir, _plan)
        print(f'plan → {_path}  ({len(_plan["calls"])} 个调用)')
        for _c in _plan['calls']:
            print(f"  {_c['dim']:18s} | {_c['connector']:16s} | "
                  f"{_c['tool']:30s} | {_c['status']}")
    else:
        print(json.dumps(_plan, ensure_ascii=False, indent=2))
