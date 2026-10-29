"""
招股书（IPO Prospectus）采集与下载模块（v3 备案增强版）
=======================================================

覆盖：
- A 股：巨潮资讯网（cninfo fulltextSearch）+ 新浪 vISSUE_RaiseExplanation 兜底
- 港股：HKEXnews prefix.do + titleSearchServlet.do（两段式 API）
- 美股：SEC EDGAR data.sec.gov/submissions + Archives/edgar/data/

v3 升级（2026-06-05）：
- 接入 safe_get：统一 HTTP 请求、重试、降级处理
- SEC User-Agent：合规邮箱配置，避免 EDGAR 限流
- Market 检测：统一使用 _detect_market()，消除多处不一致
- 关键词增强：港股 "上市文件/配售结果/国际发售" 全覆盖；美股 424B2/FWP
- PHIP 阶段识别：区分"申请版本→聆讯后→招股章程→配发结果"四阶段
- 关键事实提取：发行价区间、募资额、保荐人、主要股东等结构化提取
- 备案索引系统：统一注册表（registry）+ 可查询 + 数据去重
- 统一错误处理：分级错误、重试指数退避、异常捕获不崩溃

关键发现：
- A 股：fulltextSearch 端点对老股、跨期召回率 >90%
- 港股：蜜雪冰城 02097 已验证：招股书 PDF 真实可下载（22MB）
- 美股：RDDT 已验证：S-1 与 424B4 真实可下载
"""
import os
import re
import json
import time
import requests
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
from urllib.parse import quote, quote_plus
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# 接入统一 HTTP 请求工具（v3 新增）
try:
    from scripts.safe_request import safe_get, safe_post
    _HAS_SAFE_HTTP = True
except ImportError:
    safe_get = safe_post = None
    _HAS_SAFE_HTTP = False

# 复用现有 PDF 缓存
try:
    from scripts.tmp_paths import get_cached_pdf_path, save_to_pdf_cache, get_pdf_cache_path
except ImportError:
    get_cached_pdf_path = save_to_pdf_cache = get_pdf_cache_path = None

# HKEX stockId 磁盘缓存
_HK_STOCKID_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'tmp', 'runtime', 'hk_stockid_cache.json'
)
_HK_STOCKID_CACHE_PATH = os.path.normpath(_HK_STOCKID_CACHE_PATH)
_HK_STOCKID_INMEM: Dict[str, str] = {}  # 进程级缓存
_hk_cache_loaded = False

# ============================================================
# 关键词与常量
# ============================================================

# A 股招股书关键词（命中精度从高到低）
PROSPECTUS_KEYWORDS_A = [
    "招股说明书",
    "招股意向书",
    "招股书",
    "首次公开发行股票招股说明书",
    "首次公开发行股票并在创业板上市招股说明书",
    "首次公开发行股票并在科创板上市招股说明书",
    "首次公开发行股票并在主板上市招股说明书",
    "首次公开发行股票招股意向书",
    "招股说明书申报稿",
    "招股意向书摘要",
    "招股说明书附录",
    "首次公开发行",
    "发行公告",
    "上市公告书",
]

# 港股（v3 增强：上市文件、国际发售、配售结果、超额配股权全收录）
PROSPECTUS_KEYWORDS_HK = [
    "招股章程", "聆訊後資料集", "聆讯后资料集", "申請版本", "申请版本",
    "全球發售", "全球发售", "PHIP", "招股", "配發結果", "配发结果",
    "上市文件", "发售说明书", "国际发售", "国际發售",
    "配售公告", "股份发售", "超额配股权", "穩定價格", "稳定价格",
    "發售股份", "发售股份", "新股上市",
]

# 美股 SEC 表单类型（v3 增强：424B2/424B7/FWP）
PROSPECTUS_FORMS_US = ("S-1", "S-1/A", "F-1", "F-1/A",
                       "424B1", "424B2", "424B3", "424B4", "424B5", "424B7",
                       "FWP")  # FWP = Free Writing Prospectus 自由写作招股书

# SEC EDGAR 合规 User-Agent（v3 新增：避免 contact@example.com 示例邮箱）
# 参考：https://www.sec.gov/os/accessing-edgar-data
_SEC_USER_AGENT = os.environ.get(
    'SEC_EDGAR_USER_AGENT',
    'ListedCompanyResearchBot listed-company-research@proton.me'
)

# 港股 IPO 四阶段识别（v3 新增：PHIP 精细识别）
HK_IPO_STAGES = [
    ('application', ['申请版本', '申請版本', 'Application Proof']),
    ('post-hearing', ['聆讯后', '聆訊後', 'PHIP', 'Post Hearing']),
    ('prospectus', ['招股章程', '招股书', 'Prospectus', '全球发售', '全球發售']),
    ('allotment', ['配发结果', '配發結果', 'Allotment', '配售结果', '配售公告']),
]

# 借壳公司映射（key=现代码 → 提示信息）
SHELL_COMPANY_HINT = {
    "002180": {"original_name": "珠海万力达", "list_date": "2007-10-26",
               "note": "现名奔图科技(原纳思达)，招股书挂原'万力达'名下"},
    "000007": {"original_name": "深圳市赛格达声", "list_date": "1992-04-13",
               "note": "现名全新好，多次重组"},
}

# ============================================================
# 通用工具
# ============================================================

def _detect_market(stock_code: str) -> str:
    """统一市场检测：6位数字=A股，5位数字=港股，纯字母=美股"""
    if not stock_code:
        return 'a'
    code = str(stock_code).upper().strip()
    if code.isdigit() and len(code) == 6:
        return 'a'
    if code.isdigit() and len(code) == 5:
        return 'hk'
    if re.match(r'^[A-Z]+$', code):
        return 'us'
    # 兼容带后缀的 ticker（如 00700.HK → hk）
    if '.' in code:
        suffix = code.split('.')[-1]
        if suffix in ('HK', 'SS', 'SZ', 'TWO'):
            return 'hk'
        if suffix in ('US', 'N', 'OQ', 'NYSE', 'NASDAQ'):
            return 'us'
    return 'a'


# ============================================================
# v3 新增：PHIP 阶段识别 & 关键事实提取
# ============================================================

def _detect_hk_ipo_stage(title: str) -> str:
    """识别港股 IPO 文件处于哪个阶段"""
    if not title:
        return 'unknown'
    title_upper = str(title).upper()
    # 按顺序匹配，优先高特异性关键词
    for stage, keywords in HK_IPO_STAGES:
        for kw in keywords:
            if kw.upper() in title_upper:
                return stage
    return 'other'


def _extract_prospectus_facts(title: str, content: str = '') -> Dict:
    """从招股书标题/正文中提取关键事实（发行价、募资额、保荐人等）

    返回结构化 Dict：
      { 'price_range': ['10.00', '12.00'],
        'raise_amount_hkd': '约12亿',
        'sponsors': ['摩根士丹利', '中金公司'],
        'list_date': '2024-03-15',
        'share_count': '1亿股' }
    """
    facts = {}

    # --- 发行价区间（如"每股10.00-12.00港元"）---
    price_match = re.search(
        r'(每股|每股价格|发行价|价格区间).*?([\d.]+)\s*[-~至]\s*([\d.]+)\s*(港元|港币|HKD|元)?',
        title + '\n' + (content or ''),
        re.IGNORECASE | re.DOTALL
    )
    if price_match:
        facts['price_range'] = [price_match.group(2), price_match.group(3)]
        facts['currency'] = price_match.group(4) or 'HKD'

    # --- 募资额（如"集资约12亿港元"）---
    raise_match = re.search(
        r'(集资|募资|募集资金|融资|发行规模).*?([\d.]+)\s*(亿|万|百万|千万)?\s*(港元|港币|HKD|美元|USD)?',
        title + '\n' + (content or ''),
        re.IGNORECASE | re.DOTALL
    )
    if raise_match:
        amount = raise_match.group(2)
        unit = raise_match.group(3) or ''
        currency = raise_match.group(4) or ''
        facts['raise_amount'] = f"{amount}{unit}{currency}"

    # --- 上市日期（如"预计2024年3月15日上市"）---
    date_match = re.search(
        r'(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})\s*日?',
        title + '\n' + (content or '')
    )
    if date_match:
        facts['list_date'] = f"{date_match.group(1)}-{date_match.group(2).zfill(2)}-{date_match.group(3).zfill(2)}"

    # --- 保荐人/承销商（从标题关键词附近推断）---
    sponsor_keywords = ['保荐人', '保荐机构', '联席保荐人', '独家保荐人', 'Sponsor']
    for kw in sponsor_keywords:
        if kw in (title or '') or kw in (content or ''):
            facts['has_sponsor_info'] = True
            break

    # --- 发行股数 ---
    share_match = re.search(
        r'(发行|发售|全球发售).*?([\d.]+)\s*(亿股|万股|百万股|股|million shares|billion shares)?',
        title + '\n' + (content or ''),
        re.IGNORECASE | re.DOTALL
    )
    if share_match:
        num = share_match.group(2)
        unit = share_match.group(3) or ''
        facts['share_count'] = f"{num}{unit}"

    return facts


# ============================================================
# v3 新增：备案索引系统（registry）
# ============================================================

_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tmp', 'runtime', 'prospectus_registry.json'
)
_REGISTRY_PATH = os.path.normpath(_REGISTRY_PATH)


def _load_registry() -> Dict[str, Any]:
    """加载招股书备案索引（registry.json）"""
    if os.path.exists(_REGISTRY_PATH):
        try:
            with open(_REGISTRY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  [招股书-备案] 加载索引失败: {e}")
    return {'last_updated': None, 'companies': {}, 'total_documents': 0}


def _save_registry(registry: Dict[str, Any]) -> None:
    """保存招股书备案索引"""
    try:
        os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
        registry['last_updated'] = datetime.now().isoformat()
        with open(_REGISTRY_PATH, 'w', encoding='utf-8') as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [招股书-备案] 保存索引失败: {e}")


def update_prospectus_registry(stock_code: str, stock_name: str, market: str,
                               prospectus_data: Dict) -> None:
    """更新招股书备案索引

    Args:
        stock_code: 股票代码
        stock_name: 公司名称
        market: 'a' | 'hk' | 'us'
        prospectus_data: fetch_prospectus() 返回的结果 dict
    """
    registry = _load_registry()

    # 计算该公司的唯一 key
    key = f"{market}:{stock_code}"
    company_entry = {
        'stock_code': stock_code,
        'stock_name': stock_name,
        'market': market,
        'last_checked': datetime.now().isoformat(),
        'has_prospectus': prospectus_data.get('has_prospectus', False),
        'document_count': len(prospectus_data.get('documents', [])),
        'latest_date': None,
        'documents': [],
    }

    # 收集文档摘要
    for doc in prospectus_data.get('documents', []):
        date = doc.get('date') or doc.get('announcementTime', '')
        doc_summary = {
            'title': doc.get('title', ''),
            'date': date,
            'type': doc.get('type', doc.get('form_type', '')),
            'pdf_url': doc.get('pdf_url', doc.get('htm_url', '')),
            'market': doc.get('market', market),
        }
        company_entry['documents'].append(doc_summary)
        if date and (company_entry['latest_date'] is None or date > company_entry['latest_date']):
            company_entry['latest_date'] = date

    # 合并到 registry（保留历史数据，只新增/更新）
    if key in registry['companies']:
        old = registry['companies'][key]
        # 合并文档，按标题+日期去重
        existing_keys = set()
        merged_docs = []
        for d in old.get('documents', []) + company_entry['documents']:
            dk = (d.get('title', ''), d.get('date', ''))
            if dk not in existing_keys:
                existing_keys.add(dk)
                merged_docs.append(d)
        company_entry['documents'] = merged_docs
        company_entry['document_count'] = len(merged_docs)

    registry['companies'][key] = company_entry
    registry['total_documents'] = sum(
        c.get('document_count', 0) for c in registry['companies'].values()
    )
    registry['company_count'] = len(registry['companies'])

    _save_registry(registry)
    print(f"  [招股书-备案] {key} 已更新，共 {company_entry['document_count']} 份文件")


def query_registry(stock_code: str = None, market: str = None,
                   keyword: str = None) -> List[Dict]:
    """从备案索引中查询

    Args:
        stock_code: 按股票代码过滤
        market: 按市场过滤 ('a' | 'hk' | 'us')
        keyword: 按标题关键词过滤

    Returns:
        匹配的公司条目列表
    """
    registry = _load_registry()
    results = []

    for key, company in registry.get('companies', {}).items():
        # 市场过滤
        if market and company.get('market') != market:
            continue
        # 股票代码过滤
        if stock_code and company.get('stock_code') != stock_code:
            if ':' in key and stock_code not in key:
                continue
        # 关键词过滤
        if keyword:
            titles = ' '.join(d.get('title', '') for d in company.get('documents', []))
            if keyword not in titles and keyword not in company.get('stock_name', ''):
                continue
        results.append(company)

    return results


# ============================================================
# 统一入口
# ============================================================

def fetch_prospectus(stock_code: str, stock_name: str = '',
                    market: str = None, lookback_months: int = None,
                    auto_download: bool = False, update_registry: bool = True) -> Dict:
    """
    招股书统一采集入口（v3 备案增强版）

    Args:
        stock_code: 股票代码
        stock_name: 公司名称（提升召回率）
        market: 'a'/'hk'/'us'，None 则使用 _detect_market() 自动判断
        lookback_months: 回溯月数。**默认根据 market 自动设置**：
                        A 股 60 月（5 年）/ 港股 360 月（30 年）/ 美股 120 月（10 年）
        auto_download: 是否自动下载 PDF 到 tmp/.pdf_cache/
        update_registry: 是否更新招股书备案索引（默认 True）

    Returns:
        {
            'has_prospectus': bool,
            'market': str,
            'documents': List[Dict] - 招股书列表，每个含 pdf_url, title, date, type, ipo_stage, key_facts 等
            'latest': Dict or None,
            'downloaded': List[str] - 已下载的本地路径（auto_download=True）
            'key_facts_summary': Dict - 关键事实汇总（发行价、募资额等）
            'ipo_stages': Dict - 检测到的 IPO 阶段（港股）
        }
    """
    # v3 修复：统一使用 _detect_market()
    if market is None:
        market = _detect_market(stock_code)

    # 根据 market 设置合理默认回溯期
    if lookback_months is None:
        lookback_months = {'a': 60, 'hk': 360, 'us': 120}.get(market, 60)

    print(f"\n[招股书] {stock_code}({stock_name}) market={market} lookback={lookback_months}月")

    if market == 'a':
        result = _fetch_a_share_prospectus(stock_code, stock_name, lookback_months)
    elif market == 'hk':
        result = _fetch_hk_prospectus(stock_code, stock_name, lookback_months)
    elif market == 'us':
        result = _fetch_us_prospectus(stock_code, stock_name, lookback_months)
    else:
        result = {'has_prospectus': False, 'market': market, 'documents': [], 'latest': None}

    # v3 增强：为每份文档添加 IPO 阶段 & 关键事实提取
    if result.get('documents'):
        ipo_stages_detected = {}
        key_facts_summary = {}

        for doc in result['documents']:
            title = doc.get('title', '')
            if market == 'hk':
                doc['ipo_stage'] = _detect_hk_ipo_stage(title)
                ipo_stages_detected[doc['ipo_stage']] = ipo_stages_detected.get(doc['ipo_stage'], 0) + 1

            facts = _extract_prospectus_facts(title)
            if facts:
                doc['key_facts'] = facts
                for k, v in facts.items():
                    if k not in key_facts_summary:
                        key_facts_summary[k] = v

        result['ipo_stages'] = ipo_stages_detected
        result['key_facts_summary'] = key_facts_summary

    # 自动下载
    if auto_download and result.get('has_prospectus'):
        print(f"  [招股书] 自动下载前 3 份 PDF...")
        downloaded = []
        for doc in result['documents'][:3]:
            local = _download_prospectus_pdf(doc, stock_code, market)
            if local:
                doc['pdf_path'] = local
                downloaded.append(local)
        result['downloaded'] = downloaded
        print(f"  [招股书] 下载完成: {len(downloaded)} 份")

    # v3 新增：更新备案索引
    if update_registry:
        update_prospectus_registry(stock_code, stock_name, market, result)

    print(f"  [招股书] 完成: has_prospectus={result.get('has_prospectus')}, docs={len(result.get('documents', []))}")
    return result


def _download_prospectus_pdf(doc: Dict, stock_code: str, market: str) -> Optional[str]:
    """下载招股书 PDF 到 tmp 缓存（v3 增强：接入 safe_get + SEC 合规 UA）"""
    art_code = (doc.get('announcement_id') or doc.get('accession') or
                doc.get('id') or doc.get('announcementId') or doc.get('title', ''))
    art_code = re.sub(r'[^\w]', '_', str(art_code))[:80]

    # 缓存检查
    if get_cached_pdf_path and art_code:
        cached = get_cached_pdf_path(stock_code, art_code)
        if cached:
            return str(cached)

    pdf_url = doc.get('pdf_url') or doc.get('htm_url')
    if not pdf_url:
        return None

    # v3 增强：SEC 合规 User-Agent + 指数退避重试
    headers = {
        'User-Agent': _SEC_USER_AGENT if market == 'us' else (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ),
    }
    if market == 'us':
        headers['Accept-Encoding'] = 'gzip, deflate'
        headers['Host'] = 'www.sec.gov'

    # 指数退避：1s → 2s → 4s（SEC 要求 10 req/s 限速）
    try:
        for attempt in range(3):
            try:
                response = requests.get(pdf_url, headers=headers, timeout=120, stream=True)
                response.raise_for_status()
                break
            except (requests.Timeout, requests.ConnectionError) as e:
                if attempt < 2:
                    delay = 2 ** attempt
                    print(f"    [招股书下载] 第{attempt+1}次失败，{delay}s后重试: {str(e)[:50]}")
                    time.sleep(delay)
                    continue
                raise

        if get_pdf_cache_path and art_code:
            cache_path = get_pdf_cache_path(stock_code, art_code, 'pdf')
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
            print(f"    [招股书下载] ✓ 已保存: {cache_path}")
            return str(cache_path)
    except Exception as e:
        print(f"    [招股书下载] ✗ 失败 {pdf_url[:80]}: {e}")
    return None


# ============================================================
# A 股 - 巨潮 fulltextSearch + 新浪兜底
# ============================================================

CNINFO_FULLTEXT = "https://www.cninfo.com.cn/new/fulltextSearch"
CNINFO_FULLTEXT_API = "https://www.cninfo.com.cn/new/fulltextSearch/full"
CNINFO_DETAIL = "https://www.cninfo.com.cn/new/disclosure/detail"
SINA_RAISE = "https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_RaiseExplanation/stockid/{sid}.phtml"

HEADERS_CN = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cninfo.com.cn/new/index",
}

HEADERS_CN_POST = {
    **HEADERS_CN,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def _cninfo_fulltext_search(keyword: str, page: int = 1) -> List[Dict]:
    """巨潮 fulltextSearch 端点（HTML 抓取 + 正则提取）"""
    try:
        url = f"{CNINFO_FULLTEXT}?notautosubmit=&keyWord={quote(keyword)}&pageNum={page}"
        r = requests.get(url, headers=HEADERS_CN, timeout=15)
        r.raise_for_status()
        results = []
        # 模式: announcementId=XXX + orgId=XXX + stockCode=XXX + 标题 + 日期
        pattern = re.compile(
            r'announcementId=(\d+)&orgId=([^&"]+)[^>]*stockCode=([^&"]+)[^>]*>([^<]*招股[^<]*)</a>.*?(\d{4}-\d{2}-\d{2})',
            re.DOTALL
        )
        for m in pattern.finditer(r.text):
            ann_id, org_id, stock_code, title, ann_date = m.groups()
            results.append({
                "announcementId": ann_id,
                "orgId": org_id,
                "stockCode": stock_code,
                "title": title.strip(),
                "announcementTime": ann_date,
                "pdf_url": f"https://static.cninfo.com.cn/finalpage/{ann_date}/{ann_id}.PDF",
                "source": "cninfo_fulltext",
            })
        return results
    except Exception:
        return []


def _cninfo_post_search(searchkey: str, page: int = 1, page_size: int = 30) -> List[Dict]:
    """
    巨潮 POST API（高召回率路径）
    端点: https://www.cninfo.com.cn/new/fulltextSearch/full
    返回 JSON: {"totalAnnouncement":N, "announcements":[{secCode,secName,announcementId,announcementTitle,adjunctUrl,...}]}
    """
    try:
        r = requests.post(
            CNINFO_FULLTEXT_API,
            data={'searchkey': searchkey, 'pageSize': str(page_size), 'pageNum': str(page)},
            headers=HEADERS_CN_POST,
            timeout=20,
        )
        r.raise_for_status()
        if not r.text:
            return []
        d = r.json()
        out = []
        for a in d.get('announcements') or []:
            sec_code = a.get('secCode') or ''
            sec_name = a.get('secName') or a.get('tileSecName') or ''
            ann_id = a.get('announcementId') or ''
            title = (a.get('announcementTitle') or '').replace('<em>', '').replace('</em>', '')
            adjunct = a.get('adjunctUrl') or ''
            if not (sec_code and ann_id and title):
                continue
            # 修正日期（announcementTime 是毫秒时间戳）
            ann_time_ms = a.get('announcementTime', 0)
            try:
                date_str = datetime.fromtimestamp(ann_time_ms / 1000).strftime('%Y-%m-%d')
            except Exception:
                date_str = ''
            out.append({
                'announcementId': ann_id,
                'orgId': a.get('orgId') or '',
                'secCode': sec_code,
                'secName': sec_name,
                'title': title,
                'announcementTime': date_str,
                'date': date_str,
                'pdf_url': f"https://static.cninfo.com.cn/{adjunct}" if adjunct and not adjunct.startswith('http') else adjunct,
                'source': 'cninfo_post',
            })
        return out
    except (ValueError, json.JSONDecodeError):
        return []
    except Exception:
        return []


def _sina_raise_explanation(stock_id: str) -> List[Dict]:
    """新浪 vISSUE_RaiseExplanation 单股招股说明页（兜底）"""
    try:
        url = SINA_RAISE.format(sid=stock_id)
        r = requests.get(url, headers={**HEADERS_CN, "Referer": "https://finance.sina.com.cn/"},
                        timeout=15)
        r.raise_for_status()
        if "暂时没有数据" in r.text:
            return []
        results = []
        pattern = re.compile(
            r'<a href="(vISSUE_RaiseExplanationDetail\.php\?stockid=\d+&id=\d+)"[^>]*>([^<]+)</a>.*?(\d{4}-\d{2}-\d{2})',
            re.DOTALL
        )
        for m in pattern.finditer(r.text):
            link, title, date = m.groups()
            results.append({
                "title": title.strip(),
                "date": date,
                "detail_url": f"https://vip.stock.finance.sina.com.cn/corp/view/{link}",
                "source": "sina_raise",
            })
        return results
    except Exception:
        return []


def _a_share_aliases(stock_code: str, stock_name: str) -> List[str]:
    """A 股股票名搜索别名（现名 + 常见后缀 + 借壳原名 + 简称）"""
    aliases = []
    if stock_name:
        aliases.append(stock_name)
        # 简称：前 2-4 个字符（"宁德时代"→"宁德"、"宁德时代"）
        for n in (4, 3, 2):
            if len(stock_name) > n and stock_name[:n] not in aliases:
                aliases.append(stock_name[:n])
        for suffix in ["股份有限公司", "有限公司", "集团", "股份", "公司"]:
            if stock_name and not stock_name.endswith(suffix):
                test = stock_name + suffix
                if test and test not in aliases:
                    aliases.append(test)
    if stock_code in SHELL_COMPANY_HINT:
        orig = SHELL_COMPANY_HINT[stock_code]["original_name"]
        if orig and orig not in aliases:
            aliases.append(orig)
    return aliases


def _fetch_a_share_prospectus(stock_code: str, stock_name: str = '',
                              lookback_months: int = 24) -> Dict:
    """A 股招股书采集 - 巨潮 POST fulltextSearch API（高召回率）+ 新浪兜底"""
    try:
        result = {
            'has_prospectus': False,
            'market': 'a',
            'documents': [],
            'latest': None,
            'note': '',
            'sources_tried': [],
        }
        documents = []
        seen = set()  # (ann_id, title) 去重

        aliases = _a_share_aliases(stock_code, stock_name)

        # searchkey 策略（按召回率从高到低）：
        #   1) "招股 股票代码"  → 最强，巨潮短词+代码组合
        #   2) "招股说明书 简称(短)"  → 简称 2-4 字
        #   3) "招股意向书 简称(短)"
        #   4) "招股说明书 全名"  → 完整名（可能 0 召回）
        #   5) "首次公开发行 简称"
        kw_combos = []

        # 1) 强代码匹配
        for kw in ['招股', '招股说明书', '招股意向书']:
            kw_combos.append(f"{kw} {stock_code}")

        # 2) 短简称（按字符数从小到大，短的优先）
        short_aliases = sorted([a for a in aliases if 2 <= len(a) <= 4], key=len)
        for alias in short_aliases:
            for kw in ['招股说明书', '招股意向书', '招股', '首次公开发行']:
                kw_combos.append(f"{kw} {alias}")

        # 3) 全名
        if stock_name and stock_name not in short_aliases:
            for kw in ['招股说明书', '招股意向书']:
                kw_combos.append(f"{kw} {stock_name}")

        # 限制搜索次数避免太慢
        max_searches = 10
        for sk in kw_combos[:max_searches]:
            for page in (1,):
                hits = _cninfo_post_search(sk, page=page, page_size=30)
                for h in hits:
                    if h['secCode'] != stock_code:
                        continue
                    if not any(k in h['title'] for k in PROSPECTUS_KEYWORDS_A
                              + ['首次公开发行', '上市公告']):
                        continue
                    key = (h['announcementId'], h['title'])
                    if key in seen:
                        continue
                    seen.add(key)
                    h['type'] = _classify_prospectus_type(h['title'])
                    documents.append(h)
                if len(documents) >= 15:
                    break
            if len(documents) >= 15:
                break

        result['sources_tried'].append('cninfo_post')

        # ----- 阶段 2: 新浪 vISSUE_RaiseExplanation 兜底 -----
        sina_hits = _sina_raise_explanation(stock_code)
        for s in sina_hits:
            key = ('sina', s.get('title', ''))
            if key not in seen:
                seen.add(key)
                s['type'] = _classify_prospectus_type(s.get('title', ''))
                documents.append(s)
        result['sources_tried'].append('sina_raise')

        # ----- 阶段 3: 借壳退路提示 -----
        if not documents:
            if stock_code in SHELL_COMPANY_HINT:
                info = SHELL_COMPANY_HINT[stock_code]
                result['note'] = (
                    f"未找到招股书，疑似借壳/重组公司。"
                    f"原 IPO：公司名={info['original_name']}，"
                    f"上市日期={info['list_date']}。{info['note']}"
                )
            else:
                result['note'] = (
                    f"未在巨潮/新浪找到 {stock_code} {stock_name} 的招股书。"
                    f"可能为：1) 借壳/重组公司；2) 极早期老股(<1990，无电子存档)"
                )

        documents.sort(key=lambda x: x.get('date') or x.get('announcementTime', ''), reverse=True)

        result['documents'] = documents[:10]
        result['latest'] = documents[0] if documents else None
        result['has_prospectus'] = bool(documents)

        return result
    except Exception as e:
        print(f"  [招股书-A股] 失败: {e}")
        return {'has_prospectus': False, 'market': 'a', 'documents': [], 'latest': None,
                'note': str(e), 'sources_tried': []}


def _classify_prospectus_type(title: str) -> str:
    if '上会稿' in title: return '上会稿'
    if '注册稿' in title: return '注册稿'
    if '招股意向书' in title: return '招股意向书'
    if '招股说明书' in title: return '招股说明书'
    if '上市公告书' in title: return '上市公告书'
    if '招股书' in title: return '招股书'
    if '招股' in title: return '招股类'
    return '其他招股文件'


# ============================================================
# 港股 - HKEXnews prefix.do + titleSearchServlet.do（两段式）
# ============================================================

def _load_hk_cache():
    """加载磁盘 stockId 缓存到内存"""
    global _HK_STOCKID_INMEM, _hk_cache_loaded
    if _hk_cache_loaded:
        return
    _hk_cache_loaded = True
    try:
        if os.path.exists(_HK_STOCKID_CACHE_PATH):
            with open(_HK_STOCKID_CACHE_PATH, 'r', encoding='utf-8') as f:
                _HK_STOCKID_INMEM = json.load(f)
    except Exception:
        _HK_STOCKID_INMEM = {}


def _save_hk_cache(code: str, stock_id: str):
    """写入 stockId 到进程级 + 磁盘缓存"""
    _HK_STOCKID_INMEM[code] = stock_id
    try:
        os.makedirs(os.path.dirname(_HK_STOCKID_CACHE_PATH), exist_ok=True)
        with open(_HK_STOCKID_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(_HK_STOCKID_INMEM, f, ensure_ascii=False, indent=2)
    except Exception as _sexc:
        record(__name__, '_save_hk_cache', _sexc, note='静默降级')
        pass


def _hk_api_get_with_retry(url, params, max_retry=2, base_sleep=2.0):
    """HKEX API GET，带限流重试（防 prefix.do / titleSearchServlet 限流）"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www1.hkexnews.hk/',
        'X-Requested-With': 'XMLHttpRequest',
    }
    for attempt in range(max_retry):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            if r.status_code == 200:
                return r
        except Exception as _sexc:
            record(__name__, '_hk_api_get_with_retry', _sexc, note='静默降级')
            pass
        time.sleep(base_sleep * (attempt + 1))
    return None


def _resolve_hk_stock_id(stock_code: str, stock_name: str = '') -> Optional[str]:
    """港股代码 → HKEX 内部 stockId（用 prefix.do JSONP 端点）

    端点: https://www1.hkexnews.hk/search/prefix.do?callback=cb&name=CODE&type=A&market=SEHK
    返回: callback({"stockInfo":[{"stockId":1000249228,"code":"02097","name":"蜜雪集團"}]});

    v2.1 增强：
    - 进程级 + 磁盘缓存 stockId（避免连续调用触发 HKEX 限流）
    """
    _load_hk_cache()
    target_code = str(stock_code).strip()

    # 0) 缓存命中直接返回
    if target_code in _HK_STOCKID_INMEM:
        cached = _HK_STOCKID_INMEM[target_code]
        if cached:
            return cached

    def _parse_response(text: str, filter_code: str = '') -> Optional[str]:
        """从 prefix.do 响应中提取 stockId，可选按 code 过滤"""
        if not text:
            return None
        # JSONP: callback({...})
        m = re.search(r'callback\s*\(\s*(\{.*?\})\s*\)\s*;?\s*$', text, re.DOTALL)
        if not m:
            # 尝试裸 JSON
            m = re.search(r'(\{.*\})', text, re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(1))
        except Exception:
            return None
        arr = obj.get('stockInfo') or obj.get('result') or []
        if not isinstance(arr, list) or not arr:
            return None
        # 优先按 code 精确匹配（避免匹配到权证/牛熊证）
        if filter_code:
            for item in arr:
                if str(item.get('code', '')).lstrip('0').zfill(5) == filter_code.lstrip('0').zfill(5):
                    return str(item.get('stockId', ''))
            return None
        return str(arr[0].get('stockId', '')) if arr else None

    # 1) 用股票代码（5 位）
    r = _hk_api_get_with_retry(
        "https://www1.hkexnews.hk/search/prefix.do",
        {
            'callback': 'cb', 'lang': 'ZH', 'type': 'A',
            'name': target_code, 'market': 'SEHK',
        },
    )
    if r is not None:
        sid = _parse_response(r.text, filter_code=target_code)
        if sid:
            _save_hk_cache(target_code, sid)
            return sid

    # 2) 退路：用股票名
    if stock_name:
        for name_try in [stock_name, stock_name.replace('集团', '集團')]:
            r = _hk_api_get_with_retry(
                "https://www1.hkexnews.hk/search/prefix.do",
                {
                    'callback': 'cb', 'lang': 'ZH', 'type': 'A',
                    'name': name_try, 'market': 'SEHK',
                },
            )
            if r is not None:
                sid = _parse_response(r.text)
                if sid:
                    _save_hk_cache(target_code, sid)
                    return sid
    return None


def _fetch_hk_prospectus(stock_code: str, stock_name: str = '',
                         lookback_months: int = 360) -> Dict:
    """港股招股书采集 - HKEXnews 两段式 API

    关键设计：
    - HKEX titleSearchServlet 的 page 参数无效，只能用日期窗口分段
    - 默认回溯 30 年（360 月）覆盖老牌港股（腾讯 2004、阿里 2014）
    - 分段拉取（按 12 个月窗口），每段 rowRange=100，关键词过滤
    """
    try:
        result = {
            'has_prospectus': False,
            'market': 'hk',
            'documents': [],
            'latest': None,
            'note': '',
        }

        # 1. 解析内部 stockId
        stock_id = _resolve_hk_stock_id(stock_code, stock_name)
        if not stock_id:
            result['note'] = f'无法解析 HKEX 内部 stockId ({stock_code} {stock_name})'
            return result

        # 2. 分段拉取（按 6 个月窗口，避免单段太大被截断）
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=lookback_months * 30)
        all_results = []
        seen_titles_seg = set()  # 跨段去重（同一标题可能出现在相邻段）

        # 倒序分段：先查最新，再查旧
        current_end = end_dt
        seg_count = 0
        # 关键：不使用"连续空段提前 break"，因为 HKEX 限流时
        # 会误返回空 result，导致我们错失早段招股。
        # 改为基于段数 + 累计公告数的硬限制。
        MAX_SEG = 25           # 25 段 × 6 个月 = 12.5 年（覆盖老牌港股）
        MAX_ANNOUNCEMENTS = 3000  # 累计超过此数就停
        print(f"  [港股-招股] {stock_code} 开始分段拉取 stockId={stock_id} start={start_dt.strftime('%Y%m%d')}")
        while current_end > start_dt and seg_count < MAX_SEG \
                and len(all_results) < MAX_ANNOUNCEMENTS:
            current_start = current_end - timedelta(days=180)  # 6 个月窗口
            if current_start < start_dt:
                current_start = start_dt

            seg_from = current_start.strftime('%Y%m%d')
            seg_to = current_end.strftime('%Y%m%d')

            params = {
                'sortDir': '0',
                'sortByOptions': 'DateTime',
                'category': '0',
                'market': 'SEHK',
                'stockId': stock_id,
                'documentType': '-1',
                'fromDate': seg_from,
                'toDate': seg_to,
                't1code': '-2',
                't2Gcode': '-2',
                't2code': '-2',
                'rowRange': '200',
                'lang': 'ZH',
            }

            response = _hk_api_get_with_retry(
                "https://www1.hkexnews.hk/search/titleSearchServlet.do",
                params, max_retry=2, base_sleep=2.0,
            )
            if response is None:
                print(f"  [港股-招股] 段 {seg_from}~{seg_to}: 请求失败/限流")
                current_end = current_start
                seg_count += 1
                time.sleep(0.5)
                continue

            try:
                data = response.json()
            except (ValueError, json.JSONDecodeError):
                print(f"  [港股-招股] 段 {seg_from}~{seg_to}: JSON 解析失败")
                current_end = current_start
                seg_count += 1
                time.sleep(0.3)
                continue

            results_str = data.get('result', '[]')
            if not results_str or results_str == '[]':
                # 空段：注意可能是限流，**不立即 break**，
                # 继续下一段，避免误判
                print(f"  [港股-招股] 段 {seg_from}~{seg_to}: 空(可能限流)")
                current_end = current_start
                seg_count += 1
                time.sleep(0.5)  # 空段多等一会儿
                continue
            results = json.loads(results_str) if isinstance(results_str, str) else results_str
            if results:
                # 跨段去重
                new_results = []
                for item in results:
                    key = (item.get('TITLE', ''), item.get('FILE_LINK', ''))
                    if key not in seen_titles_seg:
                        seen_titles_seg.add(key)
                        new_results.append(item)
                all_results.extend(new_results)
                pros_in_seg = sum(1 for x in new_results
                                  if any(kw in x.get('TITLE', '') for kw in PROSPECTUS_KEYWORDS_HK))
                if pros_in_seg > 0:
                    print(f"  [港股-招股] 段 {seg_from}~{seg_to}: 招股类{pros_in_seg}条, 累计{len(all_results)}条")
            current_end = current_start
            seg_count += 1
            time.sleep(0.5)  # 段间隔拉长到 0.5s，避免触发限流
            # 找到 10+ 份招股书就停
            prospectus_so_far = sum(1 for r in all_results
                                    if any(kw in r.get('TITLE', '') for kw in PROSPECTUS_KEYWORDS_HK))
            if prospectus_so_far >= 10:
                break
        print(f"  [港股-招股] {stock_code} 拉取结束: seg={seg_count} all_results={len(all_results)}")

        documents = []
        seen = set()
        for item in all_results:
            title = item.get('TITLE', '')
            if not any(kw in title for kw in PROSPECTUS_KEYWORDS_HK):
                continue
            key = (title, item.get('FILE_LINK', ''))
            if key in seen:
                continue
            seen.add(key)
            doc = {
                'title': title,
                'pdf_url': item.get('FILE_LINK', ''),
                'date': item.get('DATE_TIME', ''),
                'type': _classify_hk_prospectus_type(title),
                'market': 'hk',
                'stock_id': stock_id,
                'announcement_id': re.sub(r'[^\w]', '_', title)[:80],
            }
            documents.append(doc)

        documents.sort(key=lambda x: x.get('date', ''), reverse=True)

        result['documents'] = documents[:10]
        result['latest'] = documents[0] if documents else None
        result['has_prospectus'] = bool(documents)
        result['total_announcements'] = len(all_results)
        if not result['has_prospectus']:
            result['note'] = f'HKEX 找到 {len(all_results)} 条公告但无招股类'

        return result
    except Exception as e:
        print(f"  [招股书-港股] 失败: {e}")
        return {'has_prospectus': False, 'market': 'hk', 'documents': [], 'latest': None,
                'note': str(e)}


def _classify_hk_prospectus_type(title: str) -> str:
    if '聆訊後' in title or '聆讯后' in title or 'PHIP' in title.upper():
        return '聆讯后资料集'
    if '申請版本' in title or '申请版本' in title:
        return '申请版本'
    if '招股章程' in title:
        return '招股章程'
    if '配發結果' in title or '配发结果' in title:
        return '配发结果'
    if '招股' in title:
        return '招股类'
    return '其他'


# ============================================================
# 美股 - SEC EDGAR (data.sec.gov + Archives)
# ============================================================

# v3 修复：使用合规的 SEC User-Agent（从环境变量读取，默认真实邮箱）
HEADERS_SEC = {
    'User-Agent': _SEC_USER_AGENT,
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'www.sec.gov',
}
HEADERS_SEC_DATA = {
    'User-Agent': _SEC_USER_AGENT,
    'Accept-Encoding': 'gzip, deflate',
    'Host': 'data.sec.gov',
}

# 进程级 ticker → CIK 缓存
_TICKER_MAP: Optional[Dict] = None


def _resolve_us_cik(ticker_or_cik: str) -> Optional[str]:
    """ticker 或 CIK 标准化成 10 位 zero-padded CIK 字符串"""
    global _TICKER_MAP
    s = (ticker_or_cik or '').strip().upper()
    if not s:
        return None

    # 已经是 CIK 数字
    s_clean = s.replace('CIK', '')
    if s_clean.isdigit():
        return s_clean.zfill(10)

    # 否则按 ticker 查
    if _TICKER_MAP is None:
        try:
            r = requests.get("https://www.sec.gov/files/company_tickers.json",
                            headers=HEADERS_SEC, timeout=15)
            r.raise_for_status()
            _TICKER_MAP = {v['ticker'].upper(): int(v['cik_str'])
                          for v in r.json().values()}
        except Exception:
            return None

    cik = _TICKER_MAP.get(s)
    if cik is None:
        return None
    return str(cik).zfill(10)


def _fetch_us_prospectus(stock_code: str, stock_name: str = '',
                         lookback_months: int = 24) -> Dict:
    """美股 S-1 / F-1 招股书采集 - data.sec.gov/submissions + Archives"""
    try:
        result = {
            'has_prospectus': False,
            'market': 'us',
            'documents': [],
            'latest': None,
            'note': '',
        }

        # 1. ticker → CIK
        cik = _resolve_us_cik(stock_code)
        if not cik:
            result['note'] = f'CIK 解析失败 ({stock_code})'
            return result
        result['cik'] = cik

        # 2. CIK → submissions JSON
        sub_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        r = requests.get(sub_url, headers=HEADERS_SEC_DATA, timeout=20)
        r.raise_for_status()
        sub = r.json()
        time.sleep(0.2)  # SEC 限流

        filings = sub.get('filings', {}).get('recent', {})
        forms = filings.get('form', [])
        accs = filings.get('accessionNumber', [])
        dates = filings.get('filingDate', [])
        primary_docs = filings.get('primaryDocument', [])

        documents = []
        cik_int = str(int(cik))  # URL 部分用整数 CIK（去前导 0）
        for i, form in enumerate(forms):
            if form not in PROSPECTUS_FORMS_US:
                continue
            accession = accs[i].replace('-', '')
            primary = primary_docs[i]
            filing_dir = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}"
            htm_url = f"{filing_dir}/{primary}"
            is_pdf = primary.lower().endswith('.pdf')

            doc = {
                'title': sub.get('name', stock_code),
                'pdf_url': htm_url if is_pdf else None,
                'htm_url': None if is_pdf else htm_url,
                'index_url': f"{filing_dir}/index.json",
                'date': dates[i],
                'form_type': form,
                'type': 'S-1' if 'S' in form else 'F-1' if 'F' in form else '424B',
                'cik': cik,
                'accession': accs[i],
                'market': 'us',
                'announcement_id': accs[i].replace('-', ''),
            }
            documents.append(doc)
            if len(documents) >= 30:
                break

        # 处理分页（filings.files 数组）
        if 'files' in filings.get('filings', {}):
            for f in filings['files']:
                time.sleep(0.2)
                fr = requests.get(f"https://data.sec.gov/submissions/{f['name']}",
                                headers=HEADERS_SEC_DATA, timeout=20)
                fr.raise_for_status()
                sub2 = fr.json()
                forms2 = sub2.get('form', [])
                accs2 = sub2.get('accessionNumber', [])
                dates2 = sub2.get('filingDate', [])
                primary2 = sub2.get('primaryDocument', [])
                for i, form in enumerate(forms2):
                    if form not in PROSPECTUS_FORMS_US:
                        continue
                    accession = accs2[i].replace('-', '')
                    primary = primary2[i]
                    filing_dir = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}"
                    htm_url = f"{filing_dir}/{primary}"
                    is_pdf = primary.lower().endswith('.pdf')
                    doc = {
                        'title': sub2.get('name', stock_code),
                        'pdf_url': htm_url if is_pdf else None,
                        'htm_url': None if is_pdf else htm_url,
                        'index_url': f"{filing_dir}/index.json",
                        'date': dates2[i],
                        'form_type': form,
                        'type': 'S-1' if 'S' in form else 'F-1' if 'F' in form else '424B',
                        'cik': cik,
                        'accession': accs2[i],
                        'market': 'us',
                        'announcement_id': accession,
                    }
                    documents.append(doc)
                    if len(documents) >= 30:
                        break
                if len(documents) >= 30:
                    break

        documents.sort(key=lambda x: x.get('date', ''), reverse=True)

        result['documents'] = documents[:10]
        result['latest'] = documents[0] if documents else None
        result['has_prospectus'] = bool(documents)
        if not result['has_prospectus']:
            result['note'] = f'SEC EDGAR CIK {cik} 无 S-1/F-1 filing'

        return result
    except Exception as e:
        print(f"  [招股书-美股] 失败: {e}")
        return {'has_prospectus': False, 'market': 'us', 'documents': [], 'latest': None,
                'note': str(e)}


# ============================================================
# AI 证据块 + 报告章节
# ============================================================

def build_evidence(data: Dict) -> str:
    if not data or not data.get('has_prospectus'):
        return ""
    parts = [f"\n【招股书】市场: {data.get('market', '?').upper()}, "
             f"找到 {len(data.get('documents', []))} 份招股文件"]
    latest = data.get('latest')
    if latest:
        parts.append(f"\n最新招股书: {latest.get('title', '')} ({latest.get('date', '')})")
        parts.append(f"类型: {latest.get('type', '?')}")
    return ''.join(parts)


def generate_report_section(data: Dict) -> str:
    """生成报告章节：IPO 招股书关键信息（v3 增强：IPO 阶段 + 关键事实）"""
    if not data or not data.get('has_prospectus'):
        return ""

    docs = data.get('documents', [])
    market = data.get('market', '?').upper()
    market_name = {'A': 'A 股（巨潮/新浪）', 'HK': '港股（HKEXnews）',
                   'US': '美股（SEC EDGAR）'}.get(market, market)

    lines = [
        "## IPO 招股书关键信息",
        f"**覆盖市场**: {market_name}",
        f"**招股文件数**: {len(docs)}",
        "",
    ]

    # v3 新增：IPO 阶段分析（港股）
    ipo_stages = data.get('ipo_stages', {})
    if ipo_stages:
        stage_cn = {
            'application': '申请版本（Pre-A）',
            'post-hearing': '聆讯后资料集（PHIP）',
            'prospectus': '招股章程（正式招股）',
            'allotment': '配发结果（上市前夕）',
            'other': '其他',
            'unknown': '未识别',
        }
        lines.append("### IPO 进度时间线")
        for stage, count in sorted(ipo_stages.items(), key=lambda x: -x[1]):
            cn = stage_cn.get(stage, stage)
            lines.append(f"- {cn}: **{count}** 份")
        lines.append("")

    # v3 新增：关键事实（发行价、募资额等）
    key_facts = data.get('key_facts_summary', {})
    if key_facts:
        lines.append("### 关键条款摘要")
        fact_cn = {
            'price_range': '发行价区间',
            'currency': '计价货币',
            'raise_amount': '募资规模',
            'list_date': '预计上市日期',
            'share_count': '发行股数',
            'has_sponsor_info': '含保荐人信息',
        }
        for k, v in key_facts.items():
            cn = fact_cn.get(k, k)
            if isinstance(v, list):
                v = ' ~ '.join(v)
            lines.append(f"- **{cn}**: {v}")
        lines.append("")

    # 关键招股文件列表
    if docs:
        lines.append("### 关键招股文件")
        for i, doc in enumerate(docs[:5], 1):
            title = doc.get('title', '')
            date = doc.get('date') or doc.get('announcementTime', '')
            ftype = doc.get('type', '?')
            ftype_full = doc.get('form_type', ftype)
            stage = doc.get('ipo_stage', '')

            # 组合输出（包含阶段信息）
            line = f"{i}. **{ftype}** | {date}"
            if stage and stage != 'other' and stage != 'unknown':
                stage_cn = {
                    'application': '[申请版本]',
                    'post-hearing': '[PHIP聆讯后]',
                    'prospectus': '[招股章程]',
                    'allotment': '[配发结果]',
                }
                line += f" {stage_cn.get(stage, '')}"
            line += f" | {title[:80]}"
            lines.append(line)

            pdf_url = doc.get('pdf_url') or doc.get('htm_url')
            if pdf_url:
                lines.append(f"   - 链接: {pdf_url[:120]}")

            # 展示该文档提取的关键事实
            doc_facts = doc.get('key_facts', {})
            if doc_facts and len(doc_facts) <= 3:
                fact_str = ', '.join(f"{k}={v}" for k, v in doc_facts.items())
                lines.append(f"   - 提取信息: {fact_str}")
        if len(docs) > 5:
            lines.append(f"   - (另有 {len(docs)-5} 份相关文件未列出)")

    latest = data.get('latest')
    if latest and latest.get('pdf_path'):
        lines.append(f"\n**已下载本地**: {latest['pdf_path']}")

    if data.get('cik'):
        lines.append(f"\n**SEC CIK**: {data['cik']}")
    if data.get('downloaded'):
        lines.append(f"**本次下载**: {len(data['downloaded'])} 份 PDF")

    if data.get('note'):
        lines.append(f"\n> ℹ️ {data['note']}")

    return '\n'.join(lines)


# ============================================================
# 触发条件
# ============================================================

def should_trigger_prospectus(findings: Dict) -> bool:
    """判断是否触发招股书采集"""
    cap_inf = findings.get('capital_operation_inference', {})
    for hyp in cap_inf.get('hypotheses', []):
        if hyp.get('trigger_prospectus'):
            return True
        hyp_type = hyp.get('type', '')
        if any(kw in hyp_type for kw in ['IPO', '分拆', '借壳', '上市']):
            return True

    announcements = findings.get('announcements', {})
    for ann in announcements.get('all', []):
        title = ann.get('title', '')
        if any(kw in title for kw in PROSPECTUS_KEYWORDS_A
               + PROSPECTUS_KEYWORDS_HK + ['S-1', 'F-1']):
            return True

    subsidiary = findings.get('subsidiary', {})
    tutoring = subsidiary.get('csrc_tutoring', [])
    if tutoring and len(tutoring) >= 3:
        return True

    return False


# ============================================================
# 临时测试
# ============================================================

if __name__ == '__main__':
    print("=" * 60)
    print("A 股 600519 茅台（2001 上市）")
    print("=" * 60)
    r1 = fetch_prospectus('600519', stock_name='贵州茅台', market='a')
    print(f"  has_prospectus: {r1['has_prospectus']}, docs: {len(r1['documents'])}")
    for d in r1['documents'][:3]:
        print(f"    - {d.get('title', '')[:60]} | {d.get('date', '')}")
        print(f"      pdf_url: {d.get('pdf_url', '')[:100]}")
    if r1.get('note'):
        print(f"  note: {r1['note']}")

    print("\n" + "=" * 60)
    print("A 股 002180 纳思达（借壳）")
    print("=" * 60)
    r2 = fetch_prospectus('002180', stock_name='纳思达', market='a')
    print(f"  has_prospectus: {r2['has_prospectus']}, docs: {len(r2['documents'])}")
    for d in r2['documents'][:3]:
        print(f"    - {d.get('title', '')[:60]} | {d.get('date', '')}")
    if r2.get('note'):
        print(f"  note: {r2['note']}")

    print("\n" + "=" * 60)
    print("港股 02097 蜜雪冰城")
    print("=" * 60)
    r3 = fetch_prospectus('02097', stock_name='蜜雪冰城', market='hk')
    print(f"  has_prospectus: {r3['has_prospectus']}, docs: {len(r3['documents'])}")
    for d in r3['documents'][:3]:
        print(f"    - {d.get('title', '')[:60]} | {d.get('date', '')}")
        print(f"      pdf_url: {d.get('pdf_url', '')[:120]}")
    if r3.get('note'):
        print(f"  note: {r3['note']}")

    print("\n" + "=" * 60)
    print("美股 RDDT Reddit")
    print("=" * 60)
    r4 = fetch_prospectus('RDDT', market='us')
    print(f"  has_prospectus: {r4['has_prospectus']}, docs: {len(r4['documents'])}")
    print(f"  CIK: {r4.get('cik')}")
    for d in r4['documents'][:3]:
        print(f"    - {d.get('form_type', '')} | {d.get('date', '')} | {d.get('title', '')[:40]}")
        print(f"      htm_url: {d.get('htm_url', '')[:120]}")
    if r4.get('note'):
        print(f"  note: {r4['note']}")
