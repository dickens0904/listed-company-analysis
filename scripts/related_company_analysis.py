# -*- coding: utf-8 -*-
"""
related_company_analysis.py - 关联公司深度分析模块

功能：从年报+工商信息两个维度分析关联公司
  - 子公司分析（年报子公司章节）
  - 母公司分析（实际控制人+上层股权）
  - 参股公司分析（长期股权投资）
  - 关联企业图谱构建

数据来源：
  1. 年报 - annual_report_sections.json
  2. 工商信息 - gsxt_crawler.py（待集成）
  3. 股东信息 - structure.json / top10_shareholders

使用方式：
  from scripts.related_company_analysis import RelatedCompanyAnalyzer

  analyzer = RelatedCompanyAnalyzer(stock_code, market, data_dir)
  result = analyzer.analyze()
"""

import sys
import json
import os
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class RelatedCompanyAnalyzer:
    """关联公司深度分析器"""

    def __init__(self, stock_code: str, market: str, data_dir: str):
        """初始化分析器

        Args:
            stock_code: 股票代码
            market: 市场（a/h/n）
            data_dir: 数据目录
        """
        self.stock_code = stock_code
        self.market = market
        self.data_dir = data_dir
        self.results = {}

    def analyze(self) -> Dict[str, Any]:
        """执行完整分析

        Returns:
            关联公司分析结果
        """
        print(f"[关联公司分析] 开始分析 {self.stock_code}...")

        self.results = {
            'stock_code': self.stock_code,
            'market': self.market,
            'analyze_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'subsidiaries': {},
            'parent_company': {},
            'investees': {},
            'related_companies': [],
            'corporate_structure': {},
            'risks': [],
            'summary': '',
            'score': 0
        }

        self._load_base_data()
        self._extract_subsidiaries()
        self._extract_parent_company()
        self._extract_investees()
        self._build_related_companies()
        self._analyze_corporate_structure()
        self._identify_risks()
        self._generate_summary()
        self._calculate_score()

        print(f"[关联公司分析] 完成，综合评分: {self.results['score']}/100")
        return self.results

    def _load_base_data(self):
        """加载基础数据"""
        files_to_load = {
            'annual_report': 'annual_report_sections.json',
            'structure': 'structure.json',
            'shareholders': 'top10_shareholders.json',
            'results': 'results.json'
        }

        self.data = {}
        for key, filename in files_to_load.items():
            filepath = os.path.join(self.data_dir, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.data[key] = json.load(f)
                    print(f"  [加载] {filename}")
                except Exception as e:
                    print(f"  [警告] 加载 {filename} 失败: {e}")

    def _extract_subsidiaries(self):
        """从年报中提取子公司信息"""
        self.results['subsidiaries'] = {
            'total_count': 0,
            'major_subsidiaries': [],
            'by_region': {'国内': [], '海外': []},
            'by_business': {},
            'performance_summary': {}
        }

        if 'annual_report' not in self.data:
            return

        ar = self.data['annual_report']

        if 'subsidiaries' in ar:
            content = ar['subsidiaries'].get('content', '')

            table_rows = re.findall(
                r'([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)',
                content
            )

            for row in table_rows:
                if len(row) >= 4:
                    company_name = row[0].strip()
                    biz_type = row[1].strip() if len(row) > 1 else ''
                    business = row[2].strip() if len(row) > 2 else ''
                    reg_capital = row[3].strip() if len(row) > 3 else ''
                    total_asset = row[4].strip() if len(row) > 4 else ''
                    net_asset = row[5].strip() if len(row) > 5 else ''
                    revenue = row[6].strip() if len(row) > 6 else ''

                    if company_name and '公司名称' not in company_name:
                        sub_info = {
                            'name': company_name,
                            'type': biz_type,
                            'business': business[:100] if business else '',
                            'registered_capital': reg_capital,
                            'total_asset': total_asset,
                            'net_asset': net_asset,
                            'revenue': revenue
                        }

                        self.results['subsidiaries']['major_subsidiaries'].append(sub_info)

                        if '中国' in company_name or '珠海' in company_name or '深圳' in company_name:
                            self.results['subsidiaries']['by_region']['国内'].append(sub_info['name'])
                        else:
                            self.results['subsidiaries']['by_region']['海外'].append(sub_info['name'])

            self.results['subsidiaries']['total_count'] = len(
                self.results['subsidiaries']['major_subsidiaries']
            )

            major_subs = self.results['subsidiaries']['major_subsidiaries']
            if major_subs:
                self.results['subsidiaries']['performance_summary'] = {
                    'total_revenue': sum([
                        self._parse_amount(s.get('revenue', '0'))
                        for s in major_subs
                        if s.get('revenue')
                    ]),
                    'total_assets': sum([
                        self._parse_amount(s.get('total_asset', '0'))
                        for s in major_subs
                        if s.get('total_asset')
                    ]),
                    'top_performers': sorted(
                        major_subs,
                        key=lambda x: self._parse_amount(x.get('revenue', '0')),
                        reverse=True
                    )[:5]
                }

        print(f"  [子公司] 提取到 {self.results['subsidiaries']['total_count']} 家主要子公司")

    def _extract_parent_company(self):
        """提取母公司/实际控制人信息"""
        self.results['parent_company'] = {
            'actual_controller': {},
            'controlling_shareholders': [],
            'ultimate_beneficial_owner': {},
            'equity_chain': []
        }

        if 'structure' in self.data:
            structure = self.data['structure']

            if 'actual_controller' in structure:
                self.results['parent_company']['actual_controller'] = structure['actual_controller']

            if 'shareholders' in structure:
                for sh in structure['shareholders'][:5]:
                    self.results['parent_company']['controlling_shareholders'].append(sh['name'])

            if 'control_chain' in structure:
                self.results['parent_company']['equity_chain'] = structure['control_chain']

            if 'equity_penetration' in structure:
                penetration = structure['equity_penetration']
                if penetration:
                    self.results['parent_company']['ultimate_beneficial_owner'] = {
                        'name': penetration[0].get('entity', ''),
                        'ratio': penetration[0].get('ratio', 0),
                        'type': penetration[0].get('type', '')
                    }

        if 'annual_report' not in self.data:
            return

        ar = self.data['annual_report']

        if 'actual_controller' in ar:
            content = ar['actual_controller'].get('content', '')

            controller_match = re.search(
                r'实际控制人[：:]\s*([^\n，,]+)',
                content
            )
            if controller_match and not self.results['parent_company']['actual_controller']:
                self.results['parent_company']['actual_controller']['name'] = \
                    controller_match.group(1).strip()

        print(f"  [母公司] 提取到 {len(self.results['parent_company']['controlling_shareholders'])} 个控股股东")

    def _extract_investees(self):
        """提取参股公司信息"""
        self.results['investees'] = {
            'total_count': 0,
            'joint_ventures': [],
            'associates': [],
            'financial_investments': []
        }

        if 'annual_report' not in self.data:
            return

        ar = self.data['annual_report']

        if 'lt_equity' in ar:
            content = ar['lt_equity'].get('content', '')

            table_rows = re.findall(
                r'([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)\|([^\n\|]+)',
                content
            )

            for row in table_rows:
                if len(row) >= 3:
                    company_name = row[0].strip()
                    region = row[1].strip() if len(row) > 1 else ''
                    business = row[2].strip() if len(row) > 2 else ''
                    share_ratio = row[3].strip() if len(row) > 3 else ''

                    if company_name and '公司名称' not in company_name and len(company_name) > 2:
                        inv_info = {
                            'name': company_name,
                            'region': region,
                            'business': business,
                            'share_ratio': share_ratio
                        }

                        if '合营' in content or '50%' in share_ratio:
                            self.results['investees']['joint_ventures'].append(inv_info)
                        elif '联营' in content or '20%' in share_ratio:
                            self.results['investees']['associates'].append(inv_info)
                        else:
                            self.results['investees']['financial_investments'].append(inv_info)

        self.results['investees']['total_count'] = (
            len(self.results['investees']['joint_ventures']) +
            len(self.results['investees']['associates']) +
            len(self.results['investees']['financial_investments'])
        )

        print(f"  [参股公司] 提取到 {self.results['investees']['total_count']} 家参股公司")

    def _build_related_companies(self):
        """构建关联企业图谱"""
        related = []

        for sub in self.results['subsidiaries'].get('major_subsidiaries', []):
            related.append({
                'name': sub['name'],
                'relation': '子公司',
                'type': '控股',
                'business': sub.get('business', ''),
                'region': '国内' if any(r in sub['name'] for r in ['珠海', '深圳', '中国']) else '海外'
            })

        for inv in self.results['investees'].get('associates', []):
            related.append({
                'name': inv['name'],
                'relation': '联营公司',
                'type': '参股',
                'business': inv.get('business', ''),
                'share_ratio': inv.get('share_ratio', '')
            })

        for inv in self.results['investees'].get('joint_ventures', []):
            related.append({
                'name': inv['name'],
                'relation': '合营公司',
                'type': '参股',
                'business': inv.get('business', ''),
                'share_ratio': inv.get('share_ratio', '')
            })

        self.results['related_companies'] = related
        print(f"  [关联企业] 构建了 {len(related)} 家关联企业")

    def _analyze_corporate_structure(self):
        """分析股权结构"""
        self.results['corporate_structure'] = {
            'ownership_chain': [],
            'layer_count': 0,
            'structure_type': '',
            'governance_risk': ''
        }

        parent = self.results['parent_company']
        subs = self.results['subsidiaries']

        chain = []

        if parent.get('actual_controller', {}).get('name'):
            chain.append(parent['actual_controller']['name'])

        if parent.get('controlling_shareholders'):
            chain.extend(parent['controlling_shareholders'])

        chain.append(f"{self.stock_code}（上市公司）")

        self.results['corporate_structure']['ownership_chain'] = chain
        self.results['corporate_structure']['layer_count'] = len(chain)

        if len(chain) <= 2:
            self.results['corporate_structure']['structure_type'] = '扁平化'
        elif len(chain) <= 4:
            self.results['corporate_structure']['structure_type'] = '常规'
        else:
            self.results['corporate_structure']['structure_type'] = '复杂'

        if subs.get('total_count', 0) > 50:
            self.results['corporate_structure']['governance_risk'] = '高'
        elif subs.get('total_count', 0) > 20:
            self.results['corporate_structure']['governance_risk'] = '中'
        else:
            self.results['corporate_structure']['governance_risk'] = '低'

        print(f"  [股权结构] {self.results['corporate_structure']['structure_type']}，共 {len(chain)} 层")

    def _identify_risks(self):
        """识别关联公司风险"""
        risks = []

        subs_count = self.results['subsidiaries'].get('total_count', 0)
        if subs_count > 50:
            risks.append({
                'type': '治理风险',
                'level': '高',
                'description': f'子公司数量过多（{subs_count}家），管理复杂度高'
            })
        elif subs_count > 20:
            risks.append({
                'type': '治理风险',
                'level': '中',
                'description': f'子公司数量较多（{subs_count}家），需关注管理效率'
            })

        gov_risk = self.results['corporate_structure'].get('governance_risk', '')
        if gov_risk == '高':
            risks.append({
                'type': '架构风险',
                'level': '高',
                'description': '股权结构复杂，治理风险较高'
            })

        overseas = len(self.results['subsidiaries'].get('by_region', {}).get('海外', []))
        if overseas > 10:
            risks.append({
                'type': '海外风险',
                'level': '高',
                'description': f'海外子公司较多（{overseas}家），面临地缘政治、汇率等风险'
            })
        elif overseas > 5:
            risks.append({
                'type': '海外风险',
                'level': '中',
                'description': f'有一定数量的海外子公司（{overseas}家）'
            })

        self.results['risks'] = risks
        print(f"  [风险识别] 发现 {len(risks)} 项风险")

    def _generate_summary(self):
        """生成分析总结"""
        subs = self.results['subsidiaries']
        parent = self.results['parent_company']
        structure = self.results['corporate_structure']
        risks = self.results['risks']

        summary_parts = []

        subs_count = subs.get('total_count', 0)
        if subs_count > 0:
            summary_parts.append(f"上市公司共有{sub_count}家主要子公司")

        if parent.get('controlling_shareholders'):
            ctrl = parent['controlling_shareholders'][0]
            summary_parts.append(f"控股股东为{ctrl}")

        if structure.get('structure_type'):
            summary_parts.append(f"股权结构为{structure['structure_type']}结构")

        if risks:
            high_risk = [r for r in risks if r['level'] == '高']
            if high_risk:
                summary_parts.append(f"存在{len(high_risk)}项高风险事项需关注")

        self.results['summary'] = '。'.join(summary_parts) if summary_parts else '关联公司结构分析完成'

    def _calculate_score(self):
        """计算综合评分"""
        score = 100

        risks = self.results['risks']
        for risk in risks:
            if risk['level'] == '高':
                score -= 20
            elif risk['level'] == '中':
                score -= 10
            elif risk['level'] == '低':
                score -= 5

        subs_count = self.results['subsidiaries'].get('total_count', 0)
        if subs_count > 50:
            score -= 10
        elif subs_count > 100:
            score -= 20

        overseas = len(self.results['subsidiaries'].get('by_region', {}).get('海外', []))
        if overseas > 10:
            score -= 10

        self.results['score'] = max(0, min(100, score))

    def _parse_amount(self, text: str) -> float:
        """解析金额文本"""
        if not text:
            return 0.0

        text = text.replace(',', '').replace('，', '')

        multipliers = {
            '万': 10000,
            '亿': 100000000,
            '千': 1000,
            'k': 1000,
            'K': 1000,
            'M': 1000000,
            'm': 1000000
        }

        for unit, mult in multipliers.items():
            if unit in text:
                try:
                    num = float(text.replace(unit, '').strip())
                    return num * mult
                except Exception as _sexc:
                    record(__name__, '_parse_amount', _sexc, note='静默降级')
                    pass

        try:
            return float(text)
        except:
            return 0.0

    def save(self, output_dir: str = None):
        """保存分析结果"""
        if output_dir is None:
            output_dir = self.data_dir

        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, 'related_company_analysis.json')

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        print(f"[关联公司分析] 结果已保存至 {output_file}")


def analyze_related_companies(stock_code: str, market: str, data_dir: str) -> Dict[str, Any]:
    """关联公司分析主入口

    Args:
        stock_code: 股票代码
        market: 市场（a/h/n）
        data_dir: 数据目录

    Returns:
        分析结果字典
    """
    analyzer = RelatedCompanyAnalyzer(stock_code, market, data_dir)
    results = analyzer.analyze()
    analyzer.save()
    return results


if __name__ == '__main__':
    import sys

    if len(sys.argv) >= 4:
        stock_code = sys.argv[1]
        market = sys.argv[2]
        data_dir = sys.argv[3]

        print(f"=" * 60)
        print(f"关联公司深度分析 - {stock_code} ({market})")
        print(f"=" * 60)

        results = analyze_related_companies(stock_code, market, data_dir)

        print(f"\n{'=' * 60}")
        print(f"分析结果摘要")
        print(f"{'=' * 60}")
        print(f"综合评分: {results['score']}/100")
        print(f"子公司数量: {results['subsidiaries']['total_count']}")
        print(f"参股公司: {results['investees']['total_count']}")
        print(f"关联企业: {len(results['related_companies'])}")
        print(f"股权结构: {results['corporate_structure']['structure_type']}")
        print(f"风险数量: {len(results['risks'])}")
        print(f"\n{results['summary']}")

    else:
        print("用法: python related_company_analysis.py <股票代码> <市场> <数据目录>")
        print("示例: python related_company_analysis.py 002180 a output/002180_20260530/data")
