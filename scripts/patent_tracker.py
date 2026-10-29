# -*- coding: utf-8 -*-
"""
通用国际专利情报追踪模块
支持任意公司（A股/港股/美股/未上市）

数据源：
1. 中国专利局 (CNIPA) - 中国专利检索
2. Google Patents - 全球专利检索
3. 巨潮/东方财富公告 - 专利诉讼/纠纷
4. 网络搜索 - 专利诉讼新闻

用法:
    python patent_tracker.py --company "小米集团"
    python patent_tracker.py --stock 01810.HK
    python patent_tracker.py --company "Apple" --market us
"""
import sys, os, json, re, requests, argparse, time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

# 复用skill内的工具
try:
    from scripts.safe_request import safe_get, safe_extract
except ImportError:
    # 独立运行时
    def safe_get(url, params=None, headers=None, timeout=15, retries=2, backoff=1):
        for attempt in range(retries + 1):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=timeout)
                if r.status_code == 200:
                    try:
                        return r.json()
                    except:
                        return r.text
            except:
                if attempt < retries:
                    time.sleep(backoff * (attempt + 1))
        return None

    def safe_extract(data, keys, default=None):
        curr = data
        for k in keys:
            if isinstance(curr, dict):
                curr = curr.get(k)
            else:
                return default
        return curr if curr is not None else default


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# ========== 数据源可访问性说明（2026-04-29 测试）==========
# ✅ CNIPA主站:         www.cnipa.gov.cn          - 可访问
# ✅ CNIPA公共服务平台:  ggfw.cnipa.gov.cn         - 可访问（专利公布公告等）
# ❌ CNIPA检索系统(旧): pss-system.cnipa.gov.cn    - DNS无法解析，完全不可访问
# ⚠️ CNIPA检索系统(新): cpquery.cponline.cnipa.gov.cn - DNS可解析，但页面JS渲染需登录
# ✅ SooPAT:            www.soopat.com            - 可访问（第三方专利搜索）
# ❌ Google Patents:    patents.google.com        - DNS可解析，但连接超时（网络屏蔽）
# ✅ DRAMeXchange:      www.dramexchange.com       - 可访问（DRAM/存储芯片价格）
# ✅ LME:               www.lme.com               - 可访问，但实时价格需登录
# ✅ SHFE:              www.shfe.com.cn           - 可访问，但被WAF拦截
# ============================================================================

CNIPA_OPEN_API = "https://ggfw.cnipa.gov.cn/patentOpen/selectNotice"
CNIPA_HOME = "https://ggfw.cnipa.gov.cn/home"
SOOPAT_SEARCH = "https://www.soopat.com/"
EASTMONEY_NEWS_URL = "https://np-listapi.eastmoney.com/eastmoney.portal.infolist.getlist"


def normalize_company_name(company_name):
    """标准化公司名称，用于搜索"""
    # 去除常见后缀
    suffixes = ['有限公司', '股份有限公司', '集团', '科技', '技术', '股份',
                'Co., Ltd.', 'Inc.', 'Corp.', 'Corporation', 'Group', 'Technology']
    normalized = company_name
    for suffix in suffixes:
        normalized = re.sub(rf'{re.escape(suffix)}$', '', normalized, flags=re.IGNORECASE).strip()
    return normalized


def search_cnipa_patents(company_name, max_results=50):
    """
    查询中国专利局专利
    数据源：
    - CNIPA公共服务平台 (ggfw.cnipa.gov.cn) - 专利公布公告、专利审查信息
    - SooPAT (www.soopat.com) - 第三方专利搜索引擎，可通过浏览器访问
    - CNIPA旧检索系统 (pss-system.cnipa.gov.cn) - 已DNS屏蔽，无法访问
    """
    print(f"  → 查询中国专利: {company_name}")
    results = []

    # 方案1：通过CNIPA公共服务平台获取专利公布公告
    # 适合查询已公开专利的公告信息（不需要登录）
    try:
        # CNIPA专利公布公告是公开接口，但需要正确的请求格式
        # 由于ggfw.cnipa.gov.cn需要JS渲染，这里返回可访问的入口
        results.append({
            'source': 'CNIPA公共服务平台',
            'status': '可访问（需浏览器自动化获取完整数据）',
            'platform_url': CNIPA_HOME,
            'patent_search_url': f'{CNIPA_HOME}#/search?keyword={company_name}',
            'instructions': [
                '1. 打开 https://ggfw.cnipa.gov.cn/home',
                '2. 点击"信息服务" → "专利公布公告" 或 "专利检索及分析系统"',
                f'3. 输入"{company_name}"进行搜索',
                '注：完整检索需注册登录，但基本公告查询无需登录'
            ],
            'note': '2026-04-29实测：ggfw.cnipa.gov.cn 可正常访问，专利检索系统需JS渲染，建议用xbrowser自动化'
        })
    except Exception as e:
        results.append({'source': 'CNIPA公共服务平台', 'error': str(e)[:100]})

    # 方案2：SooPAT第三方专利搜索（可访问）
    try:
        encoded = requests.utils.quote(company_name)
        # SooPAT搜索URL格式（直接打开可触发搜索）
        soopat_url = f'https://www.soopat.com/Patent/Result?PatentVO=%7B%22SearchWord%22%3A%22{encoded}%22%2C%22SearchType%22%3A2%7D'
        results.append({
            'source': 'SooPAT专利搜索',
            'status': '可访问（推荐通过xbrowser自动化）',
            'direct_url': soopat_url,
            'manual_url': f'https://www.soopat.com/Home/Patent/Search?searchWord={encoded}&searchType=2',
            'instructions': [
                '1. 打开 https://www.soopat.com',
                f'2. 输入"{company_name}"，选择搜索类型（申请人/发明人/专利名称）',
                '3. 点击搜索查看专利列表',
                '4. 支持按申请日、公开日、专利类型筛选'
            ],
            'note': '2026-04-29实测：soopat.com 可正常访问，但需要浏览器JS渲染搜索结果'
        })
    except Exception as e:
        results.append({'source': 'SooPAT', 'error': str(e)[:100]})

    # 方案3：通过东方财富公告查专利相关公司公告
    # （已在search_patent_litigation中实现，这里补充说明）
    results.append({
        'source': '东方财富公告（A股）',
        'status': '可用（API直连）',
        'note': f'在{company_name}近12个月公告中搜索含"专利/侵权/知识产权"关键词的公告',
        'implemented_in': 'search_patent_litigation()函数'
    })

    return results


def search_google_patents(company_name, max_results=20):
    """
    查询 Google Patents
    ⚠️ 注意（2026-04-29实测）：patents.google.com DNS可解析(142.251.46.78)，
    但 xbrowser 访问时报 ERR_CONNECTION_TIMED_OUT（网络层面被屏蔽）。
    建议：通过xbrowser连接真实本地浏览器后访问，或使用VPN。
    """
    print(f"  → 查询 Google Patents: {company_name}")
    results = []

    encoded = requests.utils.quote(f'assignee:"{company_name}"')
    results.append({
        'source': 'Google Patents',
        'status': '⚠️ 网络层面屏蔽（ERR_CONNECTION_TIMED_OUT）',
        'note': f'patents.google.com 在当前网络环境无法直接访问',
        'query_url': f'https://patents.google.com/?q=assignee%3A%22{requests.utils.quote(company_name)}%22&sort=new',
        'workaround': [
            '方案1（推荐）：使用xbrowser连接本地浏览器访问',
            '方案2：通过VPN访问Google Patents',
            '方案3：使用Patentics (www.patentics.com) 作为替代（DNS实测可解析）',
            f'方案4：通过SooPAT (www.soopat.com) 搜索全球专利（含中国）'
        ],
        'patentics_url': f'https://www.patentics.com/patentics-search/?q={requests.utils.quote(company_name)}&db=world',
    })

    # 尝试通过搜索引擎间接获取（百度/必应）
    try:
        baidu_url = "https://www.baidu.com/s"
        baidu_params = {
            'wd': f'{company_name} site:patents.google.com',
            'rn': min(max_results, 10),
        }
        r = requests.get(baidu_url, params=baidu_params, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            # 提取专利链接
            patent_links = re.findall(r'patents\.google\.com/patent/([A-Z0-9]+)', r.text)
            if patent_links:
                results.append({
                    'source': 'Google Patents (via Baidu)',
                    'status': '通过百度搜索间接获取',
                    'patent_ids': list(set(patent_links))[:10],
                    'query_url': f'https://www.baidu.com/s?wd={requests.utils.quote(company_name)}+site%3Apatents.google.com',
                })
            else:
                results.append({
                    'source': 'Google Patents (via Baidu)',
                    'status': '未找到专利结果',
                })
    except Exception as e:
        results.append({'source': 'Google Patents (via Baidu)', 'error': str(e)[:100]})

    return results


def search_patent_litigation(company_name, stock_code=None, market='a'):
    """
    查询专利诉讼/纠纷
    来源：公告、新闻、司法公开网
    """
    print(f"  → 查询专利诉讼: {company_name}")
    results = {
        'litigations': [],
        'announcements': [],
        'news': [],
    }

    # 1. 从公告中找专利诉讼
    if market == 'a' and stock_code:
        try:
            url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
            params = {
                'cb': '', 'sr': '-1', 'ann_type': 'A',
                'client_source': 'web', 'f_node': '0', 's_node': '0',
                'stock_list': stock_code,
                'page_size': 100, 'page_index': 1,
            }
            data = safe_get(url, params=params, headers=HEADERS, timeout=20)
            items = safe_extract(data, ['data', 'list'], [])

            litigation_keywords = ['专利', '侵权', '知识产权', '诉讼', '起诉', '被诉', '纠纷']
            for item in items:
                title = item.get('title', '') or item.get('title_ch', '')
                if any(kw in title for kw in litigation_keywords):
                    results['announcements'].append({
                        'date': item.get('notice_date', '')[:10],
                        'title': title,
                        'art_code': item.get('art_code', ''),
                        'source': '东方财富公告',
                    })
        except Exception as e:
            print(f"    公告查询失败: {e}")

    elif market == 'hk' and stock_code:
        try:
            url = "https://www.cninfo.com.cn/new/fulltextSearch/full"
            params = {
                'searchkey': f'{company_name} 专利',
                'sdate': '', 'edate': '', 'isfulltext': 'false',
                'sortName': 'pubdate', 'sortType': 'desc',
                'pageNum': 1, 'pageSize': 20,
            }
            data = safe_get(url, params=params, headers=HEADERS, timeout=20)
            items = safe_extract(data, ['announcements'], [])

            for item in items:
                title_raw = item.get('announcementTitle', '')
                title = re.sub(r'<[^>]+>', '', title_raw)
                pub_ts = item.get('announcementTime', 0)
                pub_date = datetime.fromtimestamp(pub_ts / 1000).strftime('%Y-%m-%d') if pub_ts else ''
                results['announcements'].append({
                    'date': pub_date,
                    'title': title,
                    'announcement_id': item.get('announcementId', ''),
                    'source': '巨潮资讯',
                })
        except Exception as e:
            print(f"    港股公告查询失败: {e}")

    # 2. 搜索专利诉讼新闻
    try:
        # 使用东方财富新闻接口
        news_url = EASTMONEY_NEWS_URL
        news_params = {
            'cb': '', 'industryCode': '*', 'pageSize': 30, 'industry': '*',
            'rating': '*', 'ratingChange': '*', 'beginTime': (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'),
            'endTime': datetime.now().strftime('%Y-%m-%d'),
            'keywords': f'{company_name} 专利 诉讼',
        }
        news_data = safe_get(news_url, params=news_params, headers=HEADERS, timeout=15)
        news_items = safe_extract(news_data, ['data', 'list'], [])

        for item in news_items:
            results['news'].append({
                'date': item.get('publishTime', '')[:10],
                'title': item.get('title', ''),
                'summary': item.get('summary', '')[:200],
                'source': '东方财富新闻',
            })
    except Exception as e:
        print(f"    新闻查询失败: {e}")

    return results


def analyze_patent_portfolio(company_name, patent_results):
    """
    分析专利组合
    提取关键指标：专利数量、技术领域、诉讼风险
    """
    analysis = {
        'company': company_name,
        'total_patents_cn': 0,
        'total_patents_global': 0,
        'litigation_count': 0,
        'litigation_active': 0,
        'risk_level': '低',
        'key_areas': [],
        'recent_cases': [],
    }

    # 统计诉讼
    for source_result in patent_results:
        if isinstance(source_result, dict):
            litigations = source_result.get('litigations', [])
            announcements = source_result.get('announcements', [])
            analysis['litigation_count'] += len(litigations) + len(announcements)

            # 最近案件
            for ann in announcements[:5]:
                analysis['recent_cases'].append({
                    'date': ann.get('date', ''),
                    'title': ann.get('title', '')[:100],
                    'type': '公告',
                })

    # 风险评级
    if analysis['litigation_count'] >= 5:
        analysis['risk_level'] = '高'
    elif analysis['litigation_count'] >= 2:
        analysis['risk_level'] = '中'

    return analysis


def generate_patent_report(company_name, stock_code=None, market='a'):
    """
    生成专利情报报告
    """
    print(f"\n{'='*60}")
    print(f"📋 国际专利情报报告 — {company_name}")
    print(f"{'='*60}\n")

    report = {
        'company': company_name,
        'stock_code': stock_code,
        'market': market,
        'generated_at': datetime.now().isoformat(),
        'cnipa_results': [],
        'google_patents_results': [],
        'litigation_results': {},
        'analysis': {},
    }

    # 1. 查询中国专利局
    report['cnipa_results'] = search_cnipa_patents(company_name)

    # 2. 查询 Google Patents
    report['google_patents_results'] = search_google_patents(company_name)

    # 3. 查询专利诉讼
    report['litigation_results'] = search_patent_litigation(company_name, stock_code, market)

    # 4. 分析
    all_results = report['cnipa_results'] + report['google_patents_results'] + [report['litigation_results']]
    report['analysis'] = analyze_patent_portfolio(company_name, all_results)

    return report


def format_markdown_report(report):
    """格式化专利情报报告为Markdown"""
    lines = []
    lines.append(f"# 📋 国际专利情报报告 — {report['company']}\n")
    lines.append(f"**生成时间**: {report['generated_at'][:19]}")
    lines.append(f"**股票代码**: {report.get('stock_code', 'N/A')}")
    lines.append(f"**市场**: {report.get('market', 'N/A').upper()}")
    lines.append("\n---\n")

    # 中国专利局
    lines.append("## 一、中国专利局 (CNIPA)\n")
    for r in report.get('cnipa_results', []):
        if 'error' in r:
            lines.append(f"- ❌ 查询失败: {r['error']}")
        elif 'note' in r:
            lines.append(f"- ℹ️ {r['note']}")
            if 'query_url' in r:
                lines.append(f"  - 查询地址: <{r['query_url']}>")
    lines.append("")

    # Google Patents
    lines.append("## 二、Google Patents (全球)\n")
    for r in report.get('google_patents_results', []):
        if 'error' in r:
            lines.append(f"- ❌ 查询失败: {r['error']}")
        elif 'note' in r:
            lines.append(f"- ℹ️ {r['note']}")
            if 'query_url' in r:
                lines.append(f"  - 查询地址: <{r['query_url']}>")
        if 'patent_ids' in r:
            lines.append(f"- 找到专利: {', '.join(r['patent_ids'])}")
    lines.append("")

    # 专利诉讼
    lit = report.get('litigation_results', {})
    lines.append("## 三、专利诉讼/纠纷\n")
    lines.append(f"### 公告中的专利诉讼 ({len(lit.get('announcements', []))}条)\n")
    if lit.get('announcements'):
        lines.append("| 日期 | 标题 | 来源 |")
        lines.append("|------|------|------|")
        for ann in lit['announcements'][:10]:
            lines.append(f"| {ann.get('date', '?')} | {ann.get('title', '')[:60]} | {ann.get('source', '')} |")
    else:
        lines.append("_近12个月公告中未发现专利诉讼_")
    lines.append("")

    lines.append(f"### 新闻中的专利诉讼 ({len(lit.get('news', []))}条)\n")
    if lit.get('news'):
        for news in lit['news'][:5]:
            lines.append(f"- **{news.get('date', '')}** {news.get('title', '')}")
            if news.get('summary'):
                lines.append(f"  > {news['summary'][:100]}...")
    else:
        lines.append("_近12个月新闻中未发现专利诉讼_")
    lines.append("")

    # 分析
    analysis = report.get('analysis', {})
    lines.append("## 四、专利风险分析\n")
    risk_icon = {'高': '🔴', '中': '🟡', '低': '✅'}.get(analysis.get('risk_level', '低'), '❓')
    lines.append(f"**风险等级**: {risk_icon} {analysis.get('risk_level', '未知')}")
    lines.append(f"**诉讼总数**: {analysis.get('litigation_count', 0)}")
    lines.append("")

    if analysis.get('recent_cases'):
        lines.append("### 近期案件\n")
        for case in analysis['recent_cases']:
            lines.append(f"- **{case.get('date', '')}** [{case.get('type', '')}] {case.get('title', '')}")

    lines.append("\n---\n")
    lines.append("> ⚠️ **数据说明**: 专利数据来自公开渠道，部分数据源（CNIPA、Google Patents）")
    lines.append("> 需要官方API或浏览器自动化才能获取完整数据。本模块提供查询入口和诉讼公告分析。")

    return "\n".join(lines)


def save_report(report, output_dir, company_name):
    """保存报告"""
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    json_path = os.path.join(output_dir, f"patent_tracker_{company_name}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Markdown
    md = format_markdown_report(report)
    md_path = os.path.join(output_dir, f"patent_tracker_{company_name}.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)

    print(f"\n✅ 报告已保存:")
    print(f"   JSON: {json_path}")
    print(f"   Markdown: {md_path}")

    return md_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='国际专利情报追踪（通用模块）')
    parser.add_argument('--company', required=True, help='公司名称（中文/英文均可）')
    parser.add_argument('--stock', help='股票代码（可选，用于查公告）')
    parser.add_argument('--market', choices=['a', 'hk', 'us'], default='a', help='市场')
    parser.add_argument('--output', help='输出目录（默认: output/patent_tracker/）')

    args = parser.parse_args()

    output_dir = args.output or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..', 'output', 'patent_tracker'
    )

    report = generate_patent_report(
        company_name=args.company,
        stock_code=args.stock,
        market=args.market,
    )

    save_report(report, output_dir, args.company)

    # 打印报告
    print("\n" + format_markdown_report(report))
