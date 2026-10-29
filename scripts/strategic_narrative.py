# -*- coding: utf-8 -*-
"""
strategic_narrative.py - 战略叙事生成模块

用途：整合多维度数据，自动生成公司战略叙事：
  - 公司愿景与定位
  - 核心竞争优势
  - 战略执行路径
  - 风险与挑战
  - 未来展望

数据来源：
  - value_chain: 价值链分析结果
  - industry: 行业竞争格局
  - financials: 财务报表分析
  - governance: 公司治理
  - related_deals: 收并购活动
  - announcements: 重大公告

使用方式：
  from strategic_narrative import StrategicNarrativeGenerator, fetch_strategic_narrative

  # 方式1：直接调用
  result = fetch_strategic_narrative('002180', 'a', data_dir)

  # 方式2：使用生成器
  generator = StrategicNarrativeGenerator(all_data)
  narrative = generator.generate_narrative()
  print(narrative['investment_thesis'])
"""

import sys
import json
import os
from typing import Dict, List, Optional, Any

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class StrategicNarrativeGenerator:
    """战略叙事生成器"""

    def __init__(self, all_data: dict = None, stock_code: str = '', market: str = 'a'):
        """初始化生成器
        Args:
            all_data: 所有维度数据的汇总
            stock_code: 股票代码
            market: 市场（a/hk/us）
        """
        self.data = all_data or {}
        self.stock_code = stock_code
        self.market = market
        self.narrative = {}

    def generate_narrative(self) -> dict:
        """生成完整战略叙事"""
        vision = self._extract_vision()
        positioning = self._extract_positioning()
        advantages = self._extract_advantages()
        strategy_path = self._extract_strategy_path()
        execution_status = self._assess_execution()
        risks = self._extract_risks()
        outlook = self._generate_outlook()
        thesis = self._generate_investment_thesis()

        self.narrative = {
            'vision': vision,
            'positioning': positioning,
            'core_advantages': advantages,
            'strategy_path': strategy_path,
            'execution_status': execution_status,
            'risks_challenges': risks,
            'outlook': outlook,
            'investment_thesis': thesis,
            'summary': self._generate_summary()
        }

        return self.narrative

    def _extract_vision(self) -> str:
        """提取公司愿景

        🔴 2026-10-20 修复「模板套话充数」：
          旧版硬编码兜底 `"致力于成为行业领先的综合性企业集团"`，
          行业名取不到时就把它当公司愿景输出 —— 实测 002180（打印机/芯片）
          被写成「综合性企业集团」，与真实业务完全无关。
          现改为：① 优先用年报 MD&A「公司未来发展的展望」原文；
                  ② 其次行业口径；③ 都取不到 → 明确标「未披露」，不给套话。
        """
        # ① 年报 MD&A 展望原文（最权威的公司自述）
        ars = self.data.get('annual_report_sections') or {}
        fp = ''
        if isinstance(ars, dict):
            sec = ars.get('mdaa_sections') or {}
            if isinstance(sec, dict):
                fp = sec.get('future_plan') or ''
            if not fp:
                for k in ('future_plan', 'development_outlook'):
                    v = ars.get(k)
                    if isinstance(v, dict):
                        fp = v.get('content') or ''
                    elif isinstance(v, str):
                        fp = v
                    if fp:
                        break
        if fp:
            # 取第一句有信息量的战略陈述
            import re as _re
            for sent in _re.split(r'[。；\n]', fp):
                s = sent.strip().lstrip('展望未来，').strip()
                if len(s) >= 15 and _re.search(r'(将|致力|聚焦|坚持|打造|推进|布局)', s):
                    return s + '。'

        # ② 行业口径（兼容多种字段名）
        industry = self.data.get('industry') or {}
        iname = (industry.get('industry_name') or industry.get('name')
                 or (industry.get('industry_class') or {}).get('csrc_industry')
                 or '')
        if iname:
            return f"深耕{iname}领域（行业口径推断，非公司自述愿景）"

        # ③ 诚实缺失
        return '年报未披露明确愿景表述'

    def _extract_positioning(self) -> str:
        """提取市场定位

        2026-10-20：同 vision，去掉「中型综合性企业，处于行业中上游位置」套话兜底。
        """
        positioning = None

        industry = self.data.get('industry') or {}
        # 兼容三种落点：industry_name / name / industry_class.csrc_industry
        # （实测 002180 前两者均为 None，只有 csrc_industry 有值）
        _ic = industry.get('industry_class') or {}
        iname = (industry.get('industry_name') or industry.get('name')
                 or _ic.get('csrc_industry') or _ic.get('sw_industry')
                 or _ic.get('industry') or '')
        pe = self.data.get('peer_compare') or {}
        rank_txt = ''
        if isinstance(pe, dict):
            concl = str(pe.get('conclusion') or '')
            if concl:
                import re as _re
                m = _re.search(r'超越(\d+)%', concl)
                if m:
                    rank_txt = f"，关键指标超越 {m.group(1)}% 同业"

        if iname:
            positioning = f"{iname}行业{rank_txt}" if rank_txt else f"{iname}行业"
        if not positioning:
            return '未取得行业归类，市场定位无法判定'
        return positioning

    def _extract_advantages(self) -> List[str]:
        """提取核心竞争优势"""
        advantages = []

        # 从价值链分析提取
        value_chain = self.data.get('value_chain', {})
        if value_chain:
            strengths = value_chain.get('strengths', [])
            for s in strengths:
                if '优秀' in s or '强' in s or '稳固' in s:
                    advantages.append(s)

            up = value_chain.get('upstream', {})
            if up.get('supplier_risk') == '低':
                advantages.append('供应链稳定，供应商风险可控')
            if up.get('bargaining_power') == '强':
                advantages.append('对上游供应商议价能力强')

            mid = value_chain.get('midstream', {})
            if mid.get('production_efficiency') == '高':
                advantages.append('生产效率高，运营能力强')
            if mid.get('rd_intensity', 0) > 5:
                advantages.append(f'研发投入充足（{mid["rd_intensity"]:.1f}%），技术壁垒较高')

            down = value_chain.get('downstream', {})
            if down.get('channel_control') == '强':
                advantages.append('渠道掌控力强，销售网络完善')
            if down.get('brand_premium', 0) > 30:
                advantages.append(f'品牌溢价能力强（毛利率{down["brand_premium"]:.1f}%）')

        # 从财务数据提取
        financials = self.data.get('financials', {}) or self.data.get('financial', {})
        if financials:
            profit_margin = financials.get('profit_margin') or financials.get('XSMLL')
            if profit_margin:
                try:
                    pm = float(profit_margin)
                    if pm > 30:
                        advantages.append('盈利能力较强，毛利率水平较高')
                except ValueError:
                    pass

        # 从行业分析提取
        industry = self.data.get('industry', {})
        if industry:
            competitive_edges = industry.get('competitive_edges', [])
            if isinstance(competitive_edges, list):
                advantages.extend(competitive_edges[:3])

        # 从收并购分析提取
        ma_deep = self.data.get('ma_deep', {})
        if ma_deep and ma_deep.get('ma_score', 0) > 70:
            advantages.append('收并购管理能力优秀，资本运作经验丰富')

        return list(set(advantages))[:5]

    def _extract_strategy_path(self) -> str:
        """提取战略执行路径"""
        path = "稳健发展，深耕主业"

        # 从收并购分析提取战略方向
        ma_deep = self.data.get('ma_deep', {})
        if ma_deep:
            deals = ma_deep.get('deals', [])
            if deals:
                deal_types = set(d.get('type') for d in deals)
                if '资产收购' in deal_types:
                    path = "通过收购兼并实现规模扩张和产业链延伸"
                if '资产分拆' in deal_types or '资产出售' in deal_types:
                    if '资产收购' in deal_types:
                        path = "通过资产整合优化业务结构，聚焦核心主业"
                    else:
                        path = "剥离非核心资产，优化资产结构"
                if len(deals) > 3:
                    path += "，资本运作较为活跃"

        # 从年报或公告提取战略表述
        announcements = self.data.get('announcements', {})
        critical_anns = announcements.get('critical_announcements', [])
        for ann in critical_anns:
            title = ann.get('title', '')
            if '战略' in title:
                ai_analysis = ann.get('ai_analysis', {})
                if ai_analysis:
                    path = ai_analysis.get('summary', path)[:300]
                    break

        return path

    def _assess_execution(self) -> str:
        """评估战略执行状态"""
        execution_status = "执行中"

        # 从财务趋势评估
        financial_metrics = self.data.get('financial_metrics', {})
        if financial_metrics:
            records = financial_metrics.get('records', [])
            if len(records) >= 2:
                recent = records[0]
                previous = records[1]

                revenue_recent = recent.get('TOTAL_OPERATE_INCOME', 0)
                revenue_prev = previous.get('TOTAL_OPERATE_INCOME', 0)

                profit_recent = recent.get('PARENT_NETPROFIT', 0)
                profit_prev = previous.get('PARENT_NETPROFIT', 0)

                if revenue_recent > 0 and revenue_prev > 0:
                    revenue_growth = (revenue_recent - revenue_prev) / revenue_prev * 100
                    if revenue_growth > 10:
                        execution_status = "执行良好，营收增长稳健"
                    elif revenue_growth < -10:
                        execution_status = "执行面临挑战，营收下滑"

                if profit_recent > 0 and profit_prev < 0:
                    execution_status = "业绩改善，扭亏为盈"
                elif profit_recent < 0 and profit_prev > 0:
                    execution_status = "业绩承压，出现亏损"

        return execution_status

    def _extract_risks(self) -> List[str]:
        """提取风险与挑战"""
        risks = []

        # 从风险分析提取
        risk_analysis = self.data.get('risk', {})
        if risk_analysis:
            risk_items = risk_analysis.get('risk_items', [])
            if isinstance(risk_items, list):
                for item in risk_items[:5]:
                    if isinstance(item, dict):
                        risks.append(item.get('description', ''))
                    elif isinstance(item, str):
                        risks.append(item)

        # 从价值链分析提取
        value_chain = self.data.get('value_chain', {})
        if value_chain:
            weaknesses = value_chain.get('weaknesses', [])
            risks.extend(weaknesses[:3])

            mid = value_chain.get('midstream', {})
            if mid.get('production_efficiency') == '低':
                risks.append('产能利用率偏低，存在产能过剩风险')
            if mid.get('rd_intensity', 0) < 2:
                risks.append('研发投入不足，技术创新能力待提升')

        # 从收并购分析提取
        ma_deep = self.data.get('ma_deep', {})
        if ma_deep:
            risk_info = ma_deep.get('risk_analysis', {})
            risk_level = risk_info.get('overall_risk', '')
            if risk_level == '高':
                risks.append('收并购相关风险较高，需密切关注')
            risk_factors = risk_info.get('risk_factors', [])
            risks.extend(risk_factors[:3])

        # 从公告提取
        announcements = self.data.get('announcements', {})
        critical_anns = announcements.get('critical_announcements', [])
        for ann in critical_anns:
            if '诉讼' in ann.get('title', '') or '仲裁' in ann.get('title', ''):
                risks.append('存在重大诉讼或仲裁案件，可能影响公司经营')
                break

        return list(set(risks))[:6]

    def _generate_outlook(self) -> str:
        """生成未来展望"""
        outlook = "展望未来，公司将继续专注主业，寻求稳健发展机会。"

        # 综合各维度信息
        value_chain = self.data.get('value_chain', {})
        ma_deep = self.data.get('ma_deep', {})
        industry = self.data.get('industry', {})

        if value_chain:
            score = value_chain.get('value_chain_score', 0)
            if score >= 70:
                outlook = "凭借较强的价值链竞争力，公司有望在行业竞争中占据优势地位，未来发展值得期待。"
            elif score >= 50:
                outlook = "公司价值链竞争力处于中等水平，需持续优化各环节运营效率以提升整体竞争力。"
            else:
                outlook = "公司价值链竞争力有待提升，需在供应链管理、生产效率、渠道建设等方面加强改进。"

        if ma_deep and ma_deep.get('ma_score', 0) > 70:
            outlook += " 公司收并购管理能力优秀，未来可能继续通过资本运作实现战略布局。"

        if industry:
            # 2026-10-20 修复拼接残句：industry_name/name 实测均为 None，
            # 旧版 f" 在{industry_name}领域，" → 输出「在领域，」（缺词）。
            # 现兼容 csrc_industry，且取不到时**不拼该分句**。
            _ic = industry.get('industry_class') or {}
            industry_name = (industry.get('industry_name') or industry.get('name')
                             or _ic.get('csrc_industry') or '')
            trend = industry.get('industry_trend', '')
            if industry_name:
                outlook += f"\n\n在{industry_name}领域，"
                if trend:
                    outlook += f"{trend}，"
                outlook += "公司将面临新的机遇与挑战。"
            elif trend:
                outlook += f"\n\n{trend}，公司将面临新的机遇与挑战。"

        return outlook

    def _generate_investment_thesis(self) -> str:
        return "详见「投资逻辑」章节（基于全维度数据的深度分析）。"

    def _generate_summary(self) -> str:
        """生成一句话总结"""
        vision = self.narrative.get('vision', '')
        positioning = self.narrative.get('positioning', '')
        advantages = self.narrative.get('core_advantages', [])
        risks = self.narrative.get('risks_challenges', [])

        summary = f"{vision}，{positioning}。"

        if advantages:
            summary += f"核心优势包括：{advantages[0]}。"
        if risks:
            summary += f"主要风险：{risks[0]}。"

        return summary

    def format_report_section(self) -> str:
        """生成Markdown格式的报告章节"""
        narrative = self.narrative

        section = f"""
## 26. 战略叙事

### 26.1 公司愿景与定位
**愿景**：{narrative['vision']}

**市场定位**：{narrative['positioning']}

### 26.2 核心竞争优势
"""

        if narrative['core_advantages']:
            for i, advantage in enumerate(narrative['core_advantages'], 1):
                section += f"{i}. {advantage}\n"
        else:
            section += "- 暂无明确竞争优势\n"

        section += f"""

### 26.3 战略执行路径
{narrative['strategy_path']}

**执行状态**：{narrative['execution_status']}

### 26.4 风险与挑战
"""

        if narrative['risks_challenges']:
            for i, risk in enumerate(narrative['risks_challenges'], 1):
                section += f"{i}. {risk}\n"
        else:
            section += "- 暂无重大风险\n"

        section += f"""

### 26.5 未来展望
{narrative['outlook']}

### 26.6 投资逻辑总结
{narrative['investment_thesis']}

---

**总结**：{narrative['summary']}
"""
        return section


def fetch_strategic_narrative(stock_code: str, market: str = 'a',
                             data_dir: str = None) -> dict:
    """战略叙事生成主入口"""
    result = {
        'stock_code': stock_code,
        'market': market,
        'success': False,
        'error': None,
        'data': {}
    }

    try:
        all_data = {}

        if data_dir and os.path.exists(data_dir):
            # 加载各维度数据
            dimensions = ['value_chain', 'ma_deep', 'financial_metrics', 'results']

            for dim in dimensions:
                file_path = os.path.join(data_dir, f'{dim}.json')
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        try:
                            data = json.load(f)
                            if dim == 'results':
                                all_data.update(data.get('findings', {}))
                            else:
                                all_data[dim] = data
                        except json.JSONDecodeError:
                            pass

        generator = StrategicNarrativeGenerator(
            all_data=all_data,
            stock_code=stock_code,
            market=market
        )

        narrative = generator.generate_narrative()

        result['success'] = True
        result['data'] = narrative

        # 保存结果
        if data_dir:
            output_file = os.path.join(data_dir, 'strategic_narrative.json')
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(narrative, f, ensure_ascii=False, indent=2)

    except Exception as e:
        result['error'] = str(e)

    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2:
        stock = sys.argv[1]
        market = sys.argv[2] if len(sys.argv) > 2 else 'a'
        data_dir = sys.argv[3] if len(sys.argv) > 3 else None

        result = fetch_strategic_narrative(stock, market, data_dir)

        if result['success']:
            print(f"✅ 战略叙事生成完成")
            print(f"愿景：{result['data']['vision']}")
            print(f"投资逻辑：{result['data']['investment_thesis']}")
        else:
            print(f"❌ 生成失败: {result['error']}")
    else:
        print("用法: python strategic_narrative.py <股票代码> [市场] [数据 目录]")
        print("示例: python strategic_narrative.py 002180 a output/002180_20260530/data")


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    generator = StrategicNarrativeGenerator(
        all_data={},
        stock_code='',
        market='a'
    )
    generator.narrative = data
    md = generator.format_report_section()
    return [md, ""]
