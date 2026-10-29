# -*- coding: utf-8 -*-
"""
hk_records.py - 港股财务「结构对齐」适配层（2026-10-21 新增）
==========================================================

问题（实测）：
    `hk_financial.fetch_hk_financial()`（AKShare 口径）返回的是
        {'indicators': [{date, operate_income, holder_profit, gross_margin, roe, ...}],
         'valuation': {...}, 'dividend': [...]}
    **没有 `records`** —— 而下游 12 处（article_brief / financial_projection /
    check_numbers / cross_validator…）统一读 `financial['records']`。
    → 港股"财务明明取到了"但最新报告期、数字台账、盈利预测全空。

方案：
    把 `indicators` 映射成 A 股同构 records（年报口径），字段名沿用东财口径。

字段映射（AKShare 港股 → 东财 A 股）：
    date            → REPORTDATE
    operate_income  → TOTAL_OPERATE_INCOME
    holder_profit   → PARENT_NETPROFIT（归母）
    gross_margin    → XSMLL（%）
    roe             → WEIGHTAVG_ROE（%）
    income_yoy      → YSTZ（%）
    profit_yoy      → SJLTZ（%）
    currency        → CURRENCY

口径铁律：
    - 港股年报口径为**年度**（`fiscal_year` 多为 12-31），置 `IS_ANNUAL=True`，
      禁止按 A 股中期年化逻辑处理。
    - 缺字段留空，不补零；`_meta.gaps` 记录缺项。
    - 币种保留原币（HKD/CNY/RMB），不做汇率换算。
"""

from __future__ import annotations

from typing import Dict, List, Optional


def _f(v) -> Optional[float]:
    try:
        if v is None or v == '':
            return None
        return float(v)
    except Exception:
        return None


def indicators_to_records(fin: dict, max_years: int = 8) -> List[dict]:
    """AKShare 港股 indicators → A 股同构 records（年度，升序）"""
    inds = (fin or {}).get('indicators') or []
    recs: List[dict] = []
    for it in inds:
        if not isinstance(it, dict):
            continue
        rd = str(it.get('date') or '')[:10]
        if not rd:
            continue
        rev = _f(it.get('operate_income'))
        npf = _f(it.get('holder_profit'))
        gm = _f(it.get('gross_margin'))
        roe = _f(it.get('roe'))
        recs.append({
            'REPORTDATE': rd,
            'DATATYPE': f"{rd[:4]}年报(港股)",
            'DATAYEAR': rd[:4],
            'QDATE': 'Q4',
            'IS_ANNUAL': True,
            'TOTAL_OPERATE_INCOME': rev,
            'PARENT_NETPROFIT': npf,
            'BASIC_EPS': _f(it.get('eps')) or _f(it.get('basic_eps')),
            'XSMLL': round(gm, 2) if gm is not None else None,
            'WEIGHTAVG_ROE': round(roe, 2) if roe is not None else None,
            'YSTZ': _f(it.get('income_yoy')),
            'SJLTZ': _f(it.get('profit_yoy')),
            'CURRENCY': it.get('currency') or 'HKD',
            'SOURCE': 'akshare_hk',
        })
    recs.sort(key=lambda r: r['REPORTDATE'])
    return recs[-max_years:]


def attach_hk_records(fin: dict, max_years: int = 8) -> dict:
    """就地给港股财务 dict 补 records / latest / summary / _meta。"""
    if not isinstance(fin, dict):
        return fin
    try:
        recs = indicators_to_records(fin, max_years=max_years)
    except Exception as e:
        fin.setdefault('warnings', []).append(f'港股 records 适配失败: {e}')
        return fin

    if not recs:
        fin.setdefault('warnings', []).append(
            '港股 indicators 为空，未能产出 records（AKShare 该标的无数据）')
        return fin

    fin['records'] = recs
    fin['latest'] = recs[-1]
    L = recs[-1]
    cur = L.get('CURRENCY') or 'HKD'
    fin['summary'] = {
        'report_date': L.get('REPORTDATE'),
        'datatype': L.get('DATATYPE'),
        'revenue': L.get('TOTAL_OPERATE_INCOME'),
        'net_profit': L.get('PARENT_NETPROFIT'),
        'revenue_亿': (round(L['TOTAL_OPERATE_INCOME'] / 1e8, 2)
                       if L.get('TOTAL_OPERATE_INCOME') else None),
        'net_profit_亿': (round(L['PARENT_NETPROFIT'] / 1e8, 2)
                          if L.get('PARENT_NETPROFIT') else None),
        'eps': L.get('BASIC_EPS'),
        'roe_pct': L.get('WEIGHTAVG_ROE'),
        'gross_margin_pct': L.get('XSMLL'),
        'revenue_growth_pct': L.get('YSTZ'),
        'profit_growth_pct': L.get('SJLTZ'),
        'currency': cur,
    }
    meta = fin.setdefault('_meta', {})
    meta['records_from'] = 'hk_records.attach_hk_records'
    meta['fiscal_years'] = [r.get('DATAYEAR') for r in recs]
    meta['basis'] = '港股年度口径（IS_ANNUAL=True），原币种未换算'
    meta['gaps'] = [k for k in ('TOTAL_OPERATE_INCOME', 'PARENT_NETPROFIT')
                    if L.get(k) is None]
    return fin


if __name__ == '__main__':
    import json, sys
    sys.path.insert(0, '.')
    import _ctxfix  # noqa: F401
    from hk_financial import fetch_hk_financial
    code = sys.argv[1] if len(sys.argv) > 1 else '00700'
    f = fetch_hk_financial(code, market='hk')
    attach_hk_records(f)
    print(json.dumps(f.get('summary'), ensure_ascii=False, indent=2))
    for r in (f.get('records') or [])[-4:]:
        print(r['REPORTDATE'], r['DATATYPE'],
              round((r.get('TOTAL_OPERATE_INCOME') or 0) / 1e8, 1), '亿',
              '| 净利', round((r.get('PARENT_NETPROFIT') or 0) / 1e8, 1), '亿',
              '| 同比', r.get('YSTZ'))
