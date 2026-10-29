# -*- coding: utf-8 -*-
"""
资本运作意图推断引擎

设计理念：
  不看公告"说了什么"，看关联方"做了什么"。
  从已有模块的采集结果中提取多层信号，用AI推断关联公司的资本运作方向。

信号体系（7层）：
  第1层 - 结构性推断：股权链条 + 业务逻辑
  第2层 - 市场行为信号：壳公司股价/成交量异动
  第3层 - 人事/组织信号：关键人员交叉任职、岗位招聘
  第4层 - 工商实体信号：新设SPV、经营范围变更
  第5层 - 财务/审计信号：会计所变更、资产评估
  第6层 - 监管流程信号：ODI审批、CSRC备案变更
  第7层 - 正式公告信号：太晚了，但用于确认

接口：
  fetch_capital_operation_inference(findings, company_name, stock_code) → 纯数据采集
  build_evidence(data, findings) → 构建AI证据块
  generate_report_section(data, ai_analysis=None) → 渲染报告章节
"""
import sys
import json
import re
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# ============================================================
# 信号提取器：从已有findings中提取各层信号
# ============================================================

def _extract_structural_signals(findings):
    """第1层：结构性推断 — 股权链条 + 业务逻辑"""
    signals = []

    # 信号1a：子公司IPO进度
    sub = findings.get('subsidiary_ipo', {})
    csrc = sub.get('csrc_tutoring', [])
    if csrc:
        max_period = 0
        for item in csrc:
            title = item.get('report_title', '')
            m = re.search(r'第([一二三四五六七八九十\d]+)期', title)
            if m:
                cn_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
                          '十一':11,'十二':12,'十三':13,'十四':14,'十五':15}
                p = cn_map.get(m.group(1), int(m.group(1)) if m.group(1).isdigit() else 0)
                max_period = max(max_period, p)
        companies = list(set(c.get('company_name', '') for c in csrc))
        stuck = max_period >= 3
        signals.append({
            'layer': 1, 'type': 'structural', 'subtype': 'ipo_progress',
            'text': f'子公司IPO辅导: 已至第{max_period}期, 企业: {", ".join(companies[:3])}',
            'detail': f'辅导机构: {csrc[0].get("tutor_org", "未知")}, 状态: {csrc[0].get("status", "未知")}',
            'strength': 'strong' if stuck else 'medium',
            'stuck': stuck,
            'periods': max_period,
            'companies': companies,
        })

    # 信号1b：跨市场壳公司
    cross = findings.get('cross_market', {})
    if not cross:
        # 尝试从其他数据结构获取
        cross = findings.get('cross_market_scanner', {})

    hk_entities = cross.get('hk_entities', [])
    for entity in hk_entities:
        is_shell = entity.get('is_shell', False)
        mcap = entity.get('market_cap', 999)
        if is_shell or (isinstance(mcap, (int, float)) and mcap < 30):
            signals.append({
                'layer': 1, 'type': 'structural', 'subtype': 'hk_shell',
                'text': f'关联方持有港股壳公司: {entity.get("name", "未知")} (市值约{mcap}亿)',
                'detail': f'代码: {entity.get("code", "未知")}, 关系: {entity.get("relation", "未知")}',
                'strength': 'strong',
                'entity': entity,
            })

    # 信号1c：资本运作风格识别（来自cross_market_scanner）
    patterns = cross.get('capital_operation_patterns', [])
    for pat in patterns:
        signals.append({
            'layer': 1, 'type': 'structural', 'subtype': 'pattern',
            'text': f'资本运作风格: {pat.get("pattern", "未知")} — {pat.get("description", "")}',
            'detail': f'匹配信号: {", ".join(pat.get("matched_signals", [])[:5])}',
            'strength': pat.get('confidence', 'medium'),
        })

    # 信号1d：关联方交易（来自related_deals）
    deals = findings.get('related_deals', {})
    if deals:
        risks = deals.get('risks', [])
        for r in risks[:5]:
            signals.append({
                'layer': 1, 'type': 'structural', 'subtype': 'related_deal',
                'text': f'关联方资本运作: {r.get("title", "")[:60]}',
                'detail': f'类型: {r.get("type", "未知")}, 风险: {r.get("risk", "")}',
                'strength': 'medium',
            })

    return signals


def _extract_entity_signals(findings):
    """第4层：工商实体信号 — 新设SPV、经营范围变更"""
    signals = []

    enhanced = findings.get('enhanced_company_info', {})
    if not enhanced:
        return signals

    subs = enhanced.get('subsidiaries', {}).get('full_list', [])
    offshore_keywords = ['香港', 'Hong Kong', '国际', 'International', '海外',
                         'Overseas', 'Cayman', 'BVI', 'Singapore', '新加坡']

    for s in subs:
        name = s.get('name', '')
        if any(kw in name for kw in offshore_keywords):
            signals.append({
                'layer': 4, 'type': 'entity', 'subtype': 'offshore_spv',
                'text': f'境外实体/SPV: {name}',
                'detail': f'来源: {s.get("source", "未知")}, 类型: {s.get("type", "未知")}',
                'strength': 'medium',
            })

    # 跨市场扫描发现的境外实体
    cross = findings.get('cross_market', {})
    discovered = cross.get('discovered_entities', [])
    for ent in discovered:
        if ent.get('market') in ('hk', 'us', 'sg'):
            signals.append({
                'layer': 4, 'type': 'entity', 'subtype': 'cross_market_entity',
                'text': f'跨市场实体: {ent.get("name", "")} ({ent.get("market", "").upper()})',
                'detail': f'发现方式: {ent.get("discovery_method", "未知")}',
                'strength': 'medium',
            })

    return signals


def _extract_regulatory_signals(findings):
    """第6层：监管流程信号"""
    signals = []

    # 从公告中检测监管相关关键词
    ann = findings.get('announcements', {})
    all_anns = (
        ann.get('critical_announcements', []) +
        ann.get('major_announcements', [])
    )

    regulatory_keywords = {
        'odi': ['境外投资', 'ODI', '对外投资备案', '外汇登记', '境外直接投资'],
        'csrc_merger': ['并购重组委', '重大资产重组', '发行股份购买资产', '借壳上市'],
        'hkex': ['全面要约', '强制收购', '清洗豁免', '非常重大收购', '反向收购'],
        'antitrust': ['反垄断', '经营者集中', '市场监管总局申报'],
    }

    for ann_item in all_anns:
        title = ann_item.get('title', '')
        content = ann_item.get('extracted_content', {})
        if isinstance(content, dict):
            text = content.get('full_text_preview', '') or '; '.join(content.get('key_facts', []))
        else:
            text = str(content)
        combined = title + ' ' + text

        for cat, kws in regulatory_keywords.items():
            matched = [kw for kw in kws if kw in combined]
            if matched:
                signals.append({
                    'layer': 6, 'type': 'regulatory', 'subtype': cat,
                    'text': f'监管信号[{cat.upper()}]: {title[:60]}',
                    'detail': f'匹配关键词: {", ".join(matched)}',
                    'date': ann_item.get('date', '')[:10],
                    'strength': 'strong',
                })

    # 监管合规维度
    reg = findings.get('regulatory', {})
    if reg:
        for action in reg.get('actions', []):
            title = action.get('title', '')
            if any(kw in title for kw in ['问询函', '关注函', '核查意见']):
                if any(kw in title for kw in ['收购', '重组', '关联交易', '分拆']):
                    signals.append({
                        'layer': 6, 'type': 'regulatory', 'subtype': 'inquiry',
                        'text': f'监管问询: {title[:60]}',
                        'detail': '',
                        'strength': 'medium',
                    })

    return signals


def _extract_announcement_signals(findings):
    """第7层：正式公告信号（用于确认）"""
    signals = []

    ann = findings.get('announcements', {})
    all_anns = (
        ann.get('critical_announcements', []) +
        ann.get('major_announcements', [])
    )

    confirmation_keywords = [
        '分拆上市', '借壳上市', '反向收购', '资产注入',
        '私有化', '要约收购', '全面要约', '退市',
        '发行H股', '港股上市', '两地上市',
    ]

    for ann_item in all_anns:
        title = ann_item.get('title', '')
        matched = [kw for kw in confirmation_keywords if kw in title]
        if matched:
            signals.append({
                'layer': 7, 'type': 'announcement', 'subtype': 'confirmation',
                'text': f'正式公告: {title[:80]}',
                'detail': f'确认关键词: {", ".join(matched)}',
                'date': ann_item.get('date', '')[:10],
                'strength': 'strong',
            })

    return signals


def _collect_all_signals(findings):
    """汇总所有层的信号"""
    all_signals = []
    all_signals.extend(_extract_structural_signals(findings))
    all_signals.extend(_extract_entity_signals(findings))
    all_signals.extend(_extract_regulatory_signals(findings))
    all_signals.extend(_extract_announcement_signals(findings))

    # 去重
    seen = set()
    unique = []
    for s in all_signals:
        key = (s['layer'], s.get('subtype', ''), s['text'][:30])
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


# ============================================================
# 阶段1：纯数据采集
# ============================================================

def fetch_capital_operation_inference(findings, company_name='', stock_code=''):
    """
    从已有findings中提取资本运作信号（纯数据采集，0次LLM调用）

    Args:
        findings: 其他模块采集的全部数据
        company_name: 公司名称
        stock_code: 股票代码

    Returns:
        dict: 包含信号列表和初步统计
    """
    signals = _collect_all_signals(findings)

    # 按层统计
    layer_counts = {}
    for s in signals:
        layer = s['layer']
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    strong_signals = [s for s in signals if s['strength'] == 'strong']

    # 初步模式匹配（规则引擎，不用AI）
    preliminary_hypotheses = _rule_based_hypotheses(signals)

    return {
        'stock_code': stock_code,
        'company_name': company_name,
        'signals': signals,
        'signal_count': len(signals),
        'strong_count': len(strong_signals),
        'layer_counts': layer_counts,
        'preliminary_hypotheses': preliminary_hypotheses,
        'collected_at': datetime.now().isoformat(),
    }


def _rule_based_hypotheses(signals):
    """基于规则的初步假说（不依赖AI）"""
    hypotheses = []
    layers = {s['layer']: s for s in signals}
    subtypes = {}
    for s in signals:
        subtypes.setdefault(s.get('subtype', ''), []).append(s)

    # 规则1：分拆借壳
    ipo_signals = subtypes.get('ipo_progress', [])
    shell_signals = subtypes.get('hk_shell', [])
    if ipo_signals and shell_signals:
        ipo = ipo_signals[0]
        shell = shell_signals[0]
        confidence = 'high' if ipo.get('stuck') else 'medium'
        hypotheses.append({
            'type': '分拆借壳上市',
            'confidence': confidence,
            'logic': f'IPO辅导{ipo.get("periods", "?")}期未完成 + 关联方持有港股壳公司',
            'target': shell.get('entity', {}).get('name', '未知'),
            'asset': ', '.join(ipo.get('companies', ['未知'])[:2]),
            'trigger_prospectus': True,  # 触发招股书采集
            'trigger_prospectus_reason': '子公司IPO辅导+港股壳公司',
        })

    # 规则2：私有化回A
    private_keywords = subtypes.get('confirmation', [])
    for sig in private_keywords:
        if '私有化' in sig['text'] or '退市' in sig['text']:
            hypotheses.append({
                'type': '私有化回A',
                'confidence': 'high',
                'logic': f'正式公告提及私有化/退市: {sig["text"][:40]}',
            })

    # 规则3：A+H双重上市
    for sig in private_keywords:
        if 'H股' in sig['text'] or '两地上市' in sig['text']:
            hypotheses.append({
                'type': 'A+H双重上市',
                'confidence': 'high',
                'logic': f'正式公告提及H股/两地上市',
            })

    # 规则4：境外收购
    hk_deals = [s for s in signals if s.get('subtype') in ('hk_shell', 'related_deal')]
    if hk_deals and not hypotheses:
        hypotheses.append({
            'type': '境外收购/参股',
            'confidence': 'medium',
            'logic': f'发现{len(hk_deals)}条境外关联方资本运作信号',
        })

    return hypotheses


# ============================================================
# 阶段2：AI推断（build_evidence 供 ai_unified_analyzer 调用）
# ============================================================

def build_evidence(data, findings=None):
    """构建AI推断的证据块"""
    if not data:
        return ""

    signals = data.get('signals', [])
    prelim = data.get('preliminary_hypotheses', [])
    if not signals:
        return ""

    parts = []
    parts.append(f"【资本运作信号汇总】共{len(signals)}条信号, 强信号{data.get('strong_count', 0)}条")

    # 按层分组输出
    layer_names = {1: '结构性推断', 2: '市场行为', 3: '人事组织', 4: '工商实体',
                   5: '财务审计', 6: '监管流程', 7: '正式公告'}
    for layer in sorted(data.get('layer_counts', {}).keys()):
        count = data['layer_counts'][layer]
        name = layer_names.get(layer, f'第{layer}层')
        layer_signals = [s for s in signals if s['layer'] == layer]
        parts.append(f"\n  [{name}]({count}条):")
        for s in layer_signals[:8]:
            strength_icon = {'strong': '🔴', 'medium': '🟡', 'weak': '⚪'}.get(s['strength'], '⚪')
            parts.append(f"    {strength_icon} {s['text']}")
            if s.get('detail'):
                parts.append(f"       {s['detail']}")

    if prelim:
        parts.append(f"\n【规则引擎初步假说】{len(prelim)}个:")
        for h in prelim:
            parts.append(f"  - {h['type']} (置信度: {h['confidence']}): {h['logic']}")

    # 补充关联公司全景（如果有）
    cross = {}
    if findings:
        cross = findings.get('cross_market', {})
    if cross:
        narrative = cross.get('narrative', '')
        if narrative:
            parts.append(f"\n【跨市场扫描叙事】\n{narrative[:500]}")

    return '\n'.join(parts)


def infer_with_ai(data, findings, company_name, stock_code):
    """
    用AI综合推断资本运作方向（1次LLM调用）

    Returns:
        dict: AI推断结果，包含假说列表、综合分析、跟踪建议
    """
    evidence = build_evidence(data, findings)
    if not evidence:
        return {}

    # 补充公司基本面上下文
    basic = findings.get('basic_info', {})
    if not basic:
        basic = findings.get('quote', {})
    company_context = ""
    if basic:
        name = basic.get('SECURITY_NAME_ABBR', basic.get('name', company_name))
        industry = basic.get('CSRC_INDUSTRY_NAME', '')
        concepts = basic.get('BLGAINIAN', '')
        company_context = f"公司: {name}, 行业: {industry}, 概念: {concepts[:200]}"

    prompt = f"""你是顶级投行并购部MD（董事总经理），擅长从公开信号中推断企业的资本运作意图。

以下是{company_name}（{stock_code}）的多层信号数据。请注意：这些信号中**没有**明确说明资本运作方向的正式公告，你需要基于信号链推理。

===== 公司背景 =====
{company_context}

===== 多层信号数据 =====
{evidence}

===== 你的任务 =====

1. **信号链分析**：将分散的信号串联成逻辑链。哪些信号之间存在因果关系或时间先后关系？

2. **假说生成**：基于信号链，生成1-3个资本运作假说。每个假说包含：
   - 运作类型（分拆借壳/私有化回A/资产注入/境外收购/A+H上市/业务重组等）
   - 置信度（高/中/低）
   - 完整逻辑链（从信号A → 信号B → 推断C）
   - 预期下一步动作（验证假说需要关注什么）
   - 预期时间窗口

3. **缺失信号识别**：要确认你的推断，还需要哪些信号？目前缺失什么关键信息？

4. **投资影响评估**：如果假说成立，对上市公司股价的影响路径是什么？

请以JSON格式输出：
{{
  "signal_chain_analysis": "信号链分析(300-600字)",
  "hypotheses": [
    {{
      "type": "运作类型",
      "confidence": "高|中|低",
      "logic_chain": "完整逻辑链(信号A→信号B→推断C)",
      "expected_next": "预期下一步动作",
      "timeline": "预期时间窗口",
      "impact_on_stock": "对股价的影响路径"
    }}
  ],
  "missing_signals": ["缺失信号1", "缺失信号2"],
  "monitoring_checklist": ["跟踪要点1", "跟踪要点2", "跟踪要点3"],
  "overall_assessment": "综合评估(200-400字)"
}}"""

    system = ("你是一位顶级投行并购部MD，擅长从公开信息中推断未公开的资本运作意图。"
              "你的分析风格：逻辑严密、证据链完整、不臆测但敢于合理推断。输出必须是合法JSON。")

    try:
        from scripts.llm_config import call_llm
        raw = call_llm(system, prompt, max_tokens=4096)
    except Exception as e:
        print(f"  [AI推断] LLM调用失败: {e}")
        return {}

    if not raw:
        return {}

    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return {}

    try:
        result = json.loads(match.group())
    except json.JSONDecodeError:
        return {}

    return result


# ============================================================
# 阶段3：报告渲染
# ============================================================

def generate_report_section(data, ai_analysis=None):
    """渲染资本运作推断的报告章节"""
    lines = []
    lines.append("## 资本运作意图推断")
    lines.append("")

    if not data:
        lines.append("*资本运作推断数据未获取*")
        lines.append("")
        return lines

    signals = data.get('signals', [])
    prelim = data.get('preliminary_hypotheses', [])

    # 信号汇总
    lines.append(f"### 信号汇总")
    lines.append(f"共采集 **{len(signals)}** 条信号，其中强信号 **{data.get('strong_count', 0)}** 条")
    lines.append("")

    layer_names = {1: '结构性推断', 2: '市场行为', 3: '人事组织', 4: '工商实体',
                   5: '财务审计', 6: '监管流程', 7: '正式公告'}
    for layer in sorted(data.get('layer_counts', {}).keys()):
        count = data['layer_counts'][layer]
        name = layer_names.get(layer, f'第{layer}层')
        layer_signals = [s for s in signals if s['layer'] == layer]
        lines.append(f"**{name}**（{count}条）:")
        for s in layer_signals[:6]:
            icon = {'strong': '🔴', 'medium': '🟡', 'weak': '⚪'}.get(s['strength'], '⚪')
            lines.append(f"- {icon} {s['text']}")
            if s.get('detail'):
                lines.append(f"  - {s['detail']}")
        lines.append("")

    # 规则引擎假说
    if prelim:
        lines.append("### 规则引擎初步推断")
        for h in prelim:
            conf_icon = {'high': '🟢', 'medium': '🟡', 'low': '⚪'}.get(h['confidence'], '⚪')
            lines.append(f"- {conf_icon} **{h['type']}** (置信度: {h['confidence']})")
            lines.append(f"  - 逻辑: {h['logic']}")
            if h.get('target'):
                lines.append(f"  - 目标壳: {h['target']}")
            if h.get('asset'):
                lines.append(f"  - 注入资产: {h['asset']}")
        lines.append("")

    # AI推断结果
    if ai_analysis:
        lines.append("### AI深度推断")
        lines.append("")

        chain = ai_analysis.get('signal_chain_analysis', '')
        if chain:
            lines.append(f"**信号链分析**:")
            lines.append(chain)
            lines.append("")

        hypotheses = ai_analysis.get('hypotheses', [])
        if hypotheses:
            lines.append(f"**资本运作假说**（{len(hypotheses)}个）:")
            for i, h in enumerate(hypotheses, 1):
                conf = h.get('confidence', '中')
                conf_icon = {'高': '🟢', '中': '🟡', '低': '⚪'}.get(conf, '⚪')
                lines.append(f"")
                lines.append(f"**假说{i}: {h.get('type', '未知')}** {conf_icon} 置信度{conf}")
                lines.append(f"- 逻辑链: {h.get('logic_chain', '')}")
                lines.append(f"- 预期下一步: {h.get('expected_next', '')}")
                lines.append(f"- 时间窗口: {h.get('timeline', '未知')}")
                lines.append(f"- 股价影响: {h.get('impact_on_stock', '')}")
            lines.append("")

        missing = ai_analysis.get('missing_signals', [])
        if missing:
            lines.append(f"**缺失信号**（待验证）:")
            for m in missing:
                lines.append(f"- {m}")
            lines.append("")

        checklist = ai_analysis.get('monitoring_checklist', [])
        if checklist:
            lines.append(f"**跟踪要点**:")
            for c in checklist:
                lines.append(f"- {c}")
            lines.append("")

        overall = ai_analysis.get('overall_assessment', '')
        if overall:
            lines.append(f"**综合评估**:")
            lines.append(overall)
            lines.append("")

    elif not prelim:
        lines.append("> 未检测到明显的资本运作信号。如需深度分析，建议补充跨市场扫描和子公司IPO追踪数据。")
        lines.append("")

    return lines
