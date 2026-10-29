# -*- coding: utf-8 -*-
"""
AI批量分析模块

一次性输入多个维度的数据，让LLM一次性输出多个章节的解读
减少LLM调用次数，节约资源

支持的维度：
1. 财务分析解读
2. 高管动态分析
3. 资金动作分析
4. 投资者关系分析
"""

import json
import re
from typing import Dict, List, Any, Optional


def _build_financial_evidence(financial_data, multi_year_data=None):
    """构建财务数据证据"""
    parts = []
    if not financial_data:
        return ""

    records = financial_data.get('records', [])
    summary = financial_data.get('summary', {})
    audit = financial_data.get('audit_opinion', '')

    parts.append(f"审计意见: {audit}")
    if summary:
        parts.append(f"营收: {summary.get('revenue_亿', 'N/A')}亿 | 净利润: {summary.get('net_profit_亿', 'N/A')}亿 | 毛利率: {summary.get('gross_margin_pct', 'N/A')}%")

    for r in records[:4]:
        rdate = str(r.get('REPORTDATE', ''))[:10]
        rev = round(float(r.get('TOTAL_OPERATE_INCOME', 0)) / 1e8, 2) if r.get('TOTAL_OPERATE_INCOME') else 'N/A'
        np = round(float(r.get('PARENT_NETPROFIT', 0)) / 1e8, 2) if r.get('PARENT_NETPROFIT') else 'N/A'
        gm = round(float(r.get('GROSS_PROFIT_RATIO', 0)), 2) if r.get('GROSS_PROFIT_RATIO') else 'N/A'
        parts.append(f"{rdate}: 营收{rev}亿, 净利{np}亿, 毛利率{gm}%")

    if multi_year_data and multi_year_data.get('trend'):
        trend = multi_year_data['trend']
        cagr_rev = trend.get('revenue_cagr_pct')
        cagr_pro = trend.get('profit_cagr_pct')
        if cagr_rev is not None:
            parts.append(f"营收CAGR: {cagr_rev:+.2f}%")
        if cagr_pro is not None:
            parts.append(f"净利润CAGR: {cagr_pro:+.2f}%")

    if multi_year_data and multi_year_data.get('cashflow_quality'):
        cf = multi_year_data['cashflow_quality']
        parts.append(f"现金流质量: {cf.get('quality_signal', 'N/A')} (经营CF/净利比: {cf.get('avg_cf_netprofit_ratio', 'N/A')})")

    return '\n'.join(parts)


def _build_executive_evidence(executives_data):
    """构建高管变动数据证据"""
    parts = []
    if not executives_data:
        return ""

    changes = executives_data.get('changes', [])
    incentives = executives_data.get('equity_incentives', [])
    summary = executives_data.get('summary', {})

    parts.append(f"高管变动总数: {len(changes)}条")

    type_counts = {}
    for c in changes:
        t = c.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    parts.append(f"变动类型分布: {type_counts}")

    for c in changes[:10]:
        parts.append(f"{c.get('date', '')[:10]} [{c.get('type', '')}] {c.get('title', '')[:60]}")

    if incentives:
        parts.append(f"\n股权激励事项: {len(incentives)}条")
        for i in incentives[:5]:
            parts.append(f"{i.get('date', '')[:10]} [{i.get('type', '')}] {i.get('title', '')[:60]}")

    if summary.get('warnings'):
        parts.append(f"\n风险提示: {'; '.join(summary['warnings'][:3])}")

    return '\n'.join(parts)


def _build_capital_evidence(capital_data):
    """构建资金动作数据证据"""
    parts = []
    if not capital_data:
        return ""

    actions = capital_data.get('actions', [])
    parts.append(f"资金动作总数: {capital_data.get('count', 0)}项")

    type_counts = {}
    for a in actions:
        t = a.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    parts.append(f"动作类型分布: {type_counts}")

    risk_actions = [a for a in actions if a.get('risk_signal')]
    if risk_actions:
        parts.append(f"风险信号动作: {len(risk_actions)}项")
        for a in risk_actions[:5]:
            parts.append(f"  {a.get('date', '')[:10]} [{a.get('type', '')}] {a.get('risk_signal', '')}")

    for a in actions[:10]:
        parts.append(f"{a.get('date', '')[:10]} [{a.get('type', '')}] {a.get('title', '')[:60]}")

    return '\n'.join(parts)


def _build_investor_evidence(investor_data):
    """构建投资者互动数据证据"""
    parts = []
    if not investor_data:
        return ""

    ir = investor_data.get("ir_activities", [])
    surveys = investor_data.get("survey_records", [])
    roadshows = investor_data.get("roadshow_records", [])
    smry = investor_data.get("summary", {})

    parts.append(f"机构关注度: {smry.get('institutional_attention', '数据不足')}")
    parts.append(f"近12月调研次数: {smry.get('survey_count_12m', 0)}次")
    parts.append(f"近12月IR活动: {smry.get('ir_activity_count_12m', 0)}次")
    parts.append(f"近12月路演/业绩会: {smry.get('roadshow_count_12m', 0)}次")
    parts.append(f"参与机构数: {smry.get('unique_institutions', 0)}家")

    if surveys:
        parts.append(f"\n机构调研记录({len(surveys)}条):")
        for s in surveys[:8]:
            parts.append(f"  {s.get('date', '')} {s.get('organizers', '')[:30]} - {s.get('theme', '')[:40]}")

    if roadshows:
        parts.append(f"\n路演/业绩说明会({len(roadshows)}条):")
        for r in roadshows[:5]:
            parts.append(f"  {r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:50]}")

    return '\n'.join(parts)


def generate_batch_analysis(
    financial_data: Dict,
    executives_data: Dict,
    capital_data: Dict,
    investor_data: Dict,
    multi_year_data: Dict = None,
    company_name: str = "",
    stock_code: str = "",
    regulatory_data: Dict = None,
    governance_data: Dict = None,
) -> Dict[str, str]:
    """
    一次性生成多个维度的AI解读（扩展版：6个维度）

    返回:
        {
            "financial": "财务分析解读文本",
            "executives": "高管动态分析文本",
            "capital": "资金动作分析文本",
            "investor": "投资者关系分析文本",
            "regulatory": "监管合规分析文本",
            "governance": "公司治理分析文本",
        }
    """
    result = {
        "financial": "",
        "executives": "",
        "capital": "",
        "investor": "",
        "regulatory": "",
        "governance": "",
    }

    financial_evidence = _build_financial_evidence(financial_data, multi_year_data)
    executive_evidence = _build_executive_evidence(executives_data)
    capital_evidence = _build_capital_evidence(capital_data)
    investor_evidence = _build_investor_evidence(investor_data)
    regulatory_evidence = _build_regulatory_evidence(regulatory_data) if regulatory_data else ""
    governance_evidence = _build_governance_evidence(governance_data) if governance_data else ""

    has_data = any([
        financial_evidence, executive_evidence, capital_evidence,
        investor_evidence, regulatory_evidence, governance_evidence
    ])
    if not has_data:
        return result

    dim_count = sum(1 for e in [financial_evidence, executive_evidence, capital_evidence,
                                 investor_evidence, regulatory_evidence, governance_evidence] if e)

    dims_spec = """1. 每个维度的分析控制在200-400字
2. 语言专业、客观、有洞察力
3. 每个分析独立成段，不要交叉引用
4. 输出格式严格按照JSON"""

    sections = f"""===== 财务数据 =====
{financial_evidence or '暂无数据'}
===== 财务数据结束 =====

===== 高管变动数据 =====
{executive_evidence or '暂无数据'}
===== 高管变动数据结束 =====

===== 资金动作数据 =====
{capital_evidence or '暂无数据'}
===== 资金动作数据结束 =====

===== 投资者互动数据 =====
{investor_evidence or '暂无数据'}
===== 投资者互动数据结束 ====="""

    if regulatory_evidence:
        sections += f"""

===== 监管合规数据 =====
{regulatory_evidence}
===== 监管合规数据结束 ====="""

    if governance_evidence:
        sections += f"""

===== 公司治理数据 =====
{governance_evidence}
===== 公司治理数据结束 ====="""

    output_keys = '''{
  "financial": "财务分析解读（200-400字）",
  "executives": "高管动态分析（200-400字）",
  "capital": "资金动作分析（200-400字）",
  "investor": "投资者关系分析（200-400字）"'''

    if regulatory_evidence:
        output_keys += ',\n  "regulatory": "监管合规分析（200-400字）"'
    if governance_evidence:
        output_keys += ',\n  "governance": "公司治理分析（200-400字）"'
    output_keys += '\n}'

    prompt = f"""你是顶级券商首席分析师。以下是{company_name}（{stock_code}）的多维度数据，请一次性输出{dim_count}个维度的专业分析解读。

要求：
{dims_spec}

{sections}

请以JSON格式输出（不要输出其他内容）：
{output_keys}"""

    try:
        from scripts.llm_config import LLM_CONFIG
        from openai import OpenAI
        client = OpenAI(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
        )
        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=[
                {"role": "system", "content": "你是一位顶级券商首席分析师，擅长从多维度数据中提取关键信息并撰写专业分析报告。输出必须是合法JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=8192,
            stream=False
        )
        raw = response.choices[0].message.content

        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            data = json.loads(json_match.group())
            for key in result:
                if data.get(key) and len(data[key]) > 50:
                    result[key] = data[key]

        print(f"  [AI批量分析] 生成成功，{dim_count}个维度")

    except Exception as e:
        print(f"  [AI批量分析] LLM调用失败: {e}")
        result = _fallback_individual(financial_data, executives_data, capital_data, investor_data, multi_year_data)

    return result


def _build_regulatory_evidence(regulatory_data):
    """构建监管数据证据"""
    parts = []
    if not regulatory_data:
        return ""

    records = regulatory_data.get('records', [])
    summary = regulatory_data.get('summary', {})

    parts.append(f"监管记录总数: {len(records)}条")
    if summary.get('warnings'):
        parts.append(f"风险提示: {'; '.join(summary['warnings'][:3])}")

    severity_counts = {}
    for r in records:
        s = r.get('severity', '未知')
        severity_counts[s] = severity_counts.get(s, 0) + 1
    if severity_counts:
        parts.append(f"严重程度分布: {severity_counts}")

    for r in records[:8]:
        parts.append(f"{r.get('date', '')[:10]} [{r.get('severity', '')}] {r.get('title', '')[:60]}")

    return '\n'.join(parts)


def _build_governance_evidence(governance_data):
    """构建治理数据证据"""
    parts = []
    if not governance_data:
        return ""

    if governance_data.get('score') is not None:
        parts.append(f"治理评分: {governance_data['score']}/100")
    if governance_data.get('cr1') is not None:
        parts.append(f"第一大股东持股: {governance_data['cr1']}%")
    if governance_data.get('cr5') is not None:
        parts.append(f"前五大股东持股: {governance_data['cr5']}%")
    if governance_data.get('pledge_ratio') is not None:
        parts.append(f"股权质押比例: {governance_data['pledge_ratio']}%")

    top1 = governance_data.get('top1_holder', {})
    if top1:
        parts.append(f"控股股东: {top1.get('name', '')} 持股{top1.get('pct', '')}%")

    return '\n'.join(parts)


def _fallback_individual(financial_data, executives_data, capital_data, investor_data, multi_year_data):
    """LLM调用失败时的降级方案"""
    return {
        "financial": "",
        "executives": "",
        "capital": "",
        "investor": "",
        "regulatory": "",
        "governance": "",
    }


def generate_batch_analysis_from_findings(findings: Dict) -> Dict[str, str]:
    """从findings字典中提取数据并生成批量分析（扩展版，含监管+治理）"""
    financial_data = findings.get('financial', {})
    executives_data = findings.get('executives', {})
    capital_data = findings.get('capital', {})
    investor_data = findings.get('investor_qa', {})
    multi_year_data = findings.get('multi_year_trend', {})
    regulatory_data = findings.get('regulatory', {})
    governance_data = findings.get('governance', {})
    quote = findings.get('quote', {})

    company_name = quote.get('name', '')
    stock_code = quote.get('code', '')

    return generate_batch_analysis(
        financial_data=financial_data,
        executives_data=executives_data,
        capital_data=capital_data,
        investor_data=investor_data,
        multi_year_data=multi_year_data,
        company_name=company_name,
        stock_code=stock_code,
        regulatory_data=regulatory_data,
        governance_data=governance_data,
    )
