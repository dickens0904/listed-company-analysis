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

# 🔴 兼容导入：本模块大量使用 `from scripts.xxx import ...`。当从 scripts/ 目录
#    直接运行（如重渲染脚本，sys.path 首位是 scripts/ 而非 skill 根）时，`scripts`
#    包不存在 → "No module named 'scripts.financials'"。此处注册指向 scripts/ 的伪包。
try:
    import scripts as _scripts_pkg  # noqa: F401
except ImportError:
    import types as _types
    _pkg = _types.ModuleType('scripts')
    _pkg.__path__ = [_scripts_dir]
    sys.modules['scripts'] = _pkg

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
            try:
                _module_cache[module_path] = importlib.import_module(module_path)
            except ImportError:
                # 从 scripts/ 目录直接运行（sys.path 已含 scripts/）时 `scripts` 包不可用
                # → 回退裸模块名，避免 "No module named 'scripts.xxx'"
                _module_cache[module_path] = importlib.import_module(module_path.split('.')[-1])
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
    # 审计意见：优先真实提取；旧推断值（含"推断"）不可信 → 用年报重建值或标"未取到"
    _opinion = fin.get('audit_opinion')
    if not _opinion or '推断' in str(_opinion):
        _va = ((findings.get('annual_pdf') or {}).get('_visual_tables') or {}).get('audit', '')
        if '标准无保留' in _va:
            _opinion = '标准无保留意见'
        elif any(x in _va for x in ('保留意见', '否定意见', '无法表示')):
            _opinion = '非标准意见（详见年报审计报告）'
        else:
            _opinion = '未取到（详见年报审计报告）'
    if _opinion:
        lines.append(f"**审计意见**: {_opinion}")
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


def _section_valuation_fallback(findings):
    """估值章节：SOTP 不成立/无 current 时，回退用当日行情快照的 PE/PB/市值。"""
    q = findings.get('quote') or {}
    v = findings.get('valuation') or {}
    lines = ["## 估值分析", ""]
    if q.get('mcap_yi') or q.get('price'):
        lines.append("**行情快照估值**（当日收盘）")
        lines.append("")
        lines.append("| 指标 | 数值 | 说明 |")
        lines.append("|---|---:|---|")
        lines.append(f"| 股价 | {q.get('price', '—')} 元 | {q.get('_source', '')} |")
        lines.append(f"| 总市值 | {q.get('mcap_yi', '—')} 亿元 | — |")
        lines.append(f"| 流通市值 | {q.get('float_mcap_yi', '—')} 亿元 | — |")
        _pe = q.get('pe_ttm')
        _pe_note = '负值＝亏损，PE 无意义' if isinstance(_pe, (int, float)) and _pe < 0 else '—'
        lines.append(f"| PE(TTM) | {_pe if _pe is not None else '—'} | {_pe_note} |")
        lines.append(f"| PB | {q.get('pb', '—')} | — |")
        lines.append("")
        _note = v.get('note') or ''
        lines.append(f"> 亏损公司 PE 失效，应以 PS / PB 交叉验证（PS = 总市值 / TTM 营收）。"
                     f"分部估值（SOTP）{'不成立：' + _note if _note else '未生成'}。")
    else:
        lines.append("_暂无行情数据_")
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

    # 缺失字段的 ? / ❓ 统一显示为「—」，避免报告出现占位符
    rows = [[('—' if str(v) in ('?', '❓', 'None') else v) for v in r] for r in rows]
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


def _clean_table_block(block):
    """清洗单个 markdown 表格块。

    - 删除**格内** None/NaN token（PDF 抽取常把多值挤进一格，如「None 应收账款 合同资产」）；
    - 单格含 ≥4 个数字串 → 判定 PDF 表格结构已丢失，隐藏并提示（避免读者误读乱表）；
    - 其余：去全空行列、超宽截断、长表截断。
    """
    import re as _re

    def _tok(c):
        c = _re.sub(r'(?<![A-Za-z0-9_])(?:None|NaN|null|nan)(?![A-Za-z0-9_])', ' ', c)
        return _re.sub(r'[ \t]{2,}', ' ', c).strip()

    data = []
    for ln in block:
        s = ln.strip()
        if _re.match(r'^\|[\s\-:|]+\|$', s):      # 分隔行，重建时再生成
            continue
        data.append([_tok(c) for c in s.strip('|').split('|')])
    if not data:
        return []
    ncol = max(len(r) for r in data)
    data = [r + [''] * (ncol - len(r)) for r in data]

    keep = [j for j in range(ncol) if any(r[j] for r in data)]

    # 多值挤格 / 超宽表检测（PDF 表格行列结构丢失 → 隐藏，避免读者误读乱表）
    def _nnum(c):
        return len(_re.findall(r'\d[\d,]*\.\d+|\d{3,}', c))
    if max((_nnum(c) for r in data for c in r), default=0) >= 3 or len(keep) > 12:
        # 源 PDF 表格无清晰框线 → 列边界客观上不可还原（pdfplumber 把多行并成一格）。
        # 不做假表，也不整段隐藏：保留原文数据行（去表格符号），读者至少能读到数。
        out = ['', '> 📄 该表 PDF 行列结构未能还原（源表无清晰框线），以下为原文数据行：', '']
        shown = 0
        for r in data:
            cells = [c for c in r if c]
            if not cells:
                continue
            out.append('- ' + ' · '.join(cells))
            shown += 1
            if shown >= 24:
                out.append('- _…（已截断，完整数据见年报原文）_')
                break
        return out

    data = [[r[j] for j in keep] for r in data]
    data = [r for r in data if any(r)]
    if not data:
        return []
    # 破损表常出现"全空表头"→ 下移一行作表头
    if not any(data[0]) and len(data) > 1:
        data = data[1:]

    def _cap(c):
        c = c.replace('\n', ' ').strip()
        return c if len(c) <= 60 else c[:58] + '…'
    data = [[_cap(c) for c in r] for r in data]

    out = ['| ' + ' | '.join(data[0]) + ' |',
           '|' + '|'.join([' --- '] * len(data[0])) + '|']
    body = data[1:]
    truncated = False
    if len(body) > 12:
        body = body[:12]
        truncated = True
    out += ['| ' + ' | '.join(r) + ' |' for r in body]
    if truncated:
        out.append('')
        out.append('_（该表已截断，完整数据以年报原文为准）_')
    return out


def _clean_md_tables(text):
    """清洗 PDF 抽取表格：合并被换行拆断的行 + 逐表去 None / 空行列。"""
    if not text:
        return text
    import re as _re
    lines = text.split('\n')
    # ① 合并续行：上一行是表格行、本行非空且不是标题/列表/引用/代码 → 拼回
    merged = []
    for ln in lines:
        s = ln.strip()
        if (merged and s and not s.startswith('|')
                and not _re.match(r'^(#{1,6}\s|[-*+]\s|\d+\.\s|>|```)', s)
                and merged[-1].strip().startswith('|')):
            prev = merged[-1].rstrip()
            # 续行以数字/逗号/点开头且上一行也以数字结尾 → 直接黏合（还原被换行截断的数字）
            if (s[0].isdigit() or s[0] in ',.') and prev and (prev[-1].isdigit() or prev[-1] in ',.'):
                merged[-1] = prev + s
            else:
                merged[-1] = prev + ' ' + s
        else:
            merged.append(ln)
    # ② 逐表格块清洗
    out, i = [], 0
    while i < len(merged):
        if merged[i].strip().startswith('|'):
            block = []
            while i < len(merged) and merged[i].strip().startswith('|'):
                block.append(merged[i]); i += 1
            out.extend(_clean_table_block(block))
        else:
            out.append(merged[i]); i += 1
    return '\n'.join(out)


def _parse_top5(content, label):
    """把「序号 / 名称 / 金额 / 占比」竖排文本解析成 markdown 表；无法解析返回 None。

    年报 PDF 文本层形如（每字段一行）：
        序号 客户名称 销售额（元） 占年度销售总额比例
        1 客户一 158,359,597.81 7.82%
        ...
        合计 -- 377,607,903.46 18.63%
    """
    import re as _re
    if not content:
        return None
    lines = [l.strip() for l in content.split('\n') if l.strip()]

    hdr = next((i for i, l in enumerate(lines) if label in l), None)
    if hdr is None:
        return None

    # 表头可能占多行（列名各占一行）→ 找第一个纯数字行作数据起点
    start = next((j for j in range(hdr + 1, len(lines)) if _re.fullmatch(r'\d{1,2}', lines[j])), None)
    if start is None:
        return None

    rows, i = [], start
    while i + 3 < len(lines):
        no, nm, amt, pct = lines[i], lines[i + 1], lines[i + 2], lines[i + 3]
        if not _re.fullmatch(r'\d{1,2}', no) or not _re.search(r'[\d,]+\.\d{2}', amt):
            break
        rows.append([no, nm, amt, pct])
        i += 4
    if len(rows) < 3:
        return None

    md = ['| 序号 | %s | 金额（元） | 占比 |' % label,
          '| --- | --- | ---: | ---: |']
    md += ['| %s | %s | %s | %s |' % tuple(r) for r in rows]

    # 合计行（「合计」后可能隔页码行，向后找金额与占比）
    for j in range(i, len(lines) - 1):
        if lines[j] == '合计':
            seg = lines[j:j + 6]
            _amt = next((x for x in seg if _re.search(r'[\d,]+\.\d{2}', x)), '')
            _pct = next((x for x in seg if _re.fullmatch(r'\d+(?:\.\d+)?%', x)), '')
            if _amt:
                md.append('| 合计 | — | %s | %s |' % (_amt, _pct or '—'))
            break
    return '\n'.join(md)


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
                # 去重：litigation_detail 与 litigation 内容高度重复（后者已含汇总），仅保留后者
                if key == 'litigation_detail' and 'litigation' in sections:
                    continue
                sdata = sections[key]
                name = sdata.get('name', key)
                desc = sdata.get('description', '')
                # 🔴 视觉重建表优先：PDF 表格无清晰框线导致抽取错位时，
                #    由人/AI 看页面截图理解结构后重建的 markdown 表（存于 annual_pdf._visual_tables），
                #    此处直接采用，不再走 PDF 文本清洗/降级。
                _vis = (data.get('_visual_tables') or {}).get(key)
                if _vis:
                    lines.append(f"### {name}")
                    if desc:
                        lines.append(f"_{desc}_  ")
                    lines.append(_vis)
                    lines.append("")
                    continue
                raw_content = sdata.get('content', '')
                # 碎片降级：PDF 原文被拆成大量短行（平均 <18 字/行，如「姓名/性/别/年/龄」），
                # 直接铺进报告无法阅读 → 只给页码指引（有价值的内容另见 _visual_tables）
                _ls = [x for x in raw_content.split('\n') if x.strip()]
                if (key not in ('top5_customers', 'top5_suppliers')
                        and len(_ls) > 60 and (sum(len(x) for x in _ls) / len(_ls)) < 15):
                    lines.append(f"### {name}")
                    if desc:
                        lines.append(f"_{desc}_  ")
                    _pg = next((x for x in raw_content.split('\n') if '第' in x and '页' in x), '')
                    lines.append(f"> 📄 本章为年报 PDF 原文逐行碎片（{len(_ls)} 行），"
                                 f"不便直接阅读；完整内容见年报{_pg or '对应页'}。")
                    lines.append("")
                    continue
                # 前五名客户/供应商：原文是竖排文本（序号/名称/金额/占比 各一行），
                # 文本层完整 → 解析成规范表格（不隐藏、不丢数据）
                if key in ('top5_customers', 'top5_suppliers'):
                    _label = '客户名称' if key == 'top5_customers' else '供应商名称'
                    _tbl = _parse_top5(raw_content, _label)
                    if _tbl:
                        lines.append(f"### {name}")
                        if desc:
                            lines.append(f"_{desc}_  ")
                        _head = next((l.strip() for l in raw_content.split('\n') if '关联方' in l), '')
                        if _head:
                            lines.append(f'> {_head}')
                        lines.append(_tbl)
                        lines.append("")
                        continue
                content = _clean_md_tables(raw_content)
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
    # 🔴 审计意见校正：旧版按"净利润为负"推断出的"非标准意见"不可信（亏损≠非标），
    #    有年报重建值则用真实值，否则标"未取到"——禁止编造审计意见。
    _fin0 = findings.get('financial')
    if isinstance(_fin0, dict) and '推断' in str(_fin0.get('audit_opinion') or ''):
        _va0 = ((findings.get('annual_pdf') or {}).get('_visual_tables') or {}).get('audit', '')
        _fin0['audit_opinion'] = ('标准无保留意见' if '标准无保留' in _va0
                                  else '未取到（详见年报审计报告）')

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
            # 用文件路径直接加载，绕过 `scripts` 包名在运行时的解析差异
            import importlib.util as _ilu
            _pli_path = os.path.join(_scripts_dir, 'product_line_intro.py')
            _spec = _ilu.spec_from_file_location('_pli_report', _pli_path)
            _pli = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_pli)
            lines += _pli.generate_report_section(pli_data)
        except Exception as e:
            lines.append(f"\n⚠️ 产品与产线基地章节生成失败: {e}\n")

    ai = findings.get('ai_analysis', {})
    batch = {}
    for dim in ('financial', 'executives', 'capital', 'investor_qa', 'regulatory', 'governance'):
        if ai.get(dim):
            batch[dim] = ai[dim]

    for dim in results['dims']:
        # 产品与产线已在正文前专门渲染（generate_report 中 pli_data 段），此处跳过避免重复
        if dim == 'product_line_intro':
            continue
        if dim == 'quote':
            if 'quote' in findings:
                lines += _section_quote(findings['quote'])
            continue

        if dim == 'annual_pdf':
            if 'annual_pdf' in findings:
                lines += _section_annual_pdf(findings['annual_pdf'])
            continue

        # 估值：SOTP 不成立时回退行情快照（PE/PB/市值），避免出现「暂无行情数据」
        if dim == 'valuation':
            lines += _section_valuation_fallback(findings)
            continue

        # qcc 权威维度：专用渲染器（2026-10-19）
        if dim == 'legal_risk':
            try:
                from scripts.qcc_dimensions import format_legal_risk_markdown
                lines.append(format_legal_risk_markdown(data))
            except Exception as e:
                lines.append(f"\n⚠️ 法律/合规风险章节生成失败: {e}\n")
            continue

        if dim == 'intellectual_property':
            try:
                from scripts.qcc_dimensions import format_ip_markdown
                lines.append(format_ip_markdown(data))
            except Exception as e:
                lines.append(f"\n⚠️ 知识产权章节生成失败: {e}\n")
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

    # ⚠️ 静默降级清单（2026-10-19 审计新增）
    # 置于报告末尾"附录位"：不污染主体叙事，但让数据可靠性问题可追问、可追责。
    se = results.get('_silenced_errors') or {}
    if se.get('total'):
        try:
            from scripts.silenced_errors import format_markdown as _fmt_sil
            lines.append(_fmt_sil(se))
        except Exception as e:
            lines.append(f"\n⚠️ 静默降级清单渲染失败: {e}\n")

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

    # ── P0 红线章节注入（2026-10-16 审计修复）──
    # 核心维度数据不足时，把 🔴 红灯说明插到报告最顶部（执行摘要之前），
    # 确保读者第一眼看到"本报告不出具投资建议"，而不是先看到一堆半截数据。
    try:
        from scripts.redline_gate import format_redline_markdown
        rl = (results or {}).get('redline')
        if rl:
            rl_md = format_redline_markdown(rl)
            if rl_md:
                report_text = rl_md + '\n' + report_text
    except Exception as _e:
        print(f"  ⚠️ 红灯章节注入失败: {_e}")

    # AI 全景叙事过长（实测 1.7 万字）→ 截断至 1500 字，避免淹没整篇报告
    _m_ai = re.search(r'(#{2,3}\s*🤖\s*AI公司全景叙事[^\n]*\n)', report_text)
    if _m_ai:
        _st = _m_ai.end()
        _rest = report_text[_st:]
        _nxt = re.search(r'\n## ', _rest)
        _seg = _rest[:_nxt.start()] if _nxt else _rest
        if len(_seg) > 1500:
            report_text = (report_text[:_st] + _seg[:1500]
                           + '\n\n_（AI 全景叙事过长，已截断至 1500 字）_\n'
                           + (_rest[_nxt.start():] if _nxt else ''))
    report_path = os.path.join(out_dir, 'report.md')
    # 兜底：模块拼出的 HTML 表格里残留的 None 单元格 → 统一替换为「—」
    report_text = (report_text.replace('<td>None</td>', '<td>—</td>')
                              .replace('<td> None </td>', '<td>—</td>'))
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

    # 兜底：模块拼出的 HTML 表格里残留的 None 单元格 → 统一替换为「—」
    _md_out = '\n'.join(lines)
    _md_out = (_md_out.replace('<td>None</td>', '<td>—</td>')
                      .replace('<td> None </td>', '<td>—</td>'))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(_md_out)


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
