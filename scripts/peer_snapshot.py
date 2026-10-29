# -*- coding: utf-8 -*-
"""
同业快照：一组代码 → 可比公司估值与财务对照表

为什么单独做这个脚本（2026-10-20 教训）：
写行业对比时，需要的是"同一天收盘的市值/PB/PS + 同一期年报的营收/净利"。
- `peer_compare` 维度用的是**申万/证监会大类行业**，把东方雨虹、北新建材
  这类体量差几十倍的公司混进来，均值没有参考意义（实测法狮龙被归入
  "制造业-其他制造业"，行业均值营收 28.45 亿 vs 它自己 5.24 亿）。
- 二手资料里的市值有时点。自媒体写"友邦吊顶 2025 年中市值约 25 亿"，
  实测 2026-10-20 是 109.9 亿——差 4 倍。照抄会让整篇对比错掉。

本脚本规则：
- 市值/PB/PS/PE 一律取**当日实时行情**（不缓存、不引用二手数字）
- 营收/净利取**最近一个完整年度**（12-31 截止）
- 打印时就标注取值时点，写作时必须把这个口径写进脚注

用法:
    python scripts/peer_snapshot.py 605318 002718 603551 603272
    python scripts/peer_snapshot.py 605318 002718 --json out.json
"""
import sys
import os
import json
import argparse
from datetime import datetime

# scripts/ 已加入 path，故用不带前缀的导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def snapshot(code: str, market: str = 'a') -> dict:
    """单只股票快照：估值（当日）+ 年报财务"""
    row = {'code': code, 'name': '', 'industry': '', 'price': None,
           'market_cap_亿': None, 'pb': None, 'ps': None, 'pe_ttm': None,
           'report_period': '', 'revenue_亿': None, 'net_profit_亿': None,
           'roe': None, 'error': ''}
    try:
        # 名称：用 valuation 链路的实时简称（该源已实测稳定）
        from dispatcher import get_company_name
        row['name'] = get_company_name(code) or ''
    except Exception as e:
        row['error'] += f'名称失败({type(e).__name__}); '

    try:
        # 行业：optional，失败不影响其他字段
        # （push2 行情接口偶发 RemoteDisconnected，不能让它拖垮整行）
        from free_data_provider import eastmoney_stock_info
        info = eastmoney_stock_info(code) or {}
        row['industry'] = info.get('industry') or ''
    except Exception as e:
        row['error'] += f'行业失败(已忽略); '

    try:
        # 估值倍数（PB/PS/PE 与市值同源，保证口径一致）
        from valuation import fetch_valuation
        v = fetch_valuation(code, market) or {}
        cur = v.get('current') or {}
        for src, dst in (('pb', 'pb'), ('ps', 'ps'), ('pe_ttm', 'pe_ttm')):
            val = cur.get(src)
            if isinstance(val, (int, float)):
                row[dst] = round(val, 2)
        # 市值/价格与估值倍数同源，保证口径一致（避免两处数据不同时点）
        _cap = cur.get('market_cap_亿')
        if isinstance(_cap, (int, float)):
            row['market_cap_亿'] = round(_cap, 2)
        _px = cur.get('price')
        if isinstance(_px, (int, float)):
            row['price'] = _px
    except Exception as e:
        row['error'] += f'估值失败({type(e).__name__}); '

    try:
        # 年报财务（12-31 截止的最近一期）
        from financials import fetch_financials
        fin = fetch_financials(code, market, skip_pdf=True) or {}
        recs = (fin.get('records') if isinstance(fin, dict) else None) or []
        annual = [r for r in recs
                  if str(r.get('REPORTDATE') or '')[:10].endswith('12-31')]
        latest = annual[0] if annual else (recs[0] if recs else {})
        if latest:
            row['report_period'] = str(latest.get('REPORTDATE') or '')[:10]
            rev = latest.get('TOTAL_OPERATE_INCOME')
            npf = latest.get('PARENT_NETPROFIT')
            roe = latest.get('WEIGHTAVG_ROE')
            if isinstance(rev, (int, float)):
                row['revenue_亿'] = round(rev / 1e8, 2)
            if isinstance(npf, (int, float)):
                row['net_profit_亿'] = round(npf / 1e8, 2)
            if isinstance(roe, (int, float)):
                row['roe'] = round(roe, 2)
    except Exception as e:
        row['error'] += f'财务失败({type(e).__name__}); '

    return row


def render(rows: list, asof: str) -> str:
    out = [f'\n同业快照（市值/估值取 {asof} 实时行情；财务取最近一期年报）',
           '=' * 96]
    out.append(f"{'代码':<8}{'名称':<10}{'市值亿':>10}{'PB':>8}{'PS':>9}{'PE(TTM)':>12}"
               f"{'报告期':>12}{'营收亿':>10}{'净利亿':>10}{'ROE%':>8}")
    out.append('-' * 96)
    for r in rows:
        if r.get('error') and not r.get('name'):
            out.append(f"{r['code']:<8}取数失败: {r['error']}")
            continue
        out.append(
            f"{r['code']:<8}{r.get('name','')[:8]:<10}"
            f"{_fmt(r.get('market_cap_亿')):>10}{_fmt(r.get('pb')):>8}"
            f"{_fmt(r.get('ps')):>9}{_fmt(r.get('pe_ttm')):>12}"
            f"{r.get('report_period',''):>12}{_fmt(r.get('revenue_亿')):>10}"
            f"{_fmt(r.get('net_profit_亿')):>10}{_fmt(r.get('roe')):>8}")
    out.append('=' * 96)
    # 自动提示：市值排序 vs 营收排序是否背离（这正是行业对比要抓的东西）
    ok = [r for r in rows if r.get('market_cap_亿') and r.get('revenue_亿')]
    if len(ok) >= 2:
        by_cap = sorted(ok, key=lambda x: -x['market_cap_亿'])
        by_rev = sorted(ok, key=lambda x: -x['revenue_亿'])
        if [r['code'] for r in by_cap] != [r['code'] for r in by_rev]:
            out.append('⚠️ 市值排序与营收排序不一致 —— 说明估值差异不是规模驱动，')
            out.append('   大概率来自题材/资本运作/盈利能力差异，行业对比要抓的就是这条。')
        else:
            out.append('市值排序与营收排序一致（估值大体随规模走）。')
    for r in rows:
        if r.get('error'):
            out.append(f"⚠️ {r['code']} {r.get('name') or ''}: {r['error'].rstrip('; ')}")
    return '\n'.join(out)


def _fmt(v):
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:,.2f}'
    return str(v)


def main():
    ap = argparse.ArgumentParser(description='同业快照：可比公司估值与财务对照')
    ap.add_argument('codes', nargs='+', help='股票代码列表，如 605318 002718')
    ap.add_argument('--market', default='a', choices=['a', 'hk', 'us'])
    ap.add_argument('--json', default='', help='同时保存 JSON 到该路径')
    a = ap.parse_args()

    asof = datetime.now().strftime('%Y-%m-%d %H:%M')
    rows = [snapshot(c, a.market) for c in a.codes]
    print(render(rows, asof))

    if a.json:
        json.dump({'asof': asof, 'rows': rows},
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'已保存 {a.json}')


if __name__ == '__main__':
    main()
