# -*- coding: utf-8 -*-
"""
AI综合报告生成器
汇总27维度数据，通过DeepSeek生成首席分析师风格完整报告
"""
import json
import time
import sys
from datetime import datetime
from openai import OpenAI

sys.stdout.reconfigure(encoding='utf-8')

from scripts.llm_config import LLM_CONFIG

ANALYST_SYSTEM_PROMPT = """你是一位顶级券商首席分析师，拥有20年A股研究经验。你的分析风格：
1. **专业严谨**：基于数据说话，逻辑清晰
2. **深度洞察**：不浮于表面，挖掘本质
3. **投资导向**：给出明确的投资建议和风险提示
4. **简洁有力**：避免废话，每句话都有价值

请按照以下结构输出报告：
1. **投资要点**（3-5条核心观点，每条不超过30字）
2. **公司概况**（业务模式、行业地位、核心竞争力）
3. **财务分析**（盈利能力、成长性、现金流质量、财务风险）
4. **公告解读**（重要公告深度分析，提取关键信息和影响）
5. **行业分析**（竞争格局、公司定位、行业趋势）
6. **治理与风险**（股权结构、治理问题、主要风险因素）
7. **投资建议**（评级：强烈推荐/推荐/中性/回避，目标价区间，理由）

注意：
- 使用Markdown格式输出
- 数据要具体，不要模糊表述
- 风险提示要具体，不要泛泛而谈
- 投资建议要有理有据"""


def summarize_for_ai(all_data, max_length=15000):
    """
    汇总27维度数据，构建AI分析输入
    
    Args:
        all_data: 全部分析结果
        max_length: 最大文本长度（控制token）
    
    Returns:
        str: 结构化的数据摘要
    """
    sections = []
    findings = all_data.get('findings', {})
    
    # 1. 公司基本信息
    company_section = _format_company_info(all_data)
    if company_section:
        sections.append(f"## 公司基本信息\n{company_section}")
    
    # 2. 财务分析
    financial_section = _format_financial_data(findings)
    if financial_section:
        sections.append(f"## 财务分析\n{financial_section}")
    
    # 3. 公告分析
    announcement_section = _format_announcement_data(findings)
    if announcement_section:
        sections.append(f"## 公告分析\n{announcement_section}")
    
    # 4. 行业分析
    industry_section = _format_industry_data(findings)
    if industry_section:
        sections.append(f"## 行业分析\n{industry_section}")
    
    # 5. 治理分析
    governance_section = _format_governance_data(findings)
    if governance_section:
        sections.append(f"## 公司治理\n{governance_section}")
    
    # 6. 风险评估
    risk_section = _format_risk_data(findings)
    if risk_section:
        sections.append(f"## 风险评估\n{risk_section}")
    
    # 合并并控制长度
    full_text = "\n\n".join(sections)
    if len(full_text) > max_length:
        full_text = full_text[:max_length] + "\n\n[数据已截断，完整数据请查看原始报告]"
    
    return full_text


def _format_company_info(all_data):
    """格式化公司基本信息"""
    lines = []
    
    stock = all_data.get('stock', '')
    market = all_data.get('market', 'a')
    lines.append(f"股票代码: {stock}")
    lines.append(f"市场: {'A股' if market == 'a' else ('港股' if market == 'hk' else '美股')}")
    
    findings = all_data.get('findings', {})
    
    # 行情数据
    quote = findings.get('quote', {})
    if quote and isinstance(quote, dict):
        if 'price' in quote:
            lines.append(f"最新价格: {quote['price']}")
        if 'change_pct' in quote:
            lines.append(f"涨跌幅: {quote['change_pct']}%")
        if 'volume' in quote:
            lines.append(f"成交量: {quote['volume']}")
    
    # 行业信息
    industry = findings.get('industry', {})
    if industry and isinstance(industry, dict):
        if 'industry' in industry:
            lines.append(f"所属行业: {industry['industry']}")
        if 'sector' in industry:
            lines.append(f"所属板块: {industry['sector']}")
    
    # 股权结构
    structure = findings.get('structure', {})
    if structure and isinstance(structure, dict):
        if 'actual_controller' in structure:
            lines.append(f"实际控制人: {structure['actual_controller']}")
        if 'controller_ratio' in structure:
            lines.append(f"控制权比例: {structure['controller_ratio']}%")
    
    return '\n'.join(lines) if len(lines) > 3 else ''


def _format_financial_data(findings):
    """格式化财务数据"""
    lines = []
    
    # 财务报表
    financial = findings.get('financial', {})
    if financial and isinstance(financial, dict):
        if 'revenue' in financial:
            lines.append(f"营业收入: {financial['revenue']}")
        if 'net_profit' in financial:
            lines.append(f"归母净利润: {financial['net_profit']}")
        if 'gross_margin' in financial:
            lines.append(f"毛利率: {financial['gross_margin']}%")
        if 'roe' in financial:
            lines.append(f"ROE: {financial['roe']}%")
        if 'debt_ratio' in financial:
            lines.append(f"资产负债率: {financial['debt_ratio']}%")
    
    # 多年趋势
    trend = findings.get('multi_year_trend', {})
    if trend and isinstance(trend, dict):
        lines.append("\n### 多年趋势")
        if 'revenue_cagr' in trend:
            lines.append(f"营收CAGR: {trend['revenue_cagr']}%")
        if 'profit_cagr' in trend:
            lines.append(f"利润CAGR: {trend['profit_cagr']}%")
        if 'gross_margin_trend' in trend:
            lines.append(f"毛利率趋势: {trend['gross_margin_trend']}")
        if 'roe_trend' in trend:
            lines.append(f"ROE趋势: {trend['roe_trend']}")
    
    # 估值
    valuation = findings.get('valuation', {})
    if valuation and isinstance(valuation, dict):
        lines.append("\n### 估值指标")
        if 'pe_ttm' in valuation:
            lines.append(f"PE(TTM): {valuation['pe_ttm']}")
        if 'pb' in valuation:
            lines.append(f"PB: {valuation['pb']}")
        if 'ps' in valuation:
            lines.append(f"PS: {valuation['ps']}")
        if 'market_cap' in valuation:
            lines.append(f"总市值: {valuation['market_cap']}")
    
    return '\n'.join(lines) if lines else ''


def _format_announcement_data(findings):
    """格式化公告分析数据"""
    lines = []
    
    announcements = findings.get('announcements', {})
    if not announcements:
        return ''
    
    # 公告统计
    stats = announcements.get('importance_stats', {})
    if stats:
        lines.append(f"公告总数: {announcements.get('count', 0)}")
        lines.append(f"重大公告(CRITICAL): {stats.get('critical', 0)}")
        lines.append(f"重要公告(MAJOR): {stats.get('major', 0)}")
        lines.append(f"常规公告(ROUTINE): {stats.get('routine', 0)}")
    
    # CRITICAL公告
    critical = announcements.get('critical_announcements', [])
    if critical:
        lines.append("\n### 重大公告")
        for ann in critical[:5]:
            title = ann.get('title', '')[:60]
            date = ann.get('date', '')[:10]
            tag = ann.get('importance_tag', '')
            lines.append(f"- [{date}] {title} ({tag})")
            
            # AI分析结果
            ai_analysis = ann.get('ai_analysis', {})
            if ai_analysis:
                if 'summary' in ai_analysis:
                    lines.append(f"  AI摘要: {ai_analysis['summary']}")
                if 'impact_analysis' in ai_analysis:
                    lines.append(f"  影响分析: {ai_analysis['impact_analysis']}")
            
            # 深度分析结果
            deep = ann.get('deep_analysis', {})
            if deep:
                if 'nature' in deep:
                    lines.append(f"  性质: {deep['nature']}")
                if 'impact' in deep:
                    lines.append(f"  影响: {deep['impact']}")
                if 'facts' in deep and deep['facts']:
                    lines.append(f"  关键事实: {', '.join(deep['facts'][:3])}")
    
    # MAJOR公告
    major = announcements.get('major_announcements', [])
    if major:
        lines.append("\n### 重要公告")
        for ann in major[:10]:
            title = ann.get('title', '')[:50]
            date = ann.get('date', '')[:10]
            tag = ann.get('importance_tag', '')
            lines.append(f"- [{date}] {title} ({tag})")
    
    # 风险信号
    risk_signals = announcements.get('risk_signals', [])
    if risk_signals:
        lines.append("\n### 公告风险信号")
        for signal in risk_signals[:5]:
            lines.append(f"- ⚠️ {signal}")
    
    return '\n'.join(lines) if lines else ''


def _format_industry_data(findings):
    """格式化行业分析数据"""
    lines = []
    
    # 行业信息
    industry = findings.get('industry', {})
    if industry and isinstance(industry, dict):
        if 'industry' in industry:
            lines.append(f"行业分类: {industry['industry']}")
        if 'peers' in industry:
            peers = industry['peers']
            if isinstance(peers, list):
                lines.append(f"可比公司数: {len(peers)}")
    
    # 同业对比
    peer_compare = findings.get('peer_compare', {})
    if peer_compare and isinstance(peer_compare, dict):
        lines.append("\n### 同业对比")
        
        target = peer_compare.get('target', {})
        stats = peer_compare.get('stats', {})
        rank = peer_compare.get('rank', {})
        
        # 营收对比
        if 'revenue' in rank:
            lines.append(f"营收行业分位: {rank['revenue']}%")
        if 'roe' in rank:
            lines.append(f"ROE行业分位: {rank['roe']}%")
        if 'gross_margin' in rank:
            lines.append(f"毛利率行业分位: {rank['gross_margin']}%")
        if 'revenue_growth' in rank:
            lines.append(f"营收增速行业分位: {rank['revenue_growth']}%")
        
        # 同业公司
        peers = peer_compare.get('peers', [])
        if peers:
            lines.append(f"\n可比公司: {len(peers)}家")
            for p in peers[:5]:
                name = p.get('name', '')
                roe = p.get('roe', '')
                gm = p.get('gross_margin', '')
                lines.append(f"- {name}: ROE {roe}%, 毛利率 {gm}%")
    
    return '\n'.join(lines) if lines else ''


def _format_governance_data(findings):
    """格式化治理数据"""
    lines = []
    
    governance = findings.get('governance', {})
    if not governance:
        return ''
    
    if isinstance(governance, dict):
        if 'score' in governance:
            lines.append(f"治理评分: {governance['score']}/100")
        if 'cr1' in governance:
            lines.append(f"第一大股东持股: {governance['cr1']}%")
        if 'cr5' in governance:
            lines.append(f"前五大股东持股: {governance['cr5']}%")
        if 'pledge_ratio' in governance:
            lines.append(f"质押比例: {governance['pledge_ratio']}%")
    
    # 高管动态
    executives = findings.get('executives', {})
    if executives and isinstance(executives, dict):
        changes = executives.get('changes', [])
        if changes:
            lines.append(f"\n高管变动: {len(changes)}条")
            for c in changes[:5]:
                lines.append(f"- {c}")
    
    return '\n'.join(lines) if lines else ''


def _format_risk_data(findings):
    """格式化风险数据"""
    lines = []
    
    risk = findings.get('risk', {})
    if not risk:
        return ''
    
    if isinstance(risk, dict):
        if 'overall_score' in risk:
            lines.append(f"综合风险评分: {risk['overall_score']}/100")
        if 'risk_level' in risk:
            lines.append(f"风险等级: {risk['risk_level']}")
        if 'risk_factors' in risk:
            factors = risk['risk_factors']
            if isinstance(factors, list):
                lines.append("\n主要风险因素:")
                for f in factors[:10]:
                    lines.append(f"- {f}")
    
    # 交叉验证隐情
    cross = findings.get('cross_validation', {})
    if cross and isinstance(cross, dict):
        hidden = cross.get('hidden_findings', [])
        if hidden:
            lines.append("\n交叉验证发现:")
            for h in hidden[:5]:
                lines.append(f"- 🔍 {h}")
    
    return '\n'.join(lines) if lines else ''


def generate_comprehensive_report(all_data, output_dir=None):
    """
    生成AI综合分析报告
    
    Args:
        all_data: 全部分析结果
        output_dir: 输出目录
    
    Returns:
        str: AI生成的报告内容
    """
    print("\n" + "="*60)
    print("🤖 AI综合报告生成中...")
    print("="*60 + "\n")
    
    stock = all_data.get('stock', 'Unknown')
    print(f"📊 分析股票: {stock}")
    
    # 汇总数据
    data_summary = summarize_for_ai(all_data)
    print(f"📝 数据汇总完成，长度: {len(data_summary)} 字符")
    
    # 构建Prompt
    prompt = f"""请基于以下数据，生成一份专业的投资分析报告：

{data_summary}

---

请按照分析师风格，给出完整的投资分析报告。重点关注：
1. 公司的核心竞争力和行业地位
2. 财务健康度和成长性
3. 重要公告的影响和风险
4. 明确的投资建议和风险提示"""
    
    # 调用AI
    print("⏳ 正在调用 DeepSeek V4 Flash 进行深度分析...")
    start_time = time.time()
    
    try:
        client = OpenAI(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
        )
        
        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=[
                {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=8000,
            stream=False
        )
        
        analysis = response.choices[0].message.content
        elapsed = time.time() - start_time
        print(f"✅ AI分析完成，耗时 {elapsed:.1f} 秒")
        
    except Exception as e:
        print(f"❌ AI分析失败: {e}")
        return None
    
    # 生成完整报告
    report = f"""# {stock} AI首席分析师深度报告

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**股票代码**: {stock}  
**分析引擎**: 商汤 DeepSeek V4 Flash  
**分析耗时**: {elapsed:.1f} 秒  

---

{analysis}

---

## 📋 数据来源

本报告基于以下数据源生成：

- 公司基本信息（东方财富API）
- 财务数据（多年趋势、盈利能力、现金流）
- 公告分析（东方财富公告API + AI深度解读）
- 行业竞争格局（证监会行业分类 + 同业对比）
- 公司治理（股权结构、高管动态）
- 风险评估（多维度交叉验证）

---

**免责声明**: 本报告由AI自动生成，仅供参考，不构成投资建议。投资者应自行判断投资风险，独立做出投资决策。
"""
    
    # 保存报告
    if output_dir:
        import os
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, 'ai_analyst_report.md')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n✅ AI报告已保存: {report_path}")
    
    return report


def analyze_announcements_with_ai(announcements, max_analyze=20):
    """
    公告AI深度分析
    
    Args:
        announcements: 公告列表
        max_analyze: 最多分析数量
    
    Returns:
        list: 带AI分析结果的公告列表
    """
    from scripts.ai_announcement_analyzer import AIAnnouncementAnalyzer
    
    analyzer = AIAnnouncementAnalyzer()
    results = []
    
    # 优先分析CRITICAL/MAJOR级别
    sorted_anns = sorted(
        announcements,
        key=lambda x: {'critical': 0, 'major': 1, 'routine': 2}.get(x.get('importance', 'routine'), 2)
    )
    
    analyzed = 0
    for ann in sorted_anns:
        if analyzed >= max_analyze:
            break
        
        # 只分析CRITICAL和MAJOR
        if ann.get('importance') not in ['critical', 'major']:
            continue
        
        title = ann.get('title', '')
        
        # 获取公告内容
        content = ''
        extracted = ann.get('extracted_content', {})
        if isinstance(extracted, dict):
            content = extracted.get('full_text_preview', '') or extracted.get('summary', '')
        
        if not content:
            content = ann.get('content', '')
        
        # 调用AI分析
        try:
            print(f"  [AI分析] {title[:40]}...")
            analysis = analyzer.analyze_announcement(title, content[:3000])
            ann['ai_analysis'] = analysis
            analyzed += 1
            time.sleep(0.5)  # 控制频率
        except Exception as e:
            ann['ai_analysis'] = {'error': str(e)}
        
        results.append(ann)
    
    print(f"  ✅ AI公告分析完成，共分析 {analyzed} 条")
    return results


if __name__ == "__main__":
    print("🤖 AI综合报告生成器")
    print("请通过 analyze.py --ai-report 选项调用此模块")
