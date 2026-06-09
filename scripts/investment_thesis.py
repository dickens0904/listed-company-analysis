# -*- coding: utf-8 -*-
"""
投资逻辑自动生成模块

基于上市公司全景分析结果，通过LLM生成深度投资逻辑报告
输出格式：核心投资逻辑 + 催化剂 + 关键假设 + 风险提示 + 投资评级
"""
import json, os
from datetime import datetime


def _build_evidence_summary(findings):
    """汇总各维度数据，构建LLM输入证据"""
    parts = []

    company = findings.get('quote', {})
    name = company.get('name', '')
    parts.append(f"公司: {name} | 代码: {company.get('code', '')} | 行业: {company.get('industry', '')}")
    parts.append(f"当前股价: {company.get('price', 'N/A')} | 市值: {company.get('total_mv', 'N/A')}亿")

    fin = findings.get('financial', {})
    if fin:
        summary = fin.get('summary', {})
        revenue = summary.get('revenue_亿', fin.get('revenue', 'N/A'))
        net_profit = summary.get('net_profit_亿', fin.get('net_profit', 'N/A'))
        gross_margin = summary.get('gross_margin_pct', fin.get('gross_margin', 'N/A'))
        roe = summary.get('roe_pct', fin.get('roe', 'N/A'))
        parts.append(f"\n【财务数据】营收: {revenue}亿 | 净利润: {net_profit}亿 | 毛利率: {gross_margin}% | ROE: {roe}%")
        
        latest = fin.get('latest', {})
        if latest:
            debt_ratio = latest.get('DEBT_ASSET_RATIO', latest.get('debt_ratio', 'N/A'))
            op_cash = latest.get('OPERATE_CASH_FLOW_PS', latest.get('op_cash_per_share', 'N/A'))
            parts.append(f"资产负债率: {debt_ratio}% | 每股经营现金流: {op_cash}")
        
        records = fin.get('records', [])
        if records:
            parts.append(f"历史财报: {len(records)}期")
            for rec in records[:4]:
                rd = rec.get('report_date', '?')
                rev = rec.get('TOTAL_OPERATE_INCOME_YOY', rec.get('revenue_growth_pct', ''))
                profit_yoy = rec.get('PARENT_NETPROFIT_YOY', rec.get('profit_growth_pct', ''))
                parts.append(f"  {rd}: 营收增速{rev}% 净利增速{profit_yoy}%")

    trend = findings.get('multi_year_trend', {})
    if trend:
        parts.append(f"营收CAGR: {trend.get('revenue_cagr', 'N/A')} | 利润CAGR: {trend.get('profit_cagr', 'N/A')} | 趋势: {trend.get('trend', 'N/A')}")
        warnings = trend.get('warnings', [])
        if warnings:
            parts.append(f"财务预警: {'; '.join(warnings[:5])}")

    val = findings.get('valuation', {})
    if val:
        cur = val.get('current', {})
        parts.append(f"PE(TTM): {cur.get('pe_ttm', 'N/A')} | PB: {cur.get('pb', 'N/A')} | PS: {cur.get('ps_ttm', 'N/A')}")
        dcf = val.get('dcf', {})
        if dcf:
            parts.append(f"DCF估值: {dcf.get('dcf_value_亿', 'N/A')}亿 | 市值: {cur.get('market_cap_亿', 'N/A')}亿")
        conc = val.get('conclusion', {})
        if conc:
            parts.append(f"估值结论: {conc.get('overall', 'N/A')}")

    risk = findings.get('risk_score', {})
    if risk:
        parts.append(f"\n【风险评级】得分: {risk.get('score', 'N/A')}/100 | 等级: {risk.get('level', 'N/A')}")
        for r in risk.get('risks', [])[:6]:
            parts.append(f"  - [{r.get('level', '')}] {r.get('signal', '')}")

    ann = findings.get('announcements', {})
    if ann:
        parts.append(f"\n【公告摘要】总数: {ann.get('count', 0)}条 | CRITICAL: {ann.get('importance_stats', {}).get('critical', 0)}条")
        critical = ann.get('critical_announcements', [])[:8]
        for a in critical:
            tag = a.get('importance_tag', '')
            parts.append(f"  - [{tag}] {a.get('date', '')[:10]} {a.get('title', '')[:60]}")

        ann_ai = findings.get('ai_analysis', {}).get('announcements', {})
        if ann_ai.get('key_insights'):
            parts.append(f"公告核心洞察: {'; '.join(ann_ai['key_insights'][:5])}")
        if ann_ai.get('risk_summary'):
            parts.append(f"公告风险摘要: {ann_ai['risk_summary'][:300]}")

    inv = findings.get('investor_qa', {})
    if inv:
        survey = inv.get('survey_records', [])
        ir_acts = inv.get('ir_activities', [])
        parts.append(f"\n【投资者互动】调研记录: {len(survey)}条 | IR活动: {len(ir_acts)}条")
        
        # 最新投资者关系活动内容（含新业务方向等重要信息）
        for s in survey[:3]:
            title = s.get('title', '')
            date = s.get('date', '')
            content = s.get('content', '')
            if content and len(content) > 50:
                parts.append(f"  [{date}] {title[:50]}: {content[:200]}")
            else:
                parts.append(f"  [{date}] {title[:70]}")
        
        # AI分析叙事
        inv_narrative = findings.get('ai_analysis', {}).get('investor_qa', '')
        if inv_narrative:
            parts.append(f"投资者互动AI分析: {inv_narrative[:300]}")

    peer = findings.get('peer_compare', {})
    if peer:
        parts.append(f"\n【同业对比】结论: {peer.get('conclusion', 'N/A')}")
        for p in peer.get('peers', [])[:5]:
            parts.append(f"  - {p.get('name', '')} 营收:{p.get('revenue', 'N/A')}亿 PE:{p.get('pe', 'N/A')}")

    governance = findings.get('governance', {})
    if governance:
        parts.append(f"\n【治理评分】{governance.get('score', 'N/A')}/100")
        top1 = governance.get('top1_holder', {})
        if top1:
            parts.append(f"大股东: {top1.get('name', '')} 持股{top1.get('pct', 'N/A')}%")

    cross = findings.get('cross_validation', {})
    if cross:
        findings_cv = cross.get('findings', [])
        if findings_cv:
            parts.append(f"\n【交叉验证隐情】评分: {cross.get('score', 'N/A')}/100")
            for f in findings_cv[:5]:
                parts.append(f"  - [{f.get('level', '')}] {f.get('category', '')}→{f.get('type', '')}: {f.get('summary', '')[:60]}")

    strategic = findings.get('strategic_narrative', {})
    if strategic:
        highlights = strategic.get('highlights', [])
        if highlights:
            parts.append(f"\n【战略亮点】{'；'.join(highlights[:3])}")
        risks_s = strategic.get('risks', [])
        if risks_s:
            parts.append(f"【战略风险】{'；'.join(risks_s[:3])}")

    return '\n'.join(parts)


def generate_investment_thesis(analysis_data, stock_code, market='a'):
    """生成投资逻辑（LLM驱动）"""
    findings = analysis_data.get('findings', {})
    result = {
        "thesis": "",
        "catalysts": [],
        "assumptions": [],
        "risks": [],
        "investment_rating": "中性",
        "target_price": None,
        "markdown": "",
    }

    company_name = findings.get('quote', {}).get('name', stock_code)
    evidence = _build_evidence_summary(findings)

    llm_narrative = _generate_llm_thesis(company_name, stock_code, evidence, findings)

    if llm_narrative:
        result["thesis"] = llm_narrative.get("thesis", "")
        result["catalysts"] = llm_narrative.get("catalysts", [])
        result["assumptions"] = llm_narrative.get("assumptions", [])
        result["risks"] = llm_narrative.get("risks", [])
        result["investment_rating"] = llm_narrative.get("investment_rating", "中性")
        result["markdown"] = llm_narrative.get("markdown", "")

    if not result["markdown"]:
        result = _fallback_rule_based(analysis_data, stock_code, result)

    return result


def _generate_llm_thesis(company_name, stock_code, evidence, findings):
    """调用LLM生成投资逻辑"""
    prompt = f"""你是顶级券商首席分析师。以下是{company_name}（{stock_code}）的全景分析数据，请基于这些数据撰写一份完整的投资逻辑报告。

要求：
1. **投资评级**必须明确给出：强烈推荐/推荐/中性/减持/回避，并说明理由
2. **核心观点**：3-5句话概括投资逻辑，要具体、有洞察力，不要空话
3. **催化剂**：列出2-4个可能推动股价的具体事件或时间节点
4. **关键假设**：你的投资逻辑基于哪些核心假设
5. **风险提示**：列出3-5个具体风险，不要泛泛而谈
6. **估值判断**：结合PE/PB/DCF，给出合理估值区间判断
7. 语言风格：专业、果断、有观点，像真正的卖方研报

===== 公司数据 =====
{evidence}
===== 数据结束 =====

请以JSON格式输出（不要输出其他内容）：
{{
  "thesis": "核心投资观点（3-5句话）",
  "catalysts": ["催化剂1", "催化剂2", ...],
  "assumptions": ["假设1", "假设2", ...],
  "risks": ["风险1", "风险2", ...],
  "investment_rating": "评级",
  "markdown": "完整的投资逻辑报告（Markdown格式，1500-2500字）"
}}"""

    try:
        from scripts.llm_config import call_llm
        raw = call_llm(
            system_prompt="你是一位顶级券商首席分析师，擅长撰写深度投资逻辑报告。你的风格是果断、专业、有明确观点，绝不模棱两可。输出必须是合法JSON。",
            user_prompt=prompt,
            max_tokens=8192,
        )
        import re
        json_match = re.search(r'\{[\s\S]*\}', raw or '')
        if json_match:
            data = json.loads(json_match.group())
            if data.get("markdown") and len(data["markdown"]) > 200:
                print(f"  [投资逻辑LLM] 生成成功，{len(data['markdown'])}字")
                return data
    except Exception as e:
        print(f"  [投资逻辑LLM] 调用失败: {e}")

    return None


def _fallback_rule_based(analysis_data, stock_code, result):
    """LLM失败时的规则降级"""
    findings = analysis_data.get('findings', {})
    company_name = findings.get('quote', {}).get('name', stock_code)

    thesis_parts = []
    industry = findings.get('industry', {})
    if industry.get('competitors'):
        thesis_parts.append(f"申万行业可比公司{len(industry['competitors'])}家")

    financial = findings.get('financial', {})
    multi_year = findings.get('multi_year_trend', {})
    fin_highlights = []
    if financial.get('revenue'):
        rev = financial['revenue']
        if rev > 100:
            fin_highlights.append(f"营收{rev:.0f}亿")
    if financial.get('net_profit'):
        np = financial['net_profit']
        if np > 0:
            fin_highlights.append(f"净利{np:.1f}亿")
        elif np < 0:
            fin_highlights.append(f"净亏损{abs(np):.1f}亿")
    if financial.get('gross_margin'):
        gm = financial['gross_margin']
        if gm > 30:
            fin_highlights.append(f"毛利率{gm:.0f}%")
    if fin_highlights:
        thesis_parts.append("、".join(fin_highlights))

    valuation = findings.get('valuation', {})
    if valuation.get('pe_ttm') and isinstance(valuation['pe_ttm'], (int, float)):
        pe = valuation['pe_ttm']
        if pe > 0 and pe < 15:
            thesis_parts.append(f"低估值PE{pe:.0f}x")

    result["thesis"] = f"{company_name}：{'；'.join(thesis_parts)}。" if thesis_parts else f"{company_name}：数据不足，暂无法给出明确投资逻辑。"

    announcements = findings.get('announcements', {})
    catalysts = []
    if announcements.get('key_events'):
        for evt in announcements['key_events'][:3]:
            title = evt.get('title', '')[:30]
            if '收购' in title or '重组' in title:
                catalysts.append(title)
    result["catalysts"] = catalysts[:5] or ["等待业绩验证"]

    risk_score = findings.get('risk_score', {})
    risks = []
    if risk_score.get('risks'):
        for r in risk_score['risks'][:5]:
            if r.get('signal'):
                risks.append(r['signal'])
    result["risks"] = risks[:6] or ["行业竞争加剧", "宏观经济下行"]

    if risk_score.get('score') is not None:
        score = risk_score['score']
        if score < 30:
            result["investment_rating"] = "增持"
        elif score < 50:
            result["investment_rating"] = "中性"
        elif score < 70:
            result["investment_rating"] = "减持"
        else:
            result["investment_rating"] = "规避"

    md_lines = [
        "## 投资逻辑",
        "",
        f"**核心观点**: {result['thesis']}",
        "",
    ]
    if result['catalysts']:
        md_lines.append("**催化剂**:")
        for c in result['catalysts']:
            md_lines.append(f"- {c}")
        md_lines.append("")
    if result['risks']:
        md_lines.append("**风险提示**:")
        for r in result['risks']:
            md_lines.append(f"- {r}")
        md_lines.append("")
    md_lines.append(f"**投资评级**: {result['investment_rating']}")
    md_lines.append("")
    md_lines.append("> ⚠️ 以上投资逻辑由AI自动生成（规则降级模式），仅供参考，不构成投资建议。")
    result["markdown"] = "\n".join(md_lines)

    return result


def save_investment_thesis(thesis_data, output_dir, stock_code):
    """保存投资逻辑到文件"""
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(output_dir, 'investment_thesis.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(thesis_data, f, ensure_ascii=False, indent=2)

    # Markdown
    md_path = os.path.join(output_dir, 'investment_thesis.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(thesis_data['markdown'])

    return json_path, md_path


if __name__ == '__main__':
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else '002180'

    # 读取分析结果
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    results_path = os.path.join(parent_dir, 'output', f'{stock}_*', 'data', 'results.json')

    import glob
    matches = glob.glob(results_path)
    if not matches:
        print(f"未找到 {stock} 的分析结果，请先运行 analyze.py")
        sys.exit(1)

    latest = sorted(matches)[-1]
    print(f"读取: {latest}")

    with open(latest, encoding='utf-8') as f:
        data = json.load(f)

    thesis = generate_investment_thesis(data, stock)
    print(thesis['markdown'])
    print(f"\n投资评级: {thesis['investment_rating']}")
