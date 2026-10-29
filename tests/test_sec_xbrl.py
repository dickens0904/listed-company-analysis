"""
测试SEC EDGAR的XBRL数据获取（结构化财务数据）
SEC提供了XBRL格式的财务数据，比HTML更容易解析
"""
import requests
import json
import time

headers = {
    'User-Agent': 'Mozilla/5.0 (QCLaw Financial Research contact@qclaw.com)',
    'Accept': 'application/json',
}

print("=" * 60)
print("SEC EDGAR XBRL数据测试")
print("=" * 60)

# 测试苹果的SEC Company API（包含XBRL财务数据）
ticker = "AAPL"
cik = "0000320193"

# 方案1：Company API（包含标准化的财务数据）
print(f"\n[方案1] SEC Company API")
company_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
print(f"URL: {company_url}")

try:
    r = requests.get(company_url, headers=headers, timeout=30)
    print(f"状态码: {r.status_code}")
    
    if r.status_code == 200:
        data = r.json()
        
        # 分析数据结构
        facts = data.get('facts', {})
        us_gaap = facts.get('us-gaap', {})
        
        print(f"\n可用的财务科目: {len(us_gaap)} 个")
        
        # 提取关键科目
        key_items = [
            'RevenueFromContractWithCustomerExcludingAssessedTaxes',  # 营收
            'NetIncomeLoss',  # 净利润
            'Assets',  # 总资产
            'StockholdersEquity',  # 股东权益
            'CashAndCashEquivalentsAtCarryingValue',  # 现金
            'EarningsPerShareBasic',  # 基本EPS
            'WeightedAverageNumberOfSharesOutstandingBasic',  # 流通股数
        ]
        
        financials = {}
        for item in key_items:
            if item in us_gaap:
                item_data = us_gaap[item]
                units = item_data.get('units', {})
                
                # 获取USD单位的数据
                usd_data = units.get('USD', [])
                shares_data = units.get('shares', [])
                
                data_list = usd_data if usd_data else shares_data
                
                if data_list:
                    # 取最新一期数据
                    latest = data_list[-1]
                    val = latest.get('val', 0)
                    end_date = latest.get('end', '')
                    frame = latest.get('frame', '')
                    
                    print(f"[OK] {item}: {val:,.0f} ({end_date})")
                    financials[item] = {
                        'value': val,
                        'date': end_date,
                        'frame': frame
                    }
        
        # 保存结果
        with open('output/test_us/AAPL_xbrl_data.json', 'w') as f:
            json.dump({'financials': financials, 'raw_facts': list(us_gaap.keys())}, f, indent=2)
        print(f"\n[OK] 已保存到 output/test_us/AAPL_xbrl_data.json")
        
    else:
        print(f"请求失败: {r.text[:200]}")
        
except Exception as e:
    print(f"错误: {e}")

# 方案2：直接获取10-K的XBRL文件
print("\n" + "=" * 60)
print("[方案2] 获取10-K XBRL文件")
print("SEC EDGAR的每个filing都有对应的XBRL文件")
print("格式：https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}.xml")

# 演示如何获取XBRL文件列表
print("\n示例：苹果最新10-K的XBRL文件")
print("需要先获取accession number，然后构造XBRL文件URL")
print("文件通常命名为：aapl-20250927.xml 或类似格式")

print("\n" + "=" * 60)
print("总结")
print("=" * 60)
print("""
✅ SEC Company API提供结构化XBRL财务数据
✅ 包含数百个标准化的财务科目
✅ 数据格式清晰，易于解析
✅ 这是获取美股财务数据的最佳方式

对比：
┌─────────────────────────────────────────────┐
│ 方案            │ 难度 │ 质量 │ 推荐      │
├─────────────────────────────────────────────┤
│ HTML正则提取    │ ❌难 │ ⚠️中 │ 不推荐    │
│ XBRL API       │ ✅易 │ ✅高 │ 强烈推荐  │
│ 第三方API      │ ⚠️中 │ ⚠️中 │ 备选      │
└─────────────────────────────────────────────┘
""")
