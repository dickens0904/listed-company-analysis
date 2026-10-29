"""港交所公告 - 正确的URL格式"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

headers = {'User-Agent': 'Mozilla/5.0'}

# 港交所公告列表有多种URL格式
test_urls = [
    # 格式1: 按日期目录
    'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0427/',
    
    # 格式2: 主索引页
    'https://www1.hkexnews.hk/listedco/listconews/index.htm',
    'https://www1.hkexnews.hk/listedco/listconews/',
    
    # 格式3: 搜索页
    'https://www.hkexnews.hk/',
    
    # 格式4: 今日公告API
    'https://www1.hkexnews.hk/listedco/listconews/advancedsearch/json/advancesearch.json?category=0&market=SEHK',
]

print('=== 测试港交所URL格式 ===\n')

for url in test_urls:
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        print(f'{url}')
        print(f'  状态: {resp.status_code}, 大小: {len(resp.text)} bytes')
        
        if resp.status_code == 200 and len(resp.text) > 1000:
            # 检查是否有PDF链接
            pdf_count = len(re.findall(r'href="[^"]*\.pdf"', resp.text))
            print(f'  PDF链接: {pdf_count}个')
            
            # 如果是JSON
            if url.endswith('.json'):
                try:
                    data = resp.json()
                    print(f'  JSON键: {list(data.keys())[:5]}')
                except Exception as _sexc:
                    record(__name__, '<module>', _sexc, note='静默降级')
                    pass
        
        print()
    except Exception as e:
        print(f'  错误: {e}\n')

# 测试昨天的日期（可能今天还没发布）
yesterday = datetime.now() - timedelta(days=1)
yest_path = yesterday.strftime('%Y/%m%d')
yest_url = f'https://www1.hkexnews.hk/listedco/listconews/sehk/{yest_path}/'

print(f'测试昨天: {yest_url}')
resp = requests.get(yest_url, headers=headers, timeout=10)
print(f'状态: {resp.status_code}, 大小: {len(resp.text)} bytes')

if resp.status_code == 200:
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # 查找表格
    tables = soup.find_all('table')
    print(f'表格数: {len(tables)}')
    
    # 查找PDF链接
    pdf_links = re.findall(r'href="([^"]*\.pdf)"', resp.text)
    print(f'PDF链接: {len(pdf_links)}个')
    
    if pdf_links:
        print('\n前5个PDF:')
        for link in pdf_links[:5]:
            print(f'  {link}')
