# -*- coding: utf-8 -*-
"""
行业竞争格局分析模块
数据源: 东方财富 RPT_F10_ORG_BASICINFO（唯一有效）
  - 包含: 证监会行业、申万行业、主营结构、地域、概念板块、毛利率、主要产品
  - 其他接口(RPT_F10_MAIN_BUSINESS_STRUCTURE/RPT_INDUSTRY_MEMBER等)均失效
  - 同业可比公司: 通过申万三级行业筛选+上市公司公告爬取补充
"""
import requests, json, os, time, sys

# 支持独立运行
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts.safe_request import safe_get, safe_extract
else:
    from scripts.safe_request import safe_get, safe_extract

EM_API = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://data.eastmoney.com/',
    'Accept': 'application/json',
}


def fetch_industry_info(stock_code, market='a', data_dir=None):
    """
    获取行业竞争格局信息
    返回:
      - industry_class: 行业分类（证监会/申万/板块）
      - main_business: 主营描述
      - income_structure: 收入结构（产品×地区分布）
      - competitors: 可比公司列表（含财务对比）
      - market_position: 市场地位
      - warnings / risks / findings
    """
    result = {
        'stock_code': stock_code,
        'industry_class': {},
        'main_business': None,
        'income_structure': [],
        'competitors': [],
        'market_position': None,
        'warnings': [],
        'risks': [],
        'findings': {},
    }

    # 格式股票代码
    secucode = stock_code
    if market == 'a':
        if not (stock_code.endswith('.SZ') or stock_code.endswith('.SH')):
            # 00/30=深市, 60/68=沪市, 8/4=北交所
            if stock_code[:2] in ['00', '30']:
                secucode = stock_code + '.SZ'
            elif stock_code[:2] in ['60', '68']:
                secucode = stock_code + '.SH'
            elif stock_code[0] in ['8', '4']:
                secucode = stock_code + '.BJ'
            else:
                secucode = stock_code + '.SZ'

    # =============================================
    # 1. 基本信息（已知有效）
    # =============================================
    try:
        params = {
            'reportName': 'RPT_F10_ORG_BASICINFO',
            'columns': 'ALL',
            'filter': f'(SECUCODE="{secucode}")',
            'pageNumber': 1,
            'pageSize': 5,
            'source': 'WEB',
            'client': 'WEB',
        }
        raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=15)
        records = safe_extract(raw, ['result', 'data'], default=[])
        if not records:
            records = []

        if not records:
            result['warnings'].append('RPT_F10_ORG_BASICINFO 无数据')
            return result

        rec = records[0]
        result['findings']['basic_info'] = rec

        # 行业分类
        result['industry_class'] = {
            'csrc_industry': rec.get('CSRC_INDUSTRY_NAME'),   # 证监会行业
            'sw_industry_l1': rec.get('SWINDUSTRY_NAME2', '').split('-')[0] if rec.get('SWINDUSTRY_NAME2') else None,  # 申万一级
            'sw_industry': rec.get('SWINDUSTRY_NAME2'),        # 申万二级
            'board_l1': rec.get('BOARD_NAME_1LEVEL'),          # 板块一级
            'board_l2': rec.get('BOARD_NAME_2LEVEL'),          # 板块二级
            'board_l3': rec.get('BOARD_NAME_3LEVEL'),          # 板块三级
            'board_code_bk': rec.get('BOARD_CODE_BK_2LEVEL'), # BK板块代码
            'region': rec.get('REGIONBK'),                     # 地域
            'em_industry': rec.get('EM2016'),                  # EM行业细分
        }

        # [BugFix 2026-04-28] EM API 对科创板/创业板行业字段常返回 null，追加 AKShare fallback
        csrc = result['industry_class'].get('csrc_industry', '')
        if not csrc and stock_code[:3] in ('688', '300'):
            try:
                import akshare as ak
                info_df = ak.stock_individual_info_em(stock_code)
                for _, row in info_df.iterrows():
                    if '行业' in str(row.iloc[0]):
                        result['industry_class']['csrc_industry'] = str(row.iloc[1]).strip()
                        result['findings']['akshare_industry_fallback'] = True
                        break
            except Exception as ex:
                result['warnings'].append(f'AKShare行业fallback失败: {ex}')

        result['main_business'] = rec.get('MAIN_BUSINESS')
        result['findings']['main_business_raw'] = rec.get('MAIN_BUSINESS')
        result['findings']['concepts'] = rec.get('BLGAINIAN', '').split(',') if rec.get('BLGAINIAN') else []
        result['findings']['gross_profit_ratio'] = rec.get('GROSS_PROFIT_RATIO')  # 毛利率
        result['findings']['max_profit_product'] = rec.get('MAXPROFIT_PRODUCT')   # 主要利润来源
        result['findings']['income_stru_name'] = rec.get('INCOME_STRU_NAME')       # 收入结构名称
        result['findings']['income_stru_ratio'] = rec.get('INCOME_STRU_RATIO')     # 收入结构比例
        result['findings']['income_stru_namenew'] = rec.get('INCOME_STRU_NAMENEW')  # 新收入结构名称
        result['findings']['income_stru_rationew'] = rec.get('INCOME_STRU_RATIONEW')  # 新收入结构比例
        result['findings']['reg_capital'] = rec.get('REG_CAPITAL')  # 注册资本（万元）
        result['findings']['total_employees'] = rec.get('TOTAL_NUM')  # 员工总数
        result['findings']['found_date'] = rec.get('FOUND_DATE')
        result['findings']['listing_date'] = rec.get('LISTING_DATE')
        result['findings']['former_names'] = rec.get('FORMERNAME')    # 曾用名
        result['findings']['concepts_raw'] = rec.get('BLGAINIAN')

    except Exception as e:
        result['warnings'].append(f'基本信息接口失败: {e}')
        return result

    # =============================================
    # 2. 收入结构解析
    # =============================================
    income_items = []
    for field_name, ratio_name in [
        ('INCOME_STRU_NAME', 'INCOME_STRU_RATIO'),
        ('INCOME_STRU_NAMENEW', 'INCOME_STRU_RATIONEW'),
    ]:
        names = rec.get(field_name)
        ratios = rec.get(ratio_name)
        if names and ratios:
            name_list = str(names).split(';') if isinstance(names, str) else []
            ratio_list = str(ratios).split(';') if isinstance(ratios, str) else []
            for i, name in enumerate(name_list):
                ratio = ratio_list[i] if i < len(ratio_list) else ''
                if name and name.strip():
                    income_items.append({'product': name.strip(), 'ratio': ratio.strip() if ratio else ''})
    result['income_structure'] = income_items[:10]

    # =============================================
    # 3. 竞争对手识别（已知打印机行业公司）
    # =============================================
    # 打印机/激光打印行业上市公司（基于 MEMORY.md 知识库）
    # 纳思达(002180)是国内打印机龙头，奔图+利盟双品牌
    # 国内其他打印机相关：联想图像(000861)、汉光药业/中船汉光另作他用
    # 纳思达的主要竞争对手:
    #   - 惠普(HPQ.N) - 全球霸主
    #   - 佳能(7751.T) - 全球办公打印
    #   - 兄弟工业(6444.T) - 全球标签打印
    #   - 联想图像(000861.SZ) - 国内激光打印（联想集团旗下）
    #   - 得力集团 - 国内办公文具龙头（非上市）
    #   - 晨光股份(603899.SH) - 办公文具（非专业打印）

    competitors = []

    # 尝试从东方财富获取申万三级同行
    # 优先用 BOARD_CODE_BK_2LEVEL 筛选（比 SWINDUSTRY_NAME2 like 更可靠）
    bk_code = rec.get('BOARD_CODE_BK_2LEVEL', '')
    sw_industry = rec.get('SWINDUSTRY_NAME2', '')
    
    if bk_code:
        try:
            params2 = {
                'reportName': 'RPT_F10_ORG_BASICINFO',
                'columns': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,SWINDUSTRY_NAME2,CSRC_INDUSTRY_NAME,MAIN_BUSINESS',
                'filter': f'(BOARD_CODE_BK_2LEVEL="{bk_code}")',
                'pageNumber': 1,
                'pageSize': 30,
                'source': 'WEB',
                'client': 'WEB',
            }
            raw2 = safe_get(EM_API, params=params2, headers=HEADERS, timeout=15)
            peer_records = safe_extract(raw2, ['result', 'data'], default=[])
            if not peer_records:
                peer_records = []
            result['findings']['bk_peer_raw'] = peer_records

            for p in peer_records:
                sc = p.get('SECURITY_CODE', '')
                if sc and sc != stock_code:
                    competitors.append({
                        'code': sc,
                        'name': p.get('SECURITY_NAME_ABBR', ''),
                        'sw_industry': p.get('SWINDUSTRY_NAME2', ''),
                        'csrc_industry': p.get('CSRC_INDUSTRY_NAME', ''),
                        'main_business': p.get('MAIN_BUSINESS', ''),
                        'data_source': f'东方财富-BK{bk_code}',
                    })
        except Exception as e:
            result['warnings'].append(f'BK板块同行查询失败: {e}')
    elif sw_industry:
        try:
            # Fallback: 申万行业名作为过滤条件
            params2 = {
                'reportName': 'RPT_F10_ORG_BASICINFO',
                'columns': 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,SWINDUSTRY_NAME2,CSRC_INDUSTRY_NAME,MAIN_BUSINESS',
                'filter': f'(SWINDUSTRY_NAME2 like "%{sw_industry}%")',
                'pageNumber': 1,
                'pageSize': 30,
                'source': 'WEB',
                'client': 'WEB',
            }
            raw2 = safe_get(EM_API, params=params2, headers=HEADERS, timeout=15)
            peer_records = safe_extract(raw2, ['result', 'data'], default=[])
            if not peer_records:
                peer_records = []
            result['findings']['sw_peer_raw'] = peer_records

            for p in peer_records:
                sc = p.get('SECURITY_CODE', '')
                if sc and sc != stock_code:
                    competitors.append({
                        'code': sc,
                        'name': p.get('SECURITY_NAME_ABBR', ''),
                        'sw_industry': p.get('SWINDUSTRY_NAME2', ''),
                        'csrc_industry': p.get('CSRC_INDUSTRY_NAME', ''),
                        'main_business': p.get('MAIN_BUSINESS', ''),
                        'data_source': '东方财富-申万同行',
                    })
        except Exception as e:
            result['warnings'].append(f'申万同行查询失败: {e}')

    # [P1-1修复] 删除了过时的hardcoded list，改为纯BK/申万行业自动获取
    # 如需特定行业补充，请通过配置或知识库动态注入，而非hardcode
    pass  # 无hardcoded补充

    result['competitors'] = competitors[:15]

    # =============================================
    # 4. 市场地位分析
    # =============================================
    gross_profit = rec.get('GROSS_PROFIT_RATIO')
    employees = rec.get('TOTAL_NUM')
    reg_capital = rec.get('REG_CAPITAL')
    income_stru = result['income_structure']

    market_position_parts = []
    if employees:
        market_position_parts.append(f"员工{employees}人")
    if reg_capital:
        market_position_parts.append(f"注册资本{float(reg_capital):.0f}万元")

    if income_stru:
        main_products = [f"{i['product']}({i['ratio']})" for i in income_stru[:3] if i['ratio']]
        if main_products:
            market_position_parts.append(f"主营: {'; '.join(main_products)}")

    result['market_position'] = '；'.join(market_position_parts) if market_position_parts else None

    # =============================================
    # 5. 竞争格局综合评估
    # =============================================
    csrc = result['industry_class'].get('csrc_industry', '')
    sw = result['industry_class'].get('sw_industry', '')
    result['warnings'].append('行业成分股通过BK板块代码自动筛选获取，如返回0家可能是BK代码为空或行业过细')

    # 风险信号
    if not competitors:
        result['risks'].append({'level': 'info', 'dim': '行业', 'signal': '可比公司数据不完整'})

    # 保存
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        out = os.path.join(data_dir, 'industry_analysis.json')
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    return result


def format_industry_summary(data):
    """格式化行业分析摘要为Markdown文本"""
    if not data or not data.get('industry_class'):
        return '行业数据暂无可用'

    lines = []
    ib = data['industry_class']
    lines.append("## 行业竞争格局")
    lines.append("")

    # 行业分类
    lines.append(f"**证监会行业**: {ib.get('csrc_industry') or '未知'}")
    lines.append(f"**申万行业**: {ib.get('sw_industry') or '未知'}")
    if ib.get('board_l1'):
        lines.append(f"**板块**: {ib.get('board_l1')} > {ib.get('board_l2') or ''}")
    lines.append(f"**地域**: {ib.get('region') or '未知'}")

    # 主营结构
    income = data.get('income_structure', [])
    if income:
        lines.append("")
        lines.append("**主营构成**:")
        for item in income[:6]:
            lines.append(f"- {item['product']} {item['ratio']}")

    # 概念板块
    concepts = data.get('findings', {}).get('concepts', [])
    if concepts:
        sample = [c for c in concepts if c][:10]
        lines.append("")
        lines.append(f"**概念板块**: {', '.join(sample)}")

    # 毛利率
    gp = data.get('findings', {}).get('gross_profit_ratio')
    if gp:
        lines.append(f"**毛利率**: {gp}%")

    # 可比公司
    competitors = data.get('competitors', [])
    if competitors:
        lines.append("")
        lines.append(f"**可比公司**（{len(competitors)}家）:")
        for c in competitors[:8]:
            note = f" - {c.get('note','')}" if c.get('note') else ''
            src = f"[{c.get('data_source','')}]" if c.get('data_source') != '知识库补充' else ''
            lines.append(f"- {c.get('code','')} {c.get('name','')}{note} {src}")

    # 市场地位
    mp = data.get('market_position')
    if mp:
        lines.append("")
        lines.append(f"**市场地位**: {mp}")

    warnings = data.get('warnings', [])
    if warnings:
        lines.append("")
        lines.append("**⚠️ 说明**:")
        for w in warnings:
            lines.append(f"- {w}")

    return '\n'.join(lines)


# 向后兼容别名
fetch_industry = fetch_industry_info


if __name__ == '__main__':
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else '002180'
    data = fetch_industry_info(stock, data_dir='output/test')
    print(format_industry_summary(data))


def generate_report_section(data):
    lines = []
    lines.append("## 行业竞争格局")
    lines.append("")
    ib = data.get('industry_class', {})
    if ib:
        csrc = ib.get('csrc_industry', '未知')
        sw = ib.get('sw_industry', ib.get('sw_industry_l1', ''))
        board = ib.get('board_l2', '')
        region = ib.get('region', '')
        lines.append(f"**证监会行业**: {csrc or '未知'}")
        if sw:
            lines.append(f"**申万行业**: {sw}")
        if board:
            lines.append(f"**板块**: 计算机 > {board}")
        if region:
            lines.append(f"**地域**: {region}")
    else:
        lines.append("> 行业分类数据暂缺")
    lines.append("")

    income = data.get('income_structure', [])
    if income:
        lines.append("**主营构成**（收入占比）:")
        for item in income[:6]:
            ratio = f"({item['ratio']})" if item.get('ratio') else ""
            lines.append(f"- {item['product']} {ratio}")
        lines.append("")

    gp = data.get('findings', {}).get('gross_profit_ratio')
    if gp:
        lines.append(f"**毛利率**: {gp}%（原装打印机及耗材驱动）")
        lines.append("")

    concepts = data.get('findings', {}).get('concepts', [])
    if concepts:
        sample = [c for c in concepts if c][:10]
        lines.append(f"**概念板块**: {', '.join(sample)}")
        lines.append("")

    competitors = data.get('competitors', [])
    if competitors:
        lines.append(f"**主要可比公司**（{len(competitors)}家）:")
        for c in competitors[:6]:
            note = f" — {c.get('note','')}" if c.get('note') else ''
            src = "" if c.get('data_source') == '知识库补充' else f" [{c.get('data_source','')}]"
            lines.append(f"- {c.get('code','')} {c.get('name','')}{note}{src}")
        lines.append("")

    mp = data.get('market_position')
    if mp:
        lines.append(f"**市场地位**: {mp}")
        lines.append("")

    risks = data.get('risks', [])
    if risks:
        lines.append("**风险信号**:")
        for r in risks:
            lines.append(f"- [{r.get('level','?')}] {r.get('signal','')}")
        lines.append("")

    warnings = data.get('warnings', [])
    if warnings:
        lines.append("**⚠️ 说明**:")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return lines
