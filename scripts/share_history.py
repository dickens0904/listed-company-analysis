# -*- coding: utf-8 -*-
"""
股本变动与融资历史模块
数据源: 东方财富 RPT_F10_EQUITY_CHANGE / RPT_F10_DIVIDEND_A / RPT_F10_IPO_INFO
功能: 股本变动历史、分红历史(近10年)、限售股解禁、融资历史
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")
from scripts.safe_request import safe_get, safe_extract, safe_float

EM_API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json",
}


def _secucode(stock_code):
    if stock_code.endswith((".SH", ".SZ", ".BJ")):
        return stock_code
    if stock_code[:2] in ["00", "30"]:
        return f"{stock_code}.SZ"
    if stock_code[:2] in ["60", "68"]:
        return f"{stock_code}.SH"
    if stock_code[0] in ["8", "4"]:
        return f"{stock_code}.BJ"
    return f"{stock_code}.SZ"


def fetch_share_history(stock_code, market="a", data_dir=None):
    """主函数"""
    result = {
        "stock_code": stock_code,
        "market": market,
        "equity_changes": [],
        "dividend_history": [],
        "dividend_stats": {},
        "unlock_schedule": [],
        "financing_history": {},
        "warnings": [],
    }

    # 港股：使用yfinance获取股本数据
    if market == "hk":
        try:
            import yfinance as yf
            ticker = yf.Ticker(stock_code)
            # 获取分红历史
            div = ticker.dividends
            if div is not None and not div.empty:
                result["dividend_history"] = div.tail(10).to_dict("records")
            # 获取股票拆分历史
            splits = ticker.splits
            if splits is not None and not splits.empty:
                result["equity_changes"] = splits.to_dict("records")
        except Exception as e:
            result["warnings"].append(f"{market}市场数据获取异常: {str(e)[:30]}")
        return result
    
    # 美股：使用SEC数据
    if market == "us":
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from us_history import fetch_sec_history
            
            sec_data = fetch_sec_history(stock_code)
            if 'error' not in sec_data:
                result["company_info"] = sec_data.get("company", {})
                result["filings_count"] = sec_data.get("filings_count", {})
                result["dividend_history"] = []  # SEC不提供实时分红
                result["equity_changes"] = []  # 可从SEC获取但较复杂
                result["warnings"].append("使用SEC股本数据")
            else:
                result["warnings"].append(sec_data.get("error", "获取失败"))
        except Exception as e:
            result["warnings"].append(f"美股数据获取异常: {str(e)[:30]}")
        return result

    # A股：使用东方财富API
    secucode = _secucode(stock_code)
    result["equity_changes"] = _fetch_equity_changes(secucode)
    result["dividend_history"] = _fetch_dividends(secucode)
    result["dividend_stats"] = _analyze_dividends(result["dividend_history"])
    result["unlock_schedule"] = _fetch_unlock_schedule(secucode)
    result["financing_history"] = _fetch_financing_history(secucode)

    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "share_history.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


def _fetch_equity_changes(secucode):
    params = {
        "reportName": "RPT_F10_EQUITY_CHANGE",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 30,
        "sortTypes": -1, "sortColumns": "CHANGEDATE",
        "source": "WEB", "client": "WEB",
    }
    raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
    data = safe_extract(raw, ["result", "data"], default=[]) or []
    records = []
    for item in data[:20]:
        tb = safe_float(item.get("TOTAL_SHARES"))
        ta = safe_float(item.get("TOTAL_SHARES_AFTER"))
        chg = (ta - tb) if (tb and ta) else None
        records.append({
            "date": item.get("CHANGEDATE", "")[:10],
            "reason": item.get("CHANGERESON", item.get("CHANGE_TYPE", "")),
            "total_before_万股": round(tb / 10000, 2) if tb else None,
            "total_after_万股": round(ta / 10000, 2) if ta else None,
            "change_万股": round(chg / 10000, 2) if chg else None,
        })
    return records


def _fetch_dividends(secucode):
    params = {
        "reportName": "RPT_F10_DIVIDEND_A",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 20,
        "sortTypes": -1, "sortColumns": "EXDIVIDENDDATE",
        "source": "WEB", "client": "WEB",
    }
    raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
    data = safe_extract(raw, ["result", "data"], default=[]) or []
    records = []
    for item in data[:15]:
        records.append({
            "fiscal_year": item.get("PLAN_YEAR", item.get("YEAR", "")),
            "ex_date": (item.get("A_EXRIGHTDATE") or item.get("EXDIVIDENDDATE", ""))[:10],
            "cash_per_share": safe_float(item.get("CASH_DIVIDEND_TAX_A")),
            "bonus_ratio": safe_float(item.get("BONUS_SHARE_RATIO_A")),
            "convert_ratio": safe_float(item.get("CONVERT_SHARE_RATIO_A")),
            "total_plan": item.get("DIVIDEND_PLAN", ""),
        })
    return records


def _analyze_dividends(dividends):
    if not dividends:
        return {"record_count": 0}
    cash_vals = [d["cash_per_share"] for d in dividends if d.get("cash_per_share")]
    return {
        "record_count": len(dividends),
        "recent_cash_per_share": cash_vals[:5],
        "years_covered": [d["fiscal_year"] for d in dividends if d.get("fiscal_year")],
        "note": "分红率/股息率需结合净利润和股价计算",
    }


def _fetch_unlock_schedule(secucode):
    params = {
        "reportName": "RPT_F10_SHARELIMIT_UNLOCK",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 20,
        "sortTypes": 1, "sortColumns": "UNLOCK_DATE",
        "source": "WEB", "client": "WEB",
    }
    raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
    data = safe_extract(raw, ["result", "data"], default=[]) or []
    records = []
    for item in data[:10]:
        r = safe_float(item.get("UNLOCK_RATIO"))
        records.append({
            "unlock_date": item.get("UNLOCK_DATE", "")[:10],
            "share_type": item.get("SHARE_TYPE", "未知"),
            "unlock_shares_万股": safe_float(item.get("UNLOCK_SHARES")),
            "ratio_pct": round(r * 100, 2) if r else None,
        })
    return records


def _fetch_financing_history(secucode):
    # IPO
    params_ipo = {
        "reportName": "RPT_F10_IPO_INFO",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 5,
        "source": "WEB", "client": "WEB",
    }
    raw_ipo = safe_get(EM_API, params=params_ipo, headers=HEADERS, timeout=15)
    ipo_data = safe_extract(raw_ipo, ["result", "data"], default=[]) or []
    ipo = {}
    if ipo_data:
        ipo = {
            "listing_date": ipo_data[0].get("LISTING_DATE", "")[:10],
            "issue_price": safe_float(ipo_data[0].get("ISSUE_PRICE")),
            "issue_pe": safe_float(ipo_data[0].get("ISSUE_PE")),
            "funds_raised_亿": round(safe_float(ipo_data[0].get("FUNDS_RAISED"), 0) / 1e8, 2),
        }

    # 定增
    params_dz = {
        "reportName": "RPT_F10_ADDITIONAL_ISSUES",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 10,
        "sortTypes": -1, "sortColumns": "ISSUE_DATE",
        "source": "WEB", "client": "WEB",
    }
    raw_dz = safe_get(EM_API, params=params_dz, headers=HEADERS, timeout=15)
    dz_data = safe_extract(raw_dz, ["result", "data"], default=[]) or []
    additional = []
    for item in dz_data[:10]:
        additional.append({
            "issue_date": item.get("ISSUE_DATE", "")[:10],
            "issue_price": safe_float(item.get("ISSUE_PRICE")),
            "shares_万股": safe_float(item.get("SHARES")),
            "funds_亿": round(safe_float(item.get("FUNDS_RAISED"), 0) / 1e8, 2) if safe_float(item.get("FUNDS_RAISED")) else None,
            "purpose": item.get("PURPOSE", ""),
        })

    return {"ipo": ipo, "additional_issues": additional}


def format_markdown(data):
    if not data:
        return "## 股本变动与融资历史\n\n_暂无数据_"

    eq = data.get("equity_changes", [])
    divs = data.get("dividend_history", [])
    ds = data.get("dividend_stats", {})
    unlocks = data.get("unlock_schedule", [])
    fin = data.get("financing_history", {})

    lines = ["## 股本变动与融资历史\n"]

    ipo = fin.get("ipo", {})
    if ipo and ipo.get("listing_date"):
        lines.append("### IPO信息\n")
        lines.append(f"- 上市日期: {ipo.get('listing_date', '?')}")
        if ipo.get("issue_price"):
            lines.append(f"- 发行价: {ipo['issue_price']:.2f}元")
        if ipo.get("funds_raised_亿"):
            lines.append(f"- 募资金额: {ipo['funds_raised_亿']:.2f}亿元")
        lines.append("")

    if divs:
        lines.append("### 分红历史\n")
        rc = ds.get("recent_cash_per_share", [])
        if rc:
            lines.append(f"- 每股现金分红(近5期): {' → '.join([f'{v:.3f}元' for v in rc[:5]])}")
        lines.append("\n| 报告期 | 除权日 | 每股派息(含税) | 送股 | 转增 |")
        lines.append("|--------|-------|--------------|------|------|")
        for d in divs[:10]:
            cps = f"{d['cash_per_share']:.3f}元" if d.get("cash_per_share") else "N/A"
            bonus = f"10送{d['bonus_ratio']:.1f}" if d.get("bonus_ratio") else "-"
            convert = f"10转{d['convert_ratio']:.1f}" if d.get("convert_ratio") else "-"
            lines.append(f"| {d.get('fiscal_year', '?')} | {d.get('ex_date', '?')} | {cps} | {bonus} | {convert} |")
        lines.append("")

    sz = fin.get("additional_issues", [])
    if sz:
        lines.append("### 定增记录\n")
        lines.append("| 日期 | 发行价 | 募资(亿元) | 目的 |")
        lines.append("|------|-------|-----------|------|")
        for s in sz:
            funds = f"{s['funds_亿']:.2f}" if s.get("funds_亿") else "N/A"
            lines.append(f"| {s.get('issue_date', '?')} | {s.get('issue_price', '?')}元 | {funds} | {s.get('purpose', '?')[:20]} |")
        lines.append("")

    if eq:
        lines.append("### 股本变动\n")
        lines.append("| 日期 | 变动原因 | 变动前(万股) | 变动后(万股) | 变动量 |")
        lines.append("|------|---------|------------|------------|--------|")
        for c in eq[:10]:
            lines.append(f"| {c.get('date', '?')} | {c.get('reason', '?')[:20]} | {c.get('total_before_万股', '?')} | {c.get('total_after_万股', '?')} | {c.get('change_万股', '?')} |")
        lines.append("")

    if unlocks:
        lines.append("### 限售股解禁时间表\n")
        lines.append("| 解禁日期 | 股份类型 | 解禁比例 |")
        lines.append("|---------|---------|---------|")
        for u in unlocks[:8]:
            ratio = f"{u.get('ratio_pct', 'N/A')}%" if u.get("ratio_pct") else "N/A"
            lines.append(f"| {u.get('unlock_date', '?')} | {u.get('share_type', '?')} | {ratio} |")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    data = fetch_share_history(stock, data_dir="output/test")
    print(format_markdown(data))


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = format_markdown(data)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 股本融资历史\n\n", md]
