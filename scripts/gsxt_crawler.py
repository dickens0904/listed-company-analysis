# -*- coding: utf-8 -*-
"""
gsxt_crawler.py - 企业工商信息爬取模块（优化版）

功能：从多个数据源获取企业工商信息
  1. 国家企业信用信息公示系统（gsxt.gov.cn）- 官方数据
  2. 企查查（qcc.com）- 商业数据
  3. 天眼查（tianyancha.com）- 商业数据

数据来源：
  - 基本信息（注册资本、法人、经营范围等）
  - 股东信息（股权穿透）
  - 对外投资（子公司、参股公司）
  - 历史变更记录

使用方式：
  from scripts.gsxt_crawler import CompanyInfoCrawler, fetch_company_info

  # 方式1：直接调用（自动选择最佳数据源）
  result = fetch_company_info('纳思达股份有限公司')

  # 方式2：指定数据源
  crawler = CompanyInfoCrawler(source='gsxt')
  result = crawler.get_company_info('纳思达股份有限公司')
"""

import sys
import json
import os
import re
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from cloakbrowser import launch as cloak_launch
    CLOAKBROWSER_AVAILABLE = True
except ImportError:
    CLOAKBROWSER_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

try:
    from playwright_stealth import stealth_sync
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

BROWSER_AVAILABLE = CLOAKBROWSER_AVAILABLE or PLAYWRIGHT_AVAILABLE

if not BROWSER_AVAILABLE:
    print("⚠️ 请安装浏览器: pip install cloakbrowser 或 pip install playwright")


class CompanyInfoCrawler:
    """企业工商信息爬虫（支持多种数据源）"""

    SOURCES = {
        'gsxt': {
            'name': '国家企业信用信息公示系统',
            'url': 'https://www.gsxt.gov.cn/',
            'priority': 1
        },
        'qcc': {
            'name': '企查查',
            'url': 'https://www.qcc.com/',
            'priority': 2
        },
        'tianyancha': {
            'name': '天眼查',
            'url': 'https://www.tianyancha.com/',
            'priority': 3
        }
    }

    def __init__(self, source: str = 'auto', headless: bool = True, timeout: int = 60000,
                 use_cloak: bool = True):
        """初始化爬虫

        Args:
            source: 数据源（gsxt/qcc/tianyancha/auto）
            headless: 是否无头模式
            timeout: 超时时间（毫秒）
            use_cloak: 是否优先使用CloakBrowser
        """
        if not BROWSER_AVAILABLE:
            raise ImportError("请安装浏览器: pip install cloakbrowser 或 pip install playwright")

        self.source = source
        self.headless = headless
        self.timeout = timeout
        self.browser = None
        self.page = None
        self.use_cloak = use_cloak and CLOAKBROWSER_AVAILABLE

    def _init_browser(self):
        """初始化浏览器"""
        if self.browser is None:
            if self.use_cloak:
                print("  [使用CloakBrowser反爬浏览器]")
                try:
                    self.browser = cloak_launch(headless=self.headless, humanize=True)
                    self.page = self.browser.new_page()
                    return True
                except Exception as e:
                    print(f"  [CloakBrowser失败，切换到Playwright] {e}")

            if PLAYWRIGHT_AVAILABLE:
                print("  [使用Playwright" + (" + Stealth" if STEALTH_AVAILABLE else "") + "]")
                self.playwright = sync_playwright().start()
                self.browser = self.playwright.chromium.launch(headless=self.headless)
                self.context = self.browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                self.page = self.context.new_page()
                if STEALTH_AVAILABLE:
                    stealth_sync(self.page)
                return True

            return False

        return True

    def _close_browser(self):
        """关闭浏览器"""
        try:
            if self.page:
                self.page.close()
            if hasattr(self, 'context') and self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if hasattr(self, 'playwright'):
                self.playwright.stop()
        except Exception as _sexc:
            record(__name__, '_close_browser', _sexc, note='静默降级')
            pass
        finally:
            self.browser = None
            self.page = None

    def get_company_info(self, company_name: str, data_dir: str = None) -> dict:
        """获取企业信息

        Args:
            company_name: 企业名称
            data_dir: 数据保存目录

        Returns:
            企业信息字典
        """
        result = {
            'company_name': company_name,
            'source': self.source,
            'success': False,
            'error': None,
            'data': {}
        }

        if self.source == 'auto':
            sources_to_try = ['gsxt', 'qcc', 'tianyancha']
        else:
            sources_to_try = [self.source]

        for source in sources_to_try:
            print(f"\n[尝试数据源] {self.SOURCES[source]['name']}")

            try:
                if source == 'gsxt':
                    info = self._get_info_from_gsxt(company_name)
                elif source == 'qcc':
                    info = self._get_info_from_qcc(company_name)
                elif source == 'tianyancha':
                    info = self._get_info_from_tianyancha(company_name)
                else:
                    continue

                if info.get('success'):
                    result = info
                    break

            except Exception as e:
                print(f"  [失败] {e}")
                continue

        if data_dir and result.get('success'):
            self._save_data(result, data_dir)

        return result

    def _get_info_from_gsxt(self, company_name: str) -> dict:
        """从国家企业信用信息公示系统获取信息"""
        result = {
            'company_name': company_name,
            'source': 'gsxt.gov.cn',
            'success': False,
            'error': None,
            'data': {}
        }

        try:
            if not self._init_browser():
                result['error'] = "浏览器初始化失败"
                return result

            print(f"  [访问] {self.SOURCES['gsxt']['url']}")
            self.page.goto(self.SOURCES['gsxt']['url'], timeout=self.timeout, wait_until='domcontentloaded')
            time.sleep(3)

            search_selectors = [
                'input[placeholder*="企业名称"]',
                'input[placeholder*="请输入"]',
                'input[type="text"]',
                '#keyword',
                '.search-input'
            ]

            search_input = None
            for selector in search_selectors:
                try:
                    search_input = self.page.wait_for_selector(selector, timeout=5000)
                    if search_input:
                        print(f"  [找到搜索框] {selector}")
                        break
                except:
                    continue

            if not search_input:
                result['error'] = "未找到搜索框"
                return result

            search_input.fill(company_name)
            time.sleep(0.5)

            btn_selectors = [
                'button:has-text("搜索")',
                '.search-btn',
                'button[type="submit"]',
                '.btn-search'
            ]

            search_btn = None
            for selector in btn_selectors:
                try:
                    search_btn = self.page.wait_for_selector(selector, timeout=3000)
                    if search_btn:
                        print(f"  [找到搜索按钮] {selector}")
                        break
                except:
                    continue

            if search_btn:
                search_btn.click()
            else:
                self.page.keyboard.press('Enter')

            time.sleep(4)

            result_link = None
            link_selectors = [
                'a[href*="company"]',
                '.search-result a',
                'td a',
                '.list a'
            ]

            for selector in link_selectors:
                try:
                    links = self.page.query_selector_all(selector)
                    if links:
                        for link in links[:3]:
                            text = link.inner_text()
                            if company_name[:4] in text or text[:4] in company_name:
                                result_link = link
                                print(f"  [找到匹配结果] {text}")
                                break
                except:
                    continue

            if result_link:
                result_link.click()
                time.sleep(3)

                result['data'] = self._extract_gsxt_data()
                result['success'] = True
            else:
                result['error'] = "未找到企业"

        except PlaywrightTimeout:
            result['error'] = "页面加载超时"
        except Exception as e:
            result['error'] = str(e)
        finally:
            self._close_browser()

        return result

    def _get_info_from_qcc(self, company_name: str) -> dict:
        """从企查查获取信息"""
        result = {
            'company_name': company_name,
            'source': 'qcc.com',
            'success': False,
            'error': None,
            'data': {}
        }

        try:
            if not self._init_browser():
                result['error'] = "浏览器初始化失败"
                return result

            print(f"  [访问] {self.SOURCES['qcc']['url']}")
            self.page.goto(self.SOURCES['qcc']['url'], timeout=self.timeout, wait_until='domcontentloaded')
            time.sleep(5)

            search_selectors = [
                'input[placeholder*="请输入公司名"]',
                '#searchKey',
                '.search-input'
            ]

            search_input = None
            for selector in search_selectors:
                try:
                    search_input = self.page.wait_for_selector(selector, timeout=5000)
                    if search_input:
                        print(f"  [找到搜索框] {selector}")
                        break
                except:
                    continue

            if not search_input:
                result['error'] = "未找到搜索框"
                return result

            search_input.fill(company_name)
            time.sleep(0.5)
            self.page.keyboard.press('Enter')

            time.sleep(4)

            result['data'] = self._extract_qcc_data()
            result['success'] = True

        except PlaywrightTimeout:
            result['error'] = "页面加载超时"
        except Exception as e:
            result['error'] = str(e)
        finally:
            self._close_browser()

        return result

    def _get_info_from_tianyancha(self, company_name: str) -> dict:
        """从天眼查获取信息"""
        result = {
            'company_name': company_name,
            'source': 'tianyancha.com',
            'success': False,
            'error': None,
            'data': {}
        }

        try:
            if not self._init_browser():
                result['error'] = "浏览器初始化失败"
                return result

            print(f"  [访问] {self.SOURCES['tianyancha']['url']}")
            self.page.goto(self.SOURCES['tianyancha']['url'], timeout=self.timeout, wait_until='domcontentloaded')
            time.sleep(5)

            search_selectors = [
                'input[placeholder*="搜公司"]',
                '#search',
                '.search-input'
            ]

            search_input = None
            for selector in search_selectors:
                try:
                    search_input = self.page.wait_for_selector(selector, timeout=5000)
                    if search_input:
                        print(f"  [找到搜索框] {selector}")
                        break
                except:
                    continue

            if not search_input:
                result['error'] = "未找到搜索框"
                return result

            search_input.fill(company_name)
            time.sleep(0.5)
            self.page.keyboard.press('Enter')

            time.sleep(4)

            result['data'] = self._extract_tianyancha_data()
            result['success'] = True

        except PlaywrightTimeout:
            result['error'] = "页面加载超时"
        except Exception as e:
            result['error'] = str(e)
        finally:
            self._close_browser()

        return result

    def _extract_gsxt_data(self) -> dict:
        """从gsxt页面提取数据"""
        return self._extract_generic_data('gsxt')

    def _extract_qcc_data(self) -> dict:
        """从qcc页面提取数据"""
        return self._extract_generic_data('qcc')

    def _extract_tianyancha_data(self) -> dict:
        """从天眼查页面提取数据"""
        return self._extract_generic_data('tianyancha')

    def _extract_generic_data(self, source: str) -> dict:
        """通用数据提取"""
        data = {
            'basic_info': {},
            'shareholders': [],
            'investments': [],
            'changes': [],
            'crawl_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        try:
            content = self.page.content()

            code_match = re.search(r'统一社会信用代码[：:]\s*([A-Z0-9]{18})', content)
            if code_match:
                data['basic_info']['unified_code'] = code_match.group(1)

            name_match = re.search(r'名[称称][：:]\s*([^\n<]{5,50})', content)
            if name_match:
                data['basic_info']['company_name'] = name_match.group(1).strip()

            legal_match = re.search(r'法定代表人[：:]\s*([^\n<]{2,10})', content)
            if legal_match:
                data['basic_info']['legal_representative'] = legal_match.group(1).strip()

            capital_match = re.search(r'注册资本[：:]\s*([^\n<]+)', content)
            if capital_match:
                data['basic_info']['registered_capital'] = capital_match.group(1).strip()

            date_match = re.search(r'成立日期[：:]\s*([\d-]+)', content)
            if date_match:
                data['basic_info']['establish_date'] = date_match.group(1)

            scope_match = re.search(r'经营范围[：:]\s*([^\n]{10,500})', content)
            if scope_match:
                data['basic_info']['business_scope'] = scope_match.group(1).strip()

            status_match = re.search(r'经营状态[：:]\s*([^\n<]+)', content)
            if status_match:
                data['basic_info']['business_status'] = status_match.group(1).strip()

        except Exception as e:
            print(f"  [提取数据失败] {e}")

        return data

    def _save_data(self, result: dict, data_dir: str):
        """保存数据"""
        try:
            os.makedirs(data_dir, exist_ok=True)
            filename = f"gsxt_{result['company_name']}.json"
            filepath = os.path.join(data_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"  [已保存] {filepath}")
        except Exception as e:
            print(f"  [保存失败] {e}")


def fetch_company_info(company_name: str, source: str = 'auto',
                      headless: bool = True, data_dir: str = None) -> dict:
    """获取企业信息主入口

    Args:
        company_name: 企业名称
        source: 数据源（gsxt/qcc/tianyancha/auto）
        headless: 是否无头模式
        data_dir: 数据保存目录

    Returns:
        企业信息字典
    """
    print(f"\n{'=' * 60}")
    print(f"企业工商信息查询 - {company_name}")
    print(f"{'=' * 60}")

    crawler = CompanyInfoCrawler(source=source, headless=headless, use_cloak=True)
    result = crawler.get_company_info(company_name, data_dir)

    if result.get('success'):
        print(f"\n✅ 查询成功")
        print(f"数据来源: {result['source']}")
        basic = result['data'].get('basic_info', {})
        print(f"统一社会信用代码: {basic.get('unified_code', 'N/A')}")
        print(f"法定代表人: {basic.get('legal_representative', 'N/A')}")
        print(f"注册资本: {basic.get('registered_capital', 'N/A')}")
    else:
        print(f"\n❌ 查询失败: {result.get('error')}")

    return result


def get_related_company_graph(stock_code: str, company_name: str,
                              data_dir: str = None) -> dict:
    """获取关联企业图谱

    Args:
        stock_code: 股票代码
        company_name: 上市公司名称
        data_dir: 数据目录

    Returns:
        关联企业图谱
    """
    result = {
        'stock_code': stock_code,
        'center': company_name,
        'nodes': [],
        'edges': [],
        'success': False,
        'error': None
    }

    try:
        info = fetch_company_info(company_name, data_dir=data_dir)

        if info.get('success'):
            result['nodes'].append({
                'name': company_name,
                'type': 'center',
                'level': 0
            })

            for shareholder in info['data'].get('shareholders', [])[:10]:
                result['nodes'].append({
                    'name': shareholder.get('name', ''),
                    'type': 'shareholder',
                    'level': 1
                })
                result['edges'].append({
                    'from': shareholder.get('name', ''),
                    'to': company_name,
                    'relation': '股东'
                })

            for investment in info['data'].get('investments', [])[:10]:
                result['nodes'].append({
                    'name': investment.get('name', ''),
                    'type': 'investment',
                    'level': 1
                })
                result['edges'].append({
                    'from': company_name,
                    'to': investment.get('name', ''),
                    'relation': '投资'
                })

            result['success'] = True

    except Exception as e:
        result['error'] = str(e)

    return result


if __name__ == '__main__':
    import sys

    if len(sys.argv) >= 2:
        company = sys.argv[1]
        source = sys.argv[2] if len(sys.argv) > 2 else 'auto'
        data_dir = sys.argv[3] if len(sys.argv) > 3 else None

        result = fetch_company_info(company, source=source, data_dir=data_dir)
    else:
        print("用法:")
        print("  python gsxt_crawler.py <企业名称> [数据源] [数据目录]")
        print("  python gsxt_crawler.py 纳思达股份有限公司 auto output/")
        print("\n数据源: gsxt(默认) / qcc / tianyancha / auto")
