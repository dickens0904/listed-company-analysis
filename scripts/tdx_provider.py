# -*- coding: utf-8 -*-
"""
tdx_provider.py - 通达信(TDX)官方API统一数据供给模块
单例模式，使用通达信官方数据源

API地址: https://tdxhub.icfqs.com:7615/TQLEX
Token: 通过环境变量 TDX_API_TOKEN 配置

已验证可用接口（2026-06-03 实测）：
- company_info(code, info_type='basic')     → 公司基本信息（名称/行业/高管/股本等）
- share_structure(code, struct_type='gbjg') → 股本结构/股本变动/限售解禁
- trading_info(code, info_type='ztfx')       → 涨停分析/资金流向/龙虎榜等
- tdx_api_raw(entry, params)                → 原始API调用（高级用法）

单例用法：
    from scripts.tdx_provider import tdxp
    info = tdxp.company_info('600519')
    structure = tdxp.share_structure('600519')
    trading = tdxp.trading_info('600519', 'zjlx')  # 资金流向
"""
import sys, os, time, json, re
from datetime import datetime, timedelta
from pathlib import Path
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# 缓存目录（使用 skill 目录下的本地缓存，避免 sandbox 限制）
_SCRIPT_DIR = Path(__file__).parent
_CACHE_DIR = _SCRIPT_DIR / '.tdx_cache'
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# TDX API 配置
_TDX_API_ENDPOINT = "https://tdxhub.icfqs.com:7615/TQLEX"
_TDX_API_TOKEN = os.environ.get("TDX_API_TOKEN", "")


# ── 缓存工具 ───────────────────────────────────────────────────────────────────

def _load_cache(key: str, ttl_seconds: int):
    """读取缓存（TTL秒内有效）"""
    cache_file = _CACHE_DIR / f'{key}.json'
    if not cache_file.exists():
        return None
    try:
        if time.time() - cache_file.stat().st_mtime > ttl_seconds:
            return None
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(key: str, data):
    """保存缓存"""
    cache_file = _CACHE_DIR / f'{key}.json'
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception as _sexc:
        record(__name__, '_save_cache', _sexc, note='静默降级')
        pass


# ── API调用工具 ─────────────────────────────────────────────────────────────────

_last_call = 0


def _rate_limited():
    """频率限制：0.5秒间隔"""
    global _last_call
    now = time.time()
    wait = 0.5 - (now - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _call_tdx_api(entry: str, params_list: list):
    """
    调用通达信API
    
    Args:
        entry: API入口，如 TdxSharePCCW.tdxf10_gg_gsgk
        params_list: 参数列表，如 ['0', '600519', '']
    
    Returns:
        API返回的JSON数据，失败返回None
    """
    import requests
    
    _rate_limited()
    
    headers = {
        "Content-Type": "application/json",
        "token": _TDX_API_TOKEN
    }
    
    url = f"{_TDX_API_ENDPOINT}?Entry={entry}"
    body = {"Params": params_list}
    
    try:
        response = requests.post(url, json=body, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"  [TDX] API调用失败: {e}", file=sys.stderr)
        return None


def _parse_result_sets(data):
    """
    解析通达信返回的ResultSets格式
    
    返回格式示例：
    {
        "ErrorCode": 0,
        "ResultSets": [
            {
                "Count": 1,
                "ColName": ["N001", "N002", ...],
                "Content": [[value1, value2, ...]]
            }
        ]
    }
    """
    if not data or data.get("ErrorCode") != 0:
        return None
    
    result_sets = data.get("ResultSets", [])
    if not result_sets:
        return None
    
    parsed = []
    for rs in result_sets:
        col_names = rs.get("ColName", [])
        contents = rs.get("Content", [])
        
        for row in contents:
            item = {}
            for i, col in enumerate(col_names):
                if i < len(row):
                    item[str(col)] = row[i]
            parsed.append(item)
    
    return parsed


# ── 主要接口 ───────────────────────────────────────────────────────────────────

class TdxProvider:
    """通达信数据供给类（单例模式）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ── 1. 公司基本信息 ─────────────────────────────────────────────────────

    def company_info(self, code: str, info_type: str = 'basic'):
        """
        获取公司信息
        
        Args:
            code: 股票代码（6位数字）
            info_type: 信息类型
                - 'basic': 基本信息（公司概况）
                - 'affiliates': 参股控股公司
                - 'employee': 员工构成
                - 'employee_efficiency': 员工效益
                - 'issuance': 发行与交易
                - 'executives': 董监高信息
        
        Returns:
            dict，包含success字段和具体数据
        """
        cache_key = f'company_{code}_{info_type}'
        cached = _load_cache(cache_key, 86400)  # 24小时缓存
        if cached:
            return cached
        
        fixed_tag_map = {
            'basic': '0',
            'affiliates': '3',
            'employee': '4',
            'employee_efficiency': '5',
            'issuance': '8',
            'executives': '20',
        }
        
        fixed_tag = fixed_tag_map.get(info_type, '0')
        result = _call_tdx_api("TdxSharePCCW.tdxf10_gg_gsgk", [fixed_tag, code, ""])
        
        if result is None:
            return {'success': False, 'error': 'API调用失败'}
        
        parsed = _parse_result_sets(result)
        if parsed is None:
            return {'success': False, 'error': '解析失败'}
        
        # 整理基本信息
        formatted = {
            'success': True,
            'info_type': info_type,
            'code': code,
            'data': parsed,
            'source': 'tdx'
        }
        
        # 如果是基本信息，提取关键字段
        if info_type == 'basic' and len(parsed) > 0:
            first = parsed[0]
            formatted['company_name'] = first.get('T003', '')
            formatted['region'] = first.get('T038', '')
            formatted['english_name'] = first.get('T006', '')
            formatted['website'] = first.get('url', '')
            formatted['industry'] = first.get('yjhy', '')
            formatted['unified_code'] = first.get('shxydm', '')
            formatted['main_business'] = first.get('T017', '')
            formatted['product_name'] = first.get('cpmc', '')
            formatted['controlling_shareholder'] = first.get('T036', '')
            formatted['legal_representative'] = first.get('T008', '')
            formatted['general_manager'] = first.get('T030', '')
            formatted['board_secretary'] = first.get('T023', '')
            formatted['chairman'] = first.get('dsz', '')
            formatted['registered_capital'] = first.get('T010', '')
            formatted['employee_count'] = first.get('ygzs', '')
            formatted['phone'] = first.get('T024', '')
            formatted['email'] = first.get('T026', '')
            formatted['auditor'] = first.get('T028', '')
            formatted['lawyer'] = first.get('T029', '')
            formatted['registered_address'] = first.get('T009', '')
            formatted['office_address'] = first.get('T012', '')
            formatted['company_intro'] = first.get('T019', '')
            formatted['business_scope'] = first.get('T018', '')
        
        _save_cache(cache_key, formatted)
        return formatted

    # ── 2. 股本结构信息 ─────────────────────────────────────────────────────

    def share_structure(self, code: str, struct_type: str = 'gbjg'):
        """
        获取股本结构
        
        Args:
            code: 股票代码
            struct_type: 结构类型
                - 'gbjg': 股本结构
                - 'gbbd': 股本变动
                - 'xslt': 限售解禁
        
        Returns:
            dict，包含success字段和具体数据
        """
        cache_key = f'structure_{code}_{struct_type}'
        cached = _load_cache(cache_key, 86400)  # 24小时缓存
        if cached:
            return cached
        
        result = _call_tdx_api("TdxSharePCCW.tdxf10_gg_gbjg", [code, struct_type])
        
        if result is None:
            return {'success': False, 'error': 'API调用失败'}
        
        parsed = _parse_result_sets(result)
        if parsed is None:
            return {'success': False, 'error': '解析失败'}
        
        formatted = {
            'success': True,
            'struct_type': struct_type,
            'code': code,
            'data': parsed,
            'source': 'tdx'
        }
        
        _save_cache(cache_key, formatted)
        return formatted

    # ── 3. 交易相关信息 ─────────────────────────────────────────────────────

    def trading_info(self, code: str, info_type: str = 'ztfx'):
        """
        获取交易相关信息
        
        Args:
            code: 股票代码
            info_type: 信息类型
                - 'ztfx': 涨停分析
                - 'zjlx': 资金流向
                - 'jglhb': 龙虎榜
                - 'zttzbkz': 热点题材板块族谱
                - 'sjcd': 事件驱动
        
        Returns:
            dict，包含success字段和具体数据
        """
        cache_key = f'trading_{code}_{info_type}'
        cached = _load_cache(cache_key, 7200)  # 2小时缓存
        if cached:
            return cached
        
        result = _call_tdx_api("TdxSharePCCW.tdxf10_gg_jyds", [code, info_type])
        
        if result is None:
            return {'success': False, 'error': 'API调用失败'}
        
        parsed = _parse_result_sets(result)
        if parsed is None:
            return {'success': False, 'error': '解析失败'}
        
        formatted = {
            'success': True,
            'info_type': info_type,
            'code': code,
            'data': parsed,
            'source': 'tdx'
        }
        
        _save_cache(cache_key, formatted)
        return formatted

    # ── 4. 原始API调用（高级用法） ───────────────────────────────────────────

    def tdx_api_raw(self, entry: str, params_list: list):
        """
        直接调用通达信API（高级用法）
        
        Args:
            entry: API入口
            params_list: 参数列表
        
        Returns:
            解析后的ResultSets数据
        """
        cache_key = f'raw_{entry}_{"_".join([str(p) for p in params_list])}'
        cached = _load_cache(cache_key, 7200)
        if cached:
            return cached
        
        result = _call_tdx_api(entry, params_list)
        
        if result is None:
            return {'success': False, 'error': 'API调用失败'}
        
        parsed = _parse_result_sets(result)
        if parsed is None:
            return {'success': False, 'error': '解析失败'}
        
        formatted = {
            'success': True,
            'entry': entry,
            'params': params_list,
            'data': parsed,
            'source': 'tdx'
        }
        
        _save_cache(cache_key, formatted)
        return formatted

    # ── 5. 综合信息获取 ─────────────────────────────────────────────────────

    def get_company_overview(self, code: str):
        """
        获取公司综合信息（多个API合并）
        
        Args:
            code: 股票代码
        
        Returns:
            dict，包含基本信息、股本结构、高管信息等
        """
        cache_key = f'overview_{code}'
        cached = _load_cache(cache_key, 86400)
        if cached:
            return cached
        
        result = {
            'success': True,
            'code': code,
            'source': 'tdx',
            'basic': self.company_info(code, 'basic'),
            'executives': self.company_info(code, 'executives'),
            'share_structure': self.share_structure(code, 'gbjg'),
            'capital_change': self.share_structure(code, 'gbbd'),
            'unlock_schedule': self.share_structure(code, 'xslt'),
        }
        
        _save_cache(cache_key, result)
        return result

    # ── 6. 数据增强：将通达信数据注入现有分析模块 ──────────────

    def enhance_with_tdx_data(self, code: str, existing_findings: dict = None) -> dict:
        """
        获取并组织通达信数据，作为增强数据源注入到现有分析模块中
        
        Args:
            code: 股票代码
            existing_findings: 现有分析结果（用于检查是否需要补充）
        
        Returns:
            dict, 包含以下字段：
                - basic_enhanced: 公司基本信息增强
                - product_structure: 产品构成
                - executives_enhanced: 高管信息增强
                - structure_enhanced: 股本结构增强
                - raw_data: 原始通达信数据（用于报告展示）
        """
        result = {
            'success': True,
            'source': 'tdx',
            'code': code,
            'basic_enhanced': {},
            'product_structure': [],
            'executives_enhanced': [],
            'structure_enhanced': {},
            'raw_data': {},
        }

        try:
            # 获取基本信息
            basic = self.company_info(code, 'basic')
            if basic.get('success'):
                result['basic_enhanced'] = self._extract_basic_summary(basic)
                result['product_structure'] = self._extract_product_structure(basic)
                result['raw_data']['basic'] = basic

            # 获取高管信息
            executives = self.company_info(code, 'executives')
            if executives.get('success'):
                result['executives_enhanced'] = self._extract_executives_summary(executives)
                result['raw_data']['executives'] = executives

            # 获取股本结构
            structure = self.share_structure(code, 'gbjg')
            if structure.get('success'):
                result['structure_enhanced'] = self._extract_share_structure_summary(structure)
                result['raw_data']['share_structure'] = structure

        except Exception as e:
            print(f"  [TDX] 数据增强失败: {e}", file=sys.stderr)
            result['success'] = False
            result['error'] = str(e)

        return result

    # ── 内部辅助：提取公司基本信息摘要 ──────────────────────────

    def _extract_basic_summary(self, basic_data: dict) -> dict:
        """从基本信息中提取关键摘要"""
        summary = {}
        data = basic_data.get('data', [])
        if not data or len(data) == 0:
            return summary

        first = data[0]

        # 提取公司基本信息
        summary['company_name'] = basic_data.get('company_name', first.get('T003', ''))
        summary['industry'] = basic_data.get('industry', first.get('yjhy', ''))
        summary['region'] = basic_data.get('region', first.get('T038', ''))
        summary['english_name'] = basic_data.get('english_name', first.get('T006', ''))
        summary['website'] = basic_data.get('website', first.get('url', ''))
        summary['unified_code'] = basic_data.get('unified_code', first.get('shxydm', ''))

        # 提取核心人员
        summary['chairman'] = basic_data.get('chairman', first.get('dsz', ''))
        summary['general_manager'] = basic_data.get('general_manager', first.get('T030', ''))
        summary['board_secretary'] = basic_data.get('board_secretary', first.get('T023', ''))
        summary['legal_representative'] = basic_data.get('legal_representative', first.get('T008', ''))
        summary['controlling_shareholder'] = basic_data.get('controlling_shareholder', first.get('T036', ''))

        # 提取基本指标
        summary['registered_capital'] = basic_data.get('registered_capital', first.get('T010', ''))
        summary['employee_count'] = basic_data.get('employee_count', first.get('ygzs', ''))
        summary['main_business'] = basic_data.get('main_business', first.get('T017', ''))
        summary['company_intro'] = basic_data.get('company_intro', first.get('T019', ''))

        # 提取审计和法律信息
        summary['auditor'] = basic_data.get('auditor', first.get('T028', ''))
        summary['lawyer'] = basic_data.get('lawyer', first.get('T029', ''))

        # 提取联系方式和地址
        summary['phone'] = basic_data.get('phone', first.get('T024', ''))
        summary['email'] = basic_data.get('email', first.get('T026', ''))
        summary['registered_address'] = basic_data.get('registered_address', first.get('T009', ''))
        summary['office_address'] = basic_data.get('office_address', first.get('T012', ''))

        return summary

    # ── 内部辅助：提取产品构成 ─────────────────────────────

    def _extract_product_structure(self, basic_data: dict) -> list:
        """从基本信息中提取产品构成"""
        products = []
        data = basic_data.get('data', [])

        # 产品构成数据在 data 数组的后续记录中（从第2项开始）
        # 格式: {T003: 2, N002: "产品名称", N004: 占比, N008: 对比占比}
        for item in data[1:]:  # 跳过第一项（公司基本信息）
            if item.get('T003') == 2 or item.get('N002'):
                product = {
                    'name': item.get('N002', ''),
                    'revenue_ratio': item.get('N004'),
                    'compare_ratio': item.get('N008'),
                }
                if product['name'] and product['revenue_ratio'] is not None:
                    products.append(product)

        return products

    # ── 内部辅助：提取高管摘要 ─────────────────────────────

    def _extract_executives_summary(self, executives_data: dict) -> list:
        """从高管数据中提取结构化摘要"""
        executives = []
        data = executives_data.get('data', [])

        for item in data:
            # 跳过统计行（只有 T003 和 zs 字段的）
            if 'T002' not in item:
                continue

            exec_item = {
                'name': item.get('T002', ''),
                'position': item.get('T015', ''),
                'start_date': item.get('T005', '').split(' ')[0] if item.get('T005') else '',
                'gender': item.get('T006', ''),
                'education': item.get('T008', ''),
                'age': item.get('nncj', ''),
                'salary': item.get('T010', ''),
                'shares_held': item.get('T011', ''),
                'shares_held_total': item.get('T012', ''),
                'record_id': item.get('rec_id', ''),
                'category_code': item.get('T003', ''),
            }

            # 过滤掉空记录
            if exec_item['name']:
                executives.append(exec_item)

        return executives

    # ── 内部辅助：提取股本结构摘要 ─────────────────────────

    def _extract_share_structure_summary(self, structure_data: dict) -> dict:
        """从股本结构数据中提取摘要"""
        summary = {
            'latest': {},
            'history': [],
        }
        data = structure_data.get('data', [])

        # 提取最新一期数据
        if data and len(data) > 0:
            latest = data[0]  # 第一条通常是最新的
            summary['latest'] = {
                'date': latest.get('T002', ''),
                'total_shares': latest.get('T003', ''),
                'tradable_shares': latest.get('T004', ''),
                'non_tradable_shares': latest.get('T005', ''),
                'total_shares_field9': latest.get('T009', ''),
                'total_shares_field10': latest.get('T010', ''),
                'total_shares_field11': latest.get('T011', ''),
                'field19': latest.get('T019', ''),
                'field10_n': latest.get('N010', ''),
            }

            # 提取历史记录（前5期）
            for item in data[:5]:
                history_item = {
                    'date': item.get('T002', ''),
                    'total_shares': item.get('T003', ''),
                    'tradable_shares': item.get('T004', ''),
                    'non_tradable_shares': item.get('T005', ''),
                }
                if history_item['date'] and history_item['total_shares']:
                    summary['history'].append(history_item)

        return summary


# ── 全局单例 ───────────────────────────────────────────────────────────────────

tdxp = TdxProvider()


# ── 简化函数接口 ───────────────────────────────────────────────────────────────

def get_company_info(code: str, info_type: str = 'basic'):
    """获取公司信息（简化接口）"""
    return tdxp.company_info(code, info_type)


def get_share_structure(code: str, struct_type: str = 'gbjg'):
    """获取股本结构（简化接口）"""
    return tdxp.share_structure(code, struct_type)


def get_trading_info(code: str, info_type: str = 'ztfx'):
    """获取交易信息（简化接口）"""
    return tdxp.trading_info(code, info_type)


def get_company_overview(code: str):
    """获取公司综合信息（简化接口）"""
    return tdxp.get_company_overview(code)


# ── 数据增强统一接口 ──────────────────────────────────────────────────────────

def enhance_with_tdx_data(code: str, existing_findings: dict = None) -> dict:
    """获取通达信数据并组织为增强格式（简化接口）"""
    return tdxp.enhance_with_tdx_data(code, existing_findings)


# ── 报告生成：通达信数据章节 ──────────────────────────────────────────────

def generate_report_section(tdx_data: dict) -> list:
    """
    生成通达信数据的报告章节（Markdown格式）
    
    Args:
        tdx_data: enhance_with_tdx_data 返回的数据结构
    
    Returns:
        list of str, 每一项是一行 Markdown 文本
    """
    lines = []

    if not tdx_data or not tdx_data.get('success'):
        return lines

    # 标题
    lines.append('## 🏢 公司基础信息（通达信）')
    lines.append('')

    # ── 公司基本信息 ────────────────────────────────────
    basic = tdx_data.get('basic_enhanced', {})
    if basic:
        lines.append('### 公司概况')
        lines.append('')
        company_name = basic.get('company_name', '')
        if company_name:
            lines.append(f'**公司名称**：{company_name}')

        industry = basic.get('industry', '')
        if industry:
            lines.append(f'**所属行业**：{industry}')

        region = basic.get('region', '')
        if region:
            lines.append(f'**所在地区**：{region}')

        english_name = basic.get('english_name', '')
        if english_name:
            lines.append(f'**英文名称**：{english_name}')

        website = basic.get('website', '')
        if website:
            lines.append(f'**公司网址**：{website}')

        unified_code = basic.get('unified_code', '')
        if unified_code:
            lines.append(f'**统一社会信用代码**：{unified_code}')

        registered_capital = basic.get('registered_capital', '')
        if registered_capital:
            lines.append(f'**注册资本**：{registered_capital} 万元')

        employee_count = basic.get('employee_count', '')
        if employee_count:
            lines.append(f'**员工人数**：{employee_count} 人')

        chairman = basic.get('chairman', '')
        if chairman:
            lines.append(f'**董事长**：{chairman}')

        general_manager = basic.get('general_manager', '')
        if general_manager:
            lines.append(f'**总经理**：{general_manager}')

        board_secretary = basic.get('board_secretary', '')
        if board_secretary:
            lines.append(f'**董事会秘书**：{board_secretary}')

        controlling_shareholder = basic.get('controlling_shareholder', '')
        if controlling_shareholder:
            lines.append(f'**控股股东**：{controlling_shareholder}')

        phone = basic.get('phone', '')
        if phone:
            lines.append(f'**联系电话**：{phone}')

        email = basic.get('email', '')
        if email:
            lines.append(f'**电子邮箱**：{email}')

        office_address = basic.get('office_address', '')
        if office_address:
            lines.append(f'**办公地址**：{office_address}')

        auditor = basic.get('auditor', '')
        if auditor:
            lines.append(f'**会计师事务所**：{auditor}')

        lawyer = basic.get('lawyer', '')
        if lawyer:
            lines.append(f'**律师事务所**：{lawyer}')

        main_business = basic.get('main_business', '')
        if main_business:
            lines.append(f'**主营业务**：{main_business}')

        company_intro = basic.get('company_intro', '')
        if company_intro and len(company_intro) > 10:
            lines.append('')
            lines.append('**公司简介**：')
            lines.append('')
            lines.append(f'> {company_intro}')

        lines.append('')

    # ── 产品构成 ─────────────────────────────────────
    products = tdx_data.get('product_structure', [])
    if products and len(products) > 0:
        lines.append('### 产品构成（按收入占比）')
        lines.append('')
        lines.append('| 产品 | 收入占比 | 对比占比 |')
        lines.append('|------|---------|---------|')
        for product in products:
            name = product.get('name', '')
            ratio = product.get('revenue_ratio', '')
            compare = product.get('compare_ratio', '')

            ratio_str = f'{ratio * 100:.2f}%' if isinstance(ratio, (int, float)) else str(ratio)
            compare_str = f'{compare * 100:.2f}%' if isinstance(compare, (int, float)) else str(compare) if compare else '-'

            lines.append(f'| {name} | {ratio_str} | {compare_str} |')
        lines.append('')

    # ── 高管信息 ──────────────────────────────────────
    executives = tdx_data.get('executives_enhanced', [])
    if executives and len(executives) > 0:
        lines.append('### 核心管理团队')
        lines.append('')
        lines.append('| 姓名 | 职务 | 任职日期 | 性别 | 学历 | 年龄 | 薪酬(万元) | 持股(股) |')
        lines.append('|------|------|---------|------|------|------|-----------|---------|')

        for exec_item in executives[:15]:  # 最多显示15位
            name = exec_item.get('name', '')
            position = exec_item.get('position', '')
            start_date = exec_item.get('start_date', '')
            gender = exec_item.get('gender', '')
            education = exec_item.get('education', '')
            age = exec_item.get('age', '')
            salary = exec_item.get('salary', '')
            shares = exec_item.get('shares_held_total', '')

            salary_str = str(salary) if salary not in ['', None] else '-'
            shares_str = str(shares) if shares not in ['', None] else '-'

            lines.append(f'| {name} | {position} | {start_date} | {gender} | {education} | {age} | {salary_str} | {shares_str} |')

        if len(executives) > 15:
            lines.append(f'| 其他 {len(executives) - 15} 人 | ... | ... | ... | ... | ... | ... | ... |')

        lines.append('')

    # ── 股本结构 ─────────────────────────────────────
    structure = tdx_data.get('structure_enhanced', {})
    if structure and structure.get('latest'):
        latest = structure.get('latest', {})
        history = structure.get('history', [])

        lines.append('### 股本结构')
        lines.append('')

        latest_date = latest.get('date', '')
        total_shares = latest.get('total_shares', '')
        tradable = latest.get('tradable_shares', '')
        non_tradable = latest.get('non_tradable_shares', '')

        lines.append(f'**最新数据日期**：{latest_date}')
        if total_shares:
            total_str = f'{total_shares:,}' if isinstance(total_shares, (int, float)) else str(total_shares)
            lines.append(f'**总股本**：{total_str} 股')

        if tradable:
            tradable_str = f'{tradable:,}' if isinstance(tradable, (int, float)) else str(tradable)
            lines.append(f'**流通股**：{tradable_str} 股')

        if non_tradable:
            non_tradable_str = f'{non_tradable:,}' if isinstance(non_tradable, (int, float)) else str(non_tradable)
            lines.append(f'**限售股**：{non_tradable_str} 股')

        lines.append('')

        # 历史变化趋势
        if history and len(history) > 1:
            lines.append('**近期股本变化**：')
            lines.append('')
            lines.append('| 日期 | 总股本 | 流通股 | 限售股 |')
            lines.append('|------|--------|--------|--------|')

            for item in history:
                date = item.get('date', '')
                total = item.get('total_shares', '')
                trad = item.get('tradable_shares', '')
                non_trad = item.get('non_tradable_shares', '')

                total_s = f'{total:,}' if isinstance(total, (int, float)) else str(total)
                trad_s = f'{trad:,}' if isinstance(trad, (int, float)) else str(trad)
                non_trad_s = f'{non_trad:,}' if isinstance(non_trad, (int, float)) else str(non_trad)

                lines.append(f'| {date} | {total_s} | {trad_s} | {non_trad_s} |')

            lines.append('')

    # 数据来源说明
    lines.append('---')
    lines.append('')
    lines.append('*数据来源：通达信官方数据接口（TDX API）*')
    lines.append('')

    return lines


# ── AI分析证据构建 ─────────────────────────────────────────────────────

def build_evidence_for_ai(tdx_data: dict) -> str:
    """
    将通达信数据构建为 AI 分析可用的证据文本
    
    Args:
        tdx_data: enhance_with_tdx_data 返回的数据结构
    
    Returns:
        str, 格式化的证据文本
    """
    if not tdx_data or not tdx_data.get('success'):
        return ''

    sections = []

    # 公司基本信息
    basic = tdx_data.get('basic_enhanced', {})
    if basic:
        basic_lines = []
        basic_lines.append('【公司基础信息 - 来源：通达信】')

        company_name = basic.get('company_name', '')
        if company_name:
            basic_lines.append(f'公司名称：{company_name}')

        industry = basic.get('industry', '')
        if industry:
            basic_lines.append(f'所属行业：{industry}')

        region = basic.get('region', '')
        if region:
            basic_lines.append(f'所在地区：{region}')

        registered_capital = basic.get('registered_capital', '')
        if registered_capital:
            basic_lines.append(f'注册资本：{registered_capital} 万元')

        employee_count = basic.get('employee_count', '')
        if employee_count:
            basic_lines.append(f'员工人数：{employee_count} 人')

        chairman = basic.get('chairman', '')
        if chairman:
            basic_lines.append(f'董事长：{chairman}')

        general_manager = basic.get('general_manager', '')
        if general_manager:
            basic_lines.append(f'总经理：{general_manager}')

        controlling_shareholder = basic.get('controlling_shareholder', '')
        if controlling_shareholder:
            basic_lines.append(f'控股股东/实际控制人：{controlling_shareholder}')

        main_business = basic.get('main_business', '')
        if main_business:
            basic_lines.append(f'主营业务：{main_business}')

        company_intro = basic.get('company_intro', '')
        if company_intro and len(company_intro) > 10:
            basic_lines.append(f'公司简介：{company_intro[:200]}...' if len(company_intro) > 200 else f'公司简介：{company_intro}')

        sections.append('\n'.join(basic_lines))

    # 产品构成
    products = tdx_data.get('product_structure', [])
    if products and len(products) > 0:
        prod_lines = ['【产品构成分析 - 来源：通达信】']
        for product in products:
            name = product.get('name', '')
            ratio = product.get('revenue_ratio', '')

            ratio_str = f'{ratio * 100:.1f}%' if isinstance(ratio, (int, float)) else str(ratio)
            if name:
                prod_lines.append(f'- {name}：占比 {ratio_str}')

        sections.append('\n'.join(prod_lines))

    # 高管信息（摘要）
    executives = tdx_data.get('executives_enhanced', [])
    if executives and len(executives) > 0:
        exec_lines = ['【管理团队信息 - 来源：通达信】']
        exec_lines.append(f'核心管理团队共 {len(executives)} 人')

        # 统计高管基本信息
        total_salary = 0
        salary_count = 0
        for exec_item in executives[:10]:
            name = exec_item.get('name', '')
            position = exec_item.get('position', '')
            salary = exec_item.get('salary', '')

            if salary and isinstance(salary, (int, float)):
                total_salary += salary
                salary_count += 1

            salary_str = f'，薪酬{salary}万元' if salary not in ['', None] else ''
            if name and position:
                exec_lines.append(f'- {name}（{position}）{salary_str}')

        if salary_count > 0:
            avg_salary = total_salary / salary_count
            exec_lines.append(f'核心成员平均薪酬：{avg_salary:.2f}万元/年')

        sections.append('\n'.join(exec_lines))

    # 股本结构信息
    structure = tdx_data.get('structure_enhanced', {})
    if structure and structure.get('latest'):
        struct_lines = ['【股本结构数据 - 来源：通达信】']
        latest = structure.get('latest', {})

        date = latest.get('date', '')
        total_shares = latest.get('total_shares', '')
        tradable = latest.get('tradable_shares', '')

        if date:
            struct_lines.append(f'数据日期：{date}')
        if total_shares:
            struct_lines.append(f'总股本：{total_shares} 股')
        if tradable:
            struct_lines.append(f'流通股：{tradable} 股')

        sections.append('\n'.join(struct_lines))

    return '\n\n'.join(sections) if sections else ''


if __name__ == "__main__":
    """测试代码"""
    if len(sys.argv) < 2:
        print("用法: python tdx_provider.py <股票代码> [信息类型]")
        print("  信息类型: basic/affiliates/employee/issuance/executives")
        print("           gbjg/gbbd/xslt (股本结构)")
        print("           ztfx/zjlx/jglhb (交易信息)")
        print("           overview (综合信息)")
        sys.exit(1)
    
    code = sys.argv[1]
    info_type = sys.argv[2] if len(sys.argv) > 2 else 'basic'
    
    print(f"正在获取通达信数据: {code} ({info_type})...")
    
    if info_type == 'overview':
        result = get_company_overview(code)
    elif info_type in ['gbjg', 'gbbd', 'xslt']:
        result = get_share_structure(code, info_type)
    elif info_type in ['ztfx', 'zjlx', 'jglhb', 'zttzbkz', 'sjcd']:
        result = get_trading_info(code, info_type)
    else:
        result = get_company_info(code, info_type)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
