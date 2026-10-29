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
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result


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
        # 🔴 2026-10-20 修复「数据在但接不上」：
        #   旧版读 `fin.get('revenue')` / `fin.get('net_profit')` —— 这两个**顶层字段不存在**，
        #   实际结构是 `financial = {'records': [...], 'latest': {...}}`，
        #   营收在 `records[i]['TOTAL_OPERATE_INCOME']`、净利在 `['PARENT_NETPROFIT']`、
        #   日期在 `['REPORTDATE']`（**注意是 REPORTDATE，不是 REPORT_DATE**）。
        #   结果 revenues=[] → 三个情景全部 insufficient → 目标价永远出不来
        #   → advice_blocked（不出投资建议）。
        #   现改为直接遍历 records，按 REPORTDATE 取年份。
        _recs = (fin.get('records') if isinstance(fin, dict) else None) or []
        _by_year: Dict[int, Dict[str, float]] = {}
        _partial_years = set()      # 只披露了半年/季报、尚无年报的年份
        for r in _recs:
            d = (r.get('REPORTDATE') or r.get('REPORT_DATE') or
                 r.get('NOTICE_DATE') or '')
            y = None
            if isinstance(d, str) and len(d) >= 4 and d[:4].isdigit():
                y = int(d[:4])
            elif isinstance(r.get('DATAYEAR'), (int, str)) and str(r['DATAYEAR']).isdigit():
                y = int(r['DATAYEAR'])
            if not y:
                continue
            rev = r.get('TOTAL_OPERATE_INCOME')
            np_ = r.get('PARENT_NETPROFIT')
            try:
                rev = float(rev) / 1e8 if rev not in (None, '') else None
            except (TypeError, ValueError):
                rev = None
            try:
                np_ = float(np_) / 1e8 if np_ not in (None, '') else None
            except (TypeError, ValueError):
                np_ = None

            # 🔴 2026-10-20：只有**年报**（12-31）才算年度值。
            # 旧版把当年半年报（如 2026-06-30 营收 45.64 亿）当成 2026 年度值，
            # 接在 2025 年报 165.15 亿后面 → CAGR 断崖式 -73% → 被 clamp 到 -10%
            # → 保守/中性/乐观三档营收全部相同（41.08/36.97/33.27），情景失去意义。
            is_annual = isinstance(d, str) and d[5:10] == '12-31'
            if not is_annual:
                _partial_years.add(y)
                continue
            slot = _by_year.setdefault(y, {})
            if rev is not None:
                slot['rev'] = rev
            if np_ is not None:
                slot['np'] = np_

        # 只披露半年报/季报、**且该年无年报**的年份 → 不进入年度序列
        # （2026 只有半年报，若不排除会把 45.64 亿半年营收当成全年，紧接 2025 年报
        #   165.15 亿之后 → CAGR 断崖 -73% → 三档情景被 clamp 压平）
        _orphan_years = sorted(_partial_years - set(_by_year))
        if _orphan_years:
            metrics['partial_years_excluded'] = _orphan_years

        for y in sorted(_by_year):
            slot = _by_year[y]
            if slot.get('rev') is not None and not any(
                    x['year'] == y for x in metrics['revenue']):
                metrics['revenue'].append({'year': y, 'value': slot['rev']})
            if slot.get('np') is not None and not any(
                    x['year'] == y for x in metrics['net_profit']):
                metrics['net_profit'].append({'year': y, 'value': slot['np']})

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
    
    def _calculate_cagr(self, values: List[float], years: int = 3) -> Optional[float]:
        """
        计算CAGR

        2026-10-16 审计修复（P0）：数据不足时返回 None，**不再默认 5%**。
        上游须显式处理"数据不足"，不得把"无数据"当成"年增长5%"外推。
        """
        if not values:
            return None
        valid = [v for v in values if v is not None and v > 0]
        if len(valid) < 2:
            return None

        # 取最近N年
        recent = valid[-years:] if len(valid) >= years else valid
        if len(recent) < 2:
            return None

        start = recent[0]
        end = recent[-1]
        n = len(recent) - 1

        if start <= 0 or end <= 0:
            return None

        return (end / start) ** (1 / n) - 1
    
    def _forecast_scenario(self, metrics: Dict, scenario: str) -> Dict:
        """
        单情景预测

        2026-10-16 审计修复（P0）：**数据不足直接返回 error，不再用
        base_revenue=100亿 / base_profit=10亿 等编造基准值外推**。
        对应五段式铁律"缺口不得写成结论"。

        Returns:
            {
                'years': [2026, 2027, 2028],
                'revenue': [...],
                'net_profit': [...],
                'net_margin': [...],
                'revenue_cagr': 0.15,
                'profit_cagr': 0.18,
            }
            或 {'error': '历史数据不足，无法预测', 'insufficient': True, ...}
        """
        params = SCENARIOS[scenario]

        # 历史营收和利润
        revenues = [r['value'] for r in metrics['revenue'] if r['value']]
        profits = [p['value'] for p in metrics['net_profit'] if p['value']]

        # ── 数据充分性门槛（硬约束）──
        # 至少需要：2 期正营收 + 2 期正净利润，否则无法做有意义的外推
        if len(revenues) < 2 or len(profits) < 2:
            return {
                'error': (f'历史数据不足，无法做{scenario}情景预测'
                          f'（有效营收期数={len(revenues)}，有效净利润期数={len(profits)}，'
                          f'均需≥2）。请先补齐财报数据源（MCP/结构化API），'
                          f'不得使用编造基准值。'),
                'insufficient': True,
                'scenario': scenario,
                'revenue_periods': len(revenues),
                'profit_periods': len(profits),
            }

        # 计算历史CAGR（None 表示无法计算）
        revenue_cagr = self._calculate_cagr(revenues)
        profit_cagr = self._calculate_cagr(profits)

        if revenue_cagr is None or profit_cagr is None:
            return {
                'error': (f'历史增速无法计算（revenue_cagr={revenue_cagr}, '
                          f'profit_cagr={profit_cagr}），通常因期间存在亏损或数据为负。'
                          f'该公司不适合用CAGR外推法预测，建议改用人工判断或情景假设。'),
                'insufficient': True,
                'scenario': scenario,
            }

        # 调整后的增长率
        # 🔴 2026-10-20 修复「三档情景被压平」：旧顺序是
        #   max(-0.10, min(0.50, cagr + adj))
        #   当 cagr 极端（如 -0.73）时，cagr±0.03 都仍 < -0.10 → 全部被 clamp 到
        #   -0.10 → 保守/中性/乐观营收完全相同，情景分析失去意义。
        #   正确顺序：**先对基准 CAGR 做合理区间约束，再加情景偏移**，
        #   保证三档之间至少保留参数设定的差异。
        _base_rev_cagr = max(-0.10, min(0.50, revenue_cagr))
        _base_prof_cagr = max(-0.15, min(0.60, profit_cagr))
        adj_revenue_cagr = max(-0.15, min(0.55, _base_rev_cagr + params['revenue_growth_adj']))
        adj_profit_cagr = max(-0.20, min(0.65, _base_prof_cagr + params['revenue_growth_adj']))

        # 最新基数（已确认有数据）
        base_revenue = revenues[-1]
        base_profit = profits[-1]
        
        # 历史净利率（无 net_margin 时用 净利润/营收 推算；仍无则报错，不默认 10%）
        net_margins = [m['value'] for m in metrics['net_margin'] if m['value']]
        if not net_margins and base_revenue and base_revenue > 0:
            net_margins = [base_profit / base_revenue]
        if not net_margins:
            return {
                'error': '无法确定净利率（缺 net_margin 且营收为0），拒绝预测',
                'insufficient': True,
                'scenario': scenario,
            }
        avg_margin = sum(net_margins) / len(net_margins)
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
        # 2026-10-16 审计修复（P0）：预测数据不足时拒绝出 DCF
        # 注意：insufficient 分支先于任何下标访问，避免 KeyError
        if forecast.get('insufficient') or forecast.get('error') \
                or not forecast.get('net_profit'):
            return {
                'error': '预测数据不足，无法做DCF估值（拒绝用编造现金流出终值）',
                'insufficient': True,
                'forecast_error': forecast.get('error'),
            }

        fcfs = forecast['net_profit']  # 简化：FCFF ≈ 净利润
        if any(f is None or f <= 0 for f in fcfs):
            return {
                'error': '预测净利润存在负值或缺失，DCF 不适用（亏损公司应改用PB/PS）',
                'insufficient': True,
            }

        years = forecast['years']

        wacc = self._calculate_wacc(scenario=scenario)
        terminal_growth = TERMINAL_GROWTH_RATES[scenario]

        # 硬断言：WACC 必须显著大于永续增长率，否则 Gordon 模型失效
        if wacc <= terminal_growth + 0.005:
            return {
                'error': (f'DCF失效：WACC({wacc:.4f}) 未显著大于永续增长率'
                          f'({terminal_growth:.4f})，Gordon终值模型不成立。'
                          f'请检查 WACC 假设（无风险利率/ERP/资本结构）后重算。'),
                'insufficient': True,
                'wacc': wacc,
                'terminal_growth': terminal_growth,
            }        
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
        # 2026-10-16 审计修复（P0）：预测数据不足时拒绝相对估值
        if forecast.get('insufficient') or forecast.get('error'):
            return {
                'error': '预测数据不足，无法做相对估值',
                'insufficient': True,
                'forecast_error': forecast.get('error'),
            }

        # 预测净利润（中性情景）
        profit_2026 = forecast['net_profit'][0] if forecast.get('net_profit') else None

        if not profit_2026 or profit_2026 <= 0:
            return {
                'error': '预测净利润为负或缺失，PE法不适用（亏损公司应改用PB/PS）',
                'insufficient': True,
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

        # 2026-10-16 审计修复（P0）：无同业数据时**不默认 PE=20/PB=2**
        if not industry_pe:
            return {
                'error': ('无有效同业PE数据（industry_peers 为空或全部异常），'
                          '拒绝使用默认 PE=20 倍编造估值。请先通过 '
                          'dzh-mcp.getBlockIndustryObj 拉取同业成分股行情。'),
                'insufficient': True,
                'peer_count': len(self.industry_peers or []),
            }

        pe_median = sorted(industry_pe)[len(industry_pe) // 2]
        pb_median = sorted(industry_pb)[len(industry_pb) // 2] if industry_pb else None
        
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

        # 2026-10-16 审计修复（P0）：任一情景数据不足 → 整体标 insufficient，不出目标价
        _scen_keys = [s for s in ('conservative', 'neutral', 'optimistic') if s in forecast]
        insufficient = bool(_scen_keys) and all(
            forecast[s].get('insufficient') for s in _scen_keys
        )
        forecast_errors = {k: f.get('error') for k, f in forecast.items()
                           if isinstance(f, dict) and f.get('error')}

        # 2. DCF估值（中性情景）
        dcf = self.dcf_valuation(forecast['neutral'], scenario='neutral')

        # 3. 相对估值
        relative = self.relative_valuation(forecast['neutral'])

        # 4. 目标价推导
        target_prices = []
        blocked = []

        if dcf.get('per_share_value') and not dcf.get('insufficient'):
            target_prices.append(('DCF', dcf['per_share_value']))
        elif dcf.get('error'):
            blocked.append(('DCF', dcf['error']))

        pe_val = relative.get('pe_valuation', {}) if isinstance(relative, dict) else {}
        if pe_val and pe_val.get('per_share') and not relative.get('insufficient'):
            target_prices.append(('PE', pe_val['per_share']))
        elif relative.get('error'):
            blocked.append(('PE', relative['error']))

        if target_prices:
            avg_target = sum(p[1] for p in target_prices) / len(target_prices)
            min_target = min(p[1] for p in target_prices)
            max_target = max(p[1] for p in target_prices)
        else:
            avg_target = min_target = max_target = None

        # 5. 投资评级（简化逻辑）
        # 需要当前股价，这里留空，由调用方填充
        rating = '数据不足，不出评级' if insufficient else '待定价'

        return {
            'forecast': forecast,
            'dcf': dcf,
            'relative': relative,
            'target_price': {
                'methods': target_prices,
                'average': round(avg_target, 2) if avg_target else None,
                'range': [round(min_target, 2), round(max_target, 2)] if min_target else None,
                'insufficient': insufficient,
                'blocked': blocked,
                'forecast_errors': forecast_errors,
            },
            'insufficient': insufficient,
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
            except Exception as _sexc:
                record(__name__, 'fetch_earnings_forecast', _sexc, note='静默降级')
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

    2026-10-16 审计修复（P0）：数据不足时输出 🔴 红灯缺口说明，
    不再输出由编造基准值推导的"综合目标价"。
    """
    lines = []

    # ── 🔴 红灯分支：数据不足，拒绝出结论 ──
    if valuation_data.get('insufficient') or not valuation_data.get('target_price', {}).get('methods'):
        lines.append("### 🔴 盈利预测与估值：数据不足，拒绝输出结论\n")
        lines.append("> **未达输出门槛，本节不出具任何预测值与目标价。**\n")
        fe = valuation_data.get('target_price', {}).get('forecast_errors', {})
        if fe:
            lines.append("**缺口原因（按情景）**：")
            for k, v in fe.items():
                lines.append(f"- {k}：{v}")
            lines.append("")
        blocked = valuation_data.get('target_price', {}).get('blocked', [])
        if blocked:
            lines.append("**被拦截的估值方法**：")
            for name, err in blocked:
                lines.append(f"- {name}法：{err}")
            lines.append("")
        lines.append("**补齐路径**：通过 `dzh-mcp`（getStockCorpProfit/getBalanceSheetMetrics/"
                     "getStockXjllData/getBlockIndustryObj）或 `alphapai-lite-mcp`"
                     "（query_financial_data）补齐财报与同业行情后重跑。")
        lines.append("")
        return "\n".join(lines)

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
