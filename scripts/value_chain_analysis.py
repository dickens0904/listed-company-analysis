# -*- coding: utf-8 -*-
"""
value_chain_analysis.py - 价值链分析模块（优化版）

用途：从年报、业务概述、产销量等章节提取公司价值链定位，
      分析上游供应商、中游生产制造、下游客户端的完整价值链。

数据来源：
  - 年报章节（annual_extract.py）：供应商、客户、产能
  - 财务报表（financials.py）：成本结构、毛利率
  - 公告（announcements.py）：销售渠道、合作伙伴

使用方式：
  from value_chain_analysis import ValueChainAnalyzer, fetch_value_chain
  
  # 方式1：直接调用
  result = fetch_value_chain('002180', 'a', data_dir)
  
  # 方式2：使用分析器
  analyzer = ValueChainAnalyzer(annual_sections, financials)
  report = analyzer.analyze()
  print(report['summary'])
  print(f"评分：{report['value_chain_score']}/100")
"""

import sys
import re
import json
import os
from typing import Dict, List, Optional, Any

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class ValueChainAnalyzer:
    """价值链分析器（优化版）"""

    def __init__(self, annual_sections: dict = None, financials: dict = None,
                 stock_code: str = '', market: str = 'a', financial_metrics: dict = None):
        """初始化分析器
        Args:
            annual_sections: 年报章节提取结果
            financials: 财务数据
            stock_code: 股票代码
            market: 市场（a/hk/us）
            financial_metrics: 财务指标（来自 financial_metrics.json）
        """
        self.sections = annual_sections or {}
        self.financials = financials or {}
        self.financial_metrics = financial_metrics or {}
        self.stock_code = stock_code
        self.market = market
        self.upstream = {}
        self.midstream = {}
        self.downstream = {}
        self.value_chain_score = 0
        self.strengths = []
        self.weaknesses = []
        self.opportunities = []
        self.threats = []
        self.detail_analysis = {}

    def analyze(self) -> dict:
        """执行完整价值链分析"""
        self.analyze_upstream()
        self.analyze_midstream()
        self.analyze_downstream()
        self.calculate_overall_score()
        return self.generate_value_chain_report()

    def analyze_upstream(self) -> dict:
        """分析上游（供应商端）- 优化版"""
        result = {
            'supplier_concentration': 0.0,
            'top5_supplier_ratio': 'N/A',
            'related_supplier_ratio': 0.0,
            'raw_material_cost_ratio': 0.0,
            'supplier_risk': '中',
            'bargaining_power': '中',
            'key_findings': [],
            'top5_suppliers': [],
            'supplier_details': '',
            'accounts_payable_turnover': 0.0,
            'purchase_cost_ratio': 0.0,
            'supply_chain_stability': '中'
        }

        supplier_section = self.sections.get('top5_suppliers', {})

        if supplier_section and isinstance(supplier_section, dict):
            content = supplier_section.get('content', '') or supplier_section.get('text', '')

            if content:
                result['supplier_details'] = content[:2000]

                # 提取供应商集中度
                ratio_pattern = r'(\d+\.?\d*)\s*%'
                ratios = re.findall(ratio_pattern, content)

                if len(ratios) >= 1:
                    try:
                        top5_ratio = float(ratios[0])
                        result['top5_supplier_ratio'] = f"{top5_ratio:.1f}%"
                        result['supplier_concentration'] = top5_ratio
                    except (ValueError, IndexError):
                        pass

                # 检查关联交易
                # 🔴 2026-10-20 修复「臆造数值」：旧版只要文本里出现「关联」二字
                #   就写 `related_supplier_ratio = 50.0` —— 这是凭空假设的占比，
                #   不是年报披露数据。现改为：只记录**定性事实**（存在关联交易），
                #   占比留 None 并标注不可计算，避免用假比率参与评分。
                if '关联' in content or '关联方' in content:
                    result['related_supplier_ratio'] = None
                    result['related_supplier_ratio_note'] = (
                        '年报文本提及关联交易，但未披露关联采购占比 → 不估算')
                    result['key_findings'].append('存在关联交易供应商，需关注定价公允性（占比未披露）')
                else:
                    result['related_supplier_ratio'] = 0.0

                # 检查年报中是否有具体的供应商名称（不是"第一名"等通用名称）
                has_generic_names = '第一名' in content or '第二名' in content
                if has_generic_names:
                    # 年报未披露具体供应商名称（只有"第一名"等通用名称）
                    result['top5_suppliers'] = ['公司未披露具体供应商名称']
                    result['key_findings'].append('供应商名称未披露，符合信息披露规则')
                else:
                    # 提取供应商名称
                    names = re.findall(r'([^\s\n]{2,15}公司|[^\s\n]{2,15}集团)', content)
                    # 过滤掉通用词汇
                    generic_names = ['公司前', '公司第', '公司名', '序号供', '报告期内公司', '重组', '子公司']
                    filtered_names = [n for n in names if not any(g in n for g in generic_names)]
                    if filtered_names and len(filtered_names) >= 5:
                        result['top5_suppliers'] = filtered_names[:5]
                    else:
                        result['top5_suppliers'] = ['公司未披露具体供应商名称']

        # 从财务指标计算
        latest_metrics = self.financial_metrics.get('latest', {})
        if latest_metrics:
            # 毛利率估算原材料成本占比
            gross_margin = latest_metrics.get('XSMLL', 0)
            if gross_margin:
                try:
                    gm = float(gross_margin)
                    result['raw_material_cost_ratio'] = 100.0 - gm
                    if gm > 40:
                        result['bargaining_power'] = '强'
                        result['key_findings'].append(f'高毛利率({gm:.1f}%)，对下游议价能力强')
                    elif gm < 20:
                        result['bargaining_power'] = '弱'
                        result['key_findings'].append(f'低毛利率({gm:.1f}%)，可能受上下游挤压')
                except (ValueError, TypeError):
                    pass

            # 估算应付账款周转率
            revenue = latest_metrics.get('TOTAL_OPERATE_INCOME', 0)
            payables = latest_metrics.get('ACCOUNTS_RECE', 0)  # 应付账款
            try:
                if revenue > 0 and payables > 0:
                    result['accounts_payable_turnover'] = (float(revenue) / float(payables)) * 100
            except (ValueError, TypeError):
                pass

        # 风险评估
        if result['supplier_concentration'] > 50:
            result['supplier_risk'] = '高'
            result['key_findings'].append(f'供应商集中度较高({result["supplier_concentration"]:.1f}%)，存在供应风险')
        elif result['supplier_concentration'] < 30:
            result['supplier_risk'] = '低'
            result['key_findings'].append('供应商分散，风险可控')
        else:
            result['supplier_risk'] = '中'

        self.upstream = result
        return result

    def analyze_midstream(self) -> dict:
        """分析中游（生产制造端）- 优化版"""
        result = {
            'capacity_utilization': 0.0,
            'good_rate': 0.0,
            'production_scale': 'N/A',
            'tech_barrier': [],
            'capex_intensity': 0.0,
            'production_efficiency': '中',
            'key_findings': [],
            'capacity_details': '',
            'rd_intensity': 0.0,
            'inventory_turnover': 0.0,
            'fixed_assets_ratio': 0.0,
            'production_quality': '中'
        }

        # 从年报章节提取研发费用
        supplier_section = self.sections.get('top5_suppliers', {})
        if supplier_section and isinstance(supplier_section, dict):
            content = supplier_section.get('content', '') or supplier_section.get('text', '')
            if content and '研发费用' in content:
                # 提取研发费用金额（格式：研发费用\n1,139,926,657.22）
                rd_pattern = r'研发费用\s*\n\s*([0-9,]+(?:\.[0-9]+)?)'
                rd_match = re.search(rd_pattern, content)
                if rd_match:
                    rd_amount = float(rd_match.group(1).replace(',', ''))
                    # 从财务指标获取营收
                    latest_metrics = self.financial_metrics.get('latest', {})
                    revenue = latest_metrics.get('TOTAL_OPERATE_INCOME', 0)
                    if revenue > 0:
                        result['rd_intensity'] = (rd_amount / float(revenue)) * 100
                        if result['rd_intensity'] > 10:
                            result['tech_barrier'].append(f'高研发投入({result['rd_intensity']:.1f}%)，形成技术壁垒')
                        elif result['rd_intensity'] > 5:
                            result['tech_barrier'].append(f'研发投入占营收{result['rd_intensity']:.1f}%')
                        result['key_findings'].append(f'研发投入强度{result['rd_intensity']:.1f}%')

        capacity_section = self.sections.get('capacity', {})
        if capacity_section and isinstance(capacity_section, dict):
            content = capacity_section.get('content', '') or capacity_section.get('text', '')
            if content:
                result['capacity_details'] = content[:2000]

                # 提取产能利用率
                util_pattern = r'(\d+\.?\d*)\s*%'
                utilizations = re.findall(util_pattern, content)

                for util_str in utilizations:
                    try:
                        util = float(util_str)
                        if 50 <= util <= 150:
                            result['capacity_utilization'] = util
                            break
                    except ValueError:
                        continue

                if '利用率' in content:
                    result['key_findings'].append('产能利用率数据已提取')
                if '在建' in content:
                    result['key_findings'].append('存在在建产能，扩张中')

        prod_section = self.sections.get('production_sales', {})
        if prod_section and isinstance(prod_section, dict):
            content = prod_section.get('content', '') or prod_section.get('text', '')
            if content:
                result['production_scale'] = content[:500]
                if '产销量' in content or '产量' in content:
                    result['key_findings'].append('产销量数据已提取')

        # 从财务指标补充
        latest_metrics = self.financial_metrics.get('latest', {})
        if latest_metrics:
            revenue = latest_metrics.get('TOTAL_OPERATE_INCOME', 0)
            inventory = latest_metrics.get('INVENTORY', 0)
            try:
                if revenue > 0 and inventory > 0:
                    result['inventory_turnover'] = (float(revenue) / float(inventory)) * 100
            except (ValueError, TypeError):
                pass

            # 估算固定资产比例
            total_assets = latest_metrics.get('TOTAL_ASSETS', 0)
            current_assets = latest_metrics.get('TOTAL_CURRENT_ASSETS', 0)
            try:
                if total_assets > 0 and current_assets > 0:
                    fixed_assets = float(total_assets) - float(current_assets)
                    result['fixed_assets_ratio'] = (fixed_assets / float(total_assets)) * 100
            except (ValueError, TypeError):
                pass

        # 生产效率评估
        if result['capacity_utilization'] > 80:
            result['production_efficiency'] = '高'
            result['key_findings'].append(f'产能利用率较高({result["capacity_utilization"]:.1f}%)')
        elif result['capacity_utilization'] < 50:
            result['production_efficiency'] = '低'
            result['key_findings'].append(f'产能利用率偏低({result["capacity_utilization"]:.1f}%)，存在产能过剩风险')
        else:
            result['production_efficiency'] = '中'

        # 技术壁垒评估
        if result['rd_intensity'] > 5:
            result['production_quality'] = '高'

        self.midstream = result
        return result

    def analyze_downstream(self) -> dict:
        """分析下游（客户端）- 优化版"""
        result = {
            'customer_concentration': 0.0,
            'top5_customer_ratio': 'N/A',
            'sales_model': 'N/A',
            'channel_control': '中',
            'brand_premium': 0.0,
            'customer_loyalty': '中',
            'key_findings': [],
            'top5_customers': [],
            'customer_details': '',
            'accounts_receivable_turnover': 0.0,
            'selling_expense_ratio': 0.0,
            'market_position': '中'
        }

        customer_section = self.sections.get('top5_customers', {})

        if customer_section and isinstance(customer_section, dict):
            content = customer_section.get('content', '') or customer_section.get('text', '')

            if content:
                result['customer_details'] = content[:2000]

                ratio_pattern = r'(\d+\.?\d*)\s*%'
                ratios = re.findall(ratio_pattern, content)

                if len(ratios) >= 1:
                    try:
                        top5_ratio = float(ratios[0])
                        result['top5_customer_ratio'] = f"{top5_ratio:.1f}%"
                        result['customer_concentration'] = top5_ratio
                    except (ValueError, IndexError):
                        pass

                if '关联' in content or '关联方' in content:
                    result['key_findings'].append('存在关联交易客户，可能存在利益输送风险')

                names = re.findall(r'[\u4e00-\u9fa5a-zA-Z]+公司', content)
                result['top5_customers'] = names[:5]

        # 从财务指标补充
        latest_metrics = self.financial_metrics.get('latest', {})
        if latest_metrics:
            gross_margin = latest_metrics.get('XSMLL', 0)
            if gross_margin:
                try:
                    gm = float(gross_margin)
                    result['brand_premium'] = gm

                    if gm > 40:
                        result['channel_control'] = '强'
                        result['key_findings'].append(f'高毛利率({gm:.1f}%)，品牌溢价能力强')
                    elif gm < 20:
                        result['channel_control'] = '弱'
                        result['key_findings'].append(f'低毛利率({gm:.1f}%)，可能受制于渠道')
                    else:
                        result['channel_control'] = '中'
                        result['key_findings'].append(f'毛利率({gm:.1f}%)，处于行业中游')
                except (ValueError, TypeError):
                    pass

            # 应收账款周转率
            revenue = latest_metrics.get('TOTAL_OPERATE_INCOME', 0)
            receivables = latest_metrics.get('ACCOUNTS_RECE', 0)
            try:
                if revenue > 0 and receivables > 0:
                    result['accounts_receivable_turnover'] = (float(revenue) / float(receivables)) * 100
            except (ValueError, TypeError):
                pass

        # 客户风险评估
        if result['customer_concentration'] > 50:
            result['customer_loyalty'] = '高（集中）'
            result['key_findings'].append(f'客户集中度较高({result["customer_concentration"]:.1f}%)，存在大客户依赖风险')
        elif result['customer_concentration'] < 30:
            result['customer_loyalty'] = '低（分散）'
            result['key_findings'].append('客户分散，风险可控')
        else:
            result['customer_loyalty'] = '中'

        self.downstream = result
        return result

    def calculate_overall_score(self):
        """计算价值链综合评分（0-100）- 科学评分算法"""
        # 各维度满分值
        upstream_weight = 30  # 上游权重
        midstream_weight = 40  # 中游权重
        downstream_weight = 30  # 下游权重

        upstream_score = 0
        midstream_score = 0
        downstream_score = 0

        # === 上游评分 ===
        up = self.upstream

        # 供应商集中度（10分）
        if up.get('supplier_concentration', 0) < 30:
            upstream_score += 10
        elif up.get('supplier_concentration', 0) < 50:
            upstream_score += 6
        elif up.get('supplier_concentration', 0) > 0:
            upstream_score += 2

        # 毛利率/议价能力（10分）
        if up.get('bargaining_power') == '强':
            upstream_score += 10
        elif up.get('bargaining_power') == '中':
            upstream_score += 6
        else:
            upstream_score += 2

        # 供应商风险（10分）
        if up.get('supplier_risk') == '低':
            upstream_score += 10
        elif up.get('supplier_risk') == '中':
            upstream_score += 6
        else:
            upstream_score += 2

        # === 中游评分 ===
        mid = self.midstream

        # 产能利用率（15分）
        if mid.get('capacity_utilization', 0) > 80:
            midstream_score += 15
        elif mid.get('capacity_utilization', 0) > 50:
            midstream_score += 10
        elif mid.get('capacity_utilization', 0) > 0:
            midstream_score += 5

        # 研发强度（15分）
        if mid.get('rd_intensity', 0) > 8:
            midstream_score += 15
        elif mid.get('rd_intensity', 0) > 5:
            midstream_score += 12
        elif mid.get('rd_intensity', 0) > 3:
            midstream_score += 8
        elif mid.get('rd_intensity', 0) > 0:
            midstream_score += 4

        # 生产效率（10分）
        if mid.get('production_efficiency') == '高':
            midstream_score += 10
        elif mid.get('production_efficiency') == '中':
            midstream_score += 6
        else:
            midstream_score += 2

        # === 下游评分 ===
        down = self.downstream

        # 客户集中度（10分）
        if down.get('customer_concentration', 0) < 30:
            downstream_score += 10
        elif down.get('customer_concentration', 0) < 50:
            downstream_score += 6
        elif down.get('customer_concentration', 0) > 0:
            downstream_score += 2

        # 渠道控制（10分）
        if down.get('channel_control') == '强':
            downstream_score += 10
        elif down.get('channel_control') == '中':
            downstream_score += 6
        else:
            downstream_score += 2

        # 品牌溢价/毛利率（10分）
        if down.get('brand_premium', 0) > 40:
            downstream_score += 10
        elif down.get('brand_premium', 0) > 25:
            downstream_score += 7
        elif down.get('brand_premium', 0) > 0:
            downstream_score += 4

        # === 计算总分 ===
        self.value_chain_score = upstream_score + midstream_score + downstream_score

        # === 优势劣势分析 ===
        if upstream_score > 20:
            self.strengths.append(f'上游供应商管理优秀（{upstream_score}/{upstream_weight}分）')
        elif upstream_score < 15:
            self.weaknesses.append(f'上游供应商管理待改进（{upstream_score}/{upstream_weight}分）')

        if midstream_score > 30:
            self.strengths.append(f'中游生产研发能力强（{midstream_score}/{midstream_weight}分）')
        elif midstream_score < 20:
            self.weaknesses.append(f'中游生产研发需提升（{midstream_score}/{midstream_weight}分）')

        if downstream_score > 20:
            self.strengths.append(f'下游客户渠道稳固（{downstream_score}/{downstream_weight}分）')
        elif downstream_score < 15:
            self.weaknesses.append(f'下游客户渠道需强化（{downstream_score}/{downstream_weight}分）')

        # 保存详细评分
        self.detail_analysis = {
            'upstream_score': upstream_score,
            'upstream_max': upstream_weight,
            'midstream_score': midstream_score,
            'midstream_max': midstream_weight,
            'downstream_score': downstream_score,
            'downstream_max': downstream_weight
        }

    def generate_value_chain_report(self) -> dict:
        """生成完整价值链分析报告"""
        return {
            'stock_code': self.stock_code,
            'market': self.market,
            'upstream': self.upstream,
            'midstream': self.midstream,
            'downstream': self.downstream,
            'value_chain_score': self.value_chain_score,
            'score_detail': self.detail_analysis,
            'strengths': self.strengths,
            'weaknesses': self.weaknesses,
            'opportunities': self.opportunities,
            'threats': self.threats,
            'summary': self._generate_summary()
        }

    def _generate_summary(self) -> str:
        """生成一句话总结"""
        score = self.value_chain_score
        level = '强' if score >= 70 else '中' if score >= 50 else '弱'
        level_desc = '行业领先' if score >= 80 else '具有竞争力' if score >= 60 else '有待提升'

        upstream_risk = self.upstream.get('supplier_risk', '中')
        mid_efficiency = self.midstream.get('production_efficiency', '中')
        downstream_control = self.downstream.get('channel_control', '中')

        summary = (
            f"公司价值链综合竞争力{level}（{score}分，{level_desc}），"
            f"上游供应商风险{upstream_risk}，中游生产效率{mid_efficiency}，下游渠道掌控力{downstream_control}。"
        )

        if self.strengths:
            summary += f"核心优势包括：{self.strengths[0]}。"
        if self.weaknesses:
            summary += f"主要不足包括：{self.weaknesses[0]}。"

        return summary

    def format_report_section(self) -> str:
        """生成Markdown格式的报告章节"""
        report = self.generate_value_chain_report()
        up = report['upstream']
        mid = report['midstream']
        down = report['downstream']
        score_detail = report.get('score_detail', {})

        section = f"""
## 24. 价值链分析

### 24.1 上游分析（供应商端）
| 指标 | 数值 | 状态 |
|------|------|------|
| 前五大供应商占比 | {up.get('top5_supplier_ratio', 'N/A')} | {'高' if up.get('supplier_concentration', 0) > 50 else '低' if up.get('supplier_concentration', 0) < 30 else '中'} |
| 关联交易供应商占比 | {('未披露' if up.get('related_supplier_ratio') is None else f"{up.get('related_supplier_ratio'):.1f}%")} | {'存在关联交易（占比未披露，不估算）' if up.get('related_supplier_ratio') is None else ('存在关联交易' if up.get('related_supplier_ratio', 0) > 0 else '无关联交易')} |
| 原材料成本占比（估算） | {up.get('raw_material_cost_ratio', 0):.1f}% | {'高' if up.get('raw_material_cost_ratio', 0) > 60 else '低' if up.get('raw_material_cost_ratio', 0) < 40 else '中'} |
| 供应商议价能力 | {up.get('bargaining_power', 'N/A')} | {'强' if up.get('bargaining_power') == '强' else '弱' if up.get('bargaining_power') == '弱' else '中'} |
| 供应商风险等级 | {up.get('supplier_risk', '中')} | {'⚠️ 高风险' if up.get('supplier_risk') == '高' else '✅ 低风险' if up.get('supplier_risk') == '低' else '🟡 中风险'} |

{'**前五大供应商**：' + ', '.join(up.get('top5_suppliers', []))[:5] if up.get('top5_suppliers') else ''}

{'**关键发现**：' + '；'.join(up.get('key_findings', [])) if up.get('key_findings') else ''}

---

### 24.2 中游分析（生产制造端）
| 指标 | 数值 | 状态 |
|------|------|------|
| 产能利用率 | {mid.get('capacity_utilization', 0):.1f}% | {'高' if mid.get('capacity_utilization', 0) > 80 else '低' if mid.get('capacity_utilization', 0) < 50 else '中'} |
| 研发投入强度 | {mid.get('rd_intensity', 0):.1f}% | {'高' if mid.get('rd_intensity', 0) > 8 else '中' if mid.get('rd_intensity', 0) > 3 else '低'} |
| 生产效率 | {mid.get('production_efficiency', '中')} | {'✅ 高效率' if mid.get('production_efficiency') == '高' else '⚠️ 低效率' if mid.get('production_efficiency') == '低' else '🟡 中效率'} |
| 存货周转率（估算） | {mid.get('inventory_turnover', 0):.1f}% | {'高' if mid.get('inventory_turnover', 0) > 80 else '中' if mid.get('inventory_turnover', 0) > 50 else '低'} |
| 固定资产比例 | {mid.get('fixed_assets_ratio', 0):.1f}% | {'重资产' if mid.get('fixed_assets_ratio', 0) > 50 else '轻资产'} |

{'**技术壁垒**：' + '；'.join(mid.get('tech_barrier', [])) if mid.get('tech_barrier') else ''}

{'**关键发现**：' + '；'.join(mid.get('key_findings', [])) if mid.get('key_findings') else ''}

---

### 24.3 下游分析（客户端）
| 指标 | 数值 | 状态 |
|------|------|------|
| 前五大客户占比 | {down.get('top5_customer_ratio', 'N/A')} | {'高' if down.get('customer_concentration', 0) > 50 else '低' if down.get('customer_concentration', 0) < 30 else '中'} |
| 销售模式 | {down.get('sales_model', 'N/A')} | - |
| 渠道掌控力 | {down.get('channel_control', '中')} | {'✅ 强' if down.get('channel_control') == '强' else '⚠️ 弱' if down.get('channel_control') == '弱' else '🟡 中'} |
| 品牌溢价（毛利率） | {down.get('brand_premium', 0):.1f}% | {'高溢价' if down.get('brand_premium', 0) > 40 else '低溢价' if down.get('brand_premium', 0) < 20 else '中溢价'} |
| 客户稳定性 | {down.get('customer_loyalty', '中')} | - |

{'**前五大客户**：' + ', '.join(down.get('top5_customers', []))[:5] if down.get('top5_customers') else ''}

{'**关键发现**：' + '；'.join(down.get('key_findings', [])) if down.get('key_findings') else ''}

---

### 24.4 综合评估

#### 价值链综合评分：**{report['value_chain_score']}/100**
{'🟢 **等级：强（行业领先）**' if report['value_chain_score'] >= 70 else '🟡 **等级：中（具有竞争力）**' if report['value_chain_score'] >= 50 else '🔴 **等级：弱（有待提升）**'}

| 维度 | 得分 | 满分 | 评级 |
|------|------|------|------|
| 上游（供应商） | {score_detail.get('upstream_score', 0)} | {score_detail.get('upstream_max', 30)} | {'✅ 优秀' if score_detail.get('upstream_score', 0) > 20 else '⚠️ 待改进' if score_detail.get('upstream_score', 0) < 15 else '🟡 良好'} |
| 中游（生产制造） | {score_detail.get('midstream_score', 0)} | {score_detail.get('midstream_max', 40)} | {'✅ 优秀' if score_detail.get('midstream_score', 0) > 30 else '⚠️ 待改进' if score_detail.get('midstream_score', 0) < 20 else '🟡 良好'} |
| 下游（客户渠道） | {score_detail.get('downstream_score', 0)} | {score_detail.get('downstream_max', 30)} | {'✅ 优秀' if score_detail.get('downstream_score', 0) > 20 else '⚠️ 待改进' if score_detail.get('downstream_score', 0) < 15 else '🟡 良好'} |

---

**核心优势**：
{chr(10).join([f'- {s}' for s in report['strengths']]) if report['strengths'] else '- 暂无明显优势'}

**主要不足**：
{chr(10).join([f'- {w}' for w in report['weaknesses']]) if report['weaknesses'] else '- 暂无明显不足'}

---

**总结**：{report['summary']}
"""
        return section


def fetch_value_chain(stock_code: str, market: str = 'a',
                     data_dir: str = None) -> dict:
    """价值链分析主入口（优化版）"""
    result = {
        'stock_code': stock_code,
        'market': market,
        'success': False,
        'error': None,
        'data': {}
    }

    try:
        annual_sections = {}
        financials = {}
        financial_metrics = {}

        if data_dir and os.path.exists(data_dir):
            results_file = os.path.join(data_dir, 'results.json')
            if os.path.exists(results_file):
                with open(results_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                    findings = results.get('findings', {})

                    if 'annual_report_sections' in findings:
                        annual_sections = findings['annual_report_sections']

                    if 'financial' in findings:
                        financials = findings['financial']

            # 尝试从本地文件加载年报章节数据
            if not annual_sections:
                ars_file = os.path.join(data_dir, 'annual_report_sections.json')
                if os.path.exists(ars_file):
                    with open(ars_file, 'r', encoding='utf-8') as f:
                        annual_sections = json.load(f)

            # 尝试读取财务指标
            fm_file = os.path.join(data_dir, 'financial_metrics.json')
            if os.path.exists(fm_file):
                with open(fm_file, 'r', encoding='utf-8') as f:
                    financial_metrics = json.load(f)

        analyzer = ValueChainAnalyzer(
            annual_sections=annual_sections,
            financials=financials,
            stock_code=stock_code,
            market=market,
            financial_metrics=financial_metrics
        )

        report = analyzer.analyze()

        result['success'] = True
        result['data'] = report

        # 保存结果
        if data_dir:
            output_file = os.path.join(data_dir, 'value_chain.json')
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)

    except Exception as e:
        result['error'] = str(e)

    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2:
        stock = sys.argv[1]
        market = sys.argv[2] if len(sys.argv) > 2 else 'a'
        data_dir = sys.argv[3] if len(sys.argv) > 3 else None

        result = fetch_value_chain(stock, market, data_dir)

        if result['success']:
            print(f"✅ 价值链分析完成")
            print(f"评分：{result['data']['value_chain_score']}/100")
            print(f"总结：{result['data']['summary']}")
        else:
            print(f"❌ 分析失败: {result['error']}")
    else:
        print("用法: python value_chain_analysis.py <股票代码> [市场] [数据目录]")
        print("示例: python value_chain_analysis.py 002180 a output/002180_20260530/data")


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    analyzer = ValueChainAnalyzer(
        annual_sections={},
        financials={},
        stock_code='',
        market='a'
    )
    analyzer.upstream = data.get('upstream', {})
    analyzer.midstream = data.get('midstream', {})
    analyzer.downstream = data.get('downstream', {})
    analyzer.value_chain_score = data.get('value_chain_score', 0)
    analyzer.strengths = data.get('strengths', [])
    analyzer.weaknesses = data.get('weaknesses', [])
    analyzer.opportunities = data.get('opportunities', [])
    analyzer.threats = data.get('threats', [])
    md = analyzer.format_report_section()
    return [md, ""]
