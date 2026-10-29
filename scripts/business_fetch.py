# -*- coding: utf-8 -*-
"""
business_fetch.py - 商业模式/产品/渠道/市场份额数据抓取模块

功能：
1. 复用 strategic_opportunity 已提取的品牌数据（品牌名、IDC、荣誉、覆盖范围）
2. 基于具体品牌名生成精准电商/行业搜索查询
3. 从互动易获取渠道/招商模式信息
4. 综合商业模式分析

用法：
    from business_fetch import fetch_business_intel
    
    result = fetch_business_intel(
        stock_code='000001',
        company_name='示例公司',
        market='a',
        strategic_opportunity=findings.get('strategic_opportunity')
    )
"""
import sys, os, json, re, time
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def fetch_business_intel(stock_code, company_name='', market='a',
                         sse_qa_data=None, szse_qa_data=None,
                         strategic_opportunity=None):
    """
    主函数：商业模式/产品/渠道/市场份额数据抓取
    
    Args:
        stock_code: 股票代码
        company_name: 公司名称
        market: 市场类型 (a/hk/us)
        sse_qa_data: 上证e互动原始数据
        szse_qa_data: 深交所互动易原始数据
        strategic_opportunity: strategic_opportunity模块的findings数据
    
    Returns:
        dict
    """
    result = {
        'stock_code': stock_code,
        'company_name': company_name,
        'fetch_time': datetime.now().isoformat(),
        'brand_data': {},
        'product_searches': [],
        'industry_searches': [],
        'investor_qa': {},
        'business_model': {},
        'summary': '',
        'warnings': [],
        'data_sources': [],
    }
    
    # ─── 核心：复用 strategic_opportunity 品牌数据 ───
    brand_data = _extract_brand_from_strategic(strategic_opportunity)
    result['brand_data'] = brand_data
    
    if brand_data.get('brand_names'):
        result['data_sources'].append('年报品牌数据')
    
    # ─── 基于品牌名生成精准搜索 ───
    brand_names = brand_data.get('brand_names', [])
    if brand_names:
        result['product_searches'] = _generate_product_searches(brand_names, company_name)
        result['industry_searches'] = _generate_industry_searches(brand_names, company_name)
    
    # ─── 互动易数据整合 ───
    qa_data = _integrate_qa_data(stock_code, market, sse_qa_data, szse_qa_data)
    result['investor_qa'] = qa_data
    if qa_data.get('hot_questions'):
        result['data_sources'].append('互动易')
    
    # ─── 综合商业模式分析 ───
    result['business_model'] = _analyze_business_model(result, brand_data)
    
    # ─── 生成摘要 ───
    result['summary'] = _generate_summary(result)
    
    return result


# ─── 模块1：从 strategic_opportunity 提取品牌数据 ─────

def _extract_brand_from_strategic(strategic_opportunity):
    """
    从 strategic_opportunity 的 findings 中提取品牌数据
    
    数据来源：strategic_opportunity.py 的 _parse_brand() 输出
    """
    brand_data = {
        'brand_names': [],
        'brand_strategy': '',
        'idc_data': '',
        'industry_ranking': '',
        'honors_awards': [],
        'brand_coverage': '',
        'market_share_hint': '',
    }
    
    if not strategic_opportunity:
        return brand_data
    
    # 从 dimensions.brand_equity 提取
    dims = strategic_opportunity.get('dimensions', {})
    brand_equity = dims.get('brand_equity', {})
    
    if brand_equity:
        brand_data['brand_names'] = brand_equity.get('brand_names', [])
        brand_data['brand_strategy'] = brand_equity.get('brand_strategy', '')
        brand_data['idc_data'] = brand_equity.get('idc_data', '')
        brand_data['industry_ranking'] = brand_equity.get('industry_ranking', '')
        brand_data['honors_awards'] = brand_equity.get('honors_awards', [])
        brand_data['brand_coverage'] = brand_equity.get('brand_coverage', '')
        brand_data['market_share_hint'] = brand_equity.get('market_share_hint', '')
    
    return brand_data


# ─── 模块2：基于品牌名生成精准电商搜索 ─────────────────

def _generate_product_searches(brand_names, company_name):
    """
    基于具体品牌名生成电商搜索查询
    
    例如：品牌名=["奔图","极海","G&G"] →
    - "奔图 打印机 京东 价格 销量"
    - "极海 芯片 天猫 旗舰店"
    - "G&G 打印耗材 电商平台"
    """
    searches = []
    
    # 产品类型关键词（根据品牌名推断）
    # 通用产品类型推断（基于品牌名关键词，不绑定特定公司）
    product_type_map = {
        '打印机': '打印机',
        '芯片': '芯片 MCU',
        '耗材': '打印耗材',
        '硒鼓': '硒鼓 墨盒',
        '墨盒': '硒鼓 墨盒',
    }
    
    for brand in brand_names[:5]:  # 最多5个品牌
        # 推断产品类型
        product_type = ''
        for key, ptype in product_type_map.items():
            if key in brand or brand in key:
                product_type = ptype
                break
        
        if product_type:
            searches.append({
                'brand': brand,
                'query': f'{brand} {product_type} 京东 价格',
                'platform': '京东',
                'purpose': f'查询{brand}品牌{product_type}的价格和销量',
            })
            searches.append({
                'brand': brand,
                'query': f'{brand} {product_type} 天猫 旗舰店',
                'platform': '天猫',
                'purpose': f'查询{brand}品牌天猫旗舰店销售数据',
            })
        else:
            searches.append({
                'brand': brand,
                'query': f'{brand} 京东 价格 销量',
                'platform': '京东',
                'purpose': f'查询{brand}品牌产品价格和销量',
            })
    
    return searches


# ─── 模块3：基于品牌名生成精准行业搜索 ─────────────────

def _generate_industry_searches(brand_names, company_name):
    """
    基于具体品牌名生成行业排名/市场份额搜索
    
    例如：品牌名=["奔图"] →
    - "奔图 激光打印机 市场份额 2025"
    - "奔图 打印机 行业排名 IDC"
    """
    searches = []
    
    # 基于品牌名关键词推断行业分类（通用，不绑定特定公司）
    printer_brands = [b for b in brand_names if any(kw in b for kw in ['打印', 'printer', '印刷'])]
    chip_brands = [b for b in brand_names if any(kw in b for kw in ['芯片', 'chip', 'MCU', '半导体'])]
    consumable_brands = [b for b in brand_names if any(kw in b for kw in ['耗材', '硒鼓', '墨盒', '碳粉'])]
    
    for brand in printer_brands[:2]:
        searches.append({
            'brand': brand,
            'query': f'{brand} 激光打印机 市场份额 2025',
            'purpose': f'查询{brand}在激光打印机市场的份额',
        })
        searches.append({
            'brand': brand,
            'query': f'{brand} IDC 打印机 出货量 排名',
            'purpose': f'查询{brand}在IDC打印机出货量排名',
        })
    
    for brand in chip_brands[:2]:
        searches.append({
            'brand': brand,
            'query': f'{brand} MCU 芯片 市场份额 行业排名',
            'purpose': f'查询{brand}在MCU芯片市场的份额',
        })
    
    for brand in consumable_brands[:2]:
        searches.append({
            'brand': brand,
            'query': f'{brand} 打印耗材 市场份额 排名',
            'purpose': f'查询{brand}在打印耗材市场的份额',
        })
    
    return searches


# ─── 模块4：互动易数据整合 ─────────────────────────────

def _integrate_qa_data(stock_code, market, sse_qa_data=None, szse_qa_data=None):
    """
    整合互动易问答数据，提取商业模式/渠道/招商信息
    """
    result = {
        'hot_questions': [],
        'business_model_qa': [],
        'channel_qa': [],
        'product_qa': [],
        'competition_qa': [],
        'summary': {},
        'source': 'investor_qa',
    }
    
    biz_keywords = ['商业模式', '盈利模式', '收入模式', '怎么赚钱', '靠什么赚钱',
                     '主营业务', '核心业务', '业务模式']
    channel_keywords = ['渠道', '经销', '直销', '代理', '招商', '加盟',
                         '销售模式', '销售网络', '电商', '线上线下']
    product_keywords = ['产品', '新品', '产品线', '产品系列', '核心产品',
                         '拳头产品', '主力产品', '技术', '研发']
    competition_keywords = ['竞争', '对手', '竞品', '市场份额', '市占率',
                             '行业地位', '龙头', '领先', '排名']
    
    for qa_data_src in [sse_qa_data, szse_qa_data]:
        if not qa_data_src:
            continue
        qa_list = qa_data_src if isinstance(qa_data_src, list) else qa_data_src.get('qa_list', [])
        source_name = '上证e互动' if qa_data_src == sse_qa_data else '深交所互动易'
        
        for qa in qa_list:
            question = qa.get('question', '') or qa.get('content', '')
            answer = qa.get('answer', '') or qa.get('reply', '')
            full_text = f'{question} {answer}'
            
            record = {
                'question': question[:200],
                'answer': answer[:500],
                'date': qa.get('date', ''),
                'source': source_name,
            }
            
            if any(kw in full_text for kw in biz_keywords):
                result['business_model_qa'].append(record)
            if any(kw in full_text for kw in channel_keywords):
                result['channel_qa'].append(record)
            if any(kw in full_text for kw in product_keywords):
                result['product_qa'].append(record)
            if any(kw in full_text for kw in competition_keywords):
                result['competition_qa'].append(record)
    
    result['summary'] = {
        'total_qa': len(result['business_model_qa']) + len(result['channel_qa']) +
                    len(result['product_qa']) + len(result['competition_qa']),
        'biz_model_count': len(result['business_model_qa']),
        'channel_count': len(result['channel_qa']),
        'product_count': len(result['product_qa']),
        'competition_count': len(result['competition_qa']),
    }
    
    return result


# ─── 模块5：商业模式综合分析 ─────────────────────────

def _analyze_business_model(result, brand_data):
    """
    综合分析商业模式（基于品牌数据+互动易）
    """
    biz_model = {
        'revenue_model': '',
        'customer_type': '',
        'sales_channel': '',
        'competitive_barrier': '',
        'product_positioning': '',
        'key_metrics': {},
    }
    
    # 从品牌数据推断商业模式
    brand_names = brand_data.get('brand_names', [])
    brand_strategy = brand_data.get('brand_strategy', '')
    idc_data = brand_data.get('idc_data', '')
    brand_coverage = brand_data.get('brand_coverage', '')
    
    # 收入模式：基于品牌列表推断
    if brand_names:
        # 打印机+芯片+耗材 = 硬件+耗材的"剃须刀模式"
        has_printer = any('打印' in b or 'printer' in b.lower() for b in brand_names)
        has_chip = any('芯片' in b or 'chip' in b.lower() or 'MCU' in b for b in brand_names)
        has_consumable = any('耗材' in b or '硒鼓' in b or '墨盒' in b for b in brand_names)
        
        if has_printer and has_consumable:
            biz_model['revenue_model'] = '硬件+耗材（剃须刀模式）'
        elif has_printer:
            biz_model['revenue_model'] = '硬件销售'
        elif has_chip:
            biz_model['revenue_model'] = '芯片设计/销售'
    
    # 客户类型
    if brand_strategy:
        if '全球' in brand_strategy or '150' in brand_strategy:
            biz_model['customer_type'] = '全球企业+消费者'
        elif '企业' in brand_strategy:
            biz_model['customer_type'] = 'To B'
    
    # 销售渠道
    if brand_coverage:
        if '150' in brand_coverage or '全球' in brand_coverage:
            biz_model['sales_channel'] = '全球经销网络（150+国家和地区）'
    
    # 竞争壁垒
    barriers = []
    if brand_names and len(brand_names) >= 3:
        barriers.append(f'多品牌矩阵（{len(brand_names)}个品牌）')
    if '全产业链' in brand_strategy or '覆盖' in brand_strategy:
        barriers.append('打印产业链全覆盖')
    if '中高端' in brand_strategy:
        barriers.append('中高端产品定位')
    if idc_data:
        barriers.append('IDC市场份额数据支撑')
    biz_model['competitive_barrier'] = '；'.join(barriers) if barriers else '待确认'
    
    # 产品定位
    if '中高端' in brand_strategy:
        biz_model['product_positioning'] = '中高端市场'
    
    return biz_model


# ─── 模块6：Markdown报告生成 ─────────────────────────

def _generate_summary(result):
    """生成Markdown摘要（基于实际品牌数据）"""
    lines = []
    company = result.get('company_name', '未知')
    
    lines.append(f'### 商业模式与市场情报（{company}）')
    lines.append('')
    
    # ─── 品牌矩阵 ───
    brand_data = result.get('brand_data', {})
    brand_names = brand_data.get('brand_names', [])
    if brand_names:
        lines.append('**品牌矩阵**：')
        for b in brand_names:
            lines.append(f'- {b}')
        lines.append('')
    
    # ─── 品牌战略 ───
    brand_strategy = brand_data.get('brand_strategy', '')
    if brand_strategy:
        lines.append('**品牌战略**：')
        # 取前300字
        lines.append(brand_strategy[:300] + ('...' if len(brand_strategy) > 300 else ''))
        lines.append('')
    
    # ─── IDC/市场份额数据 ───
    idc_data = brand_data.get('idc_data', '')
    if idc_data:
        lines.append('**IDC/市场份额数据**：')
        lines.append(idc_data[:300])
        lines.append('')
    
    # ─── 品牌覆盖范围 ───
    brand_coverage = brand_data.get('brand_coverage', '')
    if brand_coverage:
        lines.append('**品牌覆盖**：')
        lines.append(brand_coverage[:200])
        lines.append('')
    
    # ─── 荣誉奖项 ───
    honors = brand_data.get('honors_awards', [])
    if honors:
        lines.append('**荣誉奖项**：')
        for h in honors[:5]:
            lines.append(f'- {h}')
        lines.append('')
    
    # ─── 商业模式 ───
    biz_model = result.get('business_model', {})
    if biz_model.get('revenue_model'):
        lines.append('**商业模式**：')
        lines.append(f'- 收入模式：{biz_model["revenue_model"]}')
        if biz_model.get('customer_type'):
            lines.append(f'- 客户类型：{biz_model["customer_type"]}')
        if biz_model.get('sales_channel'):
            lines.append(f'- 销售渠道：{biz_model["sales_channel"]}')
        if biz_model.get('competitive_barrier'):
            lines.append(f'- 竞争壁垒：{biz_model["competitive_barrier"]}')
        if biz_model.get('product_positioning'):
            lines.append(f'- 产品定位：{biz_model["product_positioning"]}')
        lines.append('')
    
    # ─── 互动易问答摘要 ───
    qa_data = result.get('investor_qa', {})
    qa_summary = qa_data.get('summary', {})
    if qa_summary.get('total_qa', 0) > 0:
        lines.append('**投资者互动**：')
        lines.append(f'- 商业模式相关问答：{qa_summary.get("biz_model_count", 0)}条')
        lines.append(f'- 渠道/招商问答：{qa_summary.get("channel_count", 0)}条')
        lines.append(f'- 产品/技术问答：{qa_summary.get("product_count", 0)}条')
        lines.append(f'- 竞争格局问答：{qa_summary.get("competition_count", 0)}条')
        lines.append('')
    
    # ─── 精准搜索建议（基于品牌名） ───
    product_searches = result.get('product_searches', [])
    industry_searches = result.get('industry_searches', [])
    if product_searches or industry_searches:
        lines.append('**联网搜索建议**：')
        for s in (product_searches + industry_searches)[:8]:
            lines.append(f'- {s["query"]}')
        lines.append('')
    
    # ─── 数据来源 ───
    sources = result.get('data_sources', [])
    if sources:
        lines.append(f'> 📊 数据来源：{", ".join(sources)}')
    
    lines.append('> ⚠️ 以上数据基于年报MD&A章节提取，商业模式分析需结合行业研究报告。')
    lines.append('')
    
    return '\n'.join(lines)


# ─── 模块7：格式化输出 ─────────────────────────────

def format_markdown(result):
    """格式化为Markdown报告"""
    return result.get('summary', '')


def format_json(result):
    """格式化为JSON"""
    return json.dumps(result, ensure_ascii=False, indent=2)


# ─── CLI入口 ─────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='商业模式/产品/渠道/市场份额数据抓取')
    parser.add_argument('--stock', required=True, help='股票代码')
    parser.add_argument('--name', default='', help='公司名称')
    parser.add_argument('--market', default='a', help='市场类型 (a/hk/us)')
    parser.add_argument('--output', default='', help='输出文件路径')
    
    args = parser.parse_args()
    
    result = fetch_business_intel(
        stock_code=args.stock,
        company_name=args.name,
        market=args.market
    )
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(format_markdown(result))
        print(f'报告已保存到: {args.output}')
    else:
        print(format_markdown(result))
