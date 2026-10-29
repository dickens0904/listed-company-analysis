# -*- coding: utf-8 -*-
"""
模块7：监管历史追溯
问询函/处罚/核查意见/监管措施（A股/北交所）
+ 港股：HKEXnews 公告标题关键词扫描（2026-10-21）
+ 美股：SEC 执法/新闻通稿 RSS 匹配（2026-10-21）
"""
import sys, json, requests, re, time
sys.stdout.reconfigure(encoding='utf-8')

# 港股：公司自身公告里与监管/纪律相关的标题关键词（繁体+简体）
_HK_REG_KEYWORDS = ['紀律', '監管', '調查', '制裁', '停牌', '復牌', '除牌', '合規',
                    '监管', '调查', '停牌', '复牌', '处罚', '處罰']

# 美股：SEC 执法/新闻通稿 RSS
_SEC_RSS = [
    ('litigation_release', 'https://www.sec.gov/enforcement-litigation/litigation-releases/rss'),
    ('press_release', 'https://www.sec.gov/news/pressreleases.rss'),
]


def fetch_hk_regulatory(stock_code, years: int = 5):
    """港股监管相关公告：HKEXnews 标题关键词扫描。

    ⚠️ 边界（必须写进报告）：这是**公司自己发布的公告**（如"有关监管调查的公告"），
    不是港交所/证监会的处分数据库。**未命中 ≠ 无违规**——交易所纪律行动发布在
    HKEX/SFC 官网而非公司公告。
    """
    out = []
    try:
        from hkex_announcements import _hkex_stock_id
        sid = _hkex_stock_id(stock_code)
    except Exception as e:
        return {'records': [], 'count': 0, 'status': 'unavailable',
                'error': f'HKEX stockId 解析失败: {e}'}
    if not sid:
        return {'records': [], 'count': 0, 'status': 'unavailable',
                'error': 'HKEX stockId 未解析到'}
    now_y = time.localtime().tm_year
    H = {'User-Agent': 'Mozilla/5.0',
         'Referer': 'https://www1.hkexnews.hk/search/titlesearch.xhtml'}
    seen = set()
    for kw in _HK_REG_KEYWORDS:
        p = {'sortDir': '0', 'sortByOptions': 'DateTime', 'category': '0', 'market': 'SEHK',
             'stockId': sid, 'documentType': '-1',
             'fromDate': f'{now_y - years}0101', 'toDate': f'{now_y}1231',
             'title': kw, 'searchType': '0',
             't1code': '-2', 't2Gcode': '-2', 't2code': '-2',
             'rowRange': '50', 'lang': 'ZH'}
        try:
            j = requests.get('https://www1.hkexnews.hk/search/titleSearchServlet.do',
                             params=p, headers=H, timeout=25).json()
            raw = j.get('result')
            data = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            continue
        for d in data:
            title = d.get('TITLE') or ''
            link = d.get('FILE_LINK') or ''
            key = (title, str(d.get('DATE_TIME'))[:10])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                'date': str(d.get('DATE_TIME') or '')[:10],
                'title': title,
                'type': '公司公告(监管相关)',
                'url': ('https://www1.hkexnews.hk' + ('' if link.startswith('/') else '/') + link
                        if link and not link.startswith('http') else link),
                'source': 'hkexnews_title_keyword',
                'keyword': kw,
            })
    out.sort(key=lambda x: x.get('date') or '', reverse=True)
    return {
        'records': out, 'count': len(out), 'status': 'ok',
        'window': f'近 {years} 年 HKEXnews 公告标题关键词（{len(set(_HK_REG_KEYWORDS))} 组）',
        '_note': ('仅覆盖公司自身发布的监管相关公告；交易所纪律行动/SFC 处分不在公告库，'
                  '**未命中不等于无违规**，重要标的须人工查 SFC 新闻与 HKEX 纪律行动页'),
        '_links': {
            'SFC 新闻': 'https://www.sfc.hk/en/News-and-announcements',
            'HKEX 上市规则执行': 'https://www.hkex.com.hk/Listing/Rules-and-Guidance/Disciplinary-and-Enforcement',
        },
    }


def _match_sec_rss(items, keys, kind: str):
    """从 SEC RSS 的 <item> 列表里按公司名/ticker 匹配（抽出来便于单测）"""
    recs = []
    for it in items:
        title = (re.search(r'<title>(.*?)</title>', it, re.S) or [None, ''])[1]
        date = (re.search(r'<pubDate>(.*?)</pubDate>', it, re.S) or [None, ''])[1]
        link = (re.search(r'<link>(.*?)</link>', it, re.S) or [None, ''])[1]
        title = re.sub(r'<!\[CDATA\[|\]\]>', '', str(title)).strip()
        hit = next((k for k in keys if k and k.lower() in title.lower()), None)
        if hit:
            recs.append({
                'date': str(date)[:16], 'title': title,
                'type': 'SEC 执法/新闻通稿', 'url': str(link).strip(),
                'source': f'sec_rss:{kind}', 'matched': hit,
            })
    return recs


def fetch_us_regulatory(ticker: str):
    """美股：SEC 执法/新闻通稿 RSS 按公司名匹配。

    ⚠️ 边界：RSS 只含**最近约 25 条**（约 1–2 周）。命中即可确证有执法动作；
    未命中**不能**推断"无违规"——历史执法须用 SEC EDGAR 全文检索或执法页人工查。
    """
    name = ''
    try:
        from us_financial import get_us_10k_detail
        name = (get_us_10k_detail(ticker) or {}).get('company') or ''
    except Exception:
        pass
    # 去掉法律后缀，提高匹配率
    core = re.sub(r'\b(Inc\.?|Corp\.?|Corporation|Company|Ltd\.?|PLC|Holdings?|Group)\b',
                  '', name, flags=re.I).strip().rstrip(',').strip()
    keys = [k for k in {name.strip(), core, ticker.upper()} if k and len(k) >= 3]

    recs, feeds_ok = [], []
    H = {'User-Agent': 'research contact@example.com'}
    for kind, url in _SEC_RSS:
        try:
            r = requests.get(url, headers=H, timeout=25)
            if r.status_code != 200:
                continue
            items = re.findall(r'<item>(.*?)</item>', r.text, re.S)
            feeds_ok.append(f'{kind}:{len(items)}')
        except Exception:
            continue
        recs.extend(_match_sec_rss(items, keys, kind))
    return {
        'records': recs, 'count': len(recs),
        'status': 'ok' if feeds_ok else 'unavailable',
        'window': f'SEC 执法/新闻 RSS 最近通稿（{", ".join(feeds_ok) or "不可用"}）',
        '_note': ('RSS 仅覆盖最近约 1–2 周通稿：命中即确证有执法动作；未命中**不能**推断无违规。'
                  '历史执法须查 SEC 执法页或 EDGAR 全文检索'),
        '_links': {
            'SEC 执法行动': 'https://www.sec.gov/enforcement-litigation',
            'SEC 全文检索': 'https://efts.sec.gov/LATEST/search-index?q=%22'
                            + (core or ticker) + '%22',
        },
    }


def fetch_regulatory_history(stock_code, market='a', data_dir=None):
    """追溯监管历史"""
    # 港美股分流（2026-10-21）：A 股走东财公告，港美股走各自专用源
    if market == 'hk':
        r = fetch_hk_regulatory(stock_code)
        r.update({'stock_code': stock_code, 'market': 'hk'})
        r.setdefault('summary', {})
        return r
    if market == 'us':
        r = fetch_us_regulatory(stock_code)
        r.update({'stock_code': stock_code, 'market': 'us'})
        r.setdefault('summary', {})
        return r

    result = {'stock_code': stock_code, 'records': [], 'count': 0, 'summary': {}}

    # 北交所迁码（2026-10-21）：8xxxxx/4xxxxx 老代码在东财公告接口查不到，先迁 920xxx
    _code = stock_code
    if str(stock_code).startswith(('8', '4')) and not str(stock_code).startswith('920'):
        try:
            from bse_migrate import resolve_bse_code
            _m = resolve_bse_code(stock_code)
            if _m.get('switched') and _m.get('current_code'):
                _code = _m['current_code']
        except Exception:
            pass

    url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?cb=&sr=-1&page_size=200&page_index=1&ann_type=A"
           f"&client_source=web&f_node=0&s_node=0&stock_list={_code}")
    try:
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://data.eastmoney.com/'
        }, timeout=20)
        r.encoding = 'utf-8'
        data = r.json()
        items = data.get('data', {}).get('list', [])
    except:
        items = []

    reg_keywords = [
        '问询函', '监管函', '关注函', '核查意见',
        '警示函', '行政处罚', '立案', '整改',
        '自律监管', '公开谴责', '通报批评',
        '非标准审计报告', '审计问题', '保留意见',
        '强调事项', '持续经营', '内部控制',
    ]

    records = []
    for item in items:
        title = item.get('title', '') or item.get('title_ch', '')
        notice_date = item.get('notice_date', '')[:10]
        art_code = item.get('art_code', '')
        columns = [c.get('column_name', '') for c in item.get('columns', [])]
        col_str = '|'.join(columns)

        is_reg = any(k in title for k in reg_keywords)
        is_reg_cat = any(c in col_str for c in ['监管', '核查', '问询', '核查意见'])

        if is_reg or is_reg_cat:
            records.append({
                'date': notice_date,
                'title': title,
                'art_code': art_code,
                'category': col_str,
                'severity': _assess_severity(title, col_str),
                'type': _classify_reg(title, col_str),
            })

    result['records'] = records
    result['count'] = len(records)
    result['summary'] = _summarize_reg(records)

    # 港美股无脚本源：显式标缺口，禁止把"空"读成"无监管风险"
    if market not in ('a', 'bse', 'cn'):
        result['_gap'] = ('监管处罚/纪律行动：港股须 HKEX 纪律行动，美股须 SEC enforcement / '
                          'litigation releases；本 skill 暂无脚本源，不得据此判定"无监管风险"')
    elif not result.get('records'):
        result['_note'] = '东财公告源未匹配到监管类公告（可能确无，也可能召回不足，需人工复核）'
    return result


def _classify_reg(title, category):
    """分类监管类型"""
    if '问询函' in title or '问询' in category:
        return '问询函'
    elif '关注函' in title:
        return '关注函'
    elif '核查意见' in title or '核查意见' in category:
        return '保荐机构核查意见'
    elif '行政处罚' in title:
        return '行政处罚'
    elif '警示' in title:
        return '警示函'
    elif '立案' in title:
        return '立案调查'
    elif '公开谴责' in title:
        return '公开谴责'
    elif '非标准' in title or '非标' in title:
        return '非标准审计意见'
    elif '强调事项' in title:
        return '强调事项'
    else:
        return '其他监管事项'


def _assess_severity(title, category):
    """评估监管事项严重程度"""
    if any(k in title for k in ['行政处罚', '立案', '公开谴责']):
        return '🔴 严重'
    elif any(k in title for k in ['问询函']):
        return '🟡 中等'
    elif any(k in title for k in ['关注函', '警示', '核查意见']):
        return '🟡 中等'
    elif any(k in title for k in ['非标准', '保留意见', '强调事项', '持续经营']):
        return '🔴 财务风险'
    else:
        return '🟢 轻微'


def _summarize_reg(records):
    summary = {
        'total': len(records),
        'by_severity': {},
        'by_type': {},
        'latest': records[0] if records else None,
    }
    for r in records:
        summary['by_severity'][r['severity']] = \
            summary['by_severity'].get(r['severity'], 0) + 1
        summary['by_type'][r['type']] = \
            summary['by_type'].get(r['type'], 0) + 1
    return summary


if __name__ == '__main__':
    result = fetch_regulatory_history('002180')
    print(f"监管记录: {result['count']}条")
    for r in result['records']:
        print(f"  {r['date']} [{r['severity']}] {r['title'][:60]}")


def _generate_regulatory_ai_narrative(data):
    """生成监管合规AI综合解读"""
    records = data.get('records', [])
    if not records:
        return ""

    summary = data.get('summary', {})

    evidence_parts = []
    evidence_parts.append(f"监管记录总数: {len(records)}条")

    if summary.get('by_severity'):
        evidence_parts.append(f"严重程度分布: {summary['by_severity']}")
    if summary.get('by_type'):
        evidence_parts.append(f"监管类型分布: {summary['by_type']}")

    severe = [r for r in records if '严重' in r.get('severity', '') or '风险' in r.get('severity', '')]
    if severe:
        evidence_parts.append(f"严重/高风险事项: {len(severe)}条")
        for r in severe[:5]:
            evidence_parts.append(f"  {r.get('date', '')} [{r.get('severity', '')}] {r.get('title', '')[:60]}")

    for r in records[:10]:
        evidence_parts.append(f"{r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:60]}")

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司的监管记录数据，请写一段专业的监管合规分析（200-400字）。

要求：
1. 评估监管风险的整体水平和趋势
2. 分析主要监管事项的性质和影响
3. 关注严重/高风险事项的具体内容
4. 评估合规治理的整体状况
5. 提出投资者应关注的合规风险点

{evidence_block}

请输出监管合规分析："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券互联网合规分析师，擅长解读上市公司监管记录和合规风险。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [监管AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建监管数据证据块"""
    records = data.get('records', [])
    if not records:
        return ""
    summary = data.get('summary', {})
    parts = [f"监管记录总数: {len(records)}条"]
    if summary.get('by_severity'):
        parts.append(f"严重程度分布: {summary['by_severity']}")
    if summary.get('by_type'):
        parts.append(f"监管类型分布: {summary['by_type']}")
    severe = [r for r in records if '严重' in r.get('severity', '') or '风险' in r.get('severity', '')]
    if severe:
        parts.append(f"严重/高风险事项: {len(severe)}条")
        for r in severe[:5]:
            parts.append(f"  {r.get('date', '')} [{r.get('severity', '')}] {r.get('title', '')[:60]}")
    for r in records[:10]:
        parts.append(f"{r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:60]}")
    return '\n'.join(parts)


def generate_report_section(data: dict, batch_analysis=None) -> list:
    lines = []
    lines.append("## 监管历史追溯")
    lines.append("")
    lines.append(f"**监管记录总数**: {data.get('count', 0)}条")
    lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('regulatory'):
        ai_narrative = batch_analysis['regulatory']
    else:
        ai_narrative = _generate_regulatory_ai_narrative(data)

    if ai_narrative:
        lines.append("### 🤖 AI监管合规分析")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    summary = data.get('summary', {})
    if summary.get('by_severity'):
        lines.append("**严重程度分布**:")
        for sev, cnt in summary['by_severity'].items():
            lines.append(f"- {sev}: {cnt}条")
        lines.append("")

    records = data.get('records', [])
    if records:
        lines.append("**监管记录明细**:")
        for r in records[:20]:
            lines.append(f"- **{r.get('date','')}** {r.get('severity','')} [{r.get('type','')}] {r.get('title','')[:70]}")
        lines.append("")

    return lines
