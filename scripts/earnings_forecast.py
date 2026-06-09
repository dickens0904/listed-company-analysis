#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
盈利预测与估值建模模块

功能：
1. 基于历史财务数据做未来3年盈利预测（保守/中性/乐观三情景）
2. DCF估值模型
3. PE/PB相对估值法
4. 目标价推导与投资建议

数据源：
- 历史财务数据：financial.py / multi_year_trend.py
- 行业均值：industry.py 可比公司数据
- 无风险利率：Tushare宏观数据（或硬编码）
"""

import json
import math
import os
import sys
from typing import Dict, List, Optional, Tuple

# 支持独立运行
if __name__ == '__main__' and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.safe_request import safe_get, safe_extract


# ==================== 常量配置 ====================

# 无风险利率（中国10年期国债收益率，约2.5%）
RISK_FREE_RATE = 0.025

# 市场风险溢价（中国A股，约5.5%）
MARKET_RISK_PREMIUM = 0.055

# 永续增长率（保守1.5%，中性2.0%，乐观2.5%）
TERMINAL_GROWTH_RATES = {
    'conservative': 0.015,
    'neutral': 0.020,
    'optimistic': 0.025,
}

# 预测情景参数
SCENARIOS = {
    'conservative': {
        'revenue_growth_adj': -0.03,  # 比趋势低3pct
        'margin_adj': -0.005,         # 利润率低0.5pct
        'discount_adj': 0.01,         # 折现率高1pct
    },
    'neutral': {
        'revenue_growth_adj': 0,
        'margin_adj': 0,
        'discount_adj': 0,
    },
    'optimistic': {
        'revenue_growth_adj': 0.03,   # 比趋势高3pct
        'margin_adj': 0.005,          # 利润率高0.5pct
        'discount_adj': -0.01,        # 折现率低1pct
    },
}


# ==================== 核心类 ====================

class EarningsForecaster:
    """盈利预测器"""
    
    def __init__(self, stock_code: str, market: str = 'a'):
        self.stock_code = stock_code
        self.market = market
        self.historical_data = None
        self.industry_peers = None
        
    def load_historical_data(self, financial_data: Dict, multi_year_data: Optional[Dict] = None):
        """
        加载历史财务数据
        
        Args:
            financial_data: financial.py 返回的数据
            multi_year_data: multi_year_trend.py 返回的数据（可选）
        """
        self.historical_data = {
            'financial': financial_data,
            'multi_year': multi_year_data or {},
        }
        
    def load_industry_peers(self, peers_data: List[Dict]):
        """
        加载行业可比公司数据
        
        Args:
            peers_data: industry.py 返回的可比公司列表
        """
        self.industry_peers = peers_data
        
    def _extract_historical_metrics(self) -> Dict:
        """提取关键历史指标"""
        fin = self.historical_data.get('financial', {})
        
        # 尝试从 multi_year_trend 获取多年数据
        trend = self.historical_data.get('multi_year', {})
        
        metrics = {
            'revenue': [],
            'net_profit': [],
            'gross_margin': [],
            'net_margin': [],
            'roe': [],
            'total_shares': None,  # 总股本（亿股）
        }
        
        # 从 trend 数据提取
        if trend and 'years' in trend:
            years = trend.get('years', [])
            revenue_list = trend.get('revenue', [])
            profit_list = trend.get('net_profit', [])
            
            for i, year in enumerate(years):
                if i < len(revenue_list):
                    metrics['revenue'].append({
                        'year': year,
                        'value': revenue_list[i],
                    })
                if i < len(profit_list):
                    metrics['net_profit'].append({
                        'year': year,
                        'value': profit_list[i],
                    })
        
        # 从 financial 数据补充最新一期
        if fin:
            latest_revenue = fin.get('revenue', 0)
            latest_profit = fin.get('net_profit', 0)
            latest_year = fin.get('year', 2025)
            
            if latest_revenue and (not metrics['revenue'] or metrics['revenue'][-1]['year'] != latest_year):
                metrics['revenue'].append({'year': latest_year, 'value': latest_revenue})
            if latest_profit and (not metrics['net_profit'] or metrics['net_profit'][-1]['year'] != latest_year):
                metrics['net_profit'].append({'year': latest_year, 'value': latest_profit})
                
            # 利润率
            if latest_revenue and latest_profit:
                metrics['net_margin'].append({
                    'year': latest_year,
                    'value': latest_profit / latest_revenue,
                })
                
            # ROE
            roe = fin.get('roe')
            if roe:
                metrics['roe'].append({'year': latest_year, 'value': roe})
                
            # 总股本
            metrics['total_shares'] = fin.get('total_shares')
            
        return metrics
    
    def _calculate_cagr(self, values: List[float], years: int = 3) -> float:
        """计算CAGR"""
        if len(values) < 2:
            return 0.05  # 默认5%
            
        # 取最近N年
        recent = values[-years:] if len(values) >= years else values
        if len(recent) < 2:
            return 0.05
            
        start = recent[0]
        end = recent[-1]
        n = len(recent) - 1
        
        if start <= 0 or end <= 0:
            return 0.05
            
        return (end / start) ** (1 / n) - 1
    
    def _forecast_scenario(self, metrics: Dict, scenario: str) -> Dict:
        """
        单情景预测
        
        Returns:
            {
                'years': [2026, 2027, 2028],
                'revenue': [...],
                'net_profit': [...],
                'net_margin': [...],
                'revenue_cagr': 0.15,
                'profit_cagr': 0.18,
            }
        """
        params = SCENARIOS[scenario]
        
        # 历史营收和利润
        revenues = [r['value'] for r in metrics['revenue'] if r['value']]
        profits = [p['value'] for p in metrics['net_profit'] if p['value']]
        
        # 计算历史CAGR
        revenue_cagr = self._calculate_cagr(revenues)
        profit_cagr = self._calculate_cagr(profits)
        
        # 调整后的增长率
        adj_revenue_cagr = max(-0.10, min(0.50, revenue_cagr + params['revenue_growth_adj']))
        adj_profit_cagr = max(-0.15, min(0.60, profit_cagr + params['revenue_growth_adj']))
        
        # 最新基数
        base_revenue = revenues[-1] if revenues else 100  # 亿元
        base_profit = profits[-1] if profits else 10
        
        # 历史净利率
        net_margins = [m['value'] for m in metrics['net_margin'] if m['value']]
        avg_margin = sum(net_margins) / len(net_margins) if net_margins else 0.10
        adj_margin = max(0.01, min(0.50, avg_margin + params['margin_adj']))
        
        # 预测未来3年
        forecast_years = [2026, 2027, 2028]
        forecast_revenue = []
        forecast_profit = []
        forecast_margin = []
        
        for i, year in enumerate(forecast_years):
            # 营收 = 上年营收 * (1 + CAGR)
            if i == 0:
                rev = base_revenue * (1 + adj_revenue_cagr)
            else:
                rev = forecast_revenue[-1] * (1 + adj_revenue_cagr)
                
            # 利润 = 营收 * 净利率（或按利润CAGR）
            # 采用混合法：前两年按利润CAGR，第三年趋近营收*利润率
            if i < 2:
                if i == 0:
                    prof = base_profit * (1 + adj_profit_cagr)
                else:
                    prof = forecast_profit[-1] * (1 + adj_profit_cagr)
            else:
                prof = rev * adj_margin
                
            margin = prof / rev if rev > 0 else 0
            
            forecast_revenue.append(round(rev, 2))
            forecast_profit.append(round(prof, 2))
            forecast_margin.append(round(margin, 4))
            
        return {
            'years': forecast_years,
            'revenue': forecast_revenue,
            'net_profit': forecast_profit,
            'net_margin': forecast_margin,
            'revenue_cagr': round(adj_revenue_cagr, 4),
            'profit_cagr': round(adj_profit_cagr, 4),
            'terminal_margin': round(adj_margin, 4),
        }
    
    def forecast_all_scenarios(self) -> Dict:
        """
        三情景预测
        
        Returns:
            {
                'conservative': {...},
                'neutral': {...},
                'optimistic': {...},
                'base_metrics': {...},
            }
        """
        metrics = self._extract_historical_metrics()
        
        return {
            'conservative': self._forecast_scenario(metrics, 'conservative'),
            'neutral': self._forecast_scenario(metrics, 'neutral'),
            'optimistic': self._forecast_scenario(metrics, 'optimistic'),
            'base_metrics': metrics,
        }
    
    def _calculate_wacc(self, beta: float = 1.0, scenario: str = 'neutral') -> float:
        """
        计算WACC（加权平均资本成本）
        
        简化模型：
        WACC = E/(E+D) * Re + D/(E+D) * Rd * (1-T)
        Re = Rf + β * (Rm - Rf)
        """
        params = SCENARIOS[scenario]
        
        # 股权成本
        re = RISK_FREE_RATE + beta * MARKET_RISK_PREMIUM + params['discount_adj']
        
        # 债务成本（简化，假设6%）
        rd = 0.06
        
        # 资本结构（简化，假设股权70%，债权30%）
        equity_ratio = 0.70
        debt_ratio = 0.30
        tax_rate = 0.25
        
        wacc = equity_ratio * re + debt_ratio * rd * (1 - tax_rate)
        return round(wacc, 4)
    
    def dcf_valuation(self, forecast: Dict, scenario: str = 'neutral') -> Dict:
        """
        DCF估值模型
        
        简化假设：
        - 预测期：3年（显性预测）
        - 永续期：Gordon增长模型
        - FCFF ≈ 净利润（简化，假设无重大资本支出和营运资金变化）
        """
        fcfs = forecast['net_profit']  # 简化：FCFF ≈ 净利润
        years = forecast['years']
        
        wacc = self._calculate_wacc(scenario=scenario)
        terminal_growth = TERMINAL_GROWTH_RATES[scenario]
        
        # 显性期现值
        pv_explicit = 0
        for i, fcf in enumerate(fcfs):
            pv = fcf / ((1 + wacc) ** (i + 1))
            pv_explicit += pv
            
        # 终值（Gordon增长模型）
        terminal_fcf = fcfs[-1] * (1 + terminal_growth)
        terminal_value = terminal_fcf / (wacc - terminal_growth)
        pv_terminal = terminal_value / ((1 + wacc) ** len(fcfs))
        
        # 企业价值
        enterprise_value = pv_explicit + pv_terminal
        
        # 股权价值（简化：假设净债务为0）
        equity_value = enterprise_value
        
        # 每股价值
        metrics = self._extract_historical_metrics()
        total_shares = metrics.get('total_shares')
        
        if total_shares and total_shares > 0:
            per_share_value = equity_value / total_shares
        else:
            per_share_value = None
            
        return {
            'wacc': round(wacc, 4),
            'terminal_growth': terminal_growth,
            'pv_explicit': round(pv_explicit, 2),
            'pv_terminal': round(pv_terminal, 2),
            'enterprise_value': round(enterprise_value, 2),
            'equity_value': round(equity_value, 2),
            'per_share_value': round(per_share_value, 2) if per_share_value else None,
            'total_shares': total_shares,
        }
    
    def relative_valuation(self, forecast: Dict) -> Dict:
        """
        相对估值法（PE/PB）
        
        需要行业可比公司数据
        """
        # 预测净利润（中性情景）
        profit_2026 = forecast['net_profit'][0] if forecast.get('net_profit') else None
        
        if not profit_2026 or profit_2026 <= 0:
            return {
                'pe_valuation': None,
                'pb_valuation': None,
                'industry_pe_median': None,
                'industry_pb_median': None,
            }
            
        # 行业PE/PB中位数
        industry_pe = []
        industry_pb = []
        
        if self.industry_peers:
            for peer in self.industry_peers:
                pe = peer.get('pe')
                pb = peer.get('pb')
                if pe and pe > 0 and pe < 200:  # 过滤异常值
                    industry_pe.append(pe)
                if pb and pb > 0 and pb < 50:
                    industry_pb.append(pb)
                    
        pe_median = sorted(industry_pe)[len(industry_pe)//2] if industry_pe else 20
        pb_median = sorted(industry_pb)[len(industry_pb)//2] if industry_pb else 2
        
        # PE估值
        pe_equity_value = profit_2026 * pe_median
        
        # PB估值（需要净资产数据，简化处理）
        # 假设ROE = 10%，则 PB = ROE * PE
        roe = 0.10
        pb_equity_value = None  # 需要净资产数据
        
        metrics = self._extract_historical_metrics()
        total_shares = metrics.get('total_shares')
        
        pe_per_share = pe_equity_value / total_shares if total_shares and pe_equity_value else None
        
        return {
            'pe_valuation': {
                'equity_value': round(pe_equity_value, 2),
                'per_share': round(pe_per_share, 2) if pe_per_share else None,
                'pe_multiple': pe_median,
            },
            'pb_valuation': {
                'pb_multiple': pb_median,
            },
            'industry_pe_median': pe_median,
            'industry_pb_median': pb_median,
        }
    
    def generate_valuation_summary(self) -> Dict:
        """
        生成完整估值摘要
        
        Returns:
            {
                'forecast': {...},
                'dcf': {...},
                'relative': {...},
                'target_price': {...},
                'investment_rating': '买入/增持/中性/减持',
            }
        """
        # 1. 三情景预测
        forecast = self.forecast_all_scenarios()
        
        # 2. DCF估值（中性情景）
        dcf = self.dcf_valuation(forecast['neutral'], scenario='neutral')
        
        # 3. 相对估值
        relative = self.relative_valuation(forecast['neutral'])
        
        # 4. 目标价推导
        target_prices = []
        
        if dcf.get('per_share_value'):
            target_prices.append(('DCF', dcf['per_share_value']))
        if relative.get('pe_valuation', {}).get('per_share'):
            target_prices.append(('PE', relative['pe_valuation']['per_share']))
            
        if target_prices:
            avg_target = sum(p[1] for p in target_prices) / len(target_prices)
            min_target = min(p[1] for p in target_prices)
            max_target = max(p[1] for p in target_prices)
        else:
            avg_target = min_target = max_target = None
            
        # 5. 投资评级（简化逻辑）
        # 需要当前股价，这里留空，由调用方填充
        rating = '待定价'
        
        return {
            'forecast': forecast,
            'dcf': dcf,
            'relative': relative,
            'target_price': {
                'methods': target_prices,
                'average': round(avg_target, 2) if avg_target else None,
                'range': [round(min_target, 2), round(max_target, 2)] if min_target else None,
            },
            'investment_rating': rating,
        }


# ==================== 便捷函数 ====================

def fetch_earnings_forecast(stock_code: str, market: str = 'a', data_dir: str = None) -> Dict:
    """
    兼容analyze.py的调用接口
    
    从已有分析结果中加载数据并生成盈利预测
    """
    # 尝试从data_dir加载之前的分析结果
    analysis_data = {}
    if data_dir:
        results_path = os.path.join(data_dir, 'results.json')
        if os.path.exists(results_path):
            try:
                with open(results_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    findings = saved.get('findings', {})
                    analysis_data = {
                        'financial': findings.get('financial', {}),
                        'multi_year_trend': findings.get('multi_year_trend', {}),
                        'industry': findings.get('industry', {}),
                    }
            except Exception:
                pass
    
    return generate_earnings_forecast(analysis_data, stock_code, market)


def generate_earnings_forecast(analysis_data: Dict, stock_code: str, market: str = 'a') -> Dict:
    """
    生成盈利预测和估值的便捷函数
    
    Args:
        analysis_data: 包含 financial 和 industry 数据的字典
        stock_code: 股票代码
        market: 市场类型
        
    Returns:
        完整估值报告数据
    """
    forecaster = EarningsForecaster(stock_code, market)
    
    # 加载数据
    financial = analysis_data.get('financial', {})
    multi_year = analysis_data.get('multi_year_trend', {})
    industry = analysis_data.get('industry', {})
    
    forecaster.load_historical_data(financial, multi_year)
    
    # 加载可比公司
    peers = industry.get('peers', []) if isinstance(industry, dict) else []
    forecaster.load_industry_peers(peers)
    
    # 生成估值
    result = forecaster.generate_valuation_summary()
    
    # 添加元数据
    result['_meta'] = {
        'source': 'earnings_forecast',
        'stock_code': stock_code,
        'market': market,
    }
    
    return result


def format_forecast_markdown(valuation_data: Dict, stock_code: str) -> str:
    """
    将估值数据格式化为Markdown报告
    """
    lines = []
    
    forecast = valuation_data.get('forecast', {})
    dcf = valuation_data.get('dcf', {})
    relative = valuation_data.get('relative', {})
    target = valuation_data.get('target_price', {})
    
    # 三情景预测表
    lines.append("### 盈利预测（三情景）\n")
    lines.append("| 指标 | 保守 | 中性 | 乐观 |")
    lines.append("|------|------|------|------|")
    
    scenarios = ['conservative', 'neutral', 'optimistic']
    scenario_names = {'conservative': '保守', 'neutral': '中性', 'optimistic': '乐观'}
    
    # 营收预测
    for i, year in enumerate([2026, 2027, 2028]):
        revs = []
        for s in scenarios:
            f = forecast.get(s, {})
            revs.append(f"{f.get('revenue', [None]*3)[i]}" if i < len(f.get('revenue', [])) else '-')
        lines.append(f"| {year}年营收(亿) | {' | '.join(revs)} |")
        
    # 净利润预测
    for i, year in enumerate([2026, 2027, 2028]):
        profits = []
        for s in scenarios:
            f = forecast.get(s, {})
            profits.append(f"{f.get('net_profit', [None]*3)[i]}" if i < len(f.get('net_profit', [])) else '-')
        lines.append(f"| {year}年净利润(亿) | {' | '.join(profits)} |")
        
    # CAGR
    cagrs = []
    for s in scenarios:
        f = forecast.get(s, {})
        cagrs.append(f"{f.get('profit_cagr', 0)*100:.1f}%")
    lines.append(f"| 利润CAGR | {' | '.join(cagrs)} |")
    
    lines.append("")
    
    # DCF估值
    lines.append("### DCF估值\n")
    lines.append(f"- WACC: {dcf.get('wacc', 0)*100:.2f}%")
    lines.append(f"- 永续增长率: {dcf.get('terminal_growth', 0)*100:.2f}%")
    lines.append(f"- 显性期现值: {dcf.get('pv_explicit', 0):.2f}亿元")
    lines.append(f"- 终值现值: {dcf.get('pv_terminal', 0):.2f}亿元")
    lines.append(f"- 企业价值: **{dcf.get('enterprise_value', 0):.2f}亿元**")
    if dcf.get('per_share_value'):
        lines.append(f"- 每股价值(DCF): **{dcf['per_share_value']:.2f}元**")
    lines.append("")
    
    # 相对估值
    lines.append("### 相对估值\n")
    pe = relative.get('pe_valuation', {})
    if pe and pe.get('per_share'):
        lines.append(f"- 行业PE中位数: {pe.get('pe_multiple', 0):.1f}x")
        lines.append(f"- PE估值每股: **{pe['per_share']:.2f}元**")
    else:
        lines.append("- 行业PE数据不足，无法计算")
    lines.append("")
    
    # 目标价
    lines.append("### 目标价推导\n")
    methods = target.get('methods', [])
    if methods:
        for name, price in methods:
            lines.append(f"- {name}法: {price:.2f}元")
        if target.get('average'):
            lines.append(f"\n**综合目标价: {target['average']:.2f}元**")
        if target.get('range'):
            lines.append(f"（区间: {target['range'][0]:.2f} - {target['range'][1]:.2f}元）")
    else:
        lines.append("- 数据不足，无法推导目标价")
    lines.append("")
    
    # 风险提示
    lines.append("> ⚠️ **风险提示**: 以上预测基于历史数据外推，未考虑重大政策变化、行业周期波动、公司战略调整等因素。实际业绩可能与预测存在重大偏差。")
    lines.append("")
    
    return "\n".join(lines)


# ==================== 测试 ====================

if __name__ == '__main__':
    # 测试用例
    test_data = {
        'financial': {
            'revenue': 150.5,
            'net_profit': 74.7,
            'roe': 0.30,
            'total_shares': 12.56,
            'year': 2025,
        },
        'multi_year_trend': {
            'years': [2021, 2022, 2023, 2024, 2025],
            'revenue': [109.5, 127.5, 150.5, 174.0, 150.5],
            'net_profit': [52.5, 62.7, 74.7, 86.2, 74.7],
        },
        'industry': {
            'peers': [
                {'name': 'Peer A', 'pe': 25.5, 'pb': 3.2},
                {'name': 'Peer B', 'pe': 18.3, 'pb': 2.8},
                {'name': 'Peer C', 'pe': 22.0, 'pb': 3.0},
            ]
        }
    }
    
    result = generate_earnings_forecast(test_data, '600519', 'a')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n" + "="*60 + "\n")
    print(format_forecast_markdown(result, '600519'))


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    stock_code = data.get('_meta', {}).get('stock_code', '')
    md = format_forecast_markdown(data, stock_code)
    if md.startswith("## "):
        md = md.split('\n', 1)[1]
    return ["\n## 盈利预测\n\n", md]
