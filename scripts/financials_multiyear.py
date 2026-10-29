# -*- coding: utf-8 -*-
"""
模块：3年+最近一期财务对比分析
========================================
功能：
1. 获取3年+最近一期的财务数据对比
2. 趋势分析（营收、净利、毛利率、ROE等）
3. 生成对比表格
4. 从年报PDF提取多年度数据

数据源优先级：
1. 东方财富API（多期数据）
2. 年报PDF提取（历史年度补充）
"""
import json, os, re, sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from safe_request import safe_get, safe_extract
from annual_extract import AnnualReportExtractor
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

EM_API = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://data.eastmoney.com/',
    'Accept': 'application/json',
}


def extract_financial_from_pdf(stock_code, year, data_dir=None):
    """
    从年报PDF提取财务数据（API数据缺失时的fallback）
    
    Args:
        stock_code: 股票代码
        year: 年份（如2025）
        data_dir: 数据目录
    
    Returns:
        dict: {'扣非净利润': xxx, '资产负债率': xx, ...} or None if PDF not found
    """
    import glob
    
    if not data_dir:
        return None
    
    # 查找年报PDF
    pdf_patterns = [
        os.path.join(data_dir, f'{stock_code}*annual*.pdf'),
        os.path.join(data_dir, 'data', f'{year}*annual*.pdf'),
        os.path.join(data_dir, f'{stock_code}_{year}*.pdf'),
    ]
    
    pdf_path = None
    for pattern in pdf_patterns:
        files = glob.glob(pattern)
        if files:
            pdf_path = files[0]
            break
    
    # 如果没找到，尝试通用搜索
    if not pdf_path:
        search_patterns = [
            os.path.join(data_dir, '**', f'*{year}*annual*.pdf'),
            os.path.join(data_dir, '**', f'*{stock_code}*.pdf'),
        ]
        for pattern in search_patterns:
            files = glob.glob(pattern, recursive=True)
            if files:
                # 找最近的年报
                pdf_path = max(files, key=os.path.getmtime)
                break
    
    if not pdf_path or not os.path.exists(pdf_path):
        return None
    
    try:
        extractor = AnnualReportExtractor(pdf_path)
        metrics = extractor.extract_financial_metrics()
        return metrics if metrics else None
    except Exception as e:
        print(f"[PDF提取] {stock_code} {year} 失败: {e}")
        return None


def fetch_financial_multi_year(stock_code, market='a', data_dir=None, years=3):
    """
    获取3年+最近一期的财务数据对比
    
    Args:
        stock_code: 股票代码
        market: 'a' / 'hk'
        data_dir: 数据目录（用于缓存和PDF提取）
        years: 对比年数（默认3年）
    
    Returns:
        {
            'annual': {
                '2025': {财务指标dict},
                '2024': {财务指标dict},
                '2023': {财务指标dict},
            },
            'latest_quarter': {最近一期季报},
            'trend_analysis': {
                'revenue_trend': '上升/下降/波动',
                'profit_trend': '上升/下降/波动',
                'gross_margin_trend': '上升/下降/波动',
                'roe_trend': '上升/下降/波动',
            },
            'comparison_table': [...],  # Markdown格式对比表格
            'warnings': [...],
            'risks': [...],
            '_meta': {...},
        }
    """
    print(f"[MultiYear] 获取 {stock_code} {years}年+最近一期财务数据")
    
    result = {
        'annual': {},
        'latest_quarter': None,
        'trend_analysis': {},
        'comparison_table': [],
        'warnings': [],
        'risks': [],
        '_meta': {
            'stock_code': stock_code,
            'market': market,
            'years': years,
            'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        },
    }
    
    # Step 1: 从东方财富API获取多年数据
    records = _fetch_multi_year_from_em(stock_code, market)
    if not records:
        result['warnings'].append('东方财富API无数据')
        return result
    
    # Step 2: 按年度分组
    annual_records = _group_by_year(records)
    result['annual'] = annual_records
    
    # Step 3: 趋势分析
    trend = _analyze_financial_trend(annual_records)
    result['trend_analysis'] = trend
    
    # Step 4: 生成对比表格
    table = _generate_comparison_table(annual_records, trend)
    result['comparison_table'] = table
    
    # Step 5: 风险信号
    risks = _identify_financial_risks(annual_records)
    result['risks'] = risks
    
    # Step 6: 最近一期季报
    if records:
        for rec in records:
            date_str = str(rec.get('REPORTDATE', ''))[:10]
            if '-12-31' not in date_str:  # 排除年报
                result['latest_quarter'] = _format_record(rec)
                break
    
    # Step 7: 补充年报PDF数据（如果API数据不足）
    if len(annual_records) < years:
        result['warnings'].append('API数据仅覆盖' + str(len(annual_records)) + '年，尝试从年报PDF补充...')
        pdf_data = _supplement_from_annual_pdf(stock_code, market, data_dir, years)
        if pdf_data:
            for year, pdf_rec in pdf_data.items():
                if year not in result['annual']:
                    result['annual'][year] = pdf_rec
                else:
                    result['annual'][year] = dict(list(pdf_rec.items()) + list(result['annual'][year].items()))
    
    result['_meta']['annual_count'] = len(result['annual'])
    return result


def _fetch_multi_year_from_em(stock_code, market='a'):
    """从东方财富API获取多年财务数据"""
    # 格式股票代码
    secucode = stock_code
    if market == 'a':
        if not (stock_code.endswith('.SZ') or stock_code.endswith('.SH') or stock_code.endswith('.BJ')):
            if stock_code[:2] in ['00', '30']:
                secucode = stock_code + '.SZ'
            elif stock_code[:2] in ['60', '68']:
                secucode = stock_code + '.SH'
            elif stock_code[0] in ['8', '4']:
                secucode = stock_code + '.BJ'
            else:
                secucode = stock_code + '.SZ'
    elif market == 'hk':
        secucode = stock_code + '.HK'
    
    params = {
        'reportName': 'RPT_LICO_FN_CPD',
        'columns': 'ALL',
        'filter': '(SECUCODE="' + secucode + '")',
        'pageNumber': 1,
        'pageSize': 40,
        'sortTypes': -1,
        'sortColumns': 'REPORTDATE',
        'source': 'WEB',
        'client': 'WEB',
    }
    
    try:
        raw = safe_get(EM_API, params=params, headers=HEADERS, timeout=20)
        records = safe_extract(raw, ['result', 'data'], default=[])
        if records is None:
            return []
        print("[MultiYear] 从API获取 " + str(len(records)) + " 期财务数据")
        return records
    except Exception as e:
        print("[MultiYear] API请求失败: " + str(e))
        return []


def _group_by_year(records):
    """按年度分组，取每年最新一期数据"""
    year_groups = {}
    
    for rec in records:
        date_str = str(rec.get('REPORTDATE', ''))[:10]
        if not date_str:
            continue
        year = date_str[:4]
        if year not in year_groups:
            year_groups[year] = []
        year_groups[year].append((date_str, rec))
    
    # 每年的最新一期
    annual = {}
    for year, recs in year_groups.items():
        recs.sort(key=lambda x: x[0], reverse=True)
        latest_date, latest_rec = recs[0]
        annual[year] = _format_record(latest_rec)
    
    # 按年份排序（降序）
    sorted_annual = {}
    for year in sorted(annual.keys(), reverse=True):
        sorted_annual[year] = annual[year]
    
    return sorted_annual


def _format_record(rec):
    """格式化单期财务数据"""
    def safe(val, default=None):
        return val if val is not None else default
    
    def to_yi(val):
        if val is None:
            return None
        try:
            return round(float(val) / 1e8, 2)
        except:
            return None
    
    return {
        'report_date': str(rec.get('REPORTDATE', ''))[:10],
        'report_type': rec.get('REPORT_TYPE', rec.get('REPORTTYPE', '')),
        'revenue': safe(rec.get('TOTAL_OPERATE_INCOME')),
        'revenue_yi': to_yi(rec.get('TOTAL_OPERATE_INCOME')),
        'net_profit': safe(rec.get('PARENT_NETPROFIT')),
        'net_profit_yi': to_yi(rec.get('PARENT_NETPROFIT')),
        'deduct_net_profit': safe(rec.get('CUT_PARENT_NETPROFIT')),
        'deduct_net_profit_yi': to_yi(rec.get('CUT_PARENT_NETPROFIT')),
        'eps': safe(rec.get('BASIC_EPS')),
        'deduct_eps': safe(rec.get('DEDUCT_BASIC_EPS')),
        'bps': safe(rec.get('BPS')),
        'op_cash_ps': safe(rec.get('MGJYXJJE')),
        'roe': safe(rec.get('WEIGHTAVG_ROE')),
        'gross_margin': safe(rec.get('XSMLL')),
        'net_margin': safe(rec.get('XSJLL')),
        'revenue_growth': safe(rec.get('YSTZ')),
        'profit_growth': safe(rec.get('SJLTZ')),
        'total_assets': to_yi(rec.get('TOTAL_ASSETS')),
        'total_liab': to_yi(rec.get('TOTAL_LIABILITIES')),
        'parent_equity': to_yi(rec.get('TOTAL_PARENT_EQUITY')),
        'debt_ratio': safe(rec.get('ASSET_LIAB_RATIO')),
        'op_cash_flow': to_yi(rec.get('NET_CASH_FRM_OPERATING_ACTIVITIES')),
        '_raw': rec,
    }


def _analyze_financial_trend(annual):
    """分析财务趋势"""
    years = sorted(annual.keys(), reverse=True)
    if len(years) < 2:
        return {'status': '数据不足'}
    
    def analyze_series(values):
        valid = [v for v in values if v is not None]
        if len(valid) < 2:
            return '数据不足'
        
        changes = []
        for i in range(len(valid)-1):
            if valid[i+1] != 0:
                pct_change = ((valid[i] - valid[i+1]) / abs(valid[i+1])) * 100
                changes.append(pct_change)
        
        if not changes:
            return '数据不足'
        
        avg_change = sum(changes) / len(changes)
        
        if avg_change > 5:
            return '上升（均速' + str(round(avg_change, 1)) + '%）'
        elif avg_change < -5:
            return '下降（均速' + str(round(avg_change, 1)) + '%）'
        else:
            return '基本稳定'
    
    revenue_series = [annual.get(y, {}).get('revenue_yi') for y in years]
    profit_series = [annual.get(y, {}).get('net_profit_yi') for y in years]
    gross_series = [annual.get(y, {}).get('gross_margin') for y in years]
    roe_series = [annual.get(y, {}).get('roe') for y in years]
    revenue_growth_series = [annual.get(y, {}).get('revenue_growth') for y in years]
    profit_growth_series = [annual.get(y, {}).get('profit_growth') for y in years]
    
    return {
        'years': years,
        'revenue_trend': analyze_series(revenue_series),
        'profit_trend': analyze_series(profit_series),
        'gross_margin_trend': analyze_series(gross_series),
        'roe_trend': analyze_series(roe_series),
        'revenue_growth_trend': analyze_series(revenue_growth_series),
        'profit_growth_trend': analyze_series(profit_growth_series),
    }


def _generate_comparison_table(annual, trend):
    """生成Markdown格式对比表格"""
    years = sorted(annual.keys(), reverse=True)
    
    # 表头
    headers = ['指标'] + years
    header_line = '| ' + ' | '.join(headers) + ' |'
    separator = '|' + '|'.join(['---' for _ in headers]) + '|'
    
    # 数据行
    rows = []
    
    def add_yi_row(label, key, suffix='亿'):
        vals = []
        for y in years:
            val = annual.get(y, {}).get(key)
            if val is not None:
                vals.append(str(val) + suffix)
            else:
                vals.append('N/A')
        rows.append('| ' + label + ' | ' + ' | '.join(vals) + ' |')
    
    def add_pct_row(label, key, suffix='%'):
        vals = []
        for y in years:
            val = annual.get(y, {}).get(key)
            if val is not None:
                vals.append(str(round(val, 2)) + suffix)
            else:
                vals.append('N/A')
        rows.append('| ' + label + ' | ' + ' | '.join(vals) + ' |')
    
    def add_num_row(label, key, fmt='.2f', suffix=''):
        vals = []
        for y in years:
            val = annual.get(y, {}).get(key)
            if val is not None:
                try:
                    vals.append(format(float(val), fmt) + suffix)
                except:
                    vals.append(str(val) + suffix)
            else:
                vals.append('N/A')
        rows.append('| ' + label + ' | ' + ' | '.join(vals) + ' |')
    
    # 营收/净利
    add_yi_row('营业收入', 'revenue_yi')
    add_yi_row('归母净利润', 'net_profit_yi')
    add_yi_row('扣非净利润', 'deduct_net_profit_yi')
    add_pct_row('营收增速', 'revenue_growth')
    add_pct_row('净利增速', 'profit_growth')
    
    # 盈利能力
    add_num_row('每股收益(EPS)', 'eps', '.4f', '元')
    add_num_row('扣非每股收益', 'deduct_eps', '.4f', '元')
    add_num_row('每股净资产', 'bps', '.2f', '元')
    add_pct_row('加权ROE', 'roe')
    add_pct_row('毛利率', 'gross_margin')
    add_pct_row('净利率', 'net_margin')
    
    # 资产负债
    add_yi_row('总资产', 'total_assets')
    add_yi_row('总负债', 'total_liab')
    add_yi_row('归母净资产', 'parent_equity')
    add_pct_row('资产负债率', 'debt_ratio')
    
    # 现金流
    add_yi_row('经营现金流', 'op_cash_flow')
    add_num_row('每股经营现金流', 'op_cash_ps', '.2f', '元')
    
    # 趋势分析
    trend_years = trend.get('years', years)
    trend_years_str = trend_years[:3]
    
    rows.append('| **趋势分析** | **---** | **---** | **---** |')
    rows.append('| 营收趋势 | ' + trend.get('revenue_trend', 'N/A') + ' |')
    rows.append('| 净利趋势 | ' + trend.get('profit_trend', 'N/A') + ' |')
    rows.append('| 毛利率趋势 | ' + trend.get('gross_margin_trend', 'N/A') + ' |')
    rows.append('| ROE趋势 | ' + trend.get('roe_trend', 'N/A') + ' |')
    
    return [header_line, separator] + rows


def _identify_financial_risks(annual):
    """识别财务风险"""
    risks = []
    years = sorted(annual.keys(), reverse=True)
    
    for i, year in enumerate(years[:3]):
        rec = annual.get(year, {})
        
        # 亏损风险
        net_profit_yi = rec.get('net_profit_yi')
        if net_profit_yi is not None and net_profit_yi < 0:
            risks.append({
                'level': 'high',
                'year': year,
                'signal': year + '年亏损' + str(round(abs(net_profit_yi), 2)) + '亿元'
            })
        
        # 扣非亏损
        deduct_yi = rec.get('deduct_net_profit_yi')
        if deduct_yi is not None and deduct_yi < 0:
            risks.append({
                'level': 'high',
                'year': year,
                'signal': year + '年扣非亏损' + str(round(abs(deduct_yi), 2)) + '亿元（主业盈利能力弱）'
            })
        
        # 由盈转亏
        if i < len(years) - 1:
            prev_rec = annual.get(years[i+1], {})
            prev_profit = prev_rec.get('net_profit_yi')
            curr_profit = rec.get('net_profit_yi')
            if prev_profit is not None and curr_profit is not None:
                if prev_profit > 0 and curr_profit < 0:
                    risks.append({
                        'level': 'high',
                        'year': year,
                        'signal': year + '年由盈转亏（' + str(round(prev_profit, 2)) + '亿→' + str(round(curr_profit, 2)) + '亿）'
                    })
        
        # 营收大幅下滑
        rev_growth = rec.get('revenue_growth')
        if rev_growth is not None and rev_growth < -20:
            risks.append({
                'level': 'medium',
                'year': year,
                'signal': year + '年营收同比下滑' + str(round(abs(rev_growth), 1)) + '%'
            })
        
        # 净利大幅下滑
        profit_growth = rec.get('profit_growth')
        if profit_growth is not None and profit_growth < -50:
            risks.append({
                'level': 'medium',
                'year': year,
                'signal': year + '年净利同比下滑' + str(round(abs(profit_growth), 1)) + '%'
            })
        
        # 毛利率异常
        gross_margin = rec.get('gross_margin')
        if gross_margin is not None and gross_margin < 10:
            risks.append({
                'level': 'medium',
                'year': year,
                'signal': year + '年毛利率极低（' + str(round(gross_margin, 1)) + '%）'
            })
        
        # ROE为负
        roe = rec.get('roe')
        if roe is not None and roe < 0:
            risks.append({
                'level': 'medium',
                'year': year,
                'signal': year + '年ROE为负（' + str(round(roe, 2)) + '%）'
            })
    
    return risks


def _supplement_from_annual_pdf(stock_code, market, data_dir, years):
    """从年报PDF补充历史数据"""
    if not data_dir:
        return {}
    
    # 方法1: 从预提取的sections.json读取
    sections_path = os.path.join(data_dir, 'annual_report_sections.json')
    annual = {}
    
    if os.path.exists(sections_path):
        try:
            with open(sections_path, 'r', encoding='utf-8') as f:
                sections = json.load(f)
        except:
            sections = {}
        
        fh = sections.get('financial_highlights', '')
        amounts = re.findall(r'([\d,]+)\.\d{2}\s*\((\d{4})\)', fh)
        for amount_str, year in amounts:
            amount = float(amount_str.replace(',', ''))
            year_str = str(year)
            if year_str not in annual:
                annual[year_str] = {}
            
            if amount > 1e8:
                annual[year_str]['revenue_yi'] = round(amount / 1e8, 2)
    
    # 方法2: 直接从PDF提取更多字段
    if data_dir:
        years_to_try = [datetime.now().year - i for i in range(years)]
        for year in years_to_try:
            year_str = str(year)
            # 调用extract_financial_from_pdf提取
            pdf_metrics = extract_financial_from_pdf(stock_code, year, data_dir)
            if pdf_metrics and year_str not in annual:
                annual[year_str] = {}
            
            if pdf_metrics:
                # 转换扣非净利润
                deduct_np = pdf_metrics.get('扣非净利润', '')
                if deduct_np:
                    if year_str not in annual:
                        annual[year_str] = {}
                    try:
                        val = float(str(deduct_np).replace(',', ''))
                        # PDF返回的是元，转换为亿元
                        annual[year_str]['deduct_net_profit_yi'] = round(val / 1e8, 2)
                    except Exception as _sexc:
                        record(__name__, '_supplement_from_annual_pdf', _sexc, note='静默降级')
                        pass
                
                # 转换资产负债率
                debt_ratio = pdf_metrics.get('资产负债率', '')
                if debt_ratio:
                    if year_str not in annual:
                        annual[year_str] = {}
                    try:
                        annual[year_str]['debt_ratio'] = float(str(debt_ratio).replace('%', ''))
                    except Exception as _sexc:
                        record(__name__, '_supplement_from_annual_pdf', _sexc, note='静默降级')
                        pass
                
                # 转换营业收入
                revenue = pdf_metrics.get('营业收入', '')
                if revenue:
                    if year_str not in annual:
                        annual[year_str] = {}
                    if 'revenue_yi' not in annual[year_str]:
                        try:
                            val = float(str(revenue).replace(',', ''))
                            annual[year_str]['revenue_yi'] = round(val / 1e8, 2)
                        except Exception as _sexc:
                            record(__name__, '_supplement_from_annual_pdf', _sexc, note='静默降级')
                            pass
                
                print(f"[PDF补充] {stock_code} {year_str}: 扣非净利润={pdf_metrics.get('扣非净利润', 'N/A')}, 资产负债率={pdf_metrics.get('资产负债率', 'N/A')}")
    
    return annual


def format_multi_year_summary(result):
    """格式化多年财务分析为Markdown文本"""
    if not result:
        return '财务数据暂无可用'
    
    annual = result.get('annual', {})
    trend = result.get('trend_analysis', {})
    risks = result.get('risks', [])
    warnings = result.get('warnings', [])
    years = sorted(annual.keys(), reverse=True)
    
    lines = []
    
    # 标题
    lines.append('## 📊 3年+最近一期财务对比分析')
    lines.append('')
    
    # 风险提示
    if risks:
        lines.append('### 🔴 财务风险信号')
        for r in risks[:5]:
            level = '🔴' if r['level'] == 'high' else '🟡'
            lines.append('- ' + level + ' **' + r.get('year', '') + '** ' + r['signal'])
        lines.append('')
    
    # 趋势分析
    if trend and 'years' in trend:
        lines.append('### 📈 趋势分析')
        years_str = ' → '.join(trend['years'][:3])
        lines.append('- **覆盖期间**: ' + years_str)
        lines.append('- **营收趋势**: ' + str(trend.get('revenue_trend', 'N/A')))
        lines.append('- **净利趋势**: ' + str(trend.get('profit_trend', 'N/A')))
        lines.append('- **毛利率趋势**: ' + str(trend.get('gross_margin_trend', 'N/A')))
        lines.append('- **ROE趋势**: ' + str(trend.get('roe_trend', 'N/A')))
        lines.append('')
    
    # 对比表格
    table = result.get('comparison_table', [])
    if table:
        lines.append('### 📋 核心指标对比表')
        for row in table:
            lines.append(row)
        lines.append('')
    
    # 警告
    if warnings:
        lines.append('### ⚠️ 数据警告')
        for w in warnings:
            lines.append('- ' + w)
        lines.append('')
    
    return '\n'.join(lines)


# ============================================================
if __name__ == '__main__':
    stock = '002259'
    data_dir = r'C:\Users\Administrator\.qclaw\workspace-agent-550df5d1\skills\listed-company-analysis\output\002259_20260511\data'
    
    result = fetch_financial_multi_year(stock, 'a', data_dir, years=3)
    
    print('\n' + '='*60)
    print(format_multi_year_summary(result))
    print('\n=== 原始数据 ===')
    print(json.dumps(result.get('annual', {}), ensure_ascii=False, indent=2, default=str))
