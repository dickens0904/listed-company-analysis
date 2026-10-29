# -*- coding: utf-8 -*-
"""
机构持仓与市场筹码分析模块
数据源: 东方财富 RPT_F10_EQUITY_HOLDER / RPT_F10_HK_SHARESTANDARDINFO
功能: 机构持仓、股东户数变化趋势、筹码集中度、北向资金
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


def fetch_institutional(stock_code, market="a", data_dir=None):
    """主函数"""
    result = {
        "stock_code": stock_code,
        "institutional_holdings": [],
        "holder_count_trend": [],
        "northbound": {},
        "market_structure": {},
        "risks": [],
        "warnings": [],
    }

    secucode = _secucode(stock_code)
    result["institutional_holdings"] = _fetch_institutional(secucode)
    result["holder_count_trend"] = _fetch_holder_count(secucode)
    if market == "a":
        result["northbound"] = _fetch_northbound(secucode)
    result["market_structure"] = _analyze_market_structure(result)
    result["risks"] = _summarize_risks(result)

    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "institutional.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


def _fetch_institutional(secucode):
    """获取机构持仓"""
    params = {
        "reportName": "RPT_F10_EQUITY_HOLDER",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 20,
        "sortTypes": -1, "sortColumns": "END_DATE",
        "source": "WEB", "client": "WEB",
    }
    raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
    data = safe_extract(raw, ["result", "data"], default=[]) or []

    all_records = []
    for item in data[:20]:
        name = item.get("HOLDER_NAME", "")
        ratio = safe_float(item.get("HOLD_RATIO"))
        if not name or not ratio or ratio < 0.0001:
            continue
        ratio_pct = round(ratio * 100, 3) if ratio < 1 else round(ratio, 3)
        all_records.append({
            "name": name,
            "type": item.get("HOLDER_TYPE", ""),
            "ratio_pct": ratio_pct,
            "shares": safe_float(item.get("HOLDNUMBER")),
            "date": item.get("END_DATE", "")[:10],
            "change_ratio": item.get("CHANGE_RATIO"),
        })

    # 按名称去重（取最新一期）
    latest = {}
    for r in all_records:
        if r["name"] not in latest or (r["date"] > latest[r["name"]]["date"]):
            latest[r["name"]] = r
    return list(latest.values())[:30]


def _fetch_holder_count(secucode):
    """获取股东户数趋势"""
    params = {
        "reportName": "RPT_F10_EQUITY_SHAREHOLDERSTATISTIC",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": 1, "pageSize": 20,
        "sortTypes": -1, "sortColumns": "END_DATE",
        "source": "WEB", "client": "WEB",
    }
    raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
    data = safe_extract(raw, ["result", "data"], default=[]) or []
    if not data:
        # fallback: 从EQUITY_HOLDER聚合
        params2 = {
            "reportName": "RPT_F10_EQUITY_HOLDER",
            "columns": "ALL",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": 1, "pageSize": 50,
            "sortTypes": -1, "sortColumns": "END_DATE",
            "source": "WEB", "client": "WEB",
        }
        raw2 = safe_get(EM_API, params=params2, headers=HEADERS, timeout=15)
        data2 = safe_extract(raw2, ["result", "data"], default=[]) or []
        # 按END_DATE聚合
        by_date = {}
        for item in data2:
            d = item.get("END_DATE", "")[:10]
            if d:
                by_date.setdefault(d, 0)
                # 无法直接获取股东户数，返回空
        return []

    records = []
    for item in data[:16]:
        hn = safe_float(item.get("HOLDER_NUM")) or safe_float(item.get("HOLDER_NUMBER"))
        avg = safe_float(item.get("AVG_HOLD_SHARE"))
        if hn:
            records.append({"date": item.get("END_DATE", "")[:10], "holder_count": int(hn), "avg_hold": round(avg, 0) if avg else None})
    return records


def _fetch_northbound(secucode):
    """北向资金"""
    plain = secucode.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
    params = {
        "reportName": "RPT_F10_HK_SHARESTANDARDINFO",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{plain}")',
        "pageNumber": 1, "pageSize": 10,
        "sortTypes": -1, "sortColumns": "HOLD_DATE",
        "source": "WEB", "client": "WEB",
    }
    raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
    data = safe_extract(raw, ["result", "data"], default=[]) or []
    if not data:
        return {"latest": None, "trend": [], "signal": "暂无北向数据(可能非沪/深股通标的)"}

    latest = data[0] if data else {}
    latest_record = {
        "date": latest.get("HOLD_DATE", "")[:10],
        "shares": safe_float(latest.get("HOLD_SHARES")),
        "market_cap": safe_float(latest.get("HOLD_MARKET_CAP")),
        "ratio_float": safe_float(latest.get("HOLD_RATIO")),
    }

    trend = []
    for item in data[:6]:
        trend.append({
            "date": item.get("HOLD_DATE", "")[:10],
            "shares": safe_float(item.get("HOLD_SHARES")),
            "ratio": safe_float(item.get("HOLD_RATIO")),
        })

    signal = "数据不足"
    if len(trend) >= 2:
        cur = safe_float(trend[0].get("shares")) or 0
        prev = safe_float(trend[1].get("shares")) or 0
        if prev > 0:
            chg = (cur - prev) / prev * 100
            if chg > 10:
                signal = f"🟢北向增持(+{chg:.1f}%)"
            elif chg < -10:
                signal = f"🔴北向减持({chg:.1f}%)"
            else:
                signal = f"🟡北向持股稳定({chg:+.1f}%)"

    return {"latest": latest_record, "trend": trend, "signal": signal}


def _analyze_market_structure(result):
    hc = result.get("holder_count_trend", [])
    if len(hc) < 2:
        return {"chip_trend": "数据不足"}
    latest = hc[0]["holder_count"]
    oldest = hc[-1]["holder_count"]
    chg_pct = round((latest - oldest) / oldest * 100, 1) if oldest else 0

    if chg_pct < -10:
        chip_trend = f"🟢筹码趋于集中（股东户数减少{chg_pct:.1f}%）"
    elif chg_pct > 10:
        chip_trend = f"🔴筹码趋于分散（股东户数增加{chg_pct:.1f}%）"
    else:
        chip_trend = f"🟡筹码基本稳定（变化{chg_pct:+.1f}%）"

    return {"chip_trend": chip_trend, "holder_count_latest": latest, "holder_count_oldest": oldest}


def _summarize_risks(result):
    risks = []
    ms = result.get("market_structure", {})
    if "分散" in ms.get("chip_trend", ""):
        risks.append({"level": "medium", "dim": "筹码", "signal": "股东户数增加，筹码分散"})
    nb = result.get("northbound", {})
    if nb.get("signal", "").startswith("🔴"):
        risks.append({"level": "medium", "dim": "北向", "signal": nb["signal"]})
    return risks


def format_markdown(data):
    if not data:
        return "## 机构持仓与市场筹码\n\n_暂无数据_"

    inst = data.get("institutional_holdings", [])
    hc = data.get("holder_count_trend", [])
    nb = data.get("northbound", {})
    ms = data.get("market_structure", {})
    risks = data.get("risks", [])

    lines = ["## 机构持仓与市场筹码\n"]

    # 北向资金
    if nb.get("latest"):
        nl = nb["latest"]
        lines.append("### 北向资金（沪/深股通）\n")
        lines.append(f"- 信号: **{nb.get('signal', '数据不足')}**")
        if nl.get("date"):
            lines.append(f"- 截止日期: {nl['date']}")
        if nl.get("shares"):
            lines.append(f"- 持股数量: {nl['shares']:,.0f}股")
        if nl.get("ratio_float"):
            lines.append(f"- 占流通股: {nl['ratio_float']*100:.2f}%")
        trend = nb.get("trend", [])
        if trend:
            lines.append("\n| 日期 | 持股数量 | 占比 |")
            lines.append("|------|---------|------|")
            for t in trend[:6]:
                sh = f"{t['shares']:,.0f}" if t.get("shares") else "N/A"
                rt = f"{t['ratio']*100:.2f}%" if t.get("ratio") else "N/A"
                lines.append(f"| {t.get('date', '?')} | {sh} | {rt} |")
        lines.append("")

    # 股东户数
    if hc:
        lines.append("### 股东户数趋势（筹码集中度）\n")
        lines.append(f"- 当前: **{hc[0]['holder_count']:,}户**（{hc[0]['date']}）")
        lines.append(f"- 判断: {ms.get('chip_trend', '数据不足')}")
        lines.append("\n| 报告期 | 股东户数 | 户均持股 |")
        lines.append("|--------|---------|---------|")
        for h in hc[:8]:
            avg = f"{h['avg_hold']:,.0f}股" if h.get("avg_hold") else "N/A"
            lines.append(f"| {h['date'][:10]} | {h['holder_count']:,} | {avg} |")
        lines.append("")

    # 机构持仓
    if inst:
        lines.append(f"### 机构持仓明细（共{len(inst)}条记录）\n")
        lines.append("| 机构名称 | 类型 | 持股比例 | 日期 |")
        lines.append("|----------|------|---------|------|")
        for i in inst[:15]:
            lines.append(f"| {i.get('name', '?')[:20]} | {i.get('type', '?')} | {i.get('ratio_pct', '?')} | {i.get('date', '?')} |")
        lines.append("")

    if risks:
        lines.append("### 市场结构风险信号\n")
        for r in risks:
            icon = "🔴" if r["level"] == "high" else "🟡"
            lines.append(f"- {icon} [{r['dim']}] {r['signal']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    data = fetch_institutional(stock, data_dir="output/test")
    print(format_markdown(data))


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = format_markdown(data)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 机构持仓分析\n\n", md]
