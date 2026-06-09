# -*- coding: utf-8 -*-
"""
hk_financial.py - 港股财务数据模块
数据来源：AKShare (东方财富源)
支持：财务指标/估值/分红/公司概况

注意：AKShare接口调用需间隔2秒，否则可能返回None
"""
import sys
import os
import time
import json
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional

sys.stdout.reconfigure(encoding='utf-8')

try:
    import akshare as ak
    AKSHARE_OK = True
except ImportError:
    AKSHARE_OK = False
    print("[WARN] AKShare 未安装，请运行: pip install akshare")


def fetch_hk_financial_indicator(stock_code: str, years: int = 10) -> Dict:
    """
    获取港股财务指标（AKShare东方财富源）

    Args:
        stock_code: 港股代码（不带HK前缀，如 '06939'）
        years: 获取最近几年

    Returns:
        {
            'success': bool,
            'indicators': [...],
            'valuation': {...},
            'dividend': [...],
            'profile': {...},
            'warnings': [],
            '_meta': {'source': 'akshare_hk_fin', 'steps': [...], 'fetched_at': ...}
        }
    """
    if not AKSHARE_OK:
        return {'success': False, 'error': 'AKShare未安装'}

    result = {
        'success': True,
        'stock_code': stock_code,
        'fetch_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'indicators': [],
        'valuation': {},
        'dividend': [],
        'profile': {},
        'warnings': [],
        '_meta': {
            'source': 'akshare_hk_fin',
            'steps': [],
            'fetched_at': datetime.now().isoformat(),
        },
    }

    # 1. 财务指标（利润表+资产表综合，36字段）
    try:
        time.sleep(1.5)
        df_ind = ak.stock_financial_hk_analysis_indicator_em(symbol=stock_code)
        if df_ind is not None and len(df_ind) > 0:
            df_ind = df_ind.sort_values('REPORT_DATE', ascending=False).head(years)
            for _, row in df_ind.iterrows():
                date_str = str(row.get('REPORT_DATE', ''))[:10] if pd.notna(row.get('REPORT_DATE')) else ''
                result['indicators'].append({
                    'date': date_str,
                    'fiscal_year': row.get('FISCAL_YEAR', ''),
                    'currency': row.get('CURRENCY', 'HKD'),
                    'operate_income': _safe_float(row.get('OPERATE_INCOME')),
                    'income_yoy': _safe_float(row.get('OPERATE_INCOME_YOY')),
                    'gross_profit': _safe_float(row.get('GROSS_PROFIT')),
                    'gross_margin': _safe_float(row.get('GROSS_PROFIT_RATIO')),
                    'holder_profit': _safe_float(row.get('HOLDER_PROFIT')),
                    'profit_yoy': _safe_float(row.get('HOLDER_PROFIT_YOY')),
                    'net_margin': _safe_float(row.get('NET_PROFIT_RATIO')),
                    'roe': _safe_float(row.get('ROE_AVG')),
                    'roe_yearly': _safe_float(row.get('ROE_YEARLY')),
                    'roa': _safe_float(row.get('ROA')),
                    'debt_asset_ratio': _safe_float(row.get('DEBT_ASSET_RATIO')),
                    'current_ratio': _safe_float(row.get('CURRENT_RATIO')),
                    'basic_eps': _safe_float(row.get('BASIC_EPS')),
                    'bps': _safe_float(row.get('BPS')),
                    'ocf_per_sales': _safe_float(row.get('OCF_SALES')),
                })
            print("[OK] 财务指标: " + str(len(result['indicators'])) + "期")
            result['_meta']['steps'].append({'step': 'financial_indicator', 'source': 'akshare_hk_fin', 'count': len(result['indicators']), 'status': 'OK'})
        else:
            result['warnings'].append('财务指标数据为空')
            result['_meta']['steps'].append({'step': 'financial_indicator', 'source': 'akshare_hk_fin', 'count': 0, 'status': 'EMPTY'})
    except Exception as e:
        result['warnings'].append('财务指标获取失败: ' + str(e))
        result['_meta']['steps'].append({'step': 'financial_indicator', 'source': 'akshare_hk_fin', 'error': str(e)[:80], 'status': 'FAIL'})

    # 2. 估值指标
    try:
        time.sleep(1.5)
        df_val = ak.stock_hk_financial_indicator_em(symbol=stock_code)
        if df_val is not None and len(df_val) > 0:
            row = df_val.iloc[-1]
            result['valuation'] = {
                'market_cap': _safe_float(row.get('总市值(港元)')),
                'pe_ttm': _safe_float(row.get('市盈率')),
                'pb': _safe_float(row.get('市净率')),
                'roe': _safe_float(row.get('股东权益回报率(%)')),
                'dividend_yield': _safe_float(row.get('股息率TTM(%)')),
                'eps': _safe_float(row.get('基本每股收益(元)')),
                'bps': _safe_float(row.get('每股净资产(元)')),
                'revenue': _safe_float(row.get('营业总收入')),
                'net_profit': _safe_float(row.get('净利润')),
                'revenue_growth': _safe_float(row.get('营业总收入滚动环比增长(%)')),
                'profit_growth': _safe_float(row.get('净利润滚动环比增长(%)')),
                'shares': _safe_float(row.get('已发行股本(股)')),
            }
            pe = result['valuation'].get('pe_ttm')
            pb = result['valuation'].get('pb')
            print("[OK] 估值指标: PE=" + str(pe) + ", PB=" + str(pb))
            result['_meta']['steps'].append({'step': 'valuation', 'source': 'akshare_hk_fin', 'status': 'OK'})
        else:
            result['warnings'].append('估值指标数据为空')
            result['_meta']['steps'].append({'step': 'valuation', 'source': 'akshare_hk_fin', 'status': 'EMPTY'})
    except Exception as e:
        result['warnings'].append('估值指标获取失败: ' + str(e))
        result['_meta']['steps'].append({'step': 'valuation', 'source': 'akshare_hk_fin', 'error': str(e)[:80], 'status': 'FAIL'})

    # 3. 分红数据
    try:
        time.sleep(1.5)
        df_div = ak.stock_hk_dividend_payout_em(symbol=stock_code)
        if df_div is not None and len(df_div) > 0:
            for _, row in df_div.iterrows():
                result['dividend'].append({
                    'fiscal_year': str(row.get('财政年度', '')),
                    'plan': str(row.get('分红方案', '')),
                    'ex_date': str(row.get('除净日', '')),
                    'record_date': str(row.get('截至过户日', '')),
                    'pay_date': str(row.get('发放日', '')),
                    'type': str(row.get('分配类型', '')),
                })
            print("[OK] 分红: " + str(len(result['dividend'])) + "期")
            result['_meta']['steps'].append({'step': 'dividend', 'source': 'akshare_hk_fin', 'count': len(result['dividend']), 'status': 'OK'})
    except Exception as e:
        result['warnings'].append('分红数据获取失败: ' + str(e))
        result['_meta']['steps'].append({'step': 'dividend', 'source': 'akshare_hk_fin', 'error': str(e)[:80], 'status': 'FAIL'})

    # 4. 公司概况
    try:
        time.sleep(1.5)
        df_pro = ak.stock_hk_company_profile_em(symbol=stock_code)
        if df_pro is not None and len(df_pro) > 0:
            row = df_pro.iloc[-1]
            result['profile'] = {
                'company_name_cn': row.get('公司名称', ''),
                'company_name_en': row.get('英文名称', ''),
                'registered_place': row.get('注册地', ''),
                'established_date': str(row.get('公司成立日期', '')),
                'industry': row.get('所属行业', ''),
                'chairman': row.get('董事长', ''),
                'employees': _safe_int(row.get('员工人数')),
                'auditor': row.get('核数师', ''),
                'year_end': row.get('年结日', ''),
                'website': row.get('公司网址', ''),
                'description': str(row.get('公司介绍', ''))[:2000],
            }
            name = result['profile'].get('company_name_cn', '')
            ind = result['profile'].get('industry', '')
            print("[OK] 公司概况: " + name + " | " + ind)
            result['_meta']['steps'].append({'step': 'company_profile', 'source': 'akshare_hk_fin', 'status': 'OK'})
    except Exception as e:
        result['warnings'].append('公司概况获取失败: ' + str(e))
        result['_meta']['steps'].append({'step': 'company_profile', 'source': 'akshare_hk_fin', 'error': str(e)[:80], 'status': 'FAIL'})

    return result


def analyze_hk_financial(data: Dict) -> Dict:
    """分析港股财务数据，输出风险信号"""
    warnings = []
    highlights = []

    indicators = data.get('indicators', [])
    valuation = data.get('valuation', {})

    if indicators:
        latest = indicators[0]
        prev = indicators[1] if len(indicators) > 1 else {}

        # 营收
        yoy = latest.get('income_yoy')
        if yoy is not None and yoy < 0:
            warnings.append('营收同比下滑 ' + str(round(yoy, 1)) + '%')
        elif yoy is not None and yoy > 20:
            highlights.append('营收同比增长 ' + str(round(yoy, 1)) + '%')

        # 净利润
        hp = latest.get('holder_profit')
        if hp is not None and hp < 0:
            warnings.append('归母净利润亏损 ' + str(round(hp, 0)))
        elif hp is not None and prev.get('holder_profit'):
            prev_val = prev['holder_profit']
            if prev_val > 0:
                change = (hp - prev_val) / abs(prev_val) * 100
                if change < -30:
                    warnings.append('归母净利润同比下降 ' + str(round(change, 1)) + '%')

        # 毛利率
        gm = latest.get('gross_margin')
        if gm is not None and gm < 20:
            warnings.append('毛利率偏低: ' + str(round(gm, 1)) + '%')
        elif gm is not None and gm > 50:
            highlights.append('高毛利率: ' + str(round(gm, 1)) + '%')

        # ROE
        roe = latest.get('roe')
        if roe is not None and roe < 5:
            warnings.append('ROE偏低: ' + str(round(roe, 1)) + '%')
        elif roe is not None and roe > 15:
            highlights.append('高ROE: ' + str(round(roe, 1)) + '%')

        # 负债率
        dar = latest.get('debt_asset_ratio')
        if dar is not None and dar > 70:
            warnings.append('资产负债率偏高: ' + str(round(dar, 1)) + '%')

    # 估值
    pe = valuation.get('pe_ttm')
    pb = valuation.get('pb')
    if pe is not None and pe < 0:
        warnings.append('PE为负(' + str(round(pe, 1)) + '): 公司亏损')
    elif pe is not None and pe > 50:
        warnings.append('PE偏高: ' + str(round(pe, 1)) + 'x')
    if pb is not None and pb < 1.5 and pb > 0:
        highlights.append('PB较低: ' + str(round(pb, 2)) + 'x（破净可能）')

    summary = _build_summary(data)

    return {
        'warnings': warnings,
        'highlights': highlights,
        'summary': summary,
    }


def _safe_float(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except:
        return None


def _safe_int(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(float(val))
    except:
        return None


def _build_summary(data: Dict) -> str:
    parts = []
    profile = data.get('profile', {})
    if profile.get('company_name_cn'):
        ind = profile.get('industry', '')
        parts.append('公司: ' + profile['company_name_cn'] + (' (' + ind + ')' if ind else ''))

    indicators = data.get('indicators', [])
    if indicators:
        lat = indicators[0]
        cur = lat.get('currency', 'HKD')
        oi = lat.get('operate_income')
        hp = lat.get('holder_profit')
        gm = lat.get('gross_margin')
        roe = lat.get('roe')
        if oi: parts.append('营收: ' + str(round(oi, 0)) + ' ' + cur)
        if hp: parts.append('归母净利润: ' + str(round(hp, 0)) + ' ' + cur)
        if gm: parts.append('毛利率: ' + str(round(gm, 1)) + '%')
        if roe: parts.append('ROE: ' + str(round(roe, 1)) + '%')

    v = data.get('valuation', {})
    pe = v.get('pe_ttm')
    pb = v.get('pb')
    mc = v.get('market_cap')
    if pe is not None: parts.append('PE: ' + str(round(pe, 1)) + 'x')
    if pb is not None: parts.append('PB: ' + str(round(pb, 2)) + 'x')
    if mc is not None: parts.append('市值: ' + str(round(mc, 0)) + ' HKD')

    return ' | '.join(parts)


def fetch_hk_financial(stock_code: str, market: str, data_dir: str = None) -> Dict:
    """
    主入口：获取港股财务数据

    Args:
        stock_code: 股票代码（如 '06939' 或 'HK06939'）
        market: 市场 ('hk')
        data_dir: 数据保存目录

    Returns:
        财务分析结果
    """
    pure_code = stock_code.upper().replace('HK', '').replace(' ', '')
    result = fetch_hk_financial_indicator(pure_code, years=10)

    if result.get('success'):
        analysis = analyze_hk_financial(result)
        result['analysis'] = analysis
        result['warnings'].extend(analysis.get('warnings', []))
        result['highlights'] = analysis.get('highlights', [])

    if data_dir and result.get('success'):
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, 'hk_financial.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print("[SAVE] 港股财务数据: " + path)

    return result


# 测试
if __name__ == '__main__':
    data_dir = r'C:\Users\Administrator\.qclaw\workspace-agent-550df5d1\output\06939_20260420\data'
    result = fetch_hk_financial('06939', 'hk', data_dir)
    analysis = result.get('analysis', {})
    print('\n=== 分析结果 ===')
    print('Warnings:', result.get('warnings'))
    print('Highlights:', result.get('highlights'))
    print('Summary:', analysis.get('summary', ''))


def generate_report_section(data: dict) -> list:
    lines = []
    lines.append("## 财务报表分析（港股）")
    lines.append("")

    profile = data.get('profile', {})
    if profile:
        lines.append(f"**公司**: {profile.get('company_name_cn', '未知')} ({profile.get('industry', '')})")
        lines.append(f"**董事长**: {profile.get('chairman', '未知')} | **核数师**: {profile.get('auditor', '未知')}")
        lines.append(f"**员工**: {profile.get('employees', '未知')}人 | **注册地**: {profile.get('registered_place', '未知')}")
        lines.append("")

    valuation = data.get('valuation', {})
    if valuation:
        pe = valuation.get('pe_ttm')
        pb = valuation.get('pb')
        mc = valuation.get('market_cap')
        dy = valuation.get('dividend_yield')
        lines.append("**估值指标**:")
        lines.append(f"- 市值: {mc:,.0f} HKD" if mc else "- 市值: 未知")
        lines.append(f"- PE: {pe:.1f}x (亏损)" if pe and pe < 0 else f"- PE: {pe:.1f}x" if pe else "- PE: 未知")
        lines.append(f"- PB: {pb:.2f}x" if pb else "- PB: 未知")
        lines.append(f"- 股息率: {dy:.2f}%" if dy else "- 股息率: 未知")
        lines.append("")

    indicators = data.get('indicators', [])
    if indicators:
        lat = indicators[0]
        lines.append("**财务指标（最新一期）**:")
        lines.append(f"- 报告期: {lat.get('date', '未知')} | 币种: {lat.get('currency', 'HKD')}")
        lines.append(f"- 营收: {lat.get('operate_income'):,.0f} HKD (同比: {lat.get('income_yoy'):+.1f}%)" if lat.get('operate_income') else "- 营收: 未知")
        lines.append(f"- 毛利: {lat.get('gross_profit'):,.0f} HKD | 毛利率: {lat.get('gross_margin'):.1f}%" if lat.get('gross_margin') else "- 毛利: 未知")
        lines.append(f"- 归母净利润: {lat.get('holder_profit'):,.0f} HKD" if lat.get('holder_profit') else "- 归母净利润: 未知")
        lines.append(f"- ROE: {lat.get('roe'):.1f}%" if lat.get('roe') else "- ROE: 未知")
        lines.append(f"- 资产负债率: {lat.get('debt_asset_ratio'):.1f}%" if lat.get('debt_asset_ratio') else "- 资产负债率: 未知")
        lines.append("")

        if len(indicators) > 1:
            show_count = len(indicators)
            lines.append(f"**近{show_count}年财务趋势**:")
            lines.append("| 报告期 | 营收(HKD) | 同比 | 毛利率 | 归母净利润 | ROE | 资产负债率 |")
            lines.append("|--------|-----------|------|--------|-----------|-----|----------|")
            for r in indicators:
                oi = f"{r.get('operate_income',0)/1e8:,.0f}亿" if r.get('operate_income') else "N/A"
                yoy = f"{r.get('income_yoy',0):+.1f}%" if r.get('income_yoy') is not None else "N/A"
                gm = f"{r.get('gross_margin',0):.1f}%" if r.get('gross_margin') else "N/A"
                hp = f"{r.get('holder_profit',0)/1e8:,.0f}亿" if r.get('holder_profit') else "N/A"
                roe = f"{r.get('roe',0):.1f}%" if r.get('roe') else "N/A"
                dar = f"{r.get('debt_asset_ratio',0):.1f}%" if r.get('debt_asset_ratio') else "N/A"
                lines.append(f"| {r.get('date','?')} | {oi} | {yoy} | {gm} | {hp} | {roe} | {dar} |")
            lines.append("")

    dividend = data.get('dividend', [])
    if dividend:
        lines.append("**分红历史**:")
        for d in dividend[:4]:
            lines.append(f"- {d.get('fiscal_year','?')} | {d.get('plan','?')} | 除净日: {d.get('ex_date','?')}")
        lines.append("")

    analysis = data.get('analysis', {})
    warnings = analysis.get('warnings', []) or data.get('warnings', [])
    if warnings:
        lines.append("**⚠️ 风险信号**:")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return lines
