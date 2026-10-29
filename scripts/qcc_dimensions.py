# -*- coding: utf-8 -*-
"""
qcc_dimensions.py — qcc-company 权威数据维度的结构化解析器（P1 · 2026-10-19）
==============================================================================

解决什么问题
------------
`legal_risk` / `intellectual_property` 两个维度在 `data_source_registry.py` 中
已登记 qcc MCP 工具，但 `dispatcher._dispatch_dim` 没有对应分支 → 只在
`mcp_plan.json` 里生成计划，实际跑 `analyze.py --dims legal_risk` 返回 `{}`，
维度永远接不上。本模块负责把 Agent 回填的 MCP 原始结果解析成可用结论。

严格遵守 qcc 的 AI 数据纪律（工具说明原文）：
    1. 风险因子计数为服务端聚合终值，**逐字引用，禁止跨维加总/求和**；
    2. scan 仅分诊，未下钻明细工具前，**禁止凭计数下定性结论**；
    3. 35 项全 0 只代表"结构化风险维度当前无记录"，**不等于无风险**，
       未并行取舆情前禁止输出"无风险/风险较低"等整体定性表述。
    → 本模块因此：
      - 逐因子原样列出计数，不做求和；
      - 分级只表达"该维度有记录/无记录"，不下"公司违法/有欺诈"式定性；
      - 无记录时措辞一律为"结构化风险维度未见记录"，并显式列为数据缺口。

交叉护栏（沿用 cross_validator 纪律）
------------------------------------
**qcc 单源不得直接下"实锤"**。只有当 ≥2 个独立信号（qcc 维度 + 本地
cross_validator / 监管记录 / 公告）同时命中同一风险域，才允许升级为
`confirmed`；否则一律 `needs_corroboration`（需核实的疑点）。

用法
----
    from scripts.qcc_dimensions import build_legal_risk, build_intellectual_property
    r = build_legal_risk(data_dir)                       # 读 data/mcp 下已回填结果
    r = build_legal_risk(data_dir, findings=cross_validator结果)  # 带交叉印证
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

# ============================================================
# 风险因子分级（仅表达"该维度是否有记录"，不对公司定性）
# ============================================================
# 🔴 严重类：命中即需立即核实（属"结构化风险维度有记录"，非定性结论）
SEVERE_FACTORS = {
    '失信信息', '被执行人', '限制高消费', '终本案件', '破产重整',
    '股权冻结', '严重违法', '限制出境', '行政处罚', '税务非正常户',
    '税收违法', '经营异常', '欠税公告', '纪律处分',
}
# 🟡 关注类：常态存在但需看结构
ATTENTION_FACTORS = {
    '裁判文书', '立案信息', '开庭公告', '法院公告', '送达公告',
    '司法拍卖', '担保信息', '股权质押', '动产抵押', '土地抵押',
    '劳动仲裁', '公示催告', '违约事项', '简易注销', '注销备案',
    '清算信息', '司法协助', '股权出质', '财产悬赏公告',
}
# 知识产权相关（专利/商标单列维度，此处仅供 IP 出质交叉）
IP_PLEDGE_FACTORS = {'股权出质'}

FACTOR_LABELS = {
    '失信信息': '失信被执行',
    '被执行人': '被执行人',
    '限制高消费': '限制高消费',
    '终本案件': '终本案件',
    '破产重整': '破产/重整',
    '股权冻结': '股权冻结',
    '严重违法': '严重违法',
    '限制出境': '限制出境',
    '行政处罚': '行政处罚',
    '经营异常': '经营异常',
    '裁判文书': '裁判文书',
    '立案信息': '立案信息',
    '开庭公告': '开庭公告',
    '法院公告': '法院公告',
    '担保信息': '对外担保',
    '股权质押': '股权质押',
    '司法拍卖': '司法拍卖',
    '公示催告': '公示催告',
    '送达公告': '送达公告',
}


def _jsonable(obj: Any) -> Any:
    """MCP 回填结果可能是 JSON 字符串（qcc 中文键会被序列化为 str），尝试解析"""
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith('{') or s.startswith('['):
            for attempt in (s, s.replace('\\n', '\n')):
                try:
                    return json.loads(attempt)
                except Exception:
                    continue
    return obj


def _pick_list(payload: Any, *keys: str) -> List[dict]:
    """从任意结构里防御式取出条目列表"""
    payload = _jsonable(payload)
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
            if isinstance(v, str):
                sub = _jsonable(v)
                if isinstance(sub, list):
                    return [x for x in sub if isinstance(x, dict)]
        # 单层嵌套一层
        for v in payload.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [x for x in v if isinstance(x, dict)]
    return []


def _count(payload: Any, *keys: str) -> Optional[int]:
    payload = _jsonable(payload)
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, (int, float)):
                return int(v)
    if isinstance(payload, list):
        return len(payload)
    return None


# ============================================================
# 解析器：各 qcc 工具 → 规范化结构
# ============================================================
def parse_risk_scan(payload: Any) -> dict:
    """get_company_risk_scan → 35 项因子计数（逐字保留，不加总）"""
    payload = _jsonable(payload)
    factors = []
    raw = payload.get('风险因子扫描') if isinstance(payload, dict) else None
    if isinstance(raw, str):
        raw = _jsonable(raw)
    for item in (raw or []) if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get('风险因子') or '').strip()
        cnt = item.get('条目数')
        if not name:
            continue
        if name in SEVERE_FACTORS:
            level = 'severe'
        elif name in ATTENTION_FACTORS or name in IP_PLEDGE_FACTORS:
            level = 'attention'
        else:
            level = 'other'
        factors.append({
            'factor': name,
            'label': FACTOR_LABELS.get(name, name),
            'count': cnt if isinstance(cnt, (int, float)) else None,
            'level': level,
            'detail_tool': item.get('明细工具') or '',
        })
    hit = [f for f in factors if isinstance(f['count'], (int, float)) and f['count'] > 0]
    return {
        'company_name': payload.get('企业名称') if isinstance(payload, dict) else None,
        'summary': payload.get('摘要') if isinstance(payload, dict) else None,
        'factors_total': len(factors),
        'factors_with_record': len(hit),
        'factors_zero': len(factors) - len(hit),
        'severe_hit': [f for f in hit if f['level'] == 'severe'],
        'attention_hit': [f for f in hit if f['level'] == 'attention'],
        'all_factors': factors,
    }


def parse_pledge(payload: Any, kind: str = 'stock') -> dict:
    """get_stock_pledge_info / get_equity_pledge_info → 在押 vs 已解除拆分"""
    key = '股权质押信息' if kind == 'stock' else '股权出质信息'
    items = _pick_list(payload, key, '股权质押', '股权出质', '质押信息')
    active, released, other = [], [], []
    for it in items:
        st = str(it.get('状态') or '').strip()
        rec = {
            'pledgor': _as_list(it.get('质押人') or it.get('出质人')),
            'pledgee': _as_list(it.get('质押权人') or it.get('质权人')),
            'shares': it.get('股份总数') or it.get('出质股权数额') or '',
            'value': it.get('股份市值') or it.get('出质股权数额') or '',
            'status': st,
            'date': it.get('公告日期') or it.get('登记日期') or '',
            'raw': it,
        }
        if '解除' in st or '注销' in st or '到期' in st:
            released.append(rec)
        elif st:
            active.append(rec)
        else:
            other.append(rec)
    return {
        'kind': kind,
        'total_records': len(items),
        'active_count': len(active),
        'released_count': len(released),
        'active': active,
        'released': released[:10],
        'released_truncated': len(released) > 10,
        'undetermined': other,
    }


def _as_list(v) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


def parse_case_filing(payload: Any) -> dict:
    """
    get_case_filing_info → 在册未结案立案。

    🔴 关键：立案 37 条 ≠ 公司是被告。必须按「当事人」拆出**我方诉讼角色**：
    原告（我方主动维权，风险低）vs 被告/被上诉人/被执行人（我方被诉，风险高）。
    不拆角色就会把"公司起诉别人"误报成"公司有 37 起诉讼"。
    """
    items = _pick_list(payload, '立案信息', '案件列表', '立案')
    as_def, as_plain, third, unknown = [], [], [], []
    for it in items:
        parties = it.get('当事人') or {}
        roles = set()
        if isinstance(parties, dict):
            for r, names in parties.items():
                if isinstance(names, list) and names:
                    roles.add(r)
        elif isinstance(parties, list):
            roles.add('当事人')
        if roles & {'被告', '被上诉人', '被执行人', '被申请人'}:
            as_def.append(it)
        elif roles & {'原告', '上诉人', '申请执行人', '申请人'}:
            as_plain.append(it)
        elif roles & {'第三人'}:
            third.append(it)
        else:
            unknown.append(it)
    years: Dict[str, int] = {}
    causes: Dict[str, int] = {}
    for it in items:
        d = str(it.get('立案日期') or '')[:4]
        if d:
            years[d] = years.get(d, 0) + 1
        c = str(it.get('案由') or '').strip()
        if c:
            causes[c] = causes.get(c, 0) + 1
    return {
        'total': len(items),
        'tool_reported_total': _tool_total(payload),
        'truncated_by_tool': _tool_truncated(payload),
        'count_basis': ('展示条目口径（工具截断，非全量）' if _tool_truncated(payload)
                        else '返回条目口径（未截断，可视为全量）'),
        'summary': _jsonable(payload).get('摘要') if isinstance(_jsonable(payload), dict) else None,
        'as_defendant': len(as_def),
        'as_plaintiff': len(as_plain),
        'as_third_party': len(third),
        'role_undetermined': len(unknown),
        'year_dist': dict(sorted(years.items(), reverse=True)),
        'top_causes': dict(sorted(causes.items(), key=lambda x: -x[1])[:8]),
        'defendant_cases': as_def[:15],
        'items': items[:30],
        'truncated': len(items) > 30,
    }


def parse_dishonest(payload: Any) -> dict:
    items = _pick_list(payload, '失信信息', '失信被执行人信息', '失信')
    return {'total': len(items), 'items': items[:20], 'truncated': len(items) > 20}


def parse_debtor(payload: Any) -> dict:
    items = _pick_list(payload, '被执行人信息', '被执行人')
    return {'total': len(items), 'items': items[:20], 'truncated': len(items) > 20}


def parse_related_risk(payload: Any) -> dict:
    """
    get_company_related_risk_scan → 关联方风险传导。

    实测返回结构：'维度计数汇总' = {关键风险:{维度:计数}, 司法案件:[{类型,条目数}],
    其他关联风险:[{类型,条目数}]}，计数为**字符串**，另有 '有风险关联方数'。
    本解析器逐维取值、**不加总**，并单独抽出关键风险命中（>0）。
    """
    payload = _jsonable(payload)
    if not isinstance(payload, dict):
        return {'factors': [], 'factors_with_record': 0}

    factors: List[dict] = []
    agg = payload.get('维度计数汇总') or {}
    critical_map = agg.get('关键风险') or {}
    for name, cnt in critical_map.items():
        try:
            n = int(cnt)
        except (TypeError, ValueError):
            continue
        factors.append({'group': '关键风险', 'factor': name, 'count': n})
    for grp in ('司法案件', '其他关联风险'):
        for item in (agg.get(grp) or []):
            if isinstance(item, dict):
                try:
                    n = int(item.get('条目数'))
                except (TypeError, ValueError):
                    continue
                factors.append({'group': grp, 'factor': str(item.get('类型') or ''), 'count': n})

    # 关联方定位（7 个重点维度）
    located = []
    for item in (payload.get('重点维度关联方定位') or []):
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get('本维度条目数'))
        except (TypeError, ValueError):
            continue
        located.append({'dimension': item.get('维度'), 'count': n,
                        'related': _as_list(item.get('关联方'))[:10]})

    hit = [f for f in factors if f['count'] > 0]
    try:
        risky_parties = int(payload.get('有风险关联方数'))
    except (TypeError, ValueError):
        risky_parties = None
    return {
        'summary': payload.get('摘要'),
        'risky_party_count': risky_parties,
        'factors': factors,
        'factors_with_record': len(hit),
        'critical_hit': [f for f in hit if f['group'] == '关键风险'],
        'other_hit': [f for f in hit if f['group'] != '关键风险'],
        'located': located,
    }


def _tool_total(payload: Any) -> Optional[int]:
    """工具摘要里的"该查询实体共有 N 条X记录"——这是**服务端总量**，比返回条数可靠"""
    payload = _jsonable(payload)
    if not isinstance(payload, dict):
        return None
    s = str(payload.get('摘要') or '')
    m = re.search(r'共有\s*(\d+)\s*条', s)
    if m:
        return int(m.group(1))
    s2 = str(payload.get('有风险关联方数') or '')
    return None


def _tool_truncated(payload: Any) -> bool:
    payload = _jsonable(payload)
    if not isinstance(payload, dict):
        return False
    return '已为您展示前' in str(payload.get('提示') or '')


def _dist(items: List[dict], key: str) -> Dict[str, int]:
    """状态/类型分布统计"""
    d: Dict[str, int] = {}
    for it in items:
        v = str(it.get(key) or '').strip()
        if v:
            d[v] = d.get(v, 0) + 1
    return dict(sorted(d.items(), key=lambda x: -x[1]))


def parse_patent(payload: Any) -> dict:
    """
    get_patent_info → 当前有效专利。

    🔴 关键：返回条目含「法律状态」= 授权/实质审查/**主动放弃**/**未缴年费专利权终止**。
    「有 N 条专利」不等于「有 N 项在权壁垒」——放弃/终止的专利不构成技术护城河，
    故必须输出状态分布，并把「授权且在权」与「放弃/终止」分开计。

    🔴 2026-10-19 修复（Agent 回填场景）：
      Agent 把 MCP 返回落盘时，可能因为工具返回量太大（766 条只展示 100 条）
      而只保存了**汇总分布 + 少量样本**。此时旧逻辑只从 `items`（30 条截断样本）
      统计 in_force/abandoned → 实测得出「在权 5 条、放弃 0 条」的荒谬数字
      （真实：授权 37 条、主动放弃 47 条）。
      现优先读取**预聚合分布字段**（`展示样本法律状态分布` / `status_dist`），
      没有才回退到 items 逐条统计。
    """
    items = _pick_list(payload, '专利信息', '专利列表', '专利')
    st = _dist(items, '法律状态')
    ty = _dist(items, '专利类型')

    # 🔴 预聚合分布**优先于** items 逐条统计。
    # 理由：Agent 回填 766 条时只能存代表样本（30 条），而工具实际返回了 100 条
    # 并已聚合成分布。用 30 条样本统计 → 「在权 12」；用 100 条分布 → 「在权 37」。
    # 后者更接近真实（且明确标注不可外推全量）。
    _pre_st = (payload.get('展示样本法律状态分布') or payload.get('status_dist') or {})
    _pre_ty = (payload.get('展示样本类型分布') or payload.get('type_dist') or {})
    _used_pre = False
    if isinstance(_pre_st, dict) and _pre_st:
        st = {str(k): int(v) for k, v in _pre_st.items()}
        _used_pre = True
    if isinstance(_pre_ty, dict) and _pre_ty:
        ty = {str(k): int(v) for k, v in _pre_ty.items()}

    abandoned = sum(v for k, v in st.items()
                    if any(x in k for x in ('放弃', '终止', '无效', '驳回')))
    in_force = sum(v for k, v in st.items()
                   if any(x in k for x in ('授权', '有效')))
    # total：优先用 tools 自报总量；其次展示样本数
    total = payload.get('总记录数') or payload.get('展示条数') or len(items)
    return {
        'total': int(total) if str(total).isdigit() else len(items),
        'displayed': len(items) or int(payload.get('展示条数') or 0),
        'tool_reported_total': _tool_total(payload) or payload.get('总记录数'),
        'truncated_by_tool': _tool_truncated(payload) or bool(payload.get('展示条数')),
        'items': items[:30],
        'truncated': len(items) > 30,
        'status_dist': st,
        'type_dist': ty,
        'in_force_count': in_force,
        'abandoned_or_terminated_count': abandoned,
        'stats_basis': ('预聚合分布（工具返回样本更全）' if _used_pre else '逐条统计'),
    }


def parse_trademark(payload: Any) -> dict:
    """
    get_trademark_info → 商标。同样必须看「商标状态」：
    「商标无效·初审驳回」= 未获注册，直接推翻"品牌已注册"的结论。

    2026-10-19：与 parse_patent 同步支持**预聚合分布**（Agent 回填场景）。
    """
    items = _pick_list(payload, '商标信息', '商标列表', '商标')
    st = _dist(items, '商标状态')
    # 预聚合分布优先
    if not st:
        pre = (payload.get('状态分布') or payload.get('status_dist') or {})
        if isinstance(pre, dict) and pre:
            st = {str(k): int(v) for k, v in pre.items()}
    invalid = sum(v for k, v in st.items()
                  if any(x in k for x in ('无效', '驳回', '撤销')))
    total = payload.get('总记录数') or payload.get('展示条数') or len(items)
    return {
        'total': int(total) if str(total).isdigit() else len(items),
        'displayed': len(items) or int(payload.get('展示条数') or 0),
        'tool_reported_total': _tool_total(payload) or payload.get('总记录数'),
        'truncated_by_tool': _tool_truncated(payload) or bool(payload.get('展示条数')),
        'items': items[:30],
        'truncated': len(items) > 30,
        'status_dist': st,
        'class_dist': _dist(items, '国际分类'),
        'invalid_or_rejected_count': invalid,
        'stats_basis': ('预聚合分布（工具返回样本）' if st and not _dist(items, '商标状态')
                        else '逐条统计'),
    }


# ============================================================
# 工具名 → (解析器, 归一 key)
# ============================================================
_TOOL_PARSERS = {
    'get_company_risk_scan': ('scan', parse_risk_scan),
    'get_company_related_risk_scan': ('related_scan', parse_related_risk),
    'get_stock_pledge_info': ('pledge_stock', lambda p: parse_pledge(p, 'stock')),
    'get_equity_pledge_info': ('pledge_equity', lambda p: parse_pledge(p, 'equity')),
    'get_case_filing_info': ('case_filing', parse_case_filing),
    'get_judgment_debtor_info': ('debtor', parse_debtor),
    'get_dishonest_info': ('dishonest', parse_dishonest),
    'get_patent_info': ('patent', parse_patent),
    'get_trademark_info': ('trademark', parse_trademark),
}


def _load_mcp(data_dir: str) -> dict:
    try:
        from mcp_bridge import load_mcp_results
    except ImportError:
        from scripts.mcp_bridge import load_mcp_results
    return load_mcp_results(data_dir)


# ============================================================
# 构建 legal_risk 维度结果
# ============================================================
def build_legal_risk(data_dir: str, findings: Optional[dict] = None) -> dict:
    """
    构建 legal_risk 维度结果（消费 data/mcp 下已回填的 qcc 结果）。

    Returns:
        {
          'status': 'ok' | 'empty' | 'not_backfilled' | 'error',
          'scan': {...}, 'pledge_stock': {...}, ...,
          'signals': [{domain, label, count, level, source_tool, corroborated}],
          'missing_tools': [...],       # 计划内但未回填/失败
          'failed_tools': [...],
          'assessment': 'needs_corroboration' | 'no_structured_record' | 'insufficient',
          'verdict': str,               # 合规措辞的结论句（绝不定性）
          'cross_check': {...},
          'gaps': [...],
        }
    """
    if not data_dir or not os.path.isdir(data_dir):
        return {'status': 'error', 'error': f'data_dir 不存在: {data_dir}'}

    allm = _load_mcp(data_dir)
    slot = allm.get('legal_risk')
    if not slot:
        return {
            'status': 'not_backfilled',
            'error': 'legal_risk 未回填 qcc 数据（见 mcp_plan.json 的 legal_risk 计划）',
            'missing_tools': sorted(set(t for _, t, _ in _registered_tools('legal_risk'))),
            'gaps': ['legal_risk 全维度未回填 → 法律/合规风险不可评估，本维度不得出结论'],
        }
    if slot.get('error') and not slot.get('ok_tool_count'):
        return {
            'status': 'error',
            'error': slot.get('error'),
            'failed_tools': sorted(slot.get('errors', {}).keys()),
            'gaps': ['legal_risk 全部 qcc 工具调用失败'],
        }

    parsed: Dict[str, Any] = {}
    errors: Dict[str, str] = dict(slot.get('errors') or {})
    for tool, entry in (slot.get('tools') or {}).items():
        if entry.get('error'):
            continue
        spec = _TOOL_PARSERS.get(tool)
        if not spec:
            continue
        key, fn = spec
        try:
            parsed[key] = fn(entry.get('result'))
        except Exception as e:  # 单工具解析失败不影响其他维度
            errors[tool] = f'解析失败: {e}'

    planned = sorted(set(t for _, t, _ in _registered_tools('legal_risk')))
    missing = [t for t in planned if t not in (slot.get('tools') or {})]

    # ── 信号汇总：逐因子列出，绝不跨因子加总 ──
    signals = []
    scan = parsed.get('scan') or {}
    for f in scan.get('all_factors', []):
        if not (isinstance(f.get('count'), (int, float)) and f['count'] > 0):
            continue
        # 🔴 2026-10-19：这些维度是**历史累计**（含已解除/已结案），
        # 不能当作"当前在押/在诉"读。有明细工具的须以明细为准。
        _CUMULATIVE = {'股权质押', '股权出质', '担保信息', '裁判文书',
                       '立案信息', '开庭公告', '法院公告', '送达公告'}
        _is_cum = f['factor'] in _CUMULATIVE
        signals.append({
            'domain': 'company_risk',
            'label': f['label'],
            'factor': f['factor'],
            'count': f['count'],
            'level': f['level'],
            'is_cumulative': _is_cum,
            'source_tool': 'get_company_risk_scan',
            'detail_tool': f.get('detail_tool') or '',
            'statement': (f"「{f['factor']}」维度历史累计 {f['count']} 条"
                          f"（qcc get_company_risk_scan，服务端聚合终值，未加总"
                          + ("；**含已解除/已结案，当前在册数以明细工具为准**"
                             if _is_cum else "") + "）"),
        })

    for key, dom, label in (('pledge_stock', 'stock_pledge', '上市公司股权质押'),
                            ('pledge_equity', 'equity_pledge', '股东股权出质')):
        p = parsed.get(key)
        if p and p.get('active_count'):
            signals.append({
                'domain': dom, 'label': label, 'level': 'attention',
                'count': p['active_count'],
                'total_records': p['total_records'],
                'source_tool': ('get_stock_pledge_info' if dom == 'stock_pledge'
                                else 'get_equity_pledge_info'),
                'statement': (f"{label}在册记录 {p['active_count']} 条仍在押/在质"
                              f"（总记录 {p['total_records']} 条，其余为已解除/已注销）"),
            })

    for key, dom, label in (('dishonest', 'dishonest', '失信被执行'),
                            ('debtor', 'judgment_debtor', '被执行人')):
        p = parsed.get(key)
        if p and p.get('total'):
            signals.append({
                'domain': dom, 'label': label,
                'level': 'severe', 'count': p['total'], 'source_tool': _DOM_TOOL.get(dom, ''),
                'statement': f"{label}在册 {p['total']} 条（未下钻明细，仅计数事实）",
            })

    cf = parsed.get('case_filing')
    if cf and cf.get('total'):
        # 只有"我方为被告"才是被诉风险；原告是主动维权
        if cf.get('as_defendant'):
            signals.append({
                'domain': 'case_filing', 'label': '在册立案·我方为被告/被上诉人',
                'level': 'severe', 'count': cf['as_defendant'],
                'total_records': cf['total'],
                'source_tool': 'get_case_filing_info',
                'statement': (f"在册立案共 {cf['total']} 条（本口径：{cf['count_basis']}"
                              + (f"，工具称累计 {cf['tool_reported_total']} 条"
                                 if cf.get('tool_reported_total') else "")
                              + f"），其中**我方作为被告/被上诉人 "
                              f"{cf['as_defendant']} 条**（原告方 {cf['as_plaintiff']} 条、"
                              f"第三人 {cf['as_third_party']} 条、角色待确认 {cf['role_undetermined']} 条）。"
                              f"常见案由：{('、'.join(list(cf['top_causes'].keys())[:3])) or 'N/A'}"),
                'detail_tool': 'get_case_filing_info',
            })
        if cf.get('as_plaintiff'):
            signals.append({
                'domain': 'case_plaintiff', 'label': '在册立案·我方为原告/上诉人',
                'level': 'attention', 'count': cf['as_plaintiff'],
                'source_tool': 'get_case_filing_info',
                'statement': f"我方作为原告/上诉人 {cf['as_plaintiff']} 条（主动维权，非被诉风险）",
            })

    rel = parsed.get('related_scan') or {}
    if rel.get('factors_with_record'):
        crit = rel.get('critical_hit') or []
        crit_txt = ('，重点风险维度命中：' + '、'.join(f"{f['factor']}({f['count']})" for f in crit)
                    if crit else '，重点风险维度（失信/严重违法/破产重整/税收违法/被执行/终本/股权冻结）均为 0')
        signals.append({
            'domain': 'related_party', 'label': '关联方风险传导',
            'level': 'severe' if crit else 'attention',
            'count': rel['factors_with_record'],
            'risky_party_count': rel.get('risky_party_count'),
            'source_tool': 'get_company_related_risk_scan',
            'statement': (f"直接关联方中有风险记录者 {rel.get('risky_party_count')} 家，"
                          f"共 {rel['factors_with_record']} 个风险维度存在记录{crit_txt}"
                          f"（人企合并计数，未加总）"),
        })

    # ── 交叉印证（qcc 单源不得实锤）──
    cross = _cross_check(signals, findings or {})

    # ── 结论：严格合规措辞 ──
    if not signals:
        verdict = ('qcc 35 项结构化风险因子当前均无记录，'
                   '**仅代表结构化维度无在册记录，不等于公司无风险**；'
                   '未取舆情（get_news_sentiment）前不得出整体定性结论。')
        assessment = 'no_structured_record'
        gaps = ['舆情维度未取（qcc-news get_news_sentiment）→ 负面舆情未覆盖']
    else:
        severe = [s for s in signals if s['level'] == 'severe']
        confirmed = [s for s in signals if s.get('corroborated')]
        if confirmed:
            assessment = 'needs_corroboration'
        else:
            assessment = 'needs_corroboration' if signals else 'no_structured_record'
        verdict = (f"qcc 结构化风险维度共 {len(signals)} 项有记录"
                   + (f"，其中严重类 {len(severe)} 项" if severe else "")
                   + "。以上为**命中维度与计数的事实陈述**，"
                   "未下钻明细工具前不作定性结论；"
                   + (f"其中 {len(confirmed)} 项获独立信号交叉印证。" if confirmed
                      else "暂未获第二个独立来源交叉印证，一律标记为「需核实的疑点」。"))
        gaps = ['未并行取舆情（get_news_sentiment）→ 负面舆情未覆盖'
                if not (findings or {}).get('news_sentiment')
                and 'get_news_sentiment' not in missing else '']
    gaps = [g for g in gaps if g]
    cfp = parsed.get('case_filing') or {}
    if cfp.get('truncated_by_tool') and cfp.get('tool_reported_total'):
        gaps.append(f"立案明细被工具截断（返回 {cfp['total']} 条 / 称累计 {cfp['tool_reported_total']} 条）"
                    f" → 被诉角色分布仅覆盖展示部分，占比不可外推至全量")
    if missing:
        gaps.append('未回填工具：' + ', '.join(missing))
    if errors:
        gaps.append('调用/解析失败：' + ', '.join(f'{k}({v})' for k, v in errors.items()))

    status = 'ok' if signals else 'empty'
    return {
        'status': status,
        'company_name': scan.get('company_name'),
        'scan': scan,
        'pledge_stock': parsed.get('pledge_stock'),
        'pledge_equity': parsed.get('pledge_equity'),
        'case_filing': parsed.get('case_filing'),
        'dishonest': parsed.get('dishonest'),
        'debtor': parsed.get('debtor'),
        'related_scan': rel,
        'signals': signals,
        'signal_count': len(signals),
        'severe_count': len([s for s in signals if s['level'] == 'severe']),
        'missing_tools': missing,
        'failed_tools': errors,
        'tools_backfilled': sorted((slot.get('tools') or {}).keys()),
        'cross_check': cross,
        'assessment': assessment,
        'verdict': verdict,
        'gaps': gaps,
        'source': 'qcc-company',
        'discipline': 'qcc AI 数据纪律：计数逐字引用不加总；scan 仅分诊不定性；全0≠无风险',
    }


_DOM_TOOL = {
    'dishonest': 'get_dishonest_info',
    'judgment_debtor': 'get_judgment_debtor_info',
    'case_filing': 'get_case_filing_info',
}


def _cross_check(signals: List[dict], findings: dict) -> dict:
    """与本地 findings 交叉；≥2 独立信号才允许升级 corroborated"""
    local_text = []
    cv = findings.get('cross_validation') or {}
    for f in (cv.get('findings') or []):
        if isinstance(f, dict):
            local_text.append(str(f.get('title') or f.get('description') or ''))
    reg = findings.get('regulatory') or {}
    for r in (reg.get('records') or reg.get('items') or []):
        if isinstance(r, dict):
            local_text.append(str(r.get('title') or r.get('reason') or ''))

    KEYWORDS = {
        'dishonest': ('失信', '老赖'),
        'judgment_debtor': ('被执行', '执行'),
        'case_filing': ('诉讼', '仲裁', '起诉', '立案'),
        'stock_pledge': ('质押', '平仓', '冻结'),
        'equity_pledge': ('质押', '出质'),
    }
    corroborated = []
    for s in signals:
        kws = KEYWORDS.get(s['domain'], ())
        hit = [t for t in local_text if t and any(k in t for k in kws)]
        s['corroborated'] = bool(hit)
        s['corroborating_signals'] = hit[:3]
        if hit:
            corroborated.append(s['label'])
    return {
        'local_sources_checked': ['cross_validation', 'regulatory'],
        'corroborated': corroborated,
        'rule': 'qcc 单源不得下实锤；需 ≥2 独立信号方可定性',
    }


def _registered_tools(dim: str):
    try:
        from data_source_registry import SOURCE_REGISTRY
    except ImportError:
        from scripts.data_source_registry import SOURCE_REGISTRY
    spec = SOURCE_REGISTRY.get(dim, {})
    return list(spec.get('mcp_primary') or []) + list(spec.get('mcp_fallback') or [])


# ============================================================
# 构建 intellectual_property 维度
# ============================================================
def build_intellectual_property(data_dir: str) -> dict:
    if not data_dir or not os.path.isdir(data_dir):
        return {'status': 'error', 'error': f'data_dir 不存在: {data_dir}'}
    allm = _load_mcp(data_dir)
    slot = allm.get('intellectual_property')
    if not slot:
        return {
            'status': 'not_backfilled',
            'error': 'intellectual_property 未回填 qcc 数据',
            'missing_tools': sorted(set(t for _, t, _ in _registered_tools('intellectual_property'))),
            'gaps': ['IP 维度未回填 → 专利/商标不得用于技术壁垒或资产化判断'],
        }
    if slot.get('error') and not slot.get('ok_tool_count'):
        return {'status': 'error', 'error': slot.get('error'),
                'failed_tools': sorted(slot.get('errors', {}).keys())}

    patents = parse_patent((slot.get('tools') or {}).get('get_patent_info', {}).get('result'))
    trademarks = parse_trademark((slot.get('tools') or {}).get('get_trademark_info', {}).get('result'))
    gaps = []
    if patents.get('truncated_by_tool'):
        gaps.append('专利返回被工具截断（仅展示前 N 条），'
                    f"分布统计仅覆盖展示的 {patents['total']} 条，"
                    f"服务端称总量 {patents.get('tool_reported_total')} 条 —— 状态分布不可外推至全量")
    if trademarks.get('truncated_by_tool'):
        gaps.append('商标返回被工具截断')
    ptot = patents.get('tool_reported_total') or patents['total']
    ttot = trademarks.get('tool_reported_total') or trademarks['total']
    verdict = (f"qcc 当前有效专利记录 {ptot} 条（展示 {patents['total']} 条，"
               f"其中在权/授权 {patents['in_force_count']} 条、"
               f"主动放弃或权终止 {patents['abandoned_or_terminated_count']} 条）；"
               f"商标 {ttot} 条（展示 {trademarks['total']} 条，"
               f"其中无效/驳回 {trademarks['invalid_or_rejected_count']} 条）。"
               "**专利/商标「有 N 条」不等于「有 N 项在权壁垒」** —— "
               "评估技术护城河或 IP 资本化能力时须先下钻明细核实法律状态与剩余期限。")
    return {
        'status': 'ok' if (patents['total'] or trademarks['total']) else 'empty',
        'patent': patents,
        'trademark': trademarks,
        'patent_count_returned': patents['total'],
        'trademark_count_returned': trademarks['total'],
        'patent_count_reported': ptot,
        'trademark_count_reported': ttot,
        'patent_in_force': patents['in_force_count'],
        'patent_abandoned_or_terminated': patents['abandoned_or_terminated_count'],
        'trademark_invalid_or_rejected': trademarks['invalid_or_rejected_count'],
        'tools_backfilled': sorted((slot.get('tools') or {}).keys()),
        'missing_tools': [t for t in sorted(set(t for _, t, _ in _registered_tools('intellectual_property')))
                          if t not in (slot.get('tools') or {})],
        'verdict': verdict,
        'gaps': gaps,
        'source': 'qcc-company',
    }


# ============================================================
# Markdown 渲染
# ============================================================
def format_legal_risk_markdown(r: dict) -> str:
    if r.get('status') in ('not_backfilled', 'error'):
        return (f"\n## 🔴 法律/合规风险维度：数据缺口\n\n"
                f"**未取得 qcc 权威数据，本维度不得出任何结论。**\n\n"
                f"- 原因：{r.get('error')}\n"
                + (f"- 未回填工具：{', '.join(r.get('missing_tools') or [])}\n"
                   if r.get('missing_tools') else '')
                + (f"- 失败工具：{', '.join(r.get('failed_tools') or {})}\n"
                   if r.get('failed_tools') else '')
                + "\n补齐：按 `mcp_plan.json` 的 legal_risk 计划调用 qcc-company 工具并 `save_mcp_result` 回填。\n")

    lines = ["\n## ⚖️ 法律 / 合规风险（qcc 权威源）\n"]
    lines.append(f"**结论**：{r.get('verdict', '')}\n")

    scan = r.get('scan') or {}
    if scan.get('summary'):
        lines.append(f"> qcc 原始摘要：{scan['summary']}\n")

    sigs = r.get('signals') or []
    if sigs:
        lines.append("### 命中维度与计数（逐项列示，未跨维加总）\n")
        lines.append("| 维度 | 计数 | 级别 | 交叉印证 | 来源工具 |")
        lines.append("|---|---|---|---|---|")
        for s in sorted(sigs, key=lambda x: (x['level'] != 'severe', -(x.get('count') or 0))):
            lvl = '🔴' if s['level'] == 'severe' else '🟡'
            cross = '✅ 有' if s.get('corroborated') else '⚪ 无（需核实）'
            lines.append(f"| {s['label']} | {s.get('count', '—')} | {lvl} | {cross} | `{s.get('source_tool','')}` |")
        lines.append("")

        sev = [s for s in sigs if s['level'] == 'severe']
        if sev:
            lines.append("**🔴 严重类命中（须立即下钻明细工具核实）**：\n")
            for s in sev:
                lines.append(f"- **{s['label']}** {s['count']} 条 → 下钻 `{s.get('detail_tool') or _DOM_TOOL.get(s['domain'],'')}`")
            lines.append("")

        cf = r.get('case_filing') or {}
        if cf.get('total'):
            lines.append("### 在册立案的诉讼角色拆分\n")
            lines.append(f"- 立案记录（**{cf.get('count_basis', '返回条目口径')}**）"
                         f"**{cf['total']}** 条"
                         + (f"；工具摘要称累计 {cf['tool_reported_total']} 条"
                            if cf.get('tool_reported_total') else ''))
            lines.append(f"- 🔴 **我方为被告/被上诉人：{cf.get('as_defendant', 0)} 条** ← 真实被诉风险")
            lines.append(f"- 🟢 我方为原告/上诉人：{cf.get('as_plaintiff', 0)} 条（主动维权）")
            lines.append(f"- ⚪ 第三人：{cf.get('as_third_party', 0)} 条 ｜ "
                         f"角色待确认：{cf.get('role_undetermined', 0)} 条")
            if cf.get('truncated_by_tool') and cf.get('tool_reported_total'):
                lines.append(f"> 🔴 **口径警示**：上方角色拆分基于工具返回的 {cf['total']} 条，"
                             f"而 qcc 称累计 {cf['tool_reported_total']} 条。"
                             f"**被告占比不可外推至全量**——被诉风险的完整分布须以全量明细或"
                             f"逐年分页查询复核。")
            if cf.get('top_causes'):
                lines.append("- 主要案由："
                             + " · ".join(f"{k} {v}" for k, v in list(cf['top_causes'].items())[:5]))
            if cf.get('year_dist'):
                lines.append("- 年份分布："
                             + " · ".join(f"{k} 年 {v}" for k, v in list(cf['year_dist'].items())[:8]))
            lines.append("")

        pledge = r.get('pledge_stock') or {}
        if pledge.get('active_count'):
            lines.append("### 股权质押结构（在押 vs 已解除）\n")
            lines.append(f"- 在押 **{pledge['active_count']}** 条 / 总记录 {pledge['total_records']} 条"
                         f"（已解除 {pledge['released_count']} 条）")
            lines.append(f"- 在押合计股数（工具口径，原样引用）："
                         f"{_sum_shares(pledge.get('active'))}")
            lines.append("")
    else:
        lines.append("**结构化风险因子：当前无在册记录。**\n")

    cc = r.get('cross_check') or {}
    lines.append(f"\n*交叉规则：{cc.get('rule','')}；已检查本地来源 "
                 f"{', '.join(cc.get('local_sources_checked') or [])}。*\n")

    if r.get('gaps'):
        lines.append("\n**数据缺口**：\n")
        for g in r['gaps']:
            lines.append(f"- ⚠️ {g}")
        lines.append("")
    return '\n'.join(lines)


def _sum_shares(records: List[dict]) -> str:
    """把 '3500.00万' / '1.26亿' 之类文本转成股数合计（仅在押），保留原口径"""
    total = 0.0
    any_found = False
    for r in records or []:
        s = str(r.get('shares') or '').strip()
        m = re.match(r'^([\d.]+)\s*(亿|万)?', s)
        if not m:
            continue
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        unit = m.group(2) or ''
        total += v * (1e8 if unit == '亿' else 1e4 if unit == '万' else 1)
        any_found = True
    if not any_found:
        return '工具未给可解析口径（不推算）'
    return f"{total / 1e8:.4f}亿股"


def format_ip_markdown(r: dict) -> str:
    if r.get('status') in ('not_backfilled', 'error'):
        return (f"\n## 🔴 知识产权维度：数据缺口\n\n"
                f"**未取得 qcc 数据，专利/商标不得用于技术壁垒判断。**\n\n"
                f"- 原因：{r.get('error')}\n")
    lines = ["\n## 🔬 知识产权（qcc 权威源）\n"]
    lines.append(f"**结论**：{r.get('verdict', '')}\n")

    pt = r.get('patent') or {}
    if pt.get('total'):
        lines.append("### 专利法律状态分布（展示条目口径，非全量）\n")
        lines.append("| 法律状态 | 条数 |")
        lines.append("|---|---|")
        for k, v in (pt.get('status_dist') or {}).items():
            lines.append(f"| {k} | {v} |")
        lines.append("")
        if pt.get('type_dist'):
            lines.append("**专利类型分布**："
                         + " · ".join(f"{k} {v}" for k, v in pt['type_dist'].items()) + "\n")
        lines.append(f"> ⚠️ 展示 {pt['total']} 条中，在权/授权 **{pt.get('in_force_count', 0)}** 条、"
                     f"主动放弃或权终止 **{pt.get('abandoned_or_terminated_count', 0)}** 条。"
                     "评估技术壁垒应以在权专利为准。\n")

    tt = r.get('trademark') or {}
    if tt.get('total'):
        lines.append("### 商标状态分布\n")
        lines.append("| 商标状态 | 条数 |")
        lines.append("|---|---|")
        for k, v in (tt.get('status_dist') or {}).items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    if r.get('gaps'):
        lines.append("\n**数据缺口**：\n")
        for g in r['gaps']:
            lines.append(f"- ⚠️ {g}")
        lines.append("")
    return '\n'.join(lines)


# ============================================================
# CLI
# ============================================================
if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data_dir = sys.argv[1] if len(sys.argv) > 1 else 'output/002180_20261019/data'
    which = sys.argv[2] if len(sys.argv) > 2 else 'legal_risk'
    if which == 'legal_risk':
        print(format_legal_risk_markdown(build_legal_risk(data_dir)))
    else:
        print(format_ip_markdown(build_intellectual_property(data_dir)))
