# -*- coding: utf-8 -*-
"""
上市公司全景分析主脚本
用法: python analyze.py --stock 002180 [--dims all|announcements|financial|...]
"""
import sys, os, argparse, json, re
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

from scripts.announcements import fetch_announcements
from scripts.financials import fetch_financials
from scripts.executives import fetch_executives
from scripts.capital import fetch_capital_actions
from scripts.subsidiary import fetch_subsidiary_ipo
from scripts.related_deals import fetch_related_deals
from scripts.regulatory import fetch_regulatory_history
from scripts.structure import build_structure
from scripts.industry import fetch_industry
from scripts.risk import assess_risk
from scripts.report import generate_report
from scripts.source_tracker import SOURCE_LABELS
# 新增模块
from scripts.websearch import search_cninfo_annual, parse_cninfo_response
from scripts.pdf_download import download_and_extract, get_annual_report_list
from scripts.hk_financial import fetch_hk_financial
from scripts.us_financial import get_us_company_info
from scripts.sec_xbrl_api import fetch_us_financials
from scripts.peer_compare import PeerComparator
from scripts.rd_analysis import fetch_rd_analysis
from scripts.bse_price import fetch_price, format_price, infer_market
from scripts.unlisted_company import (
    fetch_unlisted_company, fetch_basic_info, fetch_equity_structure,
    fetch_financing_history, fetch_legal_risks, fetch_news_sentiment,
    fetch_ipo_status, fetch_esop_info, format_unlisted_summary
)
# 新增深度分析模块
from scripts.multi_year_trend import fetch_multi_year_trend
from scripts.valuation import fetch_valuation
from scripts.governance import fetch_governance
from scripts.share_history import fetch_share_history
from scripts.institutional import fetch_institutional
from scripts.earnings_forecast import fetch_earnings_forecast
from scripts.investor_qa import fetch_investor_qa
from scripts.company_resolver import resolve_company_name, format_resolver_summary
from scripts.hkex_announcements import search_hkex_announcements
from scripts.cross_validator import CrossValidator


def parse_args():
    parser = argparse.ArgumentParser(description='上市公司/未上市公司全景分析')
    parser.add_argument('--stock', help='股票代码（上市公司）')
    parser.add_argument('--name', help='中文公司名（自动跨市场识别A股/港股/美股）')
    parser.add_argument('--company', help='公司名称（未上市公司）')
    parser.add_argument('--market', default='auto',
                        choices=['auto', 'a', 'hk', 'us'],
                        help="市场: auto=自动识别(默认), a=A股, hk=港股, us=美股。"\
                              "提示: 纯字母代码(AAPL/MSFT)自动识别为美股，4-5位数字(00700)自动识别为港股，92xxx自动识别为北交所")
    parser.add_argument('--dims', default='all',
                        help='上市公司: announcements,financial,executives,capital,'
                             'subsidiary,related,regulatory,structure,industry,risk'
                             ' | 未上市公司: basic,equity,financing,legal,news,ipo,esop')
    parser.add_argument('--full', action='store_true', help='完整分析')
    parser.add_argument('--output', default=None, help='输出目录')
    parser.add_argument('--no-pdf', action='store_true', help='跳过PDF下载')
    parser.add_argument('--no-peer', action='store_true', help='跳过同业对比')
    parser.add_argument('--report-type', dest='report_type', default='all',
                        choices=['annual', 'semi_annual', 'quarterly', 'all'],
                        help='定期报告类型(all=年报+半年报+季报)')
    parser.add_argument('--report-years', dest='report_years', type=int, default=1,
                        help='定期报告回溯年数(默认1)')
    args = parser.parse_args()
    if not args.stock and not args.name and not args.company:
        parser.error('必须指定 --stock / --name 或 --company')
    if args.stock and args.name:
        parser.error('--stock 和 --name 不能同时使用')
    return args
    return args


def call_dim(dim, stock, market, data_dir, results, args):
    """调用单个分析维度"""
    if dim == 'announcements':
        return fetch_announcements(stock, market, data_dir,
                                  deep_extract=True, max_critical=5, trace_events=True)
    elif dim == 'financial':
        # 美股走SEC EDGAR XBRL API（结构化数据，503科目）
        if market == 'us':
            return fetch_us_financials(stock)
        return fetch_financials(stock, market, data_dir, skip_pdf=args.no_pdf)
    elif dim == 'executives':
        return fetch_executives(stock, market, data_dir)
    elif dim == 'capital':
        return fetch_capital_actions(stock, market, data_dir)
    elif dim == 'subsidiary':
        return fetch_subsidiary_ipo(stock, market, data_dir)
    elif dim == 'related':
        return fetch_related_deals(stock, market, data_dir)
    elif dim == 'regulatory':
        return fetch_regulatory_history(stock, market, data_dir)
    elif dim == 'structure':
        return build_structure(stock, market, results['findings'], data_dir)
    elif dim == 'industry':
        return fetch_industry(stock, market, data_dir)
    elif dim == 'risk':
        return assess_risk(results['findings'])
    elif dim == 'cross_validation':
        cv = CrossValidator(results['findings'], stock, market)
        return cv.validate()
    elif dim == 'websearch':
        return fetch_websearch(stock, data_dir)
    elif dim == 'annual_pdf':
        return fetch_annual_pdf(stock, data_dir, args)
    elif dim == 'periodic_reports':
        return fetch_periodic_reports(stock, data_dir, args)
    elif dim == 'hk_financial':
        return fetch_hk_financial(stock, market, data_dir)
    elif dim == 'peer_compare':
        return run_peer_compare(stock, data_dir, args)
    elif dim == 'rd_analysis':
        return fetch_rd_analysis(stock, market, data_dir=data_dir)
    elif dim == 'multi_year_trend':
        return fetch_multi_year_trend(stock, market, data_dir=data_dir)
    elif dim == 'valuation':
        return fetch_valuation(stock, market, data_dir=data_dir)
    elif dim == 'governance':
        return fetch_governance(stock, market, data_dir=data_dir)
    elif dim == 'share_history':
        return fetch_share_history(stock, market, data_dir=data_dir)
    elif dim == 'institutional':
        return fetch_institutional(stock, market, data_dir=data_dir)
    elif dim == 'earnings_forecast':
        return fetch_earnings_forecast(stock, market, data_dir=data_dir)
    elif dim == 'investor_qa':
        # investor_qa 需要 announcements 的原始数据
        raw_anns = results.get('findings', {}).get('announcements', {}).get('announcements', [])
        return fetch_investor_qa(stock, market, data_dir=data_dir, raw_announcements=raw_anns)
    elif dim == 'quote':
        # ✅ 傻瓜式四市场自动识别：纯字母=美股，4-5位数字=港股，92xxx=北交所，其余=A股
        # 内部调用 bse_price.py（已内置自动推断，无需手动指定 --market）
        # 批量逗号分隔也支持，自动识别每只股票的市场
        codes_raw = stock.strip()
        # 批量模式：逗号分隔多只，每只独立自动识别市场
        if isinstance(codes_raw, str) and ',' in codes_raw:
            results_all = []
            for c in codes_raw.split(','):
                c = c.strip()
                if not c:
                    continue
                # ✅ 批量时强制 auto，让每只股票独立推断市场
                r = fetch_price(c, 'auto', data_dir)
                if isinstance(r, list):
                    results_all.extend(r)
                elif r:
                    results_all.append(r)
            return results_all
        # 单只：自动识别市场
        return fetch_price(codes_raw, 'auto', data_dir)
    elif dim == 'hkex_announcements':
        # 港交所公告搜索（Playwright自动化）
        if market != 'hk':
            return {'status': 'skip', 'message': '仅支持港股市场'}
        hkex_result = search_hkex_announcements(stock, max_results=20)
        # search_hkex_announcements 返回 list[dict]，需包装为 dict
        if isinstance(hkex_result, list):
            return {
                'announcements': hkex_result,
                'count': len(hkex_result),
                'status': 'ok' if hkex_result else 'empty',
            }
        return hkex_result
    elif dim == 'bse_price':
        result = fetch_price(stock, 'bse', data_dir)
        if isinstance(result, list):
            return result[0] if result else {'status': 'not_found'}
        return result
    return {}


def _infer_source_from_dim(dim, result):
    """
    智能推断数据来源。
    规则：按数据源已知模式推断（大多数脚本没有 _meta.source）。
    返回 None 表示无法推断（走兜底 'unknown'）。
    """
    # 1. 已有 _meta.source 或 result.source
    if isinstance(result, dict):
        meta = result.get('_meta', {})
        src = meta.get('source') or result.get('source')
        if src:
            return src

    # 2. 基于 dim 的行业规律推断
    if dim == 'announcements':
        return 'em_announce'
    elif dim == 'executives':
        return 'em_announce'
    elif dim == 'capital':
        return 'em_announce'
    elif dim == 'related':
        return 'em_announce'
    elif dim == 'regulatory':
        return 'em_announce'
    elif dim == 'structure':
        return 'em_announce'
    elif dim == 'subsidiary':
        return 'em_announce'
    elif dim == 'industry':
        return 'csrc_ak'
    elif dim == 'peer_compare':
        return 'csrc_ak'
    elif dim == 'rd_analysis':
        return 'em_api'
    elif dim == 'governance':
        return 'cninfo_api'
    elif dim == 'share_history':
        return 'cninfo_api'
    elif dim == 'institutional':
        return 'em_api'
    elif dim == 'earnings_forecast':
        return 'em_api'
    elif dim == 'investor_qa':
        return 'szse'
    elif dim == 'risk':
        # risk 是综合评分，source 来自上游各维度
        return 'composite'
    elif dim == 'websearch':
        return 'manual'
    elif dim == 'annual_pdf':
        return 'cninfo_pdf'
    elif dim == 'multi_year_trend':
        return 'em_api'
    elif dim == 'valuation':
        return 'em_api'
    elif dim == 'periodic_reports':
        return 'cninfo_pdf'
    elif dim == 'hk_financial':
        return 'akshare_hk_fin'
    elif dim == 'cross_validation':
        return 'em_api'

    return None


def dim_label(dim):
    labels = {
        'announcements': '公告全景', 'financial': '财务报表', 'executives': '高管动态',
        'capital': '资金动作', 'subsidiary': '子公司IPO', 'related': '关联方运作',
        'regulatory': '监管历史', 'structure': '股权结构', 'industry': '行业竞争', 'risk': '综合风险',
        'websearch': '联网搜索', 'annual_pdf': '年报PDF', 'periodic_reports': '定期报告(年报+半年报+季报)', 'hk_financial': '港股财务',
        'peer_compare': '同业对比', 'rd_analysis': '研发与利润归因',
        'quote': '实时行情', 'bse_price': '实时行情',
        'multi_year_trend': '多年财务趋势', 'valuation': '估值分析',
        'governance': '公司治理', 'share_history': '股本融资历史',
        'institutional': '机构持仓', 'earnings_forecast': '盈利预测',
        'investor_qa': '投资者互动', 'hkex_announcements': '港交所公告',
        'cross_validation': '隐情交叉验证',
    }
    return labels.get(dim, dim)


def dim_summary(dim, result):
    """打印维度摘要"""
    # 批量模式：list → 降级为通用描述
    if isinstance(result, list):
        total = len(result)
        ok = sum(1 for r in result if isinstance(r, dict) and r.get('status') == 'trading')
        if dim in ('quote', 'bse_price'):
            return f"批量行情: {total}只 [{ok}只交易中]"
        return f"批量结果: {total}项"
    summaries = {
        'announcements': f"公告{result.get('count',0)}条 | CRITICAL:{result.get('importance_stats',{}).get('critical',0)} MAJOR:{result.get('importance_stats',{}).get('major',0)} ROUTINE:{result.get('importance_stats',{}).get('routine',0)} | 溯源链:{len(result.get('event_chains',{}))}条",
        'financial': f"审计意见: {result.get('audit_opinion','未知')}",
        'executives': f"发现 {result.get('change_count',0)} 条高管变动",
        'capital': f"发现 {result.get('count',0)} 项资金动作",
        'subsidiary': f"辅导期数: {result.get('report_count','未知')}",
        'related': f"发现 {result.get('count',0)} 项运作",
        'regulatory': f"发现 {result.get('count',0)} 条监管记录",
        'industry': f"行业: {result.get('industry_class',{}).get('csrc_industry') or result.get('industry_class',{}).get('sw_industry') or '未知'} | 可比公司{len(result.get('competitors',[]))}家",
        'risk': f"风险等级: {result.get('level','未知')} | 得分: {result.get('score','?')}/100",
        'websearch': f"搜索完成",
        'annual_pdf': f"年报: {result.get('year','?')}年 | {result.get('page_count',0)}页" if result and not result.get('error') else "年报: 获取失败",
        'periodic_reports': f"定期报告: 已下载{result.get('summary',{}).get('total_downloaded',0)}份" if result and not result.get('error') else "定期报告: 获取失败",
        'hk_financial': f"财务数据: {result.get('profile',{}).get('company_name_cn','?')} | 营收 {result.get('valuation',{}).get('revenue','?')}",
        'cross_validation': f"隐情 {len(result.get('findings',[]))} 条 | 综合风险评分: {result.get('overall_risk_score','?')}/100",
        'peer_compare': f"同业公司: {result.get('peer_count',0)}家 | 对比结论: {result.get('conclusion','N/A')}",
        'rd_analysis': f"主因: {result.get('profit_decomposition',{}).get('primary_cause','未知')} | 研发: {result.get('rd_quality',{}).get('rd_expense_亿','N/A')}亿元(资本化{result.get('rd_quality',{}).get('capitalization_rate','N/A')}%) | {result.get('rd_vs_loss_summary','N/A')}",
        'quote': '行情维度',
        'bse_price': '行情维度',
    }
    val = summaries.get(dim, '')
    if callable(val):
        val = val(result)
    return val


def run_peer_compare(stock, data_dir, args):
    """同业对比维度：调用 PeerComparator"""
    try:
        comp = PeerComparator()
        data = comp.compare(stock)
        md = comp.format_markdown(data) if data else ''
        # 结论文本从 format_markdown() 末尾提取（"## 同业对比结论" 章节最后几行）
        conclusion = ''
        if md:
            parts = md.split('## 同业对比结论')
            if len(parts) > 1:
                conc_block = parts[-1].strip().split('\n')
                conc_lines = [l.strip() for l in conc_block if l.strip() and not l.strip().startswith('**⚠️')]
                conclusion = conc_lines[0] if conc_lines else ''
        return {
            'has_data': data is not None and bool(md),
            'markdown': md,
            'target': data.get('target', {}) if data else {},
            'stats': data.get('stats', {}) if data else {},
            'peer_count': len(data.get('peers', [])) if data else 0,
            'conclusion': conclusion,
        }
    except Exception as e:
        return {'error': str(e), 'has_data': False}


def _get_company_name(stock):
    """获取公司名称 — 多数据源降级"""
    # 数据源1: datacenter估值API（最可靠）
    try:
        prefix = 'SZ' if stock[:2] in ['00','30'] else 'SH'
        secucode = f"{stock}.{prefix}"
        from scripts.valuation import _fetch_valuation_data
        val = _fetch_valuation_data(secucode)
        if val and val.get('SECURITY_NAME_ABBR'):
            return val['SECURITY_NAME_ABBR']
    except:
        pass
    # 数据源2: 行情API（f58字段）
    try:
        import requests
        mid = '0' if stock[:2] in ['00','30'] else '1'
        url = "http://push2.eastmoney.com/api/qt/stock/get"
        params = {'secid': f'{mid}.{stock}', 'fields': 'f58', 'ut': 'fa1fd612f2f5e7b0'}
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://data.eastmoney.com/'}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json().get('data', {})
        name = data.get('f58', '')
        if name:
            return name
    except:
        pass
    return ''


def fetch_websearch(stock, data_dir):
    """联网搜索维度（目前主要是年报PDF搜索）"""
    import json, requests
    
    company_name = _get_company_name(stock)
    
    # 搜索年报PDF
    try:
        reports = get_annual_report_list(stock, company_name, years=3)
    except Exception as e:
        print(f"[ERROR] get_annual_report_list: {e}")
        reports = []
    
    return {
        'count': len(reports),
        'reports': reports,
        'company_name': company_name,
    }


def fetch_annual_pdf(stock, data_dir, args):
    """年报PDF下载与提取"""
    import json, requests
    
    company_name = _get_company_name(stock)
    
    # 下载并提取年报
    try:
        result = download_and_extract(stock, company_name, data_dir)
    except Exception as e:
        print(f"[ERROR] download_and_extract: {e}")
        result = {'error': str(e)}
    
    # 保存提取结果
    if result and not result.get('error'):
        text_path = os.path.join(data_dir, 'annual_report_text.txt')
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(result.get('text_preview', ''))
        
        # 保存章节提取结果
        sections = result.get('sections', {})
        if sections:
            sections_path = os.path.join(data_dir, 'annual_report_sections.json')
            with open(sections_path, 'w', encoding='utf-8') as f:
                json.dump(sections, f, ensure_ascii=False, indent=2)
    
    return result


def fetch_periodic_reports(stock, data_dir, args):
    """定期报告（年报+半年报+季报）PDF下载与提取"""
    import json
    from scripts.pdf_download import download_and_extract_periodic, REPORT_CATEGORIES

    company_name = _get_company_name(stock)
    report_type = getattr(args, 'report_type', 'all') or 'all'
    years = getattr(args, 'report_years', 1) or 1

    try:
        result = download_and_extract_periodic(
            stock, company_name, save_dir=data_dir,
            report_type=report_type, years=years
        )
    except Exception as e:
        print(f"[ERROR] download_and_extract_periodic: {e}")
        result = {'error': str(e)}

    # 保存各报告的章节提取结果
    if result and not result.get('error'):
        reports = result.get('reports', {})
        for rtype, year_data in reports.items():
            if isinstance(year_data, dict) and 'status' not in year_data:
                for year, info in year_data.items():
                    sections = info.get('sections', {})
                    if sections:
                        sections_path = os.path.join(data_dir, f'{rtype}_{year}_sections.json')
                        with open(sections_path, 'w', encoding='utf-8') as f:
                            json.dump(sections, f, ensure_ascii=False, indent=2)

    return result


def main():
    args = parse_args()
    is_unlisted = bool(args.company)

    if is_unlisted:
        # ── 未上市公司分析模式 ──────────────────────────────
        company_name = args.company.strip()
        date_str = datetime.now().strftime('%Y%m%d')
        safe_name = re.sub(r'[^\w\u4e00-\u9fa5]+', '_', company_name)
        out_dir = args.output or f"output/{safe_name}_{date_str}"
        os.makedirs(out_dir, exist_ok=True)
        data_dir = os.path.join(out_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)

        ALL_DIMS_UNLISTED = ['basic', 'equity', 'financing', 'legal', 'news', 'ipo', 'esop']
        if args.full or args.dims == 'all':
            dims = ALL_DIMS_UNLISTED
        else:
            dims = [d.strip() for d in args.dims.split(',')]

        print(f"\n{'='*60}")
        print(f"  未上市公司全景分析")
        print(f"  公司: {company_name}")
        print(f"  维度: {', '.join(dims)}")
        print(f"  输出: {out_dir}")
        print(f"{'='*60}\n")

        results = {
            'company': company_name, 'mode': 'unlisted',
            'dims': dims, 'date': date_str, 'findings': {}
        }

        # 未上市公司7维度分析
        unlisted_all = fetch_unlisted_company(company_name, dims=dims, data_dir=data_dir)
        results['findings'] = unlisted_all

        # 打印摘要
        summary_text = format_unlisted_summary(unlisted_all)
        print(f"\n{'─'*60}")
        print(f"  汇总: {summary_text}")
        print(f"{'─'*60}\n")

        # 生成报告
        from scripts.unlisted_report import generate_unlisted_report
        report_path = generate_unlisted_report(results, out_dir, company_name)
        print(f"{'='*60}")
        print(f"生成分析报告...")
        print(f"  → 报告已保存: {report_path}")

        data_path = os.path.join(data_dir, 'results.json')
        with open(data_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"📝 原始数据: {data_path}")
        print(f"✅ 分析完成！报告: {report_path}")
        return

    # 中文公司名识别模式
    if args.name:
        company_query = args.name.strip()
        resolver_result = resolve_company_name(company_query)

        if resolver_result['total'] == 0:
            print(f"⚠️ 未找到匹配的上市公司: '{company_query}'")
            print("   建议: 尝试使用完整公司名或股票代码")
            return

        if resolver_result['has_multi_market']:
            print(f"📊 检测到跨市场上市，将合并分析...")
            for g in resolver_result['groups']:
                print(f"  🏢 {g['company_name']} [{g['summary']}]")
                for l in g['listings']:
                    mkt = {'a': 'A股', 'hk': '港股', 'us': '美股', 'bse': '北交所'}.get(l['market'], l['market'])
                    print(f"      {l['stock']:>10s}  ({mkt:>4s})")

        # 获取所有股票代码（去重）
        all_codes = list(set(r['stock'] for r in resolver_result['results']))
        all_markets = list(set(r['market'] for r in resolver_result['results']))

        # 简单情况：只有一个匹配
        if len(all_codes) == 1:
            args.stock = all_codes[0]
            # 不覆盖 args.market，保持 auto
            print(f"📌 自动选择: {all_codes[0]}")
        else:
            # 多个匹配：先做行情查询
            args.stock = ','.join(all_codes)
            if args.dims == 'all':
                args.dims = 'quote'  # 多只股票默认只查行情
            print(f"📌 自动选择多只股票行情模式")
        # 继续执行常规分析（不 return）

    # 上市公司分析模式
    stock = args.stock.strip()
    market = args.market  # 'auto' resolved in call_dim for quote; actual market used for other dims
    # 自动推断市场（非quote维度需要明确的A股/港股/美股）
    if market == 'auto':
        resolved = infer_market(stock.split(',')[0].strip())
        market = resolved
        print(f"  [自动识别] {stock.split(',')[0].strip()} → {resolved} 市场")

    date_str = datetime.now().strftime('%Y%m%d')
    import re
    stock_clean = re.sub(r'[^0-9A-Za-z]', '_', stock)
    # 默认输出到skill目录下的output/，避免相对路径散落
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(script_dir, 'output', f'{stock_clean}_{date_str}')
    out_dir = args.output or default_out
    os.makedirs(out_dir, exist_ok=True)
    data_dir = os.path.join(out_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    # 港股/美股用 --market hk + --dims hk_financial, us用yfinance
    ALL_DIMS_A = ['announcements', 'financial', 'executives', 'capital',
                  'subsidiary', 'related', 'regulatory', 'structure', 'industry',
                  'peer_compare', 'rd_analysis', 'risk',
                  'websearch', 'annual_pdf', 'periodic_reports', 'quote',
                  'multi_year_trend', 'valuation', 'governance',
                  'share_history', 'institutional', 'earnings_forecast',
                  'investor_qa', 'cross_validation']
    ALL_DIMS_HK = ['announcements', 'hk_financial', 'hkex_announcements', 'industry', 'risk', 'quote',
                  'multi_year_trend', 'valuation']
    ALL_DIMS_US = [
        'announcements', 'quote', 'financial', 'industry', 'risk',
        'structure', 'executives', 'capital', 'governance', 'regulatory',
        'multi_year_trend', 'valuation', 'share_history'
    ]
    ALL_DIMS = ALL_DIMS_HK if market == 'hk' else (ALL_DIMS_US if market == 'us' else ALL_DIMS_A)
    if args.full or args.dims == 'all':
        dims = ALL_DIMS
    else:
        dims = [d.strip() for d in args.dims.split(',')]

    # 跳过选项
    if args.no_peer and 'peer_compare' in dims:
        dims.remove('peer_compare')

    print(f"\n{'='*60}")
    print(f"  上市公司全景分析")
    market_name = {'a': 'A股', 'hk': '港股', 'us': '美股'}.get(market, market)
    print(f"  代码: {stock} ({market_name})")
    print(f"  维度: {', '.join(dims)}")
    print(f"  输出: {out_dir}")
    print(f"{'='*60}\n")

    results = {
        'stock': stock, 'market': market, 'dims': dims,
        'date': date_str, 'findings': {}, '_traces': []
    }

    for i, dim in enumerate(dims):
        label = dim_label(dim)
        step_num = i + 1
        print(f"[{step_num}/{len(dims)}] {label}...")
        try:
            result = call_dim(dim, stock, market, data_dir, results, args)
        except Exception as e:
            print(f"  ⚠️ {dim}维度异常: {e}")
            result = {'error': str(e), 'warnings': [f'维度执行异常: {e}']}
        results['findings'][dim] = result

        # 溯源轨迹收集（兼容两种source格式：_meta.source 或 顶层 source）
        # 🔧 修复：多数脚本没有写 _meta.source，全部显示 "未知来源"
        # 兜底策略：
        #   1. _meta.source
        #   2. 顶层 result.source
        #   3. 基于 dim 名称智能推断（按数据源规律）
        if isinstance(result, dict):
            meta = result.get('_meta', {})
            src = meta.get('source', result.get('source', None))
        else:
            meta = {}
            src = None

        # 智能推断：常见数据源模式
        if not src:  # 只有为None时才兜底，'' 空字符串也走兜底
            src = _infer_source_from_dim(dim, result)

        # 最终兜底：从未获取到任何source信息
        if not src:
            src = 'unknown'

        src_label = SOURCE_LABELS.get(src, src)
        status = 'OK' if src not in ('all_failed', 'unknown') else 'FAIL'
        results['_traces'].append({
            'dim': dim, 'dim_label': dim_label(dim),
            'source': src, 'source_label': src_label,
            'status': status,
            'msg': dim_summary(dim, result),
            'pdf_source': meta.get('pdf_source'),
            'pdf_path': meta.get('pdf_path'),
            'fetched_at': meta.get('fetched_at', ''),
        })

        smry = dim_summary(dim, result)
        if smry:
            src_emoji = '✅' if src not in ('all_failed', 'unknown') else '❌'
            print(f"  {src_emoji} 来源: {src_label} | {smry}")
        print()

    # 后处理：如果年报PDF已完成，补充审计意见
    _postprocess_audit_opinion(results, data_dir)

    # 生成可视化图表（如果包含相关维度）
    if any(d in dims for d in ['earnings_forecast', 'multi_year_trend', 'peer_compare', 'risk', 'industry', 'structure']):
        print(f"\n{'='*60}")
        print("生成可视化图表...")
        try:
            from scripts.visualization import generate_all_charts
            chart_paths = generate_all_charts(results['findings'], stock, out_dir)
            if chart_paths:
                results['findings']['charts'] = chart_paths
                for name, path in chart_paths.items():
                    print(f"  📊 {name}: {os.path.basename(path)}")
            else:
                print("  ⚠️ 未生成图表（数据不足）")
        except Exception as e:
            print(f"  ⚠️ 图表生成失败: {e}")

    # 溯源轨迹汇总
    print(f"\n{'='*60}")
    print("📋 数据来源溯源表：")
    print(f"{'─'*60}")
    for t in results['_traces']:
        icon = '✅' if t['status'] == 'OK' else '❌'
        pdf_note = f" [PDF:{t['pdf_source']}]" if t.get('pdf_source') else ''
        print(f"  {icon} {t['dim_label']:<10s} → {t['source_label']:<20s}{pdf_note}")

    # 生成报告（含溯源表）
    print(f"\n{'='*60}")
    print("生成分析报告...")
    report_path = generate_report(results, out_dir)
    print(f"  → 报告已保存: {report_path}")

    data_path = os.path.join(data_dir, 'results.json')
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  → 原始数据: {data_path}")
    print(f"\n✅ 分析完成！报告: {report_path}")


def _postprocess_audit_opinion(results, data_dir):
    """后处理：如果年报PDF已完成，用PDF审计意见替换推断的审计意见"""
    fin = results.get('findings', {}).get('financial', {})
    pdf = results.get('findings', {}).get('annual_pdf', {})
    
    if not fin or not pdf or pdf.get('error'):
        return
    
    # 检查当前审计意见是否为"推断"
    current = fin.get('audit_opinion') or ''
    if '推断' not in current:
        return  # 已经是精确值，无需替换
    
    # 从年报PDF提取审计意见
    from scripts.financials import _get_audit_opinion
    stock_code = results.get('stock', '')
    eps = fin.get('summary', {}).get('eps')
    roe = fin.get('summary', {}).get('roe_pct')
    
    opinion = _get_audit_opinion(stock_code, data_dir, eps, roe)
    if opinion and '推断' not in opinion:
        fin['audit_opinion'] = opinion
        # 从key_risks中移除推断相关的风险提示
        fin['key_risks'] = [r for r in fin.get('key_risks', []) if '推断' not in r]
        print(f"  📝 审计意见更新: {opinion}")


if __name__ == '__main__':
    main()
