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

# 新增战略分析模块
from scripts.national_strategy import analyze_national_strategy, format_strategy_report
from scripts.industry_analysis import analyze_industry, format_industry_report
from scripts.competition_analysis import analyze_competition, format_competition_report
from scripts.product_analysis import analyze_product_and_business, format_product_report
from scripts.capacity_analysis import analyze_capacity, format_capacity_report
from scripts.subcompany_analysis import analyze_subcompanies, format_subcompany_report

# 新增公告分析模块
from scripts.exchange_api import get_announcement_timeline, format_announcement_report
from scripts.ai_announcement_analyzer import analyze_announcement_risk, format_ai_analysis_report

from scripts.cli import parse_args, dim_label, dim_summary
from scripts.dispatcher import (
    call_dim, infer_source_from_dim, run_peer_compare, get_company_name,
    fetch_websearch, fetch_annual_pdf, fetch_periodic_reports,
)

# NOTE: parse_args, dim_label, dim_summary 已提取到 scripts/cli.py
# NOTE: call_dim, infer_source_from_dim 等已提取到 scripts/dispatcher.py

def main():
    args = parse_args()

    # 处理 tmp 管理命令
    if args.tmp_status:
        from scripts.tmp_paths import get_tmp_usage, format_size
        usage = get_tmp_usage()
        print("=== tmp目录使用情况 ===")
        for name, info in usage.items():
            print(f"  {name:12s}: {info['files']:>6d} 个文件, {format_size(info['bytes'])}")
        return

    if args.cleanup:
        from scripts.tmp_paths import cleanup_expired_files, format_size
        days = args.cleanup_days
        print(f"清理 {days} 天未访问的临时文件...")
        result = cleanup_expired_files(retention_days=days, dry_run=False)
        print(f"  删除文件: {result['files_removed']} 个")
        print(f"  释放空间: {format_size(result['bytes_removed'])}")
        print(f"  删除空目录: {result['dirs_removed']} 个")
        return

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
    # 维度顺序：先运行基础模块（数据采集），再运行增强模块（深度分析）
    BASE_DIMS_A = ['announcements', 'financial', 'executives', 'capital',
                   'subsidiary', 'related', 'regulatory', 'structure', 'industry',
                   'peer_compare', 'rd_analysis', 'risk',
                   'websearch', 'annual_pdf', 'periodic_reports', 'quote',
                   'multi_year_trend', 'valuation', 'governance',
                   'share_history', 'institutional', 'institutional_visit',
                   'seasoned_offerings', 'shareholders_meeting', 'earnings_forecast',
                   'investor_qa', 'cross_validation']
    
    ENHANCED_DIMS_A = ['value_chain', 'ma_deep', 'strategic_narrative', 'competition_map', 'enhanced_company_info', 'cross_market_scan']
    
    ALL_DIMS_A = BASE_DIMS_A + ENHANCED_DIMS_A
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
            src = infer_source_from_dim(dim, result)

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

    # ============================================================
    # 阶段2：统一AI分析（所有数据采集完成后，一次性AI解读）
    # ============================================================
    findings = results['findings']
    company_name = findings.get('quote', {}).get('name', '')
    try:
        from scripts.ai_unified_analyzer import unified_analyze
        ai_result = unified_analyze(findings, company_name=company_name, stock_code=stock)
        findings['ai_analysis'] = ai_result
    except Exception as e:
        print(f"  ⚠️ 统一AI分析失败: {e}")
        findings['ai_analysis'] = {}

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

    # 生成HTML报告
    try:
        from scripts.report_html import generate_html_report
        html_path = generate_html_report(results, out_dir)
        print(f"  → HTML报告已保存: {html_path}")
        
        # 自动打开HTML报告
        try:
            import webbrowser
            webbrowser.open('file:///' + html_path.replace('\\', '/'))
            print(f"  🌐 HTML报告已在浏览器中打开")
        except Exception as e:
            print(f"  ⚠️ 打开浏览器失败: {e}")
    except Exception as e:
        print(f"  ⚠️ HTML报告生成失败: {e}")

    # 如果启用 AI 报告，调用首席分析师
    if args.ai_report:
        try:
            from scripts.ai_comprehensive_report import generate_comprehensive_report
            analyst_report = generate_comprehensive_report(results, output_dir=out_dir)
            if analyst_report:
                print(f"  → AI首席分析师报告已生成")
        except ImportError:
            print("  ⚠️ AI 分析师模块未找到，跳过 AI 报告生成")
        except Exception as e:
            print(f"  ⚠️ AI 报告生成失败: {e}")

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
        # 同时更新risk signals（风险模块在annual_pdf之前运行，需同步更新）
        risk = results.get('findings', {}).get('risk', {})
        sigs = risk.get('signals', [])
        new_sigs = [s for s in sigs if s.get('dim') != '审计意见']  # 移除旧推断信号
        # 根据新opinion重建审计意见信号（与risk.py保持一致）
        has_unreserved = '无保留意见' in opinion
        has_reserved = '保留意见' in opinion and not has_unreserved
        has_adverse = '无法表示意见' in opinion or '否定意见' in opinion
        is_reserved = has_reserved or has_adverse
        is_empha = '强调事项' in opinion and has_unreserved
        if is_reserved:
            new_sigs.insert(0, {'dim': '审计意见', 'level': '🔴 高',
                                'detail': f'审计意见：{opinion}'})
        elif is_empha:
            new_sigs.insert(0, {'dim': '审计意见', 'level': '🟡 中',
                                'detail': f'审计意见：{opinion}'})
        risk['signals'] = new_sigs
        print(f"  📝 审计意见更新: {opinion}")


if __name__ == '__main__':
    main()
