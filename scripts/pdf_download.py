# -*- coding: utf-8 -*-
"""
pdf_download.py - PDF 下载与提取模块
支持 CNINFO 年报PDF下载（沪深） + BSE年报PDF下载（北交所）
+ 上交所年报PDF下载（cookie反爬流程） + PyMuPDF 文本提取
"""
import os
import time
import re
import json
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result


# ================================================================
# 上交所（沪市）年报PDF下载 - JS反爬cookie流程
# 适用：6开头股票（沪市），深交所和北交所不受此保护
# 依赖：xbrowser（获取cookie）+ requests（带cookie下载）
# ================================================================

def _build_sse_annual_url(stock_code: str, year: int = None) -> str:
    """
    构建上交所年报PDF直链（无需JS渲染，直接构造URL）
    格式：https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/{YYYY-MM-DD}/{code}_{YYYYMMDD}_{id}.pdf
    """
    # 上交所公告按股票代码目录存放，文件名格式相对固定
    # 实际URL需从公告列表API获取，这里返回搜索页URL供xbrowser使用
    return f"https://www.sse.com.cn/disclosure/listedinfo/listing/"


def get_sse_annual_report_list(stock_code: str, years: int = 3) -> List[Dict]:
    """
    从上交所官网API获取年报列表（无需JS，直接请求）
    API: https://query.sse.com.cn/sseQuery/commonQuery.do
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.sse.com.cn/',
        'Accept': 'application/json, text/plain, */*',
    })
    
    api_url = 'https://query.sse.com.cn/sseQuery/commonQuery.do'
    params = {
        'jsonCallBack': '',
        'isPagination': 'false',
        'pageHelp.pageSize': '30',
        'pageHelp.pageNo': '1',
        'sqlId': 'COMMON_SSE_ZQPZ_GPLB_MCJS_SSGS_L',
        'COMPANY_CODE': stock_code,
        'report_type': '2',  # 年报
        'START_DATE': '',
        'END_DATE': '',
    }
    
    try:
        r = session.get(api_url, params=params, timeout=15)
        text = r.text
        # 去掉JSONP包装
        if text.startswith('('):
            text = text[1:]
        if text.endswith(')'):
            text = text[:-1]
        j = json.loads(text)
        result_list = j.get('result', []) or []
        
        reports = []
        for item in result_list:
            title = item.get('TITLE', '')
            if '年度报告' in title and '摘要' not in title:
                pub_date = item.get('PUBLISH_DATE', '')
                adj_url = item.get('ATTACHMENT_URL', '')
                if adj_url:
                    # 上交所PDF路径格式
                    if not adj_url.startswith('http'):
                        adj_url = 'https://static.sse.com.cn/' + adj_url.lstrip('/')
                    year_match = re.search(r'(\d{4})', pub_date)
                    yr = int(year_match.group(1)) if year_match else None
                    reports.append({
                        'year': yr,
                        'title': title,
                        'pdf_url': adj_url,
                        'date': pub_date[:10] if pub_date else '',
                    })
        
        reports.sort(key=lambda x: x['year'] or 0, reverse=True)
        return reports[:years]
    
    except Exception as e:
        print(f"[WARN] get_sse_annual_report_list: {e}")
        return []


def download_sse_pdf_with_cookie(pdf_url: str, save_path: str, cookie_value: str = None, timeout: int = 120) -> bool:
    """
    带cookie下载上交所年报PDF
    
    Args:
        pdf_url: 上交所PDF直链
        save_path: 保存路径
        cookie_value: acw_sc__v2=xxx cookie值（从xbrowser提取）
        timeout: 超时秒数
    
    Returns:
        是否成功
    """
    # 如果cookie_value为空，尝试不带cookie下载（有些PDF无反爬）
    cookies = {'acw_sc__v2': cookie_value} if cookie_value else {}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/pdf,*/*',
        'Referer': 'https://www.sse.com.cn/',
    }
    
    try:
        r = requests.get(pdf_url, headers=headers, cookies=cookies, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 10000:
            # 检查是否返回了混淆JS而非PDF
            if r.content[:4] != b'%PDF':
                print(f"[FAIL] 返回内容不是PDF（可能是JS反爬），需要xbrowser提取cookie")
                return False
            with open(save_path, 'wb') as f:
                f.write(r.content)
            print(f"[OK] 上交所PDF下载成功: {save_path} ({len(r.content)/1024/1024:.1f}MB)")
            return True
        else:
            print(f"[FAIL] 上交所PDF下载失败: status={r.status_code}, size={len(r.content)}")
            return False
    except Exception as e:
        print(f"[ERROR] download_sse_pdf_with_cookie: {e}")
        return False


# ================================================================
# 上交所年报PDF自动化流程（需配合xbrowser）
# 使用方法：
#   1. xbrowser打开PDF页面：xb open https://static.sse.com.cn/xxx.pdf
#   2. 提取cookie：xb act kind=evaluate fn:"() => document.cookie"
#   3. 运行此函数：python scripts/pdf_download.py --sse-download --url "..." --cookie "xxx" --out "..."
# ================================================================
def sse_pdf_workflow(pdf_url: str, cookie_value: str, save_path: str) -> Dict:
    """
    上交所年报PDF一键下载流程
    
    推荐使用xbrowser自动获取cookie：
        1. xb open {pdf_url}
        2. xb act kind=evaluate fn:"() => document.cookie"
        3. 使用返回值中的 acw_sc__v2=xxx 传入此函数
    
    Args:
        pdf_url: 上交所PDF完整URL
        cookie_value: acw_sc__v2=xxx
        save_path: 保存路径
    
    Returns:
        {'success': bool, 'pdf_path': str, 'page_count': int, 'error': str}
    """
    os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
    ok = download_sse_pdf_with_cookie(pdf_url, save_path, cookie_value)
    if not ok:
        return {'success': False, 'pdf_path': save_path, 'error': 'PDF下载失败（可能需cookie）'}
    
    try:
        import fitz
        doc = fitz.open(save_path)
        page_count = doc.page_count
        doc.close()
        return {'success': True, 'pdf_path': save_path, 'page_count': page_count}
    except Exception as e:
        return {'success': True, 'pdf_path': save_path, 'error': f'页数提取失败: {e}'}
import os
import re
import json
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime


# ============================================================
# BSE（北交所）年报下载
# ============================================================

def _is_bse_stock(stock_code: str) -> bool:
    """判断是否为北交所股票"""
    return stock_code.startswith('8') or stock_code.startswith('9')


def _get_bse_annual_from_em(stock_code: str, years: int = 3) -> List[Dict]:
    """从东方财富公告接口取北交所年报 PDF（2026-10-21 新增，替代失效的 BSE 官网翻页）。

    背景：BSE 官网 `initDisclosureList.do` 的 `companyCd` 被服务端忽略（实测无论传
    companyCd/companyCode/stockCode，返回的都是全市场 636 页，首条=别家公司），
    老代码翻 50 页也命中不了目标公司 → "未找到年报"。

    东财通道：`np-anotice-stock/api/security/ann?stock_list=<920xxx>` → art_code
    → `https://pdf.dfcfw.com/pdf/H2_<art_code>_1.pdf`（实测 200 / application/pdf）。

    🔴 只认 920xxx 段：调用方须先用 bse_migrate.resolve_bse_code() 迁码。
    """
    reports: List[Dict] = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    }
    try:
        r = requests.get(
            'https://np-anotice-stock.eastmoney.com/api/security/ann',
            params={'sr': -1, 'page_size': 100, 'page_index': 1, 'ann_type': 'A',
                    'client_source': 'web', 'stock_list': stock_code,
                    'f_node': 0, 's_node': 0},
            headers=headers, timeout=20,
        )
        items = ((r.json().get('data') or {}).get('list') or [])
    except Exception as _e:
        record(__name__, '_get_bse_annual_from_em', _e, note='静默降级')
        return []

    for it in items:
        title = it.get('title') or ''
        # 严格：年报全文（排除摘要 / 业绩说明会 / 预告 / 英文版 / 已取消）
        if '年度报告' not in title:
            continue
        if any(k in title for k in ('摘要', '说明会', '预告', '英文', '已取消', '问询')):
            continue
        art = it.get('art_code') or ''
        if not art:
            continue
        m = re.search(r'(20\d{2})\s*年\s*年度报告', title)
        year = int(m.group(1)) if m else None
        reports.append({
            'year': year,
            'title': title,
            'pdf_url': f'https://pdf.dfcfw.com/pdf/H2_{art}_1.pdf',
            'date': str(it.get('notice_date') or '')[:10],
            'art_code': art,
            'current_code': stock_code,
            'source': 'em_announce_bse',
        })

    # 同年去重（保留最新一条）
    dedup: Dict[int, Dict] = {}
    for rp in reports:
        y = rp.get('year')
        if y not in dedup or str(rp.get('date', '')) > str(dedup[y].get('date', '')):
            dedup[y] = rp
    out = sorted(dedup.values(), key=lambda x: x.get('year') or 0, reverse=True)
    # 若当年年报尚未披露，补一条最新半年报，避免"完全无 PDF"
    return out[:years]


def fetch_bse_notice_text(art_code: str, max_pages: int = None, sleep_sec: float = 0.15) -> Dict:
    """东财公告「分页正文」→ 拼接全文（2026-10-21 新增）。

    背景：东财 PDF（pdf.dfcfw.com）已被反爬，返回 985B `<script>` 页伪装成
    application/pdf；但 `np-cnotice-stock/api/content/ann` 的 `notice_content`
    是**真文本**（按 page_size 分页，实测 47 页）。年报 PDF 拿不到时用它兜底，
    MD&A / 风险 / 审计意见文字仍可提取（图表、表格排版会丢）。

    Returns: {'text','pages','chars','truncated'}
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
               'Referer': 'https://data.eastmoney.com/'}
    api = 'https://np-cnotice-stock.eastmoney.com/api/content/ann'

    def _page(i: int) -> Optional[str]:
        try:
            j = requests.get(api, params={'art_code': art_code, 'client_source': 'web',
                                         'page_index': i}, headers=headers, timeout=25).json()
            d = j.get('data') or {}
            return d.get('notice_content') or ''
        except Exception:
            return None

    first = _page(1)
    if first is None:
        return {'text': '', 'pages': 0, 'chars': 0, 'truncated': False}

    try:
        _meta = requests.get(api, params={'art_code': art_code, 'client_source': 'web',
                                          'page_index': 1}, headers=headers, timeout=25).json()
        total = int(((_meta.get('data') or {}).get('page_size') or 1))
    except Exception:
        total = 1
    pages = min(total, max_pages) if max_pages else total

    parts = [first]
    for i in range(2, pages + 1):
        t = _page(i)
        if t:
            parts.append(t)
        time.sleep(sleep_sec)

    text = '\n'.join(parts)
    return {'text': text, 'pages': pages, 'chars': len(text),
            'truncated': pages < total}


def _bse_text_fallback(art_code: str, pdf_path: str, max_pages: int = 60) -> Optional[Dict]:
    """年报 PDF 不可得时，把公告全文文本落盘为 `<stem>_fulltext.txt`。"""
    if not art_code:
        return None
    try:
        r = fetch_bse_notice_text(art_code, max_pages=max_pages)
    except Exception as _e:
        print(f"[WARN] 北交所公告全文抓取失败: {_e}")
        return None
    if not r.get('text'):
        return None
    stem = os.path.splitext(pdf_path)[0]
    txt_path = f'{stem}_fulltext.txt'
    try:
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(r['text'])
        print(f"[溯源] ✓ 已改用公告全文文本: {txt_path} "
              f"({r['chars']} 字 / {r['pages']} 页"
              f"{'·已截断' if r.get('truncated') else ''})")
    except Exception as _e:
        print(f"[WARN] 全文文本落盘失败: {_e}")
        return None
    return {'text_path': txt_path, 'chars': r['chars'], 'pages': r['pages'],
            'truncated': r.get('truncated', False)}


def _get_bse_annual_reports(stock_code: str, years: int = 3) -> List[Dict]:
    """
    从北交所(BSE)官网获取年报列表
    API: POST https://www.bse.cn/disclosureInfoController/initDisclosureList.do
    
    注意: companyCd参数无效，需遍历分页查找目标公司
    需翻页50-100页才能覆盖全部公告
    
    Returns:
        [{'year': int, 'title': str, 'pdf_url': str, 'date': str}, ...]
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.bse.cn/disclosure/announcement.html',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    # 获取session cookie
    try:
        session.get('https://www.bse.cn/disclosure/announcement.html', timeout=10)
    except Exception as _sexc:
        record(__name__, '_get_bse_annual_reports', _sexc, note='静默降级')
        pass

    api_url = 'https://www.bse.cn/disclosureInfoController/initDisclosureList.do'
    all_anns = []

    for page in range(1, 100):
        params = [
            ('page', str(page)), ('companyCd', ''), ('xxfcbj[]', '2'),
            ('siteId', '6'), ('flag', '0'), ('isNewThree', '1'),
            ('disclosureSubtype[]', ''), ('keyword', ''),
        ]
        try:
            r = session.post(api_url, data=params, timeout=10)
            j = r.json()
            content = j.get('data', {}).get('content', [])
            if not content:
                break
            for item in content:
                for d in item.get('disclosures', []):
                    cd = d.get('companyCd', '')
                    if cd == stock_code:
                        all_anns.append(d)
        except Exception:
            break
        # 翻够50页还没找到目标公司，放弃
        if page > 50 and not all_anns:
            break

    reports = []
    for ann in all_anns:
        title = ann.get('disclosureTitle', '')
        # 严格判断：年报全文（排除摘要、业绩说明会预告等）
        if ('年度报告' in title and '摘要' not in title
                and '业绩说明' not in title and '说明会' not in title):
            path = ann.get('destFilePath', '')
            if path:
                year_match = re.search(r'(\d{4})', path)
                year = int(year_match.group(1)) if year_match else None
                reports.append({
                    'year': year,
                    'title': title,
                    'pdf_url': f'https://www.bse.cn{path}',
                    'date': path[:10] if path else '',
                })

    reports.sort(key=lambda x: x.get('year') or 0, reverse=True)
    return reports[:years]


# ============================================================
# CNINFO（沪深）年报下载
# ============================================================

def get_annual_report_list(stock_code: str, company_name: str = None, years: int = 3) -> List[Dict]:
    """
    从 CNINFO 获取年报列表

    Args:
        stock_code: 股票代码
        company_name: 公司名称（推荐，搜索更稳定）
        years: 获取最近几年

    Returns:
        年报列表 [{'year': int, 'title': str, 'pdf_url': str, 'date': str}, ...]
    """
    url = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://www.cninfo.com.cn/new/disclosure/stock',
        'Origin': 'https://www.cninfo.com.cn',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    searchkey = company_name if company_name else stock_code

    data = {
        'tabName': 'fulltext',
        'category': 'category_ndbg_szsh',
        'plate': 'sz',
        'searchkey': searchkey,
        'seDate': '',
        'isHLtitle': 'true',
        'pageSize': 30,
    }

    if stock_code.startswith('6'):
        data['plate'] = 'sh'
    elif stock_code.startswith('0') or stock_code.startswith('3'):
        data['plate'] = 'sz'
    elif stock_code.startswith('4') or stock_code.startswith('8') or stock_code.startswith('9'):
        # BSE北交所股票 (40/80/92/83/87等) → plate='bj'
        data['plate'] = 'bj'

    try:
        r = requests.post(url, data=data, headers=headers, timeout=15)
        result = r.json()
        announcements = result.get('announcements') or []

        reports = []
        for ann in announcements:
            title = ann.get('announcementTitle', '')
            if '年度报告' in title and '摘要' not in title:
                adj_url = ann.get('adjunctUrl', '')
                if adj_url:
                    year_match = re.search(r'(\d{4})年', title)
                    year = int(year_match.group(1)) if year_match else None
                    reports.append({
                        'year': year,
                        'title': title,
                        'pdf_url': f"https://static.cninfo.com.cn/{adj_url}",
                        'date': ann.get('announcementTime', ''),
                        'announcement_id': ann.get('announcementId', ''),
                    })

        reports.sort(key=lambda x: x['year'] or 0, reverse=True)
        return reports[:years]

    except Exception as e:
        print(f"[ERROR] get_annual_report_list: {e}")
        return []


# 定期报告类型映射
REPORT_CATEGORIES = {
    'annual': {
        'cninfo_code': 'category_ndbg_szsh',  # 年报分类码有效
        'cninfo_searchkey_suffix': '',         # 无需关键词附加，分类码足够
        'label': '年报',
        'title_keywords': ['年度报告'],
        'exclude_keywords': ['摘要', '英文版', 'English'],
    },
    'semi_annual': {
        'cninfo_code': '',                      # category_ydbg_szsh 已失效（返回全量数据）
        'cninfo_searchkey_suffix': ' 半年度报告', # 改用关键词搜索
        'label': '半年报',
        'title_keywords': ['半年度报告', '中期报告'],
        'exclude_keywords': ['摘要', '英文版', 'English'],
    },
    'quarterly': {
        'cninfo_code': '',                      # category_bdbg_szsh 已失效
        'cninfo_searchkey_suffix': ' 季度报告',  # 改用关键词搜索
        'label': '季报',
        'title_keywords': ['季度报告', '季报'],
        'exclude_keywords': ['摘要', '英文版', 'English'],
    },
}


def get_periodic_report_list(stock_code: str, company_name: str = None,
                             report_type: str = 'all', years: int = 3) -> Dict[str, List[Dict]]:
    """
    从 CNINFO 获取定期报告列表（年报+半年报+季报）

    Args:
        stock_code: 股票代码
        company_name: 公司名称
        report_type: 'annual'|'semi_annual'|'quarterly'|'all'
        years: 获取最近几年

    Returns:
        {'annual': [...], 'semi_annual': [...], 'quarterly': [...]}
    """
    result = {}
    types = [report_type] if report_type != 'all' else list(REPORT_CATEGORIES.keys())

    for rtype in types:
        cat_info = REPORT_CATEGORIES.get(rtype)
        if not cat_info:
            continue
        reports = _fetch_cninfo_reports(
            stock_code, company_name, cat_info, years=years
        )
        result[rtype] = reports

    return result


def _fetch_cninfo_reports(stock_code, company_name, cat_info, years=3):
    """从CNINFO获取指定类型报告列表"""
    url = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://www.cninfo.com.cn/new/disclosure/stock',
        'Origin': 'https://www.cninfo.com.cn',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    # 年报用分类码过滤，半年报/季报用关键词搜索（分类码已失效）
    searchkey = (company_name if company_name else stock_code) + cat_info.get('cninfo_searchkey_suffix', '')
    data = {
        'tabName': 'fulltext',
        'category': cat_info.get('cninfo_code', ''),
        'plate': 'sz',
        'searchkey': searchkey,
        'seDate': '',
        'isHLtitle': 'true',
        'pageSize': 30,
    }
    if stock_code.startswith('6'):
        data['plate'] = 'sh'
    elif stock_code.startswith('4') or stock_code.startswith('8') or stock_code.startswith('9'):
        # BSE北交所股票 (40/80/83/87/92等) → plate='bj'
        data['plate'] = 'bj'
    else:
        data['plate'] = 'sz'

    try:
        r = requests.post(url, data=data, headers=headers, timeout=15)
        resp = r.json()
        announcements = resp.get('announcements') or []

        reports = []
        for ann in announcements:
            title = ann.get('announcementTitle', '')
            # 去除HTML标签
            import re as _re
            title_clean = _re.sub(r'<[^>]+>', '', title)
            # 匹配包含关键词且不含排除词的
            has_kw = any(kw in title_clean for kw in cat_info['title_keywords'])
            has_exclude = any(ex in title_clean for ex in cat_info['exclude_keywords'])
            if has_kw and not has_exclude:
                adj_url = ann.get('adjunctUrl', '')
                if adj_url:
                    year_match = _re.search(r'(\d{4})', title_clean)
                    year = int(year_match.group(1)) if year_match else None
                    reports.append({
                        'year': year,
                        'title': title_clean,
                        'pdf_url': f"https://static.cninfo.com.cn/{adj_url}",
                        'date': ann.get('announcementTime', ''),
                        'announcement_id': ann.get('announcementId', ''),
                        'report_type': cat_info['label'],
                    })

        reports.sort(key=lambda x: x['year'] or 0, reverse=True)
        # 季报每年4份，多保留一些
        max_count = years * 4 if '季' in cat_info['label'] else years
        return reports[:max_count]

    except Exception as e:
        print(f"[ERROR] _fetch_cninfo_reports({cat_info['label']}): {e}")
        return []


def download_and_extract_periodic(stock_code: str, company_name: str = None,
                                  save_dir: str = None,
                                  report_type: str = 'all',
                                  years: int = 1) -> Dict:
    """
    一键下载并提取定期报告（年报+半年报+季报）

    Args:
        stock_code: 股票代码
        company_name: 公司名称
        save_dir: 保存目录
        report_type: 'annual'|'semi_annual'|'quarterly'|'all'
        years: 获取最近几年

    Returns:
        {
            'reports': {
                'annual': {year: {sections, text_preview, page_count}},
                'semi_annual': {...},
                'quarterly': {...}
            },
            'summary': {...}
        }
    """
    try:
        from safe_request import safe_get as _safe_get
    except ImportError:
        from scripts.safe_request import safe_get as _safe_get

    all_reports = get_periodic_report_list(stock_code, company_name, report_type, years)
    result = {'reports': {}, 'summary': {'total_downloaded': 0, 'errors': []}}

    for rtype, report_list in all_reports.items():
        if not report_list:
            result['reports'][rtype] = {'status': 'empty', 'message': f'无{REPORT_CATEGORIES[rtype]["label"]}数据'}
            continue

        result['reports'][rtype] = {}
        # 只下载最新一份（除非years>1）
        for report in report_list[:years]:
            year = report.get('year')
            pdf_url = report.get('pdf_url', '')
            label = REPORT_CATEGORIES[rtype]['label']

            if not pdf_url:
                continue

            if not save_dir:
                save_dir = os.path.join(os.getcwd(), 'output', f'{stock_code}_{datetime.now().strftime("%Y%m%d")}', 'data')
            os.makedirs(save_dir, exist_ok=True)

            pdf_path = os.path.join(save_dir, f'{year}_{rtype}_report.pdf')

            # 下载
            if not os.path.exists(pdf_path):
                try:
                    success = download_pdf(pdf_url, pdf_path)
                    if not success:
                        result['summary']['errors'].append(f'{label} {year}年下载失败')
                        continue
                except Exception as e:
                    result['summary']['errors'].append(f'{label} {year}年下载异常: {str(e)[:60]}')
                    continue

            # 提取文本+章节
            try:
                sections = extract_sections(pdf_path)
                text_preview = extract_text(pdf_path, max_chars=8000)
                page_count = _count_pages(pdf_path)

                result['reports'][rtype][year] = {
                    'sections': sections,
                    'text_preview': text_preview,
                    'page_count': page_count,
                    'pdf_path': pdf_path,
                    'title': report.get('title', ''),
                }
                result['summary']['total_downloaded'] += 1
            except Exception as e:
                result['summary']['errors'].append(f'{label} {year}年提取失败: {str(e)[:60]}')

    return result


def _count_pages(pdf_path):
    """获取PDF页数"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        n = len(doc)
        doc.close()
        return n
    except:
        return 0


def _pdf_pages_text(pdf_path):
    """fitz 分页文本 [(pno, text)]；fitz 不可用/异常返回 []"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages = [(i + 1, (doc[i].get_text() or '')) for i in range(len(doc))]
        doc.close()
        return pages
    except Exception:
        return []


def extract_text(pdf_path: str, max_chars: int = 8000) -> str:
    """PDF 正文前 max_chars 字（fitz 分页拼接）。fitz 不可用降级返回 ''。
    🔴 修复 2026-10-21：原 periodic_reports 提取调用未定义的 extract_text/extract_sections，
    触发 NameError，导致年报/半年报/季报正文从未进 results.json。"""
    pages = _pdf_pages_text(pdf_path)
    if not pages:
        return ''
    full = '\n'.join(t for _, t in pages)
    return full[:max_chars]


# 定期报告常见章节 marker → 短名（尽量与年报 annual_pdf.sections 的 key 对齐，便于下游复用）
_PERIODIC_SECTION_MARKERS = [
    ('管理层讨论与分析', 'mdaa'),
    ('经营情况讨论与分析', 'mdaa'),
    ('董事会报告', 'mdaa'),
    ('主要会计数据和财务指标', 'financial_key_data'),
    ('主要财务数据', 'financial_key_data'),
    ('前十大股东', 'top10_shareholders'),
    ('股本变动情况', 'share_structure'),
]


def extract_sections(pdf_path: str) -> Dict:
    """定期报告章节抽取（fitz）：定位常见章节标题、跳过目录点线、抠正文前若干字。
    返回 {短名: {'name','content','page'}}；fitz 不可用返回 {}。"""
    pages = _pdf_pages_text(pdf_path)
    if not pages:
        return {}
    sections: Dict = {}
    for pno, ptxt in pages:
        clean = re.sub(r'[ \t]+', ' ', ptxt)
        for marker, key in _PERIODIC_SECTION_MARKERS:
            if key in sections:
                continue
            idx = clean.find(marker)
            if idx < 0:
                continue
            after = clean[idx + len(marker): idx + len(marker) + 40]
            # 跳过目录页：标题后跟一长串点线
            if re.search(r'[.。·…]{4,}', after):
                continue
            # 跳过正文交叉引用：标题被引号/书名号括起（如 查阅第三节"管理层讨论与分析"中…）
            before = clean[max(0, idx - 5): idx].rstrip()
            if (before.endswith(('《', '<', '>', '（', '(', '“', '”', '"', '‘'))
                    or after[:1] in ('”', '"', '’', ')', '》', '>')):
                continue
            seg = re.sub(r'\n{2,}', '\n', clean[idx: idx + 1500]).strip()
            if len(seg) > 40:
                sections[key] = {'name': marker, 'content': seg[:1500], 'page': pno}
    return sections


# ============================================================
# PDF下载核心
# ============================================================

def download_pdf(pdf_url: str, save_path: str, timeout: int = 120) -> bool:
    """
    下载 PDF 文件

    Args:
        pdf_url: PDF URL
        save_path: 保存路径
        timeout: 超时秒数

    Returns:
        是否成功
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        r = requests.get(pdf_url, headers=headers, timeout=timeout)
        if r.status_code == 200 and len(r.content) > 10000:
            with open(save_path, 'wb') as f:
                f.write(r.content)
            print(f"[OK] PDF下载成功: {save_path} ({len(r.content)/1024/1024:.1f}MB)")
            return True
        else:
            print(f"[FAIL] PDF下载失败: status={r.status_code}, size={len(r.content)}")
            return False
    except Exception as e:
        print(f"[ERROR] download_pdf: {e}")
        return False


# ============================================================
# PDF文本提取（PyMuPDF + pdfplumber双引擎）
# ============================================================

def extract_pdf_text(pdf_path: str, pages: int = None, toc_only: bool = False) -> Dict:
    """
    提取 PDF 文本内容

    Args:
        pdf_path: PDF 文件路径
        pages: 提取页数 (None = 全部)
        toc_only: 只提取目录

    Returns:
        {
            'page_count': int,
            'toc': [...],  # 目录
            'text': str,   # 文本内容
            'sections': {...}  # 按章节提取的内容
        }
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"  ⚠️ PyMuPDF 未安装，跳过PDF内容提取")
        return {"success": False, "error": "PyMuPDF not installed", "text": "", "page_count": 0, "sections": {}, "toc": []}

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    result = {
        'page_count': total_pages,
        'toc': [],
        'text': '',
        'sections': {},
    }

    # 提取目录
    toc = doc.get_toc()
    if toc:
        result['toc'] = [
            {'level': level, 'title': title, 'page': page}
            for level, title, page in toc
        ]

    if toc_only:
        doc.close()
        return result

    # 提取文本
    extract_pages = pages if pages else total_pages
    text_parts = []

    for page_num in range(min(extract_pages, total_pages)):
        page = doc[page_num]
        text = page.get_text()
        text_parts.append(f"--- 第{page_num+1}页 ---\n{text}")

    result['text'] = '\n'.join(text_parts)
    doc.close()

    return result


def extract_key_sections(pdf_path: str) -> Dict:
    """
    提取年报关键章节

    Args:
        pdf_path: PDF 文件路径

    Returns:
        {
            'management_discussion': str,  # 管理层讨论与分析
            'risk_factors': str,           # 风险因素
            'financial_highlights': str,   # 财务数据摘要
            'shareholders': str,           # 股东情况
            'important_matters': str,       # 重要事项
        }
    """
    import fitz

    doc = fitz.open(pdf_path)
    toc = doc.get_toc()

    # 构建章节->页码映射
    section_pages = {}
    for level, title, page in toc:
        if level <= 2:
            section_pages[title] = page

    # 定义要提取的章节
    section_keywords = {
        'management_discussion': ['管理层讨论', '经营情况讨论'],
        'risk_factors': ['风险', '可能面对'],
        'financial_highlights': ['主要会计数据', '财务指标'],
        'shareholders': ['股份变动', '股东情况'],
        'important_matters': ['重要事项'],
    }

    result = {}

    for key, keywords in section_keywords.items():
        start_page = None
        end_page = None

        for title, page in section_pages.items():
            if any(kw in title for kw in keywords):
                start_page = page
                break

        if start_page:
            found_current = False
            for level, title, page in toc:
                if page == start_page:
                    found_current = True
                    continue
                if found_current and level <= 2:
                    end_page = page - 1
                    break

            if not end_page:
                end_page = min(start_page + 30, doc.page_count)

            text_parts = []
            for p in range(start_page - 1, min(end_page, doc.page_count)):
                page = doc[p]
                text_parts.append(page.get_text())

            result[key] = '\n'.join(text_parts)

    doc.close()
    return result


# ============================================================
# 一键下载并提取
# ============================================================

def download_and_extract(stock_code: str, company_name: str = None,
                         save_dir: str = None, year: int = None) -> Dict:
    """
    一键下载并提取年报（自动识别市场）
    
    市场判断规则：
    - 北交所：8xxxx / 92xxx
    - 上交所（沪市）：6xxxx → 使用上交所API（JS反爬cookie流程）
    - 深交所（深市）：0xxxx / 3xxxx
    - 港股：4-5位数字
    """
    # 判断市场并获取年报列表
    _years_default = 3  # 默认取近3年用于列表查找
    
    if _is_bse_stock(stock_code):
        # 先迁码（8xxxxx/4xxxxx → 920xxx），再走东财公告源（BSE 官网翻页接口已失效）
        _cur_code = stock_code
        try:
            from bse_migrate import resolve_bse_code
            _mig = resolve_bse_code(stock_code)
            if _mig.get('switched') and _mig.get('current_code'):
                _cur_code = _mig['current_code']
                print(f"[INFO] 北交所迁码：{stock_code} → {_cur_code}（{_mig.get('name')}）")
        except Exception as _me:
            print(f"[WARN] 北交所迁码解析失败，按原代码继续: {_me}")
        reports = _get_bse_annual_from_em(_cur_code, years=_years_default)
        if not reports:
            print("[WARN] 东财北交所年报无结果，回退 BSE 官网翻页（历史接口）...")
            reports = _get_bse_annual_reports(_cur_code, years=_years_default)
    elif stock_code.startswith('6'):
        # 上交所：6xxxx
        print(f"[INFO] 检测到上交所股票 {stock_code}，使用上交所API...")
        reports = get_sse_annual_report_list(stock_code, years=_years_default)
        if not reports:
            print(f"[WARN] 上交所API无结果，降级到CNINFO...")
            reports = get_annual_report_list(stock_code, company_name, years=_years_default)
    else:
        reports = get_annual_report_list(stock_code, company_name, years=_years_default)

    if not reports:
        return {'error': f'未找到年报 (stock_code={stock_code})'}

    # 选择年份
    target_report = None
    if year:
        for r in reports:
            if r['year'] == year:
                target_report = r
                break
    else:
        target_report = reports[0]

    if not target_report:
        return {'error': f'未找到 {year} 年年报'}

    # 确定保存路径
    if not save_dir:
        save_dir = os.path.join(os.getcwd(), 'output', f'{stock_code}_{datetime.now().strftime("%Y%m%d")}', 'data')

    os.makedirs(save_dir, exist_ok=True)
    pdf_path = os.path.join(save_dir, f'{target_report["year"]}_annual_report.pdf')

    # 下载（跳过已存在的）
    is_sse = stock_code.startswith('6')
    pdf_url = target_report['pdf_url']
    
    if not os.path.exists(pdf_path):
        if is_sse:
            # 上交所PDF：尝试无cookie下载，失败后提示需要xbrowser cookie
            ok = download_pdf(pdf_url, pdf_path)
            if not ok or os.path.getsize(pdf_path) < 10000:
                # 检查是否返回了JS而非PDF
                with open(pdf_path, 'rb') as f:
                    magic = f.read(4)
                if magic != b'%PDF':
                    print(f"[WARN] 上交所PDF疑似JS反爬（magic={magic}），请使用xbrowser获取cookie后重试")
                    print(f"[WARN] 提示：在xbrowser中打开 {pdf_url} 后执行:")
                    print(f"[WARN]   xb act kind=evaluate fn:\")() => document.cookie\"")
                    print(f"[WARN] 获取cookie后使用: sse_pdf_workflow(url, cookie, save_path)")
                    return {'error': f'上交所PDF反爬，需xbrowser cookie流程（magic={magic}）'}
        else:
            if not download_pdf(pdf_url, pdf_path):
                # 北交所：东财 PDF 走反爬（实测 985B <script> 页面伪装成 application/pdf）
                # → 降级抓「公告全文文本」，MD&A/风险/审计意见仍可用（图表丢失）
                txt = None
                if target_report.get('art_code'):
                    txt = _bse_text_fallback(target_report['art_code'], pdf_path)
                if not txt:
                    return {'error': 'PDF下载失败'}
                return {
                    'text_path': txt['text_path'],
                    'text_chars': txt['chars'],
                    'pdf_blocked': True,
                    'pdf_url': pdf_url,
                    'art_code': target_report['art_code'],
                    'notice_url': (f"https://data.eastmoney.com/notices/detail/"
                                   f"{target_report.get('current_code', stock_code)}/"
                                   f"{target_report['art_code']}.html"),
                    '_note': ('东财 PDF 接口反爬（返回 985B 脚本页），已改用公告全文文本；'
                              '可人工打开 notice_url 下载原 PDF'),
                }
    else:
        print(f"[SKIP] PDF已存在: {pdf_path}")

    # 🔴 PDF 魔数校验（2026-10-21）：反爬页会被写成 .pdf，直接喂 fitz 只会报乱码
    try:
        with open(pdf_path, 'rb') as _f:
            _magic = _f.read(5)
        if _magic != b'%PDF-':
            _sz = os.path.getsize(pdf_path)
            print(f"[WARN] 下载文件非 PDF（magic={_magic!r}, size={_sz}B）→ 删除并走文本降级")
            os.remove(pdf_path)
            if target_report.get('art_code'):
                _t = _bse_text_fallback(target_report['art_code'], pdf_path)
                if _t:
                    return {'text_path': _t['text_path'], 'text_chars': _t['chars'],
                            'pdf_blocked': True, 'pdf_url': pdf_url,
                            'art_code': target_report['art_code'],
                            'notice_url': f"https://data.eastmoney.com/notices/detail/{stock_code}/"
                                          f"{target_report['art_code']}.html"}
            return {'error': f'下载内容非 PDF（可能是反爬页，{_sz}B）'}
    except Exception as _ve:
        print(f"[WARN] PDF 校验异常: {_ve}")

    # ── 步骤2：提取PDF文本和目录 ─────────────────────────────────────────────
    extracted = extract_pdf_text(pdf_path)
    
    # ── 步骤3：调用 annual_extract.py 提取20个关键章节 ─────────────────────
    sections = {}
    text_preview = extracted['text'][:5000]
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 100000:
        try:
            from scripts.annual_extract import AnnualReportExtractor
            extractor = AnnualReportExtractor(pdf_path=pdf_path)
            if extractor.text:
                sections = extractor.extract_all()
                text_preview = extractor.text[:5000]
                print(f"  📑 提取 {len(sections)} 个章节（{'中文' if extractor.lang=='cn' else '英文'}年报）")
            else:
                print(f"  ⚠️ 年报文本为空（乱码或提取失败）")
        except Exception as e:
            print(f"  ⚠️ annual_extract 调用失败: {e}")

    return {
        'pdf_path': pdf_path,
        'year': target_report['year'],
        'title': target_report['title'],
        'page_count': extracted['page_count'],
        'toc': extracted['toc'][:50],
        'sections': sections,
        'text_preview': text_preview,
        'full_text': extracted['text'],
    }


# 使用示例
if __name__ == '__main__':
    # 北交所测试
    result = download_and_extract('920262')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
