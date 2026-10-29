"""修复版：港交所公告搜索"""
import asyncio
from playwright.async_api import async_playwright
import re
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

async def search_hkex_announcements(stock_code='00700'):
    """搜索港交所公告"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        results = []
        
        try:
            # 方案1：直接访问股票公告页
            # 格式：https://www.hkexnews.hk/listedco/listconews/sehk/2026/0427/
            # 但需要知道日期，先尝试搜索页
            
            print('访问港交所披露易搜索页...')
            await page.goto('https://www.hkexnews.hk/', timeout=30000, wait_until='networkidle')
            await page.wait_for_timeout(5000)
            
            # 截图调试
            await page.screenshot(path='output/hkex_search_page.png')
            print('截图保存: output/hkex_search_page.png')
            
            # 查找所有input
            inputs = await page.query_selector_all('input')
            print(f'找到 {len(inputs)} 个input元素')
            
            for i, inp in enumerate(inputs):
                try:
                    placeholder = await inp.get_attribute('placeholder')
                    inp_type = await inp.get_attribute('type')
                    name = await inp.get_attribute('name')
                    is_visible = await inp.is_visible()
                    print(f'  [{i}] type={inp_type}, placeholder={placeholder}, name={name}, visible={is_visible}')
                except Exception as _sexc:
                    record(__name__, 'search_hkex_announcements', _sexc, note='静默降级')
                    pass
            
            # 尝试等待搜索框出现
            try:
                search_box = await page.wait_for_selector('input[type="text"]:visible', timeout=10000)
                if search_box:
                    print(f'\n找到可见搜索框，输入 {stock_code}')
                    await search_box.fill(stock_code)
                    await page.wait_for_timeout(1000)
                    await search_box.press('Enter')
                    await page.wait_for_timeout(5000)
                    
                    # 提取结果
                    content = await page.content()
                    pdf_links = re.findall(r'href="([^"]*\.pdf)"', content)
                    print(f'找到PDF: {len(pdf_links)}个')
                    
                    for link in pdf_links[:5]:
                        if 'http' not in link:
                            link = f'https://www1.hkexnews.hk{link}'
                        print(f'  - {link}')
                        results.append(link)
            except Exception as e:
                print(f'搜索框等待失败: {e}')
                
                # 方案2：直接访问公告列表页
                print('\n尝试直接访问公告列表...')
                list_url = 'https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0427/'
                await page.goto(list_url, timeout=30000)
                await page.wait_for_timeout(3000)
                
                content = await page.content()
                pdf_links = re.findall(r'href="([^"]*\.pdf)"', content)
                print(f'今日公告PDF: {len(pdf_links)}个')
                
                for link in pdf_links[:10]:
                    if 'http' not in link:
                        link = f'https://www1.hkexnews.hk{link}'
                    print(f'  - {link}')
                    results.append(link)
                    
        except Exception as e:
            print(f'错误: {e}')
        finally:
            await browser.close()
        
        return results

if __name__ == '__main__':
    results = asyncio.run(search_hkex_announcements('00700'))
    print(f'\n共 {len(results)} 个公告')
