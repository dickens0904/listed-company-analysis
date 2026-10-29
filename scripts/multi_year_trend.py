# -*- coding: utf-8 -*-
"""
多年期财务趋势分析模块
数据源: 东方财富 RPT_LICO_FN_CPD（20期）
功能: 营收/利润CAGR、毛利率趋势、杜邦分析、现金流质量、财务预警
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


def _format_secucode(stock_code):
    if stock_code.endswith((".SH", ".SZ", ".BJ")):
        return stock_code
    if stock_code[:2] in ["00", "30"]:
        return f"{stock_code}.SZ"
    if stock_code[:2] in ["60", "68"]:
        return f"{stock_code}.SH"
    if stock_code[0] in ["8", "4"]:
        return f"{stock_code}.BJ"
    return f"{stock_code}.SZ"


def _cagr(values, n_years=None):
    """CAGR计算，values为(period_str, value)列表"""
    valid = [(p, v) for p, v in values if v is not None and v > 0]
    if len(valid) < 2:
        return None, None
    end_p, end_v = valid[0]   # 最新
    start_p, start_v = valid[-1]  # 最早
    try:
        n_yrs = n_years or (int(end_p[:4]) - int(start_p[:4]))
        if n_yrs <= 0:
            return None, None
        return round(((end_v / start_v) ** (1 / n_yrs) - 1) * 100, 2), n_yrs
    except Exception:
        return None, None


def fetch_multi_year_trend(stock_code, market="a", data_dir=None, records=None):
    """主函数：多年期财务趋势分析"""
    result = {
        "stock_code": stock_code,
        "market": market,
        "records": [],
        "trend": {},
        "dupont": {},
        "cashflow_quality": {},
        "warnings": [],
        "risks": [],
    }

    # 港股：使用AKShare港股财务指标（多年）
    if market == "hk":
        try:
            from scripts.hk_financial import fetch_hk_financial_indicator
            hk_data = fetch_hk_financial_indicator(stock_code, years=10)
            if hk_data.get('success') and hk_data.get('indicators'):
                inds = hk_data['indicators']
                result["records"] = inds
                result["source"] = "akshare_hk_fin"

                # 构建趋势序列
                rev_series = [(i.get('date',''), i.get('operate_income')) for i in inds if i.get('operate_income')]
                pro_series = [(i.get('date',''), i.get('holder_profit')) for i in inds if i.get('holder_profit') is not None]
                gm_series = [(i.get('date',''), i.get('gross_margin')) for i in inds if i.get('gross_margin') is not None]
                roe_series = [(i.get('date',''), i.get('roe')) for i in inds if i.get('roe') is not None]
                yoy_series = [(i.get('date',''), i.get('income_yoy')) for i in inds if i.get('income_yoy') is not None]

                # 营收CAGR
                cagr_rev = None
                if len(rev_series) >= 2:
                    rev_latest = rev_series[0][1]
                    rev_earliest = rev_series[-1][1]
                    if rev_earliest and rev_earliest > 0:
                        cagr_rev = ((rev_latest / rev_earliest) ** (1 / (len(rev_series)-1)) - 1) * 100

                # 净利润CAGR
                cagr_pro = None
                if len(pro_series) >= 2:
                    pro_latest = pro_series[0][1]
                    pro_earliest = pro_series[-1][1]
                    n_years = len(pro_series) - 1
                    if pro_earliest and pro_earliest > 0 and n_years > 0:
                        cagr_pro = ((pro_latest / pro_earliest) ** (1 / n_years) - 1) * 100

                # 毛利率趋势
                gm_trend = "未知"
                gm_latest = gm_series[0][1] if gm_series else None
                gm_5y_vals = [g[1] for g in gm_series[:5] if g[1] is not None]
                gm_5y_avg = sum(gm_5y_vals) / len(gm_5y_vals) if gm_5y_vals else None
                if gm_latest is not None and gm_5y_avg is not None:
                    if gm_latest > gm_5y_avg + 2:
                        gm_trend = "上升"
                    elif gm_latest < gm_5y_avg - 2:
                        gm_trend = "下降"
                    else:
                        gm_trend = "平稳"

                # 现金流质量（用 ocf_per_sales 近似）
                cf_ratios = []
                for i in inds:
                    ocf_ratio = i.get('ocf_per_sales')
                    if ocf_ratio is not None:
                        cf_ratios.append((i.get('date',''), ocf_ratio))
                cf_avg = sum(r[1] for r in cf_ratios) / len(cf_ratios) if cf_ratios else None
                cf_signal = "良好" if cf_avg and cf_avg > 5 else ("一般" if cf_avg and cf_avg > 0 else "数据不足")

                # 风险信号
                risks = []
                if gm_latest is not None and gm_5y_avg is not None and gm_latest < gm_5y_avg - 5:
                    risks.append(f"毛利率大幅下滑: {gm_latest:.1f}% vs 5年均值 {gm_5y_avg:.1f}%")
                if roe_series and roe_series[0][1] is not None and roe_series[0][1] < 3:
                    risks.append(f"ROE极低: {roe_series[0][1]:.1f}%")
                for i in inds[:2]:
                    if i.get('holder_profit') is not None and i['holder_profit'] < 0:
                        risks.append(f"{i.get('date','')} 净利润为负")
                dar = inds[0].get('debt_asset_ratio') if inds else None
                if dar and dar > 70:
                    risks.append(f"资产负债率偏高: {dar:.1f}%")

                result["trend"] = {
                    "revenue_cagr_pct": round(cagr_rev, 2) if cagr_rev is not None else None,
                    "revenue_cagr_years": len(rev_series),
                    "profit_cagr_pct": round(cagr_pro, 2) if cagr_pro is not None else None,
                    "profit_cagr_years": len(pro_series),
                    "revenue_series": rev_series,
                    "profit_series": pro_series,
                    "gross_margin_series": gm_series,
                    "roe_series": roe_series,
                    "ystz_series": yoy_series,
                    "gross_margin_trend": gm_trend,
                    "gross_margin_latest": gm_latest,
                    "gross_margin_5y_avg": gm_5y_avg,
                }
                result["cashflow_quality"] = {
                    "avg_cf_netprofit_ratio": cf_avg,
                    "quality_signal": cf_signal,
                    "cf_to_netprofit_ratios": cf_ratios,
                }
                result["risks"] = risks
                result["year_span"] = len(inds)
            else:
                result["warnings"].append("港股多年趋势数据获取失败")
        except Exception as e:
            result["warnings"].append(f"港股数据获取异常: {str(e)[:50]}")
        return result
    
    # 美股：使用SEC历史数据（仅限纯字母代码如AAPL）
    if market == "us" or (stock_code.upper() == stock_code and stock_code.isalpha()):
        try:
            # 导入SEC历史模块
            import sys
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from us_history import fetch_sec_history
            hist_data = fetch_sec_history(stock_code)
            if 'error' not in hist_data:
                result["company_info"] = hist_data.get("company", {})
                result["filings_count"] = hist_data.get("filings_count", {})
                result["warnings"].append("使用SEC历史数据")
            else:
                result["warnings"].append(hist_data.get("error", "SEC数据获取失败"))
        except Exception as e:
            result["warnings"].append(f"美股数据获取异常: {str(e)[:30]}")
        return result

    # A股：使用东方财富API
    if records is None:
        secucode = _format_secucode(stock_code)
        params = {
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "ALL",
            "filter": f'(SECUCODE="{secucode}")',
            "pageNumber": 1, "pageSize": 20,
            "sortTypes": -1, "sortColumns": "REPORTDATE",
            "source": "WEB", "client": "WEB",
        }
        raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=20)
        records = safe_extract(raw, ["result", "data"], default=[]) or []

    result["records"] = records
    if not records:
        result["warnings"].append("RPT_LICO_FN_CPD 无数据返回")
        return result

    # 提取各指标序列
    revenues = [(r.get("REPORTDATE", "")[:10], safe_float(r.get("TOTAL_OPERATE_INCOME"))) for r in records]
    profits = [(r.get("REPORTDATE", "")[:10], safe_float(r.get("PARENT_NETPROFIT"))) for r in records]
    gross_margins = [(r.get("REPORTDATE", "")[:10], safe_float(r.get("XSMLL"))) for r in records]
    roes = [(r.get("REPORTDATE", "")[:10], safe_float(r.get("WEIGHTAVG_ROE"))) for r in records]
    ystz_list = [(r.get("REPORTDATE", "")[:10], safe_float(r.get("YSTZ"))) for r in records]
    sjltz_list = [(r.get("REPORTDATE", "")[:10], safe_float(r.get("SJLTZ"))) for r in records]

    # CAGR
    cagr_rev, n_rev = _cagr(revenues)
    cagr_pro, n_pro = _cagr(profits)

    # 毛利率趋势
    gm_vals = [v for _, v in gross_margins if v is not None]
    gm_latest = gm_vals[0] if gm_vals else None
    gm_5y = round(sum(gm_vals[:5]) / len(gm_vals[:5]), 2) if len(gm_vals) >= 5 else None
    gm_change = round(gm_latest - gm_vals[-1], 2) if len(gm_vals) >= 2 else None
    if gm_change is not None:
        gm_trend = "上升" if gm_change > 2 else ("下降" if gm_change < -2 else "基本稳定")
    else:
        gm_trend = "数据不足"

    # 现金流质量
    cf_ratios = []
    for i in range(min(3, len(records))):
        eps_ = safe_float(records[i].get("BASIC_EPS"))
        oc_ps = safe_float(records[i].get("MGJYXJJE"))
        # 用每股经营现金流/每股收益计算比率（两个都是per-share值，量纲匹配）
        if eps_ and abs(eps_) > 0.001 and oc_ps is not None:
            cf_ratios.append(round(oc_ps / eps_, 3))

    avg_cf = round(sum(cf_ratios) / len(cf_ratios), 3) if cf_ratios else None
    if avg_cf is None:
        cf_signal = "数据不足"
    elif avg_cf >= 0.8:
        cf_signal = "良好：经营现金流持续覆盖净利润"
    elif avg_cf >= 0.5:
        cf_signal = "一般：现金流部分覆盖利润"
    elif avg_cf >= 0:
        cf_signal = "预警：现金流低于净利润"
    else:
        cf_signal = "异常：经营现金流为负但账面盈利"

    # 杜邦分析（简化）
    latest = records[0]
    net_margin = None
    rev0 = safe_float(latest.get("TOTAL_OPERATE_INCOME"))
    if rev0 and rev0 > 0:
        np0 = safe_float(latest.get("PARENT_NETPROFIT", 0)) or 0
        net_margin = round(np0 / rev0 * 100, 2)

    result["trend"] = {
        "revenue_cagr_pct": cagr_rev, "revenue_cagr_years": n_rev,
        "profit_cagr_pct": cagr_pro, "profit_cagr_years": n_pro,
        "revenue_series": revenues, "profit_series": profits,
        "gross_margin_series": gross_margins, "roe_series": roes,
        "ystz_series": ystz_list, "sjltz_series": sjltz_list,
        "gross_margin_trend": gm_trend, "gross_margin_change_pct": gm_change,
        "gross_margin_latest": gm_latest, "gross_margin_5y_avg": gm_5y,
    }
    result["dupont"] = {
        "net_margin_latest_pct": net_margin,
        "roe_latest_pct": safe_float(latest.get("WEIGHTAVG_ROE")),
        "note": "完整杜邦分析需资产负债表数据，本模块提供ROE和净利率趋势作为替代",
    }
    result["cashflow_quality"] = {
        "cf_to_netprofit_ratios": cf_ratios,
        "avg_cf_netprofit_ratio": avg_cf,
        "quality_signal": cf_signal,
    }

    # 财务预警
    warnings, risks = [], []

    def _consec(series, n_=2):
        vals = [v for _, v in series if v is not None]
        if len(vals) < n_ + 1:
            return False
        return all(vals[i] < vals[i + 1] for i in range(n_))

    if _consec(ystz_list):
        warnings.append("营收连续2期下滑")
        risks.append({"level": "medium", "dim": "财务趋势", "signal": "营收连续下滑"})
    if _consec(sjltz_list):
        warnings.append("净利润连续2期下滑")
        risks.append({"level": "medium", "dim": "财务趋势", "signal": "净利润连续下滑"})
    if len(gm_vals) >= 2 and gm_vals[0] is not None and gm_vals[1] is not None:
        gm_chg = gm_vals[0] - gm_vals[1]
        if abs(gm_chg) > 5:
            warnings.append(f"毛利率单期异常波动{gm_chg:+.2f}个百分点")
            risks.append({"level": "medium", "dim": "财务趋势", "signal": f"毛利率单期变化{gm_chg:+.2f}%"})
    if roes and roes[0][1] is not None and roes[0][1] < 0:
        warnings.append("ROE为负，股东回报为负")
        risks.append({"level": "high", "dim": "财务趋势", "signal": "ROE为负"})
    losses = sum(1 for r in records[:3] if safe_float(r.get("PARENT_NETPROFIT", 0)) < 0)
    if losses >= 2:
        warnings.append("连续亏损")
        risks.append({"level": "high", "dim": "财务趋势", "signal": "连续亏损"})

    result["warnings"] = warnings
    result["risks"] = risks

    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "multi_year_trend.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return result


def format_markdown(data):
    """格式化多年期趋势分析为Markdown"""
    if not data or not data.get("records"):
        return "## 多年财务趋势\n\n_暂无数据_"

    t = data["trend"]
    c = data["cashflow_quality"]
    warns = data["warnings"]
    risks = data["risks"]

    lines = ["## 多年期财务趋势分析\n"]

    cagr_rev = t.get("revenue_cagr_pct")
    cagr_pro = t.get("profit_cagr_pct")
    n_rev = t.get("revenue_cagr_years")
    n_pro = t.get("profit_cagr_years")
    if cagr_rev is not None:
        icon = "📈" if cagr_rev > 0 else "📉"
        lines.append(f"**营收CAGR**: {icon} {cagr_rev:+.2f}%/年（{n_rev or '?'}年期）")
    if cagr_pro is not None:
        icon = "📈" if cagr_pro > 0 else "📉"
        lines.append(f"**净利润CAGR**: {icon} {cagr_pro:+.2f}%/年（{n_pro or '?'}年期）")
    lines.append("")

    rev_s = t.get("revenue_series", [])
    pro_s = t.get("profit_series", [])
    gm_s = t.get("gross_margin_series", [])
    roe_s = t.get("roe_series", [])
    ystz_s = t.get("ystz_series", [])

    if rev_s:
        lines.append("### 核心财务指标趋势\n")
        lines.append("| 报告期 | 营收(亿) | 净利润(亿) | 毛利率(%) | ROE(%) | 营收增速(%) |")
        lines.append("|--------|---------|---------|---------|-------|-----------|")
        for i in range(min(8, len(rev_s))):
            rd = rev_s[i][0][:7] if rev_s[i][0] else "?"
            rv = round(rev_s[i][1] / 1e8, 1) if rev_s[i][1] else "N/A"
            pv = round(pro_s[i][1] / 1e8, 1) if (i < len(pro_s) and pro_s[i][1]) else "N/A"
            gv = f"{gm_s[i][1]:.1f}" if (i < len(gm_s) and gm_s[i][1] is not None) else "N/A"
            rov = f"{roe_s[i][1]:.1f}" if (i < len(roe_s) and roe_s[i][1] is not None) else "N/A"
            yv = f"{ystz_s[i][1]:+.1f}" if (i < len(ystz_s) and ystz_s[i][1] is not None) else "N/A"
            lines.append(f"| {rd} | {rv} | {pv} | {gv} | {rov} | {yv} |")
        lines.append("")

    # 毛利率趋势
    gm_trend = t.get("gross_margin_trend", "未知")
    gm_latest = t.get("gross_margin_latest")
    gm_5y = t.get("gross_margin_5y_avg")
    lines.append("### 毛利率趋势\n")
    if gm_latest is not None:
        diff = (gm_5y - gm_latest) if gm_5y else 0
        lines.append(f"- 最新毛利率: **{gm_latest:.2f}%**（{gm_trend}，较5年均值{diff:+.2f}%）" if gm_5y
                     else f"- 最新毛利率: **{gm_latest:.2f}%**（{gm_trend}）")
    lines.append("")

    # 现金流质量
    cf_avg = c.get("avg_cf_netprofit_ratio")
    cf_signal = c.get("quality_signal", "数据不足")
    cf_ratios = c.get("cf_to_netprofit_ratios", [])
    lines.append("### 现金流质量\n")
    if cf_avg is not None:
        lines.append(f"- 经营CF/净利润比率（近3期）: {cf_avg:.2f} → {cf_signal}")
    if cf_ratios:
        # 兼容两种格式：纯数值 或 (date, value) 元组
        vals = [r[1] if isinstance(r, (list, tuple)) else r for r in cf_ratios[:5]]
        lines.append(f"- 逐期比率: {' → '.join([f'{v:.2f}' for v in vals])}")
    lines.append("")

    # 预警
    if warns:
        lines.append("### ⚠️ 财务预警信号\n")
        for w in warns:
            lines.append(f"- {w}")
        lines.append("")

    if risks:
        lines.append("### 风险明细\n")
        for r in risks:
            icon = "🔴" if r["level"] == "high" else "🟡"
            lines.append(f"- {icon} [{r['dim']}] {r['signal']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    data = fetch_multi_year_trend(stock, data_dir="output/test")
    print(format_markdown(data))


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = format_markdown(data)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 多年财务趋势\n\n", md]
