# -*- coding: utf-8 -*-
"""
模块6：关联方资本运作
收购/出售/私有化/关联交易/资产置换
"""
import sys, json, requests, re, time, os
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result
sys.stdout.reconfigure(encoding='utf-8')

try:
    import pdfplumber
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'pdfplumber', '-q'])
    import pdfplumber


def fetch_related_deals(stock_code, market='a', data_dir=None):
    """识别关联方资本运作"""
    result = {'stock_code': stock_code, 'market': market, 'deals': [], 'count': 0, 'risks': []}

    if market == 'hk':
        result.update(_fetch_hk_related(stock_code, data_dir))
        return result

    url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?cb=&sr=-1&page_size=200&page_index=1&ann_type=A"
           f"&client_source=web&f_node=0&s_node=0&stock_list={stock_code}")
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

    deals = []
    keywords = [
        '收购', '出售', '转让', '置换', '增资', '减资',
        '参股', '合资', '合作', '设立',
        '私有化', '要约', '合并', '分立',
        '关联交易', '关联方', '担保',
        '股权激励', '员工持股',
    ]

    for item in items:
        title = item.get('title', '') or item.get('title_ch', '')
        notice_date = item.get('notice_date', '')[:10]
        art_code = item.get('art_code', '')
        matched = [k for k in keywords if k in title]
        if matched:
            deals.append({
                'date': notice_date,
                'title': title,
                'art_code': art_code,
                'keywords': matched,
                'type': _classify_deal(title),
                'risk': _assess_deal_risk(title, matched),
            })

    result['deals'] = deals
    result['count'] = len(deals)
    result['risks'] = [d for d in deals if d['risk']]
    result['summary'] = _summarize_deals(deals)

    # 特殊处理：港股私有化
    if market == 'hk':
        result.update(_check_hk_go_private(stock_code))

    return result


def _classify_deal(title):
    if '收购' in title and '要约' not in title:
        return '资产收购'
    elif '出售' in title or '转让' in title:
        return '资产出售'
    elif '私有化' in title or '要约' in title:
        return '要约收购/私有化'
    elif '增资' in title:
        return '增资扩股'
    elif '关联交易' in title:
        return '关联交易'
    elif '合资' in title or '合作' in title:
        return '战略合作/合资'
    elif '合并' in title or '吸收合并' in title:
        return '合并重组'
    else:
        return '其他资本运作'


def _assess_deal_risk(title, matched):
    if '关联交易' in matched:
        return "⚠️ 关联交易→需关注定价公允性及利益输送风险"
    if '要约' in matched or '私有化' in matched:
        return "⚠️ 私有化→需关注收购方背景及资金来源"
    if '担保' in matched:
        return "⚠️ 关联担保→需关注或有负债风险"
    return None


def _summarize_deals(deals):
    summary = {
        'total': len(deals),
        'by_type': {},
        'latest': deals[0] if deals else None,
    }
    for d in deals:
        t = d['type']
        summary['by_type'][t] = summary['by_type'].get(t, 0) + 1
    return summary


def _fetch_hk_related(stock_code, data_dir):
    """港股关联方资本运作"""
    import os as _os
    result = {'deals': [], 'count': 0}
    go_private = []
    try:
        url = ("https://www.cninfo.com.cn/new/fulltextSearch/full"
               f"?searchkey={stock_code}&sdate=&edate=&isfulltext=false"
               f"&sortName=pubdate&sortType=desc&plateCode=")
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Referer': 'https://www.cninfo.com.cn/'
        }, timeout=15)
        r.encoding = 'utf-8'
        data = r.json()
        items = data.get('announcements', [])
    except:
        return result

    for item in items:
        title_raw = item.get('announcementTitle', '')
        title = re.sub(r'<[^>]+>', '', title_raw)
        pub_ts = item.get('announcementTime', 0)
        pub_date = datetime.fromtimestamp(pub_ts / 1000).strftime('%Y-%m-%d') if pub_ts else ''
        aid = item.get('announcementId', '')

        if any(k in title for k in ['要约', '收购', '私有化', '強制', '強制性',
                                      '建議', '合併', '收購', '出售']):
            record = {
                'date': pub_date,
                'title': title,
                'announcement_id': aid,
                'type': '要约收购/私有化' if '要约' in title or '私有化' in title else '资本运作',
            }
            _download_go_private_pdf(item, record, data_dir)
            go_private.append(record)
            result['deals'].append(record)

    result['count'] = len(result['deals'])
    result['go_private'] = go_private
    return result
    """港股：检查是否有私有化公告"""
    result = {}
    try:
        url = ("https://www.cninfo.com.cn/new/fulltextSearch/full"
               f"?searchkey={stock_code}&sdate=&edate=&isfulltext=false"
               f"&sortName=pubdate&sortType=desc&plateCode=")
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Referer': 'https://www.cninfo.com.cn/'
        }, timeout=15)
        r.encoding = 'utf-8'
        data = r.json()
        items = data.get('announcements', [])
    except:
        return result

    go_private = []
    for item in items:
        title_raw = item.get('announcementTitle', '')
        title = re.sub(r'<[^>]+>', '', title_raw)
        if any(k in title for k in ['要约', '私有化', '收購', '收买', '强制']):
            pub_ts = item.get('announcementTime', 0)
            pub_date = datetime.fromtimestamp(pub_ts / 1000).strftime('%Y-%m-%d') if pub_ts else ''
            go_private.append({
                'date': pub_date,
                'title': title,
                'announcement_id': item.get('announcementId', ''),
            })
            # 下载PDF提取要约人信息
            _download_go_private_pdf(item, go_private[-1])

    if go_private:
        result['go_private'] = go_private

    return result


def _download_go_private_pdf(item, record, data_dir=None):
    """下载港股私有化公告PDF，提取要约人/收购方信息"""
    aid = item.get('announcementId', '')
    adjunct = item.get('adjunctUrl', '')
    if not adjunct:
        return

    # 构建PDF URL
    # adjunctUrl格式: finalpage/YYYY-MM-DD/announcementId.PDF
    pdf_url = f"https://static.cninfo.com.cn/{adjunct}"
    dest = os.path.join(os.getcwd(), f"{aid}_go_private.pdf")

    try:
        r = requests.get(pdf_url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.cninfo.com.cn/'
        }, timeout=30)
        if r.status_code != 200 or len(r.content) < 5000:
            return
        with open(dest, 'wb') as f:
            f.write(r.content)

        text = ""
        with pdfplumber.open(dest) as pdf:
            for page in pdf.pages:
                pt = page.extract_text()
                if pt:
                    text += pt + "\n"

        if text:
            record['pdf_text'] = text[:5000]
            # 提取关键信息
            record['offeror'] = _extract_offeror(text)
            record['target'] = '美佳音控股' if '美佳音' in text else '未知'
            record['advisor'] = _extract_advisor(text)
            record['deadline'] = _extract_deadline(text)

        _os.unlink(dest)  # 清理临时文件
    except Exception as _sexc:
        record(__name__, '_download_go_private_pdf', _sexc, note='静默降级')
        pass


def _extract_offeror(text):
    """从港股私有化PDF提取要约人/收购方"""
    # 常见模式：要約人 / OFFEROR / 要約人為 XXX
    patterns = [
        r'要約人[是为：:\s]+([^\n。]{2,30})',
        r'OFFEROR[是为：:\s]+([A-Za-z\s]{2,50})',
        r'收购人[是为：:\s]+([^\n。]{2,30})',
        r'要約人及其一致行動人士[^\n]*?([^\n]{2,50})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip()
            # 清理HTML实体
            name = re.sub(r'<[^>]+>', '', name)
            return name
    return '未知（需手动查看PDF）'


def _extract_advisor(text):
    """提取财务顾问"""
    patterns = [
        r'财务顾问[是为：:\s]+([^\n。]{2,30})',
        r'獨立財務顧問[是为：:\s]+([^\n。]{2,30})',
        r'Financial Adviser[是为：:\s]+([A-Za-z\s]{2,30})',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return '未知'


def _extract_deadline(text):
    """提取要约截止日"""
    patterns = [
        r'最後截止日期[^\d]*?(\d{4}年\d{1,2}月\d{1,2}日)',
        r'截止日期[^\d]*?(\d{4}[-/]\d{2}[-/]\d{2})',
        r'截止日期[^\d]*?(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
        r'截止[^\d]*?(\d{4}年\d{1,2}月\d{1,2}日)',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return '未知'


if __name__ == '__main__':
    result = fetch_related_deals('002180')
    print(f"资本运作: {result['count']}项")
    for d in result['deals']:
        print(f"  {d['date']} [{d['type']}] {d['title'][:60]}")


def generate_report_section(data: dict) -> list:
    lines = []
    lines.append("## 关联方资本运作")
    lines.append("")
    lines.append(f"**资本运作总数**: {data.get('count', 0)}项")
    lines.append("")

    deals = data.get('deals', [])
    if deals:
        lines.append("**运作明细**:")
        for d in deals:
            risk = f" ⚠️ {d.get('risk','')}" if d.get('risk') else ''
            lines.append(f"- **{d.get('date','')}** [{d.get('type','')}] {d.get('title','')[:70]}{risk}")
        lines.append("")

    go_private = data.get('go_private', [])
    if go_private:
        lines.append("**⚠️ 港股私有化**:")
        for gp in go_private:
            lines.append(f"- **{gp.get('date','')}** {gp.get('title','')[:80]}")
            if gp.get('offeror'):
                lines.append(f"  - 要约人/收购方: {gp['offeror']}")
            if gp.get('advisor'):
                lines.append(f"  - 财务顾问: {gp['advisor']}")
            if gp.get('deadline'):
                lines.append(f"  - 截止日期: {gp['deadline']}")
        lines.append("")

    summary = data.get('summary', {})
    if summary.get('by_type'):
        lines.append("**类型统计**:")
        for t, cnt in summary['by_type'].items():
            lines.append(f"- {t}: {cnt}项")
        lines.append("")

    return lines
