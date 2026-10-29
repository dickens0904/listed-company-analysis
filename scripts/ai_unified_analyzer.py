# -*- coding: utf-8 -*-
"""
统一AI分析编排器

设计理念：3阶段分离
  阶段1: 纯数据采集（各模块 fetch_*()，0次LLM）
  阶段2: 统一AI分析（本模块，4次LLM）
  阶段3: 报告渲染（各模块 generate_report_section()，0次LLM）

每个维度模块统一接口：
  - fetch_*()           → 纯数据采集
  - build_evidence()    → 构建AI提示词证据块
  - generate_report_section(data, ai_analysis=None) → 渲染报告章节

LLM调用策略：
  调用1: 公告深度分析（逐条分析 + 全景叙事 + 风险 + 趋势 + 洞察）
  调用2: 多维度批量分析（财务 + 高管 + 资金 + 投资者 + 监管 + 治理）
  调用3: 投资逻辑生成（估值 + 催化剂 + 风险 + 评级）
  调用4: 资本运作意图推断（信号采集 + 规则引擎 + AI推断）
"""

import json
import re
import importlib
from typing import Dict, Any, Optional
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result


# ============================================================
# 模块注册表：每个维度的模块路径和显示名
# ============================================================
_DIMENSION_REGISTRY = {
    'financial':    {'module': 'scripts.financials',    'label': '财务分析'},
    'executives':   {'module': 'scripts.executives',    'label': '高管动态'},
    'capital':      {'module': 'scripts.capital',       'label': '资金动作'},
    'investor_qa':  {'module': 'scripts.investor_qa',    'label': '投资者互动'},
    'regulatory':   {'module': 'scripts.regulatory',    'label': '监管合规'},
    'governance':   {'module': 'scripts.governance',    'label': '公司治理'},
    'announcements':{'module': 'scripts.announcements', 'label': '公告全景'},
    'prospectus':   {'module': 'scripts.prospectus',    'label': '招股书分析', 'triggered': True},
}


def _load_module(module_path: str):
    """动态加载模块"""
    return importlib.import_module(module_path)


def _build_dimension_evidence(dim: str, data: dict, findings: dict = None) -> str:
    """调用模块的 build_evidence() 构建证据块"""
    if not data:
        return ""
    try:
        info = _DIMENSION_REGISTRY.get(dim)
        if not info:
            return ""
        mod = _load_module(info['module'])
        if hasattr(mod, 'build_evidence'):
            return mod.build_evidence(data, findings)
        return ""
    except Exception as e:
        print(f"  [证据构建] {dim} 失败: {e}")
        return ""


def _call_llm(prompt: str, system_prompt: str, max_tokens: int = 8192) -> Optional[str]:
    """统一LLM调用（委托给llm_config.call_llm）"""
    from scripts.llm_config import call_llm
    return call_llm(system_prompt, prompt, max_tokens=max_tokens)


def _extract_json(raw: str) -> Optional[dict]:
    """从LLM输出中提取JSON"""
    if not raw:
        return None
    match = re.search(r'\{[\s\S]*\}', raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ============================================================
# 调用1：公告深度分析
# ============================================================
def _analyze_announcements(findings: dict, company_name: str, stock_code: str) -> dict:
    """
    公告深度分析（1次LLM调用）
    输出：逐条分析 + 全景叙事 + 风险摘要 + 趋势分析 + 核心洞察
    """
    result = {
        'per_announcement': [],
        'narrative': '',
        'risk_summary': '',
        'key_insights': [],
        'trend_analysis': '',
    }

    ann = findings.get('announcements', {})
    if not ann:
        return result

    critical = ann.get('critical_announcements', [])
    major = ann.get('major_announcements', [])
    all_important = critical + major

    if not all_important:
        return result

    # 构建公告证据
    evidence_parts = []
    for i, a in enumerate(all_important[:20], 1):
        part = f"【公告{i}】[{a.get('importance','').upper()}] {a.get('importance_tag','')}\n"
        part += f"日期: {a.get('date','')[:10]}\n"
        part += f"标题: {a.get('title','')}\n"

        content = a.get('extracted_content', {})
        if isinstance(content, dict) and not content.get('error'):
            facts = content.get('key_facts', [])
            if facts:
                part += f"关键事实: {'; '.join(facts[:5])}\n"
            preview = content.get('full_text_preview', '')
            if preview:
                part += f"正文摘要: {preview[:800]}\n"
        else:
            raw_content = a.get('content', '')
            if raw_content:
                part += f"正文摘要: {raw_content[:800]}\n"

        deep = a.get('deep_analysis', {})
        if isinstance(deep, dict) and deep.get('facts'):
            part += f"深度提取: {'; '.join(deep['facts'][:3])}\n"
            if deep.get('nature'):
                part += f"性质判断: {deep['nature']}\n"

        evidence_parts.append(part)

    evidence = '\n'.join(evidence_parts)

    stats = ann.get('importance_stats', {})
    ann_list = ""
    for i, a in enumerate(all_important[:20], 1):
        ann_list += f"{i}. [{a.get('importance','').upper()}] {a.get('date','')[:10]} | {a.get('title','')[:80]}\n"

    prompt = f"""你是顶级券商首席分析师。以下是{company_name}（{stock_code}）的公告数据（共{ann.get('count',0)}条，其中CRITICAL {stats.get('critical',0)}条、MAJOR {stats.get('major',0)}条）。
请一次性完成以下分析任务：

===== 任务1：逐条公告分析 =====
对以下每条重要公告进行独立分析：
{ann_list}
每条输出：分类、摘要(50字内)、影响分析(100字内)、风险因素、性质(利好/利空/中性)

===== 任务2：公司全景叙事 =====
基于全部公告证据，写一篇连贯的公司情况叙述报告(2000-4000字)。按时间线和逻辑线交织叙述，每个重要结论引用具体公告证据。用Markdown格式。

===== 任务3：趋势与风险 =====
分析公司近期发展趋势(200-400字)和风险摘要(200-400字)，提炼3-5条核心投资洞察。

===== 公告证据 =====
{evidence}
===== 证据结束 =====

请以JSON格式输出：
{{
  "per_announcement": [
    {{"title": "标题", "date": "日期", "category": "分类", "importance": "critical|major", "summary": "摘要", "impact_analysis": "影响分析", "risk_factors": ["风险"], "nature": "利好|利空|中性"}}
  ],
  "narrative": "全景叙述报告(Markdown, 2000-4000字)",
  "risk_summary": "风险摘要(200-400字)",
  "key_insights": ["洞察1", "洞察2", "洞察3"],
  "trend_analysis": "趋势分析(200-400字)"
}}"""

    system = "你是一位顶级券商首席分析师，擅长基于原始公告证据进行深度分析。输出必须是合法JSON。"
    raw = _call_llm(prompt, system)

    data = _extract_json(raw)
    if data:
        if isinstance(data.get('per_announcement'), list):
            result['per_announcement'] = data['per_announcement']
        if data.get('narrative') and len(data['narrative']) > 200:
            result['narrative'] = data['narrative']
        if data.get('risk_summary') and len(data['risk_summary']) > 50:
            result['risk_summary'] = data['risk_summary']
        if isinstance(data.get('key_insights'), list):
            result['key_insights'] = data['key_insights']
        if data.get('trend_analysis') and len(data['trend_analysis']) > 50:
            result['trend_analysis'] = data['trend_analysis']

    matched = len(result['per_announcement'])
    print(f"  [公告分析] 完成: {matched}/{len(all_important)}条 + 叙事{'✅' if result['narrative'] else '❌'} + 风险{'✅' if result['risk_summary'] else '❌'}")

    return result


# ============================================================
# 调用2：多维度批量分析
# ============================================================
def _analyze_dimensions(findings: dict, company_name: str, stock_code: str) -> dict:
    """
    多维度批量分析（1次LLM调用）
    输出：6个维度的AI解读文本
    """
    result = {}

    # 收集各维度证据
    dims_to_analyze = ['financial', 'executives', 'capital', 'investor_qa', 'regulatory', 'governance']
    evidence_blocks = []
    active_dims = []

    tdx_data = findings.get('tdx', {})
    if tdx_data.get('success'):
        try:
            from scripts.tdx_provider import build_evidence_for_ai
            tdx_evidence = build_evidence_for_ai(tdx_data)
            if tdx_evidence:
                evidence_blocks.append(f"===== 通达信公司信息 =====\n{tdx_evidence}\n=====")
        except Exception as e:
            print(f"  [通达信] 证据构建失败: {e}")

    pli_data = findings.get('product_line_intro', {})
    if pli_data:
        try:
            from scripts.product_line_intro import build_evidence_for_ai as pli_evidence
            pli_text = pli_evidence(pli_data)
            if pli_text:
                evidence_blocks.append(f"===== 产品与产线基地 =====\n{pli_text}\n=====")
        except Exception as e:
            print(f"  [产品模块] 证据构建失败: {e}")

    for dim in dims_to_analyze:
        data = findings.get(dim, {})
        if not data:
            continue
        evidence = _build_dimension_evidence(dim, data, findings)
        if evidence:
            info = _DIMENSION_REGISTRY.get(dim, {})
            label = info.get('label', dim)
            evidence_blocks.append(f"===== {label} =====\n{evidence}\n=====")
            active_dims.append(dim)

    if not evidence_blocks:
        return result

    output_keys = ', '.join([f'"{d}": "{_DIMENSION_REGISTRY.get(d,{}).get("label",d)}分析(200-400字)"' for d in active_dims])

    prompt = f"""你是顶级券商首席分析师。以下是{company_name}（{stock_code}）的多维度数据，请一次性输出{len(active_dims)}个维度的专业分析解读。

要求：
1. 每个维度的分析控制在200-400字
2. 语言专业、客观、有洞察力
3. 每个分析独立成段，不要交叉引用
4. 输出格式严格按照JSON

{chr(10).join(evidence_blocks)}

请以JSON格式输出（不要输出其他内容）：
{{
  {output_keys}
}}"""

    system = "你是一位顶级券商首席分析师，擅长多维度综合分析。输出必须是合法JSON。"
    raw = _call_llm(prompt, system)

    data = _extract_json(raw)
    if data:
        for dim in active_dims:
            val = data.get(dim, '')
            if val and len(val) > 50:
                result[dim] = val

    filled = [d for d in active_dims if d in result]
    print(f"  [多维度分析] 完成: {len(filled)}/{len(active_dims)}个维度: {', '.join(filled)}")

    return result


# ============================================================
# 将批量分析结果写回公告数据（保持兼容性）
# ============================================================
def _apply_announcement_results(findings: dict, ann_result: dict):
    """将公告分析结果写回公告数据结构"""
    ann = findings.get('announcements', {})
    if not ann or not ann_result:
        return

    per_ann = ann_result.get('per_announcement', [])
    if per_ann:
        critical = ann.get('critical_announcements', [])
        major = ann.get('major_announcements', [])
        all_important = critical + major

        matched = 0
        for analysis in per_ann:
            a_title = analysis.get('title', '')
            for ann_item in all_important:
                if a_title and a_title[:20] in ann_item.get('title', ''):
                    ann_item['ai_analysis'] = {
                        'category': analysis.get('category', ''),
                        'summary': analysis.get('summary', ''),
                        'impact_analysis': analysis.get('impact_analysis', ''),
                        'key_points': analysis.get('key_points', []),
                        'risk_factors': analysis.get('risk_factors', []),
                        'nature': analysis.get('nature', '中性'),
                    }
                    matched += 1
                    break
        print(f"  [结果回写] 匹配 {matched}/{len(per_ann)} 条公告")

    ann['_batch_analysis'] = {
        'narrative': ann_result.get('narrative', ''),
        'risk_summary': ann_result.get('risk_summary', ''),
        'key_insights': ann_result.get('key_insights', []),
        'trend_analysis': ann_result.get('trend_analysis', ''),
    }


# ============================================================
# 内容关联：将主公告的已提取内容关联到各模块记录
# ============================================================
def _enrich_module_records(findings: dict):
    """将已提取的公告正文内容关联到高管/资金/监管/投资者互动等只有标题的记录

    匹配策略：
    1. 优先从主公告的extracted_content中匹配（去掉公司名前缀，用核心标题前25字）
    2. 如果匹配失败，通过标题匹配主公告的adjunct_url，下载PDF提取正文
    """
    import os
    import tempfile
    from scripts.announcements import download_announcement_pdf, extract_key_content

    all_anns = (
        findings.get('announcements', {}).get('critical_announcements', []) +
        findings.get('announcements', {}).get('major_announcements', []) +
        findings.get('announcements', {}).get('routine_announcements', [])
    )

    # 建立 content_map：核心标题 → 正文内容
    # 建立 adjunct_map：核心标题 → adjunct_url（用于PDF下载）
    content_map = {}
    adjunct_map = {}
    for a in all_anns:
        title = a.get('title', '')
        if not title:
            continue
        
        # 提取正文内容
        extracted = a.get('extracted_content', {})
        content = ''
        if isinstance(extracted, dict) and not extracted.get('error'):
            preview = extracted.get('full_text_preview', '')
            facts = extracted.get('key_facts', [])
            if preview:
                content = preview[:1500]
            elif facts:
                content = '; '.join(facts[:5])
        if not content:
            content = a.get('content', '')[:1500] if a.get('content') else ''

        # 去掉公司名前缀，用核心标题作为key
        core = re.sub(r'^[^：:]+[：:]\s*', '', title)
        key = core[:25]
        
        if content:
            if key not in content_map or len(content) > len(content_map[key]):
                content_map[key] = content
        
        # 保存adjunct_url
        adjunct_url = a.get('adjunct_url', '')
        if adjunct_url and key not in adjunct_map:
            adjunct_map[key] = adjunct_url

    # 关联到各模块
    enriched = 0
    pdf_fetched = 0
    temp_dir = os.path.join(tempfile.gettempdir(), 'lca_pdf_cache')
    os.makedirs(temp_dir, exist_ok=True)

    for dim in ('executives', 'capital', 'regulatory', 'investor_qa'):
        data = findings.get(dim, {})
        if not data:
            continue
        
        # 根据模块类型获取记录列表
        if dim == 'executives':
            records = data.get('changes', [])
        elif dim == 'investor_qa':
            records = data.get('survey_records', []) + data.get('ir_activities', [])
        else:
            records = data.get('actions', data.get('records', []))
        
        for rec in records:
            if rec.get('content'):
                continue
            title = rec.get('title', '')
            core = re.sub(r'^[^：:]+[：:]\s*', '', title)
            key = core[:25]
            
            # 策略1：从主公告匹配已提取的内容
            if key in content_map:
                rec['content'] = content_map[key]
                enriched += 1
                continue
            
            # 策略2：通过标题匹配主公告的adjunct_url，下载PDF提取正文
            if key in adjunct_map:
                try:
                    adjunct_url = adjunct_map[key]
                    ann_info = {
                        'art_code': rec.get('art_code', ''),
                        'adjunct_url': adjunct_url,
                        'title': title,
                    }
                    pdf_path = download_announcement_pdf(ann_info, temp_dir, market='a')
                    if pdf_path:
                        content = extract_key_content(pdf_path, '', max_pages=3)
                        if content:
                            full_text = content.get('full_text_preview', '') or content.get('summary', '')
                            if full_text:
                                rec['content'] = full_text[:1500]
                                enriched += 1
                                pdf_fetched += 1
                except Exception as _sexc:
                    record(__name__, '_enrich_module_records', _sexc, note='静默降级')
                    pass

    if enriched:
        print(f"  [内容关联] 已关联 {enriched} 条记录的正文内容（其中 {pdf_fetched} 条通过PDF下载）")


# ============================================================
# 主入口：统一AI分析
# ============================================================
def unified_analyze(findings: dict, company_name: str = '', stock_code: str = '') -> dict:
    """
    统一AI分析入口

    阶段2的核心函数：在所有数据采集完成后，一次性完成所有AI分析。

    Args:
        findings: 所有维度的原始数据（阶段1采集结果）
        company_name: 公司名称
        stock_code: 股票代码

    Returns:
        {
            'announcements': {per_announcement, narrative, risk_summary, key_insights, trend_analysis},
            'financial': str,
            'executives': str,
            'capital': str,
            'investor_qa': str,
            'regulatory': str,
            'governance': str,
            'investment_thesis': {thesis, catalysts, risks, investment_rating, markdown},
            'capital_operation_inference': {signals, preliminary_hypotheses, ai_analysis},
        }
    """
    if not company_name:
        company_name = findings.get('quote', {}).get('name', stock_code)

    print(f"\n{'='*60}")
    print(f"🧠 AI统一分析: {company_name}({stock_code})")
    print(f"{'='*60}")

    ai_result = {
        'announcements': {},
        'financial': '',
        'executives': '',
        'capital': '',
        'investor_qa': '',
        'regulatory': '',
        'governance': '',
        'investment_thesis': {},
        'capital_operation_inference': {},
    }

    has_ann = bool(findings.get('announcements', {}).get('critical_announcements') or
                   findings.get('announcements', {}).get('major_announcements'))
    has_dims = any(findings.get(d) for d in [
        'financial', 'executives', 'capital', 'investor_qa', 'regulatory', 'governance'
    ])

    # 调用1：公告深度分析
    if has_ann:
        print(f"\n  📢 调用1/3: 公告深度分析...")
        ann_result = _analyze_announcements(findings, company_name, stock_code)
        ai_result['announcements'] = ann_result
        _apply_announcement_results(findings, ann_result)
    else:
        print(f"\n  📢 调用1/3: 无重要公告，跳过")

    # 调用2：多维度批量分析
    if has_dims:
        print(f"\n  📊 调用2/3: 多维度批量分析...")
        _enrich_module_records(findings)
        dim_result = _analyze_dimensions(findings, company_name, stock_code)
        for k, v in dim_result.items():
            ai_result[k] = v
    else:
        print(f"\n  📊 调用2/3: 无维度数据，跳过")

    # 调用3：投资逻辑
    print(f"\n  💰 调用3/4: 投资逻辑...")
    try:
        from scripts.investment_thesis import generate_investment_thesis
        analysis_data = {'findings': findings}
        thesis = generate_investment_thesis(analysis_data, stock_code)
        if thesis and thesis.get('markdown'):
            ai_result['investment_thesis'] = thesis
            print(f"  [投资逻辑] 生成成功，{len(thesis['markdown'])}字")
        else:
            print(f"  [投资逻辑] 生成失败或内容为空")
    except Exception as e:
        print(f"  [投资逻辑] 失败: {e}")

    # 调用4：资本运作意图推断
    print(f"\n  🔮 调用4/4: 资本运作意图推断...")
    try:
        from scripts.capital_operation_inference import (
            fetch_capital_operation_inference, infer_with_ai
        )
        coi_data = fetch_capital_operation_inference(findings, company_name, stock_code)
        if coi_data and coi_data.get('signal_count', 0) > 0:
            print(f"  [信号采集] {coi_data['signal_count']}条信号, 强信号{coi_data['strong_count']}条")
            prelim = coi_data.get('preliminary_hypotheses', [])
            if prelim:
                print(f"  [规则引擎] {len(prelim)}个初步假说: {', '.join(h['type'] for h in prelim)}")
            # AI推断
            ai_inference = infer_with_ai(coi_data, findings, company_name, stock_code)
            if ai_inference:
                coi_data['ai_analysis'] = ai_inference
                print(f"  [AI推断] 完成: {len(ai_inference.get('hypotheses', []))}个假说")
            else:
                print(f"  [AI推断] 未返回有效结果")
            ai_result['capital_operation_inference'] = coi_data
        else:
            print(f"  [资本运作] 未检测到有效信号，跳过AI推断")
    except Exception as e:
        print(f"  [资本运作推断] 失败: {e}")

    # 调用5：招股书（仅触发式）
    try:
        from scripts.prospectus import (
            fetch_prospectus, should_trigger_prospectus, generate_report_section as prospectus_section
        )
        coi = ai_result.get('capital_operation_inference', {})
        triggered_hyps = [h for h in coi.get('preliminary_hypotheses', [])
                         if h.get('trigger_prospectus')]
        ai_hyps = [h for h in coi.get('ai_analysis', {}).get('hypotheses', [])
                   if h.get('trigger_prospectus')]
        all_triggered = triggered_hyps or ai_hyps

        # 也直接检测
        if not all_triggered and should_trigger_prospectus(findings):
            all_triggered = [{'reason': 'should_trigger_prospectus() = True'}]

        if all_triggered and stock_code:
            print(f"\n  📑 触发招股书采集: {len(all_triggered)} 个触发信号")
            market = 'a' if len(stock_code) == 6 and stock_code.isdigit() else (
                    'hk' if len(stock_code) == 5 and stock_code.isdigit() else 'us')
            prospectus_data = fetch_prospectus(stock_code, company_name, market=market)
            ai_result['prospectus'] = prospectus_data
            if prospectus_data.get('has_prospectus'):
                print(f"  [招股书] 找到 {len(prospectus_data.get('documents', []))} 份")
            else:
                print(f"  [招股书] 未找到 {market} 市场招股书")
        else:
            print(f"\n  📑 招股书未触发（无IPO辅导/分拆借壳信号）")
    except Exception as e:
        print(f"  [招股书] 处理失败: {e}")

    # 统计
    filled = [k for k, v in ai_result.items() if v and k not in ('announcements', 'investment_thesis', 'capital_operation_inference')]
    ann_ok = bool(ai_result['announcements'].get('narrative'))
    thesis_ok = bool(ai_result['investment_thesis'].get('markdown'))
    coi_ok = bool(ai_result['capital_operation_inference'].get('ai_analysis'))
    print(f"\n  ✅ 统一分析完成: 公告{'✅' if ann_ok else '❌'} | 维度{len(filled)}个 | 投资逻辑{'✅' if thesis_ok else '❌'} | 资本推断{'✅' if coi_ok else '❌'}")

    return ai_result


def get_announcement_narrative(ai_result: dict) -> str:
    """从统一结果中提取公告叙事"""
    return ai_result.get('announcements', {}).get('narrative', '')
