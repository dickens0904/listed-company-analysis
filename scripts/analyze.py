# -*- coding: utf-8 -*-
"""
统一分析入口 v2：正确执行顺序，PDF下载前置，通达信数据前置于步骤0
用法: python analyze.py 301399 [--market a] [--output <dir>]
"""
import sys, os, json, argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, SKILL_DIR)

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def run_analysis(stock_code, market='a', output_dir=None):
    date = datetime.now().strftime('%Y%m%d')
    orig_market = market  # 保留真实市场（北交所 bse），用于 results.json 标记
    if market == 'bse':
        # 北交所复用 A 股全部采集逻辑（行情/财务/公告/年报/三表/战略机遇），
        # 子函数按 .BJ 代码自动识别北交所，与现有"伪装 a"行为零回归。
        market = 'a'
    if output_dir is None:
        output_dir = os.path.join(SKILL_DIR, 'output', f'{stock_code}_{date}')
    os.makedirs(output_dir, exist_ok=True)
    data_dir = os.path.join(output_dir, 'data')
    os.makedirs(data_dir, exist_ok=True)

    print(f'=== {stock_code} 全维度分析 [{orig_market.upper()}] ===')
    print(f'输出目录: {output_dir}')
    print()

    findings = {}
    pdf_path = None  # 年报PDF路径，后续模块共用
    tdx_data = {}    # 通达信增强数据

    # ─── 0. 通达信数据预获取（前置，为后续模块提供增强数据） ───
    print('[0/19] 通达信数据预获取...')
    try:
        if market == 'a':
            from tdx_provider import enhance_with_tdx_data, generate_report_section, build_evidence_for_ai
            tdx_data = enhance_with_tdx_data(stock_code)
            if tdx_data.get('success'):
                print(f'  ✅ 通达信数据已获取: {tdx_data.get("basic_enhanced", {}).get("company_name", "N/A")}')
                print(f'     产品构成: {len(tdx_data.get("product_structure", []))}个')
                print(f'     管理团队: {len(tdx_data.get("executives_enhanced", []))}人')
                print(f'     股本结构: {tdx_data.get("structure_enhanced", {}).get("latest", {}).get("date", "N/A")}')
            else:
                print(f'  ⚠️ 通达信数据获取失败: {tdx_data.get("error", "未知错误")}')
        else:
            print(f'  ⏭️ 非A股市场，跳过通达信预获取')
    except Exception as e:
        print(f'  ❌ 通达信预获取异常: {e}')
        tdx_data = {}

    # ─── 1. 实时行情 ───
    print('[1/19] 实时行情...')
    try:
        if market == 'a':
            # 优先免费数据源（腾讯财经），THSDK 降级
            try:
                from free_data_provider import tencent_quote
                q = tencent_quote([stock_code])
                if stock_code in q:
                    findings['quote'] = q[stock_code]
                    quote = findings['quote']
                    print(f"  ✅ 免费行情: {quote.get('name', '')} {quote.get('price', 0)}")
                else:
                    raise ValueError('无行情数据')
            except Exception:
                from thsdk_search import ThsdkSearch
                ts = ThsdkSearch()
                findings['quote'] = ts.quote(stock_code)
                print(f'  ✅ THSDK行情')
        elif market == 'hk':
            try:
                from free_data_provider import tencent_quote
                q = tencent_quote([stock_code])
                if stock_code in q:
                    findings['quote'] = q[stock_code]
                    quote = findings['quote']
                    print(f"  ✅ 免费行情: {quote.get('name', '')}")
                else:
                    raise ValueError('无数据')
            except Exception:
                from thsdk_search import ThsdkSearch
                ts = ThsdkSearch()
                findings['quote'] = ts.quote(stock_code)
        elif market == 'us':
            # US stocks: Use sec_xbrl_api for basic info
            from sec_xbrl_api import fetch_us_financials
            us_data = fetch_us_financials(stock_code)
            if us_data and us_data.get('success'):
                findings['quote'] = {
                    'name': us_data.get('company', stock_code),
                    'code': stock_code,
                    'market': 'us',
                    'cik': us_data.get('cik', ''),
                }
            else:
                findings['quote'] = {}
        print(f'  ✅ 行情数据已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['quote'] = {}

    # ─── 2. 财务报表 ───
    print('[2/19] 财务报表...')
    try:
        if market == 'a':
            from financials import fetch_financial_metrics
            findings['financial'] = fetch_financial_metrics(stock_code, market=market, data_dir=data_dir)
        elif market == 'hk':
            # HK stocks: Use hk_financial
            from hk_financial import fetch_hk_financial
            findings['financial'] = fetch_hk_financial(stock_code, market='hk', data_dir=data_dir)
            # 🔴 结构对齐（2026-10-21）：AKShare 港股给 indicators/valuation，没有 records，
            # 而下游统一读 financial['records'] → 港股财务报表/预测/台账全空。
            try:
                from hk_records import attach_hk_records
                attach_hk_records(findings['financial'])
                _hr = findings['financial'].get('records') or []
                print(f'  ✅ 港股 records 已对齐: {len(_hr)} 个财年'
                      f'（{_hr[0]["REPORTDATE"]} → {_hr[-1]["REPORTDATE"]}）' if _hr else
                      '  ⚠️ 港股 records 仍为空')
            except Exception as _he:
                print(f'  ⚠️ 港股 records 适配失败: {_he}')
        elif market == 'us':
            # US stocks: Use sec_xbrl_api（SEC XBRL 官方一手）
            from sec_xbrl_api import fetch_us_financials
            findings['financial'] = fetch_us_financials(stock_code)
            # 🔴 结构对齐（2026-10-21）：SEC 返回 {financials:{科目:[…]}}，下游 12 处
            # 统一读 financial['records']。不补这层 = "有数据但读不到"（实测 19.2/100）。
            try:
                from us_records import attach_records
                attach_records(findings['financial'], stock_code)
                recs = findings['financial'].get('records') or []
                print(f'  ✅ 美股 records 已对齐: {len(recs)} 个财年'
                      f'（{recs[0]["REPORTDATE"]} → {recs[-1]["REPORTDATE"]}）' if recs else
                      '  ⚠️ 美股 records 仍为空')
            except Exception as _ue:
                print(f'  ⚠️ 美股 records 适配失败: {_ue}')
        print(f'  ✅ 财务数据已获取')
        
        # 3年+最近一期财务对比分析
        try:
            from financials_multiyear import fetch_financial_multi_year, format_multi_year_summary
            findings['financial_multiyear'] = fetch_financial_multi_year(stock_code, market=market, data_dir=data_dir, years=3)
            findings['financial_multiyear_summary'] = format_multi_year_summary(findings['financial_multiyear'])
            print(f'  ✅ 3年财务对比已获取')
        except Exception as e2:
            print(f'  ⚠️ 3年对比失败: {e2}')
            findings['financial_multiyear'] = {}
            findings['financial_multiyear_summary'] = ''
    except Exception as e:
        print(f'  ❌ {e}')
        findings['financial'] = {}
        findings['financial_multiyear'] = {}
        findings['financial_multiyear_summary'] = ''

    # ─── 3. 年报PDF下载（提前，为后续模块提供PDF路径） ───
    print('[3/19] 年报PDF下载...')
    try:
        if market == 'a':
            from pdf_download import download_and_extract
            import inspect
            sig = inspect.signature(download_and_extract)
            params = list(sig.parameters.keys())
            # 🔴 2026-10-21：签名是 save_dir（不是 output_dir），旧判断恒不命中 →
            # PDF 落到技能目录 scripts/output/... 而非 --output 指定目录。
            if 'save_dir' in params:
                pdf_result = download_and_extract(stock_code, save_dir=data_dir)
            elif 'output_dir' in params:
                pdf_result = download_and_extract(stock_code, output_dir=data_dir)
            else:
                pdf_result = download_and_extract(stock_code)
            findings['annual_pdf'] = pdf_result
            pdf_path = pdf_result.get('pdf_path') or pdf_result.get('pdf')
            if pdf_path and os.path.exists(pdf_path):
                print(f'  ✅ PDF: {os.path.basename(pdf_path)}')
            else:
                print(f'  ⚠️ PDF下载成功但路径未返回')
                # 尝试从data_dir找PDF
                for f in os.listdir(data_dir):
                    if f.endswith('.pdf'):
                        pdf_path = os.path.join(data_dir, f)
                        print(f'  ✅ 找到PDF: {f}')
                        break
        elif market == 'hk':
            # 港股：优先纯 HTTP（披露易 titleSearch），Playwright 降为兜底
            # 2026-10-21：旧实现只走 Playwright，无头环境返回空 → annual_pdf 恒 {}。
            try:
                from hkex_announcements import fetch_hkex_annual_http
                _hkr = fetch_hkex_annual_http(stock_code, years=3)
            except Exception as _e:
                print(f'  ⚠️ HKEX HTTP 检索失败: {_e}')
                _hkr = []
            if _hkr:
                _rp = _hkr[0]
                _hk_pdf = os.path.join(data_dir, f'{_rp.get("year") or "latest"}_annual_report_hk.pdf')
                if not (os.path.exists(_hk_pdf) and os.path.getsize(_hk_pdf) > 100000):
                    try:
                        from hkex_announcements import download_hkex_pdf
                        download_hkex_pdf(_rp['pdf_url'], _hk_pdf)
                    except Exception as _de:
                        print(f'  ⚠️ HKEX PDF 下载失败: {_de}')
                if os.path.exists(_hk_pdf) and os.path.getsize(_hk_pdf) > 100000:
                    findings['annual_pdf'] = {
                        'pdf_path': _hk_pdf, 'year': _rp.get('year'),
                        'title': _rp.get('title'), 'pdf_url': _rp['pdf_url'],
                        '_source': 'hkex_title_search',
                    }
                    print(f'  ✅ HKEX年报PDF: {os.path.basename(_hk_pdf)} '
                          f'({os.path.getsize(_hk_pdf)//1024}KB)')
                else:
                    findings['annual_pdf'] = {
                        'pdf_url': _rp['pdf_url'], 'year': _rp.get('year'),
                        'title': _rp.get('title'), '_source': 'hkex_title_search',
                        '_note': 'PDF 下载失败，仅保留原文链接',
                    }
                    print(f'  ⚠️ HKEX年报链接已获取（PDF未落盘）')
            else:
                # 兜底：旧 Playwright 流程
                from hkex_announcements import fetch_hkex_announcements
                anns = fetch_hkex_announcements(stock_code, announcement_type='annual')
                if anns:
                    findings['annual_pdf'] = {'pdf_url': anns[0].get('pdf_url', ''), 'stock_code': stock_code}
                    print(f'  ✅ HKEX年报链接已获取（Playwright）')
                else:
                    findings['annual_pdf'] = {}
                    print(f'  ⚠️ 未找到HKEX年报')
        elif market == 'us':
            # US stocks: SEC EDGAR 10-K（2026-10-21 修复：ticker→CIK→submissions）
            from us_financial import get_us_10k_detail
            _det = get_us_10k_detail(stock_code) or {}
            if _det.get('url'):
                findings['annual_pdf'] = {
                    'pdf_url': _det['url'],
                    'ticker': stock_code,
                    'form': _det.get('form'),
                    'filing_date': _det.get('filing_date'),
                    'accession': _det.get('accession'),
                    '_source': 'sec_edgar_submissions',
                }
                print(f"  ✅ SEC 10-K: {_det.get('filing_date')} "
                      f"（{_det.get('accession')}，HTML 原文）")
            else:
                findings['annual_pdf'] = {}
                print(f'  ⚠️ 未找到SEC 10-K')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['annual_pdf'] = {}

    # ─── 4. 三表数据（优先新版annual_report_extractor，回退旧版） ───
    print('[4/21] 三表数据...')
    if market != 'a':
        print(f'  ⏭️ 非A股市场跳过')
        findings['three_statements'] = {}
    else:
        try:
            ts_data = {}
            if pdf_path:
                # 优先：新版模板化提取器（annual_report_extractor）
                try:
                    from annual_report_extractor import extract_annual_report
                    report = extract_annual_report(pdf_path)
                    if report and not report.get("error") and report["income_statement"]:
                        ts_data = {
                            "income_statement": report["income_statement"],
                            "balance_sheet": report["balance_sheet"],
                            "cash_flow": report["cash_flow"],
                            "mdaa_text": report.get("mdaa", ""),
                            "audit": report.get("audit", {}),
                            "dividend": report.get("dividend", {}),
                            "risks": report.get("risks", []),
                            "_source": "annual_report_extractor",
                        }
                        inc_len = len(report.get("income_statement", {}))
                        mdaa_len = len(report.get("mdaa", ""))
                        print(f"  ✅ 三表: {inc_len}项利润表 + {mdaa_len}字MD&A")
                except Exception as e:
                    print(f'  ⚠️ 新版提取器失败: {e}，回退旧版...')
                
                # 回退：旧版 ThreeStatementsExtractor
                if not ts_data:
                    from three_statements import ThreeStatementsExtractor
                    ts_ext = ThreeStatementsExtractor(pdf_path=pdf_path)
                    ts_data = ts_ext.extract_all()
                    ts_data["_source"] = "three_statements"
                    print(f'  ✅ 三表数据已获取（旧版）')
            else:
                ts_data = {}
                print(f'  ⏭️ 无PDF路径')
            findings['three_statements'] = ts_data
        except Exception as e:
            print(f'  ❌ {e}')
            findings['three_statements'] = {}

    # ─── 5. 战略机遇（需要PDF/MD&A数据） ───
    print('[5/21] 战略机遇...')
    if market != 'a':
        print(f'  ⏭️ 非A股市场跳过（{market.upper()}年报格式不同）')
        findings['strategic_opportunity'] = {}
    else:
        try:
            from annual_extract import AnnualReportExtractor
            import inspect
            sig = inspect.signature(AnnualReportExtractor.__init__)
            params = list(sig.parameters.keys())
            if pdf_path and 'pdf_path' in params:
                ext = AnnualReportExtractor(pdf_path=pdf_path)
            elif 'pdf_path' in params:
                findings['strategic_opportunity'] = {}
                print(f'  ⏭️ 无PDF路径，跳过')
                ext = None
            else:
                ext = AnnualReportExtractor(stock_code)

            if ext:
                annual_sections = ext.extract_all()
                mda_text = annual_sections.get('mda', {}).get('content', '')
                from strategic_opportunity import StrategicOpportunityAnalyzer
                so_analyzer = StrategicOpportunityAnalyzer(annual_sections=annual_sections, mda_text=mda_text)
                so_result = so_analyzer.analyze()
                findings['strategic_opportunity'] = so_result
                print(f'  ✅ 战略机遇已获取')
        except Exception as e:
            print(f'  ❌ {e}')
            findings['strategic_opportunity'] = {}

    # ─── 6. 公告全景 ───
    print('[6/19] 公告全景...')
    try:
        from announcements import fetch_announcements
        findings['announcements'] = fetch_announcements(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 公告已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['announcements'] = {}

    # ─── 7. 高管动态 ───
    print('[7/19] 高管动态...')
    try:
        from executives import fetch_executives
        findings['executives'] = fetch_executives(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 高管变动已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['executives'] = {}

    # 通达信高管增强：补充完整简历/薪酬/持股字段
    if tdx_data.get('success') and tdx_data.get('executives_enhanced'):
        base = findings.setdefault('executives', {})
        base['tdx_executives'] = tdx_data['executives_enhanced']
        print('  ✅ 通达信高管数据已注入')

    # ─── 8. 资金动作 ───
    print('[8/19] 资金动作...')
    try:
        from capital import fetch_capital_actions
        findings['capital'] = fetch_capital_actions(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 资金动作已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['capital'] = {}

    # ─── 9. 子公司 ───
    print('[9/19] 子公司...')
    try:
        from subsidiary import fetch_subsidiary_ipo
        findings['subsidiary'] = fetch_subsidiary_ipo(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 子公司已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['subsidiary'] = {}

    # ─── 10. 关联方 ───
    print('[10/19] 关联方...')
    try:
        from related_deals import fetch_related_deals
        findings['related'] = fetch_related_deals(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 关联方已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['related'] = {}

    # ─── 11. 监管历史 ───
    print('[11/19] 监管历史...')
    try:
        from regulatory import fetch_regulatory_history
        findings['regulatory'] = fetch_regulatory_history(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 监管历史已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['regulatory'] = {}

    # ─── 12. 股权结构 ───
    print('[12/19] 股权结构...')
    try:
        from structure import build_structure
        findings['structure'] = build_structure(stock_code, market, findings)
        print(f'  ✅ 股权结构已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['structure'] = {}

    # 通达信股本结构增强：补充总股本/流通股/限售股历史
    if tdx_data.get('success') and tdx_data.get('structure_enhanced'):
        base = findings.setdefault('structure', {})
        base['tdx_structure'] = tdx_data['structure_enhanced']
        print('  ✅ 通达信股本结构已注入')

    # ─── 13. 行业竞争 ───
    print('[13/19] 行业竞争...')
    try:
        from industry import fetch_industry
        findings['industry'] = fetch_industry(stock_code, market=market, data_dir=data_dir)
        print(f'  ✅ 行业已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['industry'] = {}

    # ─── 14. 综合风险 ───
    print('[14/19] 综合风险...')
    try:
        from risk import assess_risk
        findings['risk'] = assess_risk(findings)
        print(f'  ✅ 风险评分: {findings["risk"].get("score", "?")}/100')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['risk'] = {}

    # ─── 15. 商业模式 ───
    print('[15/19] 商业模式...')
    try:
        from business_fetch import fetch_business_intel
        findings['business_fetch'] = fetch_business_intel(
            stock_code=stock_code,
            company_name=findings.get('quote', {}).get('name', stock_code),
            market=market,
            strategic_opportunity=findings.get('strategic_opportunity')
        )
        print(f'  ✅ 商业模式已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['business_fetch'] = {}

    # ─── 16. 融资结构 ───
    print('[16/19] 融资结构...')
    try:
        from financing_structure import fetch_financing_structure
        findings['financing_structure'] = fetch_financing_structure(
            stock_code=stock_code,
            market=market,
            data_dir=data_dir,
            financial_metrics=findings.get('financial'),
            governance_data=findings.get('governance'),
            share_history_data=findings.get('share_history'),
            announcements_data=findings.get('announcements'),
        )
        print(f'  ✅ 融资结构已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['financing_structure'] = {}

    # ─── 17. 财务预测（盈利预测模型） ───
    print('[17/21] 财务预测...')
    try:
        multi_year = findings.get('financial_multiyear', {}) or findings.get('financial', {}) or {}
        industry_info = findings.get('industry', {})
        # 🔴 股本取值链（2026-10-21 修）：港美股走 A 股默认 12.5 亿股会让 EPS/目标价
        # 放大十倍以上（实测 AAPL 算出 EPS 86.58 / 目标价 1633，真值 EPS 7.49）。
        # 优先级：Wind 回填 total_shares → 财务 records 的 SHARES → 通答信 → 默认(标注)
        _shares_src = 'default_placeholder'
        total_shares = None
        _q = findings.get('quote') or {}
        if isinstance(_q.get('total_shares'), (int, float)) and _q.get('total_shares') > 0:
            total_shares = _q['total_shares'] / 1e8
            _shares_src = 'quote.total_shares(Wind)'
        if total_shares is None:
            _recs = (findings.get('financial') or {}).get('records') or []
            for _r in reversed(_recs):
                if isinstance(_r.get('SHARES'), (int, float)) and _r['SHARES'] > 0:
                    total_shares = _r['SHARES'] / 1e8
                    _shares_src = 'financial.records.SHARES'
                    break
        # ③ 市值/股价反推（东财行情普遍有这两个字段，港美股/北交所同样适用）
        if total_shares is None:
            _mc, _px = (findings.get('quote') or {}).get('mcap_yi'), (findings.get('quote') or {}).get('price')
            if isinstance(_mc, (int, float)) and isinstance(_px, (int, float)) and _px > 0 and _mc > 0:
                total_shares = _mc / _px
                _shares_src = 'quote.mcap_yi/price 反推(若含限售股会低估总股本·近似)'
        # ④ 净利/EPS 隐含股数（EPS 有四舍五入误差，标注"近似"）
        if total_shares is None:
            for _r in reversed((findings.get('financial') or {}).get('records') or []):
                _eps, _np = _r.get('BASIC_EPS'), _r.get('PARENT_NETPROFIT')
                if isinstance(_eps, (int, float)) and isinstance(_np, (int, float)) and _eps > 0:
                    total_shares = (_np / _eps) / 1e8
                    _shares_src = 'records 隐含股数(净利/EPS·近似)'
                    break
        if total_shares is None and tdx_data.get('success'):
            _ts = (tdx_data.get('structure_enhanced', {}).get('latest', {}) or {}).get('total_shares')
            if isinstance(_ts, (int, float)) and _ts > 0:
                total_shares = _ts / 1e8
                _shares_src = 'tdx'
        if total_shares is None:
            total_shares = 12.5
            _shares_src = 'default_placeholder(12.5亿股·不可用于定价)'
        print(f'  股本口径: {total_shares:.2f} 亿股（{_shares_src}）')
        # 统一取数口径（2026-10-21）：**一律以 financial.records 为准**。
        # A股/北交所（东财业绩报表）与美股（us_records 对齐）同构，预测模型只认年报；
        # 旧实现只喂 multi_year_trend，而它对北交所/港美股返空 → 恒报"0 期年报"。
        _fin2 = findings.get('financial') or {}
        raw_myt = {}
        if _fin2.get('records'):
            raw_myt = {'records': _fin2['records'],
                       'fiscal_years': (_fin2.get('_meta') or {}).get('fiscal_years') or []}
        if not raw_myt:
            try:
                from multi_year_trend import fetch_multi_year_trend as _myt
                raw_myt = _myt(stock_code, market)
            except Exception:
                raw_myt = {}
        from financial_projection import project_financials, format_projection_html
        findings['financial_projection'] = project_financials(
            stock_code, raw_myt, industry_info,
            assumptions={"total_shares": total_shares})
        ep = findings['financial_projection'].get('projection', {}).get('eps', [0,0,0])
        target = findings['financial_projection'].get('valuation', {}).get('target_price', 0)
        print(f'  ✅ 三年预测: EPS {ep[0]}/{ep[1]}/{ep[2]}, 目标价 {target}')
        # 股本占位时目标价无意义 → 置空并标注，避免文章引用失真目标价
        if _shares_src.startswith('default_placeholder'):
            _fp = findings['financial_projection']
            _fp.setdefault('warnings', []).append(
                '总股本缺失，已回落 12.5 亿股占位；EPS/目标价不可用于定价')
            _v = _fp.get('valuation')
            if isinstance(_v, dict):
                _v['target_price'] = None
            print('  🔴 股本缺失：目标价已置空（禁止引用）')
        # 估值锚口径提示（2026-10-21）：目标价沿用 A 股 PE 锚，高 PE 标的必然出现
        # "目标价远低于现价"，这不是算错，是锚不适用 → 显式标注，禁止当结论引用。
        _pe_now = (findings.get('quote') or {}).get('pe_ttm')
        _px_now = (findings.get('quote') or {}).get('price')
        if isinstance(_pe_now, (int, float)) and _pe_now > 60:
            _fp2 = findings['financial_projection']
            _v2 = _fp2.get('valuation')
            if isinstance(_v2, dict) and _v2.get('target_price'):
                _v2['target_price_note'] = (
                    f'目标价按 A 股 PE 锚（约 19x）测算；当前 PE(TTM) {_pe_now:.0f}x 显著高于锚，'
                    f'目标价不具参考性（现价 {_px_now}），仅供模型完整性展示')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['financial_projection'] = {}

    # ─── 18. 同业估值对比 ───
    print('[18/21] 同业估值对比...')
    try:
        ind_name = findings.get('industry', {}).get('industry_name', '')
        from peer_valuation import get_peer_comparison, get_industry_valuation
        findings['peer_valuation'] = get_peer_comparison(stock_code, ind_name)
        findings['industry_ranking'] = get_industry_valuation(stock_code)
        peers = findings['peer_valuation'].get('count', 0)
        pe_rank = findings['industry_ranking'].get('pe_percentile', 'N/A')
        if findings['peer_valuation'].get('skipped'):
            print(f"  ⏭️ 同业估值不适用：{findings['peer_valuation'].get('reason')}")
        elif findings['peer_valuation'].get('coverage') == 'only_self':
            print(f"  ⚠️ 同业对比：未匹配同业名单，仅本公司（不得表述为'同业 1 家'）")
            # 2026-10-22 补：PEER_MAP 只写死了「白酒」一个行业，其余必然落到这里。
            #   若此前跑过 peer_discovery（年报点名名单已由 Agent 判定落盘），则挂上去。
            #   🔴 不在自动流程里启用 --auto 规则版——它未经语义审核，只配当线索。
            try:
                import peer_discovery
                _od = peer_discovery._out_dir_for(stock_code, discover=True)
                _llm = os.path.join(_od, 'peers_llm.json')
                if os.path.exists(_llm):
                    _pd = peer_discovery.build_peer_table(stock_code, _llm, _od)
                    if _pd.get('ok'):
                        findings['peer_discovery'] = _pd
                        print(f"     → 年报点名对手 {_pd['counts']['competitor']} 家，"
                              f"已解析代码 {_pd['counts']['resolved']} 家"
                              f"{'（其余待 Wind 补估值）' if _pd.get('quote_plan') else ''}")
                    else:
                        print(f'     （同行发现契约未通过：{_pd.get("errors", [""])[0]}）')
            except Exception as _e:
                print(f'     （peer_discovery 未生效：{type(_e).__name__}）')
        else:
            print(f'  ✅ 同业对比: {peers}家公司, PE分位 {pe_rank}%')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['peer_valuation'] = {}
        findings['industry_ranking'] = {}

    # ─── 19. SOTP分部估值（需要全部findings） ───
    print('[19/21] SOTP分部估值...')
    try:
        from sotp_valuation import calculate_sotp
        # calculate_sotp needs analysis_data with 'findings' key
        temp_results = {'findings': findings}
        findings['valuation'] = calculate_sotp(temp_results, stock_code, market=market)
        _v = findings['valuation']
        if _v.get('skipped'):
            print(f"  ⏭️ SOTP 不适用：{_v.get('reason')}")
        elif _v.get('note'):
            print(f"  ⏭️ SOTP 不成立：{_v.get('note')}")
        else:
            sotp_total = _v.get('sotp_total') or 0
            discount = _v.get('discount') or 0
            print(f'  ✅ SOTP估值: {sotp_total:.1f}亿, 折价{discount:.1f}%')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['valuation'] = {}

    # ─── 20. 投资逻辑（需要全部findings） ───
    print('[20/21] 投资逻辑...')
    try:
        from investment_thesis import generate_investment_thesis
        temp_results = {'findings': findings}
        findings['investment_thesis'] = generate_investment_thesis(temp_results, stock_code, market=market)
        rating = findings['investment_thesis'].get('investment_rating', '?')
        print(f'  ✅ 投资评级: {rating}')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['investment_thesis'] = {}

    # ─── 21. 产品与产线基地介绍 ───
    print('[21/21] 产品与产线基地介绍...')
    try:
        from product_line_intro import fetch_product_line_intro
        findings['product_line_intro'] = fetch_product_line_intro(
            stock_code=stock_code,
            market=market,
            company_name=findings.get('quote', {}).get('name', stock_code),
            main_business=tdx_data.get('basic_enhanced', {}).get('main_business', '') if tdx_data.get('success') else '',
            announcements=findings.get('announcements', {}).get('timeline', []),
            pdf_path=pdf_path,
            tdx_data=tdx_data if tdx_data.get('success') else None,
        )
        print(f'  ✅ 产品与产线基地已获取')
    except Exception as e:
        print(f'  ❌ {e}')
        findings['product_line_intro'] = {}

    # ─── 22. 原文深挖：年报附注（关联交易/商誉/诉讼/担保）+ 美股 SEC 事件申报 ───
    # 港美股没有东财 F10，这些维度原本全空；改为从已下载的年报原文里抽，
    # 美股另补 8-K（重大事项）/ DEF 14A（高管）申报清单。
    print('[22/23] 原文深挖（年报附注 / SEC 申报）...')
    try:
        if market == 'us':
            from us_filings import fetch_us_event_filings
            _ev = fetch_us_event_filings(stock_code, years=3)
            if isinstance(_ev, dict) and not _ev.get('error'):
                _cnt = {}
                for _dim, _b in _ev.items():
                    if not isinstance(_b, dict) or 'records' not in _b:
                        continue
                    _base = findings.get(_dim)
                    if not isinstance(_base, dict):
                        _base = {}
                    _base['sec_filings'] = _b
                    if _dim == 'capital' and not _base.get('actions'):
                        _base['actions'] = _b['records']
                        _base['count'] = _b['count']
                        _base['_source'] = 'sec_edgar_8k'
                    if _dim == 'executives' and not _base.get('changes'):
                        _base['changes'] = [{'date': x.get('date'), 'title': x.get('desc'),
                                             'type': x.get('form'), 'url': x.get('url')}
                                            for x in _b['records']]
                        _base['_source'] = 'sec_edgar_def14a'
                    findings[_dim] = _base
                    _cnt[_b.get('label') or _dim] = _b.get('count')
                if _cnt:
                    print('  ✅ SEC 申报: ' + ' / '.join(f'{k} {v} 条' for k, v in _cnt.items()))
            elif isinstance(_ev, dict) and _ev.get('error'):
                print(f"  ⚠️ SEC 申报: {_ev['error']}")
        from note_extractor import extract_notes_into
        _st = extract_notes_into(findings, data_dir)
        _hit = {k: v for k, v in (_st or {}).items() if v}
        print(f"  ✅ 年报附注: {_hit if _hit else '无命中（原文可能为扫描件/无相关章节）'}")
    except Exception as e:
        print(f'  ❌ 原文深挖失败: {e}')

    # ─── 23. MCP 计划生成 + 回填合并（Wind 主力源生效点） ───
    # 计划：按市场取 MARKET_DIMS（a/bse 9维；hk/us 走 hk_*/us_* 专属维度），
    #       落 data/mcp_plan.json，Agent 据此调 Wind/dzh/qcc 并 save_mcp_result 回填。
    # 合并：若 data/mcp_data/ 已有回填，把 Wind 行情/估值/K线/财务 + dzh 港美三表
    #       合并进 findings（原生数据保留在 _native，缺失时才升主）。
    print('[23/23] MCP 计划与回填合并...')
    try:
        from mcp_bridge import (build_mcp_plan, write_mcp_plan,
                                apply_backfill, format_backfill_report)
        from data_source_registry import MARKET_DIMS
        _dims = MARKET_DIMS.get(orig_market, MARKET_DIMS['a'])
        _plan = build_mcp_plan(stock_code, orig_market, _dims,
                               company_name=findings.get('quote', {}).get('name'))
        _plan_path = write_mcp_plan(data_dir, _plan)
        print(f'  ✅ MCP 计划: {len(_plan["calls"])} 个调用 → {os.path.basename(_plan_path)}')
        _rep = apply_backfill(findings, data_dir, orig_market)
        _msg = format_backfill_report(_rep)
        if _msg:
            print('  ' + _msg.replace('\n', '\n  '))
        else:
            print('  ⏭️ 暂无回填数据（Agent 按 mcp_plan.json 调 MCP 后回填，再跑 --apply）')
    except Exception as e:
        print(f'  ❌ {e}')

    # ─── 22.5 财务红旗扫描（纯本地，不依赖 MCP）───
    try:
        from redflag import scan_redflags
        _recs = (findings.get('financial') or {}).get('records') or []
        if _recs:
            _rf = scan_redflags(_recs, {'market': orig_market})
            findings['redflags'] = _rf
            print(f"[22.5/23] 财务红旗扫描：{_rf['count']} 条"
                  f"（扫描 {_rf['scanned_periods']} 期"
                  + (f"，{len(_rf['data_gaps'])} 项数据缺口已标注" if _rf['data_gaps'] else '')
                  + "）")
        else:
            print('[22.5/23] 财务红旗扫描：无 records，跳过')
    except Exception as e:
        print(f'  ❌ 红旗扫描失败: {e}')

    # ─── 保存中间数据 ───
    results = {
        'stock': stock_code,
        'market': orig_market,  # 标记真实市场（北交所 = bse），内部采集已归一化为 a
        'date': date,
        'dims': list(findings.keys()),
        'findings': findings,
    }
    results_path = os.path.join(data_dir, 'results.json')
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f'\n中间数据: {results_path}')

    # ─── AI数据增强 ───
    try:
        from ai_data_enricher import enrich_data
        results = enrich_data(results, output_dir, max_ann_fulltext=20)
    except Exception as e:
        print(f'⚠️ AI数据增强失败: {e}')

    # ─── 压缩素材包 ───
    try:
        from data_compressor import compress_to_file
        pack_path = compress_to_file(results, os.path.join(output_dir, 'data', 'material_pack.json'))
    except Exception as e:
        print(f'⚠️ 数据压缩失败: {e}')
        pack_path = None

    # ─── AI生成报告 ───
    report_path = None
    if pack_path:
        try:
            from ai_report_generator import generate_report as ai_generate_report
            with open(pack_path, 'r', encoding='utf-8') as f:
                material_pack = json.load(f)
            report_path = ai_generate_report(material_pack, output_dir)
            if report_path:
                print(f'✅ AI报告: {report_path}')
        except Exception as e:
            print(f'⚠️ AI报告生成失败: {e}')
            import traceback
            traceback.print_exc()

    # ─── 备选：Python拼接报告 ───
    if not report_path:
        print('  降级使用Python拼接报告...')
        try:
            from report import generate_report
            report_path = generate_report(results, output_dir)
            print(f'✅ 报告: {report_path}')
        except Exception as e:
            print(f'❌ 报告生成失败: {e}')

    # ─── 生成HTML报告并自动打开 ───
    try:
        from report_html import generate_html_report
        html_path = generate_html_report(results, output_dir)
        print(f'✅ HTML报告: {html_path}')
        import webbrowser
        webbrowser.open('file://' + os.path.abspath(html_path))
    except Exception as e:
        print(f'⚠️ HTML报告生成失败: {e}')

    return report_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='上市公司全维度分析')
    parser.add_argument('stock', help='股票代码')
    parser.add_argument('--market', '-m', default='a', choices=['a', 'hk', 'us', 'bse'])
    parser.add_argument('--output', '-o', help='输出目录')
    args = parser.parse_args()
    run_analysis(args.stock, args.market, args.output)
