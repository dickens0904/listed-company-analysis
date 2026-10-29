# -*- coding: utf-8 -*-
"""
iwencai_provider.py - 统一数据查询模块（免费优先，问财降级）
为 listed-company-analysis 提供统一的数据调用接口

数据源优先级：
1. 免费数据源（东方财富 / 新浪 / 腾讯公开接口，无需 Key）
2. 问财 API（需要 IWENCAI_API_KEY，可选降级）

支持技能：
- hithink-basicinfo-query : 基本信息查询
- hithink-event-query       : 事件数据查询（公告/增发/调研）
- hithink-industry-query    : 行业数据查询
- hithink-macro-query       : 宏观数据查询
- hithink-market-query      : 市场行情查询
"""
import os
import json
import secrets
import urllib.request
import urllib.error
from typing import Dict, List, Optional, Any
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# ── 问财 API 配置 ──────────────────────────────────────────────
IWENCAI_API_BASE = "https://openapi.iwencai.com/v1/query2data"
SKILL_VERSIONS = {
    'hithink-basicinfo-query': '1.0.0',
    'hithink-event-query':     '1.0.0',
    'hithink-industry-query':  '1.0.0',
    'hithink-macro-query':     '1.0.0',
    'hithink-market-query':    '1.0.0',
}

# ── 免费接口基础 URL ─────────────────────────────────────────────
EM_BASE   = "https://push2.eastmoney.com/api/qt/stock/get"
EM_F10    = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SINA_BASE = "https://hq.sinajs.cn/list"


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def _get_api_key() -> Optional[str]:
    """获取问财 API Key；未配置返回 None（不抛异常）"""
    return os.environ.get('IWENCAI_API_KEY', '') or None


def _generate_trace_id() -> str:
    return secrets.token_hex(32)


def _http_get(url: str, timeout: int = 15) -> Any:
    """极简 HTTP GET，返回解析后的 JSON；失败抛异常"""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://www.eastmoney.com/',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _normalize_code(code: str) -> str:
    """
    把 600519 / 000001 / 00700 转成东方财富 secid 格式。
    沪市 60xxxx → 1.60xxxx
    深市 00xxxx/30xxxx → 0.00xxxx
    港股 00700  → 116.00700
    """
    code = code.strip()
    if code.isdigit() and len(code) == 6:
        return ('1.' + code) if code.startswith('6') else ('0.' + code)
    if len(code) <= 5 and code.isdigit():
        return '116.' + code.zfill(5)
    return code


# ══════════════════════════════════════════════════════════════
# 免费数据源实现（东方财富 + 新浪公开接口，零 Key）
# ══════════════════════════════════════════════════════════════

def _free_market(stock_code: str, query: str) -> Dict[str, Any]:
    """
    免费行情查询。
    使用东方财富 push2 接口，无需 Key。
    返回单条数据，与 iwencai 格式尽量兼容。
    """
    symbol = _normalize_code(stock_code)
    url = (
        f"{EM_BASE}?secid={symbol}"
        f"&fields=f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f57,f58,f60,f107,f152,f162,f169,f170,f171"
        f"&ut=fa5fd1943c7b386f172d6893dbfba10b"
    )
    try:
        js = _http_get(url)
        d = (js or {}).get('data', {}) or {}
        if not d:
            return {'success': True, 'datas': [], 'code_count': 0}

        return {'success': True, 'datas': [{
            '股票代码':  d.get('f57', stock_code),
            '股票名称':  d.get('f58', ''),
            '最新价':   d.get('f43', 0) / 100,   # 东方财富价格单位：分
            '涨跌幅':   d.get('f170', 0) / 100,  # 单位：万分之一
            '开盘价':   d.get('f46', 0) / 100,
            '最高价':   d.get('f44', 0) / 100,
            '最低价':   d.get('f45', 0) / 100,
            '昨收':     d.get('f60', 0) / 100,
            '成交量':   d.get('f47', 0),
            '成交额':   d.get('f48', 0),
            '换手率':   d.get('f168', 0) / 100,
            '市盈率':   d.get('f162', 0),
            '总市值':   d.get('f116', 0),
        }], 'code_count': 1}
    except Exception as e:
        return {'success': False, 'datas': [], 'error': f'免费行情查询失败: {e}'}


def _free_basicinfo(stock_code: str, query: str) -> Dict[str, Any]:
    """
    免费基本信息查询。
    使用东方财富 F10 公司概况接口（无需 Key）。
    """
    import re
    # 构造市场前缀
    m = re.search(r'\b(\d{6})\b', stock_code + ' ' + query)
    code = m.group(1) if m else stock_code[:6]
    prefix = 'sh' if code.startswith('6') else 'sz'
    url = f"https://f10.eastmoney.com/CompanySurvey/CompanySurveyAjax?code={prefix}{code}"
    try:
        js  = _http_get(url)
        d   = (js or {}).get('data', {}) or {}
        base = d.get('jbzl', {}) or {}
        return {'success': True, 'datas': [{
            '股票代码':   code,
            '股票简称':   base.get('agdmc', code),
            '公司全称':   base.get('fgsm', ''),
            '英文名称':   base.get('ywmc', ''),
            '成立日期':   base.get('clsj', ''),
            '上市日期':   base.get('sssj', ''),
            '注册资本':   base.get('zcc', ''),
            '法定代表人': base.get('fddbr', ''),
            '董事长':     d.get('ldrs', [{}])[0].get('xm', '') if d.get('ldrs') else '',
            '主营业务':   base.get('zyyw', ''),
            '所属行业':   base.get('sshy', ''),
        }], 'code_count': 1}
    except Exception as e:
        # 降级：至少返回代码
        return {'success': True, 'datas': [{'股票代码': code}], 'code_count': 1}


def _free_event(stock_code: str, query: str, limit: int = 10) -> Dict[str, Any]:
    """免费公告查询（东方财富）"""
    url = (
        f"https://np-anotice-stock.eastmoney.com/api/security/ann"
        f"?sr=-1&page_size={limit}&page_index=1&ann_type=ALL&client_source=web"
        f"&stock_list={stock_code}"
    )
    try:
        js = _http_get(url)
        ann_list = (((js or {}).get('data') or {}).get('list') or [])
        datas = []
        for a in ann_list:
            datas.append({
                '公告标题': a.get('title', ''),
                '公告日期': a.get('notice_date', ''),
                '公告类型': a.get('columns', ''),
            })
        return {'success': True, 'datas': datas, 'code_count': len(datas)}
    except Exception as e:
        return {'success': False, 'datas': [], 'error': f'免费公告查询失败: {e}'}


def _free_industry(query: str, limit: int = 10) -> Dict[str, Any]:
    """免费行业板块行情（东方财富）"""
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        "?pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2"
        "&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f5,f6"
    )
    try:
        js = _http_get(url)
        diff = ((js or {}).get('data') or {}).get('diff') or []
        datas = []
        for d in diff[:limit]:
            datas.append({
                '板块代码': d.get('f12', ''),
                '板块名称': d.get('f14', ''),
                '最新价':   d.get('f2', 0),
                '涨跌幅':   d.get('f3', 0),
            })
        return {'success': True, 'datas': datas, 'code_count': len(diff)}
    except Exception as e:
        return {'success': False, 'datas': [], 'error': f'免费行业查询失败: {e}'}


def _free_macro(query: str, limit: int = 12) -> Dict[str, Any]:
    """免费宏观数据（东方财富 CPI/PMI 等）"""
    # 尝试获取 CPI 数据
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?reportName=MACRO_CPI"
        "&columns=REPORT_DATE,CPI_YOY,CPI_MOM"
        "&pageNumber=1&pageSize=12&sortTypes=-1&sortColumns=REPORT_DATE"
    )
    try:
        js = _http_get(url)
        raw = (((js or {}).get('result') or {}).get('data') or [])
        datas = []
        for d in raw:
            datas.append({
                '日期':     d.get('REPORT_DATE', ''),
                'CPI同比':  d.get('CPI_YOY', ''),
                'CPI环比':  d.get('CPI_MOM', ''),
            })
        return {'success': True, 'datas': datas, 'code_count': len(datas)}
    except Exception as e:
        return {'success': False, 'datas': [], 'error': f'免费宏观查询失败: {e}'}


def _extract_stock_code(query: str) -> str:
    """从查询语句中提取 6 位股票代码"""
    import re
    m = re.search(r'\b(\d{6})\b', query)
    return m.group(1) if m else ''


def _route_free(skill_id: str, query: str, limit: int) -> Dict[str, Any]:
    """根据 skill_id 路由到免费数据源"""
    code = _extract_stock_code(query)

    if skill_id == 'hithink-market-query':
        target = code or ''
        return _free_market(target, query)

    if skill_id == 'hithink-basicinfo-query':
        target = code or ''
        return _free_basicinfo(target, query)

    if skill_id == 'hithink-event-query':
        target = code or ''
        return _free_event(target, query, limit)

    if skill_id == 'hithink-industry-query':
        return _free_industry(query, limit)

    if skill_id == 'hithink-macro-query':
        return _free_macro(query, limit)

    return {'success': False, 'datas': [], 'error': f'未知 skill_id: {skill_id}'}


# ══════════════════════════════════════════════════════════════
# 问财 API 调用（降级备用）
# ══════════════════════════════════════════════════════════════

def _call_iwencai(skill_id: str, query: str,
                  page: int = 1, limit: int = 10,
                  call_type: str = 'normal', timeout: int = 30,
                  retry_on_empty: bool = True,
                  max_retries: int = 2) -> Dict[str, Any]:
    """调用问财 API；失败时返回错误信息（不抛异常）"""
    api_key = _get_api_key()
    if not api_key:
        return {'success': False, 'datas': [], 'error': 'IWENCAI_API_KEY 未配置'}

    skill_ver = SKILL_VERSIONS[skill_id]
    trace_id  = _generate_trace_id()
    payload   = {
        'query':     query,
        'page':      str(page),
        'limit':     str(limit),
        'is_cache':  '1',
        'expand_index': 'true',
    }
    headers = {
        'Authorization':           f'Bearer {api_key}',
        'Content-Type':            'application/json',
        'X-Claw-Call-Type':      call_type,
        'X-Claw-Skill-Id':       skill_id,
        'X-Claw-Skill-Version':   skill_ver,
        'X-Claw-Plugin-Id':      'none',
        'X-Claw-Plugin-Version':  'none',
        'X-Claw-Trace-Id':        trace_id,
    }

    last_error = None
    cur_q, cur_type = query, call_type

    for attempt in range(max_retries + 1):
        try:
            data    = json.dumps(payload).encode('utf-8')
            request = urllib.request.Request(IWENCAI_API_BASE, data=data,
                                           headers=headers, method='POST')
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            datas     = result.get('datas', [])
            code_cnt  = result.get('code_count', 0)

            if attempt == 0 or datas:
                return {'success': True, 'datas': datas,
                        'code_count': code_cnt,
                        'chunks_info': result.get('chunks_info', {}),
                        'query_used': cur_q, 'error': None}

            if retry_on_empty and attempt < max_retries:
                simp = _simplify_query(cur_q)
                if simp != cur_q:
                    cur_q = simp
                    payload['query'] = simp
                    cur_type = 'retry'
                    headers['X-Claw-Call-Type'] = 'retry'
                    continue

            return {'success': True, 'datas': [], 'code_count': 0,
                    'chunks_info': result.get('chunks_info', {}),
                    'query_used': cur_q,
                    'error': '无匹配数据（已重试）'}

        except urllib.error.HTTPError as e:
            last_error = f'HTTP {e.code}: {e.reason}'
            try:
                last_error += ' - ' + json.loads(e.read().decode('utf-8')).get('message', '')
            except Exception as _sexc:
                record(__name__, '_call_iwencai', _sexc, note='静默降级')
        except urllib.error.URLError as e:
            last_error = f'网络错误: {e.reason}'
        except Exception as e:
            last_error = f'未知错误: {e}'

        if attempt == max_retries:
            break
        import time; time.sleep(1)

    return {'success': False, 'datas': [], 'code_count': 0,
            'chunks_info': {}, 'query_used': cur_q,
            'error': last_error or '未知错误'}


def _simplify_query(q: str) -> str:
    import re
    q = re.sub(r'[\（\(].*?[\)\）]', '', q)
    return ' '.join(q.split()).strip()


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

def query_iwencai(
    skill_id: str,
    query: str,
    page: int = 1,
    limit: int = 10,
    call_type: str = 'normal',
    timeout: int = 30,
    retry_on_empty: bool = True,
    max_retries: int = 2,
    prefer_free: bool = True,
) -> Dict[str, Any]:
    """
    统一查询入口。

    优先级：
    1. A股全栈免费数据（腾讯/东财/新浪/巨潮，零 Key）
    2. 内建免费源（东财 push2 公开接口）
    3. 问财 API（需 IWENCAI_API_KEY）

    返回字典新增 'source' 字段：'a_stock' / 'free' / 'iwencai' / 'none'
    """
    if skill_id not in SKILL_VERSIONS:
        raise ValueError(
            f'不支持的 skill_id: {skill_id}\n'
            f"支持的技能: {list(SKILL_VERSIONS.keys())}"
        )
    if not query or not query.strip():
        raise ValueError('query 不能为空')

    page  = max(page, 1)
    limit = max(limit, 1)

    # ── 第 1 步：尝试 A股全栈免费数据（最高优先）───────────
    if prefer_free:
        try:
            from free_data_provider import free_query as fdp_query
            result = fdp_query(skill_id, query, limit)
            if result.get('success') and result.get('datas'):
                result['source']      = 'a_stock'
                result['page']        = page
                result['limit']       = limit
                result['query_used']  = query
                result['chunks_info'] = {}
                return result
        except ImportError:
            pass  # free_data_provider 未安装，跳过

    # ── 第 2 步：尝试内建免费源 ──────────────────────────────────
    if prefer_free:
        result = _route_free(skill_id, query, limit)
        if result.get('success') and result.get('datas'):
            result['source']      = 'free'
            result['page']        = page
            result['limit']       = limit
            result['query_used']  = query
            result['chunks_info'] = {}
            return result

    # ── 第 3 步：降级到问财 ─────────────────────
    iwencai_ret = _call_iwencai(
        skill_id, query, page, limit,
        call_type, timeout, retry_on_empty, max_retries)
    if iwencai_ret.get('success'):
        iwencai_ret['source'] = 'iwencai'
        return iwencai_ret

    # ── 第 4 步：全部失败 ──────────────────────────────────
    return {
        'success': False,
        'datas': [],
        'code_count': 0,
        'chunks_info': {},
        'query_used': query,
        'page': page,
        'limit': limit,
        'error': (
            (result or {}).get('error', '')
            + '\n' + (iwencai_ret or {}).get('error', '')
            + '\n💡 免费数据源访问失败；'
            '若需更高准确率，请配置 IWENCAI_API_KEY 环境变量。'
        ),
        'source': 'none',
    }


# ══════════════════════════════════════════════════════════════
# 快捷函数
# ══════════════════════════════════════════════════════════════

def query_basicinfo(query: str, **kw) -> Dict[str, Any]:
    return query_iwencai('hithink-basicinfo-query', query, **kw)

def query_event(query: str, **kw) -> Dict[str, Any]:
    return query_iwencai('hithink-event-query', query, **kw)

def query_industry(query: str, **kw) -> Dict[str, Any]:
    return query_iwencai('hithink-industry-query', query, **kw)

def query_macro(query: str, **kw) -> Dict[str, Any]:
    return query_iwencai('hithink-macro-query', query, **kw)

def query_market(query: str, **kw) -> Dict[str, Any]:
    return query_iwencai('hithink-market-query', query, **kw)


def fetch_all_pages(skill_id: str, query: str,
                    max_pages: int = 10, limit: int = 10,
                    **kwargs) -> List[Dict]:
    """自动翻页，返回所有数据的扁平列表"""
    all_datas = []
    for p in range(1, max_pages + 1):
        r = query_iwencai(skill_id, query, page=p, limit=limit, **kwargs)
        if not r['success']:
            break
        d = r['datas']
        if not d:
            break
        all_datas.extend(d)
        if len(all_datas) >= r['code_count']:
            break
    return all_datas


# ══════════════════════════════════════════════════════════════
# CLI 测试
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('用法: python iwencai_provider.py <skill_id> <query> [page] [limit]')
        print(f"支持的 skill_id: {list(SKILL_VERSIONS.keys())}")
        print('\n💡 当前优先使用免费数据源（东方财富公开接口）')
        print('   如需使用问财，请设置 IWENCAI_API_KEY 环境变量')
        sys.exit(1)

    skill_id = sys.argv[1]
    query    = sys.argv[2]
    page     = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    limit    = int(sys.argv[4]) if len(sys.argv) > 4 else 10

    print(f"[{skill_id}] 查询: {query}")
    print(f"页 {page} / 每页 {limit}   （优先免费源）")
    print('-' * 62)

    result = query_iwencai(skill_id, query, page, limit)

    if result['success']:
        print(f"✅ 成功 | 来源: {result.get('source')} | "
              f"返回 {len(result['datas'])} 条 / 共 {result['code_count']} 条")
        print(f"查询: {result.get('query_used', query)}")
        print('-' * 62)
        for i, item in enumerate(result['datas'][:5], 1):
            print(f"  {i}. {item}")
        if len(result['datas']) > 5:
            print(f"  ... 共 {len(result['datas'])} 条，仅显示前 5")
    else:
        print(f"❌ 失败: {result['error']}")
    print('-' * 62)
