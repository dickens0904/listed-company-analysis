# -*- coding: utf-8 -*-
"""
redflag.py —— 财务异常 / 造假嫌疑红旗扫描（纯本地，不依赖 MCP）

设计目标（2026-10-22 新增）：
  投行尽调场景下，自动化初筛「财务数据里值得人工重点核查」的信号。
  不做定罪，只做「指向」——每条红旗带 severity + 证据数字 + 核查方向。

数据源：findings['financial']['records']（东财格式，每行一个报告期）。
  字段做多别名自适应（东财英文键 / 常见中文键），缺失字段自动跳过该行检测并计入 data_gaps。

⚠️ 纪律：
  - 只报「数字异常」，不臆测动机；evidence 必须给出具体报告期 + 数值。
  - 本福定律 / 明细末位分布需要年报附注级明细，本地 records 不提供 → 标 data_gap，不假装做。
  - 关联交易占比需要 qcc/公告级数据，本地无 → 标 data_gap。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# ───────────────────────── 字段别名（多源兼容） ─────────────────────────
FIELD_ALIASES = {
    'report_date':   ['REPORTDATE', '报告期', 'report_date'],
    'is_annual':     ['IS_ANNUAL', '是否年报'],
    'revenue':       ['TOTAL_OPERATE_INCOME', '营业收入', 'OPERATE_INCOME', '营业总收入'],
    'net_profit':    ['PARENT_NETPROFIT', '归母净利润', 'NETPROFIT', '净利润'],
    'receivable':    ['ACCOUNTS_RECEIVABLE', '应收账款', '应收票据及应收账款'],
    'ocf':           ['NETCASH_OPERATE', '经营活动现金流净额', 'NETCASHFLOWS_OPERATE'],
    'gross_margin':  ['GROSS_PROFIT_RATIO', '销售毛利率', 'GROSSMARGINRATIO'],
    'debt_ratio':    ['DEBT_ASSET_RATIO', '资产负债率', 'DEBTTOASSETS'],
    'total_assets':  ['TOTAL_ASSETS', '资产总计', 'TOTAL_ASSET'],
    'roe':           ['ROE', '净资产收益率', 'WEIGHTAVG_ROE'],
    'operate_profit':['OPERATE_PROFIT', '营业利润'],
}


def _alias(rows: List[dict]) -> Dict[str, str]:
    """从记录里推断每个逻辑字段实际用的键名"""
    keys = set()
    for r in rows:
        keys.update(r.keys())
    out = {}
    for logical, candidates in FIELD_ALIASES.items():
        for c in candidates:
            if c in keys:
                out[logical] = c
                break
    return out


def _f(row: dict, alias_map: dict, logical: str):
    k = alias_map.get(logical)
    if not k:
        return None
    v = row.get(k)
    if v in (None, ''):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _yoy(curr, prev):
    if curr is None or prev is None or prev == 0:
        return None
    return (curr - prev) / abs(prev)


def _sort_by_date(rows: List[dict], alias_map: dict) -> List[dict]:
    def _k(r):
        d = str(r.get(alias_map.get('report_date'), '') or '')
        return d[:10]
    return sorted(rows, key=_k)


def scan_redflags(records: List[dict], opts: Optional[dict] = None) -> dict:
    """扫描财务红旗。

    Args:
        records: 东财格式财务记录列表（每期一行）
        opts: {'min_years': 2} 等
    Returns:
        {'flags': [...], 'count': N, 'data_gaps': [...], 'method': ..., 'scanned_periods': N}
    """
    opts = opts or {}
    # 多市场阈值：A股/北交所按制造消费严口径；港股/美股成长股高增、SaaS/平台/生物科技高毛利
    # 均常见，阈值放宽避免误报（仅做「提示」，不降级为「异常定罪」）。
    _market = (opts or {}).get('market', 'a')
    _TH = {'rev_yoy': 0.50, 'gm_high': 0.80, 'gm_jump': 0.20, 'dr_surge': 0.15}
    if _market in ('hk', 'us'):
        _TH = {'rev_yoy': 0.80, 'gm_high': 0.90, 'gm_jump': 0.25, 'dr_surge': 0.20}
    _MKT_LABEL = {'a': 'A股/北交所', 'bse': '北交所', 'hk': '港股', 'us': '美股'}.get(_market, _market)
    flags: List[dict] = []
    gaps: List[str] = []
    if not records or len(records) < 2:
        return {'flags': [], 'count': 0, 'data_gaps': ['记录不足 2 期，无法做同比扫描'],
                'method': '本地财务指标波动扫描', 'scanned_periods': len(records or [])}

    am = _alias(records)
    # 仅用年报期（IS_ANNUAL 标记）做同比，更可比；无标记则全用
    is_annual_key = am.get('is_annual')
    work = records
    if is_annual_key:
        _ann = [r for r in records if str(r.get(is_annual_key, '')).strip() in ('1', 'True', 'true', '是')]
        if len(_ann) >= 2:
            work = _ann
    work = _sort_by_date(work, am)
    n = len(work)

    缺失 = [lg for lg in ('receivable', 'ocf', 'gross_margin', 'debt_ratio')
            if lg not in am]
    if 缺失:
        gaps.append('本地 records 缺字段，下列红旗未扫描：' + '、'.join(缺失))

    # 同比逐期
    for i in range(1, n):
        cur, prev = work[i], work[i - 1]
        cd = str(cur.get(am.get('report_date'), '') or '')[:10]
        pd_ = str(prev.get(am.get('report_date'), '') or '')[:10]

        rev_c, rev_p = _f(cur, am, 'revenue'), _f(prev, am, 'revenue')
        np_c, np_p = _f(cur, am, 'net_profit'), _f(prev, am, 'net_profit')

        # 1. 营收异常波动
        ry = _yoy(rev_c, rev_p)
        if ry is not None and abs(ry) > _TH['rev_yoy']:
            flags.append({
                'type': 'revenue_yoy_abnormal', 'severity': '🟡',
                'period': cd, 'compare_to': pd_,
                'evidence': f'营收同比 {ry*100:+.1f}%（{_fm(rev_p)} → {_fm(rev_c)}）',
                'check': '核查收入确认政策是否变更、是否存在大客户集中或一次性收入',
            })

        # 2. 由盈转亏 / 由亏转盈
        if np_c is not None and np_p is not None:
            if np_p > 0 and np_c <= 0:
                flags.append({'type': 'profit_turn_loss', 'severity': '🔴',
                              'period': cd, 'compare_to': pd_,
                              'evidence': f'归母净利润由盈转亏（{_fm(np_p)} → {_fm(np_c)}）',
                              'check': '核查一次性减值/费用、主业盈利能力是否恶化'})
            elif np_p <= 0 and np_c > 0:
                flags.append({'type': 'profit_turn_profit', 'severity': '🟡',
                              'period': cd, 'compare_to': pd_,
                              'evidence': f'归母净利润由亏转盈（{_fm(np_p)} → {_fm(np_c)}）',
                              'check': '核查是否含非经常性损益（政府补助/资产处置），扣非后是否仍亏'})

        # 3. 应收增速远超营收（收入确认激进信号）
        rec_c, rec_p = _f(cur, am, 'receivable'), _f(prev, am, 'receivable')
        if None not in (rec_c, rec_p, rev_c, rev_p):
            rcy, rvy = _yoy(rec_c, rec_p), _yoy(rev_c, rev_p)
            if rcy is not None and rvy is not None and (rcy - rvy) > 0.30:
                flags.append({'type': 'receivable_gt_revenue', 'severity': '🔴',
                              'period': cd, 'compare_to': pd_,
                              'evidence': f'应收账款同比 {rcy*100:+.1f}% 远超营收 {rvy*100:+.1f}%（差 {(rcy-rvy)*100:.1f}pct）',
                              'check': '核查信用政策是否放宽、是否存在通过放宽账期冲收入'})

        # 4. 经营现金流为负但净利为正（盈利质量差）
        ocf_c = _f(cur, am, 'ocf')
        if ocf_c is not None and np_c is not None and ocf_c < 0 and np_c > 0:
            flags.append({'type': 'ocf_negative_profit_positive', 'severity': '🟡',
                          'period': cd, 'compare_to': pd_,
                          'evidence': f'经营现金流 {_fm(ocf_c)} 为负，但净利 {_fm(np_c)} 为正（背离）',
                          'check': '核查利润含金量：应收/存货是否吞噬现金，是否存在挂账'})

        # 5. 毛利率异常（过高或骤变）——港股/美股高毛利行业常见，仅提示不定罪
        gm_c, gm_p = _f(cur, am, 'gross_margin'), _f(prev, am, 'gross_margin')
        if gm_c is not None:
            if gm_c > _TH['gm_high']:
                if _market in ('hk', 'us'):
                    _gm_ev = f'毛利率 {gm_c*100:.1f}%（港股/美股高毛利行业常见，须对标可比公司）'
                else:
                    _gm_ev = f'毛利率 {gm_c*100:.1f}%（显著高于制造业常态）'
                flags.append({'type': 'gross_margin_too_high', 'severity': '🟡',
                              'period': cd, 'compare_to': pd_,
                              'evidence': _gm_ev,
                              'check': '核查收入成本归集口径、是否含高毛利非主营、可比公司水平'})
            elif gm_p is not None and abs(gm_c - gm_p) > _TH['gm_jump']:
                flags.append({'type': 'gross_margin_jump', 'severity': '🟡',
                              'period': cd, 'compare_to': pd_,
                              'evidence': f'毛利率由 {gm_p*100:.1f}% 骤变至 {gm_c*100:.1f}%（Δ{(gm_c-gm_p)*100:+.1f}pct）',
                              'check': '核查产品结构/定价/成本是否突变，或会计政策变更'})

        # 6. 资产负债率骤升
        dr_c, dr_p = _f(cur, am, 'debt_ratio'), _f(prev, am, 'debt_ratio')
        if dr_c is not None and dr_p is not None and (dr_c - dr_p) > _TH['dr_surge']:
            flags.append({'type': 'debt_ratio_surge', 'severity': '🟡',
                          'period': cd, 'compare_to': pd_,
                          'evidence': f'资产负债率 {dr_p*100:.1f}% → {dr_c*100:.1f}%（+{(dr_c-dr_p)*100:.1f}pct）',
                          'check': '核查有息负债扩张用途、利息覆盖倍数、短债压力'})

    # 7. 本福定律 / 关联交易：本地无明细 → 标 gap
    gaps.append('本福定律（科目末位分布）需年报附注级明细，本地 records 未提供，未扫描')
    gaps.append('关联交易占比需 qcc/公告级数据，本地 records 未提供，未扫描')

    # 去重（同 type+period 仅留一条）
    seen = set()
    uniq = []
    for fl in flags:
        key = (fl['type'], fl['period'])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(fl)
    flags = uniq

    return {
        'flags': flags,
        'count': len(flags),
        'data_gaps': gaps,
        'method': f'本地财务指标波动扫描（{_MKT_LABEL}；营收/净利/应收/现金流/毛利/负债率 同比+背离）',
        'scanned_periods': n,
        'fields_used': list(am.keys()),
    }


def _fm(v):
    if v is None:
        return '—'
    if abs(v) >= 1e8:
        return f'{v/1e8:.2f}亿'
    if abs(v) >= 1e4:
        return f'{v/1e4:.2f}万'
    return f'{v:.2f}'


def render_redflag_md(rf: dict) -> str:
    if not rf.get('flags'):
        return ('### 财务红旗扫描\n\n'
                f'> ✅ 扫描 {rf.get("scanned_periods", 0)} 期，未触发自动红旗。'
                '（自动扫描不替代人工核查；见下方数据缺口）\n')
    out = ['### 财务红旗扫描（本地初筛，须人工复核）', '']
    sev_rank = {'🔴': 0, '🟡': 1}
    for fl in sorted(rf['flags'], key=lambda x: sev_rank.get(x['severity'], 2)):
        out.append(f"- {fl['severity']} **{fl['type']}** 〔{fl['period']} vs {fl['compare_to']}〕")
        out.append(f"  - 证据：{fl['evidence']}")
        out.append(f"  - 核查：{fl['check']}")
    out.append('')
    if rf.get('data_gaps'):
        out.append('> 📋 未覆盖（需补充数据源）：' + '；'.join(rf['data_gaps']))
    return '\n'.join(out)


# ───────────────────────── CLI / 自测 ─────────────────────────
if __name__ == '__main__':
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(description='财务红旗扫描（纯本地）')
    ap.add_argument('--records', help='含 records 的 json 路径（findings.financial）')
    ap.add_argument('--demo', action='store_true', help='用合成样本自测')
    ap.add_argument('--md', action='store_true', help='输出 markdown')
    a = ap.parse_args()

    if a.demo:
        sample = [
            {'REPORTDATE': '2023-12-31', 'IS_ANNUAL': '1',
             'TOTAL_OPERATE_INCOME': 10e8, 'PARENT_NETPROFIT': 1e8,
             'ACCOUNTS_RECEIVABLE': 2e8, 'NETCASH_OPERATE': 1.2e8,
             'GROSS_PROFIT_RATIO': 0.35, 'DEBT_ASSET_RATIO': 0.40},
            {'REPORTDATE': '2024-12-31', 'IS_ANNUAL': '1',
             'TOTAL_OPERATE_INCOME': 16e8, 'PARENT_NETPROFIT': -0.5e8,
             'ACCOUNTS_RECEIVABLE': 7e8, 'NETCASH_OPERATE': -0.8e8,
             'GROSS_PROFIT_RATIO': 0.62, 'DEBT_ASSET_RATIO': 0.58},
        ]
        rf = scan_redflags(sample)
        print(_json.dumps(rf, ensure_ascii=False, indent=2) if not a.md else render_redflag_md(rf))
        sys.exit(0)

    if a.records:
        data = _json.load(open(a.records, encoding='utf-8'))
        recs = data if isinstance(data, list) else data.get('records') or data.get('financial', {}).get('records', [])
        rf = scan_redflags(recs)
        print(render_redflag_md(rf) if a.md else _json.dumps(rf, ensure_ascii=False, indent=2, default=str))
