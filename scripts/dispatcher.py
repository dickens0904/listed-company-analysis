# -*- coding: utf-8 -*-
"""
维度调度器 — 从 analyze.py 提取的维度调用逻辑

包含：call_dim（维度调度）、数据源推断、辅助函数
"""
from __future__ import annotations
import os
import json
import logging

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
from scripts.source_tracker import SOURCE_LABELS
from scripts.websearch import search_cninfo_annual, parse_cninfo_response
from scripts.pdf_download import download_and_extract, get_annual_report_list
from scripts.hk_financial import fetch_hk_financial
from scripts.peer_compare import PeerComparator
from scripts.rd_analysis import fetch_rd_analysis
from scripts.bse_price import fetch_price, infer_market
from scripts.multi_year_trend import fetch_multi_year_trend
from scripts.valuation import fetch_valuation
from scripts.governance import fetch_governance
from scripts.share_history import fetch_share_history
from scripts.institutional import fetch_institutional
from scripts.institutional_visit import analyze_institutional_visits
from scripts.seasoned_offerings import analyze_seasoned_offerings
from scripts.shareholders_meeting import analyze_shareholders_meeting
from scripts.earnings_forecast import fetch_earnings_forecast
from scripts.investor_qa import fetch_investor_qa
from scripts.hkex_announcements import search_hkex_announcements
from scripts.cross_validator import CrossValidator
from scripts.strategic_opportunity import analyze_strategic_opportunity
from scripts.three_statements import ThreeStatementsExtractor
from scripts.us_financial import get_us_company_info
from scripts.sec_xbrl_api import fetch_us_financials
from scripts.value_chain_analysis import ValueChainAnalyzer, fetch_value_chain
from scripts.ma_deep_analysis import MADeepAnalyzer, fetch_ma_deep_analysis
from scripts.strategic_narrative import StrategicNarrativeGenerator, fetch_strategic_narrative
from scripts.competition_map import CompetitionMapGenerator, fetch_competition_map
from scripts.enhanced_company_info_extractor import EnhancedCompanyInfoExtractor
from scripts.cross_market_scanner import CrossMarketScanner
from scripts.prospectus import fetch_prospectus, query_registry  # v3:招股书备案系统
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

logger = logging.getLogger(__name__)


def load_local_data(data_dir: str) -> dict:
    """加载本地已有数据，避免重复获取

    Args:
        data_dir: 数据目录路径

    Returns:
        包含所有已加载数据的字典
    """
    local_data = {
        'results': {},
        'announcements': {},
        'financial': {},
        'annual_report_sections': {},
        'financial_metrics': {},
        'industry': {},
        'peer_compare': {},
        'value_chain': {},
        'ma_deep': {},
        'strategic_narrative': {},
        'competition_map': {}
    }

    if not data_dir or not os.path.exists(data_dir):
        return local_data

    try:
        # 1. 加载results.json（包含所有维度结果）
        results_file = os.path.join(data_dir, 'results.json')
        if os.path.exists(results_file):
            with open(results_file, 'r', encoding='utf-8') as f:
                results_data = json.load(f)
                local_data['results'] = results_data
                findings = results_data.get('findings', {})
                for key in local_data.keys():
                    if key in findings:
                        local_data[key] = findings[key]

        # 2. 加载announcements.json
        ann_file = os.path.join(data_dir, 'announcements.json')
        if os.path.exists(ann_file):
            with open(ann_file, 'r', encoding='utf-8') as f:
                local_data['announcements'] = json.load(f)

        # 3. 加载financial_metrics.json
        fm_file = os.path.join(data_dir, 'financial_metrics.json')
        if os.path.exists(fm_file):
            with open(fm_file, 'r', encoding='utf-8') as f:
                local_data['financial_metrics'] = json.load(f)

        # 4. 加载annual_report_sections.json
        ars_file = os.path.join(data_dir, 'annual_report_sections.json')
        if os.path.exists(ars_file):
            with open(ars_file, 'r', encoding='utf-8') as f:
                local_data['annual_report_sections'] = json.load(f)

        # 5. 加载其他独立维度文件
        dimension_files = {
            'industry': 'industry.json',
            'peer_compare': 'peer_compare.json',
            'value_chain': 'value_chain.json',
            'ma_deep': 'ma_deep_analysis.json',
            'strategic_narrative': 'strategic_narrative.json',
            'competition_map': 'competition_map.json'
        }

        for key, filename in dimension_files.items():
            file_path = os.path.join(data_dir, filename)
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    local_data[key] = json.load(f)

    except Exception as e:
        logger.warning(f"加载本地数据失败: {e}")

    return local_data


def call_dim(dim: str, stock: str, market: str, data_dir: str, results: dict, args) -> dict:
    """
    调用单个分析维度（P1：统一溯源标注层）。

    2026-10-16 审计修复：旧版只有 financials.py 真正接入 SourceTracker，
    其余 140+ 模块的 _meta.source 全为空，靠 infer_source_from_dim 猜。
    本包装层为**每个**维度统一打上：
        _meta.source   实际来源（保留原值，缺失时按注册表补）
        _meta.tier     数据源层级（T1-MCP / T2-OFFICIAL / T3-API / T4-CRAWLER ...）
        _meta.mcp      若存在 MCP 回填数据，附上 mcp:<tool>
        _meta.deprecated_warning  若该维度依赖已废弃源，附警示
    """
    result = _dispatch_dim(dim, stock, market, data_dir, results, args)

    # ── 统一溯源标注（P1）──
    try:
        from data_source_registry import SOURCE_REGISTRY, DEPRECATED_SOURCES, TIER_LABELS

        if isinstance(result, dict):
            meta = result.get('_meta') or {}
            spec = SOURCE_REGISTRY.get(dim, {})

            # 1) source：保留原有值；为空时按注册表 legacy 首项补
            src = meta.get('source') or result.get('source')
            if not src and dim in ('legal_risk', 'intellectual_property'):
                src = 'qcc-company'   # 权威源维度，避免被回退标成 cross_validator
            if not src and spec.get('legacy'):
                src = spec['legacy'][0][0].split('.')[-1]
            if src:
                meta['source'] = src

            # 2) tier：按注册表判定；MCP 回填存在则升为 T1
            tier = None
            for mod, t, _ in spec.get('legacy', []):
                if mod.split('.')[-1] == src:
                    tier = t
                    break
            if tier is None:
                # 未登记来源：本地复合计算维度标 composite，其余保守记 T3-API
                tier = 0 if dim in ('risk', 'cross_validation', 'investment_thesis',
                                    'strategic_narrative', 'competition_map',
                                    'value_chain', 'ma_deep') else 3

            # 3) MCP 回填合并（T1 优先）
            mcp_hit = _find_mcp_backfill(data_dir, dim)
            if mcp_hit:
                meta['mcp'] = mcp_hit.get('source')
                meta['mcp_tool'] = mcp_hit.get('tool')
                meta['mcp_fetched_at'] = mcp_hit.get('fetched_at')
                tier = 1  # 有 MCP 回填即视为 T1
                # 把 MCP 原始结果挂到结果上，供分析模块优先使用
                result.setdefault('mcp_data', mcp_hit.get('data'))

            meta['tier'] = TIER_LABELS.get(tier, f'T{tier}')

            # 4) 废弃源警示（兼容裸名与 scripts.xxx 全路径两种写法）
            if src:
                dep = (DEPRECATED_SOURCES.get(src)
                       or DEPRECATED_SOURCES.get(f'scripts.{src}'))
                if dep:
                    meta['deprecated_warning'] = dep['reason']
                    meta['replacement'] = dep['replacement']

            result['_meta'] = meta
    except Exception as e:
        # 溯源标注失败不得影响主流程
        if isinstance(result, dict):
            result.setdefault('_meta', {})['trace_error'] = str(e)

    return result


def _find_mcp_backfill(data_dir: str, dim: str):
    """查找该维度是否已有 MCP 回填数据"""
    if not data_dir:
        return None
    try:
        from mcp_bridge import load_mcp_results
        allm = load_mcp_results(data_dir)
        return allm.get(dim)
    except Exception:
        return None


def _dispatch_dim(dim: str, stock: str, market: str, data_dir: str, results: dict, args) -> dict:
    """维度分发本体（原 call_dim 逻辑，未改动）"""
    if dim == 'announcements':
        return fetch_announcements(stock, market, data_dir,
                                  deep_extract=True, max_critical=5, trace_events=True)
    elif dim == 'financial':
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
        financial_data = results.get('findings', {}).get('financial', {})
        return fetch_valuation(stock, market, data_dir=data_dir, financial_data=financial_data)
    elif dim == 'governance':
        annual_pdf_data = results.get('findings', {}).get('annual_pdf', {})
        financial_data = results.get('findings', {}).get('financial', {})
        announcements_data = results.get('findings', {}).get('announcements', {})
        return fetch_governance(stock, market, data_dir=data_dir, annual_pdf_data=annual_pdf_data, financial_data=financial_data, announcements_data=announcements_data)
    elif dim == 'share_history':
        return fetch_share_history(stock, market, data_dir=data_dir)
    elif dim == 'institutional':
        return fetch_institutional(stock, market, data_dir=data_dir)
    elif dim == 'institutional_visit':
        return analyze_institutional_visits(stock, months=12)
    elif dim == 'seasoned_offerings':
        return analyze_seasoned_offerings(stock)
    elif dim == 'shareholders_meeting':
        announcements_data = results.get('findings', {}).get('announcements', {})
        return analyze_shareholders_meeting(stock, announcements_data=announcements_data)
    elif dim == 'earnings_forecast':
        return fetch_earnings_forecast(stock, market, data_dir=data_dir)
    elif dim == 'investor_qa':
        ann_data = results.get('findings', {}).get('announcements', {})
        raw_anns = (
            ann_data.get('critical_announcements', []) +
            ann_data.get('major_announcements', []) +
            ann_data.get('routine_announcements', [])
        )
        return fetch_investor_qa(stock, market, data_dir=data_dir, raw_announcements=raw_anns)
    elif dim == 'quote':
        codes_raw = stock.strip()
        if isinstance(codes_raw, str) and ',' in codes_raw:
            results_all = []
            for c in codes_raw.split(','):
                c = c.strip()
                if not c:
                    continue
                r = fetch_price(c, 'auto', data_dir)
                if isinstance(r, list):
                    results_all.extend(r)
                elif r:
                    results_all.append(r)
            return results_all
        return fetch_price(codes_raw, 'auto', data_dir)
    elif dim == 'hkex_announcements':
        if market != 'hk':
            return {'status': 'skip', 'message': '仅支持港股市场'}
        hkex_result = search_hkex_announcements(stock, max_results=20)
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
    elif dim == 'strategic_opportunity':
        annual_sections = results.get('findings', {}).get('annual_pdf', {}).get('sections', {})
        if not annual_sections:
            sections_file = os.path.join(data_dir, 'annual_report_sections.json') if data_dir else None
            if sections_file and os.path.exists(sections_file):
                with open(sections_file, 'r', encoding='utf-8') as f:
                    annual_sections = json.load(f)
        financial_data = results.get('findings', {}).get('financial', {})
        basic_info = results.get('findings', {}).get('basic_info', {})
        stock_name = basic_info.get('name') or basic_info.get('company_name', '')
        return analyze_strategic_opportunity(stock, data_dir, annual_sections, financial_data, stock_name)
    elif dim == 'three_statements':
        pdf_files = [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.endswith('.pdf') and 'annual' in f.lower()]
        if pdf_files:
            extractor = ThreeStatementsExtractor(pdf_files[0])
            return extractor.extract_all()
        return {'status': 'no_pdf', 'message': '未找到年报PDF文件'}
    elif dim == 'value_chain':
        # 优先使用results中的数据（本次运行已获取）
        announcements_data = results.get('findings', {}).get('announcements', {})
        financials_data = results.get('findings', {}).get('financial', {})

        # 补充加载本地已有数据
        local_data = load_local_data(data_dir)

        # 获取annual_report_sections（优先从本地文件）
        annual_sections = local_data.get('annual_report_sections', {})
        if not annual_sections:
            # 也尝试从results中获取
            annual_sections = results.get('findings', {}).get('annual_report_sections', {})

        # 获取财务指标
        financial_metrics = local_data.get('financial_metrics', {})
        if not financial_metrics:
            # 也尝试从results中获取
            financial_metrics = results.get('findings', {}).get('financial_metrics', {})

        analyzer = ValueChainAnalyzer(
            annual_sections=annual_sections,
            financials=financials_data,
            stock_code=stock,
            market=market,
            financial_metrics=financial_metrics
        )
        return analyzer.analyze()
    elif dim == 'ma_deep':
        # 优先使用results中的数据
        announcements_data = results.get('findings', {}).get('announcements', {})
        financials_data = results.get('findings', {}).get('financial', {})
        annual_sections_data = results.get('findings', {}).get('annual_report_sections', {})

        # 补充加载本地已有数据
        local_data = load_local_data(data_dir)

        # 获取财务指标
        financial_metrics = local_data.get('financial_metrics', {})
        if not financial_metrics:
            financial_metrics = results.get('findings', {}).get('financial_metrics', {})

        # 获取announcements（如果results中没有）
        if not announcements_data:
            announcements_data = local_data.get('announcements', {})

        # 获取annual_sections（如果results中没有）
        if not annual_sections_data:
            annual_sections_data = local_data.get('annual_report_sections', {})

        analyzer = MADeepAnalyzer(
            announcements=announcements_data,
            financials=financials_data,
            annual_sections=annual_sections_data,
            financial_metrics=financial_metrics,
            stock_code=stock,
            market=market
        )
        return analyzer.analyze()
    elif dim == 'strategic_narrative':
        # 优先使用results中的数据
        all_data = {}

        # 从results获取
        findings = results.get('findings', {})
        for key in ['announcements', 'financial', 'industry', 'peer_compare', 'value_chain', 'ma_deep', 'financial_metrics']:
            if key in findings:
                all_data[key] = findings[key]

        # 补充加载本地已有数据
        local_data = load_local_data(data_dir)

        # 合并本地数据（不覆盖已获取的数据）
        for key, value in local_data.items():
            if key not in all_data and value:
                all_data[key] = value

        generator = StrategicNarrativeGenerator(
            all_data=all_data,
            stock_code=stock,
            market=market
        )
        return generator.generate_narrative()
    elif dim == 'competition_map':
        # 优先使用results中的数据
        industry_data = results.get('findings', {}).get('industry', {})
        peer_data = results.get('findings', {}).get('peer_compare', {})
        financial_data = {}

        # 从results获取financial_metrics
        fm = results.get('findings', {}).get('financial_metrics', {})
        if fm:
            financial_data['financial_metrics'] = fm

        # 补充加载本地已有数据
        local_data = load_local_data(data_dir)

        # 合并本地数据（不覆盖已获取的数据）
        if not industry_data:
            industry_data = local_data.get('industry', {})
        if not peer_data:
            peer_data = local_data.get('peer_compare', {})
        if not financial_data:
            financial_data = local_data.get('financial_metrics', {})

        generator = CompetitionMapGenerator(
            industry_data=industry_data,
            peer_data=peer_data,
            financial_data=financial_data,
            stock_code=stock,
            market=market
        )
        return generator.generate_competition_map()
    elif dim == 'enhanced_company_info':
        extractor = EnhancedCompanyInfoExtractor(stock, market, data_dir)
        extractor.load_data()
        return extractor.extract_all_info()
    elif dim == 'prospectus':
        # v3:招股书维度 —— 三市场招股说明书获取与备案
        return fetch_prospectus(stock, stock_name=results.get('findings', {}).get('company', {}).get('name', ''),
                                market=market, auto_download=False)
    elif dim == 'prospectus_registry_query':
        # 查询备案索引
        return {'status': 'ok', 'results': query_registry(stock_code=stock, market=market)}
    elif dim == 'cross_market_scan':
        scanner = CrossMarketScanner(stock, market, data_dir)
        scanner.load_data()
        return scanner.scan()
    elif dim == 'legal_risk':
        # qcc 权威法律/合规风险（消费 data/mcp 下已回填的 qcc 结果）
        from scripts.qcc_dimensions import build_legal_risk
        cross = results.get('findings', {}).get('cross_validation')
        return build_legal_risk(data_dir, findings={'cross_validation': cross} if cross else {})
    elif dim == 'intellectual_property':
        from scripts.qcc_dimensions import build_intellectual_property
        return build_intellectual_property(data_dir)
    return {}


def infer_source_from_dim(dim: str, result) -> str | None:
    """
    智能推断数据来源。
    规则：按数据源已知模式推断（大多数脚本没有 _meta.source）。
    返回 None 表示无法推断（走兜底 'unknown'）。
    """
    if isinstance(result, dict):
        meta = result.get('_meta', {})
        src = meta.get('source') or result.get('source')
        if src:
            return src

    dim_source_map = {
        'announcements': 'em_announce',
        'executives': 'em_announce',
        'capital': 'em_announce',
        'related': 'em_announce',
        'regulatory': 'em_announce',
        'structure': 'em_announce',
        'subsidiary': 'em_announce',
        'industry': 'csrc_ak',
        'peer_compare': 'csrc_ak',
        'rd_analysis': 'em_api',
        'governance': 'cninfo_api',
        'share_history': 'cninfo_api',
        'institutional': 'em_api',
        'earnings_forecast': 'em_api',
        'investor_qa': 'szse',
        'risk': 'composite',
        'websearch': 'manual',
        'annual_pdf': 'cninfo_pdf',
        'multi_year_trend': 'em_api',
        'valuation': 'em_api',
        'periodic_reports': 'cninfo_pdf',
        'hk_financial': 'akshare_hk_fin',
        'cross_validation': 'em_api',
        'strategic_opportunity': 'annual_pdf',
        'value_chain': 'local_data',
        'ma_deep': 'local_data',
        'strategic_narrative': 'local_data',
        'competition_map': 'local_data',
        'enhanced_company_info': 'local_data',
        'cross_market_scan': 'local_data',
    }
    return dim_source_map.get(dim)


def run_peer_compare(stock: str, data_dir: str, args) -> dict:
    """同业对比维度：调用 PeerComparator"""
    try:
        comp = PeerComparator()
        data = comp.compare(stock)
        md = comp.format_markdown(data) if data else ''
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


def get_company_name(stock: str) -> str:
    """获取公司名称 — 多数据源降级"""
    try:
        prefix = 'SZ' if stock[:2] in ['00', '30'] else 'SH'
        secucode = f"{stock}.{prefix}"
        from scripts.valuation import _fetch_valuation_data
        val = _fetch_valuation_data(secucode)
        if val and val.get('SECURITY_NAME_ABBR'):
            return val['SECURITY_NAME_ABBR']
    except Exception as _sexc:
        record(__name__, 'get_company_name', _sexc, note='静默降级')
        pass
    try:
        import requests
        mid = '0' if stock[:2] in ['00', '30'] else '1'
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {'secid': f'{mid}.{stock}', 'fields': 'f58', 'ut': 'fa1fd612f2f5e7b0'}
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json().get('data', {})
        name = data.get('f58', '')
        if name:
            return name
    except Exception as _sexc:
        record(__name__, 'get_company_name', _sexc, note='静默降级')
        pass
    return ''


def fetch_websearch(stock: str, data_dir: str) -> dict:
    """联网搜索维度（目前主要是年报PDF搜索）"""
    company_name = get_company_name(stock)
    try:
        reports = get_annual_report_list(stock, company_name, years=3)
    except Exception as e:
        logger.warning("get_annual_report_list failed: %s", e)
        reports = []
    return {'count': len(reports), 'reports': reports, 'company_name': company_name}


def fetch_annual_pdf(stock: str, data_dir: str, args) -> dict:
    """年报PDF下载与提取"""
    company_name = get_company_name(stock)
    try:
        result = download_and_extract(stock, company_name, data_dir)
    except Exception as e:
        logger.warning("download_and_extract failed: %s", e)
        result = {'error': str(e)}

    if result and not result.get('error'):
        text_path = os.path.join(data_dir, 'annual_report_text.txt')
        full_text = result.get('full_text', '')
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(full_text if full_text else result.get('text_preview', ''))
        sections = result.get('sections', {})
        if sections:
            sections_path = os.path.join(data_dir, 'annual_report_sections.json')
            with open(sections_path, 'w', encoding='utf-8') as f:
                json.dump(sections, f, ensure_ascii=False, indent=2)
    return result


def fetch_periodic_reports(stock: str, data_dir: str, args) -> dict:
    """定期报告（年报+半年报+季报）PDF下载与提取"""
    from scripts.pdf_download import download_and_extract_periodic, REPORT_CATEGORIES

    company_name = get_company_name(stock)
    report_type = getattr(args, 'report_type', 'all') or 'all'
    years = getattr(args, 'report_years', 1) or 1

    try:
        result = download_and_extract_periodic(
            stock, company_name, save_dir=data_dir,
            report_type=report_type, years=years
        )
    except Exception as e:
        logger.warning("download_and_extract_periodic failed: %s", e)
        result = {'error': str(e)}

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
