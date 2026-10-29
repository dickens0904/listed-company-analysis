# -*- coding: utf-8 -*-
"""
模块3：高管的动态分析
辞职/新任/薪酬方案/股权激励调整
"""
import sys, json, requests, re, time
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

def fetch_executives(stock_code, market='a', data_dir=None):
    """从公告列表中识别高管变动"""
    result = {
        'stock_code': stock_code,
        'changes': [],
        'equity_incentives': [],
        'summary': {},
    }

    # 北交所迁码（2026-10-21）：老代码需先迁到 920xxx 才能命中东财公告
    _code = stock_code
    if str(stock_code).startswith(('8', '4')) and not str(stock_code).startswith('920'):
        try:
            from bse_migrate import resolve_bse_code
            _m = resolve_bse_code(stock_code)
            if _m.get('switched') and _m.get('current_code'):
                _code = _m['current_code']
        except Exception:
            pass

    # 从东方财富公告中识别高管变动
    url = (f"https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?cb=&sr=-1&page_size=200&page_index=1&ann_type=A"
           f"&client_source=web&f_node=0&s_node=0&stock_list={_code}")
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

    changes = []
    incentives = []

    # 高管变动关键词
    exec_keywords = ['董事长', '副董事长', '总裁', '总经理', '副总经理',
                      '董事', '监事', '独立董事', '财务总监', '董事会秘书',
                      '辞职', '离任', '新任', '选举', '聘用', '任命',
                      '副总裁', '首席', 'COO', 'CFO', '董秘']

    # 股权激励关键词
    incentive_keywords = ['股权激励', '限制性股票', '股票期权', '员工持股',
                          '行权', '授予', '注销', '回购', '行权价格',
                          '解锁', '归属', 'ESOP']

    for item in items:
        title = item.get('title', '') or item.get('title_ch', '')
        notice_date = item.get('notice_date', '')[:10]
        columns = [c.get('column_name', '') for c in item.get('columns', [])]
        col_str = '|'.join(columns)

        # 高管变动
        is_exec = any(k in title for k in exec_keywords)
        is_incentive = any(k in title for k in incentive_keywords)
        is_egm = '临时股东会' in title or '股东大会' in title

        if is_exec or ('股东大会' in col_str and is_egm):
            changes.append({
                'date': notice_date,
                'title': title,
                'categories': col_str,
                'art_code': item.get('art_code', ''),
                'type': _classify_exec_change(title),
            })

        if is_incentive:
            incentives.append({
                'date': notice_date,
                'title': title,
                'art_code': item.get('art_code', ''),
                'type': _classify_incentive(title),
            })

    # 汇总
    result['changes'] = changes
    result['equity_incentives'] = incentives
    result['change_count'] = len(changes)
    result['summary'] = _summarize_exec(changes, incentives)

    if market not in ('a', 'bse', 'cn'):
        result['_gap'] = ('高管变动明细：港美股需港交所权益披露 / SEC 8-K 或 DEF 14A 解析；'
                          '本 skill 暂无脚本源，禁止编造任免事项')
    return result


def _classify_exec_change(title):
    """分类高管变动类型"""
    if '辞职' in title or '离任' in title:
        return '辞职/离职'
    elif '新任' in title or '选举' in title:
        return '新任/补选'
    elif '变更' in title:
        return '变更'
    elif '选举' in title:
        return '换届选举'
    else:
        return '其他'


def _classify_incentive(title):
    """分类股权激励类型"""
    if '注销' in title:
        return '注销/取消'
    elif '回购' in title:
        return '回购'
    elif '授予' in title:
        return '授予'
    elif '行权' in title:
        return '行权'
    elif '激励计划' in title:
        return '新计划'
    else:
        return '其他'


def _summarize_exec(changes, incentives):
    """高管动态摘要"""
    summary = {
        'total_changes': len(changes),
        'resignations': [c for c in changes if c['type'] == '辞职/离职'],
        'new_appointments': [c for c in changes if c['type'] in ('新任/补选', '变更')],
        'total_incentives': len(incentives),
        'incentive_cancellations': [i for i in incentives if i['type'] == '注销/取消'],
        'latest_change': changes[0] if changes else None,
    }

    # 危险信号识别
    warnings = []
    if any('董事长' in c['title'] and '辞职' in c['title'] for c in changes):
        warnings.append("⚠️ 董事长辞职（需关注原因）")
    if any('总裁' in c['title'] and '辞职' in c['title'] for c in changes):
        warnings.append("⚠️ 总裁辞职（需关注原因）")
    if any(i['type'] == '注销/取消' for i in incentives):
        warnings.append("⚠️ 股权激励注销（可能损害员工积极性）")
    if summary['total_changes'] >= 5:
        warnings.append("⚠️ 高管变动频繁")

    summary['warnings'] = warnings
    return summary


if __name__ == '__main__':
    result = fetch_executives('002180')
    print(f"高管变动: {result['change_count']}条")
    print(f"股权激励: {result['summary']['total_incentives']}条")
    for c in result['changes'][:5]:
        print(f"  {c['date']} [{c['type']}] {c['title'][:60]}")


def _generate_executive_ai_narrative(data):
    """生成高管动态AI综合解读"""
    changes = data.get('changes', [])
    incentives = data.get('equity_incentives', [])
    summary = data.get('summary', {})

    if not changes and not incentives:
        return ""

    evidence_parts = []
    evidence_parts.append(f"高管变动总数: {len(changes)}条")

    type_counts = {}
    for c in changes:
        t = c.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    evidence_parts.append(f"变动类型分布: {type_counts}")

    for c in changes[:10]:
        evidence_parts.append(f"{c.get('date', '')[:10]} [{c.get('type', '')}] {c.get('title', '')[:60]}")

    if incentives:
        evidence_parts.append(f"\n股权激励事项: {len(incentives)}条")
        for i in incentives[:5]:
            evidence_parts.append(f"{i.get('date', '')[:10]} [{i.get('type', '')}] {i.get('title', '')[:60]}")

    if summary.get('warnings'):
        evidence_parts.append(f"\n风险提示: {'; '.join(summary['warnings'][:3])}")

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司高管变动数据，请写一段专业的高管动态分析（200-400字）。

要求：
1. 分析高管变动频率和类型（辞职/聘任/换届）
2. 评估变动对公司治理的影响
3. 关注是否存在异常信号（如集中辞职、核心高管离职）
4. 如有股权激励，分析激励力度和覆盖面
5. 语言专业、客观

===== 高管数据 =====
{evidence_block}
===== 数据结束 =====

请输出高管动态分析："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券商公司治理分析师，擅长解读上市公司高管变动背后的信号。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [高管AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建高管变动证据块"""
    changes = data.get('changes', [])
    incentives = data.get('equity_incentives', [])
    summary = data.get('summary', {})
    tdx_execs = data.get('tdx_executives', [])
    if not changes and not incentives and not tdx_execs:
        return ""
    parts = [f"高管变动总数: {len(changes)}条"]
    type_counts = {}
    for c in changes:
        t = c.get('type', '其他')
        type_counts[t] = type_counts.get(t, 0) + 1
    parts.append(f"变动类型分布: {type_counts}")
    for c in changes[:10]:
        parts.append(f"{c.get('date', '')[:10]} [{c.get('type', '')}] {c.get('title', '')[:60]}")
    if incentives:
        parts.append(f"股权激励事项: {len(incentives)}条")
        for i in incentives[:5]:
            parts.append(f"{i.get('date', '')[:10]} [{i.get('type', '')}] {i.get('title', '')[:60]}")
    if summary.get('warnings'):
        parts.append(f"风险提示: {'; '.join(summary['warnings'][:3])}")
    # 通达信高管增强数据
    if tdx_execs:
        parts.append(f"\n【通达信高管数据】核心管理团队 {len(tdx_execs)} 人:")
        for ex in tdx_execs[:12]:
            name = ex.get('name', '')
            pos = ex.get('position', '')
            salary = ex.get('salary', '')
            shares = ex.get('shares_held_total', '')
            edu = ex.get('education', '')
            salary_str = f'薪酬{salary}万' if salary not in ['', None] else ''
            shares_str = f'持股{shares}股' if shares not in ['', None] else ''
            edu_str = f'学历{edu}' if edu else ''
            parts.append(f"  {name}（{pos}）{salary_str} {shares_str} {edu_str}")
    return '\n'.join(parts)


def generate_report_section(data: dict, batch_analysis=None) -> list:
    lines = []
    lines.append("## 高管动态")
    lines.append("")

    changes = data.get('changes', [])
    summary = data.get('summary', {})

    lines.append(f"**高管变动总数**: {len(changes)}条")
    lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('executives'):
        ai_narrative = batch_analysis['executives']
    else:
        ai_narrative = _generate_executive_ai_narrative(data)

    if ai_narrative:
        lines.append("### 🤖 AI高管动态分析")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    if summary.get('warnings'):
        lines.append("### ⚠️ 风险提示")
        lines.append("")
        for w in summary['warnings']:
            lines.append(f"- {w}")
        lines.append("")

    if changes:
        lines.append("### 变动明细")
        lines.append("")
        lines.append('<table class="exec-table"><thead><tr><th>日期</th><th>类型</th><th>详情</th></tr></thead><tbody>')
        for c in changes[:15]:
            lines.append(f'<tr><td>{c.get("date","")[:10]}</td><td>{c.get("type","")}</td><td>{c.get("title","")[:60]}</td></tr>')
        lines.append('</tbody></table>')
        lines.append("")

    incentives = data.get('equity_incentives', [])
    if incentives:
        lines.append("### 股权激励事项")
        lines.append("")
        lines.append('<table class="exec-table"><thead><tr><th>日期</th><th>类型</th><th>详情</th></tr></thead><tbody>')
        for i in incentives[:10]:
            lines.append(f'<tr><td>{i.get("date","")[:10]}</td><td>{i.get("type","")}</td><td>{i.get("title","")[:60]}</td></tr>')
        lines.append('</tbody></table>')
        lines.append("")

    # 通达信高管增强数据
    tdx_execs = data.get('tdx_executives', [])
    if tdx_execs:
        lines.append("### 核心管理团队（通达信）")
        lines.append("")
        lines.append("| 姓名 | 职务 | 任职日期 | 性别 | 学历 | 年龄 | 薪酬(万元) | 持股(股) |")
        lines.append("|------|------|---------|------|------|------|-----------|---------|")
        for ex in tdx_execs[:15]:
            name = ex.get('name', '')
            pos = ex.get('position', '')
            start = ex.get('start_date', '')
            gender = ex.get('gender', '')
            edu = ex.get('education', '')
            age = ex.get('age', '')
            salary = ex.get('salary', '')
            shares = ex.get('shares_held_total', '')
            salary_str = str(salary) if salary not in ['', None] else '-'
            shares_str = str(shares) if shares not in ['', None] else '-'
            lines.append(f'| {name} | {pos} | {start} | {gender} | {edu} | {age} | {salary_str} | {shares_str} |')
        if len(tdx_execs) > 15:
            lines.append(f'| 其他 {len(tdx_execs) - 15} 人 | ... | ... | ... | ... | ... | ... | ... |')
        lines.append("")
        lines.append(f'*数据来源：通达信官方数据接口（TDX API），共 {len(tdx_execs)} 人*')
        lines.append("")

    return lines
