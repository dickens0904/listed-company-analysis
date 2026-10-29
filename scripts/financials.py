# -*- coding: utf-8 -*-
"""
财务分析模块（溯源增强版）
========================================
数据源优先级：本地缓存 → 东方财富API → 年报PDF提取

溯源标记：结果中 _meta.source 标注来源
  - em_api: 东方财富API成功
  - local_pdf: 本地年报PDF提取
  - cninfo_pdf: 刚从巨潮下载的PDF提取
  - bse_cn: 北交所官网PDF提取
  - local_cache: 本地JSON缓存命中
"""
import requests, json, os, re, sys
import _ctxfix  # noqa: F401  （修正 pywin32 抢占 scripts 包名，见 _ctxfix.py）
from scripts.safe_request import safe_get, safe_extract, safe_float
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

# 溯源基础设施
try:
    from scripts.source_tracker import (
        SourceTracker, annotate_result, source_label,
        download_annual_pdf_traced, SOURCE_LABELS
    )
    _HAS_TRACKER = True
except ImportError:
    _HAS_TRACKER = False
    def annotate_result(r, s):
        if r is None:
            return {'_meta': {'source': s}}
        r['_meta'] = r.get('_meta', {})
        r['_meta']['source'] = s
        return r
    SOURCE_LABELS = {'em_api': '东方财富API', 'local_pdf': '本地PDF', 'cninfo_pdf': '巨潮资讯PDF', 'bse_cn': '北交所官网PDF', 'local_cache': '本地缓存'}
    def source_label(s):
        return SOURCE_LABELS.get(s, s)

EM_API = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://data.eastmoney.com/',
    'Accept': 'application/json',
}


def fetch_financial_metrics(stock_code, market='a', data_dir=None,
                             skip_pdf=False, extract_text=False,
                             enable_tracking=True):
    """
    获取主要财务指标（溯源增强版）
    
    溯源优先级：
    1. local_cache → 本地 financial_metrics.json
    2. em_api → 东方财富 RPT_LICO_FN_CPD
    3. annual_pdf → 年报PDF提取（自动下载未下载的）
    
    返回字段（兼容 report.py）：
      - _meta.source: 数据来源标记
      - audit_opinion: 审计意见
      - key_risks: 关键风险列表
      - warnings: 警告列表
      - risks: 完整风险列表
      - records: 原始财务数据列表
      - latest: 最新一期数据
      - summary: 结构化摘要
    """
    from datetime import datetime
    
    # 初始化溯源追踪器
    if enable_tracking and _HAS_TRACKER:
        tracker = SourceTracker(stock_code, market, data_dir)
        inject_trace = True
    else:
        tracker = None
        inject_trace = False
    
    # ====== 段1：本地JSON缓存 ======
    cache_key = 'financials.json'
    if data_dir:
        cache_path = os.path.join(data_dir, cache_key)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                # 检查缓存是否有有效数据
                if cached.get('records') and len(cached['records']) > 0:
                    cached['_meta'] = cached.get('_meta', {})
                    cached['_meta']['source'] = 'local_cache'
                    print(f"[溯源] 金融数据命中本地缓存: {cache_path}")
                    return cached
            except Exception as e:
                print(f"[WARN] 本地缓存读取失败: {e}")
    
    # ====== 段2：东方财富API ======
    result = {
        'stock_code': stock_code,
        'audit_opinion': None,
        'key_risks': [],
        'warnings': [],
        'risks': [],
        'records': [],
        'latest': None,
        'summary': {},
        '_meta': {'source': 'em_api', 'fetched_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
    }

    # 格式股票代码
    secucode = stock_code
    if market == 'a':
        if not (stock_code.endswith('.SZ') or stock_code.endswith('.SH')):
            # 00/30开头=深市, 60/68开头=沪市, 8/4开头=北交所
            if stock_code[:2] in ['00', '30']:
                secucode = stock_code + '.SZ'
            elif stock_code[:2] in ['60', '68']:
                secucode = stock_code + '.SH'
            elif stock_code[0] in ['8', '4']:
                secucode = stock_code + '.BJ'
            else:
                secucode = stock_code + '.SZ'  # 默认深市
    elif market == 'hk':
        secucode = stock_code + '.HK'

    # 🔴 北交所迁码（2026-10-21 实测根因）：830799/835185 等 8/4 开头老代码在
    # 东财新接口（RPT_LICO_FN_CPD）返回 0 条；同一公司 920xxx 新代码有 60+ 期。
    # 解析到当前代码后再取数，否则 records=0 会连带盈利预测/SOTP/估值全挂。
    bse_migrate_info = None
    if market == 'a' and stock_code.startswith(('8', '4')) and not stock_code.startswith('920'):
        try:
            from bse_migrate import resolve_bse_code
            bse_migrate_info = resolve_bse_code(stock_code)
            if bse_migrate_info.get('switched') and bse_migrate_info.get('current_code'):
                print(f"[北交所迁码] {stock_code} → {bse_migrate_info['current_code']}"
                      f"（{bse_migrate_info.get('name')}）")
                secucode = bse_migrate_info['current_code'] + '.BJ'
        except Exception as _bse_exc:
            print(f"[北交所迁码] 解析失败，按原代码继续: {_bse_exc}")

    params = {
        'reportName': 'RPT_LICO_FN_CPD',
        'columns': 'ALL',
        'filter': f'(SECUCODE="{secucode}")',
        'pageNumber': 1,
        'pageSize': 20,
        'sortTypes': -1,
        'sortColumns': 'REPORTDATE',
        'source': 'WEB',
        'client': 'WEB',
    }

    try:
        raw_result = safe_get(EM_API, params=params, headers=HEADERS, timeout=20)
        records = safe_extract(raw_result, ['result', 'data'], default=[]) or []
        # 🔴 2026-10-21：东财两个域名（datacenter-web / datacenter）可用性不同步，
        # 实测有单次请求空返回（北交所 830799 某轮回 0 条）→ 换域名重试一次。
        if not records:
            _alt = EM_API.replace('datacenter-web.', 'datacenter.') \
                if 'datacenter-web.' in EM_API else EM_API.replace('datacenter.', 'datacenter-web.')
            try:
                raw2 = safe_get(_alt, params=params, headers=HEADERS, timeout=20)
                records = safe_extract(raw2, ['result', 'data'], default=[]) or []
                if records:
                    print(f"[重试] 换域名命中: {_alt.split('/')[2]}")
            except Exception:
                pass
        if records is None:
            records = []
        result['records'] = records

        if not records:
            # ====== 段3：年报PDF提取头底 ======
            result['warnings'].append('东方财富财务指标接口无数据返回，尝试从年报PDF提取')
            print("[溯源] 东方财富API无数据 → 尝试年报PDF提取")

            # 3a. 尝试已有的 annual_report_sections.json
            pdf_data = _extract_financial_from_pdf(stock_code, data_dir)
            if pdf_data:
                result['records'] = pdf_data.get('records', [])
                result['latest'] = pdf_data.get('latest')
                result['summary'] = pdf_data.get('summary', {})
                result['audit_opinion'] = pdf_data.get('audit_opinion')
                result['from_pdf_fallback'] = True
                result['risks'] = pdf_data.get('risks', [])
                result['key_risks'] = pdf_data.get('key_risks', [])
                result['_meta']['source'] = 'local_pdf'
                print(f"[溯源] ✓ 年报PDF提取成功 (local_pdf)")

            # 3b. 如果PDF也没提取到 → 自动下载年报PDF再提取
            if not result['records']:
                print("[溯源] 本地PDF未提取到 → 尝试从源头网站下载年报PDF")
                pdf_result = _download_and_extract_annual(stock_code, market, data_dir)
                if pdf_result and pdf_result.get('records'):
                    result.update(pdf_result)
                    src = pdf_result.get('_meta', {}).get('source', 'cninfo_pdf')
                    result['_meta']['source'] = src
                    print(f"[溯源] ✓ 从源头下载PDF并提取成功 ({src})")

            if not result['records']:
                result['_meta']['source'] = 'all_failed'
                result['warnings'].append('所有财务数据源均失败（API + PDF）')
                return result

        result['latest'] = records[0]

        # 迁码溯源：原始代码 ↔ 取数代码，供报告与质检核对
        if bse_migrate_info and bse_migrate_info.get('switched'):
            result['_meta']['bse_code'] = {
                'input': stock_code,
                'current': bse_migrate_info['current_code'],
                'name': bse_migrate_info.get('name'),
            }

        # ====== 补充资产负债表字段（Sina数据源） ======
        try:
            balance_data = _supplement_balance_sheet(stock_code, market, records)
            if balance_data:
                result['_balance_sheet_source'] = 'sina'
                print(f"[溯源] ✓ 资产负债表字段已从Sina补充")
        except Exception as e:
            result['warnings'].append(f'资产负债表补充失败: {e}')

        # 保存JSON
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
            out = os.path.join(data_dir, 'financial_metrics.json')
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({'records': records, 'latest': records[0]}, f,
                          ensure_ascii=False, indent=2, default=str)

    except Exception as e:
        result['warnings'].append(f'财务接口请求失败: {e}')
        return result

    # =============================================
    # 分析逻辑
    # =============================================
    latest = records[0]
    latest_date = str(latest.get('REPORTDATE', ''))[:10]

    eps = latest.get('BASIC_EPS')
    deduct_eps = latest.get('DEDUCT_BASIC_EPS')
    net_profit = latest.get('PARENT_NETPROFIT', 0)
    revenue = latest.get('TOTAL_OPERATE_INCOME', 0)
    roe = latest.get('WEIGHTAVG_ROE')
    bps = latest.get('BPS')
    gross_margin = latest.get('XSMLL')
    ystz = latest.get('YSTZ')
    sjltz = latest.get('SJLTZ')
    op_cash_ps = latest.get('MGJYXJJE')

    result['summary'] = {
        'report_date': latest_date,
        'eps': eps,
        'deduct_eps': deduct_eps,
        'net_profit_亿': round(net_profit / 1e8, 2) if net_profit else None,
        'revenue_亿': round(revenue / 1e8, 2) if revenue else None,
        'roe_pct': roe,
        'bps': bps,
        'gross_margin_pct': round(gross_margin, 2) if gross_margin else None,
        'revenue_growth_pct': round(ystz, 2) if ystz else None,
        'profit_growth_pct': round(sjltz, 2) if sjltz else None,
        'op_cash_per_share': op_cash_ps,
    }

    # 审计意见：优先从年报PDF提取，否则从财务数据推断
    result['audit_opinion'] = _get_audit_opinion(stock_code, data_dir, eps, roe)

    # 风险信号
    if eps is not None and eps < 0:
        result['risks'].append({'level': 'high', 'dim': '财务', 'signal': f'每股收益为负({eps})，公司亏损'})
        result['key_risks'].append(f'每股收益为负({eps}元)')
    if deduct_eps is not None and deduct_eps < 0:
        result['risks'].append({'level': 'high', 'dim': '财务', 'signal': f'扣非每股收益为负({deduct_eps})，主业亏损'})
    if net_profit is not None and net_profit < 0:
        result['risks'].append({'level': 'high', 'dim': '财务', 'signal': f'净利润为负({round(net_profit/1e8,2)}亿元)'})
    if roe is not None and roe < 0:
        result['risks'].append({'level': 'high', 'dim': '财务', 'signal': f'净资产收益率为负({round(roe,2)}%)，股东回报为负'})
    if sjltz is not None and sjltz < -50:
        result['risks'].append({'level': 'medium', 'dim': '财务', 'signal': f'净利润同比大幅下滑({round(sjltz,2)}%)'})
    if ystz is not None and ystz < -20:
        result['risks'].append({'level': 'medium', 'dim': '财务', 'signal': f'营业收入同比大幅下滑({round(ystz,2)}%)'})
    if gross_margin is not None and gross_margin < 25:
        result['risks'].append({'level': 'medium', 'dim': '财务', 'signal': f'毛利率偏低({round(gross_margin,2)}%)'})

    # 历史对比（近4期）
    if len(records) >= 4:
        for i in range(min(3, len(records) - 1)):
            prev = records[i + 1]
            curr = records[i]
            prev_eps = prev.get('BASIC_EPS')
            curr_eps = curr.get('BASIC_EPS')
            if prev_eps and curr_eps and prev_eps > 0 and curr_eps < 0:
                result['risks'].append({
                    'level': 'high', 'dim': '财务',
                    'signal': f'{curr.get("REPORTDATE","")[:10]}由盈转亏（EPS: {prev_eps}→{curr_eps}）'
                })
                result['key_risks'].append(f'{curr.get("REPORTDATE","")[:10]}由盈转亏')

    return result


def format_financial_summary(data):
    """格式化财务摘要为Markdown文本"""
    if not data or not data.get('latest'):
        return '财务数据暂无可用'

    s = data['summary']
    latest = data['latest']
    date = s.get('report_date', '')
    warnings = data.get('warnings', [])
    risks = data.get('risks', [])
    key_risks = data.get('key_risks', [])

    lines = [
        f"**报告期**: {date}",
        f"**每股收益(EPS)**: {s.get('eps')}元 | 扣非: {s.get('deduct_eps')}元",
        f"**净利润**: {s.get('net_profit_亿')}亿元",
        f"**营业收入**: {s.get('revenue_亿')}亿元",
        f"**净资产收益率(ROE)**: {s.get('roe_pct')}%",
        f"**每股净资产(BPS)**: {s.get('bps')}元",
        f"**销售毛利率**: {s.get('gross_margin_pct')}%",
        f"**营收增速**: {s.get('revenue_growth_pct')}%",
        f"**净利增速**: {s.get('profit_growth_pct')}%",
        f"**每股经营现金流**: {s.get('op_cash_per_share')}元",
    ]

    if key_risks:
        lines.append('\n**⚠️ 关键风险**:')
        for r in key_risks:
            lines.append(f'- {r}')

    if warnings:
        lines.append('\n**⚠️ 警告**:')
        for w in warnings:
            lines.append(f'- {w}')

    if risks:
        lines.append('\n**🚨 财务风险信号**:')
        for r in risks:
            level = '🔴' if r['level'] == 'high' else '🟡'
            lines.append(f"- {level} {r['signal']}")

    return '\n'.join(lines)


# 向后兼容别名
fetch_financials = fetch_financial_metrics


def _get_audit_opinion(stock_code, data_dir, eps, roe):
    """获取审计意见：优先从年报PDF提取，否则从财务数据推断
    
    优先级：
    1. 年报PDF已下载 → 从PDF前10页提取（覆盖PyMuPDF换行问题）
    2. 年报PDF已下载且有sections → 从audit章节提取（兜底）
    3. 年报PDF已下载且有全文 → 正则搜索annual_report_text.txt
    4. 无PDF → 从EPS/ROE推断（标注"推断"）
    
    核心修复：sections["audit"]通常只含"审计意见 □是䯒否"勾选框，
    不是真正的审计意见正文。真正的意见在年报第2页（董事长致辞）。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print(f"  ⚠️ PyMuPDF 未安装，跳过审计意见提取")
        return {"opinion": "未提取(PyMuPDF未安装)", "basis": "跳过"}
    
    def _extract_from_pdf(pdf_path):
        """从PDF前20页提取审计意见（覆盖PyMuPDF换行问题）"""
        try:
            if not os.path.exists(pdf_path):
                return None
            doc = fitz.open(pdf_path)
            # 审计意见通常在年报前10页，第2页（董事长致辞）必有
            front_text = ''
            for i in range(min(20, len(doc))):
                front_text += doc[i].get_text('text') + '\n'
            doc.close()
            opinion = _parse_audit_from_text(front_text)
            if opinion:
                return opinion
            # 备选：搜索全文前200页（用于超长年报）
            doc = fitz.open(pdf_path)
            full_text = ''
            for i in range(min(200, len(doc))):
                full_text += doc[i].get_text('text') + '\n'
            doc.close()
            return _parse_audit_from_text(full_text)
        except Exception:
            return None
    
    if data_dir:
        # === 优先级1：直接从PDF提取（最可靠，覆盖第2页董事长致辞）===
        for pdf_name in ['2025_annual_report.pdf', 'annual_report.pdf',
                          '2024_annual_report.pdf', '2023_annual_report.pdf']:
            pdf_path = os.path.join(data_dir, pdf_name)
            opinion = _extract_from_pdf(pdf_path)
            if opinion:
                return opinion
        
        # === 优先级2：从sections提取（兜底，但sections["audit"]常为空）===
        sections_path = os.path.join(data_dir, 'annual_report_sections.json')
        if os.path.exists(sections_path):
            try:
                with open(sections_path, 'r', encoding='utf-8') as f:
                    sections = json.load(f)
                audit_section = sections.get('audit', {})
                if isinstance(audit_section, dict):
                    content = audit_section.get('content', '')
                else:
                    content = str(audit_section)
                
                if content and not content.startswith('[未找到'):
                    opinion = _parse_audit_from_text(content)
                    if opinion:
                        return opinion
            except Exception as _sexc:
                record(__name__, '_extract_from_pdf', _sexc, note='静默降级')
                pass
        
        # === 优先级3：从annual_report_text.txt提取（覆盖提前创建的场景）===
        text_path = os.path.join(data_dir, 'annual_report_text.txt')
        if os.path.exists(text_path):
            try:
                with open(text_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                opinion = _parse_audit_from_text(text)
                if opinion:
                    return opinion
            except Exception as _sexc:
                record(__name__, '_extract_from_pdf', _sexc, note='静默降级')
                pass
    
    # 降级：从财务数据推断
    return _infer_audit_opinion(eps, roe)


def _parse_audit_from_text(text):
    """从文本中提取审计意见类型

    ⚠️ PyMuPDF提取时，同一行文本可能被拆分成"无<换行>保留意见"的形式。
    解决方案：从"出具了"段落到"审计报告"之间的内容匹配（可跨行）。
    """
    # 1. 优先：从"出具了"段落到"审计报告"之间的内容匹配（覆盖PyMuPDF跨行情况）
    chu_pattern = re.compile(r'出具了[^\n]{0,200}审计报告', re.DOTALL)
    for m in chu_pattern.finditer(text[:50000]):
        chunk = m.group()
        if re.search(r'否定意见', chunk):
            return '否定意见'
        if re.search(r'无法表示意见', chunk):
            return '无法表示意见'

        # 用capture group区分具体类型
        # 方案1: "出具了" + 限定词(强调事项段/持续经营不确定性) + 的 + 无保留意见
        qual_m = re.search(
            r'出具了(带(?:强调事项段|持续经营不确定性段落)的?的?(无保留意见))',
            chunk, re.DOTALL
        )
        if qual_m:
            qualifier = qual_m.group(1)  # e.g. "带强调事项段的" or "带持续经营不确定性段落的"
            if '强调事项段' in qualifier:
                return '带强调事项段的无保留意见'
            elif '持续经营' in qualifier:
                return '带持续经营不确定性段落的无保留意见'
            return '无保留意见'  # 其他

        # 方案2: 标准无保留意见
        if re.search(r'标准无保留意见', chunk):
            return '标准无保留意见'

        # 方案3: 裸"无保留意见"前有"出具了"但没有特定限定词
        if re.search(r'出具了(?!.*?(强调事项段|持续经营|标准))', chunk, re.DOTALL):
            if re.search(r'无\s*保留意见', chunk, re.DOTALL):
                return '带强调事项段的无保留意见'  # 默认

    # 2. 备选：直接在整个文本中搜索（用于处理非"出具了"格式的情况）
    search_text = text[:30000]
    for kw, label in [
        (r'否定意见', '否定意见'),
        (r'无法表示意见', '无法表示意见'),
        # 跨行版："无"和"保留意见"之间允许换行
        (r'带强调事项段的\s*无\s*保留意见', '带强调事项段的无保留意见'),
        (r'带持续经营不确定性段落的无保留意见', '带持续经营不确定性段落的无保留意见'),
        (r'标准无保留意见', '标准无保留意见'),
        # 裸"无保留意见"前必须有"无"字（排除标准无保留）
        (r'(?<=无)\s*保留意见', '带强调事项段的无保留意见'),  # 必须前面是"无"
        (r'无\s*保留意见', '无保留意见'),
        (r'保留意见', '保留意见'),
    ]:
        if re.search(kw, search_text, re.DOTALL):
            return label
    return None


def _infer_audit_opinion(eps, roe):
    """审计意见**不得由财务指标推断**（2026-10-23 修）。

    历史问题：按"EPS<0 且 ROE<0 → 非标准无保留意见"推断，实测把标准无保留意见的
    万达信息（300168，2025 年报立信出具标准无保留）误标成"非标准无保留意见"。
    亏损 ≠ 非标意见，二者是完全不同的事。

    现改为：无真实提取时返回 None，由上层标注"未取到"，禁止编造。
    """
    return None


def _extract_financial_from_pdf(stock_code, data_dir):
    """从年报PDF提取财务数据（北交所fallback）
    
    解析 annual_report_sections.json 的 financial_highlights 章节
    数字格式: 600,068,310.60 (2025) | 515,634,513.51 (2024) | 16.37% (增速)
    """
    print(f"[PDF FALLBACK] data_dir: {data_dir}")
    if not data_dir:
        return {}
    
    # 相对路径 → 尝试从多个可能的基础路径解析
    base_paths = [
        data_dir,
        os.path.join(os.path.dirname(os.path.dirname(__file__)), data_dir),
        os.path.join(os.getcwd(), data_dir),
    ]
    sections_path = None
    for bp in base_paths:
        test_path = os.path.join(bp, 'annual_report_sections.json')
        if os.path.exists(test_path):
            sections_path = test_path
            print(f"[PDF FALLBACK] Found sections at: {sections_path}")
            break
    if not sections_path:
        return {}
    
    try:
        with open(sections_path, 'r', encoding='utf-8') as f:
            sections = json.load(f)
    except:
        return {}

    fh = sections.get('financial_highlights', '')
    if not fh:
        return {}

    import re
    fh_clean = fh.replace(',', '')
    amounts = re.findall(r'\d+\.\d{2}', fh_clean)
    percents = re.findall(r'(\d+\.\d{2})%', fh)

    if not amounts:
        return {}
    result = {'records': [], 'risks': [], 'key_risks': [], 'summary': {}, 'from_pdf_fallback': True}
    
    # 简单的启发式解析
    # 先找营收（最大数字，通常第一个大数字是营收）
    revenues = []
    for a in amounts:
        try:
            val = float(a.replace(',', ''))
            # 营收通常在亿级别（>100000000）
            if val > 100000000:
                revenues.append(val)
        except Exception as _sexc:
            record(__name__, '_extract_financial_from_pdf', _sexc, note='静默降级')
            pass
    
    # 净利润（千万到亿级别）
    net_profits = []
    for a in amounts:
        try:
            val = float(a.replace(',', ''))
            if 1000000 < val <= 100000000:
                net_profits.append(val)
        except Exception as _sexc:
            record(__name__, '_extract_financial_from_pdf', _sexc, note='静默降级')
            pass
    
    # 百分比通常是增速或比率
    growth_rates = []
    for p in percents:
        try:
            growth_rates.append(float(p))
        except Exception as _sexc:
            record(__name__, '_extract_financial_from_pdf', _sexc, note='静默降级')
            pass
    
    # 构建记录（2025年最新一期）
    latest = {}
    if revenues:
        latest['TOTAL_OPERATE_INCOME'] = revenues[0]  # 2025营收
        result['summary']['revenue_亿'] = round(revenues[0] / 1e8, 2)
    if net_profits:
        latest['PARENT_NETPROFIT'] = net_profits[0]  # 2025净利润
        result['summary']['net_profit_亿'] = round(net_profits[0] / 1e8, 2)

    # 百分比解析（基于太湖雪格式：营收增速|毛利率|毛利增速|净利增速）
    if len(growth_rates) >= 1:
        result['summary']['revenue_growth_pct'] = growth_rates[0]
    if len(growth_rates) >= 2:
        result['summary']['gross_margin_pct'] = growth_rates[1] if growth_rates[1] < 100 else None
    if len(growth_rates) >= 4:
        result['summary']['net_profit_growth_pct'] = growth_rates[4] if growth_rates[4] < 200 else None
    
    # 从 management_discussion 提取审计意见
    md = sections.get('management_discussion', '')
    result['audit_opinion'] = _parse_audit_from_text(md) if md else '标准无保留意见（PDF推断）'
    if not result['audit_opinion']:
        result['audit_opinion'] = '标准无保留意见（PDF提取）'
    
    # 风险判断
    if net_profits and net_profits[0] < 0:
        result['risks'].append({'level': 'high', 'dim': '财务', 'signal': f'净利润为负({round(net_profits[0]/1e8,2)}亿元)'})
        result['key_risks'].append(f'净利润为负({round(net_profits[0]/1e8,2)}亿元)')
    
    latest['REPORTDATE'] = '2025-12-31'  # 北交所通常是12月底发年报
    result['records'] = [latest]
    result['latest'] = latest
    
    # 标记来源
    result['summary']['data_source'] = 'PDF提取'
    
    return result


if __name__ == '__main__':
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else '002180'
    data = fetch_financial_metrics(stock, data_dir='output/test')
    print(format_financial_summary(data))


# ============================================================
# 溯源增强：源头下载 + PDF提取（段3b）
# ============================================================
def _download_and_extract_annual(stock_code, market='a', data_dir=None):
    """
    【段3b】当东方财富API和本地PDF均无数据时，
    自动从源头网站下载年报PDF，再提取财务数据。

    溯源下载链（优先级递减）：
      沪深A股 → 巨潮资讯 POST API
              → 上交所 SSE反爬（CDP cookie）
      北交所   → 北交所官网 GET（已验证）
      港股     → 港交所披露易 Playwright

    Returns: 完整 financial result dict，带 _meta.source 标注
    """
    from datetime import datetime
    from scripts.annual_extract import extract_all_sections
    from scripts.source_tracker import download_annual_pdf_traced, SOURCE_LABELS

    print(f"[溯源] 源头下载年报PDF: stock={stock_code} market={market}")

    # Step 1: 下载年报PDF
    pdf_result = download_annual_pdf_traced(
        stock_code=stock_code,
        market=market,
        year=datetime.now().year - 1,  # 默认去年
        save_dir=data_dir
    )

    if pdf_result.get('error') or not pdf_result.get('pdf_path'):
        print(f"[溯源] ❌ 年报PDF下载全部失败: {pdf_result.get('error', 'unknown')}")
        return {'_meta': {'source': 'all_failed', 'error': pdf_result.get('error')}}

    pdf_path = pdf_result['pdf_path']
    pdf_source = pdf_result.get('source', 'unknown')
    print(f"[溯源] ✓ PDF下载成功: {pdf_path} (来源: {SOURCE_LABELS.get(pdf_source, pdf_source)})")

    # Step 2: 提取章节（22章节，包含财务摘要）
    sections = extract_all_sections(pdf_path)

    if not sections:
        print(f"[溯源] ❌ PDF章节提取失败")
        return {'_meta': {'source': pdf_source + '_extract_failed'}}

    # Step 3: 保存 sections.json（标注来源）
    if data_dir:
        sections_out = os.path.join(data_dir, 'annual_report_sections.json')
        sections['_meta'] = sections.get('_meta', {})
        sections['_meta']['pdf_source'] = pdf_source
        sections['_meta']['pdf_path'] = pdf_path
        sections['_meta']['pdf_fetched_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(sections_out, 'w', encoding='utf-8') as f:
                json.dump(sections, f, ensure_ascii=False, indent=2, default=str)
            print(f"[溯源] ✓ 章节已保存: {sections_out}")
        except Exception as e:
            print(f"[WARN] 章节保存失败: {e}")

    # Step 4: 从 sections 提取财务数据
    result = _extract_financial_from_pdf(stock_code, data_dir)

    # 溯源标注
    result['_meta'] = result.get('_meta', {})
    result['_meta']['source'] = pdf_source   # 'cninfo_pdf' | 'sse' | 'bse_cn' | 'hkex_pw'
    result['_meta']['pdf_source'] = pdf_source
    result['_meta']['pdf_path'] = pdf_path
    result['_meta']['pdf_fetched_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result['_meta']['sections_count'] = len([k for k in sections.keys() if not k.startswith('_')])
    result['from_pdf_fallback'] = True

    # 审计意见：优先从PDF提取
    if not result.get('audit_opinion'):
        # 从PDF全文再搜一次
        audit_text = sections.get('audit', '') or sections.get('audit_report', '') or ''
        if not audit_text:
            # 尝试全文搜索
            import fitz
            try:
                doc = fitz.open(pdf_path)
                full_text = ''
                for page in doc:
                    full_text += page.get_text('text') + '\n'
                doc.close()
                audit_text = full_text
            except Exception as _sexc:
                record(__name__, '_download_and_extract_annual', _sexc, note='静默降级')
                pass
        if audit_text:
            result['audit_opinion'] = _parse_audit_from_text(audit_text)

    print(f"[溯源] ✓ 财务提取完成: source={pdf_source}, records={len(result.get('records', []))}")
    return result


def fetch_financial_with_trace(stock_code, market='a', data_dir=None):
    """
    带完整溯源轨迹的财务获取（供外部调用）

    流程：
      1. 本地缓存 → 东方财富API → 年报PDF（本地已有 → 源头下载）
      2. 每一步都打印溯源轨迹
      3. 返回完整 result + trace 列表

    Returns: (result_dict, trace_list)
    """
    from scripts.source_tracker import SourceTracker

    tracker = SourceTracker(stock_code, market, data_dir)

    def api_fetch():
        return fetch_financial_metrics(stock_code, market, data_dir,
                                       skip_pdf=False, enable_tracking=False)

    def pdf_fetch():
        return _download_and_extract_annual(stock_code, market, data_dir)

    result = tracker.get(
        dim='financial_metrics',
        fetch_func=api_fetch,
        fallback_funcs=[pdf_fetch],
        cache_key='financials.json'
    )

    return result, tracker.get_trace()


def _supplement_balance_sheet(stock_code, market, records):
    """用Sina资产负债表数据补充东方财富缺少的字段
    
    东方财富 RPT_LICO_FN_CPD 只返回利润表/现金流表关键字段，
    缺少：应收账款、其他应收款、总资产、总负债、短期/长期借款等。
    从新浪财经资产负债表API补充这些字段到 records 中。
    """
    try:
        import akshare as ak
    except ImportError:
        return None
    
    # Sina股票代码格式：sh/sz/bj + 6位代码
    if market == 'hk' or market == 'us':
        return None  # Sina仅支持A股
    
    prefix = 'sh' if stock_code[:2] in ['60', '68'] else ('bj' if stock_code[0] in ['8', '4'] else 'sz')
    sina_code = f'{prefix}{stock_code}'
    
    try:
        df = ak.stock_financial_report_sina(stock=sina_code, symbol="资产负债表")
    except Exception:
        return None
    
    if df is None or df.empty:
        return None
    
    # Sina列名映射 → EM字段名（兼容cross_validator）
    field_map = {
        '应收账款': 'ACCOUNTS_RECE',
        '其他应收款': 'OTHER_RECE',
        '其他应收款(合计)': 'OTHER_RECE_TOTAL',
        '流动资产合计': 'TOTAL_CURRENT_ASSETS',
        '非流动资产合计': 'TOTAL_NONCURRENT_ASSETS',
        '短期借款': 'SHORT_LOAN',
        '长期借款': 'LONG_LOAN',
        '所有者权益(或股东权益)合计': 'TOTAL_PARENT_EQUITY',
        '负债和所有者权益(或股东权益)总计': 'TOTAL_ASSETS',
        '流动负债合计': 'TOTAL_CURRENT_LIAB',
        '非流动负债合计': 'TOTAL_NONCURRENT_LIAB',
        '存货': 'INVENTORY',
        '预付款项': 'PREPAYMENT',
        '合同资产': 'CONTRACT_ASSETS',
    }
    
    # 按报告日匹配
    supplemented = 0
    for rec in records:
        report_date = str(rec.get('REPORTDATE', ''))[:10]
        if not report_date:
            continue
        
        # 在Sina数据中找匹配的报告期
        matched_row = None
        for _, row in df.iterrows():
            sina_date_raw = str(row.get('报告日', ''))
            # Sina日期格式可能为 '20251231' 或 '2025-12-31'，统一处理
            if len(sina_date_raw) == 8 and sina_date_raw.isdigit():
                sina_date = f'{sina_date_raw[:4]}-{sina_date_raw[4:6]}-{sina_date_raw[6:8]}'
            else:
                sina_date = sina_date_raw[:10]
            # 匹配逻辑：年-月一致即可（年报/中报/季报）
            if sina_date and report_date[:7] == sina_date[:7]:
                matched_row = row
                break
        
        if matched_row is None:
            continue
        
        # 补充缺失字段
        for sina_col, em_col in field_map.items():
            if rec.get(em_col) is None and sina_col in matched_row.index:
                val = matched_row[sina_col]
                if val is not None and str(val) != 'nan':
                    try:
                        rec[em_col] = float(val)
                        supplemented += 1
                    except (ValueError, TypeError):
                        pass
    
    return supplemented


def _build_financial_comparison_table(records, multi_year_data=None):
    """构建多年财务对比HTML表格"""
    if not records:
        return ""

    display_records = records[:4]

    rows = []
    for r in display_records:
        rdate = str(r.get('REPORTDATE', ''))[:10]
        rev = r.get('TOTAL_OPERATE_INCOME')
        np = r.get('PARENT_NETPROFIT')
        gm = r.get('GROSS_PROFIT_RATIO') or r.get('XSMLL')
        roe = r.get('WEIGHTAVG_ROE')
        eps = r.get('BASIC_EPS')

        rev_yi = round(float(rev) / 1e8, 2) if rev else None
        np_yi = round(float(np) / 1e8, 2) if np else None

        rows.append({
            'date': rdate,
            'revenue': rev_yi,
            'net_profit': np_yi,
            'gross_margin': round(float(gm), 2) if gm else None,
            'roe': round(float(roe), 2) if roe else None,
            'eps': round(float(eps), 4) if eps else None,
        })

    if multi_year_data and multi_year_data.get('trend'):
        trend = multi_year_data['trend']
        ystz = trend.get('ystz_series', [])
        profit_series = trend.get('profit_series', [])
        for i, row in enumerate(rows):
            if i < len(ystz) and ystz[i] and len(ystz[i]) > 1:
                row['revenue_growth'] = round(ystz[i][1], 2) if ystz[i][1] is not None else None
            if i < len(profit_series) and profit_series[i] and len(profit_series[i]) > 1:
                if row['net_profit'] is None and profit_series[i][1]:
                    row['net_profit'] = round(profit_series[i][1] / 1e8, 2)

    html = '<table class="fin-table"><thead><tr>'
    html += '<th>报告期</th><th>营收(亿)</th><th>净利润(亿)</th><th>毛利率(%)</th><th>ROE(%)</th><th>EPS(元)</th>'
    html += '</tr></thead><tbody>'
    for row in rows:
        html += '<tr>'
        html += f'<td>{row["date"]}</td>'
        html += f'<td>{row["revenue"] if row["revenue"] is not None else "N/A"}</td>'
        html += f'<td>{row["net_profit"] if row["net_profit"] is not None else "N/A"}</td>'
        html += f'<td>{row["gross_margin"] if row["gross_margin"] is not None else "N/A"}</td>'
        html += f'<td>{row["roe"] if row["roe"] is not None else "N/A"}</td>'
        html += f'<td>{row["eps"] if row["eps"] is not None else "N/A"}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


def _generate_financial_ai_narrative(data, multi_year_data=None):
    """生成财务分析AI叙事"""
    records = data.get('records', [])
    summary = data.get('summary', {})
    audit = data.get('audit_opinion', '')
    key_risks = data.get('key_risks', [])

    evidence_parts = []
    evidence_parts.append(f"审计意见: {audit}")

    if summary:
        evidence_parts.append(f"营收: {summary.get('revenue_亿', 'N/A')}亿 | 净利润: {summary.get('net_profit_亿', 'N/A')}亿 | 毛利率: {summary.get('gross_margin_pct', 'N/A')}%")

    for r in records[:4]:
        rdate = str(r.get('REPORTDATE', ''))[:10]
        rev = round(float(r.get('TOTAL_OPERATE_INCOME', 0)) / 1e8, 2) if r.get('TOTAL_OPERATE_INCOME') else 'N/A'
        np = round(float(r.get('PARENT_NETPROFIT', 0)) / 1e8, 2) if r.get('PARENT_NETPROFIT') else 'N/A'
        gm = round(float(r.get('GROSS_PROFIT_RATIO', 0)), 2) if r.get('GROSS_PROFIT_RATIO') else 'N/A'
        evidence_parts.append(f"{rdate}: 营收{rev}亿, 净利{np}亿, 毛利率{gm}%")

    if multi_year_data and multi_year_data.get('trend'):
        trend = multi_year_data['trend']
        cagr_rev = trend.get('revenue_cagr_pct')
        cagr_pro = trend.get('profit_cagr_pct')
        if cagr_rev is not None:
            evidence_parts.append(f"营收CAGR: {cagr_rev:+.2f}%")
        if cagr_pro is not None:
            evidence_parts.append(f"净利润CAGR: {cagr_pro:+.2f}%")

    if multi_year_data and multi_year_data.get('cashflow_quality'):
        cf = multi_year_data['cashflow_quality']
        evidence_parts.append(f"现金流质量: {cf.get('quality_signal', 'N/A')} (经营CF/净利比: {cf.get('avg_cf_netprofit_ratio', 'N/A')})")

    if key_risks:
        evidence_parts.append(f"风险信号: {'; '.join(key_risks[:3])}")

    if multi_year_data and multi_year_data.get('warnings'):
        evidence_parts.append(f"财务预警: {'; '.join(multi_year_data['warnings'][:3])}")

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司的财务数据，请写一段专业的财务分析解读（300-500字）。

要求：
1. 分析营收和利润趋势（增长/下滑/拐点）
2. 评估盈利能力（毛利率、ROE变化）
3. 评估现金流质量
4. 指出关键风险和异常信号
5. 语言专业、客观、有洞察力

===== 财务数据 =====
{evidence_block}
===== 数据结束 =====

请输出财务分析解读："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券商财务分析师，擅长深度解读上市公司财务数据。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [财务AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建财务数据证据块（供统一AI分析器使用）"""
    parts = []
    records = data.get('records', [])
    summary = data.get('summary', {})
    audit = data.get('audit_opinion', '')
    key_risks = data.get('key_risks', [])

    parts.append(f"审计意见: {audit}")
    if summary:
        parts.append(f"营收: {summary.get('revenue_亿', 'N/A')}亿 | 净利润: {summary.get('net_profit_亿', 'N/A')}亿 | 毛利率: {summary.get('gross_margin_pct', 'N/A')}%")

    for r in records[:4]:
        rdate = str(r.get('REPORTDATE', ''))[:10]
        rev = round(float(r.get('TOTAL_OPERATE_INCOME', 0)) / 1e8, 2) if r.get('TOTAL_OPERATE_INCOME') else 'N/A'
        np = round(float(r.get('PARENT_NETPROFIT', 0)) / 1e8, 2) if r.get('PARENT_NETPROFIT') else 'N/A'
        gm = round(float(r.get('GROSS_PROFIT_RATIO') or r.get('XSMLL') or 0), 2) if (r.get('GROSS_PROFIT_RATIO') or r.get('XSMLL')) else 'N/A'
        parts.append(f"{rdate}: 营收{rev}亿, 净利{np}亿, 毛利率{gm}%")

    multi_year = (findings or {}).get('multi_year_trend', {})
    if multi_year and multi_year.get('trend'):
        trend = multi_year['trend']
        if trend.get('revenue_cagr_pct') is not None:
            parts.append(f"营收CAGR: {trend['revenue_cagr_pct']:+.2f}%")
        if trend.get('profit_cagr_pct') is not None:
            parts.append(f"净利润CAGR: {trend['profit_cagr_pct']:+.2f}%")
    if multi_year and multi_year.get('cashflow_quality'):
        cf = multi_year['cashflow_quality']
        parts.append(f"现金流质量: {cf.get('quality_signal', 'N/A')} (经营CF/净利比: {cf.get('avg_cf_netprofit_ratio', 'N/A')})")

    if key_risks:
        parts.append(f"风险信号: {'; '.join(key_risks[:3])}")
    if multi_year and multi_year.get('warnings'):
        parts.append(f"财务预警: {'; '.join(multi_year['warnings'][:3])}")

    return '\n'.join(parts)


def generate_report_section(data: dict, multi_year_data=None, batch_analysis=None) -> list:
    lines = []
    lines.append("## 财务报表分析")
    lines.append("")

    audit = data.get('audit_opinion', '未知')
    lines.append(f"**审计意见**: {audit}")
    lines.append("")

    records = data.get('records', [])
    if records:
        table_html = _build_financial_comparison_table(records, multi_year_data)
        if table_html:
            lines.append("### 近三年+最新一期财务对比")
            lines.append("")
            lines.append(table_html)
            lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('financial'):
        ai_narrative = batch_analysis['financial']
    else:
        ai_narrative = _generate_financial_ai_narrative(data, multi_year_data)

    if ai_narrative:
        lines.append("### 🤖 AI财务分析解读")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    if multi_year_data and multi_year_data.get('cashflow_quality'):
        cf = multi_year_data['cashflow_quality']
        cf_avg = cf.get('avg_cf_netprofit_ratio')
        cf_signal = cf.get('quality_signal', '数据不足')
        if cf_avg is not None:
            lines.append("### 现金流质量")
            lines.append("")
            lines.append(f"- 经营CF/净利润比率: {cf_avg:.2f} → {cf_signal}")
            lines.append("")

    if multi_year_data and multi_year_data.get('warnings'):
        lines.append("### ⚠️ 财务预警信号")
        lines.append("")
        for w in multi_year_data['warnings']:
            lines.append(f"- {w}")
        lines.append("")

    if multi_year_data and multi_year_data.get('risks'):
        lines.append("### 风险明细")
        lines.append("")
        for r in multi_year_data['risks']:
            icon = "🔴" if r.get("level") == "high" else "🟡"
            lines.append(f"- {icon} [{r.get('dim', '')}] {r.get('signal', '')}")
        lines.append("")

    key_risks = data.get('key_risks', [])
    if key_risks and not (multi_year_data and multi_year_data.get('risks')):
        lines.append("**⚠️ 财务风险信号**:")
        for r in key_risks:
            lines.append(f"- {r}")
        lines.append("")

    return lines

