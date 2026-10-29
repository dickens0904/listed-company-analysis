# -*- coding: utf-8 -*-
"""
cross_market_discovery.py - 跨市场关联发现（通用方法论）

三阶段发现框架：
  P0: 名称库匹配（港股/美股上市公司名称匹配）
  P1: AI研判（LLM分析实体与母公司的关系）
  P2: 多数据源交叉验证（公告+年报+新闻+工商数据交叉确认）

免费数据源（全部无需API Key）：
  1. Futu OpenAPI（首选，通过OpenD获取全量港股/美股列表，数据质量最高）
  2. 本地股票宇宙数据库（stock_universe/*.json，Futu一次性下载，本地匹配最快）
  3. 东方财富港股/美股列表API（push2.eastmoney.com，回退方案，有反爬风险）
  4. Yahoo Finance搜索API（query1.finance.yahoo.com，支持英文名搜索）
  5. 新浪财经行情API（hq.sinajs.cn，验证股票代码是否有效）
  6. company_resolver（内置港股/美股快速映射表）
  7. THSDK（可选，游客账号免费）

网络环境说明：
  - Futu OpenAPI 需要本地运行OpenD服务（网关程序），数据最全最稳定
  - 东方财富搜索API（searchapi-hk.eastmoney.com）可能返回HTML而非JSON
  - AKShare 东方财富源可能被反爬限制
  - push2.eastmoney.com 列表API可用但有100条/页限制，需分页，IP易被封
  - Yahoo Finance 搜索API部分网络环境可用
  - 新浪财经行情API 最稳定，但需要预先知道代码
  - THSDK 支持搜索但无法获取全量列表

使用方式：
  from scripts.cross_market_discovery import CrossMarketDiscovery
  
  discovery = CrossMarketDiscovery(stock_code, market, data_dir)
  results = discovery.discover()
"""

import sys
import json
import os
import re
import time
import urllib.parse
from typing import Dict, List, Set, Optional
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class CrossMarketDiscovery:
    """跨市场关联发现"""
    
    def __init__(self, stock_code: str, market: str, data_dir: str):
        self.stock_code = stock_code
        self.market = market
        self.data_dir = data_dir
        self.data = {}
        self.results = {}
    
    def load_data(self):
        """加载已有的分析数据"""
        print("加载跨市场发现数据...")
        
        # 先加载 results.json（包含所有维度数据）
        results_path = os.path.join(self.data_dir, 'results.json')
        if os.path.exists(results_path):
            try:
                with open(results_path, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                findings = results.get('findings', {})
                # 从 results.json 提取各维度数据
                for key in ['announcements', 'annual_report', 'structure', 'enhanced_company_info',
                            'cross_market_scan', 'financial', 'capital', 'subsidiary']:
                    if key in findings:
                        self.data[key] = findings[key]
                        print(f"  ✓ 从results加载: {key}")
            except Exception as e:
                print(f"  ✗ 加载results.json失败: {e}")
        
        # 再加载单独的文件（覆盖results中的数据）
        for key, filename in [
            ('annual_report', 'annual_report_sections.json'),
            ('structure', 'structure.json'),
            ('enhanced_company_info', 'enhanced_company_info.json'),
            ('financial_metrics', 'financial_metrics.json'),
        ]:
            filepath = os.path.join(self.data_dir, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        self.data[key] = json.load(f)
                    print(f"  ✓ 加载: {filename}")
                except Exception as e:
                    print(f"  ✗ 加载失败: {filename}, {e}")
    
    def discover(self) -> Dict:
        """执行三阶段发现流程"""
        print(f"\n{'='*60}")
        print(f"跨市场关联发现 - {self.stock_code}")
        print(f"{'='*60}")
        
        self.results = {
            'stock_code': self.stock_code,
            'market': self.market,
            'discovery_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'p0_matches': [],  # P0: 名称库匹配结果
            'p1_analysis': [],  # P1: AI研判结果
            'p2_verification': [],  # P2: 交叉验证结果
            'final_findings': [],  # 最终发现
        }
        
        # 第0步：收集所有境外实体
        self._collect_foreign_entities()
        
        # P0: 港股/美股上市公司名称库匹配
        self._p0_name_matching()
        
        # P1: AI研判
        self._p1_ai_analysis()
        
        # P2: 多数据源交叉验证
        self._p2_cross_verification()
        
        # 汇总最终发现
        self._generate_final_findings()
        
        return self.results
    
    def _collect_foreign_entities(self):
        """收集所有境外实体（年报+公告+子公司+跨市场扫描）"""
        print("\n收集境外实体...")
        entities = []
        seen = set()
        
        # 0. 从跨市场扫描结果中获取（最高效）
        if 'cross_market_scan' in self.data:
            cms = self.data['cross_market_scan']
            for ent in cms.get('announcement_entities', []):
                name = ent.get('name', '')
                if name and name not in seen and len(name) > 5:
                    seen.add(name)
                    entities.append({
                        'name': name,
                        'source': 'announcement',
                        'entity_type': ent.get('entity_type', '境外公司'),
                    })
            for ent in cms.get('subsidiary_entities', []):
                name = ent.get('name', '')
                if name and name not in seen and len(name) > 5:
                    seen.add(name)
                    entities.append({
                        'name': name,
                        'source': 'subsidiary',
                    })
        
        # 1. 从年报文本提取
        if 'annual_report' in self.data:
            annual = self.data['annual_report']
            # 年报文本
            if isinstance(annual, dict):
                for section_key, section_data in annual.items():
                    if not isinstance(section_data, dict):
                        continue
                    content = section_data.get('content', '')
                    if not content:
                        continue
                    
                    # 提取英文名称
                    matches = re.findall(
                        r'([A-Z][a-zA-Z\s]+(?:Holdings?|International|Limited|Inc|Ltd|Co\.?|Corp|Group|Technology))',
                        content[:10000]
                    )
                    for m in matches:
                        name = m.strip()
                        if name not in seen and len(name) > 5:
                            seen.add(name)
                            entities.append({
                                'name': name,
                                'source': 'annual_report',
                                'section': section_key,
                            })
            
            # 年报文本文件
            txt_path = os.path.join(self.data_dir, 'annual_report_text.txt')
            if os.path.exists(txt_path):
                try:
                    with open(txt_path, 'r', encoding='utf-8') as f:
                        txt_content = f.read()
                    matches = re.findall(
                        r'([A-Z][a-zA-Z\s]+(?:Holdings?|International|Limited|Inc|Ltd|Co\.?|Corp|Group|Technology))',
                        txt_content[:20000]
                    )
                    for m in matches:
                        name = m.strip()
                        if name not in seen and len(name) > 5:
                            seen.add(name)
                            entities.append({
                                'name': name,
                                'source': 'annual_report_txt',
                            })
                except Exception as _sexc:
                    record(__name__, '_collect_foreign_entities', _sexc, note='静默降级')
                    pass
        
        # 2. 从公告全文提取
        if 'announcements' in self.data:
            anns = self.data['announcements']
            if isinstance(anns, dict):
                # 从 critical_announcements 目录
                critical_dir = os.path.join(self.data_dir, 'critical_announcements')
                if os.path.exists(critical_dir):
                    for filename in os.listdir(critical_dir)[:50]:  # 限制数量
                        if filename.endswith('.json'):
                            try:
                                with open(os.path.join(critical_dir, filename), 'r', encoding='utf-8') as f:
                                    ann = json.load(f)
                                content = ann.get('extracted_content', {}).get('full_text_preview', '')
                                if content:
                                    matches = re.findall(
                                        r'([A-Z][a-zA-Z\s]+(?:Holdings?|International|Limited|Inc|Ltd|Co\.?|Corp|Group|Technology))',
                                        content[:2000]
                                    )
                                    for m in matches:
                                        name = m.strip()
                                        if name not in seen and len(name) > 5:
                                            seen.add(name)
                                            entities.append({
                                                'name': name,
                                                'source': 'announcement',
                                                'title': ann.get('title', ''),
                                                'date': ann.get('publish_time', ''),
                                            })
                            except Exception as _sexc:
                                record(__name__, '_collect_foreign_entities', _sexc, note='静默降级')
                                pass
                
                # 从 announcements 列表
                for ann in anns.get('announcements', [])[:20]:
                    content = ann.get('extracted_content', {}).get('full_text_preview', '')
                    if not content:
                        continue
                    
                    matches = re.findall(
                        r'([A-Z][a-zA-Z\s]+(?:Holdings?|International|Limited|Inc|Ltd|Co\.?|Corp|Group|Technology))',
                        content[:3000]
                    )
                    for m in matches:
                        name = m.strip()
                        if name not in seen and len(name) > 5:
                            seen.add(name)
                            entities.append({
                                'name': name,
                                'source': 'announcement',
                                'title': ann.get('title', ''),
                                'date': ann.get('publish_time', ''),
                            })
        
        # 3. 从子公司列表提取
        if 'enhanced_company_info' in self.data:
            eci = self.data['enhanced_company_info']
            for sub in eci.get('subsidiaries', {}).get('full_list', []):
                name = sub.get('name', '')
                if name and any(ind in name for ind in ['International', 'Holdings', 'Limited', 'Inc', 'Ltd', 'Hong Kong', '香港']):
                    if name not in seen:
                        seen.add(name)
                        entities.append({
                            'name': name,
                            'source': 'subsidiary',
                            'sub_type': sub.get('type', ''),
                        })
        
        self.results['foreign_entities'] = entities
        print(f"  发现 {len(entities)} 个境外实体")
        for ent in entities[:15]:
            print(f"    - [{ent['source']}] {ent['name'][:60]}")
    
    def _p0_name_matching(self):
        """P0: 港股/美股上市公司名称库匹配（本地数据库+在线验证）"""
        print("\n[P0] 港股/美股上市公司名称库匹配...")
        matches = []
        
        entities = self.results.get('foreign_entities', [])
        
        # 数据源1: 本地股票宇宙数据库（东方财富一次性下载，本地匹配）
        local_matches = self._local_stock_universe_search(entities)
        matches.extend(local_matches)
        
        # 数据源2: Yahoo Finance搜索（英文名直接搜索）
        yahoo_matches = self._yahoo_us_search(entities)
        matches.extend(yahoo_matches)
        
        # 数据源3: company_resolver内置映射表（已知港股快速匹配）
        resolver_matches = self._resolver_mapping_search(entities)
        matches.extend(resolver_matches)
        
        # 数据源4: THSDK（可选）
        thsdk_matches = self._thsdk_search_entities(entities)
        matches.extend(thsdk_matches)
        
        # 去重
        seen = set()
        deduped = []
        for m in matches:
            key = f"{m['market']}_{m['code']}"
            if key not in seen:
                seen.add(key)
                deduped.append(m)
        
        self.results['p0_matches'] = deduped
        print(f"\n  P0匹配结果: {len(deduped)} 个（去重后）")
        for m in deduped[:10]:
            print(f"    - {m['entity_name'][:50]} → {m['market']} {m['code']} {m['listed_name']} [{m.get('source','?')}]")
    
    def _normalize_entity_name(self, name):
        """实体名归一化：去空格、转小写、移除公司后缀"""
        if not name:
            return ''
        # 移除常见公司后缀
        name = re.sub(r'\s+(Limited|Ltd|Inc|LLC|Co\.?|Corp|BVI|HK|Holdings?|Group|International|Technology)\b', '', name, flags=re.IGNORECASE)
        name = name.strip().lower()
        # 移除特殊字符
        name = re.sub(r'[^\w\u4e00-\u9fff]', '', name)
        return name
    
    def _load_local_stock_universe(self):
        """加载本地股票宇宙数据库
        
        数据源优先级：
        1. stock_universe/*.json（Futu OpenAPI下载，数据最全）
        2. Futu OpenAPI实时查询（如果OpenD可用）
        3. 东方财富API（回退方案，有反爬风险）
        """
        if hasattr(self, '_stock_universe_loaded'):
            return
        
        self._stock_universe_loaded = True
        self._hk_stocks = []
        self._us_stocks = []
        
        # 优先1：尝试从工作区stock_universe加载（Futu OpenAPI下载）
        # 路径全部相对化。2026-10-19 审计：原第3项硬编码
        # r'D:\BaiduSyncdisk\workspace-agent-550df5d1\stock_universe' 指向他人机器的
        # 同步盘目录，本机不存在 → 港股股票池永远为空且**静默失败**（不报错）。
        # 改为环境变量 STOCK_UNIVERSE_DIR 覆盖 + 两个相对路径。
        script_dir = os.path.dirname(__file__)
        project_root = os.path.dirname(script_dir)
        universe_dirs = [
            os.environ.get('STOCK_UNIVERSE_DIR'),                    # 显式覆盖
            os.path.join(script_dir, 'stock_universe'),               # 模块内
            os.path.join(project_root, 'stock_universe'),              # 工作区根目录
        ]
        universe_dirs = [d for d in universe_dirs if d]
        
        for universe_dir in universe_dirs:
            if os.path.exists(universe_dir):
                hk_file = os.path.join(universe_dir, 'hk_stocks.json')
                us_file = os.path.join(universe_dir, 'us_stocks.json')
                
                if os.path.exists(hk_file) and not self._hk_stocks:
                    try:
                        with open(hk_file, 'r', encoding='utf-8') as f:
                            self._hk_stocks = json.load(f)
                        print(f"    [Futu本地] 加载港股: {len(self._hk_stocks)} 条")
                    except Exception as _sexc:
                        record(__name__, '_load_local_stock_universe', _sexc, note='静默降级')
                        pass
                
                if os.path.exists(us_file) and not self._us_stocks:
                    try:
                        with open(us_file, 'r', encoding='utf-8') as f:
                            self._us_stocks = json.load(f)
                        print(f"    [Futu本地] 加载美股: {len(self._us_stocks)} 条")
                    except Exception as _sexc:
                        record(__name__, '_load_local_stock_universe', _sexc, note='静默降级')
                        pass
            
            if self._hk_stocks and self._us_stocks:
                break
        
        # 优先2：如果本地数据不足100条，尝试Futu OpenAPI
        if len(self._hk_stocks) < 100 or len(self._us_stocks) < 100:
            futu_loaded = self._load_from_futu_opend()
            if futu_loaded:
                return
        
        # 回退：如果本地和Futu都不可用，尝试从东方财富下载
        if len(self._hk_stocks) < 100:
            self._hk_stocks = self._download_stock_list_from_em(
                '港股', 'm:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2', 5  # 只下载5页
            )
        
        if len(self._us_stocks) < 100:
            self._us_stocks = self._download_stock_list_from_em(
                '美股', 'm:100,m:101,m:102,m:103,m:104,m:105,m:106', 5  # 只下载5页
            )
    
    def _load_from_futu_opend(self):
        """通过Futu OpenAPI获取全量股票列表"""
        print("    尝试通过Futu OpenAPI获取股票列表...")
        
        try:
            futu_scripts = os.environ.get('FUTU_SCRIPTS_DIR')
            if not futu_scripts or not os.path.isdir(futu_scripts):
                print("    [提示] 未配置 FUTU_SCRIPTS_DIR，跳过 Futu OpenAPI 拉取股票池"
                      "（设 FUTU_SCRIPTS_DIR 指向 futuapi 的 scripts 目录可启用）")
                return
            sys.path.insert(0, futu_scripts)
            # 2026-10-19 审计：原此处有一个"只有 try: from common import ..."的空壳嵌套
            # try（无 except/finally 配对），属上游遗留死代码。已移除。
            # ImportError 由本函数外层 try/except 统一兜底。
            from common import create_quote_context, RET_OK, Market, SecurityType, safe_close
            
            quote_ctx = None
            try:
                quote_ctx = create_quote_context()
                
                # 获取港股
                if len(self._hk_stocks) < 100:
                    ret, data = quote_ctx.get_stock_basicinfo(Market.HK, SecurityType.STOCK)
                    if ret == RET_OK:
                        self._hk_stocks = []
                        for _, row in data.iterrows():
                            self._hk_stocks.append({
                                'code': row.get('code', ''),
                                'name': row.get('name', ''),
                                'lot_size': row.get('lot_size', 0),
                                'stock_type': str(row.get('stock_type', '')),
                                'listing_date': row.get('list_time', '') or row.get('listing_date', ''),
                                'stock_id': row.get('stock_id', 0),
                                'exchange_type': str(row.get('exchange_type', '')) if 'exchange_type' in data.columns else ''
                            })
                        print(f"    [Futu OpenAPI] 获取港股: {len(self._hk_stocks)} 条")
                
                # 获取美股
                if len(self._us_stocks) < 100:
                    ret, data = quote_ctx.get_stock_basicinfo(Market.US, SecurityType.STOCK)
                    if ret == RET_OK:
                        self._us_stocks = []
                        for _, row in data.iterrows():
                            self._us_stocks.append({
                                'code': row.get('code', ''),
                                'name': row.get('name', ''),
                                'lot_size': row.get('lot_size', 0),
                                'stock_type': str(row.get('stock_type', '')),
                                'listing_date': row.get('list_time', '') or row.get('listing_date', ''),
                                'stock_id': row.get('stock_id', 0),
                                'exchange_type': str(row.get('exchange_type', '')) if 'exchange_type' in data.columns else ''
                            })
                        print(f"    [Futu OpenAPI] 获取美股: {len(self._us_stocks)} 条")
                
                return len(self._hk_stocks) >= 100 and len(self._us_stocks) >= 100
                
            finally:
                safe_close(quote_ctx)
                
        except Exception as e:
            print(f"    Futu OpenAPI不可用: {e}")
            return False
    
    def _download_stock_list_from_em(self, market_name, fs_params, max_pages=5):
        """从东方财富下载股票列表（限制页数）"""
        print(f"    从东方财富下载 {market_name}（最多{max_pages}页）...")
        import requests
        
        base_url = 'https://push2.eastmoney.com/api/qt/clist/get'
        params = {
            'pn': 1, 'pz': 100, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f12',
            'fields': 'f12,f14', 'fs': fs_params,
        }
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        all_stocks = []
        for page in range(1, max_pages + 1):
            params['pn'] = page
            try:
                r = requests.get(base_url, params=params, timeout=15, headers=headers)
                data = r.json()
                diff = data.get('data', {}).get('diff', [])
                if not diff:
                    break
                for d in diff:
                    code = d.get('f12', '').strip()
                    name = d.get('f14', '').strip()
                    if code and name:
                        all_stocks.append({'code': code, 'name': name})
                time.sleep(0.3)
            except Exception as e:
                print(f"    第{page}页失败: {e}")
                break
        
        print(f"    下载完成: {len(all_stocks)} 条")
        return all_stocks
    
    def _local_stock_universe_search(self, entities):
        """本地股票宇宙数据库匹配（最快，无网络依赖）"""
        print("\n  [数据源1] 本地股票数据库匹配...")
        matches = []
        seen = set()
        
        self._load_local_stock_universe()
        
        for ent in entities:
            name = ent['name']
            normalized = self._normalize_entity_name(name)
            
            # 港股模糊匹配
            for stock in self._hk_stocks:
                stock_norm = self._normalize_entity_name(stock['name'])
                if not stock_norm:
                    continue
                # 精确匹配或包含匹配
                if normalized == stock_norm or stock_norm in normalized or normalized in stock_norm:
                    key = f"HK_{stock['code']}"
                    if key not in seen:
                        seen.add(key)
                        matches.append({
                            'entity_name': name,
                            'search_keyword': stock['name'],
                            'market': 'HK',
                            'code': stock['code'],
                            'listed_name': stock['name'],
                            'source': 'local_hk_db',
                            'entity_source': ent['source'],
                        })
                        print(f"    港股匹配: {name[:40]} → HK {stock['code']} {stock['name']}")
                    break
            
            # 美股模糊匹配
            for stock in self._us_stocks:
                stock_norm = self._normalize_entity_name(stock['name'])
                if not stock_norm:
                    continue
                if normalized == stock_norm or stock_norm in normalized or normalized in stock_norm:
                    key = f"US_{stock['code']}"
                    if key not in seen:
                        seen.add(key)
                        matches.append({
                            'entity_name': name,
                            'search_keyword': stock['name'],
                            'market': 'US',
                            'code': stock['code'],
                            'listed_name': stock['name'],
                            'source': 'local_us_db',
                            'entity_source': ent['source'],
                        })
                        print(f"    美股匹配: {name[:40]} → US {stock['code']} {stock['name']}")
                    break
        
        return matches
    
    def _yahoo_us_search(self, entities):
        """Yahoo Finance美股搜索（免费，无需Key）"""
        print("\n  [数据源2] Yahoo Finance美股搜索...")
        matches = []
        seen = set()
        
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        
        # 提取前15个实体进行搜索
        search_names = []
        for ent in entities[:15]:
            name = ent['name']
            # 英文名归一化
            short = re.sub(r'\s+(Limited|Ltd|Inc|LLC|Co\.?|Corp|BVI|HK)?$', '', name, flags=re.IGNORECASE).strip()
            if short and len(short) >= 2:
                search_names.append({'full': name, 'short': short, 'source': ent['source']})
        
        for item in search_names[:10]:
            try:
                url = 'https://query1.finance.yahoo.com/v1/finance/search'
                params = {
                    'q': item['short'],
                    'quotesCount': 5,
                    'newsCount': 0,
                    'enableFuzzyQuery': 'true',
                }
                r = requests.get(url, params=params, timeout=8, headers=headers)
                data = r.json()
                
                for quote in data.get('quotes', [])[:5]:
                    ticker = str(quote.get('symbol', '')).strip()
                    ticker_name = str(quote.get('shortname', '') or quote.get('longname', '')).strip()
                    exchange = str(quote.get('exchange', '')).strip()
                    
                    if not ticker:
                        continue
                    # 过滤期权/期货（包含特殊符号的）
                    if '/' in ticker:
                        continue
                    # 只保留美股交易所
                    if exchange not in ('NMS', 'NYQ', 'PCX', 'NGM', 'BTS', 'ASE', 'PNK'):
                        continue
                    
                    key = f"US_{ticker}"
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    matches.append({
                        'entity_name': item['full'],
                        'search_keyword': item['short'],
                        'market': 'US',
                        'code': ticker,
                        'listed_name': ticker_name,
                        'source': 'yahoo_finance',
                        'entity_source': item['source'],
                    })
                    print(f"    匹配: {item['short'][:40]} → US {ticker} {ticker_name}")
                    break  # 找到第一个匹配就继续下一个实体
                    
            except Exception as e:
                print(f"    搜索失败: {e}")
                continue
            
            time.sleep(0.3)
        
        return matches
    
    def _resolver_mapping_search(self, entities):
        """使用 company_resolver 的内置映射表快速匹配"""
        print("\n  [数据源3] company_resolver 内置映射表...")
        matches = []
        seen = set()
        
        try:
            from scripts.company_resolver import KNOWN_CHINESE_HK
            
            # 尝试从实体名中提取中文名或已知简称
            for ent in entities[:20]:
                name = ent['name']
                
                # 直接匹配已知港股
                for cn_name, hk_code in KNOWN_CHINESE_HK.items():
                    if hk_code == '未上市':
                        continue
                    # 检查实体名是否包含已知中文公司名
                    if cn_name in name or self._normalize_entity_name(cn_name) == self._normalize_entity_name(name):
                        key = f"HK_{hk_code}"
                        if key in seen:
                            continue
                        seen.add(key)
                        
                        matches.append({
                            'entity_name': name,
                            'search_keyword': cn_name,
                            'market': 'HK',
                            'code': hk_code,
                            'listed_name': cn_name,
                            'source': 'resolver_mapping',
                            'entity_source': ent['source'],
                        })
                        print(f"    匹配: {name[:40]} → HK {hk_code} {cn_name}")
                        break
                
        except Exception as e:
            print(f"    映射表搜索失败: {e}")
        
        return matches
    
    def _akshare_hk_search(self, entities):
        """AKShare 港股全列表搜索（免费，回退方案）"""
        print("\n  [数据源4] AKShare 港股全列表搜索...")
        matches = []
        seen = set()
        
        try:
            import akshare as ak
            
            # 获取港股全列表
            hk_list = ak.stock_hk_spot_em()
            if hk_list is None or hk_list.empty:
                print("    AKShare 返回空数据")
                return matches
            
            # 构建名称索引
            hk_index = {}
            for _, row in hk_list.iterrows():
                code = str(row.get('代码', '') or row.get('code', '')).strip()
                name = str(row.get('名称', '') or row.get('name', '')).strip()
                if code and name:
                    hk_index[self._normalize_entity_name(name)] = {
                        'code': code,
                        'name': name,
                    }
            
            # 匹配实体
            for ent in entities[:20]:
                name = ent['name']
                normalized = self._normalize_entity_name(name)
                
                # 精确匹配
                if normalized in hk_index:
                    info = hk_index[normalized]
                    key = f"HK_{info['code']}"
                    if key not in seen:
                        seen.add(key)
                        matches.append({
                            'entity_name': name,
                            'search_keyword': name,
                            'market': 'HK',
                            'code': info['code'],
                            'listed_name': info['name'],
                            'source': 'akshare_hk',
                            'entity_source': ent['source'],
                        })
                        print(f"    匹配: {name[:40]} → HK {info['code']} {info['name']}")
                
                # 模糊匹配：实体名包含港股名称
                for hk_norm, info in hk_index.items():
                    if len(hk_norm) >= 2 and hk_norm in normalized:
                        key = f"HK_{info['code']}"
                        if key not in seen:
                            seen.add(key)
                            matches.append({
                                'entity_name': name,
                                'search_keyword': info['name'],
                                'market': 'HK',
                                'code': info['code'],
                                'listed_name': info['name'],
                                'source': 'akshare_hk_fuzzy',
                                'entity_source': ent['source'],
                            })
                            print(f"    模糊匹配: {name[:40]} → HK {info['code']} {info['name']}")
                        break
                        
        except Exception as e:
            print(f"    AKShare 搜索失败: {e}")
        
        return matches
    
    def _thsdk_search_entities(self, entities):
        """用THSDK搜索实体是否为上市公司"""
        matches = []
        seen = set()
        
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("thsdk_search", os.path.join(os.path.dirname(__file__), "thsdk_search.py"))
            thsdk_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(thsdk_module)
            ThsdkSearch = thsdk_module.ThsdkSearch
        except Exception as e:
            print(f"  THSDK不可用，跳过搜索: {e}")
            return matches
        
        # 搜索前10个实体
        search_list = []
        for ent in entities:
            name = ent['name']
            # 提取简称（去掉 Limited/Inc 等后缀）
            short = re.sub(r'\s+(Limited|Ltd|Inc|LLC|Co\.?|Corp|BVI|HK)?$', '', name, flags=re.IGNORECASE)
            if short and len(short) >= 3:
                search_list.append({'full': name, 'short': short, 'source': ent['source']})
        
        for item in search_list[:10]:
            for keyword in [item['short'], item['full']]:
                if len(keyword) < 3:
                    continue
                
                try:
                    with ThsdkSearch() as sdk:
                        result = sdk.search(keyword)
                    
                    if not result.get('success'):
                        continue
                    
                    for rec in result.get('data', []):
                        market = rec.get('MarketStr', '')
                        code = rec.get('Code', rec.get('code', ''))
                        name = rec.get('Name', rec.get('name', ''))
                        
                        # 只关注港股和美股
                        if market not in ('UHK', 'USE'):
                            continue
                        
                        market_label = 'HK' if market == 'UHK' else 'US'
                        key = f"{market_label}_{code}"
                        if key in seen:
                            continue
                        seen.add(key)
                        
                        matches.append({
                            'entity_name': item['full'],
                            'search_keyword': keyword,
                            'market': market_label,
                            'code': code,
                            'listed_name': name,
                            'source': 'thsdk',
                            'entity_source': item['source'],
                        })
                        print(f"    匹配: {item['short'][:40]} → {market_label} {code} {name}")
                        
                        # 找到第一个匹配就继续下一个实体
                        break
                        
                except Exception as e:
                    print(f"    搜索失败: {e}")
                    continue
                
                time.sleep(0.3)
        
        return matches
    
    def _p1_ai_analysis(self):
        """P1: AI研判实体与母公司的关系"""
        print("\n[P1] AI研判分析...")
        
        entities = self.results.get('foreign_entities', [])
        p0_matches = self.results.get('p0_matches', [])
        
        if not entities:
            print("  无实体需要研判")
            return
        
        # 准备AI分析数据：分析所有境外实体（不仅是P0匹配项）
        analysis_items = []
        
        # 1. 先分析P0匹配的实体（有上市公司代码的）
        for match in p0_matches:
            entity = next((e for e in entities if e['name'] == match['entity_name']), None)
            if entity:
                analysis_items.append({
                    'entity_name': match['entity_name'],
                    'entity_source': match['entity_source'],
                    'market': match['market'],
                    'code': match['code'],
                    'listed_name': match['listed_name'],
                    'is_listed': True,  # 标记为已确认上市
                })
        
        # 2. 再分析未匹配P0但可能是上市公司的实体
        matched_names = {m['entity_name'] for m in p0_matches}
        for ent in entities:
            if ent['name'] not in matched_names:
                # 优先分析英文名称（更可能是境外上市公司）
                name = ent['name']
                if any(c.isupper() for c in name[:10]):  # 英文名优先
                    analysis_items.append({
                        'entity_name': ent['name'],
                        'entity_source': ent['source'],
                        'market': 'unknown',
                        'code': '',
                        'listed_name': '',
                        'is_listed': False,  # 待确认是否上市
                    })
        
        # 限制分析数量（节省token）
        analysis_items = analysis_items[:15]
        
        if not analysis_items:
            print("  无实体需要AI研判")
            return
        
        # 调用LLM分析
        ai_results = self._call_llm_analysis(analysis_items)
        self.results['p1_analysis'] = ai_results
        print(f"  AI研判完成: {len(ai_results)} 个实体")
    
    def _call_llm_analysis(self, items):
        """调用LLM分析实体关系"""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("llm_config", os.path.join(os.path.dirname(__file__), "llm_config.py"))
            llm_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(llm_module)
            LLM_CONFIG = llm_module.LLM_CONFIG
            from openai import OpenAI
        except Exception as e:
            print(f"  LLM配置不可用，跳过AI研判: {e}")
            return []
        
        client = OpenAI(
            api_key=LLM_CONFIG['api_key'],
            base_url=LLM_CONFIG['base_url']
        )
        
        # 获取母公司信息
        parent_company = self._get_parent_company_name()
        
        # 构建提示词
        prompt = self._build_analysis_prompt(parent_company, items)
        
        try:
            response = client.chat.completions.create(
                model=LLM_CONFIG['model'],
                messages=[
                    {
                        "role": "system",
                        "content": "你是跨市场关联分析专家。分析境外实体与A股上市公司的关联关系。"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=LLM_CONFIG['temperature'],
                max_tokens=LLM_CONFIG['max_tokens'],
            )
            
            # 解析LLM返回结果
            content = response.choices[0].message.content
            return self._parse_llm_response(content, items)
            
        except Exception as e:
            print(f"  LLM调用失败: {e}")
            return []
    
    def _get_parent_company_name(self):
        """获取A股上市公司名称"""
        if 'structure' in self.data:
            profile = self.data['structure'].get('company_profile', {})
            name = profile.get('name', '')
            if name:
                return name
            
            struct = self.data['structure'].get('structure', {})
            name = struct.get('main_listed', {}).get('name', '')
            if name:
                return name
        
        return self.stock_code
    
    def _build_analysis_prompt(self, parent_company, items):
        """构建AI分析提示词"""
        items_text = "\n".join([
            f"  {i+1}. 实体: {item['entity_name']} (来源: {item['entity_source']}, 市场: {item['market']}, 代码: {item['code']}, 上市名称: {item['listed_name']})"
            for i, item in enumerate(items)
        ])
        
        return f"""分析以下境外实体与A股上市公司 {parent_company} 的关联关系。

待分析实体：
{items_text}

请按以下格式分析每个实体：
1. 关联关系类型：
   - 直接子公司
   - 间接子公司
   - 关联方
   - 合作伙伴
   - 投资标的
   - 借壳上市目标
   - 其他
2. 关联程度：强/中/弱
3. 分析依据：（基于实体出现的数据源）
4. 资本运作可能性：（如分拆上市、借壳、双重上市等）
5. 风险提示

请只返回JSON格式，格式如下：
[
  {{
    "entity_name": "实体名称",
    "relation_type": "关联关系类型",
    "relation_strength": "强/中/弱",
    "analysis_basis": "分析依据",
    "capital_operation_possibility": "资本运作可能性",
    "risk_note": "风险提示"
  }}
]
"""
    
    def _parse_llm_response(self, content, items):
        """解析LLM返回结果"""
        try:
            # 提取JSON
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                results = json.loads(json_match.group(0))
                return results
        except Exception as e:
            print(f"  解析LLM返回失败: {e}")
        
        # 降级：返回简单分析
        return [{
            'entity_name': item['entity_name'],
            'relation_type': '待分析',
            'relation_strength': '未知',
            'analysis_basis': 'LLM分析失败',
            'capital_operation_possibility': '待评估',
            'risk_note': '需要人工研判',
        } for item in items[:5]]
    
    def _p2_cross_verification(self):
        """P2: 多数据源交叉验证"""
        print("\n[P2] 多数据源交叉验证...")
        
        verifications = []
        entities = self.results.get('foreign_entities', [])
        p0_matches = self.results.get('p0_matches', [])
        p1_results = self.results.get('p1_analysis', [])
        
        for match in p0_matches:
            entity_name = match['entity_name']
            verification = {
                'entity_name': entity_name,
                'market': match['market'],
                'code': match['code'],
                'listed_name': match['listed_name'],
                'sources_found': [],
                'confidence': 'low',
            }
            
            # 检查在哪些数据源中出现
            sources = set()
            for ent in entities:
                if ent['name'] == entity_name:
                    sources.add(ent['source'])
            
            verification['sources_found'] = list(sources)
            
            # 计算置信度
            if len(sources) >= 3:
                verification['confidence'] = 'high'
            elif len(sources) >= 2:
                verification['confidence'] = 'medium'
            
            verifications.append(verification)
            print(f"    {entity_name[:40]}... 数据源: {', '.join(sources)} 置信度: {verification['confidence']}")
        
        self.results['p2_verification'] = verifications
    
    def _generate_final_findings(self):
        """汇总最终发现"""
        print("\n生成最终发现...")
        
        findings = []
        
        # 1. 先处理P0匹配的实体（有明确市场代码）
        for match in self.results.get('p0_matches', []):
            entity_name = match['entity_name']
            
            # 找到AI分析结果
            ai_result = next(
                (a for a in self.results.get('p1_analysis', []) if a.get('entity_name') == entity_name),
                {}
            )
            
            # 找到交叉验证结果
            verification = next(
                (v for v in self.results.get('p2_verification', []) if v.get('entity_name') == entity_name),
                {}
            )
            
            finding = {
                'entity_name': entity_name,
                'market': match['market'],
                'code': match['code'],
                'listed_name': match['listed_name'],
                'relation_type': ai_result.get('relation_type', '待分析'),
                'relation_strength': ai_result.get('relation_strength', '未知'),
                'confidence': verification.get('confidence', 'low'),
                'sources': verification.get('sources_found', []),
                'capital_operation': ai_result.get('capital_operation_possibility', '待评估'),
                'risk_note': ai_result.get('risk_note', ''),
            }
            
            findings.append(finding)
        
        # 2. 再处理P1中未匹配P0但有AI研判的实体（潜在关联）
        p0_entity_names = {m['entity_name'] for m in self.results.get('p0_matches', [])}
        
        for ai_result in self.results.get('p1_analysis', []):
            entity_name = ai_result.get('entity_name', '')
            if not entity_name or entity_name in p0_entity_names:
                continue
            
            # 找到原始实体信息
            entity = next(
                (e for e in self.results.get('foreign_entities', []) if e['name'] == entity_name),
                {}
            )
            
            finding = {
                'entity_name': entity_name,
                'market': ai_result.get('market', '待确认'),
                'code': ai_result.get('code', ''),
                'listed_name': ai_result.get('listed_name', ''),
                'relation_type': ai_result.get('relation_type', '待分析'),
                'relation_strength': ai_result.get('relation_strength', '未知'),
                'confidence': 'medium' if ai_result.get('is_listed') else 'low',
                'sources': [entity.get('source', '未知')],
                'capital_operation': ai_result.get('capital_operation_possibility', '待评估'),
                'risk_note': ai_result.get('risk_note', ''),
                'is_potential': True,  # 标记为潜在关联
            }
            
            findings.append(finding)
        
        # 按置信度排序
        confidence_order = {'high': 0, 'medium': 1, 'low': 2}
        findings.sort(key=lambda x: confidence_order.get(x['confidence'], 3))
        
        self.results['final_findings'] = findings
        print(f"\n最终发现 {len(findings)} 个跨市场关联:")
        for f in findings[:10]:
            marker = "[潜在]" if f.get('is_potential') else "[确认]"
            print(f"  [{f['confidence']}] {marker} {f['entity_name'][:40]}... → {f['market']} {f.get('code', '')}")


def generate_report_section(data) -> List[str]:
    """生成跨市场发现报告章节"""
    from typing import List
    
    lines = ["\n## 跨市场关联发现\n"]
    
    findings = data.get('final_findings', [])
    if not findings:
        lines.append("未发现跨市场关联实体。\n")
        return lines
    
    lines.append(f"**共发现 {len(findings)} 个跨市场关联实体**\n")
    
    # 按置信度分组
    high_conf = [f for f in findings if f['confidence'] == 'high']
    medium_conf = [f for f in findings if f['confidence'] == 'medium']
    low_conf = [f for f in findings if f['confidence'] == 'low']
    
    if high_conf:
        lines.append("### 高置信度关联\n")
        for f in high_conf:
            lines.append(f"- **{f['entity_name']}** ({f['market']} {f['code']})")
            lines.append(f"  - 关联类型: {f['relation_type']}")
            lines.append(f"  - 关联程度: {f['relation_strength']}")
            lines.append(f"  - 资本运作: {f['capital_operation']}")
            lines.append("")
    
    if medium_conf:
        lines.append("### 中置信度关联\n")
        for f in medium_conf:
            lines.append(f"- **{f['entity_name']}** ({f['market']} {f['code']})")
            lines.append(f"  - 关联类型: {f['relation_type']}")
            lines.append(f"  - 资本运作: {f['capital_operation']}")
            lines.append("")
    
    if low_conf:
        lines.append("### 低置信度关联（需人工研判）\n")
        for f in low_conf:
            lines.append(f"- **{f['entity_name']}** ({f['market']} {f['code']})")
            lines.append(f"  - 数据来源: {', '.join(f['sources'])}")
            lines.append(f"  - 资本运作: {f['capital_operation']}")
            lines.append("")
    
    lines.append("\n---\n*注：高置信度=3+数据源交叉验证，中置信度=2数据源，低置信度=单一数据源*\n")
    
    return lines


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='跨市场关联发现')
    parser.add_argument('--stock', default='002180', help='股票代码')
    parser.add_argument('--market', default='a', help='市场 (a/hk/us)')
    parser.add_argument('--data-dir', help='数据目录')
    
    args = parser.parse_args()
    
    if not args.data_dir:
        import glob
        dirs = glob.glob(f'output/{args.stock}_*')
        if dirs:
            # 按修改时间排序，取最新的
            dirs.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            args.data_dir = dirs[0] + '/data'
            print(f'使用数据目录: {args.data_dir}')
        else:
            print(f"未找到 {args.stock} 的数据目录")
            sys.exit(1)
    
    discovery = CrossMarketDiscovery(args.stock, args.market, args.data_dir)
    discovery.load_data()
    results = discovery.discover()
    
    print("\n" + "="*60)
    print("最终发现:")
    for f in results.get('final_findings', []):
        print(f"  [{f['confidence']}] {f['entity_name'][:50]} → {f['market']} {f['code']}")
