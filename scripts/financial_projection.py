# -*- coding: utf-8 -*-
"""
financial_projection.py — 三年盈利预测模型

基于历史财务趋势+行业增长率+可覆写假设，生成机构级三年盈利预测。
核心输出：利润表预测 / 关键比率 / 估值隐含假设 / DCF估值区间

用法:
    from financial_projection import project_financials
    proj = project_financials('600519', multi_year_data, assumptions={})
"""
import json
import os
from datetime import datetime


def _safe(val, default=0.0):
    try:
        return float(val) if val not in (None, "", "N/A", "nan") else default
    except (ValueError, TypeError):
        return default


def _calc_cagr(values: list, periods: int = 3) -> float:
    """计算 CAGR（复合年增长率）。values 按时间正序。"""
    if len(values) < 2 or periods < 1:
        return 0.0
    v0, v1 = _safe(values[0]), _safe(values[-1])
    if v0 <= 0:
        return 0.0
    return (v1 / v0) ** (1.0 / periods) - 1.0


def _median(lst: list) -> float:
    s = sorted(_safe(x) for x in lst if _safe(x) != 0)
    n = len(s)
    if n == 0:
        return 0.0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


# ═════════════════════════════════════════════════════════════
# 主预测函数
# ═════════════════════════════════════════════════════════════

def project_financials(
    stock_code: str,
    multi_year_data: dict,
    industry_data: dict = None,
    assumptions: dict = None,
) -> dict:
    """
    生成三年盈利预测。

    Args:
        stock_code: 股票代码
        multi_year_data: multi_year_trend 模块的输出
        industry_data: 行业数据（可选，用于行业对比）
        assumptions: 可覆写的假设 dict
            - revenue_growth: list[float] 每年收入增速
            - gross_margin: list[float] 每年毛利率
            - net_margin: list[float] 每年净利率
            - pe_target: float 目标PE
            - wacc: float DCF折现率
            - terminal_growth: float 永续增长率

    Returns:
        {
            "revenue": [...],  "net_income": [...],  "eps": [...],
            "gross_margin": [...],  "net_margin": [...],  "roe": [...],
            "dcf_value": float,  "target_price": float,
            "assumptions_used": {...},  "confidence": "high/medium/low"
        }
    """
    assumptions = assumptions or {}

    # ── 提取历史数据（兼容两种格式） ──
    # 格式1: multi_year_trend 输出 (records + trend)
    # 格式2: 扁平 key-value (rev_2021, net_2021, ...)
    if "records" in multi_year_data and isinstance(multi_year_data.get("records"), list):
        records = multi_year_data["records"]
        # 筛选年报数据（仅包含"年报"但不包含"半年报"/"季报"）
        annual = [r for r in records
                  if "年报" in str(r.get("DATATYPE", ""))
                  and "半年报" not in str(r.get("DATATYPE", ""))
                  and "季报" not in str(r.get("DATATYPE", ""))]
        # 🔴 必须按报告期升序排序：东财 records 是降序（最新在前），若不排序，
        #    annual[-5:] 取到的是【最旧 5 期】、hist_revenue[-1] 取到【最旧年】。
        #    2026-10-23 实测 300168：latest_rev 曾误取 2021 年 35.13 亿（实际 2025 年 20.26 亿），
        #    导致 CAGR/预测方向全反（营收连降四年被算成正增长）。
        annual.sort(key=lambda r: str(r.get("DATAYEAR") or r.get("REPORTDATE") or ""))
        print(f"  [DEBUG] records={len(records)}, annual={len(annual)}")
        if len(annual) < 2:
            return {"error": f"至少需要2期年报数据，当前仅有{len(annual)}期", "revenue": [], "net_income": []}
        
        hist_revenue   = [_safe(r.get("TOTAL_OPERATE_INCOME", 0)) / 1e8 for r in annual[-5:]]
        hist_net_inc   = [_safe(r.get("PARENT_NETPROFIT", 0)) / 1e8 for r in annual[-5:]]
        hist_gross_mgn = [_safe(r.get("XSMLL", 0)) for r in annual[-5:]]  # 销售毛利率
        # 净利率估算：净利润/营收
        hist_net_mgn   = [(_safe(r.get("PARENT_NETPROFIT", 0)) / max(_safe(r.get("TOTAL_OPERATE_INCOME", 1)), 1)) * 100 for r in annual[-5:]]
        hist_roe       = [_safe(r.get("WEIGHTAVG_ROE", 0)) for r in annual[-5:]]
        # 用实际数据计算 CAGR（更可靠）
        if len(hist_revenue) >= 4:
            rev_cagr_3y = pow(hist_revenue[-1] / max(hist_revenue[-4], 1), 1/3) - 1
        else:
            rev_cagr_3y = 0.08
        rev_cagr_5y = pow(hist_revenue[-1] / max(hist_revenue[0], 1), 1/(len(hist_revenue)-1)) - 1 if len(hist_revenue) >= 2 else rev_cagr_3y
        fy = [r.get("DATAYEAR", "") for r in annual[-5:]]
    else:
        # 扁平格式兼容（原测试用）
        fy_raw = multi_year_data.get("fiscal_years", []) or []
        fy = [y.rstrip("AEae").strip() if isinstance(y, str) else str(y) for y in fy_raw]
        fy.sort()  # 🔴 升序，保证 [-yrs:] 取到的是最新年份（同 records 降序坑）
        yrs = min(len(fy), 5)
        hist_revenue   = [_safe(multi_year_data.get(f"rev_{y}", 0)) / 1e8 for y in fy[-yrs:]]
        hist_net_inc   = [_safe(multi_year_data.get(f"net_{y}", 0)) / 1e8 for y in fy[-yrs:]]
        hist_gross_mgn = [_safe(multi_year_data.get(f"gpm_{y}", 0)) for y in fy[-yrs:]]
        hist_net_mgn   = [_safe(multi_year_data.get(f"npm_{y}", 0)) for y in fy[-yrs:]]
        hist_roe       = [_safe(multi_year_data.get(f"roe_{y}", 0)) for y in fy[-yrs:]]
        rev_cagr_3y = _calc_cagr(hist_revenue[-4:], 3) if len(hist_revenue) >= 4 else 0.08
        rev_cagr_5y = _calc_cagr(hist_revenue, min(5, len(hist_revenue)-1))

    if not hist_revenue or not any(hist_revenue):
        return {"error": "无法提取有效的历史营收数据", "revenue": [], "net_income": []}
    avg_gross_m  = _median(hist_gross_mgn[-3:]) / 100.0 if hist_gross_mgn else 0.5
    avg_net_m    = _median(hist_net_mgn[-3:]) / 100.0 if hist_net_mgn else 0.15
    avg_roe      = _median(hist_roe[-3:]) / 100.0 if hist_roe else 0.15
    latest_rev   = hist_revenue[-1] if hist_revenue else 0
    latest_ni    = hist_net_inc[-1] if hist_net_inc else 0
    print(f"  [DEBUG] latest_rev={latest_rev}, latest_ni={latest_ni}, hist_revenue={hist_revenue}")

    # 统一单位：hist_revenue/net_inc 已在亿元

    # ── 行业增速调整 ──
    industry_growth = 0.05
    if industry_data:
        industry_growth = _safe(industry_data.get("revenue_growth", 0.05))

    # ── 驱动假设 ──
    # 收入增速 = 历史趋势 × 0.7 + 行业增速 × 0.3，逐年衰减10%
    base_growth = rev_cagr_3y * 0.7 + industry_growth * 0.3
    if base_growth <= 0:
        base_growth = max(rev_cagr_5y, 0.03)

    revenue_growth_user = assumptions.get("revenue_growth", [])
    gross_margin_user   = assumptions.get("gross_margin", [])
    net_margin_user     = assumptions.get("net_margin", [])

    # 生成3年预测
    revenue   = []
    net_inc   = []
    gross_mgn = []
    net_mgn   = []
    eps       = []
    roe_list  = []

    cur_rev = latest_rev
    total_shares = assumptions.get("total_shares", 12.5)  # 总股本（亿股）
    if total_shares <= 0 or total_shares > 1000:
        total_shares = 12.5  # fallback
    yrs = min(5, len(fy) if fy else 5)
    
    latest_rev_yi = latest_rev  # 已在亿元单位

    for i in range(3):
        grow = revenue_growth_user[i] if i < len(revenue_growth_user) else base_growth * (0.9 ** i)
        rev  = cur_rev * (1.0 + grow)
        gpm  = gross_margin_user[i] / 100.0 if i < len(gross_margin_user) else avg_gross_m
        npm  = net_margin_user[i] / 100.0 if i < len(net_margin_user) else avg_net_m
        ni   = rev * npm
        ep   = ni / total_shares  # 亿元 / 亿股 = 元/股
        ro   = avg_roe  # 简化：假设ROE稳定

        revenue.append(round(rev, 2))    # 亿元（已在亿元单位）
        net_inc.append(round(ni, 2))
        gross_mgn.append(round(gpm * 100, 1))
        net_mgn.append(round(npm * 100, 1))
        eps.append(round(ep, 2))
        roe_list.append(round(ro * 100, 1))
        cur_rev = rev

    # ── 生成 historical 输出 ──
    yrs = min(5, len(fy) if fy else 5)
    
    # ── DCF 估值 ──
    wacc     = assumptions.get("wacc", 0.09)
    tg       = assumptions.get("terminal_growth", 0.03)
    fcf_mgn  = 0.85  # FCF/净利润比率
    dcf_val  = 0
    for i in range(3):
        fcf  = net_inc[i] * 1e8 * fcf_mgn  # 亿→元
        dcf_val += fcf / ((1 + wacc) ** (i + 1))
    terminal = (net_inc[-1] * 1e8 * fcf_mgn * (1 + tg)) / (wacc - tg)
    terminal /= (1 + wacc) ** 3
    dcf_val = (dcf_val + terminal) / 1e8  # 亿元

    # ── 目标价 ──
    pe_target   = assumptions.get("pe_target", max(18.0, 1.0 / wacc))
    # 🔴 亏损公司：EPS 为负时 PE 法目标价必为负值，无经济意义 → 置空（禁止当结论引用）
    if eps and eps[-1] < 0:
        target_price = None
        target_note = ('公司预测 EPS 为负（亏损），PE 法目标价无经济意义，已置空；'
                       '估值应改用 PS / PB / EV-Sales 口径')
    else:
        target_price = round(eps[-1] * pe_target, 2)
        target_note = None

    # ── 置信度 ──
    if len(fy) >= 5 and rev_cagr_3y > 0:
        confidence = "high"
    elif len(fy) >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "stock": stock_code,
        "historical": {
            "years": fy[-yrs:],
            # 🔴 hist_revenue / hist_net_inc 进入函数时已 /1e8（单位＝亿元），此处不可再除
            "revenue_yi": [round(r, 2) for r in hist_revenue],
            "net_income_yi": [round(n, 2) for n in hist_net_inc],
            "gross_margin_pct": [round(g, 1) for g in hist_gross_mgn],
            "net_margin_pct": [round(n, 1) for n in hist_net_mgn],
            "roe_pct": [round(r, 1) for r in hist_roe],
            "revenue_cagr_3y": round(rev_cagr_3y * 100, 1),
            "revenue_cagr_5y": round(rev_cagr_5y * 100, 1),
        },
        "projection": {
            "years": ["2026E", "2027E", "2028E"],
            "revenue_yi": revenue,
            "yoy_growth_pct": [round((revenue[i] / (revenue[i-1] if i > 0 else latest_rev_yi) - 1) * 100, 1) for i in range(3)],
            "net_income_yi": net_inc,
            "gross_margin_pct": gross_mgn,
            "net_margin_pct": net_mgn,
            "eps": eps,
            "roe_pct": roe_list,
        },
        "valuation": {
            "dcf_value_yi": round(dcf_val, 0),
            "target_price": target_price,
            "target_price_note": target_note,
            "pe_target": pe_target,
            "wacc": wacc,
            "terminal_growth": tg,
        },
        "assumptions_used": {
            "base_revenue_growth": f"{base_growth*100:.1f}%",
            "avg_gross_margin": f"{avg_gross_m*100:.1f}%",
            "avg_net_margin": f"{avg_net_m*100:.1f}%",
            "source": "historical_trend × 0.7 + industry × 0.3",
        },
        "confidence": confidence,
    }


# ═════════════════════════════════════════════════════════════
# HTML 表格生成（嵌入报告）
# ═════════════════════════════════════════════════════════════

def format_projection_html(proj: dict) -> str:
    """将预测结果格式化为HTML表格（嵌入研究报告用）。"""
    if proj.get("error"):
        return f"<p style='color:#c00'>❌ {proj['error']}</p>"

    hist = proj["historical"]
    fut  = proj["projection"]
    val  = proj["valuation"]
    conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(proj["confidence"], "⚪")

    html = ['<div class="projection-section"><h3>📊 三年盈利预测' + conf_emoji + '</h3>']

    # ── 预测表 ──
    h_yrs = hist["years"][-3:] if len(hist["years"]) >= 3 else hist["years"]
    h_rev = hist["revenue_yi"][-3:] if len(hist["revenue_yi"]) >= 3 else hist["revenue_yi"]
    h_ni  = hist["net_income_yi"][-3:] if len(hist["net_income_yi"]) >= 3 else hist["net_income_yi"]

    html.append('<table><thead><tr>')
    html.append('<th>指标</th>')
    for y in h_yrs + fut["years"]:
        tag = " (E)" if "E" in str(y) else ""
        html.append(f'<th>{y}{tag}</th>')
    html.append('</tr></thead><tbody>')

    # 营收
    html.append('<tr><td><b>营业收入（亿元）</b></td>')
    for v in h_rev + fut["revenue_yi"]:
        html.append(f'<td>{v}</td>')
    html.append('</tr>')

    # 营收增速
    html.append('<tr><td>营收增速</td>')
    for v in (["—"] * (len(h_rev)-1)) + [f"{hist['revenue_cagr_3y']}% CAGR"] + [f"{g}%" for g in fut["yoy_growth_pct"]]:
        html.append(f'<td>{v}</td>')
    html.append('</tr>')

    # 归母净利润
    html.append('<tr><td><b>归母净利润（亿元）</b></td>')
    for v in h_ni + fut["net_income_yi"]:
        html.append(f'<td>{v}</td>')
    html.append('</tr>')

    # 净利率
    html.append('<tr><td>净利率</td>')
    for v in (hist["net_margin_pct"][-3:] + fut["net_margin_pct"]):
        html.append(f'<td>{v}%</td>')
    html.append('</tr>')

    # 毛利率
    html.append('<tr><td>毛利率</td>')
    for v in (hist["gross_margin_pct"][-3:] + fut["gross_margin_pct"]):
        html.append(f'<td>{v}%</td>')
    html.append('</tr>')

    # EPS
    html.append('<tr><td><b>EPS（元）</b></td>')
    html.append('<td>—</td><td>—</td><td>—</td>')
    for v in fut["eps"]:
        html.append(f'<td>{v}</td>')
    html.append('</tr>')

    html.append('</tbody></table>')

    # ── 假设 ──
    html.append('<h4>驱动假设</h4><ul>')
    for k, v in proj["assumptions_used"].items():
        html.append(f'<li><b>{k}</b>：{v}</li>')
    html.append('</ul>')

    # ── DCF ──
    html.append(f'''<h4>💎 估值参考</h4>
    <p>DCF估值（WACC={val['wacc']*100:.1f}%, 永续增长={val['terminal_growth']*100:.1f}%）：
    <b>{val['dcf_value_yi']:.0f}亿元</b></p>
    <p>目标PE {val['pe_target']:.0f}倍 → 目标价 <b>{val['target_price']}元</b></p>
    </div>''')

    return "\n".join(html)


# ═════════════════════════════════════════════════════════════
# CLI 测试
# ═════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    # 模拟 multi_year_trend 数据
    test_data = {
        "fiscal_years": ["2021A", "2022A", "2023A", "2024A", "2025A"],
        "rev_2021": 1.095e11, "rev_2022": 1.274e11, "rev_2023": 1.475e11,
        "rev_2024": 1.697e11, "rev_2025": 1.861e11,
        "net_2021": 5.24e10, "net_2022": 6.27e10, "net_2023": 7.47e10,
        "net_2024": 8.62e10, "net_2025": 9.47e10,
        "gpm_2021": 91.5, "gpm_2022": 91.9, "gpm_2023": 92.0,
        "gpm_2024": 91.8, "gpm_2025": 91.5,
        "npm_2021": 47.9, "npm_2022": 49.2, "npm_2023": 50.6,
        "npm_2024": 50.8, "npm_2025": 50.9,
        "roe_2021": 29.0, "roe_2022": 30.2, "roe_2023": 31.9,
        "roe_2024": 32.5, "roe_2025": 33.1,
    }

    result = project_financials("600519", test_data)
    if result.get("error"):
        print("ERROR:", result["error"])
    else:
        print("=== 三年盈利预测 ===")
        print(json.dumps(result["projection"], ensure_ascii=False, indent=2))
        print()
        print("=== DCF估值 ===", json.dumps(result["valuation"], ensure_ascii=False))
