# -*- coding: utf-8 -*-
"""
us_filings.py - SEC 事件类申报（8-K / DEF 14A / 10-Q）清单（2026-10-22 新增）
================================================================================

为什么需要：
    `us_records` 只解决了"财务数字"，但 A 股还有 capital（资本运作/重大事项）、
    executives（高管）两个维度，美股一直空。这两块在美股对应：
      - 8-K        → 重大事项（并购/控制权/退市风险/审计师变更/业绩快报）
      - DEF 14A    → 股东大会委托书（董事名单、高管薪酬、持股）
      - 10-Q       → 季报（补充最新报告期）
    SEC 的 submissions API 一次就能拿到近 1000 条申报，按 form 过滤即可，无需爬 EDGAR。

边界（必须写进报告）：
    - 只给**申报清单 + 官方链接**，不解析 8-K 正文（正文需逐份抓取，成本高）。
    - DEF 14A 只给链接，高管薪酬明细在正文表格里，须人工/后续解析。
    - 13F 是**机构**申报（不是公司维度），公开无"按公司聚合"的免费接口；
      "谁持有本公司"一律走 Wind `get_stock_equity_holders`（实测美股返回 100+ 家机构）。

用法：
    from us_filings import fetch_us_event_filings
    r = fetch_us_event_filings('AAPL', years=3)
    # {'capital': {...8-K...}, 'executives': {...DEF 14A...}, 'financial': {...10-Q...}}
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

import requests

SEC_HEADERS = {
    'User-Agent': 'listed-company-analysis research contact@example.com',
    'Accept-Encoding': 'gzip, deflate',
}

FORM_BUCKETS = {
    '8-K': ('capital', '重大事项申报(8-K)', '并购/控制权/审计师变更/业绩快报等'),
    'DEF 14A': ('executives', '股东大会委托书(DEF 14A)', '董事名单/高管薪酬/持股'),
    '10-Q': ('financial', '季报(10-Q)', '最新季度财务'),
    'SC 13D': ('capital', '大额持股披露(SC 13D)', '5% 以上主动持股'),
    'SC 13G': ('capital', '大额持股披露(SC 13G)', '5% 以上被动持股'),
}


def _resolve_cik(ticker: str) -> Optional[str]:
    try:
        from us_financial import _resolve_cik as _r
        return _r(ticker)
    except Exception:
        return None


def fetch_us_event_filings(ticker: str, years: int = 3, per_form: int = 30) -> Dict:
    """拉取 8-K / DEF 14A / 10-Q / 13D / 13G 清单（按 form 分桶）。

    Returns: {bucket_dim: {'records': [...], 'count', 'window', '_note'}}
    """
    cik = _resolve_cik(ticker)
    if not cik:
        return {'error': f'CIK 未解析（{ticker}）'}
    try:
        j = requests.get(f'https://data.sec.gov/submissions/CIK{cik}.json',
                         headers=SEC_HEADERS, timeout=40).json()
    except Exception as e:
        return {'error': f'SEC submissions 请求失败: {e}'}

    rec = (j.get('filings') or {}).get('recent') or {}
    forms = rec.get('form') or []
    dates = rec.get('filingDate') or []
    accs = rec.get('accessionNumber') or []
    docs = rec.get('primaryDocument') or []
    descs = rec.get('primaryDocDescription') or []
    cutoff = f'{datetime.now().year - years}-01-01'

    out: Dict[str, dict] = {}
    for i, form in enumerate(forms):
        if form not in FORM_BUCKETS:
            continue
        d = str(dates[i] if i < len(dates) else '')
        if d < cutoff:
            continue
        dim, label, hint = FORM_BUCKETS[form]
        bucket = out.setdefault(dim, {
            'records': [], 'count': 0, 'label': label,
            'window': f'近 {years} 年 SEC 申报（form={form}）',
            'source': 'sec_edgar_submissions',
        })
        acc_raw = str(accs[i] if i < len(accs) else '')
        acc = acc_raw.replace('-', '')
        doc = str(docs[i] if i < len(docs) else '')
        bucket['records'].append({
            'date': d,
            'form': form,
            'type': label,
            'desc': str(descs[i] if i < len(descs) else '') or hint,
            'url': (f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}'
                    if acc and doc else ''),
            'accession': acc_raw,
        })
        bucket['count'] = len(bucket['records'])

    for dim, b in out.items():
        b['records'] = b['records'][:per_form]
        b['count'] = len(b['records'])
        b['_note'] = ('仅申报清单+官方链接，未解析正文；薪酬/交易对价等细节须打开原文核对')
    return out


if __name__ == '__main__':
    import json
    import sys
    tk = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    r = fetch_us_event_filings(tk)
    for dim, b in r.items():
        if not isinstance(b, dict) or 'records' not in b:
            continue
        print(f"== {dim}: {b['count']} 条（{b.get('label')}）==")
        for x in b['records'][:3]:
            print('  ', x['date'], x['form'], '|', x['desc'][:40])
    if 'error' in r:
        print('ERR', r['error'])
