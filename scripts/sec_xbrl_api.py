# -*- coding: utf-8 -*-
"""
sec_xbrl_api.py - SEC EDGAR XBRL财务数据API

数据源：SEC Company Facts API
优点：结构化数据，503+标准科目，免费无限制
限制：Rate limit 10 req/s
"""
import os
import json
import time
import requests
from datetime import datetime
from typing import Dict, List, Optional
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

SEC_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (QCLaw Investment Research contact@qclaw.com)',
    'Accept': 'application/json',
}

# Ticker到CIK映射
TICKER_CIK_MAP = {
    'AAPL': '0000320193', 'MSFT': '0000789019', 'GOOGL': '0001652044',
    'GOOG': '0001652044', 'AMZN': '0001018724', 'META': '0001326801',
    'NVDA': '0001045810', 'TSLA': '0001318605', 'JPM': '0000019617',
    'JNJ': '0000200406', 'V': '0001403161', 'PG': '0000080424',
    'HD': '0000354950', 'MA': '0001141391', 'DIS': '0001744489',
    'BAC': '0000070858', 'KO': '0000021344', 'PEP': '0000077476',
    'CSCO': '0001067983', 'COST': '0000909832', 'TMO': '0000911225',
    'MRK': '0000310158', 'ABBV': '0001551152', 'ACN': '0001467373',
    'CRM': '0001108524', 'NFLX': '0001065280', 'ADBE': '0000007967',
    'AMD': '0000002488', 'INTC': '0000050863', 'NKE': '0000320187',
    'ORCL': '0001341439', 'PYPL': '0001633917', 'QCOM': '0000804328',
    'SBUX': '0000829224', 'TXN': '0000097476', 'WMT': '0000104169',
    # 中概股
    'BABA': '0001577552', 'JD': '0001549642', 'PDD': '0001737806',
    'BIDU': '0001329080', 'NIO': '0001736531', 'BILI': '0001740602',
    'TME': '0001810806', 'IQ': '0001747940', 'FUTU': '0001836133',
}

# 关键财务科目映射（2026-10-21 修正：改为**候选列表**，按序命中）
# 🔴 原实现每个科目只写一个 US-GAAP tag，其中 5 个是错的 → 实测 AAPL 13 个科目里
#    没有 revenue（营收），连带毛利率/净利率/资产周转全部算不出。已纠错：
#      revenue        : ...AssessedTaxes → ...AssessedTax（多打了个 es）
#      capex          : CapitalExpenditures 不是 us-gaap 概念 → PaymentsToAcquirePropertyPlantAndEquipment
#      dividends      : DividendsCash 不存在 → PaymentsOfDividends
#      ocf            : CashFlowsFromUsedInOperatingActivities → NetCashProvidedByUsedInOperatingActivities
#      depreciation   : Depreciation → DepreciationDepletionAndAmortization（更常见）
KEY_ITEMS = {
    'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax',
                'RevenueFromContractWithCustomerIncludingAssessedTax',
                'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet'),
    'net_income': ('NetIncomeLoss', 'ProfitLoss'),
    'total_assets': ('Assets',),
    'total_equity': ('StockholdersEquity',
                     'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'),
    'cash': ('CashAndCashEquivalentsAtCarryingValue',
             'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'),
    'eps_basic': ('EarningsPerShareBasic',),
    'shares_outstanding': ('WeightedAverageNumberOfSharesOutstandingBasic',
                           'CommonStockSharesOutstanding'),
    'gross_profit': ('GrossProfit',),
    'operating_income': ('OperatingIncomeLoss',),
    'rd_expense': ('ResearchAndDevelopmentExpense',),
    'sga_expense': ('SellingGeneralAndAdministrativeExpense',),
    'total_debt': ('LongTermDebt', 'LongTermDebtNoncurrent', 'DebtCurrent',
                   'LongTermDebtAndCapitalLeaseObligations'),
    'interest_expense': ('InterestExpense', 'InterestExpenseNonoperating'),
    'depreciation': ('DepreciationDepletionAndAmortization',
                     'DepreciationAmortizationAndAccretionNet', 'Depreciation'),
    'capex': ('PaymentsToAcquirePropertyPlantAndEquipment',
              'PaymentsToAcquireProductiveAssets'),
    'dividends': ('PaymentsOfDividends', 'PaymentsOfDividendsCommonStock'),
    'ocf': ('NetCashProvidedByUsedInOperatingActivities',
            'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'),
}

class SECXBRLAPI:
    """SEC EDGAR XBRL API封装"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(SEC_HEADERS)
        self.last_request_time = 0
        self.cache = {}
    
    def _rate_limit(self):
        """Rate limiting: 10 requests/second"""
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.1:
            time.sleep(0.1 - elapsed)
        self.last_request_time = time.time()
    
    def get_cik(self, ticker: str) -> Optional[str]:
        """获取CIK"""
        ticker = ticker.upper()
        if ticker in TICKER_CIK_MAP:
            return TICKER_CIK_MAP[ticker]
        
        # 尝试从SEC获取
        self._rate_limit()
        try:
            url = f'https://data.sec.gov/submissions/CIK{ticker}.json'
            r = self.session.get(url, timeout=30)
            if r.status_code == 200:
                data = r.json()
                cik = str(data.get('cik', '')).zfill(10)
                TICKER_CIK_MAP[ticker] = cik  # 缓存
                return cik
        except Exception as _sexc:
            record(__name__, 'get_cik', _sexc, note='静默降级')
            pass
        
        return None
    
    def get_company_facts(self, ticker: str) -> Dict:
        """
        获取公司所有XBRL财务数据
        
        Returns:
            {
                'success': bool,
                'company': str,
                'cik': str,
                'financials': {...},
                'warnings': []
            }
        """
        result = {
            'success': False,
            'ticker': ticker,
            'company': '',
            'cik': '',
            'financials': {},
            'warnings': []
        }
        
        # 获取CIK
        cik = self.get_cik(ticker)
        if not cik:
            result['warnings'].append(f'未找到 {ticker} 的CIK')
            return result
        
        result['cik'] = cik
        
        # 获取公司数据
        self._rate_limit()
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code != 200:
                result['warnings'].append(f'API请求失败: {r.status_code}')
                return result
            
            data = r.json()
            result['company'] = data.get('entityName', '')
            
            facts = data.get('facts', {})
            us_gaap = facts.get('us-gaap', {})
            
            print(f"[OK] {result['company']} (CIK: {cik})")
            print(f"  可用科目: {len(us_gaap)} 个")
            
            # 提取关键财务科目（候选 tag 按序命中第一个存在的）
            for key, item_names in KEY_ITEMS.items():
                cands = (item_names,) if isinstance(item_names, str) else tuple(item_names)
                item_name = next((c for c in cands if c in us_gaap), None)
                if item_name:
                    item_data = us_gaap[item_name]
                    units = item_data.get('units', {})
                    
                    # 优先取USD单位
                    usd_data = units.get('USD', [])
                    shares_data = units.get('shares', [])
                    per_share_data = units.get('USD/shares', [])
                    
                    data_list = usd_data or shares_data or per_share_data
                    
                    if data_list:
                        # 按日期排序，保留最近 40 期（2026-10-21：原 5 期不够还原
                        # 年度序列——us_records 要用 CY 年度 frame 拼 5 年年报；下游
                        # get_latest 仍取 values[0]，语义不变）
                        data_list = sorted(data_list, key=lambda x: x.get('end', ''), reverse=True)[:120]
                        
                        values = []
                        for d in data_list:
                            values.append({
                                'date': d.get('end', ''),
                                'value': d.get('val', 0),
                                'frame': d.get('frame', '')
                            })
                        
                        result['financials'][key] = values
                        
                        # 打印最新值
                        latest = values[0]
                        val = latest['value']
                        if key in ['eps_basic']:
                            print(f"  {key}: ${val:.2f} ({latest['date'][:10]})")
                        else:
                            unit = '亿' if abs(val) > 1e9 else '万'
                            scale = 1e8 if abs(val) > 1e9 else 1e4
                            print(f"  {key}: {val/scale:.2f}{unit} ({latest['date'][:10]})")
                else:
                    result['warnings'].append(
                        f"未找到科目: {key}（候选: {', '.join(cands)}）")
            
            if result['financials']:
                result['success'] = True
            
        except Exception as e:
            result['warnings'].append(f'请求失败: {e}')
        
        return result
    
    def calculate_ratios(self, financials: Dict) -> Dict:
        """计算财务比率"""
        ratios = {}
        
        # 获取最新值
        def get_latest(key):
            data = financials.get(key, [])
            return data[0]['value'] if data else 0
        
        revenue = get_latest('revenue')
        net_income = get_latest('net_income')
        assets = get_latest('total_assets')
        equity = get_latest('total_equity')
        gross_profit = get_latest('gross_profit')
        
        # 计算比率
        if revenue > 0:
            ratios['gross_margin'] = gross_profit / revenue * 100
            ratios['net_margin'] = net_income / revenue * 100
        
        if equity > 0:
            ratios['roe'] = net_income / equity * 100
            ratios['roa'] = net_income / assets * 100 if assets > 0 else 0
        
        if assets > 0:
            ratios['asset_turnover'] = revenue / assets
        
        return ratios


# ============================================
# 便捷函数
# ============================================
def fetch_us_financials(ticker: str) -> Dict:
    """获取美股财务数据"""
    api = SECXBRLAPI()
    return api.get_company_facts(ticker)


# ============================================
# 测试
# ============================================
if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("SEC XBRL API测试")
    print("=" * 60)
    
    test_tickers = ['AAPL', 'MSFT', 'BABA']
    
    for ticker in test_tickers:
        print(f"\n{ticker}:")
        result = fetch_us_financials(ticker)
        
        if result['success']:
            print(f"✅ 成功获取 {len(result['financials'])} 个财务科目")
            
            # 计算比率
            api = SECXBRLAPI()
            ratios = api.calculate_ratios(result['financials'])
            if ratios:
                print(f"\n财务比率:")
                for k, v in ratios.items():
                    print(f"  {k}: {v:.2f}%")
        else:
            print(f"❌ 失败: {result.get('warnings', [])}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
