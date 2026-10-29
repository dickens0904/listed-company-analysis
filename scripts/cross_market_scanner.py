# -*- coding: utf-8 -*-
"""
cross_market_scanner.py - 跨市场关联扫描器

功能：自动发现上市公司在港股/美股的关联上市实体
  1. 从公告全文中提取境外公司名/SPV名/港股代码
  2. 基于子公司列表穿透搜索境外关联实体
  3. 子公司深度穿透（工商信息对外投资搜索）
  4. 主动网络搜索（THSDK证券搜索+东方财富新闻+港交所披露易）
  5. 识别资本运作风格（分拆借壳、私有化回A、A+H双重上市等）

使用方式：
  from scripts.cross_market_scanner import CrossMarketScanner

  scanner = CrossMarketScanner(stock_code, market, data_dir)
  scanner.load_data()
  results = scanner.scan()
"""

import sys
import json
import os
import re
import time
import urllib.parse
from typing import Dict, List, Set
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from scripts.safe_request import safe_get
except ImportError:
    try:
        from safe_request import safe_get
    except ImportError:
        import requests
        def safe_get(url, params=None, headers=None, timeout=15, **kwargs):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=timeout)
                return resp.json() if 'json' in resp.headers.get('content-type', '') else resp.text
            except Exception:
                return None

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://so.eastmoney.com/',
}

EASTMONEY_SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"

CAPITAL_OPERATION_PATTERNS = {
    '分拆借壳': {
        'description': '母公司收购境外壳公司，将子公司资产注入实现独立上市',
        'key_signals': [
            r'收购.*控股权', r'维持.*上市地位', r'注入.*资产',
            r'实现.*资本化', r'分拆.*上市', r'借壳.*上市',
            r'壳公司', r'上市平台',
        ],
        'context_signals': [
            r'港股', r'港交所', r'SEHK', r'HKEX', r'全面要约',
        ],
    },
    '私有化回A': {
        'description': '境外上市公司私有化退市后回归A股',
        'key_signals': [
            r'私有化', r'退市', r'回归A股', r'借壳上市', r'要约收购.*退市',
        ],
        'context_signals': [r'美股', r'港股', r'NYSE', r'NASDAQ'],
    },
    'A+H双重上市': {
        'description': '同一公司同时在A股和港股上市',
        'key_signals': [
            r'H股发行', r'港股上市', r'两地上市', r'双重上市', r'A\+H',
        ],
        'context_signals': [r'港交所', r'联交所'],
    },
    'VIE架构回归': {
        'description': 'VIE架构公司解除协议控制回归境内',
        'key_signals': [r'VIE协议', r'解除VIE', r'回归境内', r'私有化.*回归'],
        'context_signals': [r'美股', r'ADR'],
    },
    '境外收购': {
        'description': '收购境外上市公司股权',
        'key_signals': [
            r'收购.*股权', r'取得.*控股权', r'成为.*控股股东', r'持股比例.*%',
        ],
        'context_signals': [
            r'港股', r'美股', r'港交所', r'HK\d{4,5}', r'\d{4,5}\.HK',
        ],
    },
}


class CrossMarketScanner:
    """跨市场关联扫描器"""

    def __init__(self, stock_code: str, market: str, data_dir: str):
        self.stock_code = stock_code
        self.market = market
        self.data_dir = data_dir
        self.data = {}
        self.results = {}

    def load_data(self):
        print("加载跨市场扫描数据...")
        for key, filename in {
            'results': 'results.json',
            'structure': 'structure.json',
            'annual_report': 'annual_report_sections.json',
            'enhanced_company_info': 'enhanced_company_info.json',
        }.items():
            filepath = os.path.join(self.data_dir, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.data[key] = json.load(f)
                    print(f"  \u2713 加载: {filename}")
                except Exception as e:
                    print(f"  \u2717 加载失败: {filename}, {e}")

        # 如果enhanced_company_info.json不存在，尝试从results.json中获取
        if 'enhanced_company_info' not in self.data and 'results' in self.data:
            eci_from_results = self.data['results'].get('findings', {}).get('enhanced_company_info', {})
            if eci_from_results:
                self.data['enhanced_company_info'] = eci_from_results
                print(f"  \u2713 从results.json中获取enhanced_company_info")

    def scan(self) -> Dict:
        print(f"\n{'='*60}")
        print(f"跨市场关联扫描 - {self.stock_code}")
        print(f"{'='*60}")

        self.results = {
            'stock_code': self.stock_code,
            'market': self.market,
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'company_aliases': [],
            'announcement_entities': [],
            'subsidiary_entities': [],
            'deep_scan_entities': [],
            'eastmoney_news_entities': [],
            'hkex_entities': [],
            'web_search_entities': [],
            'capital_operation_patterns': [],
            'summary': '',
        }

        self._extract_company_aliases()
        self._scan_announcements_for_cross_market()
        self._scan_annual_report_for_cross_market()
        self._scan_subsidiaries_for_cross_market()
        self._deep_scan_subsidiaries()
        self._search_eastmoney_news()
        self._search_hkex_announcements()
        self._active_web_search()
        self._detect_capital_operation_patterns()
        self._generate_summary()
        return self.results

    def _extract_company_aliases(self):
        print("\n提取公司名称别名...")
        aliases = set()

        if 'structure' in self.data:
            profile = self.data['structure'].get('company_profile', {})
            name = profile.get('name', '')
            if name:
                aliases.add(name)

        if 'results' in self.data:
            findings = self.data['results'].get('findings', {})
            if 'structure' in findings:
                struct = findings['structure'].get('structure', {})
                main_name = struct.get('main_listed', {}).get('name', '')
                if main_name:
                    aliases.add(main_name)

        if 'annual_report' in self.data:
            for section_key in ['actual_controller', 'audit']:
                section = self.data['annual_report'].get(section_key, {})
                content = section.get('content', '')
                full_names = re.findall(
                    r'([\u4e00-\u9fa5]{2,20}(?:股份|集团|控股)?有限公司)', content[:500]
                )
                for n in full_names:
                    if len(n) > 4:
                        aliases.add(n)

        short_aliases = set()
        for n in aliases:
            short = re.sub(r'(股份有限公司|有限公司|集团|控股)', '', n)
            if short and len(short) >= 2:
                short_aliases.add(short)
        aliases.update(short_aliases)

        for ann in self._get_all_announcements():
            content = ann.get('extracted_content', {}).get('full_text_preview', '')
            en_names = re.findall(
                r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*'
                r'(?:\s+(?:Inc|Ltd|LLC|Co|Corp|Group|Holdings|International|Technology))\.?)',
                content[:3000]
            )
            for en in en_names:
                if len(en) > 3:
                    aliases.add(en.strip())

        self.results['company_aliases'] = list(aliases)
        print(f"  发现 {len(aliases)} 个公司名称别名")
        for alias in list(aliases)[:10]:
            print(f"    - {alias}")

    def _scan_announcements_for_cross_market(self):
        print("\n扫描公告中的跨市场关联实体...")
        entities = []
        seen = set()

        for ann in self._get_all_announcements():
            title = ann.get('title', '')
            content = ann.get('extracted_content', {}).get('full_text_preview', '')
            full_text = title + ' ' + content

            hk_codes = re.findall(r'(\d{4,5})\.HK', full_text, re.IGNORECASE)
            for code in hk_codes:
                if code not in seen:
                    seen.add(code)
                    entities.append({
                        'type': 'hk_stock', 'code': code + '.HK',
                        'source': 'announcement', 'from_announcement': title,
                        'date': ann.get('date', ''),
                        'context': self._extract_context(full_text, code),
                    })

            us_codes = re.findall(r'(?:NASDAQ|NYSE|AMEX)\s*[:\s]\s*([A-Z]{1,5})', full_text)
            for code in us_codes:
                if code not in seen:
                    seen.add(code)
                    entities.append({
                        'type': 'us_stock', 'code': code, 'exchange': 'US',
                        'source': 'announcement', 'from_announcement': title,
                        'date': ann.get('date', ''),
                    })

            spv_patterns = [
                r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Holdings?|International|Capital|Group)\s+(?:Limited|Inc|Ltd|LLC|Co))',
                r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Limited|Inc|Ltd))',
            ]
            for pattern in spv_patterns:
                matches = re.findall(pattern, full_text[:5000])
                for match in matches:
                    name = match.strip()
                    if name not in seen and len(name) > 5:
                        seen.add(name)
                        entities.append({
                            'type': 'foreign_entity', 'name': name,
                            'source': 'announcement', 'from_announcement': title,
                            'date': ann.get('date', ''),
                        })

            hk_company_keywords = re.findall(
                r'([\u4e00-\u9fa5]{2,10}(?:控股|集团|科技|国际))\s*(?:有限公司|集团)?'
                r'\s*[\(（]\s*(\d{4,5})\.HK\s*[\)）]',
                full_text
            )
            for name, code in hk_company_keywords:
                key = f"{name}_{code}"
                if key not in seen:
                    seen.add(key)
                    entities.append({
                        'type': 'hk_stock', 'name': name, 'code': code + '.HK',
                        'source': 'announcement', 'from_announcement': title,
                        'date': ann.get('date', ''),
                    })

        self.results['announcement_entities'] = entities
        print(f"  从公告中发现 {len(entities)} 个跨市场关联实体")
        for ent in entities[:10]:
            print(f"    - [{ent['type']}] {ent.get('name', '')} {ent.get('code', '')}")

    def _scan_annual_report_for_cross_market(self):
        """从年报章节中提取跨市场关联实体"""
        print("\n扫描年报中的跨市场关联实体...")
        entities = []
        seen = set()

        if 'annual_report' not in self.data:
            print("  年报数据不可用")
            return

        for section_key, section_data in self.data['annual_report'].items():
            if not isinstance(section_data, dict):
                continue
            content = section_data.get('content', '')
            if not content:
                continue

            # 提取港股代码
            hk_codes = re.findall(r'(\d{4,5})\.HK', content, re.IGNORECASE)
            for code in hk_codes:
                if code not in seen:
                    seen.add(code)
                    entities.append({
                        'type': 'hk_stock', 'code': code + '.HK',
                        'source': 'annual_report', 'section': section_key,
                    })

            # 提取境外SPV/壳公司名称
            spv_patterns = [
                r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Holdings?|International|Capital|Group)\s+(?:Limited|Inc|Ltd|LLC|Co))',
                r'([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\s+(?:Limited|Inc|Ltd))',
            ]
            for pattern in spv_patterns:
                matches = re.findall(pattern, content[:10000])
                for match in matches:
                    name = match.strip()
                    if name not in seen and len(name) > 5:
                        seen.add(name)
                        entities.append({
                            'type': 'foreign_entity', 'name': name,
                            'source': 'annual_report', 'section': section_key,
                        })

            # 提取中文公司名+港股代码模式
            hk_company_keywords = re.findall(
                r'([\u4e00-\u9fa5]{2,10}(?:控股|集团|科技|国际))\s*(?:有限公司|集团)?'
                r'\s*[\(（]\s*(\d{4,5})\.HK\s*[\)）]',
                content
            )
            for name, code in hk_company_keywords:
                key = f"{name}_{code}"
                if key not in seen:
                    seen.add(key)
                    entities.append({
                        'type': 'hk_stock', 'name': name, 'code': code + '.HK',
                        'source': 'annual_report', 'section': section_key,
                    })

        # 合并到announcement_entities中
        existing = self.results.get('announcement_entities', [])
        existing.extend(entities)
        self.results['announcement_entities'] = existing
        print(f"  从年报中发现 {len(entities)} 个跨市场关联实体")
        for ent in entities[:10]:
            print(f"    - [{ent['type']}] {ent.get('name', '')} {ent.get('code', '')}")

    def _scan_subsidiaries_for_cross_market(self):
        print("\n扫描子公司跨市场关联...")
        entities = []

        if 'enhanced_company_info' in self.data:
            eci = self.data['enhanced_company_info']
            subsidiaries = eci.get('subsidiaries', {}).get('full_list', [])
            investments = eci.get('investments', {}).get('all_investments', [])

            foreign_indicators = [
                'International', 'Holdings', 'Limited', 'Inc', 'Ltd',
                'Hong Kong', 'Singapore', 'Cayman', 'BVI', '开曼',
                '香港', '美国', '日本', '英国', '德国',
            ]
            for sub in subsidiaries + investments:
                name = sub.get('name', '')
                if not name:
                    continue
                is_foreign = any(ind.lower() in name.lower() for ind in foreign_indicators)
                if is_foreign:
                    entities.append({
                        'type': 'foreign_subsidiary', 'name': name,
                        'source': 'subsidiary_list',
                        'sub_type': sub.get('type', ''),
                        'business': sub.get('business', ''),
                    })

        if 'structure' in self.data:
            structure = self.data['structure']
            if 'main_listed' in structure and 'related' in structure['main_listed']:
                for rel in structure['main_listed']['related']:
                    name = rel.get('name', '')
                    if name and any(ind in name for ind in ['控股', '国际', '集团']):
                        entities.append({
                            'type': 'related_entity', 'name': name,
                            'source': 'structure',
                            'deal_type': rel.get('deal_type', ''),
                            'detail': rel.get('detail', ''),
                            'date': rel.get('date', ''),
                        })

        self.results['subsidiary_entities'] = entities
        print(f"  发现 {len(entities)} 个子公司关联实体")
        for ent in entities[:10]:
            print(f"    - [{ent['type']}] {ent.get('name', '')}")

    def _deep_scan_subsidiaries(self):
        """子公司深度穿透：搜索每个重要子公司的工商对外投资"""
        print("\n子公司深度穿透（工商信息搜索）...")
        deep_entities = []

        # 收集需要深度搜索的子公司名称
        target_names = []
        if 'enhanced_company_info' in self.data:
            eci = self.data['enhanced_company_info']
            subsidiaries = eci.get('subsidiaries', {}).get('full_list', [])
            for sub in subsidiaries:
                name = sub.get('name', '')
                if name and len(name) >= 3:
                    target_names.append(name)

        # 从structure数据中补充
        if 'structure' in self.data:
            structure = self.data['structure']
            if 'main_listed' in structure and 'related' in structure['main_listed']:
                for rel in structure['main_listed']['related']:
                    name = rel.get('name', '')
                    if name and len(name) >= 3 and name not in target_names:
                        target_names.append(name)

        if not target_names:
            print("  未找到需要深度搜索的子公司")
            self.results['deep_scan_entities'] = deep_entities
            return

        # 尝试导入gsxt_crawler
        try:
            from scripts.gsxt_crawler import GsxtCrawler
        except ImportError:
            print("  gsxt_crawler不可用，跳过深度穿透")
            self.results['deep_scan_entities'] = deep_entities
            return

        # 对前5个重要子公司进行工商信息搜索
        searched = 0
        max_search = 5
        seen_companies = set()

        for name in target_names[:max_search * 2]:  # 多取一些，遇到失败继续
            if searched >= max_search:
                break

            # 跳过太短或太通用的名称
            if len(name) < 3 or name in ('公司', '有限公司', '股份有限公司'):
                continue

            print(f"  搜索工商信息: {name}")
            try:
                crawler = GsxtCrawler(source='auto', headless=True, use_cloak=False)
                result = crawler.get_company_info(name, quick=True)
                if not result.get('success'):
                    print(f"    未找到工商信息")
                    continue

                info = result.get('company_info', {})
                investments = info.get('investments', [])

                for inv in investments:
                    inv_name = inv.get('name', '')
                    if not inv_name or inv_name in seen_companies:
                        continue
                    seen_companies.add(inv_name)

                    is_foreign = any(
                        ind.lower() in inv_name.lower()
                        for ind in ['International', 'Holdings', 'Limited', 'Inc',
                                    'Ltd', 'Hong Kong', 'Singapore', 'Cayman', 'BVI',
                                    '开曼', '香港', '美国', '日本', '英国', '德国']
                    )

                    entity = {
                        'type': 'deep_scan_investment' if not is_foreign else 'deep_scan_foreign',
                        'name': inv_name,
                        'parent_company': name,
                        'source': 'gsxt_deep_scan',
                        'registered_capital': inv.get('registered_capital', ''),
                    }
                    deep_entities.append(entity)
                    if is_foreign:
                        print(f"    发现境外投资: {inv_name}")

                searched += 1
                time.sleep(1)  # 避免请求过快

            except Exception as e:
                print(f"    搜索失败: {e}")
                continue

        self.results['deep_scan_entities'] = deep_entities
        print(f"  深度穿透发现 {len(deep_entities)} 个投资实体")

    def _active_web_search(self):
        """主动网络搜索：使用THSDK搜索跨市场关联证券"""
        print("\n主动网络搜索（THSDK证券搜索）...")
        web_entities = []
        seen = set()

        # 收集搜索关键词
        search_keywords = set()
        for alias in self.results.get('company_aliases', []):
            if len(alias) >= 2:
                search_keywords.add(alias)

        # 从子公司中提取关键词
        if 'enhanced_company_info' in self.data:
            eci = self.data['enhanced_company_info']
            for sub in eci.get('subsidiaries', {}).get('full_list', []):
                name = sub.get('name', '')
                if name and len(name) >= 2:
                    short = re.sub(r'(股份有限公司|有限公司|集团|控股)', '', name)
                    if short and len(short) >= 2:
                        search_keywords.add(short)

        # ========== 新增：从公告发现的境外实体名称提取搜索关键词 ==========
        # 关键改进：这些英文名称（如 Geehy International Limited）可能是港股/美股上市公司
        ann_entities = self.results.get('announcement_entities', [])
        for ent in ann_entities:
            name = ent.get('name', '')
            if not name:
                continue
            # 检查是否是英文名称（含有大写字母和常见后缀）
            is_english_name = (
                re.search(r'[A-Z]', name) and 
                any(suffix in name for suffix in ['Limited', 'Ltd', 'Inc', 'Holdings', 'International', 'Group', 'Technology', 'Co.', 'Corp'])
            )
            if is_english_name and len(name) >= 5:
                search_keywords.add(name)
                # 同时添加不带后缀的简称
                short = re.sub(r'( Limited| Ltd| Inc| Holdings| International| Group| Technology| Co\.| Corp| BVI| HK)?$', '', name, flags=re.IGNORECASE)
                if short and len(short) >= 3:
                    search_keywords.add(short)
        
        # ========== 新增：从年报发现的境外实体名称提取搜索关键词 ==========
        # 关键：Geehy International Limited 是在年报扫描中发现的
        annual_entities = self.results.get('annual_entities', [])
        for ent in annual_entities:
            name = ent.get('name', '')
            if not name:
                continue
            is_english_name = (
                re.search(r'[A-Z]', name) and 
                any(suffix in name for suffix in ['Limited', 'Ltd', 'Inc', 'Holdings', 'International', 'Group', 'Technology', 'Co.', 'Corp'])
            )
            if is_english_name and len(name) >= 5:
                search_keywords.add(name)
                short = re.sub(r'( Limited| Ltd| Inc| Holdings| International| Group| Technology| Co\.| Corp| BVI| HK)?$', '', name, flags=re.IGNORECASE)
                if short and len(short) >= 3:
                    search_keywords.add(short)
        
        # 从子公司关联实体中提取英文名称
        for ent in self.results.get('subsidiary_entities', []):
            name = ent.get('name', '')
            if name and re.search(r'[A-Z]', name) and len(name) >= 5:
                search_keywords.add(name)

        print(f"  收集到 {len(search_keywords)} 个搜索关键词")
        for kw in list(search_keywords)[:5]:
            print(f"    - {kw}")

        if not search_keywords:
            print("  无有效搜索关键词")
            self.results['web_search_entities'] = web_entities
            return

        # 尝试导入THSDK搜索
        thsdk_search = None
        try:
            from scripts.thsdk_search import search
            thsdk_search = search
        except ImportError:
            print("  THSDK搜索不可用")

        if thsdk_search:
            # 搜索前10个关键词
            for keyword in list(search_keywords)[:10]:
                if len(keyword) < 2:
                    continue

                print(f"  THSDK搜索: {keyword}")
                try:
                    search_results = thsdk_search(keyword)
                    if not search_results:
                        continue

                    for item in search_results:
                        item_market = item.get('market', '')
                        item_code = item.get('code', '')
                        item_name = item.get('name', '')

                        # 只关注港股和美股结果
                        if item_market not in ('HK', 'US'):
                            continue

                        key = f"{item_market}_{item_code}"
                        if key in seen:
                            continue
                        seen.add(key)

                        # 排除与当前股票相同的结果
                        if item_code == self.stock_code:
                            continue

                        entity = {
                            'type': 'hk_stock' if item_market == 'HK' else 'us_stock',
                            'code': item_code,
                            'name': item_name,
                            'market': item_market,
                            'source': 'thsdk_search',
                            'search_keyword': keyword,
                        }
                        web_entities.append(entity)
                        print(f"    发现 {item_market} 关联: {item_code} {item_name}")

                    time.sleep(0.5)

                except Exception as e:
                    print(f"    搜索失败: {e}")
                    continue

        self.results['web_search_entities'] = web_entities
        print(f"  网络搜索发现 {len(web_entities)} 个跨市场关联")

    def _search_eastmoney_news(self):
        """东方财富新闻搜索：搜索公司相关的跨市场新闻"""
        print("\n东方财富新闻搜索...")
        news_entities = []
        seen = set()

        # 收集搜索关键词
        search_keywords = set()
        for alias in self.results.get('company_aliases', []):
            if len(alias) >= 2:
                search_keywords.add(alias)

        # 添加跨市场相关关键词组合（扩展版）
        cross_market_keywords = []
        for alias in list(search_keywords)[:5]:  # 增加到5个
            cross_market_keywords.extend([
                f'{alias} 港股',
                f'{alias} 借壳',
                f'{alias} 收购',
                f'{alias} 上市',
                f'{alias} 分拆',
                f'{alias} 私有化',
                f'{alias} HK',
            ])
        
        all_keywords = list(search_keywords)[:5] + cross_market_keywords[:15]

        for keyword in all_keywords:
            if len(keyword) < 2:
                continue

            print(f"  东方财富搜索: {keyword}")
            try:
                import json as json_lib
                param_json = json_lib.dumps({
                    "uid": "",
                    "keyword": keyword,
                    "type": ["cmsArticleWebOld"],
                    "client": "web",
                    "clientType": "web",
                    "clientVersion": "curr",
                    "param": {
                        "cmsArticleWebOld": {
                            "searchScope": "default",
                            "sort": "default",
                            "pageIndex": 1,
                            "pageSize": 10
                        }
                    }
                })
                params = {'cb': '', 'param': param_json}
                data = safe_get(EASTMONEY_SEARCH_URL, params=params, headers=HEADERS, timeout=15)

                # 处理JSONP格式
                if isinstance(data, str):
                    # 去掉JSONP包装
                    data = re.sub(r'^[^(]*\(', '', data)
                    data = re.sub(r'\);?\s*$', '', data)
                    try:
                        data = json.loads(data)
                    except Exception:
                        print(f"    JSON解析失败")
                        continue

                if not data or not isinstance(data, dict):
                    print(f"    无返回数据")
                    continue

                # 提取文章结果
                articles = data.get('result', {}).get('cmsArticleWebOld', [])
                if not articles:
                    articles = data.get('result', {}).get('cmsArticle', [])

                for article in articles:
                    title = article.get('title', '')
                    content = article.get('content', '') or article.get('summary', '')
                    full_text = title + ' ' + content

                    # 检查是否包含跨市场关键词
                    cross_market_signals = [
                        r'港股', r'港交所', r'HK\d{4,5}', r'\d{4,5}\.HK',
                        r'美股', r'NYSE', r'NASDAQ',
                        r'借壳', r'分拆上市', r'私有化',
                        r'收购.*控股权', r'全面要约',
                        r'壳公司', r'上市平台',
                    ]

                    for signal in cross_market_signals:
                        matches = re.findall(signal, full_text, re.IGNORECASE)
                        if matches:
                            key = f"em_{title[:30]}"
                            if key not in seen:
                                seen.add(key)
                                news_entities.append({
                                    'type': 'eastmoney_news',
                                    'title': title,
                                    'date': article.get('date', '')[:10],
                                    'summary': content[:200],
                                    'keyword': keyword,
                                    'matched_signal': signal,
                                })
                                print(f"    发现: {title[:50]}")
                            break

                time.sleep(0.5)

            except Exception as e:
                print(f"    搜索失败: {e}")
                continue

        self.results['eastmoney_news_entities'] = news_entities
        print(f"  东方财富新闻发现 {len(news_entities)} 条跨市场相关新闻")

    def _search_hkex_announcements(self):
        """港交所披露易搜索：搜索关联公司的港股公告"""
        print("\n港交所披露易搜索...")
        hkex_entities = []

        # 收集需要搜索的港股代码（从已发现的实体中提取）
        hk_codes = set()
        for ent in self.results.get('announcement_entities', []):
            if ent.get('type') == 'hk_stock':
                code = ent.get('code', '').replace('.HK', '')
                if code:
                    hk_codes.add(code)

        # 从子公司名称中搜索可能的港股代码
        if 'enhanced_company_info' in self.data:
            eci = self.data['enhanced_company_info']
            for sub in eci.get('subsidiaries', {}).get('full_list', []):
                name = sub.get('name', '')
                if name and any(ind in name for ind in ['Holdings', 'International', 'Limited']):
                    # 尝试从名称中提取可能的港股代码
                    pass

        if not hk_codes:
            print("  未发现港股代码，跳过港交所搜索")
            self.results['hkex_entities'] = hkex_entities
            return

        # 尝试导入港交所搜索模块
        try:
            from scripts.hkex_announcements import search_hkex_announcements
        except ImportError:
            print("  港交所搜索模块不可用")
            self.results['hkex_entities'] = hkex_entities
            return

        # 搜索每个港股代码的公告
        for code in list(hk_codes)[:3]:  # 限制搜索数量
            print(f"  港交所搜索: {code}")
            try:
                announcements = search_hkex_announcements(code, max_results=10, headless=True)
                for ann in announcements:
                    title = ann.get('title', '')
                    if title:
                        hkex_entities.append({
                            'type': 'hkex_announcement',
                            'code': code + '.HK',
                            'title': title,
                            'date': ann.get('date', ''),
                            'pdf_url': ann.get('pdf_url', ''),
                            'doc_type': ann.get('doc_type', ''),
                        })
                        print(f"    发现: {title[:50]}")
                time.sleep(1)
            except Exception as e:
                print(f"    搜索失败: {e}")
                continue

        self.results['hkex_entities'] = hkex_entities
        print(f"  港交所发现 {len(hkex_entities)} 条公告")

    def _detect_capital_operation_patterns(self):
        print("\n检测资本运作风格...")
        detected = []
        all_text = self._collect_all_text()

        for pattern_name, pattern_def in CAPITAL_OPERATION_PATTERNS.items():
            score = 0
            matched = []
            for signal in pattern_def['key_signals']:
                if re.findall(signal, all_text, re.IGNORECASE):
                    score += len(re.findall(signal, all_text, re.IGNORECASE)) * 2
                    matched.append(signal)
            for signal in pattern_def['context_signals']:
                if re.findall(signal, all_text, re.IGNORECASE):
                    score += len(re.findall(signal, all_text, re.IGNORECASE))
                    matched.append(signal)
            if score >= 3:
                detected.append({
                    'pattern': pattern_name,
                    'description': pattern_def['description'],
                    'confidence': min(score / 10.0, 1.0),
                    'score': score,
                    'matched_signals': matched[:5],
                })

        detected.sort(key=lambda x: x['score'], reverse=True)
        self.results['capital_operation_patterns'] = detected
        print(f"  检测到 {len(detected)} 种资本运作风格")
        for pat in detected:
            print(f"    - {pat['pattern']}: 置信度 {pat['confidence']:.0%}")

    def _generate_summary(self):
        parts = []
        entities = self.results.get('announcement_entities', [])
        subs = self.results.get('subsidiary_entities', [])
        deep = self.results.get('deep_scan_entities', [])
        em_news = self.results.get('eastmoney_news_entities', [])
        hkex = self.results.get('hkex_entities', [])
        web = self.results.get('web_search_entities', [])
        patterns = self.results.get('capital_operation_patterns', [])

        if entities:
            hk = sum(1 for e in entities if e.get('type') == 'hk_stock')
            us = sum(1 for e in entities if e.get('type') == 'us_stock')
            fe = sum(1 for e in entities if e.get('type') == 'foreign_entity')
            if hk:
                parts.append(f"公告/年报中发现 {hk} 个港股关联实体")
            if us:
                parts.append(f"公告/年报中发现 {us} 个美股关联实体")
            if fe:
                parts.append(f"公告/年报中发现 {fe} 个境外实体")

        if subs:
            fs = sum(1 for s in subs if s.get('type') in ('foreign_subsidiary', 'foreign_entity'))
            if fs:
                parts.append(f"子公司中有 {fs} 家境外实体")

        if deep:
            foreign_deep = sum(1 for d in deep if d.get('type') == 'deep_scan_foreign')
            if foreign_deep:
                parts.append(f"深度穿透发现 {foreign_deep} 家境外投资实体")

        if em_news:
            parts.append(f"东方财富新闻发现 {len(em_news)} 条跨市场相关新闻")

        if hkex:
            parts.append(f"港交所披露易发现 {len(hkex)} 条港股公告")

        if web:
            hk_web = sum(1 for w in web if w.get('type') == 'hk_stock')
            us_web = sum(1 for w in web if w.get('type') == 'us_stock')
            if hk_web:
                parts.append(f"网络搜索发现 {hk_web} 个港股关联证券")
            if us_web:
                parts.append(f"网络搜索发现 {us_web} 个美股关联证券")

        if patterns:
            top = patterns[0]
            parts.append(f"检测到资本运作模式: {top['pattern']}（置信度 {top['confidence']:.0%}）")

        if not parts:
            parts.append("未发现跨市场关联")

        self.results['summary'] = '；'.join(parts)
        print(f"\n扫描摘要: {self.results['summary']}")

    def _get_all_announcements(self) -> List[Dict]:
        announcements = []
        if 'results' in self.data and 'findings' in self.data['results']:
            ann_data = self.data['results']['findings'].get('announcements', {})
            announcements.extend(ann_data.get('critical_announcements', []))
            announcements.extend(ann_data.get('major_announcements', []))
            # 也扫描routine公告，但限制数量避免过慢
            routine = ann_data.get('routine_announcements', [])
            announcements.extend(routine[:100])
        return announcements

    def _collect_all_text(self) -> str:
        texts = []
        for ann in self._get_all_announcements():
            title = ann.get('title', '')
            content = ann.get('extracted_content', {}).get('full_text_preview', '')
            texts.append(title + ' ' + content[:2000])
        if 'annual_report' in self.data:
            for section in self.data['annual_report'].values():
                if isinstance(section, dict):
                    texts.append(section.get('content', '')[:1000])
        if 'structure' in self.data:
            texts.append(json.dumps(self.data['structure'], ensure_ascii=False)[:2000])
        return ' '.join(texts)

    def _extract_context(self, text: str, keyword: str, window: int = 100) -> str:
        idx = text.find(keyword)
        if idx == -1:
            return ''
        start = max(0, idx - window)
        end = min(len(text), idx + len(keyword) + window)
        return text[start:end].strip()


def scan_cross_market(stock_code: str, market: str, data_dir: str) -> Dict:
    scanner = CrossMarketScanner(stock_code, market, data_dir)
    scanner.load_data()
    return scanner.scan()


def generate_report_section(data: Dict) -> List[str]:
    """生成跨市场关联扫描的报告章节"""
    lines = []
    lines.append("## 跨市场关联扫描")
    lines.append("")

    if not data:
        lines.append("*跨市场关联扫描数据未获取*")
        lines.append("")
        return lines

    summary = data.get('summary', '')
    if summary:
        lines.append(f"**扫描摘要**: {summary}")
        lines.append("")

    # 公告中发现的跨市场实体
    ann_entities = data.get('announcement_entities', [])
    if ann_entities:
        lines.append("### 公告中的跨市场关联")
        lines.append("")

        hk_entities = [e for e in ann_entities if e.get('type') == 'hk_stock']
        us_entities = [e for e in ann_entities if e.get('type') == 'us_stock']
        foreign_entities = [e for e in ann_entities if e.get('type') == 'foreign_entity']

        if hk_entities:
            lines.append(f"**港股关联实体** ({len(hk_entities)}个):")
            lines.append("")
            lines.append("| 代码 | 名称 | 来源公告 | 日期 |")
            lines.append("|------|------|----------|------|")
            for ent in hk_entities:
                code = ent.get('code', '')
                name = ent.get('name', '')
                source = ent.get('from_announcement', '')
                date = ent.get('date', '')
                lines.append(f"| {code} | {name} | {source} | {date} |")
            lines.append("")

        if us_entities:
            lines.append(f"**美股关联实体** ({len(us_entities)}个):")
            lines.append("")
            for ent in us_entities:
                lines.append(f"- **{ent.get('code', '')}** ({ent.get('exchange', '')}) - 来源: {ent.get('from_announcement', '')}")
            lines.append("")

        if foreign_entities:
            lines.append(f"**境外实体/SPV** ({len(foreign_entities)}个):")
            lines.append("")
            for ent in foreign_entities:
                lines.append(f"- **{ent.get('name', '')}** - 来源: {ent.get('from_announcement', '')}")
            lines.append("")

    # 子公司中的境外实体
    sub_entities = data.get('subsidiary_entities', [])
    if sub_entities:
        lines.append("### 子公司关联的境外实体")
        lines.append("")
        foreign_subs = [e for e in sub_entities if e.get('type') == 'foreign_subsidiary']
        related_entities = [e for e in sub_entities if e.get('type') == 'related_entity']

        if foreign_subs:
            lines.append(f"**境外子公司** ({len(foreign_subs)}家):")
            lines.append("")
            for sub in foreign_subs:
                lines.append(f"- **{sub.get('name', '')}** ({sub.get('sub_type', '')}) - {sub.get('business', '')[:50]}")
            lines.append("")

        if related_entities:
            lines.append(f"**关联实体** ({len(related_entities)}家):")
            lines.append("")
            for rel in related_entities:
                lines.append(f"- **{rel.get('name', '')}** - {rel.get('deal_type', '')} ({rel.get('date', '')})")
            lines.append("")

    # 资本运作风格检测
    patterns = data.get('capital_operation_patterns', [])
    if patterns:
        lines.append("### 资本运作风格检测")
        lines.append("")
        for pat in patterns:
            confidence = pat.get('confidence', 0)
            emoji = "🔴" if confidence > 0.7 else ("🟡" if confidence > 0.4 else "🟢")
            lines.append(f"{emoji} **{pat.get('pattern', '')}** (置信度: {confidence:.0%})")
            lines.append(f"   - {pat.get('description', '')}")
            lines.append(f"   - 匹配信号: {', '.join(pat.get('matched_signals', [])[:3])}")
            lines.append("")

    # 深度穿透结果
    deep_entities = data.get('deep_scan_entities', [])
    if deep_entities:
        lines.append("### 子公司深度穿透（工商对外投资）")
        lines.append("")
        foreign_deep = [e for e in deep_entities if e.get('type') == 'deep_scan_foreign']
        domestic_deep = [e for e in deep_entities if e.get('type') == 'deep_scan_investment']

        if foreign_deep:
            lines.append(f"**境外投资实体** ({len(foreign_deep)}家):")
            lines.append("")
            for ent in foreign_deep:
                lines.append(f"- **{ent.get('name', '')}** (母公司: {ent.get('parent_company', '')})")
            lines.append("")

        if domestic_deep:
            lines.append(f"**境内投资实体** ({len(domestic_deep)}家):")
            lines.append("")
            for ent in domestic_deep[:10]:
                lines.append(f"- {ent.get('name', '')} (母公司: {ent.get('parent_company', '')})")
            lines.append("")

    # 网络搜索结果
    web_entities = data.get('web_search_entities', [])
    if web_entities:
        lines.append("### 网络搜索发现的跨市场关联")
        lines.append("")
        lines.append("| 市场 | 代码 | 名称 | 搜索关键词 |")
        lines.append("|------|------|------|------------|")
        for ent in web_entities[:15]:
            market = ent.get('market', '')
            code = ent.get('code', '')
            name = ent.get('name', '')
            keyword = ent.get('search_keyword', '')
            lines.append(f"| {market} | {code} | {name} | {keyword} |")
        lines.append("")

    # 东方财富新闻搜索结果
    em_news = data.get('eastmoney_news_entities', [])
    if em_news:
        lines.append("### 东方财富跨市场新闻")
        lines.append("")
        for news in em_news[:10]:
            title = news.get('title', '')
            date = news.get('date', '')
            summary = news.get('summary', '')[:100]
            keyword = news.get('keyword', '')
            lines.append(f"- **{title}** ({date})")
            if summary:
                lines.append(f"  {summary}...")
            lines.append(f"  搜索关键词: {keyword}")
        lines.append("")

    # 港交所披露易搜索结果
    hkex_entities = data.get('hkex_entities', [])
    if hkex_entities:
        lines.append("### 港交所披露易公告")
        lines.append("")
        for ann in hkex_entities[:10]:
            title = ann.get('title', '')
            date = ann.get('date', '')
            code = ann.get('code', '')
            lines.append(f"- **{code}** {title} ({date})")
        lines.append("")

    # 公司名称别名
    aliases = data.get('company_aliases', [])
    if aliases:
        lines.append("### 公司名称别名（用于跨市场搜索）")
        lines.append("")
        lines.append(", ".join(aliases[:20]))
        lines.append("")

    return lines


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='跨市场关联扫描器')
    parser.add_argument('--stock', required=True, help='股票代码')
    parser.add_argument('--market', default='a', help='市场: a/hk/us')
    parser.add_argument('--data-dir', required=True, help='数据目录')
    args = parser.parse_args()
    results = scan_cross_market(args.stock, args.market, args.data_dir)
    print(f"\n{'='*60}")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
