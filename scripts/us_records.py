# -*- coding: utf-8 -*-
"""
us_records.py - 美股财务「结构对齐」适配层（2026-10-21 新增）
==========================================================

问题（实测）：
    `sec_xbrl_api.fetch_us_financials()` 返回的是
        {'financials': {'revenue': [{'date','value','frame'}...], ...}}
    而下游 12 处（article_brief._latest_financial / financial_projection /
    check_numbers.build_slots / cross_validator …）统一读
        financial['records'] = [{REPORTDATE, TOTAL_OPERATE_INCOME, PARENT_NETPROFIT, ...}]
    → 美股"有数据但读不到"：article_brief 拿不到最新报告期，证据包数字台账全空。

方案：
    把 SEC XBRL 的科目序列映射成 **A 股同构 records**（10-K 年报口径），字段名沿用
    东财口径，下游零改动即可消费。

口径铁律：
    1. **只取年度 frame**（`CY2019`/`CY2020`…）→ 得到完整财年值，避免把单季
       （CY2026Q2）或 TTM 当成年度值。
    2. 会计年度末不一定是 12-31（苹果是 9 月最后一个周六），故 `IS_ANNUAL=True`
       显式标注，`article_brief` 据此判定"已是年度口径"，不做中期年化。
    3. 缺科目就留空（None），**不补零、不外推**；`_meta.gaps` 记录缺什么。
    4. 金额一律 USD 原值（不换算），由展示层决定单位。

用法：
    from us_records import attach_records
    fin = fetch_us_financials('AAPL')
    attach_records(fin, 'AAPL')      # 就地补 records / latest / summary / _meta
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_ANNUAL_FRAME = re.compile(r'^CY(20\d{2})$')
_QUARTER_FRAME = re.compile(r'^CY(20\d{2})Q([1-4])$')


def _annual_series(series: List[dict]) -> Dict[int, dict]:
    """从单科目序列取「年度」值：优先 CYyyyy 年度 frame。"""
    out: Dict[int, dict] = {}
    for it in series or []:
        frame = str(it.get('frame') or '')
        m = _ANNUAL_FRAME.match(frame)
        if not m:
            continue
        out[int(m.group(1))] = it
    return out


def _instant_by_date(series: List[dict]) -> Dict[str, float]:
    """时点科目（资产/权益）：date → value（同日期取第一条非空）"""
    out: Dict[str, float] = {}
    for it in series or []:
        d = str(it.get('date') or '')[:10]
        v = it.get('value')
        if d and isinstance(v, (int, float)):
            out.setdefault(d, float(v))
    return out


def _nearest(mapping: Dict[str, float], date: str) -> Optional[float]:
    """取与 date 相同或最近（不晚于）的时点值"""
    if not mapping:
        return None
    if date in mapping:
        return mapping[date]
    earlier = [(d, v) for d, v in mapping.items() if d <= date]
    if earlier:
        return max(earlier, key=lambda x: x[0])[1]
    return min(mapping.items(), key=lambda x: x[0])[1]


def financials_to_records(fin: dict, max_years: int = 6) -> List[dict]:
    """SEC XBRL financials → A 股同构 records（年报口径，升序）。

    Returns: [{'REPORTDATE','DATATYPE','IS_ANNUAL','TOTAL_OPERATE_INCOME',
               'PARENT_NETPROFIT','BASIC_EPS','BPS','TOTAL_ASSETS',
               'TOTAL_PARENT_EQUITY','XSMLL','WEIGHTAVG_ROE','YSTZ','SJLTZ',
               'CURRENCY','SOURCE'}]
    """
    items = (fin or {}).get('financials') or {}
    if not items:
        return []

    # 以 revenue 或 net_income 的年度序列作为「财年轴」
    base_key = 'revenue' if items.get('revenue') else 'net_income'
    base = _annual_series(items.get(base_key) or [])
    if not base:
        # 无年度 frame（少数公司只报季度）→ 退回 TTM/最新一条，标注不可年度化
        series = items.get(base_key) or []
        if not series:
            return []
        latest = series[0]
        return [{
            'REPORTDATE': str(latest.get('date') or '')[:10],
            'DATATYPE': '最新期(未取到年度frame)',
            'IS_ANNUAL': False,
            'TOTAL_OPERATE_INCOME': _val(items, 'revenue', latest.get('date')),
            'PARENT_NETPROFIT': _val(items, 'net_income', latest.get('date')),
            'CURRENCY': 'USD', 'SOURCE': 'sec_xbrl',
            '_note': 'SEC 未返回 CY 年度 frame，禁止按年度口径解读',
        }]

    years = sorted(base.keys())[-max_years:]

    # 时点科目映射（用于资产/权益）
    assets_map = _instant_by_date(items.get('total_assets') or [])
    equity_map = _instant_by_date(items.get('total_equity') or [])
    shares_map = _instant_by_date(items.get('shares_outstanding') or [])

    recs: List[dict] = []
    for y in years:
        item = base[y]
        rd = str(item.get('date') or '')[:10]
        rev = item.get('value')
        rev = float(rev) if isinstance(rev, (int, float)) else None
        npf = _annual_value(items.get('net_income'), y)
        eps = _annual_value(items.get('eps_basic'), y)
        gp = _annual_value(items.get('gross_profit'), y)
        eq = _nearest(equity_map, rd)
        assets = _nearest(assets_map, rd)
        shares = _nearest(shares_map, rd)

        rec: Dict[str, Any] = {
            'REPORTDATE': rd,
            'DATATYPE': f'{y}年报(10-K)',
            'DATAYEAR': y,
            'QDATE': 'Q4',
            'IS_ANNUAL': True,
            'TOTAL_OPERATE_INCOME': rev,
            'PARENT_NETPROFIT': npf,
            'BASIC_EPS': eps,
            'TOTAL_ASSETS': assets,
            'TOTAL_PARENT_EQUITY': eq,
            'BPS': round(eq / shares, 4) if (eq and shares) else None,
            'SHARES': shares,   # 股本（供盈利预测算 EPS，避免落到 A 股默认 12.5 亿股）
            'XSMLL': round(gp / rev * 100, 2) if (gp is not None and rev) else None,
            'WEIGHTAVG_ROE': round(npf / eq * 100, 2) if (npf is not None and eq) else None,
            'CURRENCY': 'USD',
            'SOURCE': 'sec_xbrl',
        }
        recs.append(rec)

    # 同比（同一年度序列的相邻年份，不是同期累计）
    for i, r in enumerate(recs):
        if i == 0:
            continue
        prev = recs[i - 1]
        r['YSTZ'] = _pct(r.get('TOTAL_OPERATE_INCOME'), prev.get('TOTAL_OPERATE_INCOME'))
        r['SJLTZ'] = _pct(r.get('PARENT_NETPROFIT'), prev.get('PARENT_NETPROFIT'))

    return recs


def _annual_value(series, year: int):
    if not series:
        return None
    it = _annual_series(series).get(year)
    if not it:
        return None
    v = it.get('value')
    return float(v) if isinstance(v, (int, float)) else None


def _val(items: dict, key: str, date: Optional[str]):
    series = items.get(key) or []
    if not series:
        return None
    if date:
        for it in series:
            if str(it.get('date') or '')[:10] == str(date)[:10]:
                v = it.get('value')
                return float(v) if isinstance(v, (int, float)) else None
    v = series[0].get('value')
    return float(v) if isinstance(v, (int, float)) else None


def _pct(cur, prev):
    try:
        if cur is None or prev in (None, 0):
            return None
        return round((cur - prev) / abs(prev) * 100, 2)
    except Exception:
        return None


def attach_records(fin: dict, ticker: str = '', max_years: int = 6) -> dict:
    """就地给财务 dict 补 records / latest / summary / _meta（美股专用）。"""
    if not isinstance(fin, dict):
        return fin
    try:
        recs = financials_to_records(fin, max_years=max_years)
    except Exception as e:
        fin.setdefault('warnings', []).append(f'美股 records 适配失败: {e}')
        return fin

    if not recs:
        fin.setdefault('warnings', []).append(
            'SEC XBRL 未产出任何年度记录（可能非美企/CIK 未解析）')
        return fin

    fin['records'] = recs
    fin['latest'] = recs[-1]
    latest = recs[-1]
    fin['summary'] = {
        'report_date': latest.get('REPORTDATE'),
        'datatype': latest.get('DATATYPE'),
        'revenue': latest.get('TOTAL_OPERATE_INCOME'),
        'net_profit': latest.get('PARENT_NETPROFIT'),
        'revenue_亿': (round(latest['TOTAL_OPERATE_INCOME'] / 1e8, 2)
                       if latest.get('TOTAL_OPERATE_INCOME') else None),
        'net_profit_亿': (round(latest['PARENT_NETPROFIT'] / 1e8, 2)
                          if latest.get('PARENT_NETPROFIT') else None),
        'eps': latest.get('BASIC_EPS'),
        'roe_pct': latest.get('WEIGHTAVG_ROE'),
        'gross_margin_pct': latest.get('XSMLL'),
        'revenue_growth_pct': latest.get('YSTZ'),
        'profit_growth_pct': latest.get('SJLTZ'),
        'currency': 'USD',
    }
    meta = fin.setdefault('_meta', {})
    meta['source'] = 'sec_xbrl'
    meta['records_from'] = 'us_records.attach_records'
    meta['fiscal_years'] = [r.get('DATAYEAR') for r in recs]
    meta['basis'] = '10-K 年度口径（IS_ANNUAL=True），非中期累计，禁止年化'
    meta['gaps'] = [k for k, v in (fin.get('financials') or {}).items() if not v]
    return fin


if __name__ == '__main__':
    import json, sys
    sys.path.insert(0, '.')
    from sec_xbrl_api import fetch_us_financials
    tk = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    f = fetch_us_financials(tk)
    attach_records(f, tk)
    print(json.dumps(f.get('summary'), ensure_ascii=False, indent=2))
    for r in (f.get('records') or []):
        print(r['REPORTDATE'], r['DATATYPE'],
              round((r.get('TOTAL_OPERATE_INCOME') or 0) / 1e8, 1), '亿USD',
              '| 净利', round((r.get('PARENT_NETPROFIT') or 0) / 1e8, 1), '亿',
              '| 同比', r.get('YSTZ'))
