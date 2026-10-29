# -*- coding: utf-8 -*-
"""
bse_migrate.py - 北交所代码迁移解析（2026-10-21 新增）
=====================================================

问题（实测根因）：
    北交所股票代码正从 8xxxxx / 4xxxxx 迁到 **920xxx** 段。东财 2026 年后的接口
    （业绩报表 RPT_LICO_FN_CPD、公告 np-anotice-stock）**只认 920 段**：
        - 830799（艾融软件）→ 财务 0 条、公告 0 条、年报 0 条
        - 920799（同一家公司）→ 财务 60+ 期、公告 100 条、年报 PDF 可取
    行情接口 push2 对老代码仍返回数据，但证券简称带「(已切换)」后缀：
        f58 = "艾融软件(已切换)"

方案：
    给定老代码 → 先取行情简称 → 去掉「(已切换)」→ 用简称在业绩报表里反查 920 代码。
    纯 HTTP，无需 MCP；模块级缓存避免重复请求。

用法：
    from bse_migrate import resolve_bse_code
    m = resolve_bse_code('830799')
    # → {'input':'830799','current_code':'920799','name':'艾融软件','switched':True}
    code = m['current_code']   # 后续所有东财接口都用它

铁律：
    - 只有 **确实查出不同代码** 才切换；查不到就原样返回（宁可不切，不可乱切）。
    - 原始代码必须保留在返回值的 `input`，写入 `_meta` 供溯源。
"""

from __future__ import annotations

import re
import requests
from typing import Dict, Optional

_UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}
_CACHE: Dict[str, dict] = {}

# 「(已切换)」「（已切换）」等后缀
_SWITCH_SUFFIX = re.compile(r'[（(]\s*已切换\s*[)）]')


def is_bse_code(code: str) -> bool:
    """是否北交所代码：8xxxxx / 4xxxxx / 920xxx"""
    c = str(code).strip()
    return c.startswith(('8', '4', '920'))


def _em_quote_name(code: str) -> Optional[str]:
    """取证券简称：东财 push2（可能带「(已切换)」）→ 腾讯行情兜底（干净简称）。

    本机代理会让 push2 间歇性 ProxyError，故降级到腾讯（bj 前缀，GBK 编码）。
    """
    try:
        j = requests.get(
            'https://push2.eastmoney.com/api/qt/stock/get',
            params={'secid': f'0.{code}', 'fields': 'f57,f58', 'invt': '2', 'fltt': '1'},
            headers=_UA, timeout=8,
        ).json()
        nm = ((j.get('data') or {}).get('f58') or '').strip()
        if nm:
            return nm
    except Exception:
        pass
    # 兜底：腾讯行情（不走系统代理，避免 ProxyError）
    try:
        s = requests.Session()
        s.trust_env = False
        s.headers.update({'User-Agent': 'Mozilla/5.0'})
        r = s.get(f'https://qt.gtimg.cn/q=bj{code}', timeout=8)
        r.encoding = 'gbk'
        parts = r.text.split('~')
        if len(parts) > 2 and parts[1].strip():
            return parts[1].strip()
    except Exception:
        pass
    return None


def _em_code_by_name(name: str) -> Optional[str]:
    """用证券简称在业绩报表里反查当前 SECURITY_CODE（最新报告期）"""
    if not name:
        return None
    try:
        j = requests.get(
            'https://datacenter-web.eastmoney.com/api/data/v1/get',
            params={
                'reportName': 'RPT_LICO_FN_CPD',
                'columns': 'SECURITY_CODE,SECURITY_NAME_ABBR,REPORTDATE',
                'filter': f'(SECURITY_NAME_ABBR="{name}")',
                'pageNumber': 1, 'pageSize': 5,
                'sortTypes': -1, 'sortColumns': 'REPORTDATE',
                'source': 'WEB', 'client': 'WEB',
            },
            headers=_UA, timeout=15,
        ).json()
        for row in ((j.get('result') or {}).get('data') or []):
            c = str(row.get('SECURITY_CODE') or '').strip()
            if c:
                return c
    except Exception:
        pass
    return None


def resolve_bse_code(stock_code: str) -> dict:
    """解析北交所当前代码。

    Returns:
        {'input','current_code','name','switched','reason'}
        `switched=True` 表示老代码已迁到新代码，调用方应改用 `current_code`。
    """
    code = str(stock_code).strip().upper().replace('.BJ', '')
    if code in _CACHE:
        return _CACHE[code]

    out = {'input': code, 'current_code': code, 'name': None,
           'switched': False, 'reason': ''}

    if not is_bse_code(code):
        out['reason'] = '非北交所代码，跳过迁码解析'
        _CACHE[code] = out
        return out

    if code.startswith('920'):
        out['reason'] = '已是 920 新代码'
        _CACHE[code] = out
        return out

    raw_name = _em_quote_name(code)
    if raw_name:
        out['name'] = _SWITCH_SUFFIX.sub('', raw_name).strip()
        out['quote_name_raw'] = raw_name
    try:
        cur = _em_code_by_name(out['name']) if out['name'] else None
    except Exception:
        cur = None

    if cur and cur != code:
        out['current_code'] = cur
        out['switched'] = True
        out['reason'] = f"老代码 {code} 已迁码 → {cur}（东财新接口仅认 920 段）"
    elif raw_name and '切换' in raw_name:
        out['switched'] = True
        out['reason'] = f"行情简称标注「已切换」，但未反查到新代码（原名={raw_name}）"
    else:
        out['reason'] = '未发现迁码（按原代码继续）'

    _CACHE[code] = out
    return out


if __name__ == '__main__':
    import sys, json
    for c in (sys.argv[1:] or ['830799', '835185', '920799', '600519']):
        print(json.dumps(resolve_bse_code(c), ensure_ascii=False))
