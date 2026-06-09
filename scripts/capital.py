# -*- coding: utf-8 -*-
"""
模块4：资金动作分析
募资变更/套期保值/补充流动资金/银行授信
"""
import sys, json, requests, re, time
sys.stdout.reconfigure(encoding='utf-8')

def fetch_capital_actions(stock_code, market='a', data_dir=None):
    """从公告列表识别资金动作"""
    result = {'stock_code': stock_code, 'actions': [], 'count': 0, 'risks': []}

    url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?cb=&sr=-1&page_size=200&page_index=1&ann_type=A"
           f"&client_source=web&f_node=0&s_node=0&stock_list={stock_code}")
    try:
        r = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://data.eastmoney.com/'
        }, timeout=20)
        r.encoding = 'utf-8'
        data = r.json()
        items = data.get('data', {}).get('list', [])
    except:
        items = []

    capital_keywords = [
        '套期保值', '衍生品', '金融工具', '外汇', '汇率对冲',
        '募集资金', '募投', '超募', '补充流动资金', '永久补流',
        '闲置募集资金', '现金管理', '理财产品',
        '银行授信', '借款', '贷款', '融资', '担保',
        '股份回购', '增持', '减持', '回购',
        '定向增发', '配股', '可转债', '可交债',
    ]

    actions = []
    for item in items:
        title = item.get('title', '') or item.get('title_ch', '')
        notice_date = item.get('notice_date', '')[:10]
        art_code = item.get('art_code', '')

        matched = [k for k in capital_keywords if k in title]
        if matched:
            action = {
                'date': notice_date,
                'title': title,
                'art_code': art_code,
                'matched_keywords': matched,
                'type': _classify_capital(title),
                'risk_signal': _assess_capital_risk(title, matched),
            }
            actions.append(action)

    result['actions'] = actions
    result['count'] = len(actions)
    result['risks'] = [a for a in actions if a['risk_signal']]
    result['summary'] = _summarize_capital(actions)

    return result


def _classify_capital(title):
    """分类资金动作类型"""
    if '套期保值' in title or '衍生品' in title:
        return '金融衍生品/套保'
    elif '募集资金' in title or '募投' in title:
        return '募集资金使用'
    elif '补充流动资金' in title or '补流' in title:
        return '补充流动资金'
    elif '闲置' in title or '现金管理' in title or '理财' in title:
        return '闲置资金管理'
    elif '银行授信' in title or '借款' in title or '贷款' in title:
        return '银行借款/授信'
    elif '担保' in title:
        return '对外担保'
    elif '回购' in title and '增持' not in title:
        return '股份回购'
    elif '增持' in title:
        return '股东增持'
    elif '减持' in title:
        return '股东减持'
    elif '增发' in title or '配股' in title:
        return '再融资'
    else:
        return '其他'


def _assess_capital_risk(title, matched):
    """识别资金动作风险信号"""
    if '套期保值' in matched:
        # 套保可能掩盖真实的投机行为
        return "套保业务规模需关注（是否有投机嫌疑）"
    if '补充流动资金' in matched:
        return "⚠️ 募集资金永久补流→流动性紧张信号"
    if '减持' in matched:
        return "⚠️ 重要股东减持→可能信心不足"
    if '借款' in matched and '担保' not in matched:
        return "银行借款增加→负债率上升"
    if '可转债' in matched or '可交债' in matched:
        return "发行可转债/可交债→转股前稀释，需关注转股压力"
    return None


def _summarize_capital(actions):
    """资金动作摘要"""
    summary = {
        'derivative_count': len([a for a in actions if a['type'] == '金融衍生品/套保']),
        'refinancing_count': len([a for a in actions if a['type'] == '再融资']),
        'share_reduction_count': len([a for a in actions if a['type'] == '股东减持']),
        'latest': actions[0] if actions else None,
    }
    return summary


if __name__ == '__main__':
    result = fetch_capital_actions('002180')
    print(f"资金动作: {result['count']}项")
    for a in result['actions'][:10]:
        print(f"  {a['date']} [{a['type']}] {a['title'][:60]}")


def _generate_capital_ai_narrative(data):
    """生成资金动作AI综合解读"""
    actions = data.get('actions', [])
    if not actions:
        return ""

    evidence_parts = []
    evidence_parts.append(f"资金动作总数: {data.get('count', 0)}项")

    type_counts = {}
    for a in actions:
        t = a.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    evidence_parts.append(f"动作类型分布: {type_counts}")

    risk_actions = [a for a in actions if a.get('risk_signal')]
    if risk_actions:
        evidence_parts.append(f"风险信号动作: {len(risk_actions)}项")
        for a in risk_actions[:5]:
            evidence_parts.append(f"  {a.get('date', '')[:10]} [{a.get('type', '')}] {a.get('risk_signal', '')}")

    for a in actions[:10]:
        evidence_parts.append(f"{a.get('date', '')[:10]} [{a.get('type', '')}] {a.get('title', '')[:60]}")

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司资金动作数据，请写一段专业的资金动作分析（200-400字）。

要求：
1. 分析资金动作类型分布（回购/增持/减持/质押等）
2. 评估资金动作的意图和影响
3. 关注风险信号（减持、质押、募资变更等）
4. 分析资金动作频率和趋势
5. 语言专业、客观

===== 资金数据 =====
{evidence_block}
===== 数据结束 =====

请输出资金动作分析："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券商资金分析师，擅长解读上市公司资金动作背后的意图和风险。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [资金AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建资金动作证据块"""
    actions = data.get('actions', [])
    if not actions:
        return ""
    parts = [f"资金动作总数: {data.get('count', 0)}项"]
    type_counts = {}
    for a in actions:
        t = a.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    parts.append(f"动作类型分布: {type_counts}")
    risk_actions = [a for a in actions if a.get('risk_signal')]
    if risk_actions:
        parts.append(f"风险信号动作: {len(risk_actions)}项")
        for a in risk_actions[:5]:
            parts.append(f"  {a.get('date', '')[:10]} [{a.get('type', '')}] {a.get('risk_signal', '')}")
    for a in actions[:10]:
        parts.append(f"{a.get('date', '')[:10]} [{a.get('type', '')}] {a.get('title', '')[:60]}")
    return '\n'.join(parts)


def generate_report_section(data, batch_analysis=None):
    lines = []
    lines.append("## 资金动作分析")
    lines.append("")
    lines.append(f"**资金动作总数**: {data.get('count', 0)}项")
    lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('capital'):
        ai_narrative = batch_analysis['capital']
    else:
        ai_narrative = _generate_capital_ai_narrative(data)

    if ai_narrative:
        lines.append("### 🤖 AI资金动作分析")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    actions = data.get('actions', [])
    if actions:
        lines.append("### 动作明细")
        lines.append("")
        lines.append('<table class="capital-table"><thead><tr><th>日期</th><th>类型</th><th>详情</th><th>风险信号</th></tr></thead><tbody>')
        for a in actions[:20]:
            risk = a.get('risk_signal', '')
            lines.append(f'<tr><td>{a.get("date","")[:10]}</td><td>{a.get("type","")}</td><td>{a.get("title","")[:50]}</td><td>{risk}</td></tr>')
        lines.append('</tbody></table>')
        lines.append("")

    return lines
