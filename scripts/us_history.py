#!/usr/bin/env python3
"""美股历史数据 - 不依赖yfinance"""
import json
import urllib.request
import urllib.parse
import ssl
from datetime import datetime, timedelta
import time
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# CIK映射
CIK_MAP = {
    'AAPL': '0000320193',
    'MSFT': '0000789019',
    'GOOGL': '0001652044',
    'AMZN': '0001018724',
    'NVDA': '0001045810',
    'TSLA': '0001318601',
    'META': '0001652044',
    'JPM': '0000019617',
    'V': '0001403161',
}

def get_cik(ticker):
    ticker = ticker.upper().strip()
    return CIK_MAP.get(ticker, '')

def fetch_sec_history(ticker):
    """从SEC获取公司历史"""
    cik = get_cik(ticker)
    if not cik:
        return {'error': f'未找到 {ticker} 的CIK'}
    
    # SEC company tickers
    url = f'https://data.sec.gov/submissions/CIK{cik}.json'
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    req.add_header('Accept', 'application/json')
    
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read())
            
            # 提取基本信息
            company = {
                'name': data.get('name', ''),
                'cik': data.get('cik', ''),
                'sic': data.get('sic', ''),
                'category': data.get('category', ''),
                'tickers': data.get('tickers', []),
                'exchanges': data.get('exchanges', []),
            }
            
            # 提取filing历史
            recent = data.get('filings', {}).get('recent', {})
            forms = recent.get('form', [])
            dates = recent.get('filedDate', [])
            
            # 统计10-K和10-Q
            filings_count = {'10-K': 0, '10-Q': 0}
            for f in forms:
                if f == '10-K':
                    filings_count['10-K'] += 1
                elif f == '10-Q':
                    filings_count['10-Q'] += 1
            
            return {
                'ticker': ticker,
                'company': company,
                'filings_count': filings_count,
                'note': '基于SEC EDGAR公开数据'
            }
    except Exception as e:
        return {'error': str(e)}

def fetch_market_cap(ticker):
    """尝试获取市值（从简单数据源）"""
    # 尝试从其他API获取
    try:
        url = f'https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey=demo'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data:
                return data[0]
    except Exception as _sexc:
        record(__name__, 'fetch_market_cap', _sexc, note='静默降级')
        pass
    return {'note': '市值数据需付费API'}

def main():
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else 'AAPL'
    
    print("=== SEC History ===")
    data = fetch_sec_history(ticker)
    print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()