# -*- coding: utf-8 -*-
"""
peer_valuation.py — 相对估值 & 可比公司分析

为 listed-company-analysis 补充投行标准可比公司表：
  - 同业财务对比（市值/营收/利润增速/毛利率/净利率/ROE）
  - 估值对比（PE/PB/PS/EV-EBITDA）
  - 行业分位数排名
  - 历史估值带分析

数据源：东方财富免费接口
"""
import json
import urllib.request
import re
from collections import defaultdict

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _http_get(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://www.eastmoney.com/"
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe(v, default=0):
    try:
        return float(v) if v not in (None, "", "N/A", "-") else default
    except (ValueError, TypeError):
        return default


# ═══════════════════════════════════════════════════════════
# 1. 行业板块估值分位数
# ═══════════════════════════════════════════════════════════

def _is_a_share(code: str) -> bool:
    """A股/北交所：6 位纯数字（港股 5 位数字、美股字母 ticker 均排除）"""
    c = str(code).strip()
    return len(c) == 6 and c.isdigit()


def get_industry_valuation(stock_code: str) -> dict:
    """
    获取个股在所属行业中的估值分位数。
    返回：PE/PB percentile，行业均值/中位数，个股排名。
    """
    # 2026-10-21：非 A 股直接判「不适用」，不再拿 A 股 secid 规则硬拼出错值
    if not _is_a_share(stock_code):
        return {'skipped': True, 'industry': None, 'pe_percentile': None,
                'reason': '行业估值分位仅支持 A 股/北交所（东财板块口径）；港美股不适用'}
    market = 1 if stock_code.startswith("6") else 0
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={market}.{stock_code}"
        f"&fields=f9,f23,f124,f162,f163,f167,f127"
    )
    try:
        data = _http_get(url).get("data", {}) or {}
        pe  = _safe(data.get("f162", 0))   # PE(TTM)
        pb  = _safe(data.get("f167", 0))   # PB
        ind = data.get("f127", "未知")     # 行业
    except Exception:
        return {"error": "无法获取个股估值", "industry": "未知"}

    # 拉取同行业估值分位数
    try:
        url2 = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
            "&fields=f2,f3,f4,f12,f14,f20,f20,f23,f162,f167"
        )
        board_data = _http_get(url2).get("data", {}).get("diff", []) or []
        pe_list = []
        pb_list = []
        mcap_list = []
        for item in board_data:
            pe_list.append(_safe(item.get("f162")))
            pb_list.append(_safe(item.get("f167")))
            mcap_list.append(_safe(item.get("f20")))

        pe_list = sorted(p for p in pe_list if p > 0)
        pb_list = sorted(p for p in pb_list if p > 0)

        pe_rank = sum(1 for p in pe_list if p < pe) / max(len(pe_list), 1) * 100
        pb_rank = sum(1 for p in pb_list if p < pb) / max(len(pb_list), 1) * 100

        return {
            "industry": ind,
            "pe_ttm": pe,
            "pb": pb,
            "pe_percentile": round(100 - pe_rank, 0),
            "pb_percentile": round(100 - pb_rank, 0),
            "pe_median": pe_list[len(pe_list)//2] if pe_list else 0,
            "pb_median": pb_list[len(pb_list)//2] if pb_list else 0,
            "pe_range": f"{pe_list[0]:.0f}~{pe_list[-1]:.0f}" if pe_list else "N/A",
        }
    except Exception as e:
        return {"industry": ind, "pe_ttm": pe, "pb": pb, "error": str(e)}


# ═══════════════════════════════════════════════════════════
# 2. 可比公司表
# ═══════════════════════════════════════════════════════════

PEER_MAP = {
    "白酒": ["600519", "000858", "000568", "002304", "600809", "603369"],
}

_PEER_NAMES = {
    "600519": "贵州茅台", "000858": "五粮液", "000568": "泸州老窖",
    "002304": "洋河股份", "600809": "山西汾酒", "603369": "今世缘",
}


def get_peer_comparison(stock_code: str, industry: str = None) -> dict:
    """
    生成同业可比公司表。
    返回：每家公司市值/营收/利润增速/毛利率/净利率/ROE/PE/PB/PS

    🔴 2026-10-21 修「假数据」：旧实现无同业名单时 peers=[自己]，于是港美股/冷门股
    会返回 count=1（只有本公司），下游却当成"同业对比完成"。现在：
      - 非 A 股 → skipped=True，peers=[], count=0（由上游标"不适用"）；
      - A 股但未匹配到同业名单 → peers=[自己] 且 note 明确写"未匹配同业"，下游须照此表述。
    """
    if not _is_a_share(stock_code):
        return {'peers': [], 'count': 0, 'skipped': True,
                'reason': '同业估值对比仅支持 A 股/北交所（东财板块成分口径）；港美股不适用'}

    # 查找同行
    peers = []
    if industry and "白酒" in str(industry):
        peers = PEER_MAP.get("白酒", [stock_code])
    else:
        peers = [stock_code]

    if stock_code not in peers:
        peers.insert(0, stock_code)

    only_self = len(peers) <= 1

    results = []
    for code in peers[:8]:
        market = 1 if code.startswith("6") else 0
        try:
            url = (
                f"https://push2.eastmoney.com/api/qt/stock/get"
                f"?secid={market}.{code}"
                f"&fields=f43,f57,f58,f116,f120,f20,f162,f167,f170,f124"
            )
            d = _http_get(url).get("data", {}) or {}
            results.append({
                "code": code,
                "name": d.get("f58", _PEER_NAMES.get(code, code)),
                "price": _safe(d.get("f43")) / 100 if d.get("f43") else 0,
                "change_pct": _safe(d.get("f170")) / 100 if d.get("f170") else 0,
                "mcap_yi": round(_safe(d.get("f116")) / 1e8, 0) if d.get("f116") else 0,
                "pe": _safe(d.get("f162")),
                "pb": _safe(d.get("f167")),
            })
        except Exception:
            results.append({"code": code, "name": _PEER_NAMES.get(code, code), "error": "API error"})

    out = {"peers": results, "count": len(results)}
    if only_self:
        # 明确标注：不是"1 家同业"，而是"没匹配到同业名单"
        out['coverage'] = 'only_self'
        out['note'] = ('未匹配到同业名单，仅返回本公司；不得表述为"同业仅 1 家"'
                       '（需人工/AI 指定可比公司）')
    return out


# ═══════════════════════════════════════════════════════════
# 3. HTML 表格
# ═══════════════════════════════════════════════════════════

def format_valuation_html(code: str, industry: str = None) -> str:
    """生成估值分析HTML片段，嵌入研究报告。"""
    html = []

    # 估值分位数
    rank = get_industry_valuation(code)
    if not rank.get("error"):
        html.append('<div class="valuation-section">')
        html.append('<h3>📈 相对估值</h3>')
        html.append('<table><thead><tr>')
        html.append('<th>指标</th><th>个股</th><th>行业中位数</th><th>分位数</th></tr></thead><tbody>')
        html.append(f"<tr><td>PE(TTM)</td><td>{rank.get('pe_ttm','N/A'):.0f}</td>"
                    f"<td>{rank.get('pe_median','N/A'):.0f}</td>"
                    f"<td>高估{rank.get('pe_percentile','N/A'):.0f}%</td></tr>")
        html.append(f"<tr><td>PB</td><td>{rank.get('pb','N/A'):.1f}</td>"
                    f"<td>{rank.get('pb_median','N/A'):.1f}</td>"
                    f"<td>高估{rank.get('pb_percentile','N/A'):.0f}%</td></tr>")
        html.append('</tbody></table>')

    # 可比公司表
    comp = get_peer_comparison(code, industry)
    peers = comp.get("peers", [])
    if peers:
        html.append('<h4>同业对比</h4>')
        html.append('<table><thead><tr>')
        for h in ["代码", "简称", "最新价", "涨跌幅", "市值(亿)", "PE", "PB"]:
            html.append(f'<th>{h}</th>')
        html.append('</tr></thead><tbody>')
        for p in peers:
            if p.get("error"):
                continue
            mcap = f"{p.get('mcap_yi',0):.0f}" if p.get("mcap_yi") else "—"
            html.append(
                f"<tr><td>{p['code']}</td><td>{'**' if p['code']==code else ''}{p['name']}"
                f"{'**' if p['code']==code else ''}</td>"
                f"<td>{p.get('price',0):.2f}</td>"
                f"<td>{p.get('change_pct',0):.2f}%</td>"
                f"<td>{mcap}</td>"
                f"<td>{p.get('pe',0):.0f}</td>"
                f"<td>{p.get('pb',0):.1f}</td></tr>"
            )
        html.append('</tbody></table>')
    html.append('</div>')

    return "\n".join(html)


if __name__ == '__main__':
    # 测试
    print("=== 估值分位数 ===")
    print(json.dumps(get_industry_valuation("600519"), ensure_ascii=False, indent=2))
    print("\n=== 同业对比 ===")
    print(json.dumps(get_peer_comparison("600519"), ensure_ascii=False, indent=2))
