# -*- coding: utf-8 -*-
"""
模块：SOTP分部估值（子公司独立估值）
数据源：年报PDF「主要控股参股公司」章节
功能：自动解析子公司财务数据，计算SOTP估值
"""
import sys, json, re, os
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result
sys.stdout.reconfigure(encoding='utf-8')

# 加载行业PE基准表（一次性加载，避免重复读文件）
_INDUSTRY_PE_CACHE = None


def _load_industry_pe_benchmark():
    global _INDUSTRY_PE_CACHE
    if _INDUSTRY_PE_CACHE is not None:
        return _INDUSTRY_PE_CACHE
    benchmark_path = os.path.join(os.path.dirname(__file__), 'data', 'industry_pe_benchmark.json')
    try:
        with open(benchmark_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _INDUSTRY_PE_CACHE = data.get('benchmark', {})
    except Exception:
        _INDUSTRY_PE_CACHE = {}
    return _INDUSTRY_PE_CACHE


# 业务关键词 → THS行业代码 映射
_BUSINESS_TO_INDUSTRY_CODE = {
    # 半导体/芯片（最高PE行业）
    '芯片':      '881121',
    '集成电路':  '881121',
    '半导体':    '881121',
    # 打印/造纸（纳思达核心业务）
    '打印':      '881137',
    '耗材':      '881137',
    '造纸':      '881137',
    '包装印刷':  '881138',
    # 计算机/办公设备
    '计算机设备':'881130',
    '办公':      '881130',
    'IT服务':    '881271',
    '软件':      '881272',
    # 新能源/电力设备
    '光伏':      '881279',
    '新能源':    '881281',
    '电池':      '881281',
    '电网':      '881278',
    '风电':      '881280',
    # 工程/机械
    '机械':      '881268',
    '工程':      '881268',
    '电机':      '881277',
    # 电子/通信
    '电子':      '881123',
    '通信':      '881129',
    '光学':      '881122',
    # 医疗/医药
    '医疗':      '881144',
    '医药':      '881140',
    '生物':      '881142',
    # 消费/汽车/家电
    '消费电子':  '881124',
    '汽车':      '881126',
    '家电':      '881131',
    '小家电':    '881173',
    # 军工
    '军工':      '881166',
}

# 负向排除规则：如果业务描述含这些关键词，排除对应行业
# 格式：排除关键词 -> 不应匹配的行业代码列表
_EXCLUDE_RULES = {
    '打印': ['881121'],   # 含"打印"不应归入半导体
    '复印': ['881121'],   # 含"复印"不应归入半导体
    '胶印': ['881121'],   # 含"胶印"不应归入半导体
    '油墨': ['881121'],   # 含"油墨"不应归入半导体
    '耗材': ['881121'],   # 含"耗材"不应归入半导体
    '办公设备': ['881121'], # 含"办公设备"不应归入半导体
}

# 优先级关键词：这些词出现时强制覆盖其他匹配
# 格式：关键词 -> 行业代码（无视长度排序，直接命中）
_PRIORITY_KEYWORDS = {
    '复印和胶印设备': '881130',  # 打印机/复印设备 -> 计算机设备
    '印刷专用设备':   '881130',  # 印刷设备 -> 计算机设备
    '办公设备耗材':   '881137',  # 办公耗材 -> 造纸
    '打印管理服务':   '881130',  # 打印服务 -> 计算机设备
    '原装耗材':       '881137',  # 打印耗材
}


def _get_industry_pe(business):
    """根据业务描述返回行业加权PE（无则返回None）
    
    匹配优先级：
    1. _PRIORITY_KEYWORDS（强制覆盖，最具体的产品描述）
    2. _BUSINESS_TO_INDUSTRY_CODE + 负向排除规则
    3. fallback: None
    """
    benchmark = _load_industry_pe_benchmark()
    if not business:
        return None
    
    # 第1步：优先级关键词匹配（强制覆盖）
    for keyword, ind_code in sorted(_PRIORITY_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if keyword in business:
            if ind_code in benchmark:
                return benchmark[ind_code]['weighted_pe']
    
    # 第2步：检查负向排除规则，收集应排除的行业代码
    excluded_codes = set()
    for exclude_kw, excluded in _EXCLUDE_RULES.items():
        if exclude_kw in business:
            excluded_codes.update(excluded)
    
    # 第3步：通用关键词匹配（按长度降序，跳过被排除的行业）
    for keyword, ind_code in sorted(_BUSINESS_TO_INDUSTRY_CODE.items(), key=lambda x: len(x[0]), reverse=True):
        if keyword in business:
            if ind_code in excluded_codes:
                continue  # 被负向规则排除
            if ind_code in benchmark:
                return benchmark[ind_code]['weighted_pe']
    
    # 第4步：如果所有匹配都被排除了，用排除规则暗示的行业
    for exclude_kw, excluded in _EXCLUDE_RULES.items():
        if exclude_kw in business:
            # 含"打印/复印/胶印" -> 计算机设备(881130)
            if '881130' not in excluded and '881130' in benchmark:
                return benchmark['881130']['weighted_pe']
            if '881137' in benchmark:
                return benchmark['881137']['weighted_pe']
    
    return None


def calculate_sotp(analysis_data, stock_code, market='a'):
    """计算SOTP分部估值

    🔴 2026-10-21：非 A 股（hk/us）直接返回 `skipped`，不再吐 sotp_total=0/discount=0
    —— 0 值会被下游当成"分部估值算出 0"，属假数据。港美股结构不同（ADR/VIE、
    多币种、无东财子公司口径），SOTP 需人工建模。
    """
    findings = analysis_data.get('findings', {})
    if market not in ('a', 'bse', 'cn'):
        return {
            "stock_code": stock_code,
            "skipped": True,
            "reason": ("SOTP 分部估值仅支持 A 股/北交所；"
                       f"{market.upper()} 需人工建模（子公司口径/币种/VIE 结构不同）"),
            "subsidiaries": [],
            "sotp_total": None,
            "market_cap": None,
            "discount": None,
            "catalysts": [],
            "warnings": ["SOTP 未计算（不适用）"],
            "markdown": "",
        }

    result = {
        "stock_code": stock_code,
        "subsidiaries": [],
        "sotp_total": 0,
        "market_cap": 0,
        "discount": 0,
        "catalysts": [],
        "warnings": [],
        "markdown": "",
    }

    subsidiaries = _extract_subsidiary_data(findings)
    result['subsidiaries'] = subsidiaries

    # 获取市值（多数据源fallback）
    market_cap = _get_market_cap(findings, stock_code, market)
    result['market_cap'] = market_cap

    sotp_total = 0
    for sub in subsidiaries:
        equity_value = _estimate_equity_value(sub)
        sub['equity_value'] = equity_value
        sotp_total += equity_value
    result['sotp_total'] = sotp_total

    if market_cap > 0 and sotp_total > 0:
        result['discount'] = (sotp_total - market_cap) / market_cap * 100

    result['catalysts'] = _identify_catalysts(subsidiaries, findings)
    result['markdown'] = _generate_sotp_markdown(result, subsidiaries)
    if not subsidiaries:
        # 未提取到子公司分部 → 0 不是"估值为 0"，是"无法分部"
        result['note'] = '未提取到子公司/分部数据，SOTP 不成立（勿读作估值为 0）'
        result['sotp_total'] = None
        result['discount'] = None

    return result


def _get_market_cap(findings, stock_code, market='a'):
    """
    获取市值数据（多数据源fallback）
    
    优先级：
    1. quote.total_mv（实时行情）
    2. valuation.total_mv（估值数据）
    3. AKShare stock_individual_info_em（快速，单只股票）
    4. financial数据推算
    """
    # 方式1：quote.data.总市值（THSDK实际返回结构）
    quote = findings.get('quote', {})
    if quote:
        # 优先从quote.data取中文键
        quote_data = quote.get('data', {})
        if isinstance(quote_data, dict):
            total_mv = quote_data.get('总市值', 0)
            # 排除游客无效值(int32_max=2147483647 或 uint32_max=4294967295)
            INT32_MAX = 2147483647
            if total_mv and total_mv not in (INT32_MAX, INT32_MAX * 2) and total_mv > 0:
                return total_mv / 1e8
        # fallback: quote.total_mv
        total_mv = quote.get('total_mv', 0)
        if total_mv and total_mv > 0:
            return total_mv / 1e8 if total_mv > 1e6 else total_mv
    
    # 方式2：valuation
    valuation = findings.get('valuation', {})
    if valuation and valuation.get('total_mv', 0) > 0:
        return valuation['total_mv'] / 1e8 if valuation['total_mv'] > 1e6 else valuation['total_mv']
    
    # 方式3：AKShare stock_individual_info_em（快速，直接返回市值）
    try:
        import akshare as ak
        df = ak.stock_individual_info_em(symbol=stock_code)
        if not df.empty:
            row = df.set_index('item')
            total_mv = float(row.loc['总市值', 'value']) if '总市值' in row.index else 0
            if total_mv > 0:
                return total_mv / 1e8  # 转换为亿元
    except Exception as _sexc:
        record(__name__, '_get_market_cap', _sexc, note='静默降级')
        pass
    
    # 方式4：从financial推算（fallback）
    financial = findings.get('financial', {})
    if financial:
        latest = financial.get('latest', {})
        summary = financial.get('summary', {})
        
        total_equity = latest.get('TOTAL_PARENT_EQUITY', 0)
        bps = summary.get('bps', 0)
        
        if total_equity > 0 and bps > 0:
            total_shares = total_equity / bps
            eps = summary.get('eps', 0)
            if eps and eps > 0:
                # 使用行业PE估算（保守）
                estimated_price = eps * 20
                market_cap = total_shares * estimated_price / 1e8
                if market_cap > 10:
                    return market_cap
    
    return 0


def _extract_subsidiary_data(findings):
    """从年报PDF提取子公司财务数据"""
    subsidiaries = []

    annual_pdf = findings.get('annual_pdf', {})
    if annual_pdf and 'sections' in annual_pdf:
        for sec_key in ['subsidiaries', 'subsidies', 'main_subs']:
            if sec_key in annual_pdf['sections']:
                sec_data = annual_pdf['sections'][sec_key]
                content = sec_data.get('content', '') if isinstance(sec_data, dict) else str(sec_data)
                if content:
                    parsed = _parse_subsidiary_content(content)
                    subsidiaries.extend(parsed)
                    if subsidiaries:
                        break

        if not subsidiaries:
            for sec_key, sec_data in annual_pdf['sections'].items():
                content = sec_data.get('content', '') if isinstance(sec_data, dict) else str(sec_data)
                if '主要控股参股公司' in content or '主要子公司' in content:
                    parsed = _parse_subsidiary_content(content)
                    subsidiaries.extend(parsed)
                    break

    if not subsidiaries:
        three_stmt = findings.get('three_statements', {})
        if three_stmt and 'subsidiaries' in three_stmt:
            for sub in three_stmt['subsidiaries']:
                subsidiaries.append({
                    'name': sub.get('name', ''),
                    'type': sub.get('type', '子公司'),
                    'business': sub.get('business', ''),
                    'registered_capital': sub.get('registered_capital', 0),
                    'total_assets': sub.get('total_assets', 0),
                    'net_assets': sub.get('net_assets', 0),
                    'revenue': sub.get('revenue', 0),
                    'operating_profit': sub.get('operating_profit', 0),
                    'net_profit': sub.get('net_profit', 0),
                })

    return subsidiaries


def _parse_subsidiary_content(content):
    """
    解析子公司内容（处理PDF提取的多行格式）
    
    算法：
    1. 查找所有"子公"和"司"的位置（合并为"子公司"类型标记）
    2. 从类型标记向前查找公司名（跳过"（合并）"）
    3. 从类型标记向后查找业务描述
    4. 在业务描述后查找6个数字行
    """
    subsidiaries = []
    lines = content.split('\n')
    
    # 查找所有"子公司"类型标记的位置
    type_positions = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == '子公' and i + 1 < len(lines) and lines[i + 1].strip() == '司':
            type_positions.append(i)
        elif stripped == '子公司':
            type_positions.append(i)
    
    # 对每个类型标记，提取子公司数据
    for type_idx in type_positions:
        # 1. 向前查找公司名（收集所有非空行，拼接）
        name_parts = []
        for j in range(type_idx - 1, max(type_idx - 15, 0), -1):
            line = lines[j].strip()
            if not line:
                continue
            # 跳过"（合并）"等标记
            if line in ['（合并）', '合并）', '合并', '并）', '并)']:
                continue
            # 特殊处理："司（合" 或 "公司（合" 这类拆行碎片 → 提取"（"之前的字符，继续往前找
            if '（合' in line:
                idx = line.index('（合')
                before = line[:idx]
                if before:
                    name_parts.insert(0, before)
                continue  # 继续往前找更多公司名部分
            # 如果是公司名的一部分，添加
            if _is_company_name_part(line):
                name_parts.insert(0, line)
            else:
                # 如果已经找到公司名部分，遇到非公司名行就停止
                if name_parts:
                    break
        
        # 拼接公司名（英文加空格，中文直接拼接）
        # 先过滤掉"（合并）"相关的碎片
        name_parts = _clean_name_parts(name_parts)
        company_name = _join_company_name(name_parts)
        
        # 2. 向后查找业务描述和数字
        business_parts = []
        numbers = []
        found_numbers = False
        
        for j in range(type_idx + 1, min(type_idx + 30, len(lines))):
            line = lines[j].strip()
            if not line:
                continue
            
            # 检查是否是数字行
            if re.match(r'^-?[\d,]+\.\d+$', line):
                numbers.append(_parse_number(line))
                found_numbers = True
                if len(numbers) >= 6:
                    break
            elif found_numbers:
                # 如果已经开始找数字，但遇到非数字行，停止
                break
            else:
                # 业务描述（跳过"司"开头的行）
                if line.startswith('司'):
                    line = line[1:]
                if line:
                    business_parts.append(line)
        
        # 如果找到足够的数据，创建子公司记录
        if company_name and len(numbers) >= 6:
            business = ''.join(business_parts)[:100]
            sub = {
                'name': company_name.strip(),
                'type': '子公司',
                'business': business,
                'registered_capital': numbers[0],
                'total_assets': numbers[1],
                'net_assets': numbers[2],
                'revenue': numbers[3],
                'operating_profit': numbers[4],
                'net_profit': numbers[5],
            }
            subsidiaries.append(sub)
    
    return subsidiaries


def _clean_name_parts(parts):
    """
    清理公司名碎片，移除（合并）相关的PDF拆行碎片
    
    例如：
    ['珠海奔图', '电子有限', '公司（合', '并）'] → ['珠海奔图', '电子有限', '公司']
    ['珠海纳思', '达打印科', '技有限公', '司（合', '并）'] → ['珠海纳思', '达打印科', '技有限公', '司']
    """
    if not parts:
        return parts
    
    cleaned = []
    skip_rest = False
    
    for part in parts:
        if skip_rest:
            continue
        
        # 检测（合并）碎片
        if '（合' in part:
            # 提取（之前的部分
            idx = part.index('（合')
            before = part[:idx]
            if before:
                cleaned.append(before)
            skip_rest = True
            continue
        
        if part in ['并）', '并)', '）', ')']:
            skip_rest = True
            continue
        
        cleaned.append(part)
    
    return cleaned


def _join_company_name(parts):
    """
    拼接公司名
    英文单词之间加空格，中文直接拼接
    """
    if not parts:
        return ''
    
    result = []
    for i, part in enumerate(parts):
        # 判断是英文还是中文
        if re.match(r'^[A-Za-z\s]+$', part):
            # 英文：加空格（除非是第一个）
            if result:
                result.append(' ')
            result.append(part)
        else:
            # 中文：直接拼接
            result.append(part)
    
    return ''.join(result).strip()


def _is_company_name_part(text):
    """
    判断是否是公司名的一部分
    
    关键词覆盖：
    - 英文：Holdings, Company, Limited, Corp, Image, Tech
    - 中文：电子, 科技, 打印, 极海, 奔图, 纳思达, 公司, 股份, 有限
    - 排除：业务描述行（一般项目, 许可项目等）
    """
    # 排除明显不是公司名的行
    exclude_keywords = ['适用', '不适用', '单位', '公司名称', '公司类型', '主要业务', '注册资本', 
                        '主要控股参股', '主要子公司', '参股公司情况', '一般项目', '许可项目',
                        '集成电路产品设计', '打印机整机', '机械设备研发', '办公设备耗材',
                        '总资产', '净资产', '营业收入', '营业利润', '净利润', '注册资']
    if any(kw in text for kw in exclude_keywords):
        return False
    
    # 公司名特征关键词（通用，不绑定特定公司）
    part_keywords = ['Holdings', 'Company', 'Limited', 'Corp', 'Image', 'Tech', 'Group',
                     '电子', '科技', '公司', '股份', '有限', '集团', '控股', '实业', '制造',
                     '信息', '智能', '新材料', '新能源', '生物', '医药', '通信',
                     '机械', '配件', '精密', '热控', '制冷', '设备', '工业', '材料']
    if any(kw in text for kw in part_keywords):
        return True
    if re.match(r'^[A-Za-z\s]+$', text) and len(text) > 2:
        return True
    # 中文PDF碎片：排除已知非公司名词后，长度>=2的中文行视为公司名片段
    if re.match(r'^[\u4e00-\u9fff]{2,}$', text):
        return True
    return False


def _parse_number(text):
    """解析数字"""
    if not text:
        return 0
    try:
        return float(text.replace(',', '').replace(' ', ''))
    except:
        return 0


def convert_to_yi(val):
    """将各种单位的数值统一转换为亿元
    
    数据场景：
    - 年报PDF子公司数据：单位标注"元"，典型值1e7~1e11（如营收7.4e9=74亿，净利润1e8=1亿）
    - 已转换好的亿元级数据：无需转换
    
    阈值逻辑（v6，2026-05-09）：
    - |val| >= 1e8: 视为元（年报子公司大数值），除以1e8转为亿
    - |val| < 1e8: 视为元（年报子公司小数值，如净利润6588万=65880000元），除以1e8转为亿
    - |val| < 1e6 且较整（如60万=600000）：视为万元（注册资本等早年报表格），除以1e4转为亿
    
    2026-05-09 v6修复：阈值从1e8改为1e6。1e6以下若|val|<1e8，走元→亿路径，
    防止净利润6588万被错误除以1e4得到6588亿。
    """
    abs_val = abs(val)
    if abs_val > 1e11:
        return val / 1e8  # 超大数值（元）-> 亿
    elif abs_val >= 1e6:
        return val / 1e8  # 元（≥100万）-> 亿：年报子公司数据
    else:
        return val / 1e4  # 万元（<100万）-> 亿：早年报表格、注册资本



def _estimate_equity_value(sub):
    """估算子公司权益价值（使用真实行业加权PE）"""
    net_profit = sub.get('net_profit', 0)
    revenue = sub.get('revenue', 0)
    net_assets = sub.get('net_assets', 0)
    business = sub.get('business', '')

    # 优先使用真实行业PE
    industry_pe = _get_industry_pe(business)
    if industry_pe:
        pe_multiple = round(industry_pe, 1)
    else:
        # Fallback: 按关键词判断
        if '芯片' in business or '集成电路' in business or '半导体' in business:
            pe_multiple = 35
        elif '打印' in business or '耗材' in business:
            pe_multiple = 18
        else:
            pe_multiple = 20

    ps_multiple = 1.5  # PS用保守值，不再用2（行业差异大）
    pb_multiple = 2.0

    # 统一使用 convert_to_yi: 统一单位转换
    net_profit_yi = convert_to_yi(net_profit)
    revenue_yi = convert_to_yi(revenue)
    net_profit_yi = convert_to_yi(net_profit)
    net_assets_yi = convert_to_yi(net_assets)

    # 写回转换后的值供下游使用
    sub['revenue_yi'] = revenue_yi
    sub['net_profit_yi'] = net_profit_yi
    sub['net_assets_yi'] = net_assets_yi

    equity_value = 0
    # 优先用净利润×PE
    if net_profit_yi > 0:
        equity_value = net_profit_yi * pe_multiple
    elif revenue_yi > 0:
        # 无净利润用营收×PS
        equity_value = revenue_yi * ps_multiple
    elif net_assets_yi > 0:
        # 无营收用净资产×PB
        equity_value = net_assets_yi * pb_multiple

    # 附加行业来源信息
    if industry_pe:
        sub['_industry_pe_source'] = industry_pe

    return round(equity_value, 2)


def _identify_catalysts(subsidiaries, findings):
    """识别SOTP催化剂"""
    catalysts = []
    for sub in subsidiaries:
        name = sub.get('name', '')
        raw_net_profit = sub.get('net_profit', 0)
        raw_revenue = sub.get('revenue', 0)
        equity_value = sub.get('equity_value', 0)
        business = sub.get('business', '')

        # 统一用 convert_to_yi 转换
        net_profit_yi = convert_to_yi(raw_net_profit)
        revenue_yi = convert_to_yi(raw_revenue)

        # 判断是否盈利：使用已转换为亿元的值
        if net_profit_yi > 0 and revenue_yi > 0.1:  # 盈利且营收>0.1亿
            catalysts.append(f"**{name}**：已盈利且营收规模较大，具备IPO条件")
        if equity_value > 10:
            catalysts.append(f"**{name}**：独立估值{equity_value}亿元，如分拆上市可释放价值")
        if '芯片' in business or '集成电路' in business:
            catalysts.append(f"**{name}**：芯片业务，享受半导体行业高估值")

    return catalysts


def _generate_sotp_markdown(result, subsidiaries):
    """生成SOTP估值的Markdown"""
    lines = []
    lines.append("### SOTP分部估值（子公司独立估值）")
    lines.append("")
    lines.append("> 估值方法：子公司对母公司股价的传导机制：IPO→持仓有公开报价→市场被迫重估母公司。")
    lines.append("")

    lines.append("| 子公司 | 持股比例 | 主营 | 营收(亿) | 净利润(亿) | 估值方法 | 权益价值(亿) |")
    lines.append("|--------|---------|------|---------|-----------|---------|------------|")

    for sub in subsidiaries:
        name = sub.get('name', '未知')[:20]
        biz = sub.get('business', '-')[:25]
        # 统一使用 convert_to_yi 转换，保持和 equity_value 计算一致
        rev_yi = convert_to_yi(sub.get('revenue', 0))
        profit_yi = convert_to_yi(sub.get('net_profit', 0))
        equity_value = sub.get('equity_value', 0)

        if profit_yi > 0:
            ind_pe = sub.get('_industry_pe_source')
            method = f"PE({ind_pe:.1f}x)" if ind_pe else f"PE({18 if '打印' in biz else 35}x)"
        elif rev_yi > 0:
            method = f"PS(1.5x)"
        else:
            method = "PB(2.5x)"

        lines.append(f"| {name} | 100% | {biz} | {rev_yi:.2f} | {profit_yi:.2f} | {method} | {equity_value:.2f} |")

    lines.append("")

    sotp_total = result.get('sotp_total', 0)
    market_cap = result.get('market_cap', 0)
    discount = result.get('discount', 0)

    lines.append(f"**SOTP总估值**：{sotp_total:.1f}亿元")
    lines.append(f"**当前市值**：{market_cap:.1f}亿元")
    if discount > 0:
        lines.append(f"**折价率**：{discount:.1f}%（子公司价值未被充分定价）")
    elif discount < 0:
        lines.append(f"**溢价率**：{abs(discount):.1f}%（市场已部分定价子公司价值）")
    lines.append("")

    catalysts = result.get('catalysts', [])
    if catalysts:
        lines.append("**SOTP催化剂**：")
        for cat in catalysts:
            lines.append(f"- {cat}")
        lines.append("")

    lines.append("> ⚠️ 以上估值基于行业平均倍数，实际估值需根据子公司具体财务数据和行业可比公司调整。")
    lines.append("")

    return '\n'.join(lines)
