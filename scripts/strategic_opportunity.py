# -*- coding: utf-8 -*-
"""
strategic_opportunity.py - 战略机遇全景分析模块

用途：从年报MD&A章节提取8个经营分析维度的机遇面数据，
      与现有的风险雷达形成互补的"机遇雷达"。

8个维度：
1. 战略定位（愿景/核心竞争力）
2. 商业模式（收入模式/LTV/CAC/护城河）
3. 品牌资产（知名度/行业排名/舆情）
4. 产品矩阵（产品分类/定位/新品进展）
5. 渠道体系（直销/经销/电商/区域分布）
6. 供销体系（客户集中度/供应商稳定性）← 已有
7. 生产基地（工厂分布/产能利用率）← 已有
8. 产能扩张（募投项目/在建工程）← 已有

依赖：annual_extract.py（年报章节提取）
用法：
    from strategic_opportunity import StrategicOpportunityAnalyzer
    
    analyzer = StrategicOpportunityAnalyzer(annual_sections)
    result = analyzer.analyze()
"""
import os
import re
import sys
import json
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class StrategicOpportunityAnalyzer:
    """战略机遇全景分析器
    
    从年报MD&A和业务章节提取结构化的经营分析数据
    """
    
    # 战略定位关键词（用于从MD&A提取战略愿景）
    STRATEGY_KEYWORDS = [
        '战略', '愿景', '使命', '核心价值观', '发展目标',
        '核心竞争力', '竞争优势', '壁垒', '护城河',
        '行业地位', '市场地位', '龙头', '领先',
        '未来发展', '业务规划', '战略规划'
    ]
    
    # 商业模式关键词
    BUSINESS_MODEL_KEYWORDS = [
        '商业模式', '盈利模式', '收入结构', '收入来源',
        '客户类型', '客户群体', '目标客户',
        '销售模式', '销售渠道', '经销', '直销', '电商',
        '定价策略', '毛利', '附加值',
        'LTV', 'CAC', '客户生命周期', '获客成本',
        '复购率', '客户粘性', '会员'
    ]
    
    # 产品关键词
    PRODUCT_KEYWORDS = [
        '主要产品', '产品系列', '产品线', '产品结构',
        '新品', '新产品', '研发产品', '在研产品',
        '产品定位', '高端', '中端', '低端',
        '产品矩阵', '产品布局', '产品体系'
    ]
    
    # 渠道关键词
    CHANNEL_KEYWORDS = [
        '销售渠道', '销售网络', '销售模式', '渠道建设',
        '直销', '经销', '代理', '加盟', '电商', '线上', '线下',
        '区域布局', '销售区域', '国内市场', '海外市场', '出口',
        '经销商', '代理商', '渠道商', '终端客户'
    ]
    
    # 品牌关键词
    BRAND_KEYWORDS = [
        '品牌', '商标', '知名度', '美誉度',
        '行业排名', '市场份额', '市占率',
        '荣誉', '奖项', '认证', '专利'
    ]
    
    def __init__(self, annual_sections=None, mda_text=None, business_text=None):
        """
        初始化分析器
        
        Args:
            annual_sections: annual_extract.py提取的章节dict
            mda_text: MD&A章节原文（可选，优先从annual_sections获取）
            business_text: 业务描述原文（可选）
        """
        self.annual_sections = annual_sections or {}
        self.mda_text = mda_text or ''
        self.business_text = business_text or ''
        
        # 从annual_sections提取MD&A
        if not self.mda_text and 'mda' in self.annual_sections:
            self.mda_text = self.annual_sections['mda'].get('content', '')
        
        # 结果存储
        self.result = {
            'stock_code': '',
            'analyze_time': datetime.now().isoformat(),
            'dimensions': {},
            'summary': '',
            'opportunities': [],
            '_meta': {
                'source': 'annual_report_mda',
                'mda_length': len(self.mda_text),
                'version': '1.0.0'
            }
        }
    
    def analyze(self, stock_code='', financial_data=None):
        """
        执行完整分析
        
        Args:
            stock_code: 股票代码
            financial_data: 财务数据dict（用于补充商业模式分析）
        
        Returns:
            dict: 8个维度的分析结果
        """
        self.result['stock_code'] = stock_code
        self.financial_data = financial_data or {}
        
        # 1. 战略定位
        self.result['dimensions']['strategic_positioning'] = self._parse_strategy()
        
        # 2. 商业模式
        self.result['dimensions']['business_model'] = self._parse_business_model()
        
        # 3. 品牌资产
        self.result['dimensions']['brand_equity'] = self._parse_brand()
        
        # 4. 产品矩阵
        self.result['dimensions']['product_matrix'] = self._parse_products()
        
        # 5. 渠道体系
        self.result['dimensions']['channel_system'] = self._parse_channels()
        
        # 6-8 从已提取数据补充
        self._include_existing_dimensions()
        
        # 生成总结
        self._generate_summary()
        
        return self.result
    
    def _parse_strategy(self):
        """从MD&A提取战略定位"""
        result = {
            'vision': '',
            'core_competitiveness': [],
            'competitive_advantages': [],
            'development_goals': [],
            'industry_position': '',
            'raw_text': ''
        }
        
        if not self.mda_text:
            return result
        
        text = self.mda_text
        result['raw_text'] = text[:3000] if len(text) > 3000 else text
        
        # 提取愿景/使命
        vision_patterns = [
            r'(?:公司愿景|企业愿景|愿景)[：:]\s*([^\n。]+)',
            r'(?:公司使命|企业使命|使命)[：:]\s*([^\n。]+)',
            r'(?:核心价值观)[：:]\s*([^\n。]+)',
        ]
        for p in vision_patterns:
            m = re.search(p, text)
            if m:
                if not result['vision']:
                    result['vision'] = m.group(1).strip()
        
        # 提取核心竞争力
        comp_section = self._extract_section_by_keywords(
            text, ['核心竞争力', '竞争优势', '竞争壁垒'], max_chars=2000
        )
        if comp_section and '未找到' not in comp_section:
            # 提取要点（通常是编号列表）
            points = re.findall(r'[（(]?\d[)）][、.]?\s*([^\n（(]+)', comp_section)
            if points:
                result['core_competitiveness'] = [p.strip() for p in points[:5]]
            else:
                # 尝试其他格式
                sentences = re.split(r'[。\n]', comp_section)
                result['core_competitiveness'] = [
                    s.strip() for s in sentences if len(s.strip()) > 20
                ][:5]
        
        # 提取行业地位
        position_patterns = [
            r'(?:行业地位|市场地位)[：:]\s*([^\n。]+)',
            r'(公司是|企业是)([^\n，。]{2,20})(?:行业|领域|细分)',
            r'(在[^，。\n]{2,20})(?:行业|领域)(?:处于|具有)([^\n。]+)',
        ]
        for p in position_patterns:
            m = re.search(p, text)
            if m:
                pos = m.group(0) if len(m.groups()) == 1 else ''.join(m.groups())
                result['industry_position'] = pos.strip()
                break
        
        # 提取发展目标
        goal_section = self._extract_section_by_keywords(
            text, ['未来发展', '发展战略', '业务规划', '发展目标'], max_chars=1500
        )
        if goal_section and '未找到' not in goal_section:
            goals = re.findall(r'[（(]?\d[)）][、.]?\s*([^\n（(]+)', goal_section)
            result['development_goals'] = [g.strip() for g in goals[:5]]
        
        return result
    
    def _parse_business_model(self):
        """解析商业模式"""
        result = {
            'revenue_model': '',
            'customer_segments': [],
            'sales_model': '',
            'pricing_power': '',
            'moat_type': [],
            'ltv_cac_hint': '',
            'raw_text': ''
        }
        
        if not self.mda_text:
            return result
        
        text = self.mda_text
        result['raw_text'] = text[:2000] if len(text) > 2000 else text
        
        # 提取收入模式
        revenue_patterns = [
            r'(?:收入结构|收入来源|主营业务收入)[：:]\s*([^\n。]+)',
            r'(?:盈利模式|商业模式)[：:]\s*([^\n。]+)',
        ]
        for p in revenue_patterns:
            m = re.search(p, text)
            if m:
                result['revenue_model'] = m.group(1).strip()
                break
        
        # 提取客户类型
        customer_section = self._extract_section_by_keywords(
            text, ['客户类型', '客户群体', '目标客户', '主要客户'], max_chars=1000
        )
        if customer_section and '未找到' not in customer_section:
            customers = re.findall(r'[、，]([^、，。\n]{2,15})(?:客户|群体)', customer_section)
            result['customer_segments'] = [c.strip() for c in customers[:5]]
        
        # 提取销售模式（直销/经销等）
        sales_patterns = [
            r'(?:销售模式)[：:]\s*([^\n。]+)',
            r'(采用|实行)([^\n，。]{2,20})(?:销售|经销)',
        ]
        for p in sales_patterns:
            m = re.search(p, text)
            if m:
                sales = m.group(0) if len(m.groups()) == 1 else ''.join(m.groups())
                result['sales_model'] = sales.strip()
                break
        
        # 护城河类型（定性判断）
        moat_hints = {
            '技术壁垒': ['专利', '技术壁垒', '核心技术', '自主研发', '知识产权'],
            '品牌壁垒': ['品牌', '知名度', '美誉度', '品牌影响力'],
            '规模壁垒': ['规模', '产能', '成本优势', '规模效应'],
            '渠道壁垒': ['渠道', '销售网络', '终端', '经销商'],
            '牌照壁垒': ['牌照', '资质', '准入', '许可证'],
            '客户粘性': ['粘性', '复购', '客户忠诚', '转换成本'],
        }
        
        detected_moats = []
        for moat_type, keywords in moat_hints.items():
            for kw in keywords:
                if kw in text:
                    detected_moats.append(moat_type)
                    break
        result['moat_type'] = list(set(detected_moats))
        
        # LTV/CAC暗示（从财务数据推断）
        if self.financial_data:
            gross_margin = self.financial_data.get('gross_margin', 0)
            roe = self.financial_data.get('roe', 0)
            if gross_margin > 40 or roe > 15:
                result['ltv_cac_hint'] = '毛利率/ROE较高，可能具备较好的客户价值捕获能力'
        
        return result
    
    def _is_valid_product_name(self, name):
        """验证是否是有效的产品名称（过滤格式字符和乱码）"""
        if not name:
            return False
        name = name.strip()
        if len(name) < 4:
            return False
        # 过滤格式字符模式和上下文叙述
        bad_patterns = [
            r'^[》》]+$',          # 全书名号
            r'^[，，]+$',          # 全标点
            r'^[（(][^)）]{0,3}[)）]?版本',  # 版本引用如（V3.0）
            r'^相?较于',          # "相较于..."
            r'^(新增|新增了)',     # 新增了
            r'^[\s\n]+$',        # 纯空白
            r'版本|版$',          # 包含版本或结尾是版
            r'^\d',               # 以数字开头
            r'[、，。（）【】《》\u2000-\u206F\u3000-\u303F]',  # 包含格式标点
            # 排除上下文叙述（产品描述而非产品名）
            r'出货量|同比|下滑|增长|市场|行业|根据|预计|领域|需要|支撑|设计',  # 上下文叙述
            r'\d{4,}万',          # 含大量数字如"7,716万台"
            r'同比|预计|统计',     # 统计性描述
        ]
        for p in bad_patterns:
            if re.search(p, name):
                return False
        # 有效内容至少要包含中文或字母
        return bool(re.search(r'[\u4e00-\u9fff]|[a-zA-Z]', name))

    def _parse_products(self):
        """解析产品矩阵"""
        result = {
            'main_products': [],
            'product_categories': [],
            'new_products': [],
            'product_positioning': '',
            'raw_text': ''
        }
        
        if not self.mda_text:
            return result
        
        text = self.mda_text
        result['raw_text'] = text[:2000] if len(text) > 2000 else text
        
        # 提取主要产品（从"主要产品"或"产品系列"小节）
        product_section = self._extract_section_by_keywords(
            text, ['主要产品', '产品系列', '产品线', '产品结构', '产品布局'], max_chars=2000
        )
        if product_section and '未找到' not in product_section:
            # 优先找结构化列表
            products = re.findall(r'[（(]?\d[)）][、.]?\s*([\u4e00-\u9fff a-zA-Z][\u4e00-\u9fff a-zA-Z0-9 ]{3,29})', product_section)
            if products:
                valid = [p.strip() for p in products if self._is_valid_product_name(p)]
                result['main_products'] = valid[:8]
            else:
                # 降级：提取"公司主要产品包括X、Y、Z"模式
                include_match = re.search(r'(?:产品包括|产品涵盖|产品有|包括|主要涉及)([^。；。\n]{20,200})', product_section)
                if include_match:
                    raw = include_match.group(1)
                    parts = re.split(r'[、，,；]', raw)
                    valid = [p.strip() for p in parts if self._is_valid_product_name(p)]
                    result['main_products'] = valid[:8]
            
            # 如果仍然为空，尝试从更宽泛的年报业务章节提取
            if not result['main_products']:
                # 搜索产品相关关键词
                product_patterns = [
                    r'芯片[^。\n]{0,50}',      # 芯片类产品
                    r'打印机[^。\n]{0,30}',   # 打印机产品线
                    r'SoC[^。\n]{0,30}',      # SoC产品
                    r'MCU[^。\n]{0,30}',      # MCU产品
                ]
                found_products = []
                for p in product_patterns:
                    matches = re.findall(p, text)
                    for m in matches:
                        if self._is_valid_product_name(m):
                            found_products.append(m.strip())
                # 去重
                seen = set()
                for fp in found_products:
                    if fp not in seen and len(fp) >= 4:
                        seen.add(fp)
                        result['main_products'].append(fp)
                result['main_products'] = list(seen)[:8]
        
        # 提取新品（在研产品）
        new_section = self._extract_section_by_keywords(
            text, ['新产品', '新品', '在研产品', '研发产品', '正在开发', '储备产品'], max_chars=1500
        )
        if new_section and '未找到' not in new_section:
            new_products = re.findall(r'[（(]?\d[)）][、.]?\s*([\u4e00-\u9fff a-zA-Z][\u4e00-\u9fff a-zA-Z0-9 ]{3,29})', new_section)
            if new_products:
                valid = [p.strip() for p in new_products if self._is_valid_product_name(p)]
                result['new_products'] = valid[:5]
            else:
                # 提取"正在开发/在研"后的内容
                dev_match = re.search(r'(?:正在开发|在研|研发中)[^。\n]{0,100}', new_section)
                if dev_match:
                    result['new_products'] = [dev_match.group(0).strip()[:50]]
        
        # 产品定位描述
        pos_section = self._extract_section_by_keywords(
            text, ['产品定位', '市场定位', '品牌定位', '产品策略'], max_chars=800
        )
        if pos_section and '未找到' not in pos_section:
            # 取第一段完整描述
            sentences = re.split(r'[。\n]', pos_section)
            for s in sentences:
                s = s.strip()
                if len(s) > 15:
                    result['product_positioning'] = s
                    break
        
        return result
    
    def _parse_channels(self):
        """解析渠道体系"""
        result = {
            'channel_types': [],
            'sales_network': '',
            'regional_distribution': '',
            'online_offline_ratio': '',
            'raw_text': ''
        }
        
        if not self.mda_text:
            return result
        
        text = self.mda_text
        result['raw_text'] = text[:2000] if len(text) > 2000 else text
        
        # 渠道类型
        channel_types = []
        if '直销' in text:
            channel_types.append('直销')
        if '经销' in text or '代理商' in text or '加盟' in text:
            channel_types.append('经销/代理/加盟')
        if '电商' in text or '线上' in text or '网络销售' in text:
            channel_types.append('电商/线上')
        if '线下' in text or '实体店' in text or '门店' in text:
            channel_types.append('线下门店')
        result['channel_types'] = channel_types
        
        # 销售网络描述
        network_patterns = [
            r'(销售网络|销售渠道|营销网络)[：:]\s*([^\n。]+)',
            r'(覆盖)([^\n，。]{2,30})(?:区域|省市|城市)',
        ]
        for p in network_patterns:
            m = re.search(p, text)
            if m:
                result['sales_network'] = m.group(0).strip()
                break
        
        # 区域分布
        region_section = self._extract_section_by_keywords(
            text, ['区域布局', '销售区域', '国内市场', '海外市场', '出口'], max_chars=800
        )
        if region_section and '未找到' not in region_section:
            result['regional_distribution'] = region_section[:500]
        
        return result
    
    def _parse_brand(self):
        """解析品牌资产（增强版：提取品牌战略、IDC数据、品牌列表）"""
        result = {
            'brand_names': [],
            'brand_strategy': '',
            'idc_data': '',
            'industry_ranking': '',
            'honors_awards': [],
            'market_share_hint': '',
            'brand_coverage': '',
            'raw_text': ''
        }
        
        if not self.mda_text:
            return result
        
        text = self.mda_text
        result['raw_text'] = text[:2000] if len(text) > 2000 else text
        
        # 提取品牌名称（增强：支持引号格式）
        brand_patterns = [
            r'(?:品牌名称|自主品牌|主要品牌)[：:]\s*([^\n。]+)',
            r'[""]([^""]{2,10})[""](?:品牌)',
        ]
        for p in brand_patterns:
            m = re.search(p, text)
            if m:
                brands = m.group(1).split('、') if '、' in m.group(1) else [m.group(1)]
                result['brand_names'] = [b.strip() for b in brands][:5]
                break
        
        # 增强：从"拥有包括"段落提取品牌列表（如"奔图""极海""艾派克""G＆G""格之格"）
        brand_list_match = re.search(r'拥有(?:包括)?[：:]?([\s\S]{10,200})等多个', text)
        if brand_list_match:
            brand_text = brand_list_match.group(1)
            quoted_brands = re.findall(r'\u201c([^\u201d]+)\u201d', brand_text)
            if quoted_brands:
                result['brand_names'] = [b.strip() for b in quoted_brands][:8]
        
        # 品牌战略优势段落
        strategy_match = re.search(r'品牌战略优势[^\n]*([\s\S]{0,800}?)(?=\n\d|\n[一二三四五六七八九十]|\n二、|$)', text)
        if strategy_match:
            result['brand_strategy'] = strategy_match.group(0).strip()[:800]
        
        # IDC数据/市场份额
        idc_patterns = [
            r'IDC[^\n]*数据显示[^\n]*',
            r'(?:市场份额|市占率|出货量|出货金额)[^\n]*\d+[^\n]*',
            r'(?:激光打印机|打印机)[^\n]*(?:出货量|市场份额)[^\n]*',
        ]
        for p in idc_patterns:
            m = re.search(p, text)
            if m:
                result['idc_data'] = m.group(0).strip()[:500]
                break
        
        # 品牌覆盖范围
        coverage_match = re.search(r'(?:覆盖|业务覆盖|销售)[^\n]*(?:国家|地区|全球)[^\n]*', text)
        if coverage_match:
            result['brand_coverage'] = coverage_match.group(0).strip()[:200]
        
        # 行业排名
        rank_patterns = [
            r'(行业排名第|排名第|位居第)(\d+)(?:位|名)',
            r'(市场份额|市占率)([^\n，。]{0,50})',
            r'(行业领先|市场领先|国内领先)',
        ]
        for p in rank_patterns:
            m = re.search(p, text)
            if m:
                result['industry_ranking'] = m.group(0).strip()
                break
        
        # 荣誉奖项
        honors = re.findall(r'(?:荣获|获得|取得)([^，。\n]{5,30})(?:奖|认证|称号|荣誉)', text)
        result['honors_awards'] = [h.strip() for h in honors[:5]]
        
        return result


    def _extract_section_by_keywords(self, text, keywords, max_chars=2000):
        """从文本中提取包含关键词的段落"""
        for kw in keywords:
            if kw in text:
                # 找到关键词位置
                idx = text.find(kw)
                # 向前扩展找到段落开头
                start = max(0, idx - 50)
                # 向后扩展最多max_chars
                end = min(len(text), idx + max_chars)
                return text[start:end]
        return '[未找到相关内容]'
    
    def _include_existing_dimensions(self):
        """引入已提取的维度数据（供销体系、生产基地、产能扩张）"""
        # 供销体系
        if self.annual_sections:
            customers = self.annual_sections.get('top5_customers', {}).get('content', '')
            suppliers = self.annual_sections.get('top5_suppliers', {}).get('content', '')
            self.result['dimensions']['supply_chain'] = {
                'customers': customers[:1000] if customers else '',
                'suppliers': suppliers[:1000] if suppliers else '',
                'customer_concentration': '',
                'supplier_stability': '',
                'raw_text': f"{customers[:500]}\n\n{suppliers[:500]}"
            }
            
            # 生产基地
            capacity = self.annual_sections.get('capacity', {}).get('content', '')
            self.result['dimensions']['production_base'] = {
                'capacity_info': capacity[:1500] if capacity else '',
                'utilization_rate': '',
                'factory_distribution': '',
                'raw_text': capacity[:1000]
            }
            
            # 在建工程/产能扩张
            cip = self.annual_sections.get('cip', {}).get('content', '')
            self.result['dimensions']['capacity_expansion'] = {
                'projects_in_progress': cip[:1500] if cip else '',
                'fundraising_projects': '',
                'raw_text': cip[:1000]
            }
    
    def _generate_summary(self):
        """生成战略机遇总结"""
        dims = self.result['dimensions']
        
        summary_parts = []
        
        # 战略定位总结
        if dims.get('strategic_positioning', {}).get('vision'):
            summary_parts.append(f"愿景：{dims['strategic_positioning']['vision'][:50]}")
        
        # 核心竞争力
        comp = dims.get('strategic_positioning', {}).get('core_competitiveness', [])
        if comp:
            summary_parts.append(f"核心竞争力：{comp[0] if comp else ''}")
        
        # 商业模式
        if dims.get('business_model', {}).get('revenue_model'):
            summary_parts.append(f"盈利模式：{dims['business_model']['revenue_model'][:50]}")
        
        # 护城河
        moats = dims.get('business_model', {}).get('moat_type', [])
        if moats:
            summary_parts.append(f"护城河：{'+'.join(moats[:3])}")
        
        # 渠道类型
        channels = dims.get('channel_system', {}).get('channel_types', [])
        if channels:
            summary_parts.append(f"渠道模式：{'+'.join(channels)}")
        
        self.result['summary'] = '\n'.join(summary_parts) if summary_parts else '暂无有效战略机遇信息'
        
        # 生成机遇点列表
        opportunities = []
        
        if dims.get('strategic_positioning', {}).get('industry_position'):
            opportunities.append({
                'type': '行业地位',
                'content': dims['strategic_positioning']['industry_position'],
                'confidence': 'high'
            })
        
        for moat in dims.get('business_model', {}).get('moat_type', []):
            opportunities.append({
                'type': '护城河',
                'content': moat,
                'confidence': 'medium'
            })
        
        for product in dims.get('product_matrix', {}).get('new_products', [])[:3]:
            opportunities.append({
                'type': '新品储备',
                'content': product,
                'confidence': 'medium'
            })
        
        self.result['opportunities'] = opportunities

    def enrich_brand_from_search(self, stock_name=None):
        """
        通过联网搜索补充品牌资产数据（舆情/行业排名）
        
        Args:
            stock_name: 公司全称（用于搜索）
        """
        if not stock_name:
            return
        
        try:
            # 尝试导入skill的search模块
            search_module = None
            for imp in ['scripts.search_company', 'search', 'scripts.search']:
                try:
                    search_module = __import__(imp, fromlist=[''])
                    break
                except ImportError:
                    continue
            
            if search_module and hasattr(search_module, 'search_online'):
                # 执行品牌搜索
                brand_query = f"{stock_name} 品牌 排名 荣誉 奖项"
                results = search_module.search_online(brand_query, limit=3)
                
                brand_data = self.result['dimensions'].get('brand_equity', {})
                
                if results and not results.get('error'):
                    # 解析搜索结果补充行业排名
                    for r in results[:3]:
                        content = r.get('content', '') or r.get('snippet', '') or ''
                        if not brand_data.get('industry_ranking') and '排名' in content:
                            # 提取排名信息
                            rank_m = re.search(r'(?:行业排名第|排名第|第|位列)([一二三四五六七八九十\d]+)(?:位|名)', content)
                            if rank_m:
                                brand_data['industry_ranking'] = f"行业排名: {rank_m.group(0)}"
                        if '市占率' in content or '市场份额' in content:
                            share_m = re.search(r'市[场]?[份]?额[为：:]?([^。，\n]{5,30})', content)
                            if share_m:
                                brand_data['market_share_hint'] = share_m.group(1).strip()
                
                # 荣誉补充（如果年报已有，搜索结果不再覆盖）
                if not brand_data.get('honors_awards'):
                    honors_from_search = []
                    if results:
                        for r in results[:2]:
                            content = r.get('content', '') or r.get('snippet', '') or ''
                            # 搜索结果中包含的奖项
                            found_honors = re.findall(r'(?:荣获|获得)([^，。\n]{3,20})(?:奖|称号)', content)
                            honors_from_search.extend(found_honors)
                    brand_data['honors_awards'] = list(set(honors_from_search))[:3]
        except Exception as e:
            record_result(__name__, 'enrich_brand_from_search', e, note='静默降级')
            # 静默失败，不影响主流程
            pass


def analyze_strategic_opportunity(stock_code, data_dir=None, annual_sections=None, financial_data=None, stock_name=None):
    """
    便捷函数：执行战略机遇分析
    
    Args:
        stock_code: 股票代码
        data_dir: 数据目录（用于读取年报章节）
        annual_sections: 已提取的章节dict（优先使用）
        financial_data: 财务数据dict
    
    Returns:
        dict: 战略机遇分析结果
    """
    # 如果没有传入annual_sections，尝试从文件读取
    if not annual_sections and data_dir:
        sections_file = os.path.join(data_dir, 'annual_report_sections.json')
        if os.path.exists(sections_file):
            try:
                with open(sections_file, 'r', encoding='utf-8') as f:
                    annual_sections = json.load(f)
            except Exception as _sexc:
                record(__name__, 'analyze_strategic_opportunity', _sexc, note='静默降级')
                pass
    
    analyzer = StrategicOpportunityAnalyzer(annual_sections=annual_sections)
    return analyzer.analyze(stock_code=stock_code, financial_data=financial_data)


if __name__ == '__main__':
    # CLI测试
    import argparse
    parser = argparse.ArgumentParser(description='战略机遇全景分析')
    parser.add_argument('--stock', required=True, help='股票代码')
    parser.add_argument('--data-dir', help='数据目录')
    parser.add_argument('--output', help='输出文件路径')
    args = parser.parse_args()
    
    result = analyze_strategic_opportunity(args.stock, args.data_dir)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f'结果已保存到 {args.output}')
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
