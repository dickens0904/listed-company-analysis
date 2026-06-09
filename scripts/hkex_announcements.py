"""港交所披露易公告搜索模块 - 基于Playwright浏览器自动化"""
import re
import json
import os
import time
from datetime import datetime


def search_hkex_announcements(stock_code, max_results=20, headless=True):
    """
    搜索港交所披露易公告
    
    Args:
        stock_code: 港股代码（如 '00700'）
        max_results: 最大返回数量（默认20）
        headless: 是否无头模式（默认True）
    
    Returns:
        list[dict]: 公告列表，每条含 title, date, pdf_url, doc_type
    """
    from playwright.sync_api import sync_playwright
    
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        
        try:
            # 1. 加载搜索页
            page.goto('https://www1.hkexnews.hk/search/titlesearch.xhtml', timeout=30000)
            page.wait_for_load_state('networkidle')
            time.sleep(2)
            
            # 2. 接受Cookie
            try:
                page.locator('button:has-text("Accept"), a:has-text("Accept")').first.click(timeout=3000)
                time.sleep(0.5)
            except:
                pass
            
            # 3. 输入股票代码并选择自动补全
            input_elem = page.locator('#searchStockCode')
            input_elem.click()
            time.sleep(0.3)
            for char in stock_code:
                input_elem.type(char, delay=80)
            time.sleep(3)
            
            # 选择自动补全项
            try:
                page.wait_for_selector('.autocomplete-suggestion', timeout=5000)
                items = page.locator('.autocomplete-suggestion').all()
                selected = False
                for item in items:
                    text = item.inner_text().strip()
                    if stock_code in text:
                        item.click()
                        selected = True
                        break
                if not selected and items:
                    items[0].click()
            except:
                pass
            
            time.sleep(1)
            
            # 4. 点击SEARCH按钮
            search_btn = page.locator('.filter__btn-applyFilters-js')
            try:
                search_btn.click(timeout=5000)
            except:
                page.keyboard.press('Enter')
            
            time.sleep(5)
            
            # 5. 提取搜索结果
            raw_results = page.evaluate('''(maxResults) => {
                const rows = document.querySelectorAll('.title-search-result table tbody tr, .table tbody tr');
                const data = [];
                for (let i = 0; i < Math.min(rows.length, maxResults); i++) {
                    const row = rows[i];
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 4) {
                        const releaseTime = cells[0]?.textContent?.trim() || '';
                        const docLink = cells[3]?.querySelector('a');
                        const docTitle = docLink?.textContent?.trim() || '';
                        const docHref = docLink?.href || '';
                        // 获取headline（可能在不同位置）
                        let headline = '';
                        const headlineElem = cells[4] || cells[cells.length - 1];
                        if (headlineElem) {
                            const hlLink = headlineElem.querySelector('a');
                            headline = hlLink?.textContent?.trim() || headlineElem.textContent?.trim() || '';
                        }
                        data.push({
                            releaseTime: releaseTime.replace(/\\n/g, ' ').trim(),
                            title: docTitle.replace(/\\n/g, ' ').trim(),
                            pdf_url: docHref,
                            headline: headline.substring(0, 200),
                        });
                    }
                }
                return data;
            }''', max_results)
            
            # 6. 清理和格式化结果
            for r in raw_results:
                # 解析日期
                date_str = r.get('releaseTime', '')
                # 格式: "Release Time: DD/MM/YYYY HH:MM"
                date_match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', date_str)
                formatted_date = ''
                if date_match:
                    try:
                        dt = datetime.strptime(f"{date_match.group(1)} {date_match.group(2)}", '%d/%m/%Y %H:%M')
                        formatted_date = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        formatted_date = date_str
                
                # 过滤掉非PDF链接（javascript:void(0)）
                pdf_url = r.get('pdf_url', '')
                if pdf_url.startswith('javascript:') or not pdf_url:
                    # 可能是"More"链接，跳过
                    continue
                
                # 判断文档类型
                title = r.get('title', '').upper()
                doc_type = _classify_doc(title)
                
                results.append({
                    'stock_code': stock_code,
                    'title': r.get('title', ''),
                    'date': formatted_date,
                    'pdf_url': pdf_url,
                    'doc_type': doc_type,
                    'headline': r.get('headline', ''),
                })
                
                if len(results) >= max_results:
                    break
            
        finally:
            browser.close()
    
    return results


def _classify_doc(title):
    """根据标题分类公告类型"""
    title = title.upper()
    
    if 'ANNUAL REPORT' in title:
        return '年报'
    elif 'INTERIM REPORT' in title or 'HALF-YEARLY' in title:
        return '中报'
    elif 'QUARTERLY' in title:
        return '季报'
    elif 'ESG' in title or 'ENVIRONMENTAL' in title:
        return 'ESG报告'
    elif 'ANNUAL RESULTS' in title or 'FINAL RESULTS' in title:
        return '业绩公告'
    elif 'INTERIM RESULTS' in title or 'HALF-YEAR RESULTS' in title:
        return '中期业绩'
    elif 'NOTICE' in title and ('MEETING' in title or 'GENERAL' in title):
        return '股东会通知'
    elif 'DISCLOSURE RETURN' in title or 'MOVEMENTS IN SECURITIES' in title:
        return '股权变动'
    elif 'DIVIDEND' in title:
        return '分红公告'
    elif 'CONNECTED TRANSACTION' in title:
        return '关连交易'
    elif 'MAJOR TRANSACTION' in title:
        return '重大交易'
    elif 'GENERAL MANDATE' in title:
        return '一般授权'
    elif 'SHARE BUYBACK' in title or 'REPURCHASE' in title:
        return '回购'
    elif 'BOARD MEETING' in title:
        return '董事会会议'
    elif 'FORM OF PROXY' in title:
        return '代表委任表'
    elif 'GRANT OF' in title:
        return '授出股份'
    elif 'MONTHLY RETURN' in title:
        return '月度报表'
    elif 'PROFIT WARNING' in title or 'PROFIT ALERT' in title:
        return '盈利警告'
    elif 'TAKEOVER' in title or 'OFFER' in title:
        return '收购/要约'
    else:
        return '其他公告'


def download_annual_report(stock_code, save_dir, year=None, headless=True):
    """
    搜索并下载港股年报PDF

    Args:
        stock_code: 港股代码（如 '00700'）
        save_dir: 保存目录
        year: 指定年份（默认最新）
        headless: 是否无头模式

    Returns:
        str: 保存路径，或 None（未找到）
    """
    # 搜索公告
    results = search_hkex_announcements(stock_code, max_results=50, headless=headless)

    # 过滤年报
    annual_reports = [r for r in results if r['doc_type'] == '年报' and r['pdf_url'].startswith('http')]

    if not annual_reports:
        print(f'未找到年报: {stock_code}')
        return None

    # 按年份筛选
    if year:
        annual_reports = [r for r in annual_reports if str(year) in r['title']]

    # 取最新
    target = annual_reports[0]
    # 从标题提取报告年份（如 "ANNUAL REPORT 2025"）
    yr_match = re.search(r'(20\d{2})', target['title'])
    report_year = yr_match.group(1) if yr_match else target['date'][:4]
    filename = f"{stock_code}_annual_report_{report_year}.pdf"
    save_path = os.path.join(save_dir, filename)

    print(f'下载年报: {target["title"]}')
    print(f'URL: {target["pdf_url"]}')
    return download_hkex_pdf(target['pdf_url'], save_path)


def download_hkex_pdf(pdf_url, save_path, timeout=60):
    """下载港交所PDF"""
    import requests
    
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www1.hkexnews.hk/',
    }
    
    r = requests.get(pdf_url, headers=headers, timeout=timeout)
    if r.content[:4] == b'%PDF':
        with open(save_path, 'wb') as f:
            f.write(r.content)
        return save_path
    else:
        raise ValueError(f'下载内容不是PDF，前4字节: {r.content[:4]}')


# 测试
if __name__ == '__main__':
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '00700'
    results = search_hkex_announcements(code, max_results=20)
    print(f'\n共获取 {len(results)} 条公告')
    for i, r in enumerate(results[:10]):
        print(f"\n{i+1}. [{r['doc_type']}] {r['date']}")
        print(f"   {r['title']}")
        print(f"   {r['pdf_url'][:80]}...")


def generate_report_section(data: list) -> list:
    lines = []
    if not data or not isinstance(data, list) or len(data) == 0:
        lines.append("## 港交所公告")
        lines.append("")
        lines.append("未获取到港交所公告数据。")
        lines.append("")
        return lines

    lines.append("## 港交所公告")
    lines.append("")
    lines.append(f"共获取 **{len(data)}** 条港交所公告。")
    lines.append("")

    type_groups = {}
    for ann in data:
        dt = ann.get('doc_type', '其他公告')
        if dt not in type_groups:
            type_groups[dt] = []
        type_groups[dt].append(ann)

    lines.append("### 公告类型分布")
    lines.append("")
    for dtype, anns in sorted(type_groups.items(), key=lambda x: -len(x[1])):
        lines.append(f"- **{dtype}**: {len(anns)}条")
    lines.append("")

    lines.append("### 公告明细")
    lines.append("")
    for i, ann in enumerate(data[:20]):
        title = ann.get('title', '')
        date = ann.get('date', '')
        dtype = ann.get('doc_type', '')
        pdf_url = ann.get('pdf_url', '')

        lines.append(f"{i+1}. **[{dtype}]** {date} — {title}")
        if pdf_url and not pdf_url.startswith('javascript:'):
            lines.append(f"   📎 [PDF]({pdf_url})")
    lines.append("")

    return lines
