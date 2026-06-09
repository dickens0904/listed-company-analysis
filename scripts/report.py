# -*- coding: utf-8 -*-
"""
报告生成模块（模块化调度版）
生成结构化Markdown分析报告（中文）

每个维度的报告生成函数由对应模块提供 generate_report_section(data) -> List[str]
本模块仅负责：汇总调度、章节编号、特殊章节处理
"""
import sys, json, os, re, importlib
import os as _os

_scripts_dir = _os.path.dirname(_os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

_SOURCE_LABELS_DISPLAY = {
    'em_api': '🌐 东方财富API',
    'em_announce': '🌐 东方财富公告API',
    'cninfo_api': '🌐 巨潮资讯API',
    'cninfo_hk_announce': '🌐 巨潮资讯港股公告',
    'csrc': '🌐 证监会辅导数据',
    'csrc_ak': '🌐 证监会辅导数据(AKShare)',
    'akshare': '🌐 AKShare封装',
    'akshare_hk_fin': '🌐 AKShare港股财务',
    'cninfo_pdf': '📄 巨潮资讯PDF',
    'sse': '📄 上交所官网',
    'szse': '📄 深交所官网',
    'bse_cn': '📄 北交所官网',
    'hkex_pw': '🌐 港交所披露易(Playwright)',
    'hkex': '🌐 港交所披露易',
    'sec_edgar': '🌐 SEC EDGAR',
    'yfinance': '🌐 Yahoo Finance',
    'annual_pdf_text': '📄 年报PDF文本提取',
    'local_pdf': '📁 本地PDF',
    'local_cache': '💾 本地缓存',
    'manual': '✍️ 手动输入',
    'all_failed': '❌ 全部失败',
    'unknown': '❓ 未知来源',
}

_MODULE_MAP = {
    'announcements': 'scripts.announcements',
    'financial': 'scripts.financials',
    'hk_financial': 'scripts.hk_financial',
    'hkex_announcements': 'scripts.hkex_announcements',
    'executives': 'scripts.executives',
    'capital': 'scripts.capital',
    'financing_structure': 'scripts.financing_structure',
    'subsidiary': 'scripts.subsidiary',
    'related': 'scripts.related_deals',
    'regulatory': 'scripts.regulatory',
    'structure': 'scripts.structure',
    'industry': 'scripts.industry',
    'multi_year_trend': 'scripts.multi_year_trend',
    'valuation': 'scripts.valuation',
    'governance': 'scripts.governance',
    'share_history': 'scripts.share_history',
    'institutional': 'scripts.institutional',
    'institutional_visit': 'scripts.institutional_visit',
    'seasoned_offerings': 'scripts.seasoned_offerings',
    'shareholders_meeting': 'scripts.shareholders_meeting',
    'investor_qa': 'scripts.investor_qa',
    'peer_compare': 'scripts.peer_compare',
    'rd_analysis': 'scripts.rd_analysis',
    'risk': 'scripts.risk',
    'cross_validation': 'scripts.cross_validator',
    'enhanced_company_info': 'scripts.enhanced_company_info_extractor',
    'cross_market_scan': 'scripts.cross_market_scanner',
    'value_chain': 'scripts.value_chain_analysis',
    'ma_deep': 'scripts.ma_deep_analysis',
    'strategic_narrative': 'scripts.strategic_narrative',
    'competition_map': 'scripts.competition_map',
    'tdx': 'scripts.tdx_provider',
    'product_line_intro': 'scripts.product_line_intro',
}

_module_cache = {}


def _call_module_section(dim, data, **kwargs):
    module_path = _MODULE_MAP.get(dim)
    if not module_path:
        return []
    try:
        if module_path not in _module_cache:
            _module_cache[module_path] = importlib.import_module(module_path)
        mod = _module_cache[module_path]
        return mod.generate_report_section(data, **kwargs)
    except TypeError:
        try:
            return mod.generate_report_section(data)
        except Exception as e:
            return [f"\n⚠️ 模块 {module_path} 报告生成失败: {e}\n"]
    except Exception as e:
        return [f"\n⚠️ 模块 {module_path} 报告生成失败: {e}\n"]


def _section_data_sources(traces):
    lines = []
    lines.append("## 📋 数据来源溯源表")
    lines.append("")
    lines.append("| 数据维度 | 数据来源 | 状态 | 备注 |")
    lines.append("|----------|----------|------|------|")
    for t in traces:
        icon = '✅' if t['status'] == 'OK' else '❌'
        src = t.get('source', 'unknown')
        src_label = _SOURCE_LABELS_DISPLAY.get(src, src)
        pdf_note = ''
        if t.get('pdf_source') and t['pdf_source'] not in ('all_failed', 'unknown'):
            pdf_note = f"(PDF: {_SOURCE_LABELS_DISPLAY.get(t['pdf_source'], t['pdf_source'])})"
        msg = t.get('msg', '')
        if len(msg) > 60:
            msg = msg[:57] + '...'
        lines.append(f"| {t['dim_label']} | {src_label} {pdf_note} | {icon} | {msg} |")
    lines.append("")
    failed = [t for t in traces if t['status'] == 'FAIL']
    if failed:
        lines.append(f"⚠️ **有 {len(failed)} 个数据维度获取失败**，可能影响分析完整性。\n")
        for t in failed:
            lines.append(f"- **{t['dim_label']}**（{t['source_label']}）: {t.get('msg', '')}")
        lines.append("")
    return lines


def _section_executive_summary(stock, findings):
    lines = []
    lines.append("## 一、执行摘要")
    lines.append("")
    lines.append(f"**股票代码**: {stock}")
    lines.append("")

    risk = findings.get('risk', {})
    if risk:
        lines.append(f"**综合风险等级**: {risk.get('level', '未知')}（{risk.get('score', 0)}/100）")
        lines.append("")

    high_risk = risk.get('summary', {}).get('high_risk', [])
    if high_risk:
        lines.append("**⚠️ 高风险信号**:")
        for s in high_risk[:5]:
            lines.append(f"- [{s['dim']}] {s['detail']}")
        lines.append("")

    sub = findings.get('subsidiary', {})
    if sub.get('subsidiaries'):
        subs = sub['subsidiaries']
        lines.append(f"**子公司分拆/IPO**: {len(subs)}项筹划中")
        for s in subs[:3]:
            lines.append(f"- {s.get('date','')} {s.get('sub_company','子公司')} → {s.get('target_board','未知板块')}")
        lines.append("")

    fin = findings.get('financial', {})
    if fin.get('audit_opinion'):
        lines.append(f"**审计意见**: {fin['audit_opinion']}")
        if fin.get('key_risks'):
            for r in fin['key_risks'][:3]:
                lines.append(f"- {r}")
        lines.append("")

    peer = findings.get('peer_compare', {})
    if peer.get('has_data') and peer.get('peer_count', 0) > 0:
        conc = peer.get('conclusion', '')
        if conc:
            lines.append(f"**同业对比亮点**: {conc}")
        target = peer.get('target', {})
        stats = peer.get('stats', {})
        advantages = []
        for key, label in (('roe', 'ROE'), ('gross_margin', '毛利率'), ('revenue_growth', '营收增速')):
            tv = target.get(key)
            mv = stats.get(key, {}).get('mean')
            if tv is not None and mv and mv > 0 and tv > mv * 1.5:
                ratio = tv / mv
                if ratio >= 3:
                    advantages.append(f"{label}(均值{int(ratio)}倍)")
                elif ratio >= 2:
                    advantages.append(f"{label}(均值{ratio:.1f}x)")
                else:
                    advantages.append(f"{label}(超越均值{int((tv-mv)/mv*100)}%)")
        if advantages:
            lines.append(f"  核心优势: {', '.join(advantages)}")
        lines.append("")

    ann_ai = findings.get('ai_analysis', {}).get('announcements', {})
    if ann_ai.get('key_insights'):
        lines.append("**📢 公告核心洞察**:")
        for insight in ann_ai['key_insights'][:5]:
            lines.append(f"- {insight}")
        lines.append("")

    return lines


def _section_strategy(stock, findings):
    lines = []
    lines.append("## 二十一、战略意图综合分析")
    lines.append("")
    lines.append(f"**股票**: {stock}")
    lines.append("")
    lines.append("**逻辑推断**（基于已确认事实）:")
    lines.append("")
    lines.append("> 本节基于已确认的公告信息进行逻辑推断，不代表确定结论。")
    lines.append("")

    subs = findings.get('subsidiary', {}).get('subsidiaries', [])
    related = findings.get('related', {}).get('deals', [])
    go_private = findings.get('related', {}).get('go_private', [])
    fin_risks = findings.get('financial', {}).get('key_risks', [])

    if subs:
        lines.append("**1. 子公司IPO动向**:")
        for s in subs:
            lines.append(f"   - {s.get('date','')}: {s.get('title','')[:80]}")
        lines.append("")

    if go_private:
        lines.append("**2. 关联方私有化/收购**:")
        for gp in go_private:
            lines.append(f"   - {gp.get('date','')}: {gp.get('title','')[:80]}")
            if gp.get('offeror'):
                lines.append(f"     - 收购方: {gp['offeror']}")
        lines.append("")

    if fin_risks:
        lines.append("**3. 财务压力信号**:")
        for r in fin_risks:
            lines.append(f"   - {r}")
        lines.append("")

    lines.append("**综合推断**（谨慎结论）:")
    lines.append("")
    lines.append("> 基于上述发现，上市公司的资本运作呈现以下特征:")
    
    insights = []
    if subs:
        insights.append(f"**分拆上市进程活跃**：近12个月{len(subs)}项子公司分拆/IPO公告，显示上市公司正在推进资产分拆和独立融资。")
    if go_private:
        insights.append(f"**关联方整合加速**：港股私有化/关联收购动作频繁，可能是在为整体上市或资产注入扫清障碍。")
    if fin_risks:
        risk_text = "; ".join(fin_risks[:2])
        insights.append(f"**财务压力显现**：{risk_text}，这可能是资本运作频繁的直接动因。")
    
    reg_records = findings.get('regulatory', {}).get('records', [])
    exec_changes = findings.get('executives', {}).get('changes', [])
    if reg_records:
        severe = [r for r in reg_records if '警示' in r.get('severity', '') or '处罚' in r.get('severity', '')]
        if severe:
            insights.append(f"**监管风险需关注**：近12个月有{len(severe)}项监管处罚/警示，合规风险上升。")
    if len(exec_changes) > 3:
        insights.append(f"**高管层不稳定**：近12个月{len(exec_changes)}次高管变动，需关注管理层稳定性。")
    
    if len(insights) < 3:
        if not subs and not go_private:
            insights.append("**资本运作相对沉寂**：近12个月未见重大分拆、私有化等资本运作公告，可能处于战略调整期。")
        if not fin_risks:
            insights.append("**财务状况平稳**：未发现明显财务风险信号，基本面相对健康。")
    
    for i, insight in enumerate(insights[:5], 1):
        lines.append(f"> {i}. {insight}")
    
    lines.append("")
    lines.append("**风险提示**: 上述推断基于公开公告的逻辑推演，存在不确定性。建议结合：")
    lines.append("- 原始公告全文细节")
    lines.append("- 行业景气周期判断")
    lines.append("- 管理层访谈或投资者交流记录")
    lines.append("")

    return lines


def _section_quote(data):
    lines = []
    lines.append("## 三、实时行情")
    lines.append("")

    items = data if isinstance(data, list) else [data]
    if not items or (isinstance(data, dict) and not data):
        lines.append("*暂无行情数据*")
        lines.append("")
        return lines

    trading = sum(1 for it in items if it.get('status') in ('trading', 'success'))
    lines.append(f"**{len(items)}只股票** | {trading}只交易中\n")

    rows = []
    for it in items:
        code = it.get('code') or it.get('stock_code') or '?'
        name = it.get('name', '?')
        market_map = {'sh': '沪市', 'sz': '深市', 'hk': '港股', 'bse': '北交所', 'bj': '北交所', 'us': '美股', 'a': 'A股', 'A': 'A股'}
        market_label = market_map.get(it.get('market', ''), it.get('market', ''))
        price = it.get('current_price') or it.get('price') or '?'
        chg_raw = it.get('change') or it.get('chg') or '?'
        pct_raw = it.get('change_percent') or it.get('pct') or '?'
        try:
            chg_str = f'{float(chg_raw):+.2f}'
        except (ValueError, TypeError):
            chg_str = str(chg_raw) if chg_raw not in ('?', None, '') else '?'
        try:
            pct_str = f'{float(pct_raw):+.2f}%'
        except (ValueError, TypeError):
            pct_str = f'{pct_raw}%' if pct_raw and str(pct_raw) != '?' else '?'
        vol = it.get('volume') or it.get('vol_hands') or '?'
        time_str = it.get('time') or it.get('datetime') or ''
        status = it.get('status', '')
        emoji = {'trading': '✅', 'success': '✅', 'suspended': '💤', 'not_found': '❓'}.get(status, '❓')
        rows.append([emoji, code, name, market_label, price, chg_str, pct_str, vol, time_str])

    if rows:
        header = ['状态', '代码', '名称', '市场', '现价', '涨跌', '涨跌幅', '成交量', '时间']
        lines.append('| ' + ' | '.join(header) + ' |')
        lines.append('|' + '|'.join(['---'] * len(header)) + '|')
        for r in rows:
            lines.append('| ' + ' | '.join(str(v) for v in r) + ' |')
        lines.append("")

    for it in items:
        status = it.get('status', '')
        if status in ('suspended', 'not_found', 'error'):
            code = it.get('code') or it.get('stock_code') or '?'
            name = it.get('name') or ''
            notes = {
                'suspended': f'{name}({code})停牌中',
                'not_found': f'{name}({code})未找到实时数据',
                'error': f'{name}({code})查询失败: {it.get("message", "")}'
            }
            lines.append(f"- {notes.get(status, status)}")
    if any(it.get('status') in ('suspended', 'not_found', 'error') for it in items):
        lines.append("")
    return lines


def _section_annual_pdf(data):
    lines = []
    lines.append("## 二十五、年报PDF分析")
    lines.append("")
    
    if not data or data.get('error'):
        lines.append("**状态**: ❌ 获取失败")
        if data and data.get('error'):
            lines.append(f"- 错误: {data['error']}")
        lines.append("")
        return lines
    
    lines.append(f"**年报年份**: {data.get('year', '未知')}")
    lines.append(f"**标题**: {data.get('title', '未知')}")
    lines.append(f"**页数**: {data.get('page_count', 0)}页")
    pdf_path = data.get('pdf_path', '')
    if pdf_path:
        lines.append(f"**PDF路径**: `{pdf_path}`")
    lines.append("")
    
    toc = data.get('toc', [])
    if toc:
        lines.append("**主要章节**（前20项）:")
        for item in toc[:20]:
            indent = "  " * (item.get('level', 1) - 1)
            lines.append(f"{indent}- {item.get('title', '')} (p.{item.get('page', '')})")
        lines.append("")
    
    sections = data.get('sections', {})
    if sections and isinstance(sections, dict):
        ANNUAL_EXTRACT_KEYS = {
            'audit','dividend','top5_customers','top5_suppliers','actual_controller',
            'top10_shareholders','contingent','post_events','litigation','litigation_detail',
            'rd_spending','production_sales','capacity','subsidiaries','guarantee',
            'cip','goodwill','lt_equity','gov_subsidy','new_subsidiaries','auditor_change',
            'related_party',
        }
        is_new_format = any(k in ANNUAL_EXTRACT_KEYS for k in sections.keys())
        
        if is_new_format:
            lines.append("**📑 年报关键章节内容**（共{:d}章节）：\n".format(len(sections)))
            for key in sections:
                sdata = sections[key]
                name = sdata.get('name', key)
                desc = sdata.get('description', '')
                content = sdata.get('content', '')
                if not content or content.startswith('[未找到') or content.startswith('[无'):
                    continue
                lines.append(f"### {name}")
                if desc:
                    lines.append(f"_{desc}_  ")
                if len(content) > 3000:
                    lines.append(content[:3000] + "\n_...[内容截断]..._\n")
                else:
                    lines.append(content)
                lines.append("")
        else:
            lines.append("**关键章节摘要**:")
            for key in ['management_discussion','risk_factors','financial_highlights','shareholders','important_matters']:
                if not sections.get(key):
                    continue
                label_map = {
                    'management_discussion': '管理层讨论与分析',
                    'risk_factors': '风险因素',
                    'financial_highlights': '财务数据摘要',
                    'shareholders': '股东情况',
                    'important_matters': '重要事项',
                }
                content = sections[key]
                if len(content) > 2000:
                    content = content[:2000] + "\n_...[截断]..._\n"
                lines.append(f"### {label_map.get(key, key)}")
                lines.append(f"```\n{content}\n```\n")
    
    return lines


def _section_unknown(findings):
    lines = []
    lines.append("## 二十六、信息缺失清单")
    lines.append("")
    lines.append("以下信息本次分析未能获取，建议手动补充:")
    lines.append("")
    lines.append("- [ ] 年报PDF全文（财务数据）")
    lines.append("- [ ] 重大仲裁/诉讼案的具体金额和进展")
    lines.append("- [ ] 高管辞职的真实原因")
    lines.append("- [ ] 子公司IPO辅导报告全文")
    lines.append("- [ ] 港股私有化要约的具体条款（收购价格、条件）")
    lines.append("- [ ] 问询函的详细内容")
    lines.append("- [ ] 独董核查意见全文")
    lines.append("")
    return lines


def generate_report(results, out_dir):
    """生成完整分析报告"""
    stock = results['stock']
    market = results['market']
    market_name = {'a': 'A股', 'hk': '港股', 'us': '美股'}.get(market, 'A股')
    findings = results['findings']
    date = results['date']

    lines = []
    lines.append(f"# {stock} {market_name} 全景分析报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    lines.append(f"**股票代码**: {stock}  ")
    lines.append(f"**分析维度**: {', '.join(results['dims'])}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    if results.get('_traces'):
        lines += _section_data_sources(results['_traces'])

    lines += _section_executive_summary(stock, findings)

    tdx_data = findings.get('tdx', {})
    if tdx_data.get('success'):
        try:
            from scripts.tdx_provider import generate_report_section
            lines += generate_report_section(tdx_data)
        except Exception as e:
            lines.append(f"\n⚠️ 通达信章节生成失败: {e}\n")

    pli_data = findings.get('product_line_intro', {})
    if pli_data:
        try:
            from scripts.product_line_intro import generate_report_section as pli_report
            lines += pli_report(pli_data)
        except Exception as e:
            lines.append(f"\n⚠️ 产品与产线基地章节生成失败: {e}\n")

    ai = findings.get('ai_analysis', {})
    batch = {}
    for dim in ('financial', 'executives', 'capital', 'investor_qa', 'regulatory', 'governance'):
        if ai.get(dim):
            batch[dim] = ai[dim]

    for dim in results['dims']:
        if dim == 'quote':
            if 'quote' in findings:
                lines += _section_quote(findings['quote'])
            continue

        if dim == 'annual_pdf':
            if 'annual_pdf' in findings:
                lines += _section_annual_pdf(findings['annual_pdf'])
            continue

        data = findings.get(dim, {})
        if data:
            extra = {}
            if dim == 'financial' and batch.get('financial'):
                extra['batch_analysis'] = batch
                extra['multi_year_data'] = findings.get('multi_year_trend', {})
            elif dim in ('executives', 'capital', 'investor_qa', 'regulatory', 'governance'):
                if batch.get(dim):
                    extra['batch_analysis'] = batch
            lines += _call_module_section(dim, data, **extra)

    lines += _section_strategy(stock, findings)

    ai = findings.get('ai_analysis', {})
    thesis = ai.get('investment_thesis', {})
    if not thesis or not thesis.get('markdown'):
        try:
            from scripts.investment_thesis import generate_investment_thesis
            thesis = generate_investment_thesis(results, stock, market)
        except Exception as e:
            thesis = {}

    if thesis and thesis.get('markdown'):
        lines.append(thesis['markdown'])
        lines.append("")
    else:
        lines.append("## 二十二、投资逻辑")
        lines.append("")
        lines.append("投资逻辑生成失败")
        lines.append("")

    coi = ai.get('capital_operation_inference', {})
    if coi and coi.get('signals'):
        try:
            from scripts.capital_operation_inference import generate_report_section
            coi_ai = coi.get('ai_analysis')
            lines += generate_report_section(coi, ai_analysis=coi_ai)
        except Exception as e:
            pass

    # 招股书章节（仅在有数据时显示）
    prospectus_data = ai.get('prospectus', {})
    if prospectus_data and prospectus_data.get('has_prospectus'):
        try:
            from scripts.prospectus import generate_report_section as prospectus_section_fn
            lines.append("## 二十三、IPO 招股书关键信息")
            lines.append("")
            lines.append(prospectus_section_fn(prospectus_data))
            lines.append("")
        except Exception as e:
            pass

    if 'charts' in findings and findings['charts']:
        lines.append("## 二十四、可视化分析")
        lines.append("")
        from scripts.visualization import charts_to_markdown
        chart_md = charts_to_markdown(findings['charts'], out_dir)
        lines.append(chart_md)
        lines.append("")

    lines += _section_unknown(findings)

    report_text = '\n'.join(lines)

    cn_nums = ['一','二','三','四','五','六','七','八','九','十',
               '十一','十二','十三','十四','十五','十六','十七','十八','十九','二十',
               '二十一','二十二','二十三','二十四','二十五','二十六','二十七','二十八','二十九','三十',
               '三十一','三十二','三十三','三十四','三十五','三十六','三十七','三十八','三十九','四十']
    
    report_text = re.sub(r'^## (?:[一二三四五六七八九十]+[、.] ?|[0-9]+[、.] ?)', '## ', report_text, flags=re.MULTILINE)
    
    idx = 0
    def _add_num(m):
        nonlocal idx
        if idx < len(cn_nums):
            s = cn_nums[idx]
            idx += 1
            return f'## {s}、{m.group(1)}'
        return m.group(0)
    
    report_text = re.sub(r'^## ([^#\n])', _add_num, report_text, flags=re.MULTILINE)

    report_path = os.path.join(out_dir, 'report.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)

    timeline_path = os.path.join(out_dir, 'timeline.md')
    _generate_timeline(findings, timeline_path)

    warnings_path = os.path.join(out_dir, 'warnings.md')
    _generate_warnings(findings, warnings_path)

    return report_path


def _generate_timeline(findings, path):
    lines = ["# 重大事件时间线", ""]
    anns = findings.get('announcements', {}).get('recent_30', [])
    exec_changes = findings.get('executives', {}).get('changes', [])
    capital = findings.get('capital', {}).get('actions', [])
    related = findings.get('related', {}).get('deals', [])

    all_events = []
    for a in anns:
        all_events.append({'date': a.get('date', ''), 'title': a.get('title', ''), 'source': '公告'})
    for e in exec_changes:
        all_events.append({'date': e.get('date', ''), 'title': e.get('title', ''), 'source': '高管'})
    for c in capital:
        all_events.append({'date': c.get('date', ''), 'title': c.get('title', ''), 'source': '资金'})
    for r in related:
        all_events.append({'date': r.get('date', ''), 'title': r.get('title', ''), 'source': '资本运作'})

    seen = set()
    unique = []
    for e in all_events:
        key = (e['date'], e['title'][:30])
        if key not in seen and e['date']:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: x['date'], reverse=True)

    for e in unique[:50]:
        lines.append(f"- **{e['date']}** [{e['source']}] {e['title'][:80]}")

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _generate_warnings(findings, path):
    lines = ["# 风险信号清单", ""]

    fin_risks = findings.get('financial', {}).get('key_risks', [])
    if fin_risks:
        lines.append("## 财务风险")
        for r in fin_risks:
            lines.append(f"- ⚠️ {r}")
        lines.append("")

    exec_warnings = findings.get('executives', {}).get('summary', {}).get('warnings', [])
    if exec_warnings:
        lines.append("## 高管动态风险")
        for w in exec_warnings:
            lines.append(f"- {w}")
        lines.append("")

    cap_risks = findings.get('capital', {}).get('risks', [])
    if cap_risks:
        lines.append("## 资金动作风险")
        for r in cap_risks:
            lines.append(f"- ⚠️ {r.get('title','')}: {r.get('risk_signal','')}")
        lines.append("")

    regs = findings.get('regulatory', {}).get('records', [])
    if regs:
        severe = [r for r in regs if '🔴' in r.get('severity', '')]
        if severe:
            lines.append("## 监管风险")
            for r in severe:
                lines.append(f"- 🔴 {r.get('date','')} {r.get('title','')}")
            lines.append("")

    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='生成上市公司分析报告')
    parser.add_argument('--stock', default='000001', help='股票代码')
    parser.add_argument('--market', default='a', choices=['a', 'hk', 'us'], help='市场类型')
    parser.add_argument('--output', default='output/test_report', help='输出目录')
    parser.add_argument('--date', default=None, help='分析日期 (YYYYMMDD)')
    args = parser.parse_args()
    
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    
    test_results = {
        'stock': args.stock,
        'market': args.market,
        'dims': ['announcements', 'financial', 'executives', 'capital', 'subsidiary', 'related', 'regulatory', 'structure', 'risk'],
        'date': args.date or datetime.now().strftime('%Y%m%d'),
        'findings': {}
    }
    
    report_path = generate_report(test_results, output_dir)
    print(f"Report: {report_path}")
