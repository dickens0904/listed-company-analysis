# -*- coding: utf-8 -*-
"""
模块5：子公司分拆/IPO辅导追踪
数据源：
  1. 东方财富公告搜索（"分拆"/"辅导"关键词）
  2. 年报PDF"主要控股参股公司"章节（自动提取子公司名）
  3. AKShare stock_ipo_tutor_em（CSRC辅导数据，按子公司名搜索）
"""
import sys, json, requests, re, time, os
from datetime import datetime
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result
sys.stdout.reconfigure(encoding='utf-8')


def fetch_subsidiary_ipo(stock_code, market='a', data_dir=None):
    """
    追踪拟分拆/IPO的子公司辅导进度
    
    流程：
    1. 东方财富公告搜索分拆/辅导相关公告 → 提取子公司名
    2. 年报PDF提取主要控股参股公司（如有）→ 补充子公司名
    3. 用子公司名搜AKShare CSRC辅导数据 → 获取辅导期数/状态
    """
    result = {
        'stock_code': stock_code,
        'subsidiaries': [],
        'csrc_tutoring': [],
        'findings': [],
        'report_count': '未知',
        'warnings': [],
        '_meta': {
            'source': 'unknown',
            'steps': [],
            'fetched_at': datetime.now().isoformat(),
        },
    }

    if market != 'a':
        result['warnings'].append('子公司IPO追踪仅支持A股上市公司')
        return result

    # ====== Step 1: 东方财富公告搜索 ======
    subs = _find_listing_plans_via_em(stock_code)
    result['subsidiaries'] = subs
    result['_meta']['steps'].append({
        'step': 'em_announce_search',
        'label': '东方财富公告搜索',
        'source': 'em_announce',
        'count': len(subs),
        'status': 'OK' if subs else 'EMPTY',
    })

    # ====== Step 2: 收集子公司名关键词 ======
    sub_names = set()
    for s in subs:
        name = s.get('sub_company', '')
        if name and name != '未知':
            # 提取核心名（去掉"有限公司"等后缀）
            core_name = re.sub(r'(股份有限公司|有限责任公司|有限公司|公司)$', '', name)
            if len(core_name) >= 2:
                sub_names.add(core_name)
            # 也保留原名
            if len(name) >= 2:
                sub_names.add(name)

    # 从年报PDF补充子公司名（如果有已下载的年报）
    annual_subs = _extract_subsidiaries_from_annual_pdf(stock_code, data_dir)
    result['_meta']['steps'].append({
        'step': 'annual_pdf_extract',
        'label': '年报PDF子公司提取',
        'source': 'annual_pdf_text',
        'count': len(annual_subs),
        'status': 'OK' if annual_subs else 'SKIP',
        'pdf_source': 'local_pdf' if annual_subs else None,
    })
    for name in annual_subs:
        core = re.sub(r'(股份有限公司|有限责任公司|有限公司|公司)$', '', name)
        if len(core) >= 2:
            sub_names.add(core)
        if len(name) >= 2:
            sub_names.add(name)

    # ====== Step 3: AKShare CSRC辅导数据搜索 ======
    csrc = []
    csrc_status = 'SKIP'
    if sub_names:
        for kw in sorted(sub_names):  # 排序确保稳定性
            try:
                matches = _search_csrc_tutoring_ak(sub_company_name=kw)
                csrc.extend(matches)
            except Exception as e:
                result['warnings'].append(f'AKShare辅导搜索({kw})失败: {e}')
        csrc_status = 'OK' if csrc else 'EMPTY'
    result['_meta']['steps'].append({
        'step': 'csrc_tutoring_search',
        'label': f'CSRC辅导数据搜索({len(sub_names)}个关键词)',
        'source': 'csrc_ak',
        'count': len(csrc),
        'status': csrc_status,
    })

    # 去重（同一公司可能出现多次）
    seen_titles = set()
    unique_csrc = []
    for item in csrc:
        title_key = (item.get('company_name', ''), item.get('report_title', ''))
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_csrc.append(item)
    csrc = unique_csrc

    if csrc:
        result['csrc_tutoring'] = csrc
        # 统计辅导期数
        max_period = _extract_max_period(csrc)
        if max_period > 0:
            result['report_count'] = f'第{max_period}期'
        result['tutoring_total'] = len(csrc)
        result['tutoring_companies'] = list(set(c.get('company_name', '') for c in csrc))

    # ====== Step 4: 分析进度 ======
    result['findings'] = _analyze_ipo_progress(subs, csrc)

    if not subs and not csrc:
        result['findings'].append({
            'level': 'info',
            'text': '近12个月公告中未找到分拆上市相关公告，辅导数据中也未找到相关记录'
        })

    # 合并溯源：best = 有数据的最高优先级步骤
    _merge_subsidiary_source(result)

    return result


def _merge_subsidiary_source(result):
    """根据步骤结果合并顶层source"""
    steps = result.get('_meta', {}).get('steps', [])
    ok_steps = [s for s in steps if s['status'] == 'OK']
    if ok_steps:
        # 取第一个有数据的步骤作为主来源
        result['_meta']['source'] = ok_steps[0].get('source', 'unknown')
    elif any(s['status'] == 'EMPTY' for s in steps):
        result['_meta']['source'] = 'em_announce'  # 虽然为空，但API通了
    else:
        result['_meta']['source'] = 'all_failed'


def _extract_subsidiaries_from_annual_pdf(stock_code, data_dir):
    """从已下载的年报PDF提取主要控股参股公司名称"""
    names = []
    if not data_dir:
        return names
    
    # 尝试读取年报提取结果
    sections_path = os.path.join(data_dir, 'annual_report_sections.json')
    if not os.path.exists(sections_path):
        # 也尝试文本文件
        text_path = os.path.join(data_dir, 'annual_report_text.txt')
        if os.path.exists(text_path):
            try:
                with open(text_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                # 从全文搜索子公司名
                names = _parse_subsidiary_names(text)
            except Exception as _sexc:
                record(__name__, '_extract_subsidiaries_from_annual_pdf', _sexc, note='静默降级')
                pass
        return names
    
    try:
        with open(sections_path, 'r', encoding='utf-8') as f:
            sections = json.load(f)
        
        sub_section = sections.get('subsidiaries', {})
        content = sub_section.get('content', '') if isinstance(sub_section, dict) else str(sub_section)
        
        if content and not content.startswith('[未找到'):
            names = _parse_subsidiary_names(content)
    except Exception as _sexc:
        record(__name__, '_extract_subsidiaries_from_annual_pdf', _sexc, note='静默降级')
        pass
    
    return names


def _parse_subsidiary_names(text):
    """从文本中解析子公司名称"""
    names = []
    # 模式1：公司名+持股比例（如"珠海极海微电子股份有限公司 81.2%"）
    matches = re.findall(r'([\u4e00-\u9fa5]+(?:股份|有限责任|有限)?公司)\s*[\d.]+%?', text)
    for m in matches:
        if len(m) >= 4 and m not in names:
            names.append(m)
    
    # 模式2：表格行中的公司名（中文+有限公司）
    if not names:
        matches2 = re.findall(r'([\u4e00-\u9fa5]{2,}(?:股份有限公司|有限责任公司|有限公司))', text)
        for m in matches2:
            if m not in names:
                names.append(m)
    
    return names[:20]  # 最多20个，避免过多搜索


def _extract_max_period(csrc_data):
    """从CSRC辅导数据提取最大辅导期数"""
    max_period = 0
    cn_map = {
        '一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,
        '十':10,'十一':11,'十二':12,'十三':13,'十四':14,'十五':15,
        '十六':16,'十七':17,'十八':18,'十九':19,'二十':20,
        '二十一':21,'二十二':22,'二十三':23,'二十四':24,'二十五':25,
    }
    for item in csrc_data:
        title = item.get('report_title', '')
        m = re.search(r'第([一二三四五六七八九十\d]+)期', title)
        if m:
            period_str = m.group(1)
            period = cn_map.get(period_str, int(period_str) if period_str.isdigit() else 0)
            max_period = max(max_period, period)
    return max_period


def _find_listing_plans_via_em(stock_code):
    """通过东方财富找到分拆/辅导/IPO相关公告"""
    url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?cb=&sr=-1&page_size=200&page_index=1&ann_type=A"
           f"&client_source=web&f_node=0&s_node=0&stock_list={stock_code}")
    subs = []
    try:
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://data.eastmoney.com/'
        }, timeout=20)
        r.encoding = 'utf-8'
        data = r.json()
        items = data.get('data', {}).get('list', [])
    except Exception as e:
        return subs

    for item in items:
        title = item.get('title', '') or item.get('title_ch', '')
        # 扩展关键词：分拆、辅导、首次公开发行
        if any(kw in title for kw in ['分拆', '辅导', '首次公开发行']) and '上市' in title:
            notice_date = item.get('notice_date', '')[:10]
            subs.append({
                'date': notice_date,
                'title': title,
                'art_code': item.get('art_code', ''),
                'sub_company': _extract_sub_name(title),
                'target_board': _extract_target_board(title),
            })
    return subs


def _extract_sub_name(title):
    """从公告标题提取子公司名称"""
    # 常见模式：
    # "关于筹划XXX分拆上市的提示性公告"
    # "关于子公司XXX首次公开发行股票并在创业板上市的辅导备案公告"
    patterns = [
        r'子公司?([^\s]{2,20}?)(?:分拆|首次公开发行)',
        r'筹划?([^\s]{2,20}?)(?:分拆|首次公开发行)',
        r'关于([^\s]{2,20}?)(?:分拆|首次公开发行)',
    ]
    for pat in patterns:
        m = re.search(pat, title)
        if m:
            name = m.group(1).strip()
            # 清理前缀
            name = re.sub(r'^(关于|拟|拟将|下属|控股)', '', name)
            if name and len(name) >= 2:
                return name
    return '未知'


def _extract_target_board(title):
    """从标题推断拟上市板块"""
    if '科创板' in title:
        return '科创板'
    elif '创业板' in title:
        return '创业板'
    elif '北交所' in title or '新三板' in title:
        return '北交所'
    elif '主板' in title:
        return '主板'
    else:
        return '未知（需查原始公告）'


def _search_csrc_tutoring_ak(sub_company_name=None):
    """通过AKShare获取CSRC辅导数据
    
    Args:
        sub_company_name: 子公司名称关键词（如'极海微'），精确搜索
    """
    if not sub_company_name:
        return []
    results = []
    try:
        import akshare as ak
        df = ak.stock_ipo_tutor_em()
        # 按子公司名关键词筛选
        mask = df['企业名称'].str.contains(sub_company_name, na=False)
        matched = df[mask]
        for _, row in matched.iterrows():
            row_dict = {
                'company_name': row.get('企业名称', ''),
                'tutor_org': row.get('辅导机构', ''),
                'status': row.get('辅导状态', ''),
                'report_type': row.get('报告类型', ''),
                'supervisor': row.get('派出机构', ''),
                'report_title': row.get('报告标题', ''),
                'filing_date': str(row.get('备案日期', '')),
            }
            results.append(row_dict)
    except Exception as e:
        record_result(__name__, '_search_csrc_tutoring_ak', e, note='静默降级')
        pass  # 降级：AKShare不可用时静默返回空
    return results


def _analyze_ipo_progress(subs, csrc_data):
    """分析IPO进度"""
    findings = []

    for sub in subs:
        title = sub.get('title', '')
        date = sub.get('date', '')
        board = sub.get('target_board', '未知')

        if '提示性公告' in title:
            findings.append({
                'level': 'info',
                'text': f"{date} 公告筹划{board}分拆上市（初期阶段）",
                'sub': sub.get('sub_company', '子公司')
            })
        elif '辅导' in title:
            findings.append({
                'level': 'info',
                'text': f"{date} 进入{board}辅导期",
                'sub': sub.get('sub_company', '子公司')
            })
        elif '申报' in title or '受理' in title:
            findings.append({
                'level': 'positive',
                'text': f"{date} 已向{board}提交申报",
                'sub': sub.get('sub_company', '子公司')
            })
        elif '首次公开发行' in title:
            findings.append({
                'level': 'info',
                'text': f"{date} {title[:50]}",
                'sub': sub.get('sub_company', '子公司')
            })

    # 从AKShare辅导数据分析
    if csrc_data and isinstance(csrc_data, list):
        for item in csrc_data[:5]:
            name = item.get('company_name', '')
            status = item.get('status', '')
            rtype = item.get('report_type', '')
            org = item.get('tutor_org', '')
            date = item.get('filing_date', '')[:10]
            if name:
                findings.append({
                    'level': 'info',
                    'text': f"{date} {name} | {status} | {rtype} | 辅导机构:{org}",
                    'sub': name
                })

    return findings


if __name__ == '__main__':
    result = fetch_subsidiary_ipo('002180')
    print(f"找到分拆计划: {len(result['subsidiaries'])}条")
    print(f"辅导期数: {result['report_count']}")
    for s in result['subsidiaries']:
        print(f"  {s['date']} | {s['sub_company']} | 目标:{s['target_board']}")


def generate_report_section(data: dict) -> list:
    lines = []
    lines.append("## 子公司分拆/IPO追踪")
    lines.append("")

    subs = data.get('subsidiaries', [])
    csrc = data.get('csrc_tutoring', [])
    report_count = data.get('report_count', '未知')
    tutoring_total = data.get('tutoring_total', 0)

    if subs:
        lines.append("**分拆上市公告**:")
        for s in subs:
            lines.append(f"- **{s.get('date','')}** {s.get('title','')[:90]}")
            lines.append(f"  - 子公司: {s.get('sub_company','未知')} | 目标板块: {s.get('target_board','未知')}")
        lines.append("")

    if csrc and len(csrc) > 0:
        lines.append(f"**证监会辅导备案**（共{tutoring_total}条，当前{report_count}）:")
        for item in csrc[:5]:
            name = item.get('company_name', '')
            status = item.get('status', '')
            rtype = item.get('report_type', '')
            org = item.get('tutor_org', '')
            date = item.get('filing_date', '')[:10]
            lines.append(f"- {date} | {name} | {status} | {rtype} | 辅导机构:{org}")
        if len(csrc) > 5:
            lines.append(f"  - ...还有{len(csrc)-5}条")
        lines.append("")

    findings = data.get('findings', [])
    if findings:
        lines.append("**IPO进度评估**:")
        for f in findings:
            level_icon = {'high': '🔴', 'medium': '🟡', 'info': '🟢'}.get(f.get('level',''), '⚪')
            lines.append(f"- {level_icon} {f.get('text','')}")
        lines.append("")

    if not subs and not csrc:
        lines.append("> 近12个月公告中未找到分拆上市相关公告，AKShare辅导数据中也未找到相关记录。")
        lines.append("")

    return lines
