# -*- coding: utf-8 -*-
"""
enhanced_company_info_extractor.py - 增强的公司信息提取器

功能：从年报和公告中深度提取公司相关信息
- 子公司列表和详细信息
- 关联公司图谱
- 参股/合营/联营公司信息
- 重大交易/收购/并购历史
- 业务重组信息
- 投资组合分析
"""

import sys
import json
import os
import re
from typing import Dict, List, Optional, Any
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class EnhancedCompanyInfoExtractor:
    """增强的公司信息提取器"""

    def __init__(self, stock_code: str, market: str, data_dir: str):
        self.stock_code = stock_code
        self.market = market
        self.data_dir = data_dir
        self.data = {}
        self.results = {}

    def load_data(self) -> None:
        """加载所有可用数据"""
        print("加载数据...")

        files_to_load = {
            'annual_report': 'annual_report_sections.json',
            'structure': 'structure.json',
            'results': 'results.json',
            'financial_metrics': 'financial_metrics.json',
            'enhanced_company_info': 'enhanced_company_info.json'
        }

        for key, filename in files_to_load.items():
            filepath = os.path.join(self.data_dir, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.data[key] = json.load(f)
                    print(f"  ✓ 加载: {filename}")
                except Exception as e:
                    print(f"  ✗ 加载失败: {filename}, {e}")
            else:
                print(f"  - 未找到: {filename}")

    def extract_subsidiaries(self) -> Dict:
        """从多个数据源提取子公司信息"""
        print("\n提取子公司信息...")

        subsidiaries = {
            'total_count': 0,
            'full_list': [],
            'domestic': [],
            'overseas': [],
            'major_ones': [],
            'by_business_type': {}
        }

        # 1. 从年报子公司章节提取
        if 'annual_report' in self.data and 'subsidiaries' in self.data['annual_report']:
            content = self.data['annual_report']['subsidiaries'].get('content', '')
            subsidiaries_from_annual = self._parse_subsidiaries_table(content)
            for sub in subsidiaries_from_annual:
                subsidiaries['full_list'].append(sub)
                if '中国' in sub.get('name', '') or '珠海' in sub.get('name', '') or '深圳' in sub.get('name', ''):
                    subsidiaries['domestic'].append(sub)
                else:
                    subsidiaries['overseas'].append(sub)

        # 2. 从公告中提取子公司
        if 'results' in self.data and 'announcements' in self.data['results']['findings']:
            for ann in self.data['results']['findings']['announcements'].get('critical_announcements', []):
                title = ann.get('title', '')
                if '子公司' in title or '全资子公司' in title or '控股子公司' in title:
                    names = self._extract_company_names_from_announcement(ann)
                    for name in names:
                        if not any(s.get('name') == name for s in subsidiaries['full_list']):
                            sub_info = {
                                'name': name,
                                'type': 'unknown',
                                'source': 'announcement',
                                'from_announcement': title,
                                'date': ann.get('date', '')
                            }
                            subsidiaries['full_list'].append(sub_info)

        # 3. 从structure数据中补充
        if 'structure' in self.data:
            structure = self.data['structure']
            if 'main_listed' in structure and 'related' in structure['main_listed']:
                for rel in structure['main_listed']['related']:
                    name = rel.get('name', '')
                    if name and not any(s.get('name') == name for s in subsidiaries['full_list']):
                        sub_info = {
                            'name': name,
                            'type': 'unknown',
                            'source': 'structure',
                            'deal_type': rel.get('deal_type', '')
                        }
                        subsidiaries['full_list'].append(sub_info)
        
        # 4. 从已有的enhanced_company_info数据中补充
        if 'enhanced_company_info' in self.data:
            existing_data = self.data['enhanced_company_info']
            existing_subs = existing_data.get('subsidiaries', {}).get('full_list', [])
            for sub in existing_subs:
                name = sub.get('name', '')
                if name and not any(s.get('name') == name for s in subsidiaries['full_list']):
                    subsidiaries['full_list'].append(sub)

        subsidiaries['total_count'] = len(subsidiaries['full_list'])

        # 筛选重要子公司（有资产或营收数据的）
        subsidiaries['major_ones'] = [
            s for s in subsidiaries['full_list']
            if s.get('revenue') or s.get('total_asset') or s.get('net_asset')
        ]

        print(f"  提取到 {subsidiaries['total_count']} 个子公司")
        print(f"  国内: {len(subsidiaries['domestic'])} 家, 海外: {len(subsidiaries['overseas'])} 家")
        print(f"  重要子公司: {len(subsidiaries['major_ones'])} 家")

        return subsidiaries

    def _parse_subsidiaries_table(self, content: str) -> List[Dict]:
        """解析年报中的子公司表格"""
        subsidiaries = []

        # 排除的关键词（非公司名称）
        exclude_keywords = [
            '公司名称', '序号', '类型', '合计', '小计', '总计', '备注', '说明',
            '比例', '持股', '出资', '金额', '币种', '注册地', '业务性质',
            '总资产', '净资产', '营业收入', '净利润', '少数股东权益',
            '主要业务', '注册资本', '营业利润', '单位', '元'
        ]

        # 尝试匹配表格行（各种可能的格式）
        table_patterns = [
            # 模式1: 有明确列的表格（使用管道符分隔）
            r'([^\n\|]+)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)',
            # 模式2: 简化的表格（使用管道符分隔）
            r'([^\n\|]+)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)',
        ]

        for pattern in table_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if len(match) >= 1:
                    name = match[0].strip()
                    # 排除表头和非公司名称
                    if (name and len(name) > 2
                        and not any(kw in name for kw in exclude_keywords)
                        and not name.isdigit()):
                        sub_info = {
                            'name': name,
                            'source': 'annual_report',
                            'type': match[1].strip() if len(match) > 1 else '',
                            'business': match[2].strip() if len(match) > 2 else '',
                            'registered_capital': match[3].strip() if len(match) > 3 else '',
                            'total_asset': match[4].strip() if len(match) > 4 else '',
                            'net_asset': match[5].strip() if len(match) > 5 else '',
                            'revenue': match[6].strip() if len(match) > 6 else ''
                        }
                        subsidiaries.append(sub_info)

        # 如果没有匹配到表格行，尝试从文本中提取公司名称
        if not subsidiaries:
            # 匹配公司名称模式（包含"公司"、"集团"等关键词）
            company_patterns = [
                r'([\u4e00-\u9fa5]{2,15}(?:科技|控股|投资|集团|发展|实业|信息|技术|电子|机械|化工|医药|能源|材料|建设|工程|贸易|商务|咨询|服务|管理|教育|文化|传媒|网络|软件|数据|智能|新能源|环保|生物|医疗|健康|农业|食品|物流|地产|房产|酒店|旅游|餐饮|零售|电商|金融|证券|保险|基金|信托|租赁|担保|典当)?股份有限公司)',
                r'([\u4e00-\u9fa5]{2,15}(?:科技|控股|投资|集团|发展|实业|信息|技术|电子|机械|化工|医药|能源|材料|建设|工程|贸易|商务|咨询|服务|管理|教育|文化|传媒|网络|软件|数据|智能|新能源|环保|生物|医疗|健康|农业|食品|物流|地产|房产|酒店|旅游|餐饮|零售|电商|金融|证券|保险|基金|信托|租赁|担保|典当)?有限公司)',
                r'([\u4e00-\u9fa5]{2,15}(?:科技|控股|投资|集团|发展|实业|信息|技术|电子|机械|化工|医药|能源|材料|建设|工程|贸易|商务|咨询|服务|管理|教育|文化|传媒|网络|软件|数据|智能|新能源|环保|生物|医疗|健康|农业|食品|物流|地产|房产|酒店|旅游|餐饮|零售|电商|金融|证券|保险|基金|信托|租赁|担保|典当)?公司)',
                r'([\u4e00-\u9fa5]{2,15}(?:集团|控股|投资|科技))',
                # 外资公司
                r'([A-Za-z0-9\s]+(?:International|Inc|Ltd|LLC|Co|Corp|Group|Holdings))',
                # 具体已知公司（可扩展）
                r'(利盟国际)',
                r'(奔图)',
                r'(太盟投资)',
                r'(PAG)',
                r'(上海朔达)',
                r'(赛纳)',
                r'(纳思达)',
                r'(极海)',
                r'(艾派克)',
                r'(格之格)',
            ]

            for pattern in company_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    name = match.strip()
                    if name and len(name) > 2:
                        # 排除表头和非公司名称
                        if not any(kw in name for kw in exclude_keywords):
                            sub_info = {
                                'name': name,
                                'source': 'annual_report',
                                'type': '',
                                'business': '',
                                'registered_capital': '',
                                'total_asset': '',
                                'net_asset': '',
                                'revenue': ''
                            }
                            subsidiaries.append(sub_info)

        return subsidiaries

    def _extract_company_names_from_announcement(self, announcement: Dict) -> List[str]:
        """从公告中提取公司名称"""
        names = []
        content = ''

        if 'extracted_content' in announcement:
            content = announcement['extracted_content'].get('full_text_preview', '')
        if not content and 'ai_analysis' in announcement:
            ai_content = announcement['ai_analysis'].get('summary', '')
            if not ai_content:
                key_points = announcement['ai_analysis'].get('key_points', [])
                if key_points:
                    ai_content = ' '.join(str(kp) for kp in key_points)
            content = ai_content

        # 提取公司名称模式
        company_patterns = [
            # 更精确的公司名称模式（包含更多后缀）
            r'([\u4e00-\u9fa5]{2,15}(?:科技|控股|投资|集团|发展|实业|信息|技术|电子|机械|化工|医药|能源|材料|建设|工程|贸易|商务|咨询|服务|管理|教育|文化|传媒|网络|软件|数据|智能|新能源|环保|生物|医疗|健康|农业|食品|物流|地产|房产|酒店|旅游|餐饮|零售|电商|金融|证券|保险|基金|信托|租赁|担保|典当)?股份有限公司)',
            r'([\u4e00-\u9fa5]{2,15}(?:科技|控股|投资|集团|发展|实业|信息|技术|电子|机械|化工|医药|能源|材料|建设|工程|贸易|商务|咨询|服务|管理|教育|文化|传媒|网络|软件|数据|智能|新能源|环保|生物|医疗|健康|农业|食品|物流|地产|房产|酒店|旅游|餐饮|零售|电商|金融|证券|保险|基金|信托|租赁|担保|典当)?有限公司)',
            r'([\u4e00-\u9fa5]{2,15}(?:科技|控股|投资|集团|发展|实业|信息|技术|电子|机械|化工|医药|能源|材料|建设|工程|贸易|商务|咨询|服务|管理|教育|文化|传媒|网络|软件|数据|智能|新能源|环保|生物|医疗|健康|农业|食品|物流|地产|房产|酒店|旅游|餐饮|零售|电商|金融|证券|保险|基金|信托|租赁|担保|典当)?公司)',
            r'([\u4e00-\u9fa5]{2,15}(?:集团|控股|投资|科技))',
            # 外资公司
            r'([A-Za-z0-9\s]+(?:International|Inc|Ltd|LLC|Co|Corp|Group|Holdings))',
            # 具体已知公司（可扩展）
            r'(利盟国际)',
            r'(奔图)',
            r'(太盟投资)',
            r'(PAG)',
            r'(上海朔达)',
            r'(赛纳)',
            r'(纳思达)',
            r'(极海)',
            r'(艾派克)',
            r'(格之格)',
        ]

        for pattern in company_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                # 清理和验证公司名称
                name = str(match).strip()
                if (len(name) > 3
                    and '公司' in name
                    and '证券' not in name
                    and '会计师' not in name
                    and '律师' not in name
                    and '交易所' not in name
                    and '证监会' not in name
                    and '公告' not in name
                    and '提示' not in name
                    and '影响' not in name):
                    names.append(name)

        # 去重
        unique_names = list(set(names))
        return unique_names

    def extract_investment_companies(self) -> Dict:
        """提取参股/合营/联营公司信息"""
        print("\n提取投资公司信息...")

        investments = {
            'associates': [],    # 联营公司
            'joint_ventures': [],  # 合营公司
            'financial': [],      # 金融投资
            'all_investments': []
        }

        # 从年报长期股权投资章节提取
        if 'annual_report' in self.data and 'lt_equity' in self.data['annual_report']:
            content = self.data['annual_report']['lt_equity'].get('content', '')
            inv_companies = self._parse_investment_table(content)
            for inv in inv_companies:
                investments['all_investments'].append(inv)
                if '联营' in content:
                    investments['associates'].append(inv)
                elif '合营' in content:
                    investments['joint_ventures'].append(inv)
                else:
                    investments['financial'].append(inv)
        
        # 从已有的enhanced_company_info数据中补充
        if 'enhanced_company_info' in self.data:
            existing_data = self.data['enhanced_company_info']
            existing_invs = existing_data.get('investments', {}).get('all_investments', [])
            for inv in existing_invs:
                name = inv.get('name', '')
                if name and not any(i.get('name') == name for i in investments['all_investments']):
                    investments['all_investments'].append(inv)

        print(f"  提取到 {len(investments['all_investments'])} 个投资公司")
        return investments

    def _parse_investment_table(self, content: str) -> List[Dict]:
        """解析投资公司表格"""
        companies = []

        table_patterns = [
            r'([^\n\|]+)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)',
            r'([^\n\|]+)\|([^\n\|]*)\|([^\n\|]*)\|([^\n\|]*)',
        ]

        # 排除的关键词（非公司名称）
        exclude_keywords = [
            '公司名称', '序号', '项目', '合计', '小计', '总计', '备注', '说明',
            '比例', '持股', '出资', '金额', '币种', '注册地', '业务性质'
        ]

        for pattern in table_patterns:
            matches = re.findall(pattern, content)
            for match in matches:
                if len(match) >= 1:
                    name = match[0].strip()
                    if (name and len(name) > 2
                        and not any(kw in name for kw in exclude_keywords)
                        and not name.isdigit()):
                        inv_info = {
                            'name': name,
                            'source': 'annual_report',
                            'region': match[1].strip() if len(match) > 1 else '',
                            'business': match[2].strip() if len(match) > 2 else '',
                            'share_ratio': match[3].strip() if len(match) > 3 else ''
                        }
                        companies.append(inv_info)

        return companies

    def extract_ma_transactions(self) -> Dict:
        """从公告中提取重大交易/收购/并购历史"""
        print("\n提取重大交易/并购历史...")

        ma_info = {
            'acquisitions': [],     # 收购
            'divestitures': [],     # 出售
            'reorganizations': [],  # 重组
            'capital_operations': [],  # 资本运作
            'all_deals': []
        }

        # 从公告中提取
        announcements = []
        if 'results' in self.data and 'announcements' in self.data['results']['findings']:
            announcements = self.data['results']['findings']['announcements'].get('critical_announcements', [])
            announcements.extend(self.data['results']['findings']['announcements'].get('major_announcements', []))
        
        # 从已有的enhanced_company_info数据中补充
        if 'enhanced_company_info' in self.data:
            existing_data = self.data['enhanced_company_info']
            existing_deals = existing_data.get('ma_transactions', {}).get('all_deals', [])
            for deal in existing_deals:
                title = deal.get('title', '')
                if title and not any(d.get('title') == title for d in ma_info['all_deals']):
                    ma_info['all_deals'].append(deal)
                    deal_type = deal.get('type', '')
                    if deal_type == 'acquisition':
                        ma_info['acquisitions'].append(deal)
                    elif deal_type == 'divestiture':
                        ma_info['divestitures'].append(deal)
                    elif deal_type == 'reorganization':
                        ma_info['reorganizations'].append(deal)
                    elif deal_type == 'capital_operation':
                        ma_info['capital_operations'].append(deal)

        for ann in announcements:
            title = ann.get('title', '')
            category = ann.get('category', '')

            deal_type = None
            # 收购类
            if any(keyword in title or keyword in category for keyword in ['收购', '购买', '受让', '认购', '竞买', '拍得']):
                deal_type = 'acquisition'
            # 出售类
            elif any(keyword in title or keyword in category for keyword in ['出售', '转让', '剥离', '出让', '挂牌']):
                deal_type = 'divestiture'
            # 重组类
            elif any(keyword in title or keyword in category for keyword in ['重组', '并购', '重大资产', '借壳', '吸收合并', '分立']):
                deal_type = 'reorganization'
            # 资本运作类
            elif any(keyword in title or keyword in category for keyword in ['增资', '对外投资', '合资', '设立', '参股', '入股', '投资']):
                deal_type = 'capital_operation'

            if deal_type:
                deal = {
                    'title': title,
                    'date': ann.get('date', ''),
                    'type': deal_type,
                    'companies_involved': self._extract_company_names_from_announcement(ann)
                }

                # 尝试提取交易金额
                if 'extracted_content' in ann:
                    full_text = ann['extracted_content'].get('full_text_preview', '')
                    # 匹配多种金额格式
                    amount_patterns = [
                        r'([\d,]+(?:\.\d+)?)\s*(?:美元|USD)',
                        r'([\d,]+(?:\.\d+)?)\s*(?:人民币|元)',
                        r'([\d,]+(?:\.\d+)?)\s*(?:万元)',
                        r'([\d,]+(?:\.\d+)?)\s*(?:亿元)',
                        r'(?:约|共计|总计|合计)\s*([\d,]+(?:\.\d+)?)\s*(?:美元|USD|人民币|元|万元|亿元)',
                    ]
                    amounts = []
                    for pattern in amount_patterns:
                        matches = re.findall(pattern, full_text)
                        amounts.extend(matches)
                    if amounts:
                        # 去重并限制数量
                        unique_amounts = list(set(amounts))[:5]
                        deal['amounts'] = unique_amounts

                ma_info['all_deals'].append(deal)

                if deal_type == 'acquisition':
                    ma_info['acquisitions'].append(deal)
                elif deal_type == 'divestiture':
                    ma_info['divestitures'].append(deal)
                elif deal_type == 'reorganization':
                    ma_info['reorganizations'].append(deal)
                elif deal_type == 'capital_operation':
                    ma_info['capital_operations'].append(deal)

        print(f"  提取到 {len(ma_info['all_deals'])} 个重大交易")
        print(f"  收购: {len(ma_info['acquisitions'])} 个")
        print(f"  出售: {len(ma_info['divestitures'])} 个")
        print(f"  重组: {len(ma_info['reorganizations'])} 个")
        return ma_info

    def build_related_companies_graph(self, subsidiaries: Dict, investments: Dict, ma_info: Dict) -> Dict:
        """构建关联公司图谱"""
        print("\n构建关联公司图谱...")

        graph = {
            'center_node': {
                'name': '上市公司',
                'stock_code': self.stock_code
            },
            'nodes': [],
            'edges': []
        }

        # 添加子公司节点
        for sub in subsidiaries['full_list']:
            name = sub.get('name', '')
            if name:
                graph['nodes'].append({
                    'name': name,
                    'type': '子公司',
                    'category': 'domestic' if sub in subsidiaries['domestic'] else 'overseas',
                    'source': sub.get('source', '')
                })
                graph['edges'].append({
                    'from': '上市公司',
                    'to': name,
                    'relation': '控股'
                })

        # 添加投资公司节点
        for inv in investments['all_investments']:
            name = inv.get('name', '')
            if name:
                graph['nodes'].append({
                    'name': name,
                    'type': '参股/合营/联营',
                    'source': inv.get('source', '')
                })
                graph['edges'].append({
                    'from': '上市公司',
                    'to': name,
                    'relation': '参股'
                })

        # 添加交易涉及的公司
        for deal in ma_info['all_deals']:
            for comp in deal.get('companies_involved', []):
                if comp and not any(node['name'] == comp for node in graph['nodes']):
                    graph['nodes'].append({
                        'name': comp,
                        'type': '交易方',
                        'source': 'announcement'
                    })

        # 去重节点
        unique_nodes = []
        seen_names = set()
        for node in graph['nodes']:
            name = node.get('name', '')
            if name and name not in seen_names:
                seen_names.add(name)
                unique_nodes.append(node)
        graph['nodes'] = unique_nodes

        # 统计信息
        node_types = {}
        for node in unique_nodes:
            node_type = node.get('type', '未知')
            node_types[node_type] = node_types.get(node_type, 0) + 1
        
        print(f"  图谱包含 {len(unique_nodes)} 个节点, {len(graph['edges'])} 条边")
        for node_type, count in node_types.items():
            print(f"    - {node_type}: {count}个")

        return graph

    def generate_summary(self, subsidiaries: Dict, investments: Dict, ma_info: Dict, graph: Dict) -> str:
        """生成分析摘要"""
        parts = []

        # 子公司信息
        if subsidiaries['total_count'] > 0:
            parts.append(f"上市公司共有 {subsidiaries['total_count']} 家子公司")
            if subsidiaries['domestic']:
                parts.append(f"国内子公司 {len(subsidiaries['domestic'])} 家")
            if subsidiaries['overseas']:
                parts.append(f"海外子公司 {len(subsidiaries['overseas'])} 家")
            if subsidiaries['major_ones']:
                parts.append(f"重要子公司 {len(subsidiaries['major_ones'])} 家")

        # 投资公司信息
        if investments['all_investments']:
            parts.append(f"参股/合营/联营公司 {len(investments['all_investments'])} 家")
            if investments['associates']:
                parts.append(f"联营公司 {len(investments['associates'])} 家")
            if investments['joint_ventures']:
                parts.append(f"合营公司 {len(investments['joint_ventures'])} 家")

        # 重大交易信息
        if ma_info['all_deals']:
            parts.append(f"累计进行 {len(ma_info['all_deals'])} 次重大资本运作")
            if ma_info['acquisitions']:
                parts.append(f"收购 {len(ma_info['acquisitions'])} 笔")
            if ma_info['divestitures']:
                parts.append(f"出售 {len(ma_info['divestitures'])} 笔")
            if ma_info['reorganizations']:
                parts.append(f"重组 {len(ma_info['reorganizations'])} 笔")
            if ma_info['capital_operations']:
                parts.append(f"资本运作 {len(ma_info['capital_operations'])} 笔")

        # 关联公司图谱信息
        if graph['nodes']:
            parts.append(f"关联公司图谱包含 {len(graph['nodes'])} 个节点")

        if len(parts) == 0:
            return "已完成公司关联关系分析，未发现重要关联信息"

        return "；".join(parts)

    def extract_all_info(self) -> Dict:
        """执行完整的信息提取"""
        print(f"\n{'='*60}")
        print(f"增强的公司信息提取 - {self.stock_code}")
        print(f"{'='*60}")

        self.load_data()

        subsidiaries = self.extract_subsidiaries()
        investments = self.extract_investment_companies()
        ma_info = self.extract_ma_transactions()
        graph = self.build_related_companies_graph(subsidiaries, investments, ma_info)
        summary = self.generate_summary(subsidiaries, investments, ma_info, graph)

        self.results = {
            'stock_code': self.stock_code,
            'market': self.market,
            'extracted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'subsidiaries': subsidiaries,
            'investments': investments,
            'ma_transactions': ma_info,
            'related_companies_graph': graph,
            'summary': summary
        }

        return self.results

    def save(self, output_dir: str = None):
        """保存结果"""
        if output_dir is None:
            output_dir = self.data_dir

        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, 'enhanced_company_info.json')

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        print(f"\n✓ 结果已保存到: {output_file}")


def main(stock_code: str, market: str, data_dir: str) -> Dict:
    """主函数"""
    extractor = EnhancedCompanyInfoExtractor(stock_code, market, data_dir)
    results = extractor.extract_all_info()
    extractor.save()

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"提取摘要")
    print(f"{'='*60}")
    print(f"子公司总数: {results['subsidiaries']['total_count']}")
    print(f"投资公司总数: {len(results['investments']['all_investments'])}")
    print(f"重大交易总数: {len(results['ma_transactions']['all_deals'])}")
    print(f"关联公司图谱节点: {len(results['related_companies_graph']['nodes'])}")
    print(f"\n{results['summary']}")

    return results


if __name__ == '__main__':
    if len(sys.argv) >= 4:
        main(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("用法: python enhanced_company_info_extractor.py <股票代码> <市场> <数据目录>")


def generate_report_section(data: Dict) -> List[str]:
    """生成增强公司信息提取的报告章节"""
    lines = []
    lines.append("## 增强的公司信息提取")
    lines.append("")

    if not data:
        lines.append("*增强公司信息数据未获取*")
        lines.append("")
        return lines

    # 摘要信息
    summary = data.get('summary', '')
    if summary:
        lines.append(f"**分析摘要**: {summary}")
        lines.append("")

    # 子公司信息
    subsidiaries = data.get('subsidiaries', {})
    if subsidiaries:
        total = subsidiaries.get('total_count', 0)
        domestic = len(subsidiaries.get('domestic', []))
        overseas = len(subsidiaries.get('overseas', []))
        major = len(subsidiaries.get('major_ones', []))

        lines.append(f"### 子公司概况")
        lines.append(f"- **总数**: {total}家")
        lines.append(f"- **国内**: {domestic}家")
        lines.append(f"- **海外**: {overseas}家")
        lines.append(f"- **重要子公司**: {major}家")
        lines.append("")

        # 重要子公司列表
        if major > 0:
            lines.append(f"### 重要子公司")
            lines.append("")
            lines.append("| 名称 | 类型 | 业务 | 注册资本 | 总资产 | 净资产 | 营收 |")
            lines.append("|------|------|------|----------|--------|--------|------|")
            for sub in subsidiaries.get('major_ones', [])[:10]:
                name = sub.get('name', '')
                sub_type = sub.get('type', '')
                business = sub.get('business', '')
                registered_capital = sub.get('registered_capital', '')
                total_asset = sub.get('total_asset', '')
                net_asset = sub.get('net_asset', '')
                revenue = sub.get('revenue', '')
                lines.append(f"| {name} | {sub_type} | {business} | {registered_capital} | {total_asset} | {net_asset} | {revenue} |")
            lines.append("")

    # 投资公司信息
    investments = data.get('investments', {})
    if investments:
        total = len(investments.get('all_investments', []))
        associates = len(investments.get('associates', []))
        joint_ventures = len(investments.get('joint_ventures', []))

        lines.append(f"### 投资公司概况")
        lines.append(f"- **总数**: {total}家")
        lines.append(f"- **联营公司**: {associates}家")
        lines.append(f"- **合营公司**: {joint_ventures}家")
        lines.append("")

    # 重大交易/并购历史
    ma_info = data.get('ma_transactions', {})
    if ma_info:
        total = len(ma_info.get('all_deals', []))
        acquisitions = len(ma_info.get('acquisitions', []))
        divestitures = len(ma_info.get('divestitures', []))
        reorganizations = len(ma_info.get('reorganizations', []))
        capital_operations = len(ma_info.get('capital_operations', []))

        lines.append(f"### 重大交易/并购历史")
        lines.append(f"- **总数**: {total}笔")
        lines.append(f"- **收购**: {acquisitions}笔")
        lines.append(f"- **出售**: {divestitures}笔")
        lines.append(f"- **重组**: {reorganizations}笔")
        lines.append(f"- **资本运作**: {capital_operations}笔")
        lines.append("")

        # 交易明细
        if total > 0:
            lines.append(f"### 交易明细")
            lines.append("")
            for deal in ma_info.get('all_deals', [])[:10]:
                title = deal.get('title', '')
                date = deal.get('date', '')
                deal_type = deal.get('type', '')
                companies = ', '.join(deal.get('companies_involved', []))
                amounts = ', '.join(deal.get('amounts', []))

                type_map = {
                    'acquisition': '收购',
                    'divestiture': '出售',
                    'reorganization': '重组',
                    'capital_operation': '资本运作'
                }
                type_label = type_map.get(deal_type, deal_type)

                lines.append(f"- **{date}** [{type_label}] {title}")
                if companies:
                    lines.append(f"  - 涉及公司: {companies}")
                if amounts:
                    lines.append(f"  - 交易金额: {amounts}")
            lines.append("")

    # 关联公司图谱
    graph = data.get('related_companies_graph', {})
    if graph:
        nodes = len(graph.get('nodes', []))
        edges = len(graph.get('edges', []))

        lines.append(f"### 关联公司图谱")
        lines.append(f"- **节点数**: {nodes}个")
        lines.append(f"- **边数**: {edges}条")
        lines.append("")

    return lines
