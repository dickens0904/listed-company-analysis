# -*- coding: utf-8 -*-
"""
未上市公司全景分析模块
数据源：天眼查工商 + CSRC辅导备案 + 中国执行信息公开网 + 裁判文书网
用法：python analyze.py --company "珠海极海微电子" --type unlisted [--dims basic,equity,financing,legal,news,ipo,esop]
"""
import sys, os, re, json, time, urllib.parse
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

from scripts.safe_request import safe_get, safe_post

# ─────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────

def _clean(text):
    """清理HTML实体和多余空白"""
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_amount(s):
    """解析金额字符串：1.2亿 / 500万 / 12000000 → 亿元"""
    if not s:
        return None
    s = str(s).replace(',', '').strip()
    m = re.search(r'([\d.]+)\s*亿', s)
    if m:
        return float(m.group(1))
    m = re.search(r'([\d.]+)\s*万', s)
    if m:
        return float(m.group(1)) / 10000
    m = re.search(r'^[\d.]+$', s)
    if m:
        v = float(m.group(1))
        return v if v > 100 else v / 10000  # 假设 > 100万是小单位
    return None


def _get_tianyancha_headers():
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }


# ─────────────────────────────────────────────
# 维度1: 基本工商信息
# ─────────────────────────────────────────────

def fetch_basic_info(company_name, data_dir=None):
    """
    从天眼查搜索页提取工商基本信息（无需API Key）
    数据源：天眼查搜索结果页
    """
    result = {'source': 'tianyancha', 'company_name': company_name}

    # 方法1：天眼查搜索页（公开可访问，但有反爬）
    search_url = f'https://www.tianyancha.com/cloud-other-information/companyinfo?keyword={urllib.parse.quote(company_name)}'

    # 先尝试天眼查开放接口（非登录）
    try:
        url = f'https://www.tianyancha.com/search/os/{urllib.parse.quote(company_name)}'
        resp = safe_get(url, headers=_get_tianyancha_headers(), timeout=10)
        if resp and resp.status_code == 200:
            text = resp.text
            # 尝试提取公司基本信息片段
            name_match = re.search(r'"name":"([^"]+)"', text)
            if name_match:
                result['name'] = name_match.group(1)

            reg_cap_match = re.search(r'"regCapital":"([^"]+)"', text)
            if reg_cap_match:
                result['registered_capital'] = reg_cap_match.group(1)

            status_match = re.search(r'"businessStatus":"([^"]+)"', text)
            if status_match:
                result['status'] = status_match.group(1)

            est_match = re.search(r'"estiblishTime":(\d+)', text)
            if est_match:
                ts = int(est_match.group(1)) / 1000
                import datetime as dt
                result['established'] = dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')

            legal_match = re.search(r'"legalRepresentativeName":"([^"]+)"', text)
            if legal_match:
                result['legal_representative'] = legal_match.group(1)

            # 提取简介
            scope_match = re.search(r'"scope":"([^"]+)"', text)
            if scope_match:
                result['business_scope'] = scope_match.group(1)[:500]

            # 提取统一社会信用代码
            credit_match = re.search(r'"creditCode":"([^"]+)"', text)
            if credit_match:
                result['unified_credit_code'] = credit_match.group(1)

    except Exception as e:
        result['error'] = str(e)

    # 方法2：使用 iwencai 已有接口（如果可用）
    if not result.get('name'):
        try:
            import os as _os
            iwencai_key = os.environ.get('IWENCAI_API_KEY', '')
            if iwencai_key:
                payload = {
                    'question': f'{company_name} 基本信息 统一社会信用代码 注册资本 成立日期 法定代表人 经营状态',
                    'appid': 'open_index_search',
                    'client': 'pc',
                    'version': '5.0'
                }
                resp2 = safe_post('https://openapi.iwencai.com/v1/query2data',
                                 json=payload, headers={'appid': 'open_index_search', 'version': '5.0'},
                                 timeout=15)
                if resp2 and resp2.status_code == 200:
                    data = resp2.json()
                    result['iwencai'] = data
                    result['source'] = 'iwencai_fallback'
        except Exception:
            pass

    return result


# ─────────────────────────────────────────────
# 维度2: 股权结构（股东穿透）
# ─────────────────────────────────────────────

def fetch_equity_structure(company_name, data_dir=None):
    """
    从天眼查提取股东结构
    数据源：天眼查公司详情页
    """
    result = {'source': 'tianyancha', 'company_name': company_name}
    shareholders = []

    try:
        # 天眼查公司详情页（需cookie，但搜索页也有公开数据）
        search_url = f'https://www.tianyancha.com/search/os/{urllib.parse.quote(company_name)}'
        resp = safe_get(search_url, headers=_get_tianyancha_headers(), timeout=10)

        if resp and resp.status_code == 200:
            text = resp.text
            # 提取股东JSON数据块
            holder_blocks = re.findall(r'"stockList":\[(.*?)\]', text)
            if not holder_blocks:
                holder_blocks = re.findall(r'"holderList":\[(.*?)\]', text)

            for block in holder_blocks[:10]:  # 取前10大股东
                items = re.findall(r'\{"name":"([^"]+)","percent":([\d.]+)', block)
                for name, pct in items:
                    shareholders.append({
                        'name': name,
                        'share_pct': float(pct) if pct.replace('.', '').isdigit() else None
                    })

            if not shareholders:
                # 备选：提取HTML中的股东列表
                holder_section = re.search(r'股东信息.*?</tr>(.*?)</table>', text, re.DOTALL)
                if holder_section:
                    rows = re.findall(r'<td[^>]*>(.*?)</td>', holder_section.group(1))
                    for i in range(0, len(rows) - 1, 2):
                        name = _clean(rows[i])
                        pct = _clean(rows[i + 1]) if i + 1 < len(rows) else ''
                        if name and pct:
                            shareholders.append({'name': name, 'share_pct': pct})

    except Exception as e:
        result['error'] = str(e)

    result['shareholders'] = shareholders
    result['count'] = len(shareholders)
    return result


# ─────────────────────────────────────────────
# 维度3: 融资历史
# ─────────────────────────────────────────────

def fetch_financing_history(company_name, data_dir=None):
    """
    提取融资历史（烯牛数据/IT橘子/天眼查）
    数据源：天眼查融资信息 + 烯牛数据公开接口
    """
    result = {'source': 'multiple', 'company_name': company_name}
    rounds = []

    # 方法1：天眼查融资信息
    try:
        search_url = f'https://www.tianyancha.com/search/os/{urllib.parse.quote(company_name)}'
        resp = safe_get(search_url, headers=_get_tianyancha_headers(), timeout=10)
        if resp and resp.status_code == 200:
            text = resp.text
            # 提取融资轮次
            round_blocks = re.findall(r'"round":"([^"]+)".*?"date":(\d+).*?"amount":"([^"]+)"', text)
            for round_name, ts, amount in round_blocks[:20]:
                date = datetime.fromtimestamp(int(ts) / 1000).strftime('%Y-%m') if ts else ''
                rounds.append({
                    'round': round_name,
                    'date': date,
                    'amount': amount,
                    'source': 'tianyancha'
                })
    except Exception as e:
        result['tyc_error'] = str(e)

    # 方法2：烯牛数据公开搜索
    try:
        xiniu_url = f'https://www.xiniudata.com/api/search/company?q={urllib.parse.quote(company_name)}'
        resp2 = safe_get(xiniu_url,
                         headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
                         timeout=10)
        if resp2 and resp2.status_code == 200:
            try:
                data = resp2.json()
                result['xiniu'] = data
            except Exception:
                pass
    except Exception as e:
        result['xiniu_error'] = str(e)

    # 方法3：36kr新闻搜索（融资公告）
    try:
        kr_url = f'https://36kr.com/api/search-column/main?keyword={urllib.parse.quote(company_name)}&type=news'
        resp3 = safe_get(kr_url,
                         headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
                         timeout=10)
        if resp3 and resp3.status_code == 200:
            try:
                data = resp3.json()
                if data.get('data', {}).get('items'):
                    items = data['data']['items'][:10]
                    for item in items:
                        rounds.append({
                            'round': item.get('event', ''),
                            'date': item.get('published_at', '')[:7] if item.get('published_at') else '',
                            'amount': item.get('money', ''),
                            'investors': item.get('investors', ''),
                            'source': '36kr'
                        })
            except Exception:
                pass
    except Exception as e:
        result['kr36_error'] = str(e)

    result['rounds'] = rounds
    result['count'] = len(rounds)
    return result


# ─────────────────────────────────────────────
# 维度4: 法律风险（被执行人 + 裁判文书）
# ─────────────────────────────────────────────

def fetch_legal_risks(company_name, data_dir=None):
    """
    查询法律风险：被执行人 + 裁判文书 + 行政处罚
    数据源：中国执行信息公开网 + 裁判文书网 + 天眼查
    """
    result = {'source': 'zxgk+tianyancha', 'company_name': company_name}
    execution_records = []
    judgment_records = []
    admin_penalties = []

    # 方法1：中国执行信息公开网（公开可查）
    try:
        zxgk_url = 'https://zxgk.court.gov.cn/zhixing/search协助查询.do'
        params = {
            'pname': company_name,
            'cardNum': '',
            'j_region': '',
            'page': 1,
        }
        resp = safe_post(zxgk_url, data=params,
                         headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/x-www-form-urlencoded'},
                         timeout=15)
        if resp and resp.status_code == 200:
            text = resp.text
            # 提取被执行人信息
            items = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
            for item in items[1:]:  # 跳过表头
                cells = re.findall(r'<td[^>]*>(.*?)</td>', item, re.DOTALL)
                if len(cells) >= 4:
                    execution_records.append({
                        'case_no': _clean(cells[0]),
                        'amount': _clean(cells[1]),
                        'court': _clean(cells[2]),
                        'date': _clean(cells[3]),
                    })
            result['zxgk_status'] = 'found' if execution_records else 'clean'
    except Exception as e:
        result['zxgk_error'] = str(e)

    # 方法2：天眼查法律诉讼（反爬较轻）
    try:
        tyc_url = f'https://www.tianyancha.com/cloud-other-information/lawsuit?keyword={urllib.parse.quote(company_name)}&page=1'
        resp2 = safe_get(tyc_url, headers=_get_tianyancha_headers(), timeout=10)
        if resp2 and resp2.status_code == 200:
            text = resp2.text
            # 提取裁判文书摘要
            judgments = re.findall(r'"caseNo":"([^"]+)".*?"caseReason":"([^"]+)".*?"amount":"([^"]+)"',
                                    text, re.DOTALL)
            for case_no, reason, amount in judgments[:20]:
                judgment_records.append({
                    'case_no': case_no,
                    'reason': reason,
                    'amount': amount,
                })
    except Exception as e:
        result['tyc_error'] = str(e)

    # 方法3：行政处罚（国家企业信用信息公示系统）
    try:
        # 国家企业信用信息公示系统 - 经营异常名录
        credit_url = f'https://www.gsxt.gov.cn/search?searchword={urllib.parse.quote(company_name)}'
        resp3 = safe_get(credit_url, headers=_get_tianyancha_headers(), timeout=10)
        if resp3 and resp3.status_code == 200:
            result['credit_status'] = 'accessed'
            # 提取风险摘要
            risk_items = re.findall(r'"markName":"([^"]+)"', resp3.text)
            if risk_items:
                result['risk_tags'] = risk_items[:10]
    except Exception as e:
        result['credit_error'] = str(e)

    result['execution_records'] = execution_records
    result['judgment_records'] = judgment_records
    result['admin_penalties'] = admin_penalties
    result['execution_count'] = len(execution_records)
    result['judgment_count'] = len(judgment_records)

    # 风险评级
    total_risk = len(execution_records) * 10 + len(judgment_records) * 2 + len(admin_penalties) * 5
    if total_risk == 0:
        result['legal_risk_level'] = '低'
    elif total_risk <= 10:
        result['legal_risk_level'] = '中低'
    elif total_risk <= 30:
        result['legal_risk_level'] = '中高'
    else:
        result['legal_risk_level'] = '高'

    return result


# ─────────────────────────────────────────────
# 维度5: 新闻舆情
# ─────────────────────────────────────────────

def fetch_news_sentiment(company_name, data_dir=None):
    """
    新闻舆情汇总
    数据源：同花顺问财 + 百度新闻 + 微博
    """
    result = {'source': 'baidu+iwencai', 'company_name': company_name}
    news_items = []

    # 方法1：同花顺问财新闻搜索（已知可用）
    try:
        import os as _os
        iwencai_key = _os.environ.get('IWENCAI_API_KEY', '')
        payload = {
            'question': f'{company_name} 最新新闻 舆情',
            'appid': 'open_index_search',
            'client': 'pc',
            'version': '5.0'
        }
        resp = safe_post('https://openapi.iwencai.com/v1/query2data',
                         json=payload,
                         headers={'appid': 'open_index_search', 'version': '5.0'},
                         timeout=15)
        if resp and resp.status_code == 200:
            data = resp.json()
            # 解析新闻条目
            items = data.get('data', {}).get('result', {}).get('items', [])
            for item in items[:20]:
                if isinstance(item, dict):
                    news_items.append({
                        'title': item.get('title', ''),
                        'date': item.get('datetime', ''),
                        'source': item.get('source', '同花顺'),
                        'sentiment': item.get('sentiment', '中性'),
                        'url': item.get('url', ''),
                    })
            result['iwencai_data'] = data
    except Exception as e:
        result['iwencai_error'] = str(e)

    # 方法2：百度新闻RSS
    try:
        baidu_news_url = f'https://news.baidu.com/ns?word={urllib.parse.quote(company_name)}&tn=news&ie=utf8&rtt=4'
        resp2 = safe_get(baidu_news_url, headers=_get_tianyancha_headers(), timeout=10)
        if resp2 and resp2.status_code == 200:
            text = resp2.text
            # 提取新闻标题和链接
            news_blocks = re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]{5,50})</a>', text)
            seen = set()
            for url, title in news_blocks:
                title = _clean(title)
                if title and title not in seen and len(title) > 5:
                    seen.add(title)
                    news_items.append({
                        'title': title,
                        'url': url,
                        'source': '百度新闻',
                        'date': '',
                        'sentiment': '待分析',
                    })
    except Exception as e:
        result['baidu_error'] = str(e)

    # 去重+限制
    seen_titles = set()
    unique_news = []
    for n in news_items:
        if n['title'] and n['title'] not in seen_titles:
            seen_titles.add(n['title'])
            unique_news.append(n)
    result['news'] = unique_news[:20]
    result['count'] = len(unique_news)

    # 情感分析（简单关键词）
    positive = ['合作', '签约', '增长', '扩张', '获奖', '创新', '突破', '领先']
    negative = ['诉讼', '亏损', '裁员', '欠薪', '违约', '处罚', '整改', '风险', '纠纷']
    pos_count = sum(1 for n in unique_news if any(k in n['title'] for k in positive))
    neg_count = sum(1 for n in unique_news if any(k in n['title'] for k in negative))
    if neg_count > pos_count * 2:
        result['sentiment'] = '偏负面'
    elif pos_count > neg_count * 2:
        result['sentiment'] = '偏正面'
    elif pos_count > neg_count:
        result['sentiment'] = '略偏正面'
    elif neg_count > pos_count:
        result['sentiment'] = '略偏负面'
    else:
        result['sentiment'] = '中性'

    result['pos_count'] = pos_count
    result['neg_count'] = neg_count
    return result


# ─────────────────────────────────────────────
# 维度6: IPO辅导状态（CSRC公示 + 各地证监局）
# ─────────────────────────────────────────────

def fetch_ipo_status(company_name, data_dir=None):
    """
    IPO辅导备案状态查询
    数据源：CSRC辅导监管信息公示 + 各证监局公示
    """
    result = {'source': 'csrc+csrc_regulator', 'company_name': company_name}
    coaching_records = []

    # 方法1：AKShare stock_ipo_tutor_em（覆盖全量5256条，实时更新）
    # 接口：ak.stock_ipo_tutor_em() → DataFrame（含序号/企业名称/辅导机构/辅导状态/
    #   报告类型/派出机构/报告标题/备案日期），无参数，返回最新一期报告
    # 关键：企业名称、辅导状态、派出机构、报告标题（含"第十三期"可推算期数）
    try:
        import akshare as _ak
        import re as _re
        df_tutor = _ak.stock_ipo_tutor_em()
        mask = df_tutor['企业名称'].str.contains(company_name[:6], na=False)
        records_ak = df_tutor[mask]
        if len(records_ak) > 0:
            for _, row in records_ak.iterrows():
                coaching_records.append({
                    'company': str(row.get('企业名称', '')),
                    '辅导机构': str(row.get('辅导机构', '')),
                    '辅导状态': str(row.get('辅导状态', '')),
                    '报告类型': str(row.get('报告类型', '')),
                    '派出机构': str(row.get('派出机构', '')),
                    '报告标题': str(row.get('报告标题', '')),
                    '备案日期': str(row.get('备案日期', '')),
                })
            result['akshare_status'] = 'found'
            result['akshare_total'] = len(records_ak)
            titles = records_ak['报告标题'].tolist()
            period_nums = _re.findall(r'第(.+?)期', ' '.join(titles))
            if period_nums:
                result['period_count'] = max([int(p) for p in period_nums if p.isdigit() and int(p) < 200])
        else:
            result['akshare_status'] = 'not_found'
    except Exception as e:
        result['akshare_error'] = str(e)
        result['akshare_status'] = 'error'

    # 方法2：CSRC辅导监管信息平台（需维护接口）
    try:
        csrc_url = 'https://neris.csrc.gov.cn/ifr/releaselist/companyGuidanceList'
        params = {
            'page': 1,
            'pageSize': 10,
            'companyName': company_name,
        }
        resp = safe_post(csrc_url, json=params,
                         headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json',
                                  'Accept': 'application/json'},
                         timeout=15)
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                records = data.get('data', {}).get('list', []) or data.get('data', []) or []
                for rec in records:
                    coaching_records.append({
                        'company': rec.get('companyName', ''),
                        'stock_code': rec.get('stockCode', '未披露'),
                        'plate': rec.get('plate', '未披露'),
                        'coaching_institution': rec.get('coachingInstitution', ''),
                        'start_date': rec.get('guidanceStartDate', ''),
                        'status': rec.get('status', ''),
                        'regulator': rec.get('supervisor', ''),
                        'report_count': rec.get('reportCount', 0),
                    })
                    result['csrc_status'] = 'found' if records else 'not_found'
            except Exception:
                result['csrc_status'] = 'parse_error'
        else:
            result['csrc_status'] = f'http_{resp.status_code}' if resp else 'no_response'
    except Exception as e:
        result['csrc_error'] = str(e)
        result['csrc_status'] = 'error'

    # 方法3公示页（广东/深圳/北京/上海/浙江等）
    reg_urls = [
        ('广东局', 'https://www.gd.gov.cn/msfczw/zt_952/rdzt/ssgsxx/gggs/pbezfgdjcxt/index.html'),
        ('深圳局', 'http://www.sz.gov.cn/cn/xxgk/zfxxgj/tzgg/index_{}.html'),
        ('北京局', 'http://www.beijing.gov.cn/zhengce/jdxc/'),
        ('上海局', 'https://www.sse.com.cn/'),
    ]
    result['regulator_searches'] = []
    for name, base_url in reg_urls:
        try:
            search_url = base_url.format('')
            resp2 = safe_get(search_url, headers=_get_tianyancha_headers(), timeout=8)
            if resp2 and resp2.status_code == 200 and company_name[:4] in resp2.text:
                result['regulator_searches'].append(name)
        except Exception:
            pass

    # 方法3：烯牛数据IPO追踪
    try:
        xiniu_url = f'https://www.xiniudata.com/api/ipo/track?q={urllib.parse.quote(company_name)}'
        resp3 = safe_get(xiniu_url,
                         headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'},
                         timeout=10)
        if resp3 and resp3.status_code == 200:
            try:
                data = resp3.json()
                result['xiniu_ipo'] = data
            except Exception:
                pass
    except Exception as e:
        result['xiniu_error'] = str(e)

    result['coaching_records'] = coaching_records
    result['has_coaching'] = len(coaching_records) > 0
    return result


# ─────────────────────────────────────────────
# 维度7: ESOP/股权激励
# ─────────────────────────────────────────────

def fetch_esop_info(company_name, data_dir=None):
    """
    股权激励/员工持股计划信息
    数据源：天眼查 + 工商变更记录 + 新闻
    """
    result = {'source': 'tianyancha+news', 'company_name': company_name}
    esop_records = []

    # 方法1：天眼查股权变更（含员工持股平台）
    try:
        search_url = f'https://www.tianyancha.com/search/os/{urllib.parse.quote(company_name)}'
        resp = safe_get(search_url, headers=_get_tianyancha_headers(), timeout=10)
        if resp and resp.status_code == 200:
            text = resp.text
            # 提取股权变更记录
            change_records = re.findall(
                r'"changePercent":"([^"]+)".*?"changeAmount":"([^"]+)".*?"changeDate":(\d+)',
                text
            )
            for pct, amount, ts in change_records[:20]:
                date = datetime.fromtimestamp(int(ts) / 1000).strftime('%Y-%m-%d') if ts else ''
                esop_records.append({
                    'change_pct': pct,
                    'amount': amount,
                    'date': date,
                    'type': '股权变更',
                    'source': 'tianyancha',
                })

            # 提取员工持股平台（常见命名：员工持股/合伙企业）
            holding_platforms = re.findall(
                r'"name":"([^"]*(?:员工持股|合伙企业|投资中心)[^"]*)"',
                text
            )
            if holding_platforms:
                result['holding_platforms'] = list(set(holding_platforms))

    except Exception as e:
        result['error'] = str(e)

    # 方法2：新闻搜索股权激励
    try:
        import os as _os
        iwencai_key = _os.environ.get('IWENCAI_API_KEY', '')
        if iwencai_key:
            payload = {
                'question': f'{company_name} 股权激励 员工持股 股权激励计划',
                'appid': 'open_index_search',
                'client': 'pc',
                'version': '5.0'
            }
            resp2 = safe_post('https://openapi.iwencai.com/v1/query2data',
                             json=payload,
                             headers={'appid': 'open_index_search', 'version': '5.0'},
                             timeout=15)
            if resp2 and resp2.status_code == 200:
                data = resp2.json()
                result['iwencai_esop'] = data
    except Exception as e:
        result['iwencai_error'] = str(e)

    result['esop_records'] = esop_records
    result['count'] = len(esop_records)

    # 风险判断
    if result['count'] > 0:
        result['has_esop'] = True
    else:
        result['has_esop'] = False

    return result


# ─────────────────────────────────────────────
# 主入口：按维度获取数据
# ─────────────────────────────────────────────

def fetch_unlisted_company(company_name, dims=None, data_dir=None):
    """
    未上市公司分析主入口
    dims: list of dimensions to fetch
          basic | equity | financing | legal | news | ipo | esop
    """
    if dims is None:
        dims = ['basic', 'equity', 'financing', 'legal', 'news', 'ipo', 'esop']

    results = {}
    for dim in dims:
        key = f'unlisted_{dim}'
        if dim == 'basic':
            results[key] = fetch_basic_info(company_name, data_dir)
        elif dim == 'equity':
            results[key] = fetch_equity_structure(company_name, data_dir)
        elif dim == 'financing':
            results[key] = fetch_financing_history(company_name, data_dir)
        elif dim == 'legal':
            results[key] = fetch_legal_risks(company_name, data_dir)
        elif dim == 'news':
            results[key] = fetch_news_sentiment(company_name, data_dir)
        elif dim == 'ipo':
            results[key] = fetch_ipo_status(company_name, data_dir)
        elif dim == 'esop':
            results[key] = fetch_esop_info(company_name, data_dir)
        time.sleep(0.5)  # 避免请求过快

    return results


def format_unlisted_summary(results):
    """生成未上市公司的摘要文本"""
    parts = []

    basic = results.get('unlisted_basic', {})
    if basic.get('name'):
        parts.append(f"公司名: {basic['name']}")
    if basic.get('registered_capital'):
        parts.append(f"注册资本: {basic['registered_capital']}")
    if basic.get('legal_representative'):
        parts.append(f"法人: {basic['legal_representative']}")
    if basic.get('established'):
        parts.append(f"成立: {basic['established']}")
    if basic.get('status'):
        parts.append(f"状态: {basic['status']}")

    equity = results.get('unlisted_equity', {})
    if equity.get('count', 0) > 0:
        shs = equity['shareholders'][:3]
        sh_text = '; '.join([f"{s.get('name','?')}({s.get('share_pct','?')})" for s in shs])
        parts.append(f"主要股东: {sh_text}")

    financing = results.get('unlisted_financing', {})
    if financing.get('count', 0) > 0:
        parts.append(f"融资历史: {financing['count']}轮")

    legal = results.get('unlisted_legal', {})
    if legal.get('execution_count', 0) > 0:
        parts.append(f"⚠️ 被执行人: {legal['execution_count']}条")
    if legal.get('judgment_count', 0) > 0:
        parts.append(f"⚠️ 诉讼: {legal['judgment_count']}条")
    if legal.get('legal_risk_level'):
        parts.append(f"法律风险: {legal['legal_risk_level']}")

    ipo_data = results.get('unlisted_ipo', {})
    if ipo_data.get('has_coaching'):
        rec = ipo_data['coaching_records'][0]
        parts.append(f"📋 IPO辅导: {rec.get('coaching_institution','?')} | {rec.get('status','?')} | {rec.get('regulator','?')}局")
        if rec.get('report_count'):
            parts.append(f"  辅导报告: {rec['report_count']}期")

    news_sentiment = results.get('unlisted_news', {}).get('sentiment', '')
    if news_sentiment:
        parts.append(f"舆情: {news_sentiment}")

    return ' | '.join(parts) if parts else '数据获取中...'
