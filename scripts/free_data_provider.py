# -*- coding: utf-8 -*-
"""
free_data_provider.py — A股全栈免费数据提供层
基于 a-stock-data V3.2.1 的 7 层架构，为 listed-company-analysis 提供核心数据。

数据源优先级（按封IP风险）：
    1. 腾讯财经  — 行情/PE/PB/市值/换手率 (HTTP, 不封IP)
    2. 新浪财经  — 财报三表 (HTTP)
    3. 巨潮      — 公告全文 (HTTP)
    4. 东财      — 个股信息/行业排名 (HTTP, 内置限流)

所有端点全部免费，零 API Key，纯标准库（urllib）。
"""
import json
import re
import time
import random
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ═══════════════════════════════════════════════════════════
# 东财防封：统一节流入口
# ═══════════════════════════════════════════════════════════

EM_MIN_INTERVAL = 1.0      # 两次东财请求最小间隔(秒)
_last_em_call = [0.0]       # 模块级上次请求时间戳

def em_get(url: str, params: dict = None, headers: dict = None,
           timeout: int = 15) -> dict:
    """东财统一请求入口：自动节流 + 默认 UA + JSON 解析。"""
    wait = EM_MIN_INTERVAL - (time.time() - _last_em_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        h = {"User-Agent": UA}
        if headers: h.update(headers)
        qs = ""
        if params:
            qs = "?" + "&".join(f"{k}={urllib.request.quote(str(v))}"
                                for k, v in params.items())
        req = urllib.request.Request(url + qs, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    finally:
        _last_em_call[0] = time.time()


# ═══════════════════════════════════════════════════════════
# 1. 腾讯财经 — 实时行情（不封IP，首选）
# ═══════════════════════════════════════════════════════════

def tencent_quote(codes: List[str]) -> Dict[str, Dict]:
    """
    批量拉取腾讯财经实时行情（不封IP）。
    返回 PE_TTM / PB / 市值 / 换手率 / 涨跌停价 等 20 字段。
    """
    prefixed = []
    for c in codes:
        c = c.strip()
        if c.startswith(("6", "9")):   prefixed.append(f"sh{c}")
        elif c.startswith("8"):         prefixed.append(f"bj{c}")
        else:                           prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3])  if vals[3]  else 0,
            "last_close":   float(vals[4])  if vals[4]  else 0,
            "open":         float(vals[5])  if vals[5]  else 0,
            "change_amt":   float(vals[31]) if vals[31] else 0,
            "change_pct":   float(vals[32]) if vals[32] else 0,
            "high":         float(vals[33]) if vals[33] else 0,
            "low":          float(vals[34]) if vals[34] else 0,
            "amount_wan":   float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm":       float(vals[39]) if vals[39] else 0,
            "amplitude_pct":float(vals[43]) if vals[43] else 0,
            "mcap_yi":      float(vals[44]) if vals[44] else 0,
            "float_mcap_yi":float(vals[45]) if vals[45] else 0,
            "pb":           float(vals[46]) if vals[46] else 0,
            "limit_up":     float(vals[47]) if vals[47] else 0,
            "limit_down":   float(vals[48]) if vals[48] else 0,
            "vol_ratio":    float(vals[49]) if vals[49] else 0,
            "pe_static":    float(vals[52]) if vals[52] else 0,
        }
    return result


# ═══════════════════════════════════════════════════════════
# 2. 新浪财报三表（资产负债表/利润表/现金流量表）
# ═══════════════════════════════════════════════════════════

def sina_financial_report(code: str, report_type: str = "lrb",
                           num: int = 8) -> List[Dict]:
    """
    新浪财报三表。
    report_type: "lrb"(利润表) / "fzb"(资产负债表) / "llb"(现金流量表)
    返回: [{报告期, <科目>, <科目>_同比}, ...]
    """
    prefix = "sh" if code.startswith("6") else "sz"
    paper_code = f"{prefix}{code}"
    url = ("https://quotes.sina.cn/cn/api/openapi.php/"
           "CompanyFinanceService.getFinanceReport2022")
    params = {"paperCode": paper_code, "source": report_type,
              "type": "0", "page": "1", "num": str(num)}
    headers = {"User-Agent": UA}
    qs = "?" + "&".join(f"{k}={urllib.request.quote(str(v))}"
                        for k, v in params.items())
    req = urllib.request.Request(url + qs, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        js = json.loads(resp.read().decode("utf-8"))

    report_list = ((((js or {}).get("result") or {})
                     .get("data") or {}).get("report_list") or {})
    rows = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        obj = report_list[period]
        rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for it in obj.get("data", []) or []:
            title = it.get("item_title", "")
            if not title or it.get("item_value") is None:
                continue
            rec[title] = it["item_value"]
            tongbi = it.get("item_tongbi")
            if tongbi not in (None, ""):
                rec[title + "_同比"] = tongbi
        rows.append(rec)
    return rows


# ═══════════════════════════════════════════════════════════
# 3. 东财个股基本信息（push2）
# ═══════════════════════════════════════════════════════════

def eastmoney_stock_info(code: str) -> Dict[str, Any]:
    """东财个股基本面（已内置限流）"""
    market_code = 1 if code.startswith("6") else 0
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "fltt": "2", "invt": "2",
        "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43,f20",
        "secid": f"{market_code}.{code}",
    }
    headers = {"User-Agent": UA}
    r = em_get(url, params=params, headers=headers, timeout=10)
    d = (r or {}).get("data", {}) or {}
    return {
        "code":          d.get("f57", code),
        "name":          d.get("f58", ""),
        "industry":      d.get("f127", ""),
        "total_shares":  d.get("f84", 0),
        "float_shares":  d.get("f85", 0),
        "mcap":          d.get("f116", 0),
        "float_mcap":    d.get("f117", 0),
        "list_date":     str(d.get("f189", "")),
        "price":         (d.get("f43", 0) or 0) / 100 if isinstance(d.get("f43"), int) else d.get("f43", 0),
    }


# ═══════════════════════════════════════════════════════════
# 4. 行业板块排名
# ═══════════════════════════════════════════════════════════

def industry_ranking(top_n: int = 50) -> List[Dict]:
    """东财行业板块涨跌幅排名（已内置限流）"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": str(top_n), "po": "1", "np": "1",
        "fltt": "2", "invt": "2",
        "fs": "m:90+t:2",
        "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141",
    }
    r = em_get(url, params=params, timeout=15)
    items = (r or {}).get("data", {}).get("diff", []) or []
    rows = []
    for i, item in enumerate(items):
        rows.append({
            "rank": i + 1,
            "name": item.get("f14", ""),
            "change_pct": item.get("f3", 0),
            "code": item.get("f12", ""),
        })
    return rows


# ═══════════════════════════════════════════════════════════
# 5. 巨潮公告
# ═══════════════════════════════════════════════════════════

def cninfo_announcements(code: str, page_size: int = 30) -> List[Dict]:
    """巨潮公告全文检索（免费，无 Key）"""
    if code.startswith("6"):
        org_id = f"gssh0{code}"
    elif code.startswith("8") or code.startswith("4"):
        org_id = f"gsbj0{code}"
    else:
        org_id = f"gssz0{code}"

    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    payload = (
        f"stock={code},{org_id}&tabName=fulltext&pageSize={page_size}"
        f"&pageNum=1&column=&category=&plate=&seDate=&searchkey="
        f"&secid=&sortName=&sortType=&isHLtitle=true"
    )
    req = urllib.request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        d = json.loads(resp.read().decode("utf-8"))

    import datetime as _dt
    rows = []
    for item in d.get("announcements", []) or []:
        ts = item.get("announcementTime")
        # 巨潮返回 Unix 毫秒整数
        if isinstance(ts, (int, float)):
            date_str = _dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        else:
            date_str = str(ts)[:10] if ts else ""
        rows.append({
            "title": item.get("announcementTitle", ""),
            "category": item.get("announcementTypeName", ""),
            "date": date_str,
        })
    return rows


# ═══════════════════════════════════════════════════════════
# 6. 统一查询入口（兼容 iwencai_provider 接口）
# ═══════════════════════════════════════════════════════════

def _extract_code(query: str) -> str:
    """从查询文本提取6位股票代码"""
    m = re.search(r'\b(\d{6})\b', query)
    return m.group(1) if m else ""


def free_query(skill_id: str, query: str, limit: int = 10) -> Dict[str, Any]:
    """
    统一查询入口：根据 skill_id 路由到对应的免费数据源。
    返回格式与 iwencai_provider.query_iwencai() 兼容。
    """
    code = _extract_code(query)

    # ── 行情 ──
    if skill_id == 'hithink-market-query':
        if not code:
            return {"success": False, "datas": [], "error": "无法提取股票代码"}
        try:
            q = tencent_quote([code])
            if code in q:
                d = q[code]
                return {"success": True, "datas": [{
                    "股票代码": code,
                    "股票名称": d["name"],
                    "最新价":   d["price"],
                    "涨跌幅":   d["change_pct"],
                    "开盘价":   d["open"],
                    "最高价":   d["high"],
                    "最低价":   d["low"],
                    "昨收":     d["last_close"],
                    "成交量(万)": d["amount_wan"],
                    "换手率":   d["turnover_pct"],
                    "PE_TTM":  d["pe_ttm"],
                    "PB":      d["pb"],
                    "总市值(亿)": d["mcap_yi"],
                    "流通市值(亿)": d["float_mcap_yi"],
                    "涨停价":   d["limit_up"],
                    "跌停价":   d["limit_down"],
                    "PE_静态":  d["pe_static"],
                }], "code_count": 1}
            return {"success": True, "datas": [], "code_count": 0}
        except Exception as e:
            return {"success": False, "datas": [], "error": f"腾讯行情查询失败: {e}"}

    # ── 基本信息 ──
    if skill_id == 'hithink-basicinfo-query':
        if not code:
            return {"success": False, "datas": [], "error": "无法提取股票代码"}
        try:
            info = eastmoney_stock_info(code)
            return {"success": True, "datas": [{
                "股票代码": info["code"],
                "股票名称": info["name"],
                "所属行业": info["industry"],
                "总股本":   info["total_shares"],
                "流通股":   info["float_shares"],
                "总市值":   info["mcap"],
                "上市日期": info["list_date"],
            }], "code_count": 1}
        except Exception as e:
            return {"success": False, "datas": [], "error": f"东财基本信息查询失败: {e}"}

    # ── 事件/公告 ──
    if skill_id == 'hithink-event-query':
        if not code:
            return {"success": False, "datas": [], "error": "无法提取股票代码"}
        try:
            anns = cninfo_announcements(code, page_size=min(limit, 50))
            datas = [{
                "公告标题": a["title"],
                "公告日期": a["date"],
                "公告类型": a["category"],
            } for a in anns[:limit]]
            return {"success": True, "datas": datas, "code_count": len(anns)}
        except Exception as e:
            return {"success": False, "datas": [], "error": f"巨潮公告查询失败: {e}"}

    # ── 行业 ──
    if skill_id == 'hithink-industry-query':
        try:
            industries = industry_ranking(top_n=min(limit, 50))
            return {"success": True, "datas": industries, "code_count": len(industries)}
        except Exception as e:
            return {"success": False, "datas": [], "error": f"行业排名查询失败: {e}"}

    # ── 宏观（降级到新浪财报） ──
    if skill_id == 'hithink-macro-query':
        return {"success": False, "datas": [], "error": "A股全栈数据暂不支持宏观数据查询"}

    return {"success": False, "datas": [], "error": f"未知 skill_id: {skill_id}"}


# ═══════════════════════════════════════════════════════════
# CLI 测试
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("用法: python free_data_provider.py <skill_id> <query> [limit]")
        print("skill_id: hithink-market-query / basicinfo-query / event-query / industry-query")
        sys.exit(1)

    skill_id = sys.argv[1]
    query = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    print(f"[{skill_id}] 查询: {query}  |  来源: A股全栈免费数据")
    print("-" * 60)

    result = free_query(skill_id, query, limit)

    if result['success']:
        print(f"✅ 成功 | 返回 {len(result['datas'])} 条 / 共 {result['code_count']} 条")
        print("-" * 60)
        for i, item in enumerate(result['datas'][:5], 1):
            print(f"  {i}. {item}")
        if len(result['datas']) > 5:
            print(f"  ... 共 {len(result['datas'])} 条")
    else:
        print(f"❌ 失败: {result['error']}")
    print("-" * 60)
