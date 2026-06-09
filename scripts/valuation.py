# -*- coding: utf-8 -*-
"""
估值分析模块
数据源: 东方财富行情API + RPT_LICO_FN_CPD（历史EPS）
功能: 当前估值(PE/PB/PS/EV)、历史分位数、DCF框架、敏感性分析、估值结论
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")
from scripts.safe_request import safe_get, safe_extract, safe_float

EM_API = "http://datacenter-web.eastmoney.com/api/data/v1/get"
EM_QUOTE = "http://push2.eastmoney.com/api/qt/stock/get"
EM_VALUATION = "http://datacenter-web.eastmoney.com/api/data/v1/get"  # RPT_VALUEANALYSIS_DET
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "http://data.eastmoney.com/",
    "Accept": "application/json",
}
QUOTE_FIELDS = "f43,f44,f45,f46,f47,f48,f50,f57,f58,f116,f117,f162,f167,f168,f169,f170,f171,f292"


def _fetch_valuation_data(secucode):
    """从datacenter获取最新估值数据（PE/PB/PS）— 主数据源"""
    # 已验证可用列: SECUCODE, TRADE_DATE, SECURITY_NAME_ABBR, CLOSE_PRICE, PE_TTM, PB_MRQ, PS_TTM
    # 注意: PE_DYNAMIC, CIRCULATING_MARKET_CAP 等列不存在
    params = {
        "reportName": "RPT_VALUEANALYSIS_DET",
        "columns": "SECUCODE,TRADE_DATE,SECURITY_NAME_ABBR,CLOSE_PRICE,PE_TTM,PB_MRQ,PS_TTM",
        "filter": f'(SECUCODE="{secucode}")',
        "pageSize": 1,
        "sortColumns": "TRADE_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    raw = safe_get(EM_VALUATION, params=params, headers=HEADERS, timeout=20)
    records = safe_extract(raw, ["result", "data"], default=[])
    if records and len(records) > 0:
        return records[0]
    return None


def _market_id(stock_code):
    if stock_code[:2] in ["00", "30"]:
        return "0"
    if stock_code[:2] in ["60", "68"]:
        return "1"
    return "1"


def _secucode(stock_code):
    if stock_code.endswith((".SH", ".SZ", ".BJ")):
        return stock_code
    if stock_code[:2] in ["00", "30"]:
        return f"{stock_code}.SZ"
    if stock_code[:2] in ["60", "68"]:
        return f"{stock_code}.SH"
    if stock_code[0] in ["8", "4"]:
        return f"{stock_code}.BJ"
    return f"{stock_code}.SH"


def _percentile(val, all_vals):
    if not all_vals or val is None:
        return None
    rank = sum(1 for v in all_vals if v <= val)
    return round(rank / len(all_vals) * 100, 1)


def _detect_market(stock_code, market="a"):
    """检测市场类型：返回 'a'(A股) / 'hk'(港股) / 'us'(美股)"""
    if market in ("hk", "us"):
        return market
    # 美股：纯字母代码
    if stock_code.upper() == stock_code and stock_code.isalpha():
        return "us"
    # 港股：5位数字，以0开头（如00700）
    if market == "hk" or (stock_code.isdigit() and len(stock_code) == 5 and stock_code.startswith("0")):
        return "hk"
    # 默认为A股
    return "a"


def fetch_valuation(stock_code, market="a", data_dir=None, records=None, financial_data=None):
    """主函数：估值分析"""
    # 先检测正确市场
    actual_market = _detect_market(stock_code, market)
    
    result = {
        "stock_code": stock_code, "market": actual_market,
        "current": {}, "historical_pe": [], "percentile": {},
        "dcf": {}, "sensitivity": [], "relative": {}, "conclusion": {},
        "warnings": [],
    }

    # 港股：使用yfinance获取估值
    if actual_market == "hk":
        import time
        time.sleep(1)  # 避免限流
        try:
            import yfinance as yf
            ticker = yf.Ticker(stock_code)
            info = ticker.info
            if info:
                result["current"] = {
                    "market_cap": info.get("marketCap"),
                    "forwardPE": info.get("forwardPE"),
                    "trailingPE": info.get("trailingPE"),
                    "priceToBook": info.get("priceToBook"),
                    "enterpriseValue": info.get("enterpriseValue"),
                    "beta": info.get("beta"),
                }
                # 获取历史价格
                hist = ticker.history(period="2y")
                if hist is not None and not hist.empty:
                    prices = hist["Close"].values
                    if len(prices) > 0:
                        result["historical_pe"] = [float(prices.min()), float(prices.max())]
        except Exception as e:
            err = str(e)
            if "429" in err:
                result["warnings"].append("Yahoo API限流，请稍后重试")
            else:
                result["warnings"].append(f"数据获取异常: {err[:30]}")
        return result
    
    # 美股：使用SEC数据
    if actual_market == "us":
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from us_history import fetch_sec_history, fetch_market_cap
            
            # 获取公司基本信息
            sec_data = fetch_sec_history(stock_code)
            if 'error' not in sec_data:
                company = sec_data.get("company", {})
                result["current"] = {
                    "market_cap": fetch_market_cap(stock_code).get("mktCap"),
                    "company_name": company.get("name"),
                    "category": company.get("category"),
                }
                result["warnings"].append("使用SEC估值数据")
            else:
                result["warnings"].append(sec_data.get("error", "获取失败"))
        except Exception as e:
            result["warnings"].append(f"估值获取异常: {str(e)[:30]}")
        return result

    # A股：优先使用 datacenter 估值API（RPT_VALUEANALYSIS_DET），降级行情API
    secucode = _secucode(stock_code)
    plain = stock_code.replace(".SZ", "").replace(".SH", "").replace(".BJ", "")
    mid = _market_id(plain)

    # 1. 当前估值 — 优先用 datacenter 估值API
    val_data = _fetch_valuation_data(secucode)
    if val_data:
        result["current"] = {
            "price": val_data.get("CLOSE_PRICE"),
            "company_name": val_data.get("SECURITY_NAME_ABBR", ""),
            "pe_ttm": val_data.get("PE_TTM"),
            "pb": val_data.get("PB_MRQ"),
            "ps": val_data.get("PS_TTM"),
        }
        result["valuation_source"] = "datacenter_RPT_VALUEANALYSIS_DET"
    
    # 补全市值（datacenter无市值字段，需从行情API获取）
    if not result["current"].get("market_cap_亿"):
        params_q = {"secid": f"{mid}.{plain}", "fields": "f43,f116,f117", "ut": "fa1fd612f2f5e7b0"}
        raw_q = safe_get(EM_QUOTE, params=params_q, headers=HEADERS, timeout=15)
        qdata = safe_extract(raw_q, ["data"], {})
        if qdata:
            def fval(key, divisor=1):
                v = qdata.get(key)
                if v is None or str(v) in ["-", ""]:
                    return None
                try:
                    return round(float(v) / divisor, 2)
                except (ValueError, TypeError):
                    return None
            result["current"].update({
                "price": result["current"].get("price") or fval("f43", 1000),
                "market_cap_亿": round(fval("f116", 1) / 1e8, 2) if fval("f116") else None,
                "float_market_cap_亿": round(fval("f117", 1) / 1e8, 2) if fval("f117") else None,
            })
            result["valuation_source"] = result.get("valuation_source", "") + "+quote_api"

    # 如果东财API失败，使用财报数据+股价计算估值
    if not result["current"].get("pe_ttm") and financial_data:
        fin_records = financial_data.get('records', [])
        if fin_records:
            latest = fin_records[0]
            eps = safe_float(latest.get('BASIC_EPS'))
            bps = safe_float(latest.get('BPS'))
            revenue = safe_float(latest.get('TOTAL_OPERATE_INCOME'))
            net_profit = safe_float(latest.get('PARENT_NETPROFIT'))

            price = result["current"].get("price")
            market_cap = result["current"].get("market_cap_亿")

            if eps and eps > 0 and price:
                result["current"]["pe_ttm"] = round(price / eps, 2)
                result["valuation_source"] = result.get("valuation_source", "") + "+financial_calc"

            if bps and bps > 0 and price:
                result["current"]["pb"] = round(price / bps, 2)

            if revenue and revenue > 0 and market_cap:
                rev_yi = revenue / 1e8
                result["current"]["ps"] = round(market_cap / rev_yi, 2)

            if not result["current"].get("company_name"):
                result["current"]["company_name"] = financial_data.get('summary', {}).get('company_name', '')

    # 2. 历史PE
    if records is None:
        params = {
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECUCODE,REPORTDATE,BASIC_EPS,WEIGHTAVG_ROE",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": 1, "pageSize": 20,
            "sortTypes": -1, "sortColumns": "REPORTDATE",
            "source": "WEB", "client": "WEB",
        }
        raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=20)
        records = safe_extract(raw, ["result", "data"], default=[]) or []

    price = result["current"].get("price")
    if records and price and price > 0:
        hist_pe = []
        for r in records:
            eps = safe_float(r.get("BASIC_EPS"))
            if eps and eps > 0:
                hist_pe.append({"date": r.get("REPORTDATE", "")[:10], "eps": eps, "pe": round(price / eps, 2)})
        result["historical_pe"] = hist_pe

        if hist_pe:
            pes = [p["pe"] for p in hist_pe if p["pe"] and p["pe"] > 0]
            current_pe = result["current"].get("pe_ttm") or (hist_pe[0]["pe"] if hist_pe else None)
            if current_pe and current_pe > 0 and pes:
                result["percentile"] = {
                    "pe_current": current_pe,
                    "pe_hist_3y_pct": _percentile(current_pe, pes[:min(12, len(pes))]),
                    "pe_hist_5y_pct": _percentile(current_pe, pes),
                    "pe_max_5y": max(pes), "pe_min_5y": min(pes),
                    "pe_median_5y": round(sorted(pes)[len(pes) // 2], 2),
                }

    # 3. DCF框架
    result["dcf"] = _build_dcf(records, result["current"])

    # 4. 敏感性分析
    result["sensitivity"] = _sensitivity_table(result["dcf"])

    # 5. 综合结论
    result["conclusion"] = _valuation_conclusion(result)

    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "valuation.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


def _build_dcf(records, current):
    """简化DCF框架"""
    ystz_vals = []
    if records:
        for r in records[:8]:
            v = safe_float(r.get("YSTZ"))
            if v is not None:
                ystz_vals.append(v)
    avg_growth = sum(ystz_vals) / len(ystz_vals) if ystz_vals else 5.0
    growth_rate = max(min(avg_growth, 30), -10)

    latest_rev = safe_float(records[0].get("TOTAL_OPERATE_INCOME", 0)) if records else 0
    revenue = latest_rev / 1e8 if latest_rev else 100.0

    net_margin = 10.0
    if records and safe_float(records[0].get("TOTAL_OPERATE_INCOME")):
        np0 = safe_float(records[0].get("PARENT_NETPROFIT", 0)) or 0
        rev0 = safe_float(records[0].get("TOTAL_OPERATE_INCOME", 1)) or 1
        net_margin = round(np0 / rev0 * 100, 2)

    wacc = 9.0
    terminal_g = 2.5
    fcf0 = revenue * net_margin / 100 * 0.85

    fcf_forecast = []
    for y in range(1, 6):
        fcf_y = fcf0 * ((1 + growth_rate / 100) ** y)
        pv = fcf_y / ((1 + wacc / 100) ** y)
        fcf_forecast.append({"year": y, "fcf_亿": round(fcf_y, 1), "pv_亿": round(pv, 1)})

    terminal_fcf = fcf_forecast[-1]["fcf_亿"] * (1 + terminal_g / 100) / (wacc / 100 - terminal_g / 100)
    terminal_pv = terminal_fcf / ((1 + wacc / 100) ** 5)
    equity_value = sum(f["pv_亿"] for f in fcf_forecast) + terminal_pv

    mkt_cap = current.get("market_cap_亿") or 0

    return {
        "wacc_pct": wacc, "terminal_g_pct": terminal_g,
        "revenue_base_亿": round(revenue, 1), "net_margin_pct": net_margin,
        "fcf0_亿": round(fcf0, 1), "growth_rate_pct": round(growth_rate, 1),
        "fcf_forecast": fcf_forecast,
        "terminal_value_亿": round(terminal_fcf, 1), "terminal_pv_亿": round(terminal_pv, 1),
        "dcf_value_亿": round(equity_value, 1),
        "dcf_vs_market_pct": round((equity_value / mkt_cap - 1) * 100, 1) if mkt_cap else None,
        "note": "简化DCF，仅供框架参考，实际需分析师调整假设",
    }


def _sensitivity_table(dcf):
    """敏感性分析：WACC × 永续增长率"""
    wacc_base = dcf.get("wacc_pct", 9.0)
    tg_base = dcf.get("terminal_g_pct", 2.5)
    fcf0 = dcf.get("fcf0_亿", 0)
    gr = dcf.get("growth_rate_pct", 5)
    if not fcf0:
        return []
    rows = []
    for wacc in [wacc_base - 1, wacc_base, wacc_base + 1]:
        row = {"wacc": wacc}
        for tg in [tg_base - 1, tg_base, tg_base + 1]:
            if wacc <= tg:
                row[f"tg_{tg}"] = "N/A"
            else:
                tv = fcf0 * (1 + tg / 100) / (wacc / 100 - tg / 100)
                pv5 = sum(fcf0 * ((1 + gr / 100) ** y) / ((1 + wacc / 100) ** y) for y in range(1, 6))
                total = round(tv / ((1 + wacc / 100) ** 5) + pv5, 1)
                row[f"tg_{tg}"] = total
        rows.append(row)
    return rows


def _valuation_conclusion(result):
    """综合估值结论"""
    cur = result.get("current", {})
    pct = result.get("percentile", {})
    dcf = result.get("dcf", {})
    signals = []

    pe = cur.get("pe_ttm")
    is_loss = False
    if pe is not None:
        if pe < 0:
            is_loss = True
            signals.append(("PE(TTM)", f"{pe:.1f}x", "🔴亏损"))
        elif pe < 15:
            signals.append(("PE(TTM)", f"{pe:.1f}x", "🟢低估"))
        elif pe < 30:
            signals.append(("PE(TTM)", f"{pe:.1f}x", "🟡合理"))
        else:
            signals.append(("PE(TTM)", f"{pe:.1f}x", "🔴偏高"))

    ps = cur.get("ps_ttm")
    if ps is not None and ps > 0 and is_loss:
        if ps < 2:
            signals.append(("PS(TTM)", f"{ps:.1f}x", "🟢低PS"))
        elif ps < 5:
            signals.append(("PS(TTM)", f"{ps:.1f}x", "🟡合理PS"))
        else:
            signals.append(("PS(TTM)", f"{ps:.1f}x", "🔴高PS"))

    pb = cur.get("pb") or cur.get("pb_mrq")
    if pb is not None and pb > 0 and is_loss:
        if pb < 1.5:
            signals.append(("PB", f"{pb:.1f}x", "🟢低PB"))
        elif pb < 3:
            signals.append(("PB", f"{pb:.1f}x", "🟡合理PB"))
        else:
            signals.append(("PB", f"{pb:.1f}x", "🔴高PB"))

    pct_3y = pct.get("pe_hist_3y_pct")
    if pct_3y is not None and not is_loss:
        if pct_3y < 30:
            signals.append(("历史3年分位", f"{pct_3y:.0f}%", "🟢低于30%分位"))
        elif pct_3y > 70:
            signals.append(("历史3年分位", f"{pct_3y:.0f}%", "🔴高于70%分位"))
        else:
            signals.append(("历史3年分位", f"{pct_3y:.0f}%", "🟡中间分位"))

    dcf_val = dcf.get("dcf_value_亿")
    mkt_cap = cur.get("market_cap_亿")
    if dcf_val and mkt_cap and mkt_cap > 0:
        diff = (dcf_val / mkt_cap - 1) * 100
        if diff > 20:
            signals.append(("DCF vs 市值", f"溢价{diff:.0f}%", "🟢DCF显示低估"))
        elif diff < -20:
            signals.append(("DCF vs 市值", f"折价{abs(diff):.0f}%", "🔴DCF显示高估"))
        else:
            signals.append(("DCF vs 市值", f"差异{diff:.0f}%", "🟡基本匹配"))

    bullish = sum(1 for s in signals if "🟢" in s[2])
    bearish = sum(1 for s in signals if "🔴" in s[2])
    if is_loss:
        overall = "⚫ 亏损公司估值（参考PS/PB/DCF）" if bullish >= bearish else "🔴 亏损且DCF显示高估"
        if bearish > bullish:
            overall = "🔴 亏损且多项指标偏高"
        elif bullish > bearish:
            overall = "🟡 亏损但PS/PB/DCF显示估值尚可"
        else:
            overall = "🟡 亏损公司，估值需结合PS/PB/DCF综合判断"
    else:
        overall = "🟢 估值偏低" if bullish > bearish else ("🔴 估值偏高" if bearish > bullish else "🟡 估值合理")

    return {"overall": overall, "signals": signals}


def format_markdown(data):
    if not data or not data.get("current"):
        return "## 估值分析\n\n_暂无行情数据_"

    cur = data["current"]
    pct = data.get("percentile", {})
    dcf = data.get("dcf", {})
    sens = data.get("sensitivity", [])
    conc = data.get("conclusion", {})

    lines = ["## 估值分析\n"]

    # 当前估值
    lines.append("### 当前估值指标\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    if cur.get("price"):
        lines.append(f"| 当前股价 | {cur['price']:.2f}元 |")
    if cur.get("market_cap_亿"):
        lines.append(f"| 总市值 | {cur['market_cap_亿']:.0f}亿元 |")
    if cur.get("float_market_cap_亿"):
        lines.append(f"| 流通市值 | {cur['float_market_cap_亿']:.0f}亿元 |")
    pe_ttm = cur.get("pe_ttm")
    if pe_ttm:
        lines.append(f"| PE(TTM) | {pe_ttm:.2f}x |")
    if cur.get("pe_dyn"):
        lines.append(f"| PE(动态) | {cur['pe_dyn']:.2f}x |")
    if cur.get("pb"):
        lines.append(f"| PB | {cur['pb']:.2f}x |")
    if cur.get("ps"):
        lines.append(f"| PS | {cur['ps']:.2f}x |")
    lines.append("")

    # 历史分位
    if pct:
        lines.append("### 历史估值分位\n")
        lines.append(f"- 当前PE(TTM): **{pct.get('pe_current', 'N/A')}x**")
        if pct.get("pe_hist_3y_pct") is not None:
            lines.append(f"- 历史3年分位: **{pct['pe_hist_3y_pct']:.0f}%**（区间{pct.get('pe_min_5y', '?')}x ~ {pct.get('pe_max_5y', '?')}x，中位{pct.get('pe_median_5y', '?')}x）")
        lines.append("")

    # 历史PE表
    hist_pe = data.get("historical_pe", [])
    if hist_pe:
        lines.append("### 历史PE变化\n")
        lines.append("| 报告期 | EPS(元) | PE(倍) |")
        lines.append("|--------|---------|--------|")
        for p in hist_pe[:8]:
            lines.append(f"| {p['date'][:7]} | {p['eps']:.3f} | {p['pe']:.1f}x |")
        lines.append("")

    # DCF框架
    if dcf:
        lines.append("### DCF估值框架（简化）\n")
        lines.append(f"- WACC: **{dcf.get('wacc_pct', 9):.1f}%** | 永续增长率: **{dcf.get('terminal_g_pct', 2.5):.1f}%**")
        lines.append(f"- 基准营收: **{dcf.get('revenue_base_亿', '?'):.1f}亿元** | 净利率: **{dcf.get('net_margin_pct', '?'):.1f}%** | FCF: **{dcf.get('fcf0_亿', '?'):.1f}亿元**")
        fcfs = dcf.get("fcf_forecast", [])
        if fcfs:
            lines.append(f"- 5年FCF: " + " | ".join([f"Y{f['year']}:{f['fcf_亿']}亿(PV{f['pv_亿']}亿)" for f in fcfs]))
        lines.append(f"- 终值: **{dcf.get('terminal_value_亿', 0):.1f}亿元** → PV: **{dcf.get('terminal_pv_亿', 0):.1f}亿元**")
        dcf_val = dcf.get("dcf_value_亿", 0)
        mkt = dcf.get("dcf_vs_market_pct")
        mkt_str = f"（较市值{mkt:+.0f}%）" if mkt is not None else ""
        lines.append(f"- **DCF股权价值: {dcf_val:.1f}亿元** {mkt_str}")
        lines.append(f"- ⚠️ {dcf.get('note', '')}")
        lines.append("")

    # 敏感性分析
    if sens:
        lines.append("### 敏感性分析（DCF估值，亿元）\n")
        tg_vals = sorted(set(k[3:] for k in sens[0].keys() if k.startswith("tg_")))
        lines.append("| WACC \\ 永续增长率 | " + " | ".join([f"{float(tg):.1f}%" for tg in tg_vals]) + " |")
        lines.append("|" + "|".join(["---"] * (len(tg_vals) + 1)) + "|")
        for row in sens:
            cells = [f"{row['wacc']:.1f}%"] + [str(row.get(f"tg_{tg}", "N/A")) for tg in tg_vals]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    # 综合结论
    if conc:
        lines.append("### 估值综合结论\n")
        lines.append(f"**总体判断**: {conc.get('overall', '数据不足')}")
        for label, val, signal in conc.get("signals", []):
            lines.append(f"- **{signal}** [{label}] {val}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    data = fetch_valuation(stock, data_dir="output/test")
    print(format_markdown(data))


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = format_markdown(data)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 估值分析\n\n", md]
