# -*- coding: utf-8 -*-
"""
SEC EDGAR API 集成模块

功能：
- 公司信息查询（CIK、名称、行业）
- 10-K年报下载链接
- 10-Q季报下载链接
- 8-K重大事项公告

API文档：https://www.sec.gov/developer
限制：10 requests/second
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 合规User-Agent（SEC要求）
SEC_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (QCLaw Investment Research contact@qclaw.com)',
    'Accept': 'application/json',
}

# CIK前导零补全
CIK_PAD = 10

# SEC EDGAR基础URL
SEC_SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik}.json'
SEC_FILING_URL = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={filing_type}&dateb=&owner=include&count=40'
SEC_DOC_URL = 'https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}'

# 常见美股ticker到CIK映射（快速查找）
TICKER_CIK_MAP = {
    'AAPL': '0000320193',
    'MSFT': '0000789019',
    'GOOGL': '0001652044',
    'GOOG': '0001652044',
    'AMZN': '0001018724',
    'META': '0001326801',
    'NVDA': '0001045810',
    'TSLA': '0001318605',
    'BRK-A': '0001067983',
    'BRK-B': '0001067983',
    'JPM': '0000019617',
    'JNJ': '0000200406',
    'V': '0001403161',
    'PG': '0000080424',
    'UNH': '0000731766',
    'HD': '0000354950',
    'MA': '0001141391',
    'DIS': '0001744489',
    'BAC': '0000070858',
    'KO': '0000021344',
    'PEP': '0000077476',
    'CSCO': '0001067983',
    'AVGO': '0001730168',
    'COST': '0000909832',
    'TMO': '0000911225',
    'MRK': '0000310158',
    'ABBV': '0001551152',
    'ACN': '0001467373',
    'CRM': '0001108524',
    'NFLX': '0001065280',
    'ADBE': '0000007967',
    'AMD': '0000002488',
    'INTC': '0000050863',
    'NKE': '0000320187',
    'ORCL': '0001341439',
    'PYPL': '0001633917',
    'QCOM': '0000804328',
    'SBUX': '0000829224',
    'TXN': '0000097476',
    'WMT': '0000104169',
    # 中概股
    'BABA': '0001577552',
    'JD': '0001549642',
    'PDD': '0001737806',
    'BIDU': '0001329080',
    'NIO': '0001736531',
    'BILI': '0001740602',
    'FUTU': '0001836133',
    'TME': '0001810806',
    'IQ': '0001747940',
}


class SECEdgarAPI:
    """SEC EDGAR API封装类"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(SEC_HEADERS)
        self.last_request_time = 0
    
    def _rate_limit(self):
        """遵守SEC 10 req/s限制"""
        elapsed = time.time() - self.last_request_time
        if elapsed < 0.1:  # 100ms间隔
            time.sleep(0.1 - elapsed)
        self.last_request_time = time.time()
    
    def _get(self, url: str) -> Optional[Dict]:
        """GET请求封装"""
        self._rate_limit()
        try:
            r = self.session.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 404:
                return None
            else:
                print(f"SEC API错误: {r.status_code}")
                return None
        except Exception as e:
            print(f"请求失败: {e}")
            return None
    
    def resolve_cik(self, ticker: str) -> Optional[str]:
        """将ticker转换为CIK"""
        ticker = ticker.upper().strip()
        
        # 1. 先查快速映射表
        if ticker in TICKER_CIK_MAP:
            return TICKER_CIK_MAP[ticker]
        
        # 2. 用SEC公司搜索API
        url = f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&output=json'
        self._rate_limit()
        try:
            r = self.session.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if 'company' in data and data['company']:
                    # 提取CIK
                    cik = data.get('CIK', '')
                    if cik:
                        return cik.zfill(CIK_PAD)
        except Exception as e:
            print(f"CIK解析失败: {e}")
        
        return None
    
    def get_company_info(self, cik: str) -> Optional[Dict]:
        """获取公司基本信息"""
        if not cik:
            return None
        
        # 补全前导零
        cik = cik.zfill(CIK_PAD)
        url = SEC_SUBMISSIONS_URL.format(cik=cik)
        
        data = self._get(url)
        if not data:
            return None
        
        # 解析关键信息
        result = {
            'cik': cik,
            'name': data.get('name', ''),
            'ticker': data.get('tickers', [''])[0] if data.get('tickers') else '',
            'sic': data.get('sic', ''),
            'sic_description': data.get('sicDescription', ''),
            'fiscal_year_end': data.get('fiscalYearEnd', ''),
            'state': data.get('stateOfIncorporation', ''),
            'ein': data.get('ein', ''),
            'website': data.get('website', ''),
            'phone': data.get('phone', ''),
            'addresses': data.get('addresses', {}),
            'filings': {},  # 最近 filings
        }
        
        # 提取最近的10-K/10-Q
        filings = data.get('filings', {})
        recent = filings.get('recent', {})
        
        if recent:
            forms = recent.get('form', [])
            dates = recent.get('filingDate', [])
            accessions = recent.get('accessionNumber', [])
            docs = recent.get('primaryDocument', [])
            
            for i, form in enumerate(forms[:50]):  # 只看最近50个
                if form in ['10-K', '10-Q', '8-K', '20-F', '6-K']:
                    if form not in result['filings']:
                        result['filings'][form] = []
                    
                    result['filings'][form].append({
                        'filing_date': dates[i] if i < len(dates) else '',
                        'accession': accessions[i].replace('-', '') if i < len(accessions) else '',
                        'primary_doc': docs[i] if i < len(docs) else '',
                    })
        
        return result
    
    def get_filing_url(self, cik: str, filing_type: str = '10-K', index: int = 0) -> Optional[str]:
        """获取指定类型报告的下载URL"""
        info = self.get_company_info(cik)
        if not info or filing_type not in info.get('filings', {}):
            return None
        
        filings = info['filings'].get(filing_type, [])
        if index >= len(filings):
            return None
        
        f = filings[index]
        accession = f.get('accession', '')
        doc = f.get('primary_doc', '')
        
        if not accession or not doc:
            return None
        
        # 构造文档URL
        url = SEC_DOC_URL.format(cik=cik.lstrip('0'), accession=accession, doc=doc)
        return url
    
    def download_10k(self, ticker: str, output_path: str = None) -> Optional[str]:
        """下载最新10-K年报"""
        cik = self.resolve_cik(ticker)
        if not cik:
            print(f"未找到 {ticker} 的CIK")
            return None
        
        url = self.get_filing_url(cik, '10-K', 0)
        if not url:
            print(f"{ticker} 无可用10-K")
            return None
        
        # 下载文件
        self._rate_limit()
        try:
            r = self.session.get(url, timeout=60)
            if r.status_code == 200:
                if output_path:
                    with open(output_path, 'wb') as f:
                        f.write(r.content)
                    return output_path
                else:
                    return url
        except Exception as e:
            print(f"下载失败: {e}")
        
        return None
    
    def download_10q(self, ticker: str, quarter: int = 0, output_path: str = None) -> Optional[str]:
        """下载最新10-Q季报"""
        cik = self.resolve_cik(ticker)
        if not cik:
            return None
        
        url = self.get_filing_url(cik, '10-Q', quarter)
        if not url:
            return None
        
        self._rate_limit()
        try:
            r = self.session.get(url, timeout=60)
            if r.status_code == 200:
                if output_path:
                    with open(output_path, 'wb') as f:
                        f.write(r.content)
                    return output_path
                else:
                    return url
        except Exception as e:
            print(f"下载失败: {e}")
        
        return None


# 便捷函数
_api = None

def get_api() -> SECEdgarAPI:
    global _api
    if _api is None:
        _api = SECEdgarAPI()
    return _api

def get_us_company_info(ticker: str) -> Optional[Dict]:
    """获取美股公司信息"""
    api = get_api()
    cik = api.resolve_cik(ticker)
    if not cik:
        return None
    return api.get_company_info(cik)

def _resolve_cik(ticker: str) -> Optional[str]:
    """ticker → 10 位 CIK（不依赖类内部的 ticker 解析，直接走 SEC 官方映射）"""
    t = str(ticker).strip().upper()
    if not t:
        return None
    if t.isdigit():  # 已是 CIK
        return t.zfill(10)
    try:
        from sec_xbrl_api import TICKER_CIK_MAP
        if t in TICKER_CIK_MAP:
            return str(TICKER_CIK_MAP[t]).zfill(10)
    except Exception:
        pass
    # 兜底：SEC 全量映射表（体积较大，仅未命中内置表时拉一次）
    try:
        j = requests.get('https://www.sec.gov/files/company_tickers.json',
                         headers=SEC_HEADERS, timeout=25).json()
        for _, row in j.items():
            if str(row.get('ticker', '')).upper() == t:
                return str(row.get('cik_str', '')).zfill(10)
    except Exception:
        pass
    return None


def get_us_10k_url(ticker: str) -> Optional[str]:
    """获取美股 10-K（年报）原文链接。

    🔴 2026-10-21 修复：旧实现 `api.get_filing_url(ticker, '10-K', 0)` 把 **ticker**
    传给了只接受 **CIK** 的方法 → `get_company_info('AAPL')` 必失败 → 恒返回 None，
    美股 annual_pdf 一直是空 {}。现改为：ticker → CIK → SEC submissions API →
    拼 Archives 直链（实测 AAPL 命中 2025-10-31 的 aapl-20250927.htm）。
    """
    cik = _resolve_cik(ticker)
    if not cik:
        return None
    try:
        j = requests.get(f'https://data.sec.gov/submissions/CIK{cik}.json',
                         headers=SEC_HEADERS, timeout=30).json()
        rec = (j.get('filings') or {}).get('recent') or {}
        forms = rec.get('form') or []
        for i, form in enumerate(forms):
            if form != '10-K':
                continue
            acc = str(rec['accessionNumber'][i]).replace('-', '')
            doc = rec['primaryDocument'][i]
            return f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}'
    except Exception:
        return None
    return None


def get_us_10k_detail(ticker: str) -> Dict:
    """10-K 元信息：{url, filing_date, accession}（annual_pdf 溯源用）"""
    cik = _resolve_cik(ticker)
    if not cik:
        return {}
    try:
        j = requests.get(f'https://data.sec.gov/submissions/CIK{cik}.json',
                         headers=SEC_HEADERS, timeout=30).json()
        rec = (j.get('filings') or {}).get('recent') or {}
        forms = rec.get('form') or []
        for i, form in enumerate(forms):
            if form != '10-K':
                continue
            acc_raw = str(rec['accessionNumber'][i])
            acc = acc_raw.replace('-', '')
            doc = rec['primaryDocument'][i]
            return {
                'url': f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}',
                'filing_date': rec['filingDate'][i],
                'accession': acc_raw,
                'form': '10-K',
                'cik': cik,
                'company': j.get('name'),
            }
    except Exception:
        return {}
    return {}

def get_us_10q_url(ticker: str) -> Optional[str]:
    """获取美股10-Q下载链接"""
    api = get_api()
    return api.get_filing_url(ticker, '10-Q', 0)


# 测试代码
if __name__ == '__main__':
    print("=" * 70)
    print("SEC EDGAR API 测试")
    print("=" * 70)
    
    # 测试AAPL
    print("\n### 测试 AAPL")
    api = SECEdgarAPI()
    info = api.get_company_info('0000320193')  # Apple CIK
    
    if info:
        print(f"公司名称: {info['name']}")
        print(f"Ticker: {info['ticker']}")
        print(f"SIC: {info['sic']} - {info['sic_description']}")
        print(f"注册州: {info['state']}")
        print(f"\n最近10-K:")
        for f in info['filings'].get('10-K', [])[:3]:
            print(f"  - {f['filing_date']}: {f['primary_doc']}")
        
        print(f"\n最近10-Q:")
        for f in info['filings'].get('10-Q', [])[:3]:
            print(f"  - {f['filing_date']}: {f['primary_doc']}")
    
    # 测试ticker解析
    print("\n### 测试 Ticker 解析")
    for ticker in ['MSFT', 'NVDA', 'BABA', 'JD']:
        cik = api.resolve_cik(ticker)
        print(f"{ticker} -> {cik}")
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
