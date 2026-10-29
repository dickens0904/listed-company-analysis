# -*- coding: utf-8 -*-
"""
产品与产线基地介绍模块
从年报PDF、公告、通达信等数据源提取具体产品和生产设施信息
"""
import re
import sys
import os
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)

# ── 1. 数据提取 ──────────────────────────────────────────────────────────────

def extract_product_info(company_name: str, main_business: str, announcements: list = None, pdf_path: str = None) -> dict:
    """
    从多个数据源提取产品信息
    
    Args:
        company_name: 公司名称
        main_business: 主营业务描述（来自TDX或公司信息）
        announcements: 公告列表
        pdf_path: 年报PDF路径
    
    Returns:
        dict: 产品信息
    """
    result = {
        'company_name': company_name,
        'main_business': main_business,
        'products': [],
        'product_lines': [],
        'revenue_structure': {},
        'production_bases': [],
        'capacity_info': {},
    }
    
    # 1. 从主营业务描述提取产品线索
    if main_business:
        result['products'] = _extract_products_from_text(main_business)
    
    # 2. 从PDF提取详细产品和产线信息
    if pdf_path and os.path.exists(pdf_path):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(pdf_path)
            max_pages = min(30, doc.page_count)
            text_parts = []
            for i in range(max_pages):
                page = doc[i]
                text_parts.append(page.get_text())
            doc.close()
            pdf_text = '\n'.join(text_parts)
            if pdf_text:
                result['product_lines'] = _extract_product_lines_from_pdf(pdf_text)
                result['production_bases'] = _extract_production_bases_from_pdf(pdf_text)
                result['revenue_structure'] = _extract_revenue_structure_from_pdf(pdf_text)
        except Exception as e:
            print(f"  [产品模块] PDF提取失败: {e}", file=sys.stderr)
    
    # 3. 从公告提取产能和基地信息
    if announcements:
        base_info = _extract_from_announcements(announcements)
        if base_info.get('bases'):
            result['production_bases'].extend(base_info['bases'])
        if base_info.get('capacity'):
            result['capacity_info'].update(base_info['capacity'])
    
    # 4. 去重和排序
    result['products'] = _deduplicate_products(result['products'])
    result['production_bases'] = _deduplicate_bases(result['production_bases'])
    
    return result


def _extract_products_from_text(text: str) -> list:
    """从主营业务文本中提取产品信息"""
    products = []
    
    # 常见产品关键词模式
    patterns = [
        r'主要(?:产品|业务)[：:](.*?)(?:。|；|$)',
        r'(?:生产|制造|研发|销售)(.*?)(?:。|；|$)',
        r'(?:包括|涵盖)(.*?)(?:等|。|；|$)',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            # 分割产品
            items = re.split(r'[、，,；;]', match)
            for item in items:
                item = item.strip()
                if len(item) > 2 and len(item) < 20:
                    products.append({'name': item, 'source': '主营业务描述'})
    
    return products


def _extract_product_lines_from_pdf(pdf_text: str) -> list:
    """从PDF文本中提取产品线信息"""
    product_lines = []
    
    # 查找产品相关章节
    sections = _find_sections(pdf_text, ['产品', '业务', '主营业务', '产品与服务', '产品介绍'])
    
    for section in sections:
        # 提取产品线描述
        lines = section.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) > 10 and len(line) < 200:
                # 检查是否包含产品描述
                if any(keyword in line for keyword in ['产品', '业务', '系列', '型号', '规格']):
                    product_lines.append({
                        'description': line,
                        'source': '年报PDF'
                    })
    
    return product_lines


def _extract_production_bases_from_pdf(pdf_text: str) -> list:
    """从PDF文本中提取生产基地信息"""
    bases = []
    
    # 查找生产基地相关章节
    sections = _find_sections(pdf_text, ['生产基地', '生产设施', '工厂', '产业园区', '生产基地介绍'])
    
    # 地址模式
    address_patterns = [
        r'位于(.*?)(?:的|，|,)',
        r'(?:工厂|基地|园区|厂区)(?:位于|坐落在)(.*?)(?:，|,|。)',
        r'(?:地址|Location)[：:](.*?)(?:\n|$)',
    ]
    
    # 产能模式
    capacity_patterns = [
        r'(?:产能|产量|年产能)(?:为|达到?)(.*?)(?:，|,|。|$)',
        r'(?:占地面积|建筑面积)(?:为|约?)(.*?)(?:，|,|。|$)',
    ]
    
    for section in sections:
        # 提取地址
        for pattern in address_patterns:
            matches = re.findall(pattern, section)
            for match in matches:
                if len(match) > 5 and len(match) < 50:
                    bases.append({
                        'location': match.strip(),
                        'type': '生产基地',
                        'source': '年报PDF'
                    })
        
        # 提取产能信息
        for pattern in capacity_patterns:
            matches = re.findall(pattern, section)
            for match in matches:
                if len(match) > 3:
                    bases.append({
                        'capacity': match.strip(),
                        'type': '产能信息',
                        'source': '年报PDF'
                    })
    
    return bases


def _extract_revenue_structure_from_pdf(pdf_text: str) -> dict:
    """从PDF文本中提取收入结构"""
    structure = {}
    
    # 查找收入结构相关章节
    sections = _find_sections(pdf_text, ['收入结构', '营业收入构成', '分产品', '分业务'])
    
    for section in sections:
        # 提取收入占比
        ratio_pattern = r'([^\d]+?)(?:占|占比|收入占比)(?:为|约?)(\d+(?:\.\d+)?)[%％]'
        matches = re.findall(ratio_pattern, section)
        for name, ratio in matches:
            name = name.strip()
            if len(name) > 1 and len(name) < 20:
                structure[name] = float(ratio)
    
    return structure


def _extract_from_announcements(announcements: list) -> dict:
    """从公告中提取产能和基地信息"""
    result = {'bases': [], 'capacity': {}}
    
    for ann in announcements:
        title = ann.get('title', '')
        content = ann.get('content', '')
        
        # 检查是否与生产基地相关
        if any(keyword in title for keyword in ['基地', '工厂', '园区', '产能', '投产', '建设']):
            result['bases'].append({
                'title': title,
                'date': ann.get('date', ''),
                'source': '公告'
            })
    
    return result


def _find_sections(text: str, keywords: list) -> list:
    """在文本中查找包含关键词的章节"""
    sections = []
    
    for keyword in keywords:
        # 查找关键词出现的位置
        pattern = f'[^。]*?{keyword}[^。]*?。'
        matches = re.findall(pattern, text)
        sections.extend(matches)
    
    return sections


def _deduplicate_products(products: list) -> list:
    """去重产品列表"""
    seen = set()
    unique = []
    
    for product in products:
        name = product.get('name', '')
        if name and name not in seen:
            seen.add(name)
            unique.append(product)
    
    return unique


def _deduplicate_bases(bases: list) -> list:
    """去重生产基地列表"""
    seen = set()
    unique = []
    
    for base in bases:
        location = base.get('location', '') or base.get('title', '')
        if location and location not in seen:
            seen.add(location)
            unique.append(base)
    
    return unique


# ── 2. 分析功能 ──────────────────────────────────────────────────────────────

def analyze_product_and_production(company_name: str, main_business: str, 
                                   announcements: list = None, pdf_path: str = None,
                                   tdx_data: dict = None) -> dict:
    """
    分析产品与产线基地
    
    Args:
        company_name: 公司名称
        main_business: 主营业务描述
        announcements: 公告列表
        pdf_path: 年报PDF路径
        tdx_data: 通达信数据
    
    Returns:
        dict: 分析结果
    """
    # 提取产品信息
    result = extract_product_info(company_name, main_business, announcements, pdf_path)
    
    # 增强产品信息（使用TDX数据）
    if tdx_data and tdx_data.get('success'):
        result['tdx_products'] = tdx_data.get('product_structure', [])
        result['tdx_basic'] = tdx_data.get('basic_enhanced', {})
    
    return result


# ── 3. 报告生成 ──────────────────────────────────────────────────────────────

def generate_report_section(data: dict) -> list:
    """
    生成产品与产线基地介绍的报告章节
    
    Args:
        data: analyze_product_and_production 返回的数据
    
    Returns:
        list: Markdown格式的报告行
    """
    lines = []
    
    company_name = data.get('company_name', '')
    lines.append(f'## 产品与产线基地介绍')
    lines.append('')
    lines.append(f'### 公司: **{company_name}**')
    lines.append('')
    
    # 1. 主营业务概述
    main_business = data.get('main_business', '')
    if main_business:
        lines.append('### 主营业务')
        lines.append('')
        lines.append(f'> {main_business}')
        lines.append('')
    
    # 2. 产品构成（来自通达信）
    tdx_products = data.get('tdx_products', [])
    if tdx_products:
        lines.append('### 产品构成（按收入占比）')
        lines.append('')
        lines.append('| 产品 | 收入占比 | 对比占比 |')
        lines.append('|------|---------|---------|')
        for product in tdx_products:
            name = product.get('name', '')
            ratio = product.get('revenue_ratio', '')
            compare = product.get('compare_ratio', '')
            
            ratio_str = f'{ratio * 100:.2f}%' if isinstance(ratio, (int, float)) else str(ratio)
            compare_str = f'{compare * 100:.2f}%' if isinstance(compare, (int, float)) else str(compare) if compare else '-'
            
            lines.append(f'| {name} | {ratio_str} | {compare_str} |')
        lines.append('')
    
    # 3. 产品线详情
    product_lines = data.get('product_lines', [])
    if product_lines:
        lines.append('### 产品线详情')
        lines.append('')
        for pl in product_lines[:10]:
            desc = pl.get('description', '')
            source = pl.get('source', '')
            lines.append(f'- {desc} *（来源：{source}）*')
        lines.append('')
    
    # 4. 收入结构
    revenue_structure = data.get('revenue_structure', {})
    if revenue_structure:
        lines.append('### 收入结构')
        lines.append('')
        for name, ratio in revenue_structure.items():
            lines.append(f'- {name}: {ratio}%')
        lines.append('')
    
    # 5. 生产基地
    production_bases = data.get('production_bases', [])
    if production_bases:
        lines.append('### 生产基地')
        lines.append('')
        for base in production_bases:
            location = base.get('location', '') or base.get('title', '')
            base_type = base.get('type', '')
            capacity = base.get('capacity', '')
            source = base.get('source', '')
            
            if location:
                lines.append(f'- **{location}**')
                if base_type:
                    lines.append(f'  - 类型: {base_type}')
                if capacity:
                    lines.append(f'  - 产能: {capacity}')
                lines.append(f'  - 来源: {source}')
        lines.append('')
    
    # 6. 公司基本信息（来自通达信）
    tdx_basic = data.get('tdx_basic', {})
    if tdx_basic:
        lines.append('### 公司基本信息')
        lines.append('')
        
        employee_count = tdx_basic.get('employee_count', '')
        if employee_count:
            lines.append(f'- 员工人数: {employee_count}人')
        
        registered_capital = tdx_basic.get('registered_capital', '')
        if registered_capital:
            lines.append(f'- 注册资本: {registered_capital}万元')
        
        region = tdx_basic.get('region', '')
        if region:
            lines.append(f'- 所在地区: {region}')
        
        lines.append('')
    
    # 数据来源说明
    lines.append('---')
    lines.append('')
    lines.append('*数据来源：通达信、年报PDF、公告*')
    lines.append('')
    
    return lines


# ── 4. AI证据构建 ──────────────────────────────────────────────────────────────

def build_evidence_for_ai(data: dict) -> str:
    """
    为AI分析提供产品与产线基地证据
    
    Args:
        data: analyze_product_and_production 返回的数据
    
    Returns:
        str: 格式化的证据文本
    """
    sections = []
    
    company_name = data.get('company_name', '')
    
    # 1. 主营业务
    main_business = data.get('main_business', '')
    if main_business:
        sections.append(f'【主营业务】{main_business}')
    
    # 2. 产品构成
    tdx_products = data.get('tdx_products', [])
    if tdx_products:
        product_lines = ['【产品构成】']
        for product in tdx_products:
            name = product.get('name', '')
            ratio = product.get('revenue_ratio', '')
            if name and ratio:
                ratio_str = f'{ratio * 100:.1f}%' if isinstance(ratio, (int, float)) else str(ratio)
                product_lines.append(f'- {name}: 占比{ratio_str}')
        sections.append('\n'.join(product_lines))
    
    # 3. 生产基地
    production_bases = data.get('production_bases', [])
    if production_bases:
        base_lines = ['【生产基地】']
        for base in production_bases[:5]:
            location = base.get('location', '') or base.get('title', '')
            capacity = base.get('capacity', '')
            if location:
                base_lines.append(f'- {location}')
                if capacity:
                    base_lines.append(f'  产能: {capacity}')
        sections.append('\n'.join(base_lines))
    
    # 4. 员工规模
    tdx_basic = data.get('tdx_basic', {})
    if tdx_basic:
        employee_count = tdx_basic.get('employee_count', '')
        if employee_count:
            sections.append(f'【员工规模】{employee_count}人')
    
    return '\n\n'.join(sections) if sections else ''


# ── 5. 简化接口 ──────────────────────────────────────────────────────────────

def fetch_product_line_intro(stock_code: str, market: str = 'a', 
                             company_name: str = '', main_business: str = '',
                             announcements: list = None, pdf_path: str = None,
                             tdx_data: dict = None) -> dict:
    """
    获取产品与产线基地介绍（简化接口）
    
    Args:
        stock_code: 股票代码
        market: 市场类型
        company_name: 公司名称
        main_business: 主营业务描述
        announcements: 公告列表
        pdf_path: 年报PDF路径
        tdx_data: 通达信数据
    
    Returns:
        dict: 分析结果
    """
    # 如果没有提供公司信息，尝试从TDX获取
    if not company_name and market == 'a':
        try:
            from tdx_provider import enhance_with_tdx_data
            if not tdx_data:
                tdx_data = enhance_with_tdx_data(stock_code)
            if tdx_data and tdx_data.get('success'):
                company_name = tdx_data.get('basic_enhanced', {}).get('company_name', '')
                main_business = tdx_data.get('basic_enhanced', {}).get('main_business', '')
        except Exception as e:
            print(f"  [产品模块] TDX数据获取失败: {e}", file=sys.stderr)
    
    return analyze_product_and_production(
        company_name=company_name,
        main_business=main_business,
        announcements=announcements,
        pdf_path=pdf_path,
        tdx_data=tdx_data
    )


# ── 6. 测试 ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 测试示例
    result = fetch_product_line_intro(
        stock_code='300501',
        company_name='海顺新材',
        main_business='高阻隔包装材料研发、生产和销售',
        tdx_data={
            'success': True,
            'basic_enhanced': {
                'company_name': '海顺新材',
                'main_business': '高阻隔包装材料研发、生产和销售',
                'employee_count': '793',
                'registered_capital': '47597.2353',
                'region': '江苏',
            },
            'product_structure': [
                {'name': '软包装', 'revenue_ratio': 0.658, 'compare_ratio': 0.6532},
                {'name': '硬包装', 'revenue_ratio': 0.3157, 'compare_ratio': 0.3276},
            ],
        }
    )
    
    print("=== 产品与产线基地介绍 ===")
    report_lines = generate_report_section(result)
    for line in report_lines:
        print(line)
    
    print("\n=== AI证据 ===")
    evidence = build_evidence_for_ai(result)
    print(evidence)
