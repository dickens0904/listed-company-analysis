# -*- coding: utf-8 -*-
"""
模块7：监管历史追溯
问询函/处罚/核查意见/监管措施
"""
import sys, json, requests, re, time
sys.stdout.reconfigure(encoding='utf-8')

def fetch_regulatory_history(stock_code, market='a', data_dir=None):
    """追溯监管历史"""
    result = {'stock_code': stock_code, 'records': [], 'count': 0, 'summary': {}}

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

    reg_keywords = [
        '问询函', '监管函', '关注函', '核查意见',
        '警示函', '行政处罚', '立案', '整改',
        '自律监管', '公开谴责', '通报批评',
        '非标准审计报告', '审计问题', '保留意见',
        '强调事项', '持续经营', '内部控制',
    ]

    records = []
    for item in items:
        title = item.get('title', '') or item.get('title_ch', '')
        notice_date = item.get('notice_date', '')[:10]
        art_code = item.get('art_code', '')
        columns = [c.get('column_name', '') for c in item.get('columns', [])]
        col_str = '|'.join(columns)

        is_reg = any(k in title for k in reg_keywords)
        is_reg_cat = any(c in col_str for c in ['监管', '核查', '问询', '核查意见'])

        if is_reg or is_reg_cat:
            records.append({
                'date': notice_date,
                'title': title,
                'art_code': art_code,
                'category': col_str,
                'severity': _assess_severity(title, col_str),
                'type': _classify_reg(title, col_str),
            })

    result['records'] = records
    result['count'] = len(records)
    result['summary'] = _summarize_reg(records)

    return result


def _classify_reg(title, category):
    """分类监管类型"""
    if '问询函' in title or '问询' in category:
        return '问询函'
    elif '关注函' in title:
        return '关注函'
    elif '核查意见' in title or '核查意见' in category:
        return '保荐机构核查意见'
    elif '行政处罚' in title:
        return '行政处罚'
    elif '警示' in title:
        return '警示函'
    elif '立案' in title:
        return '立案调查'
    elif '公开谴责' in title:
        return '公开谴责'
    elif '非标准' in title or '非标' in title:
        return '非标准审计意见'
    elif '强调事项' in title:
        return '强调事项'
    else:
        return '其他监管事项'


def _assess_severity(title, category):
    """评估监管事项严重程度"""
    if any(k in title for k in ['行政处罚', '立案', '公开谴责']):
        return '🔴 严重'
    elif any(k in title for k in ['问询函']):
        return '🟡 中等'
    elif any(k in title for k in ['关注函', '警示', '核查意见']):
        return '🟡 中等'
    elif any(k in title for k in ['非标准', '保留意见', '强调事项', '持续经营']):
        return '🔴 财务风险'
    else:
        return '🟢 轻微'


def _summarize_reg(records):
    summary = {
        'total': len(records),
        'by_severity': {},
        'by_type': {},
        'latest': records[0] if records else None,
    }
    for r in records:
        summary['by_severity'][r['severity']] = \
            summary['by_severity'].get(r['severity'], 0) + 1
        summary['by_type'][r['type']] = \
            summary['by_type'].get(r['type'], 0) + 1
    return summary


if __name__ == '__main__':
    result = fetch_regulatory_history('002180')
    print(f"监管记录: {result['count']}条")
    for r in result['records']:
        print(f"  {r['date']} [{r['severity']}] {r['title'][:60]}")


def _generate_regulatory_ai_narrative(data):
    """生成监管合规AI综合解读"""
    records = data.get('records', [])
    if not records:
        return ""

    summary = data.get('summary', {})

    evidence_parts = []
    evidence_parts.append(f"监管记录总数: {len(records)}条")

    if summary.get('by_severity'):
        evidence_parts.append(f"严重程度分布: {summary['by_severity']}")
    if summary.get('by_type'):
        evidence_parts.append(f"监管类型分布: {summary['by_type']}")

    severe = [r for r in records if '严重' in r.get('severity', '') or '风险' in r.get('severity', '')]
    if severe:
        evidence_parts.append(f"严重/高风险事项: {len(severe)}条")
        for r in severe[:5]:
            evidence_parts.append(f"  {r.get('date', '')} [{r.get('severity', '')}] {r.get('title', '')[:60]}")

    for r in records[:10]:
        evidence_parts.append(f"{r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:60]}")

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司的监管记录数据，请写一段专业的监管合规分析（200-400字）。

要求：
1. 评估监管风险的整体水平和趋势
2. 分析主要监管事项的性质和影响
3. 关注严重/高风险事项的具体内容
4. 评估合规治理的整体状况
5. 提出投资者应关注的合规风险点

{evidence_block}

请输出监管合规分析："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券互联网合规分析师，擅长解读上市公司监管记录和合规风险。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [监管AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建监管数据证据块"""
    records = data.get('records', [])
    if not records:
        return ""
    summary = data.get('summary', {})
    parts = [f"监管记录总数: {len(records)}条"]
    if summary.get('by_severity'):
        parts.append(f"严重程度分布: {summary['by_severity']}")
    if summary.get('by_type'):
        parts.append(f"监管类型分布: {summary['by_type']}")
    severe = [r for r in records if '严重' in r.get('severity', '') or '风险' in r.get('severity', '')]
    if severe:
        parts.append(f"严重/高风险事项: {len(severe)}条")
        for r in severe[:5]:
            parts.append(f"  {r.get('date', '')} [{r.get('severity', '')}] {r.get('title', '')[:60]}")
    for r in records[:10]:
        parts.append(f"{r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:60]}")
    return '\n'.join(parts)


def generate_report_section(data: dict, batch_analysis=None) -> list:
    lines = []
    lines.append("## 监管历史追溯")
    lines.append("")
    lines.append(f"**监管记录总数**: {data.get('count', 0)}条")
    lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('regulatory'):
        ai_narrative = batch_analysis['regulatory']
    else:
        ai_narrative = _generate_regulatory_ai_narrative(data)

    if ai_narrative:
        lines.append("### 🤖 AI监管合规分析")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    summary = data.get('summary', {})
    if summary.get('by_severity'):
        lines.append("**严重程度分布**:")
        for sev, cnt in summary['by_severity'].items():
            lines.append(f"- {sev}: {cnt}条")
        lines.append("")

    records = data.get('records', [])
    if records:
        lines.append("**监管记录明细**:")
        for r in records[:20]:
            lines.append(f"- **{r.get('date','')}** {r.get('severity','')} [{r.get('type','')}] {r.get('title','')[:70]}")
        lines.append("")

    return lines
