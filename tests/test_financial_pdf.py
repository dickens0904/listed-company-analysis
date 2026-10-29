"""
测试美股和港股财务数据PDF获取
"""
import requests
import json
import re
import os

# ============================================
# 1. 美股SEC EDGAR 10-K PDF测试
# ============================================
print("=" * 60)
print("美股SEC EDGAR 10-K PDF测试")
print("=" * 60)

def get_sec_filing_pdf(ticker, filing_type='10-K', count=1):
    """从SEC EDGAR获取10-K/10-Q PDF链接并下载"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (OpenClaw Financial Analysis bot@example.com)',
        'Accept': 'application/json'
    }
    
    # Step 1: 获取CIK映射
    cik_url = f'https://data.sec.gov/submissions/CIK{ticker}.json'
    try:
        r = requests.get(cik_url, headers=headers, timeout=30)
        if r.status_code != 200:
            # 尝试ticker到CIK映射
            tickers_url = 'https://www.sec.gov/files/company_tickers.json'
            r2 = requests.get(tickers_url, headers=headers, timeout=30)
            if r2.status_code == 200:
                tickers = r2.json()
                for cik, info in tickers.items():
                    if info.get('ticker', '').upper() == ticker.upper():
                        cik_num = info.get('cik_str', '').zfill(10)
                        cik_url = f'https://data.sec.gov/submissions/CIK{cik_num}.json'
                        r = requests.get(cik_url, headers=headers, timeout=30)
                        break
    except Exception as e:
        print(f"Error getting CIK: {e}")
        return None
    
    if r.status_code != 200:
        print(f"Failed to get company info: {r.status_code}")
        return None
    
    company = r.json()
    cik = company.get('cik', '').zfill(10)
    name = company.get('name', '')
    print(f"公司: {name} (CIK: {cik})")
    
    # Step 2: 查找最新10-K
    filings = company.get('filings', {}).get('recent', {})
    forms = filings.get('form', [])
    dates = filings.get('filingDate', [])
    accessions = filings.get('accessionNumber', [])
    docs = filings.get('primaryDocument', [])
    
    filing_list = []
    for i, form in enumerate(forms):
        if form == filing_type:
            filing_list.append({
                'date': dates[i],
                'accession': accessions[i],
                'doc': docs[i]
            })
            if len(filing_list) >= count:
                break
    
    if not filing_list:
        print(f"未找到 {filing_type} 文件")
        return None
    
    result = []
    for f in filing_list:
        # Step 3: 构造PDF URL
        accession_no_dashes = f['accession'].replace('-', '')
        base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}"
        
        # 主文档通常是HTML，PDF在附件中
        # 先获取filing目录
        index_url = f"{base_url}/{f['doc']}"
        
        # PDF链接：通常是公司年报PDF在附件目录
        # 常见格式: {base_url}/xxx.pdf
        filing_info = {
            'ticker': ticker,
            'company': name,
            'cik': cik,
            'form': filing_type,
            'date': f['date'],
            'accession': f['accession'],
            'index_url': index_url,
            'base_url': base_url
        }
        
        # 尝试获取filing目录中的PDF文件
        try:
            index_r = requests.get(index_url, headers=headers, timeout=30)
            if index_r.status_code == 200:
                # 查找PDF链接
                pdf_pattern = r'href="([^"]+\.pdf)"'
                pdfs = re.findall(pdf_pattern, index_r.text)
                if pdfs:
                    filing_info['pdf_urls'] = [f"{base_url}/{pdf}" if not pdf.startswith('http') else pdf for pdf in pdfs[:3]]
        except Exception as e:
            print(f"获取PDF链接失败: {e}")
        
        result.append(filing_info)
        print(f"\n{filing_type} ({f['date']}):")
        print(f"  Index: {index_url}")
        if filing_info.get('pdf_urls'):
            print(f"  PDFs: {len(filing_info['pdf_urls'])} 个")
            for pdf in filing_info['pdf_urls'][:2]:
                print(f"    - {pdf}")
    
    return result

# 测试苹果10-K
print("\n测试苹果(AAPL)10-K:")
aapl_10k = get_sec_filing_pdf('AAPL', '10-K', count=1)

# ============================================
# 2. 港股港交所披露易PDF测试
# ============================================
print("\n" + "=" * 60)
print("港股港交所披露易年报PDF测试")
print("=" * 60)

def get_hkex_announcement_pdf(stock_code, doc_type='年报'):
    """从港交所披露易获取年报PDF"""
    
    # 港交所披露易搜索API
    # 官方搜索页面: https://www.hkexnews.hk/index.htm
    # 后端API可能需要探索
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    
    # 方案1：直接构造PDF链接（需要知道公告编号）
    # 格式: https://www1.hkexnews.hk/tools/securities/annsumarydoc/{公告编号}.pdf
    
    # 方案2：通过搜索页面
    # HKEX newsweb是SPA，需要分析JS
    
    # 方案3：使用东方财富港股公告（已有接口）
    print(f"\n股票代码: {stock_code}")
    print("方案1: 港交所披露易搜索页面")
    search_url = f"https://www1.hkexnews.hk/search/titlesearch?lang=zh-HK&issuerId={stock_code}&titleId=&titleType=A&fromDate=&toDate="
    print(f"  搜索URL: {search_url}")
    
    # 尝试获取搜索页面
    try:
        r = requests.get(search_url, headers=headers, timeout=30)
        print(f"  状态码: {r.status_code}")
        if r.status_code == 200:
            # 分析返回内容
            if 'application/json' in r.headers.get('Content-Type', ''):
                print(f"  JSON响应: {r.text[:500]}")
            else:
                print(f"  HTML响应长度: {len(r.text)} 字符")
                # 查找PDF链接
                pdf_pattern = r'href="([^"]+\.pdf)"'
                pdfs = re.findall(pdf_pattern, r.text)
                if pdfs:
                    print(f"  找到PDF: {len(pdfs)} 个")
                    for pdf in pdfs[:3]:
                        print(f"    - {pdf}")
                else:
                    print("  未直接找到PDF链接（可能需要JS渲染）")
    except Exception as e:
        print(f"  错误: {e}")
    
    # 方案2：东方财富港股公告API（已验证可用）
    print("\n方案2: 东方财富港股公告API")
    em_url = f"https://emweb.eastmoney.com/HK/GG/{stock_code}"
    print(f"  URL: {em_url}")
    
    # 尝试获取公告列表
    api_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        'sortColumns': 'REPORT_DATE',
        'sortTypes': '-1',
        'pageSize': 20,
        'pageNumber': 1,
        'reportName': 'RPT_HK_ANNOUNCEMENT',
        'columns': 'ALL',
        'filter': f'(SECURITY_CODE="{stock_code}")'
    }
    
    try:
        r = requests.get(api_url, params=params, headers=headers, timeout=30)
        print(f"  状态码: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            if data.get('success'):
                result = data.get('result', {})
                records = result.get('data', [])
                print(f"  公告数: {len(records)}")
                
                # 筛选年报
                annual_reports = [r for r in records if '年报' in r.get('TITLE', '')]
                print(f"  年报数: {len(annual_reports)}")
                
                for i, ann in enumerate(annual_reports[:3]):
                    print(f"\n  年报{i+1}:")
                    print(f"    标题: {ann.get('TITLE', '')}")
                    print(f"    日期: {ann.get('REPORT_DATE', '')}")
                    # 东方财富港股公告通常有附件链接
                    adjunct_url = ann.get('ADJUNCT_URL', '')
                    if adjunct_url:
                        print(f"    附件: {adjunct_url}")
            else:
                print(f"  API返回失败: {data.get('message', '')}")
    except Exception as e:
        print(f"  错误: {e}")
    
    return None

# 测试腾讯年报
print("\n测试腾讯(00700)年报:")
get_hkex_announcement_pdf('00700')

print("\n测试阿里巴巴(09988)年报:")
get_hkex_announcement_pdf('09988')

# ============================================
# 3. 总结PDF获取策略
# ============================================
print("\n" + "=" * 60)
print("总结")
print("=" * 60)
print("""
美股PDF策略:
  ✅ SEC EDGAR有纯API，可直接获取10-K链接
  ✅ 10-K通常是HTML格式，但附件目录中有PDF
  ⚠️ 需要解析HTML索引页提取PDF链接

港股PDF策略:
  ⚠️ 港交所披露易是SPA，搜索需要JS渲染
  ✅ 东方财富港股公告API可用（已验证）
  ⚠️ 需要确认ADJUNCT_URL字段是否包含PDF链接
  ✅ 如有公告编号，可直接构造HKEX PDF链接

下一步:
  1. 实现美股10-K PDF下载器（解析SEC附件目录）
  2. 测试港股东方财富公告的PDF下载链接
  3. 实现港股年报PDF下载器
""")
