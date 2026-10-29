# -*- coding: utf-8 -*-
"""
AI 分析师模块
使用商汤 DeepSeek V4 Flash 按照首席券商分析师能力进行深度分析
"""
import json
import time
import sys
from datetime import datetime
from scripts.llm_config import LLM_CONFIG, get_analyst_prompt

# 确保 UTF-8 编码
sys.stdout.reconfigure(encoding='utf-8')

def call_llm(prompt, max_retries=3):
    """调用商汤 DeepSeek V4 Flash API"""
    try:
        from openai import OpenAI
        
        client = OpenAI(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
        )
        
        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=[
                {
                    "role": "system", 
                    "content": "你是一位顶级券商首席分析师，以专业、严谨、客观的风格进行分析。"
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=LLM_CONFIG["temperature"],
            max_tokens=LLM_CONFIG["max_tokens"],
            stream=False
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"❌ LLM API 调用失败: {e}")
        if max_retries > 0:
            print(f"⏳ 等待 5 秒后重试...")
            time.sleep(5)
            return call_llm(prompt, max_retries - 1)
        return None


def generate_analyst_report(results, out_dir):
    """生成首席分析师风格的深度分析报告"""
    print("\n" + "="*60)
    print("🤖 AI 首席分析师分析中...")
    print("="*60 + "\n")
    
    stock = results['stock']
    market = results.get('market', 'a')
    findings = results.get('findings', {})
    
    # 整理数据
    company_info = _format_company_info(stock, market, findings)
    financial_data = _format_financial_data(findings)
    industry_data = _format_industry_data(findings)
    governance_data = _format_governance_data(findings)
    
    # 获取行业信息
    industry = findings.get('industry', {}).get('industry', '综合')
    
    # 生成提示词
    prompt = get_analyst_prompt(
        company_info,
        financial_data,
        industry_data,
        governance_data,
        industry
    )
    
    print(f"📊 分析股票: {stock}")
    print(f"🏢 所属行业: {industry}")
    print(f"⏳ 正在调用 DeepSeek V4 Flash 进行深度分析...\n")
    
    # 调用 LLM
    start_time = time.time()
    analysis = call_llm(prompt)
    elapsed = time.time() - start_time
    
    if not analysis:
        print("❌ AI 分析失败，返回基础报告")
        return None
    
    print(f"✅ AI 分析完成，耗时 {elapsed:.1f} 秒")
    
    # 生成报告
    report = f"""# {stock} 首席分析师深度报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**股票代码**: {stock}
**分析引擎**: 商汤 DeepSeek V4 Flash
**分析耗时**: {elapsed:.1f} 秒

---

{analysis}

---

## 数据来源

本报告基于以下数据源生成：

- 公司基本信息
- 财务数据（多年趋势、盈利能力、现金流）
- 行业竞争格局
- 公司治理结构
- 风险评估

**免责声明**: 本报告仅供参考，不构成投资建议。投资者应自行判断投资风险。
"""
    
    # 保存报告
    report_path = f"{out_dir}/analyst_report.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n✅ 首席分析师报告已保存: {report_path}")
    return report_path


def _format_company_info(stock, market, findings):
    """格式化公司基本信息"""
    lines = []
    lines.append(f"股票代码: {stock}")
    lines.append(f"市场: {market}")
    
    # 基本信息
    if 'structure' in findings:
        structure = findings['structure']
        if isinstance(structure, dict):
            if 'company_name' in structure:
                lines.append(f"公司名称: {structure['company_name']}")
            if 'actual_controller' in structure:
                lines.append(f"实际控制人: {structure['actual_controller']}")
    
    # 行情数据
    if 'quote' in findings:
        quote = findings['quote']
        if isinstance(quote, dict):
            price = quote.get('price', 'N/A')
            lines.append(f"最新价格: {price}")
            change = quote.get('change_pct', 'N/A')
            lines.append(f"涨跌幅: {change}%")
    
    return '\n'.join(lines)


def _format_financial_data(findings):
    """格式化财务数据"""
    lines = []
    
    # 多年趋势
    if 'multi_year_trend' in findings:
        trend = findings['multi_year_trend']
        if isinstance(trend, dict):
            lines.append("### 多年财务趋势")
            if 'revenue_cagr' in trend:
                lines.append(f"营收CAGR: {trend['revenue_cagr']}%")
            if 'profit_cagr' in trend:
                lines.append(f"利润CAGR: {trend['profit_cagr']}%")
            if 'gross_margin' in trend:
                lines.append(f"毛利率: {trend['gross_margin']}%")
            if 'roe' in trend:
                lines.append(f"ROE: {trend['roe']}%")
            lines.append("")
    
    # 估值
    if 'valuation' in findings:
        val = findings['valuation']
        if isinstance(val, dict):
            lines.append("### 估值指标")
            if 'pe_ttm' in val:
                lines.append(f"PE(TTM): {val['pe_ttm']}")
            if 'pe_historical' in val:
                lines.append(f"历史PE分位: {val['pe_historical']}%")
            if 'pb' in val:
                lines.append(f"PB: {val['pb']}")
            lines.append("")
    
    return '\n'.join(lines) if lines else "暂无财务数据"


def _format_industry_data(findings):
    """格式化行业数据"""
    lines = []
    
    if 'industry' in findings:
        industry = findings['industry']
        if isinstance(industry, dict):
            if 'industry' in industry:
                lines.append(f"行业分类: {industry['industry']}")
            if 'peers' in industry:
                lines.append(f"可比公司数: {len(industry['peers'])}")
            lines.append("")
    
    if 'peer_compare' in findings:
        peer = findings['peer_compare']
        if isinstance(peer, dict):
            lines.append("### 同业对比")
            for key, value in peer.items():
                if isinstance(value, (int, float)):
                    lines.append(f"{key}: {value}")
            lines.append("")
    
    return '\n'.join(lines) if lines else "暂无行业数据"


def _format_governance_data(findings):
    """格式化治理和风险数据"""
    lines = []
    
    # 治理
    if 'governance' in findings:
        gov = findings['governance']
        if isinstance(gov, dict):
            lines.append("### 公司治理")
            if 'cr1' in gov:
                lines.append(f"第一大股东持股: {gov['cr1']}%")
            if ' pledge_ratio' in gov:
                lines.append(f"质押比例: {gov['pledge_ratio']}%")
            if 'score' in gov:
                lines.append(f"治理评分: {gov['score']}/100")
            lines.append("")
    
    # 风险
    if 'risk' in findings:
        risk = findings['risk']
        if isinstance(risk, dict):
            lines.append("### 风险评级")
            if 'overall_score' in risk:
                lines.append(f"综合风险评分: {risk['overall_score']}/100")
            if 'risk_level' in risk:
                lines.append(f"风险等级: {risk['risk_level']}")
            lines.append("")
    
    return '\n'.join(lines) if lines else "暂无治理和风险数据"


if __name__ == "__main__":
    # 测试代码
    print("🤖 AI 分析师模块测试")
    test_results = {
        'stock': '002180',
        'market': 'a',
        'findings': {}
    }
    
    print("⚠️ 请通过 analyze.py --ai-report 选项调用此模块")
