# -*- coding: utf-8 -*-
"""
financial_pdf_downloader.py - 年报PDF下载器
支持：美股SEC EDGAR、港股港交所、A股巨潮资讯、北交所官网

策略：API优先，PDF fallback
"""
import os
import re
import time
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# ============================================
# SEC EDGAR配置（美股）
# ============================================
SEC_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (QCLaw Financial Research contact@qclaw.com)',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# Ticker到CIK映射
TICKER_CIK_MAP = {
    'AAPL': '0000320193', 'MSFT': '0000789019', 'GOOGL': '0001652044',
    'AMZN': '0001018724', 'META': '0001326801', 'NVDA': '0001045810',
    'TSLA': '0001318605', 'JPM': '0000019617', 'JNJ': '0000200406',
    'V': '0001403161', 'PG': '0000080424', 'HD': '0000354950',
    'MA': '0001141391', 'DIS': '0001744489', 'BAC': '0000070858',
    'KO': '0000021344', 'PEP': '0000077476', 'CSCO': '0001067983',
    'COST': '0000909832', 'TMO': '0000911225', 'MRK': '0000310158',
    'ABBV': '0001551152', 'ACN': '0001467373', 'CRM': '0001108524',
    'NFLX': '0001065280', 'ADBE': '0000007967', 'AMD': '0000002488',
    'INTC': '0000050863', 'NKE': '0000320187', 'ORCL': '0001341439',
    'PYPL': '0001633917', 'QCOM': '0000804328', 'SBUX': '0000829224',
    'TXN': '0000097476', 'WMT': '0000104169',
    # 中概股
    'BABA': '0001577552', 'JD': '0001549642', 'PDD': '0001737806',
    'BIDU': '0001329080', 'NIO': '0001736531', 'BILI': '0001740602',
    'TME': '0001810806', 'IQ': '0001747940', 'FUTU': '0001836133',
}


def download_us_10k_pdf(ticker: str, output_dir: str, years: int = 1) -> Dict:
    """
    从SEC EDGAR下载美股10-K年报PDF
    
    Returns:
        {
            'success': bool,
            'pdf_files': [{'year': '', 'path': '', 'url': ''}],
            'warnings': []
        }
    """
    result = {'success': False, 'pdf_files': [], 'warnings': []}
    os.makedirs(output_dir, exist_ok=True)
    
    # Step 1: 获取CIK
    cik = TICKER_CIK_MAP.get(ticker.upper())
    if not cik:
        # 尝试从SEC获取
        try:
            url = f'https://data.sec.gov/submissions/CIK{ticker}.json'
            r = requests.get(url, headers=SEC_HEADERS, timeout=30)
            if r.status_code == 200:
                data = r.json()
                cik = str(data.get('cik', '')).zfill(10)
        except Exception as _sexc:
            record(__name__, 'download_us_10k_pdf', _sexc, note='静默降级')
            pass
    
    if not cik:
        result['warnings'].append(f'未找到 {ticker} 的CIK')
        return result
    
    cik_padded = cik.zfill(10)
    print(f"[INFO] {ticker} CIK: {cik_padded}")
    
    # Step 2: 获取filing列表
    try:
        url = f'https://data.sec.gov/submissions/CIK{cik_padded}.json'
        r = requests.get(url, headers=SEC_HEADERS, timeout=30)
        if r.status_code != 200:
            result['warnings'].append(f'获取filing列表失败: {r.status_code}')
            return result
        
        data = r.json()
        filings = data.get('filings', {}).get('recent', {})
        forms = filings.get('form', [])
        dates = filings.get('filingDate', [])
        accessions = filings.get('accessionNumber', [])
        primary_docs = filings.get('primaryDocument', [])
        
        # 筛选10-K
        filing_10k = []
        for i, form in enumerate(forms):
            if form == '10-K':
                filing_10k.append({
                    'date': dates[i],
                    'accession': accessions[i],
                    'primary_doc': primary_docs[i]
                })
                if len(filing_10k) >= years:
                    break
        
        if not filing_10k:
            result['warnings'].append('未找到10-K文件')
            return result
        
        print(f"[INFO] 找到 {len(filing_10k)} 个10-K")
        
    except Exception as e:
        result['warnings'].append(f'获取filing列表失败: {e}')
        return result
    
    # Step 3: 下载PDF
    for f in filing_10k:
        try:
            # 构造文档目录URL
            accession_clean = f['accession'].replace('-', '')
            base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_padded}/{accession_clean}"
            index_url = f"{base_url}/{f['primary_doc']}"
            
            # 10-K主文档通常是HTML或TXT
            # 我们需要找到目录中的PDF文件
            
            # 先尝试获取目录索引
            idx_url = f"{base_url}/index.json"
            r = requests.get(idx_url, headers=SEC_HEADERS, timeout=30)
            
            pdf_url = None
            if r.status_code == 200:
                # 尝试从JSON目录获取PDF列表
                try:
                    idx_data = r.json()
                    if 'directory' in idx_data and 'item' in idx_data['directory']:
                        for item in idx_data['directory']['item']:
                            name = item.get('name', '').lower()
                            if name.endswith('.pdf'):
                                # 优先选择包含annual report或form 10-k的PDF
                                if 'annual' in name or '10-k' in name or 'report' in name:
                                    pdf_url = f"{base_url}/{item['name']}"
                                    break
                        # 如果没找到，取第一个PDF
                        if not pdf_url:
                            for item in idx_data['directory']['item']:
                                name = item.get('name', '')
                                if name.lower().endswith('.pdf'):
                                    pdf_url = f"{base_url}/{name}"
                                    break
                except Exception as _sexc:
                    record(__name__, 'download_us_10k_pdf', _sexc, note='静默降级')
                    pass
            
            # 如果JSON目录失败，尝试HTML目录
            if not pdf_url:
                try:
                    idx_html_url = f"{base_url}/"
                    r = requests.get(idx_html_url, headers=SEC_HEADERS, timeout=30)
                    if r.status_code == 200:
                        # 从HTML中提取PDF链接
                        pdf_matches = re.findall(r'href="([^"]+\.pdf)"', r.text)
                        if pdf_matches:
                            # 优先选择包含annual的
                            for pdf in pdf_matches:
                                if 'annual' in pdf.lower() or '10-k' in pdf.lower():
                                    pdf_url = f"{base_url}/{pdf}"
                                    break
                            if not pdf_url:
                                pdf_url = f"{base_url}/{pdf_matches[0]}"
                except Exception as _sexc:
                    record(__name__, 'download_us_10k_pdf', _sexc, note='静默降级')
                    pass
            
            if pdf_url:
                # 下载PDF
                print(f"[INFO] 下载PDF: {pdf_url}")
                r = requests.get(pdf_url, headers=SEC_HEADERS, timeout=120)
                if r.status_code == 200 and r.content[:4] == b'%PDF':
                    year = f['date'][:4]
                    pdf_path = os.path.join(output_dir, f"{ticker}_{year}_10K.pdf")
                    with open(pdf_path, 'wb') as f:
                        f.write(r.content)
                    print(f"[OK] 保存: {pdf_path} ({len(r.content)//1024}KB)")
                    result['pdf_files'].append({
                        'year': year,
                        'path': pdf_path,
                        'url': pdf_url,
                        'size_kb': len(r.content)//1024
                    })
                else:
                    result['warnings'].append(f"下载PDF失败: {pdf_url} (status={r.status_code})")
            else:
                # 下载HTML版本（作为备选）
                print(f"[INFO] 未找到PDF，下载HTML: {index_url}")
                r = requests.get(index_url, headers=SEC_HEADERS, timeout=60)
                if r.status_code == 200:
                    year = f['date'][:4]
                    html_path = os.path.join(output_dir, f"{ticker}_{year}_10K.html")
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(r.text)
                    result['pdf_files'].append({
                        'year': year,
                        'path': html_path,
                        'url': index_url,
                        'format': 'html',
                        'size_kb': len(r.content)//1024
                    })
                    result['warnings'].append(f"未找到PDF，已下载HTML: {html_path}")
            
            time.sleep(0.5)  # 遵守SEC rate limit
            
        except Exception as e:
            result['warnings'].append(f"下载失败: {e}")
    
    if result['pdf_files']:
        result['success'] = True
    
    return result


# ============================================
# 港交所披露易配置（港股）
# ============================================
HKEX_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def download_hk_annual_report_pdf(stock_code: str, output_dir: str, years: int = 1) -> Dict:
    """
    下载港股年报PDF
    
    策略：
    1. 尝试HKEX披露易（需解析页面）
    2. 尝试东方财富港股公告（API）
    3. 尝试公司官网IR页面
    
    Returns:
        {
            'success': bool,
            'pdf_files': [{'year': '', 'path': '', 'url': ''}],
            'warnings': []
        }
    """
    result = {'success': False, 'pdf_files': [], 'warnings': []}
    os.makedirs(output_dir, exist_ok=True)
    
    # 方案1：东方财富港股公告API（更可靠）
    print(f"[INFO] 尝试东方财富港股公告API: {stock_code}")
    try:
        api_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            'sortColumns': 'REPORT_DATE',
            'sortTypes': '-1',
            'pageSize': 50,
            'pageNumber': 1,
            'reportName': 'RPT_HK_ANNOUNCEMENT',  # 尝试不同的报表名
            'columns': 'ALL',
            'quoteColumns': '',
            'source': 'WEB',
            'client': 'WEB',
        }
        
        # 东方财富港股公告有多个可能的API端点
        # 尝试HKEX格式的stock code
        hk_code = stock_code.lstrip('0') if stock_code.startswith('0') else stock_code
        
        # 尝试不同的filter格式
        filter_options = [
            f'(SECURITY_CODE="{stock_code}")',
            f'(SECUCODE="{stock_code}.HK")',
            f'(TICKER="{hk_code}")',
        ]
        
        for filter_str in filter_options:
            try:
                params['filter'] = filter_str
                r = requests.get(api_url, params=params, headers=HKEX_HEADERS, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    if data.get('success') and data.get('result', {}).get('data'):
                        records = data['result']['data']
                        print(f"[OK] 东方财富API返回 {len(records)} 条公告")
                        
                        # 筛选年报
                        for rec in records[:20]:
                            title = rec.get('TITLE', '')
                            if '年报' in title or '年度报告' in title or 'ANNUAL' in title.upper():
                                # 检查是否有附件链接
                                adjunct_url = rec.get('ADJUNCT_URL', '') or rec.get('PDF_URL', '')
                                if adjunct_url:
                                    # 尝试下载
                                    year = str(rec.get('REPORT_DATE', ''))[:4]
                                    pdf_url = adjunct_url if adjunct_url.startswith('http') else f"https://data.eastmoney.com/{adjunct_url}"
                                    
                                    try:
                                        pdf_r = requests.get(pdf_url, headers=HKEX_HEADERS, timeout=60)
                                        if pdf_r.status_code == 200 and pdf_r.content[:4] == b'%PDF':
                                            pdf_path = os.path.join(output_dir, f"{stock_code}_{year}_annual_report.pdf")
                                            with open(pdf_path, 'wb') as f:
                                                f.write(pdf_r.content)
                                            result['pdf_files'].append({
                                                'year': year,
                                                'path': pdf_path,
                                                'url': pdf_url,
                                                'size_kb': len(pdf_r.content)//1024
                                            })
                                            print(f"[OK] 下载成功: {pdf_path}")
                                            time.sleep(1)
                                    except Exception as e:
                                        result['warnings'].append(f"下载失败: {e}")
                        
                        if result['pdf_files']:
                            result['success'] = True
                            return result
                        break
            except:
                continue
                
    except Exception as e:
        result['warnings'].append(f"东方财富API失败: {e}")
    
    # 方案2：直接构造HKEX PDF链接（需要公告编号）
    # 格式: https://www1.hkexnews.hk/listedco/listconews/{stock_code}/{year}/{month}{day}/{}.pdf
    # 这需要知道具体的公告编号和日期，暂不可用
    
    # 方案3：尝试公司IR页面（需要公司名称映射）
    # 留作后备方案
    
    if not result['pdf_files']:
        result['warnings'].append('未能下载港股年报PDF，建议手动从HKEX披露易或公司官网下载')
    
    return result


# ============================================
# A股/北交所：巨潮资讯（已有实现）
# ============================================
def download_cn_annual_report_pdf(stock_code: str, output_dir: str, years: int = 1) -> Dict:
    """
    下载A股/北交所年报PDF（巨潮资讯）
    
    复用已有的CNINFO API逻辑
    """
    from pdf_download import download_cninfo_pdf
    
    result = {'success': False, 'pdf_files': [], 'warnings': []}
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        # 使用已有的PDF下载模块
        pdf_path = download_cninfo_pdf(stock_code, output_dir)
        if pdf_path:
            result['pdf_files'].append({
                'year': datetime.now().strftime('%Y'),
                'path': pdf_path,
                'url': '',
                'size_kb': os.path.getsize(pdf_path)//1024
            })
            result['success'] = True
        else:
            result['warnings'].append('下载失败')
    except Exception as e:
        result['warnings'].append(f'错误: {e}')
    
    return result


# ============================================
# 统一接口
# ============================================
def download_annual_report_pdf(stock_code: str, market: str, output_dir: str, years: int = 1) -> Dict:
    """
    统一年报PDF下载接口
    
    Args:
        stock_code: 股票代码
        market: 'a' / 'hk' / 'us' / 'bse'
        output_dir: 输出目录
        years: 下载最近几年
    
    Returns:
        {
            'success': bool,
            'pdf_files': [...],
            'warnings': [...]
        }
    """
    if market == 'us':
        return download_us_10k_pdf(stock_code, output_dir, years)
    elif market == 'hk':
        return download_hk_annual_report_pdf(stock_code, output_dir, years)
    elif market in ('a', 'bse'):
        return download_cn_annual_report_pdf(stock_code, output_dir, years)
    else:
        return {'success': False, 'pdf_files': [], 'warnings': [f'不支持的市场: {market}']}


# ============================================
# 测试
# ============================================
if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("年报PDF下载器测试")
    print("=" * 60)
    
    # 测试美股
    print("\n[测试1] 美股苹果(AAPL) 10-K年报")
    us_result = download_us_10k_pdf('AAPL', 'output/test_us', years=1)
    print(f"结果: {json.dumps(us_result, indent=2, ensure_ascii=False)}")
    
    # 测试港股
    print("\n[测试2] 港股腾讯(00700) 年报")
    hk_result = download_hk_annual_report_pdf('00700', 'output/test_hk', years=1)
    print(f"结果: {json.dumps(hk_result, indent=2, ensure_ascii=False)}")
    
    # 测试港股阿里巴巴
    print("\n[测试3] 港股阿里巴巴(09988) 年报")
    hk_result2 = download_hk_annual_report_pdf('09988', 'output/test_hk', years=1)
    print(f"结果: {json.dumps(hk_result2, indent=2, ensure_ascii=False)}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
