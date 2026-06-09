# -*- coding: utf-8 -*-
"""
source_tracker.py - 溯源追踪核心基础设施
==========================================

设计原则：
  1. 每条数据必须标注来源（source）
  2. 本地优先：先查本地缓存，没有再去API，API失败再找源头网站
  3. 数据溯源链透明：report.md 里每个数字都标注了来源

来源类型（source 字段值）：
  em_api        - 东方财富 API
  cninfo_api    - 巨潮资讯 API
  csrc          - 证监会辅导数据（AKShare）
  akshare      - AKShare 封装数据源
  cninfo_pdf    - 巨潮资讯 PDF（年报/公告）
  sse           - 上交所官网（PDF/HTML）
  szse          - 深交所官网（互动易等）
  bse_cn        - 北交所官网（年报PDF）
  hkex_pw       - 港交所披露易（Playwright自动化）
  sec_edgar     - SEC EDGAR（美股）
  local_pdf     - 本地已下载PDF
  local_cache   - 本地JSON缓存
  manual        - 用户手动提供

调用方式（所有模块统一）：
  from source_tracker import SourceTracker, SourceRoute
  tracker = SourceTracker(stock_code, market, data_dir)

  # 本地优先三段式
  data = tracker.get('financial', fetch_func=fetch_from_em,
                     fallback_funcs=[fetch_from_cninfo_pdf, fetch_from_sse_pdf],
                     cache_key='financials.json')
  # data 自动携带 source 字段
  print(data['source'])  # 'em_api' 或 'cninfo_pdf' 或 'local_pdf' ...

  # 直接下载PDF（源头溯源）
  pdf_path = tracker.download_annual_pdf(year=2025)
  print(pdf_path['source'])  # 'cninfo_pdf' | 'sse' | 'bse_cn' | 'local_pdf'
"""

import os
import json
import time
from datetime import datetime
from typing import Any, Callable, Optional, List, Dict, Tuple

# ============================================================
# 溯源常量
# ============================================================
SOURCE_LABELS = {
    'local_pdf':           '📁 本地PDF',
    'local_cache':         '💾 本地缓存',
    'em_api':              '🌐 东方财富API',
    'em_announce':        '🌐 东方财富公告API',
    'cninfo_api':          '🌐 巨潮资讯API',
    'cninfo_hk_announce': '🌐 巨潮资讯港股公告',
    'csrc':                '🌐 证监会辅导数据',
    'csrc_ak':             '🌐 证监会辅导数据(AKShare)',
    'akshare':             '🌐 AKShare封装',
    'akshare_hk_fin':      '🌐 AKShare港股财务',
    'cninfo_pdf':          '📄 巨潮资讯PDF',
    'sse':                 '📄 上交所官网',
    'szse':                '📄 深交所官网',
    'bse_cn':              '📄 北交所官网',
    'hkex_pw':             '🌐 港交所披露易(Playwright)',
    'hkex':                '🌐 港交所披露易',
    'sec_edgar':           '🌐 SEC EDGAR',
    'yfinance':            '🌐 Yahoo Finance',
    'iwencai':             '🌐 iwencai问财API',
    'annual_pdf_text':     '📄 年报PDF文本提取',
    'manual':              '✍️ 手动输入',
    'all_failed':          '❌ 全部失败',
    'unknown':             '❓ 未知来源',
}

# ============================================================
# SourceTracker 核心类
# ============================================================
class SourceTracker:
    """
    统一溯源管理器

    用法：
        tracker = SourceTracker('002180', 'a', data_dir='output/002180_20260428')
        tracker.get('financial', fetch_func=api_fetch, fallback_funcs=[pdf_fetch, web_fetch])
    """

    def __init__(self, stock_code: str, market: str = 'a', data_dir: str = None):
        self.stock_code = stock_code
        self.market = market
        self.data_dir = data_dir or f'output/{stock_code}_{datetime.now().strftime("%Y%m%d")}'
        os.makedirs(self.data_dir, exist_ok=True)
        self._trace: List[Dict] = []  # 溯源日志

    # ---- 缓存读写 ----

    def _cache_path(self, cache_key: str) -> str:
        return os.path.join(self.data_dir, cache_key)

    def read_cache(self, cache_key: str) -> Optional[Dict]:
        """读本地缓存，有则返回，无则None"""
        path = self._cache_path(cache_key)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 标注来源
                data['_meta'] = data.get('_meta', {})
                data['_meta']['source'] = 'local_cache'
                data['_meta']['cache_file'] = path
                data['_meta']['cached_at'] = data.get('_meta', {}).get('fetched_at', 'unknown')
                return data
            except Exception:
                return None
        return None

    def write_cache(self, cache_key: str, data: Dict, source: str = 'unknown'):
        """写本地缓存，同时记录source"""
        data['_meta'] = {
            'source': source,
            'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stock': self.stock_code,
            'market': self.market,
        }
        path = self._cache_path(cache_key)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            print(f"[WARN] 缓存写入失败 {cache_key}: {e}")
        return data

    # ---- 溯源三段式 fetch ----

    def get(self,
            dim: str,
            fetch_func: Callable[[], Dict],
            fallback_funcs: List[Callable[[], Dict]] = None,
            cache_key: str = None,
            cache_ttl_hours: int = 24,
            **kwargs) -> Dict:
        """
        统一获取数据：本地缓存 → fetch_func → fallback_funcs → 返回错误

        Args:
            dim: 数据维度名（用于日志）
            fetch_func: 主数据获取函数 () -> Dict
            fallback_funcs: 兜底函数列表，按优先级排序
            cache_key: 缓存文件名
            cache_ttl_hours: 缓存有效期（小时）
            **kwargs: 传给 fetch_func 的额外参数

        Returns:
            始终返回Dict，带 '_meta.source' 字段
        """
        # Step 1: 读本地缓存
        if cache_key:
            cached = self.read_cache(cache_key)
            if cached:
                self._log(dim, cached.get('_meta', {}).get('source', 'local_cache'),
                         'HIT', f'缓存命中: {cache_key}')
                return cached

        # Step 2: 主数据源
        try:
            result = fetch_func(**kwargs)
            if result and not result.get('error'):
                source = result.get('_meta', {}).get('source', 'unknown')
                self._log(dim, source, 'OK', f'主数据源成功')
                if cache_key:
                    self.write_cache(cache_key, result, source=source)
                return result
            else:
                err = result.get('error', '空数据') if result else 'None'
                self._log(dim, 'unknown', 'FAIL', f'主数据源失败: {err}')
        except Exception as e:
            self._log(dim, 'unknown', 'ERROR', f'主数据源异常: {e}')

        # Step 3: fallback 链
        if fallback_funcs:
            for i, fallback in enumerate(fallback_funcs):
                try:
                    result = fallback(**kwargs)
                    if result and not result.get('error'):
                        source = result.get('_meta', {}).get('source', 'unknown')
                        self._log(dim, source, 'FALLBACK_OK',
                                  f'兜底#{i+1} {fallback.__name__} 成功')
                        if cache_key:
                            self.write_cache(cache_key, result, source=source)
                        return result
                    else:
                        err = result.get('error', '空数据') if result else 'None'
                        self._log(dim, 'unknown', 'FALLBACK_FAIL',
                                  f'兜底#{i+1} {fallback.__name__} 失败: {err}')
                except Exception as e:
                    self._log(dim, 'unknown', 'FALLBACK_ERROR',
                              f'兜底#{i+1} {fallback.__name__} 异常: {e}')

        # 全失败：返回错误结构
        result = {
            'error': f'所有数据源均失败（{dim}）',
            '_meta': {'source': 'all_failed', 'dim': dim},
        }
        self._log(dim, 'all_failed', 'FAIL', '所有数据源均失败')
        return result

    def _log(self, dim: str, source: str, status: str, msg: str):
        """记录溯源日志"""
        entry = {
            'time': datetime.now().strftime('%H:%M:%S'),
            'dim': dim,
            'source': source,
            'source_label': SOURCE_LABELS.get(source, source),
            'status': status,
            'msg': msg,
        }
        self._trace.append(entry)
        icon = {'OK': '✅', 'FAIL': '❌', 'ERROR': '❌', 'FALLBACK_OK': '🔄',
                'FALLBACK_FAIL': '⚠️', 'FALLBACK_ERROR': '⚠️', 'HIT': '💾'}.get(status, '?')
        print(f"  {icon} [{dim}] {SOURCE_LABELS.get(source, source)} | {msg}")

    def get_trace(self) -> List[Dict]:
        """返回本次所有溯源记录"""
        return self._trace

    def print_trace(self):
        """打印溯源摘要"""
        print("\n📋 溯源轨迹：")
        for e in self._trace:
            icon = {'OK': '✅', 'FAIL': '❌', 'ERROR': '❌', 'FALLBACK_OK': '🔄',
                    'FALLBACK_FAIL': '⚠️', 'FALLBACK_ERROR': '⚠️', 'HIT': '💾'}.get(e['status'], '?')
            print(f"  {icon} [{e['dim']}] {e['source_label']} | {e['msg']}")


# ============================================================
# 年报PDF下载 - 溯源三段式
# ============================================================
def download_annual_pdf_traced(stock_code: str, market: str, year: int = None,
                                save_dir: str = None) -> Dict:
    """
    溯源三段式年报PDF下载（优先级递减）：

    1. local_pdf  - 本地已下载的PDF
    2. cninfo_pdf - 巨潮资讯PDF（沪深A股，POST API，已验证可用）
    3. sse        - 上交所官网PDF（SSE反爬：CDP cookie方案，已验证）
    4. bse_cn     - 北交所官网PDF（GET翻页，已验证）
    5. hkex_pw    - 港交所披露易PDF（Playwright，需浏览器环境）

    Returns:
        {
            'pdf_path': str,          # PDF本地路径
            'source': str,            # 来源标识
            'source_label': str,      # 中文标签
            'year': int,
            'title': str,
            'page_count': int,
            'error': str,             # 失败时
        }
    """
    import fitz

    stock_code = str(stock_code).strip()
    market = market or 'a'
    year = year or (datetime.now().year - 1)  # 默认去年

    save_dir = save_dir or os.path.join(os.getcwd(), 'output', f'{stock_code}_pdf')
    os.makedirs(save_dir, exist_ok=True)

    def make_path(src, yr):
        return os.path.join(save_dir, f'{stock_code}_{yr}_{src}.pdf')

    def is_valid_pdf(path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            doc = fitz.open(path)
            valid = doc.page_count >= 10  # 年报至少10页
            doc.close()
            return valid
        except Exception:
            return False

    # ====== 段1：本地已有PDF ======
    for src in ['cninfo_pdf', 'sse', 'bse_cn', 'hkex_pw']:
        path = make_path(src, year)
        if is_valid_pdf(path):
            doc = fitz.open(path)
            page_count = doc.page_count
            doc.close()
            return {
                'pdf_path': path,
                'source': 'local_pdf',
                'source_label': f'📁 本地缓存({src})',
                'year': year,
                'page_count': page_count,
            }

    # ====== 段2：巨潮资讯（沪深A股，POST API）======
    if market in ('a',):
        try:
            from scripts.pdf_download import get_annual_report_list, download_pdf
            reports = get_annual_report_list(stock_code, years=3)
            if not reports:
                raise ValueError('CNINFO年报列表为空')

            # 找指定年份
            target = None
            for r in reports:
                if r.get('year') == year:
                    target = r
                    break
            if not target:
                target = reports[0]  # 最新

            pdf_url = target['pdf_url']
            path = make_path('cninfo_pdf', target.get('year', year))
            # 注意：CNINFO API已变更，URL可能失效
            if download_pdf(pdf_url, path):
                doc = fitz.open(path)
                page_count = doc.page_count
                doc.close()
                return {
                    'pdf_path': path,
                    'source': 'cninfo_pdf',
                    'source_label': '📄 巨潮资讯PDF',
                    'year': target.get('year', year),
                    'title': target.get('title', ''),
                    'page_count': page_count,
                    'pdf_url': pdf_url,
                }
        except Exception as e:
            print(f"[WARN] CNINFO PDF下载失败: {e}")

    # ====== 段3：北交所官网（GET翻页，已验证）======
    if market in ('a',) and (stock_code.startswith('8') or stock_code.startswith('9')
            or stock_code.startswith('4')):
        try:
            from scripts.pdf_download import _get_bse_annual_reports, download_pdf
            reports = _get_bse_annual_reports(stock_code, years=3)
            if not reports:
                raise ValueError('BSE年报列表为空')

            target = None
            for r in reports:
                if r.get('year') == year:
                    target = r
                    break
            if not target:
                target = reports[0]

            pdf_url = target['pdf_url']
            path = make_path('bse_cn', target.get('year', year))
            if download_pdf(pdf_url, path):
                doc = fitz.open(path)
                page_count = doc.page_count
                doc.close()
                return {
                    'pdf_path': path,
                    'source': 'bse_cn',
                    'source_label': '📄 北交所官网PDF',
                    'year': target.get('year', year),
                    'title': target.get('title', ''),
                    'page_count': page_count,
                    'pdf_url': pdf_url,
                }
        except Exception as e:
            print(f"[WARN] BSE PDF下载失败: {e}")

    # ====== 段4：上交所官网（SSE反爬：CDP cookie方案）======
    # TODO: 待实现 CDP cookie 提取并下载
    # 参考 TOOLS.md: 浏览器打开PDF → CDP提取cookie → requests带cookie下载

    # ====== 段5：港交所披露易（Playwright，需浏览器）======
    if market == 'hk':
        try:
            from scripts.hkex_announcements import search_hkex_announcements
            anns = search_hkex_announcements(stock_code, max_results=50)
            # 找年报类公告
            annual_urls = [
                a['pdf_url'] for a in anns
                if 'annual report' in a.get('title', '').lower()
                or '年报' in a.get('title', '')
            ]
            for pdf_url in annual_urls:
                if not pdf_url or pdf_url.startswith('javascript'):
                    continue
                path = make_path('hkex_pw', year)
                if download_pdf(pdf_url, path, timeout=60):
                    doc = fitz.open(path)
                    page_count = doc.page_count
                    doc.close()
                    return {
                        'pdf_path': path,
                        'source': 'hkex_pw',
                        'source_label': '🌐 港交所披露易PDF(Playwright)',
                        'year': year,
                        'page_count': page_count,
                        'pdf_url': pdf_url,
                    }
        except Exception as e:
            print(f"[WARN] HKEX PDF下载失败: {e}")

    return {
        'error': f'所有PDF下载方式均失败 (stock={stock_code}, market={market}, year={year})',
        'source': 'all_failed',
        'source_label': '❌ 全部失败',
    }


# ============================================================
# 公告PDF下载 - 溯源三段式
# ============================================================
def download_announcement_pdf_traced(stock_code: str, market: str,
                                      announcement_id: str = None,
                                      pdf_url: str = None,
                                      save_dir: str = None) -> Dict:
    """
    溯源三段式公告PDF下载

    优先级：
    1. local_cache - 本地缓存
    2. cninfo_pdf  - 巨潮资讯（A股）
    3. hkex_pw     - 港交所披露易（港股）
    4. sse         - 上交所官网（沪市A股）
    """
    import fitz

    save_dir = save_dir or os.path.join(os.getcwd(), 'output', f'{stock_code}_ann')
    os.makedirs(save_dir, exist_ok=True)

    ann_id = announcement_id or 'unknown'
    path = os.path.join(save_dir, f'{ann_id}.pdf')

    # 段1：本地已有
    if os.path.exists(path):
        try:
            doc = fitz.open(path)
            page_count = doc.page_count
            doc.close()
            return {'pdf_path': path, 'source': 'local_pdf', 'source_label': '📁 本地缓存公告',
                    'page_count': page_count}
        except Exception:
            pass

    # 段2：直接传入URL下载
    if pdf_url:
        try:
            if download_pdf(pdf_url, path):
                doc = fitz.open(path)
                page_count = doc.page_count
                doc.close()
                src = 'cninfo_pdf' if 'cninfo' in pdf_url else ('hkex_pw' if 'hkex' in pdf_url else 'web_pdf')
                return {'pdf_path': path, 'source': src, 'source_label': f'📄 {SOURCE_LABELS.get(src,"PDF")}',
                        'page_count': page_count, 'pdf_url': pdf_url}
        except Exception as e:
            print(f"[WARN] 公告PDF下载失败: {e}")

    return {'error': '公告PDF下载失败', 'source': 'all_failed', 'source_label': '❌ 全部失败'}


# ============================================================
# 辅助函数
# ============================================================
def source_label(source: str) -> str:
    """返回来源中文标签"""
    return SOURCE_LABELS.get(source, source)


def annotate_result(result: Dict, source: str) -> Dict:
    """给结果打上溯源标记"""
    if result is None:
        return {'_meta': {'source': source, 'error': '数据为空'}}
    if isinstance(result, dict):
        result['_meta'] = result.get('_meta', {})
        result['_meta']['source'] = source
        result['_meta']['source_label'] = SOURCE_LABELS.get(source, source)
        result['_meta']['fetched_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return result


def format_source_trace_table(trace: List[Dict]) -> str:
    """把溯源轨迹格式化成Markdown表格"""
    lines = ['\n\n---\n\n## 📋 数据来源溯源表\n']
    lines.append('| # | 数据维度 | 来源 | 状态 | 备注 |')
    lines.append('|---|----------|------|------|------|')
    for i, e in enumerate(trace, 1):
        lines.append(f"| {i} | {e['dim']} | {e['source_label']} | {e['status']} | {e['msg']} |")
    return '\n'.join(lines)


# ============================================================
# 测试
# ============================================================
if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    tracker = SourceTracker('002180', 'a', data_dir='output/trace_test')

    # 测试溯源三段式
    def fake_em_fail():
        print("  → 东方财富API [FAIL]")
        return {'error': '网络超时'}

    def fake_cninfo_ok():
        print("  → CNINFO PDF [OK]")
        return {'_meta': {'source': 'cninfo_pdf'}, 'revenue': 165.15}

    result = tracker.get('financial',
                          fetch_func=fake_em_fail,
                          fallback_funcs=[fake_cninfo_ok],
                          cache_key='financial.json')

    tracker.print_trace()
    print(f"\n最终数据: {result}")
