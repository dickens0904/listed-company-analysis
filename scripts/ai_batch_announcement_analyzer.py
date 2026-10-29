# -*- coding: utf-8 -*-
"""
AI批量公告分析模块

将所有CRITICAL+MAJOR公告打包成1次LLM调用，同时输出：
1. 每条公告的独立分析（分类/摘要/影响/风险）
2. 公司全景叙事（连贯叙述性报告）
3. 风险摘要（整体风险判断）

替代原来的逐条LLM调用（最多20次）+ 全景叙事（1次），共21次 → 1次
"""

import json
import re
from typing import Dict, List, Any, Optional


def _build_announcement_evidence(announcements, max_anns=20, max_text_per_ann=800):
    """构建公告证据块"""
    evidence_parts = []

    for i, ann in enumerate(announcements[:max_anns], 1):
        title = ann.get('title', '')
        date = ann.get('date', '')[:10]
        importance = ann.get('importance', 'routine')
        importance_tag = ann.get('importance_tag', '')

        part = f"【公告{i}】[{importance.upper()}] {importance_tag}\n"
        part += f"日期: {date}\n"
        part += f"标题: {title}\n"

        content = ann.get('extracted_content', {})
        if isinstance(content, dict) and not content.get('error'):
            facts = content.get('key_facts', [])
            if facts:
                part += f"关键事实: {'; '.join(facts[:5])}\n"
            preview = content.get('full_text_preview', '')
            if preview:
                part += f"正文摘要: {preview[:max_text_per_ann]}\n"
        else:
            raw_content = ann.get('content', '')
            if raw_content:
                part += f"正文摘要: {raw_content[:max_text_per_ann]}\n"

        deep = ann.get('deep_analysis', {})
        if isinstance(deep, dict) and deep.get('facts'):
            part += f"深度提取: {'; '.join(deep['facts'][:3])}\n"
            if deep.get('nature'):
                part += f"性质判断: {deep['nature']}\n"

        evidence_parts.append(part)

    return '\n'.join(evidence_parts)


def _build_event_chains_evidence(event_chains):
    """构建事件溯源链证据"""
    if not event_chains:
        return ""

    parts = []
    for tag, chain in event_chains.items():
        chain_anns = chain.get('chain', [])
        origin = chain.get('origin')
        part = f"【溯源链: {tag}】共{len(chain_anns)}条关联公告\n"
        if origin:
            part += f"源头: [{origin.get('date','')[:10]}] {origin.get('title','')}\n"
        for a in chain_anns[:5]:
            part += f"  - [{a.get('date','')[:10]}] {a.get('title','')}\n"
        parts.append(part)

    return '\n'.join(parts)


def batch_analyze_announcements(
    announcements_data: Dict,
    company_name: str = "",
    stock_code: str = ""
) -> Dict[str, Any]:
    """
    一次性分析所有公告，输出多维度解读

    Args:
        announcements_data: fetch_announcements()的完整返回结果
        company_name: 公司名称
        stock_code: 股票代码

    Returns:
        {
            "per_announcement": [
                {
                    "title": str,
                    "date": str,
                    "category": str,
                    "importance": str,
                    "summary": str,
                    "impact_analysis": str,
                    "risk_factors": [str],
                    "nature": str,
                },
                ...
            ],
            "narrative": str,         # 公司全景叙事（2000-4000字）
            "risk_summary": str,       # 风险摘要（200-400字）
            "key_insights": [str],     # 核心洞察（3-5条）
            "trend_analysis": str,     # 趋势分析（200-400字）
        }
    """
    result = {
        "per_announcement": [],
        "narrative": "",
        "risk_summary": "",
        "key_insights": [],
        "trend_analysis": "",
    }

    critical = announcements_data.get('critical_announcements', [])
    major = announcements_data.get('major_announcements', [])
    all_important = critical + major

    if not all_important:
        return result

    evidence = _build_announcement_evidence(all_important, max_anns=20)
    chains_evidence = _build_event_chains_evidence(
        announcements_data.get('event_chains', {})
    )

    stats = announcements_data.get('importance_stats', {})
    total_count = announcements_data.get('count', 0)

    ann_list_str = ""
    for i, ann in enumerate(all_important[:20], 1):
        ann_list_str += f"{i}. [{ann.get('importance','').upper()}] {ann.get('date','')[:10]} | {ann.get('title','')[:80]}\n"

    prompt = f"""你是顶级券商首席分析师。以下是{company_name}（{stock_code}）的公告数据（共{total_count}条，其中CRITICAL {stats.get('critical',0)}条、MAJOR {stats.get('major',0)}条）。
请一次性完成以下3项分析任务：

===== 任务1：逐条公告分析 =====
对以下每条重要公告进行独立分析：

{ann_list_str}

每条公告请输出：分类、摘要（50字内）、影响分析（100字内）、风险因素、性质（利好/利空/中性）

===== 任务2：公司全景叙事 =====
基于全部公告证据，写一篇连贯的公司情况叙述报告（2000-4000字）。
要求：按时间线和逻辑线交织叙述，涵盖控制权变化、重大资产重组、财务异常信号、法律诉讼风险、资金担保动向。
每个重要结论引用具体公告证据（日期+公告标题）。用Markdown格式。

===== 任务3：趋势与风险 =====
基于公告数据，分析公司近期发展趋势（200-400字）和风险摘要（200-400字），
并提炼3-5条核心投资洞察。

===== 公告证据 =====
{evidence}
===== 证据结束 =====

{f'''===== 事件溯源链 =====
{chains_evidence}
===== 溯源链结束 =====
''' if chains_evidence else ''}

请以JSON格式输出（不要输出其他内容）：
{{
  "per_announcement": [
    {{
      "title": "公告标题",
      "date": "日期",
      "category": "分类（业绩报告/收购兼并/诉讼仲裁等）",
      "importance": "critical|major",
      "summary": "摘要（50字内）",
      "impact_analysis": "影响分析（100字内）",
      "risk_factors": ["风险1", "风险2"],
      "nature": "利好|利空|中性"
    }}
  ],
  "narrative": "公司全景叙述报告（Markdown格式，2000-4000字）",
  "risk_summary": "风险摘要（200-400字）",
  "key_insights": ["洞察1", "洞察2", "洞察3"],
  "trend_analysis": "趋势分析（200-400字）"
}}"""

    try:
        from scripts.llm_config import LLM_CONFIG
        from openai import OpenAI
        client = OpenAI(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
        )
        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=[
                {"role": "system", "content": "你是一位顶级券商首席分析师，擅长基于原始公告证据进行深度分析。输出必须是合法JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=8192,
            stream=False
        )
        raw = response.choices[0].message.content

        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            data = json.loads(json_match.group())

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

        matched_count = len(result['per_announcement'])
        print(f"  [AI批量公告分析] 成功: {matched_count}/{len(all_important)}条公告分析 + 叙事 + 风险 + 趋势")

    except Exception as e:
        print(f"  [AI批量公告分析] LLM调用失败: {e}，降级为规则分析")
        result = _fallback_analysis(all_important, announcements_data)

    return result


def _fallback_analysis(announcements, announcements_data):
    """LLM调用失败时的降级方案"""
    result = {
        "per_announcement": [],
        "narrative": "",
        "risk_summary": "",
        "key_insights": [],
        "trend_analysis": "",
    }

    for ann in announcements:
        title = ann.get('title', '')
        date = ann.get('date', '')[:10]
        importance = ann.get('importance', 'routine')
        importance_tag = ann.get('importance_tag', '')

        category = importance_tag or '其他'
        nature = '中性'
        risk_factors = []

        bullish_tags = ['收购', '回购', '增持', '分红', '股权激励', '重大合同', '中标']
        bearish_tags = ['诉讼', '仲裁', '减持', '处罚', '退市', 'ST', '风险', '违规', '问询']
        for tag in bullish_tags:
            if tag in title or tag in importance_tag:
                nature = '利好'
                break
        for tag in bearish_tags:
            if tag in title or tag in importance_tag:
                nature = '利空'
                risk_factors.append(f"{title[:30]}存在{tag}风险")
                break

        result['per_announcement'].append({
            "title": title,
            "date": date,
            "category": category,
            "importance": importance,
            "summary": f"{date}发布{category}公告",
            "impact_analysis": f"需结合完整公告内容评估{category}的具体影响",
            "risk_factors": risk_factors,
            "nature": nature,
        })

    critical_count = sum(1 for a in announcements if a.get('importance') == 'critical')
    major_count = sum(1 for a in announcements if a.get('importance') == 'major')
    bearish_count = sum(1 for a in result['per_announcement'] if a.get('nature') == '利空')

    result['risk_summary'] = (
        f"共{len(announcements)}条重要公告，其中CRITICAL {critical_count}条、MAJOR {major_count}条。"
        f"利空公告{bearish_count}条。"
    )

    if bearish_count > 0:
        result['key_insights'] = [f"存在{bearish_count}条利空性质公告，需重点关注"]
    else:
        result['key_insights'] = ["重要公告中未发现明显利空信号"]

    return result


def apply_batch_results_to_announcements(announcements_data, batch_result):
    """
    将批量分析结果写回公告数据结构，保持与原有逐条分析的兼容性

    Args:
        announcements_data: 原始公告数据（会被原地修改）
        batch_result: batch_analyze_announcements()的返回结果

    Returns:
        更新后的公告数据
    """
    per_ann = batch_result.get('per_announcement', [])
    if not per_ann:
        return announcements_data

    critical = announcements_data.get('critical_announcements', [])
    major = announcements_data.get('major_announcements', [])
    all_important = critical + major

    ann_map = {}
    for ann in all_important:
        key = (ann.get('date', '')[:10], ann.get('title', '')[:30])
        ann_map[key] = ann

    matched = 0
    for analysis in per_ann:
        a_title = analysis.get('title', '')
        a_date = analysis.get('date', '')[:10]

        matched_ann = None
        for ann in all_important:
            if a_title and a_title[:20] in ann.get('title', ''):
                matched_ann = ann
                break
            if a_date and a_date == ann.get('date', '')[:10] and a_title[:10] in ann.get('title', ''):
                matched_ann = ann
                break

        if matched_ann:
            matched_ann['ai_analysis'] = {
                'category': analysis.get('category', ''),
                'summary': analysis.get('summary', ''),
                'impact_analysis': analysis.get('impact_analysis', ''),
                'key_points': analysis.get('key_points', []),
                'risk_factors': analysis.get('risk_factors', []),
                'nature': analysis.get('nature', '中性'),
            }
            matched += 1

    announcements_data['_batch_analysis'] = {
        'narrative': batch_result.get('narrative', ''),
        'risk_summary': batch_result.get('risk_summary', ''),
        'key_insights': batch_result.get('key_insights', []),
        'trend_analysis': batch_result.get('trend_analysis', ''),
        'matched_count': matched,
        'total_analyzed': len(per_ann),
    }

    print(f"  [批量结果回写] 匹配写入 {matched}/{len(per_ann)} 条公告")
    return announcements_data


def get_narrative_from_batch(announcements_data):
    """从公告数据中提取批量分析的叙事结果"""
    batch = announcements_data.get('_batch_analysis', {})
    return batch.get('narrative', '')
