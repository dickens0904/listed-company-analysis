# -*- coding: utf-8 -*-
"""
投资者问答与互动分析模块
数据源: 东方财富 announcements.py 的原始数据（通过 column_code 过滤）
column_code 说明:
  001003001001003 = 投资者关系活动
  001003001001004 = 公司调研
  001002005001002 = 其他（路演等）

功能:
  1. 从 announcements 原始数据中分离 IR 活动（调研/路演/业绩说明）
  2. 统计机构关注度（近12月调研次数、参与机构数）
  3. 生成投资者互动摘要
  4. 标记高信息量公告（业绩说明会/调研活动）
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8")


def fetch_investor_qa(stock_code, market="a", data_dir=None, raw_announcements=None):
    """
    主函数：投资者互动分析

    raw_announcements: 可选，来自 announcements.py 的原始公告列表。
                       如未提供则返回"请先运行公告采集"提示。
    """
    result = {
        "stock_code": stock_code,
        "ir_activities": [],
        "survey_records": [],
        "roadshow_records": [],
        "summary": {},
        "risks": [],
        "warnings": [],
        "note": "",
    }

    if raw_announcements is None:
        result["warnings"].append("请先运行公告采集模块（announcements）以获取原始数据")
        return result

    all_anns = raw_announcements if isinstance(raw_announcements, list) else []

    # column_code 映射（东方财富 announcements 里的分类编码）
    IR_ACTIVITY_CODES = {
        "001003001001003": "投资者关系活动",
        "001003001001004": "公司调研",
        "001002005001002": "路演/其他IR",
    }

    # 标题关键词匹配（当 column_code 不可用时的降级方案）
    SURVEY_KEYWORDS = ["调研", "接待", "投资者关系活动记录表", "机构调研", "投资者关系管理信息"]
    ROADSHOW_KEYWORDS = ["路演", "业绩说明会", "业绩发布会", "投资者交流会"]
    IR_KEYWORDS = ["投资者关系", "投资者开放日", "投资者接待"]

    def _match_by_title(title):
        """通过标题关键词判断类型"""
        for kw in SURVEY_KEYWORDS:
            if kw in title:
                return "survey"
        for kw in ROADSHOW_KEYWORDS:
            if kw in title:
                return "roadshow"
        for kw in IR_KEYWORDS:
            if kw in title:
                return "ir"
        return None

    # 分类
    ir_activities = []
    survey_records = []
    roadshow_records = []

    for ann in all_anns:
        title = ann.get("title", "")
        cols = ann.get("columns", [])
        codes = {c.get("column_code", ""): c.get("column_name", "") for c in cols} if cols else {}

        # 优先用 column_code，不可用时降级为标题关键词
        has_column_code = bool(cols)
        if has_column_code:
            is_ir = any(code in IR_ACTIVITY_CODES for code in codes)
            is_survey = "001003001001004" in codes
            is_roadshow = "001002005001002" in codes
        else:
            match_type = _match_by_title(title)
            is_survey = match_type == "survey"
            is_roadshow = match_type == "roadshow"
            is_ir = match_type in ("ir", "survey", "roadshow")

        if is_ir:
            ir_activities.append(_build_ir_record(ann, codes))

        if is_survey:
            survey_records.append(_build_survey_record(ann))

        if is_roadshow:
            roadshow_records.append(_build_roadshow_record(ann))

    result["ir_activities"] = ir_activities
    result["survey_records"] = survey_records
    result["roadshow_records"] = roadshow_records

    # 机构关注度统计
    result["summary"] = _build_summary(survey_records, ir_activities, roadshow_records)

    # 保存
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "investor_qa.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    return result


def _build_ir_record(ann, codes):
    """构建IR活动记录"""
    title = ann.get("title", "")
    notice_date = ann.get("notice_date", ann.get("announcementTime", ann.get("date", "")))[:10]

    # 识别活动类型
    activity_type = codes.get("001003001001003") or codes.get("001003001001004") or codes.get("001002005001002") or "IR活动"

    # 判断是调研还是路演还是业绩说明
    if "调研" in title or "公司调研" in activity_type:
        activity_type = "机构调研"
    elif "业绩" in title or "说明会" in title or "路演" in title:
        activity_type = "业绩说明会/路演"
    elif "IR" in title or "投资者" in title:
        activity_type = "投资者关系活动"
    else:
        activity_type = "IR活动"

    return {
        "date": notice_date,
        "title": title,
        "type": activity_type,
        "art_code": ann.get("art_code", ""),
        "source": ann.get("source", "东方财富"),
        "column_name": "/".join(codes.values()),
    }


def _build_survey_record(ann):
    """构建调研记录（格式与机构调研一致）"""
    title = ann.get("title", "")
    notice_date = ann.get("notice_date", ann.get("announcementTime", ann.get("date", "")))[:10]

    # 尝试从标题提取参与机构
    # 常见格式: "XXX:关于XXX接待机构投资者调研活动的公告"
    orgs = _extract_institutions(title)
    theme = _extract_theme(title)

    return {
        "date": notice_date,
        "organizers": orgs or "机构投资者",
        "participants": "",
        "theme": theme or "机构调研",
        "title": title,
        "art_code": ann.get("art_code", ""),
    }


def _build_roadshow_record(ann):
    """构建路演/业绩说明记录"""
    title = ann.get("title", "")
    notice_date = ann.get("notice_date", ann.get("announcementTime", ann.get("date", "")))[:10]

    return {
        "date": notice_date,
        "title": title,
        "type": "路演/业绩说明" if "业绩" in title or "说明" in title else "路演",
        "art_code": ann.get("art_code", ""),
    }


def _extract_institutions(title):
    """从标题提取参与机构名称"""
    # 标题格式: "XXX:关于XXX接待XXX、XXX、XXX调研的公告"
    # 或 "XXX:XXX投资者关系活动记录"
    import re
    # 尝试匹配"接待XXX调研"格式
    m = re.search(r"接待(.+?)调研", title)
    if m:
        return m.group(1).strip()
    m = re.search(r"接待(.+?)机构", title)
    if m:
        return m.group(1).strip()
    # 提取所有"XXX机构"的格式
    orgs = re.findall(r"[\u4e00-\u9fa5]{2,10}(?:基金|证券|保险|资产管理|信托|私募|投资|银行|公司|机构)", title)
    return "、".join(orgs[:5]) if orgs else ""


def _extract_theme(title):
    """从标题提取调研主题"""
    import re
    # 格式: "关于XXX业务/主题的调研"
    m = re.search(r"关于(.+?)的调研", title)
    if m:
        return m.group(1).strip()
    m = re.search(r"关于(.+?)投资者", title)
    if m:
        return m.group(1).strip()
    return ""


def _build_summary(survey_records, ir_activities, roadshow_records):
    """构建摘要"""
    # 近12个月
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    recent_surveys = [s for s in survey_records if s.get("date", "") >= cutoff]
    recent_ir = [r for r in ir_activities if r.get("date", "") >= cutoff]

    # 参与机构数
    org_names = []
    for s in recent_surveys:
        org = s.get("organizers", "")
        if org:
            for o in org.split("、"):
                if o.strip():
                    org_names.append(o.strip())

    unique_orgs = len(set(org_names))

    # 机构关注度
    survey_count = len(recent_surveys)
    if survey_count >= 30:
        attention = "🔥 高关注（机构密集调研）"
    elif survey_count >= 15:
        attention = "📈 中高关注"
    elif survey_count >= 5:
        attention = "📊 中等关注"
    elif survey_count >= 1:
        attention = "📉 低关注"
    else:
        attention = "⚪ 近期无机构调研记录"

    # 活动类型分布
    type_counts = {}
    for r in ir_activities:
        t = r.get("type", "其他")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "survey_count_12m": survey_count,
        "ir_activity_count_12m": len(recent_ir),
        "roadshow_count_12m": len([r for r in roadshow_records if r.get("date", "") >= cutoff]),
        "unique_institutions": unique_orgs,
        "institutional_attention": attention,
        "ir_activity_types": type_counts,
        "total_ir_records": len(ir_activities) + len(roadshow_records),
    }


def format_markdown(data):
    """格式化投资者互动分析为Markdown"""
    if not data:
        return "## 投资者问答与互动分析\n\n_暂无数据_"

    ir = data.get("ir_activities", [])
    surveys = data.get("survey_records", [])
    roadshows = data.get("roadshow_records", [])
    smry = data.get("summary", {})
    warns = data.get("warnings", [])

    lines = ["## 投资者问答与互动分析\n"]

    # 提示
    if warns:
        for w in warns:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    # 摘要
    lines.append("### 综合摘要\n")
    lines.append(f"- 机构关注度: **{smry.get('institutional_attention', '数据不足')}**")
    lines.append(f"- 近12月调研次数: {smry.get('survey_count_12m', 0)}次")
    lines.append(f"- 近12月IR活动: {smry.get('ir_activity_count_12m', 0)}次")
    lines.append(f"- 近12月路演/业绩会: {smry.get('roadshow_count_12m', 0)}次")
    lines.append(f"- 参与机构数（估算）: {smry.get('unique_institutions', 0)}家")
    ir_types = smry.get("ir_activity_types", {})
    if ir_types:
        type_str = "、".join([f"{k}({v}次)" for k, v in ir_types.items()])
        lines.append(f"- IR活动类型: {type_str}")
    lines.append("")

    # 机构调研记录
    if surveys:
        lines.append("### 机构调研记录\n")
        lines.append(f"| 日期 | 参与机构（估算） | 调研主题 |")
        lines.append("|------|----------------|---------|")
        for s in surveys[:20]:
            org = s.get("organizers", "机构投资者")[:30]
            theme = s.get("theme", s.get("title", ""))[:40]
            lines.append(f"| {s.get('date', '?')} | {org} | {theme} |")
        lines.append("")

    # 路演/业绩说明会
    if roadshows:
        lines.append("### 路演与业绩说明会\n")
        lines.append(f"| 日期 | 类型 | 标题 |")
        lines.append("|------|------|------|")
        for r in roadshows[:15]:
            title = r.get("title", "")[:70]
            lines.append(f"| {r.get('date', '?')} | {r.get('type', '路演')} | {title} |")
        lines.append("")

    # IR活动汇总
    if ir and not surveys and not roadshows:
        lines.append("### 投资者关系活动\n")
        lines.append(f"| 日期 | 类型 | 标题 |")
        lines.append("|------|------|------|")
        for r in ir[:20]:
            title = r.get("title", "")[:70]
            lines.append(f"| {r.get('date', '?')} | {r.get('type', 'IR活动')} | {title} |")
        lines.append("")

    # 信息质量评估
    total = len(surveys) + len(ir) + len(roadshows)
    if total == 0:
        lines.append("### ⚠️ 信息质量\n")
        lines.append("- 近12月无机构调研/IR活动记录，可能原因：\n")
        lines.append("  1. 公司为非公开/港股/北交所，IR活动未强制披露\n")
        lines.append("  2. 公司业务敏感度高，机构调研受限\n")
        lines.append("  3. 东方财富数据暂时缺失\n")
        lines.append("")
    elif len(surveys) < 3:
        lines.append("### ⚠️ 信息质量提示\n")
        lines.append("- 近12月调研记录较少（<3次），可能反映机构关注度偏低\n")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    stock = sys.argv[1] if len(sys.argv) > 1 else "600519"
    # 在独立运行时，如果没有原始公告数据，返回提示
    data = fetch_investor_qa(stock, raw_announcements=None)
    print(format_markdown(data))
    print("\n使用方法: 在 analyze.py 中，investor_qa 模块会自动接收 announcements 的原始数据")


def _generate_investor_ai_narrative(data):
    """生成投资者互动AI综合解读"""
    ir = data.get("ir_activities", [])
    surveys = data.get("survey_records", [])
    roadshows = data.get("roadshow_records", [])
    smry = data.get("summary", {})

    if not ir and not surveys and not roadshows:
        return ""

    evidence_parts = []
    evidence_parts.append(f"机构关注度: {smry.get('institutional_attention', '数据不足')}")
    evidence_parts.append(f"近12月调研次数: {smry.get('survey_count_12m', 0)}次")
    evidence_parts.append(f"近12月IR活动: {smry.get('ir_activity_count_12m', 0)}次")
    evidence_parts.append(f"近12月路演/业绩会: {smry.get('roadshow_count_12m', 0)}次")
    evidence_parts.append(f"参与机构数: {smry.get('unique_institutions', 0)}家")

    if surveys:
        evidence_parts.append(f"\n机构调研记录({len(surveys)}条):")
        for s in surveys[:8]:
            evidence_parts.append(f"  {s.get('date', '')} {s.get('organizers', '')[:30]} - {s.get('theme', '')[:40]}")

    if roadshows:
        evidence_parts.append(f"\n路演/业绩说明会({len(roadshows)}条):")
        for r in roadshows[:5]:
            evidence_parts.append(f"  {r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:50]}")

    evidence_block = '\n'.join(evidence_parts)

    prompt = f"""以下是某上市公司投资者互动数据，请写一段专业的投资者关系分析（200-400字）。

要求：
1. 分析机构关注度水平（高/中/低）
2. 评估调研频率和参与机构质量
3. 关注业绩说明会和路演的主要议题
4. 分析投资者关系管理的积极程度
5. 语言专业、客观

===== 投资者互动数据 =====
{evidence_block}
===== 数据结束 =====

请输出投资者关系分析："""

    try:
        from scripts.llm_config import call_llm
        narrative = call_llm(
            system_prompt="你是一位顶级券互联网行业分析师，擅长解读上市公司投资者关系管理。",
            user_prompt=prompt,
            max_tokens=2048,
        )
        if narrative and len(narrative) > 100:
            return narrative
    except Exception as e:
        print(f"  [投资者互动AI解读] LLM调用失败: {e}")

    return ""


def build_evidence(data, findings=None):
    """构建投资者互动证据块"""
    ir = data.get("ir_activities", [])
    surveys = data.get("survey_records", [])
    roadshows = data.get("roadshow_records", [])
    smry = data.get("summary", {})
    if not ir and not surveys and not roadshows:
        return ""
    parts = [
        f"机构关注度: {smry.get('institutional_attention', '数据不足')}",
        f"近12月调研次数: {smry.get('survey_count_12m', 0)}次",
        f"近12月IR活动: {smry.get('ir_activity_count_12m', 0)}次",
        f"近12月路演/业绩会: {smry.get('roadshow_count_12m', 0)}次",
        f"参与机构数: {smry.get('unique_institutions', 0)}家",
    ]
    if surveys:
        parts.append(f"机构调研记录({len(surveys)}条):")
        for s in surveys[:8]:
            parts.append(f"  {s.get('date', '')} {s.get('organizers', '')[:30]} - {s.get('theme', '')[:40]}")
    if roadshows:
        parts.append(f"路演/业绩说明会({len(roadshows)}条):")
        for r in roadshows[:5]:
            parts.append(f"  {r.get('date', '')} [{r.get('type', '')}] {r.get('title', '')[:50]}")
    return '\n'.join(parts)


def generate_report_section(data: dict, batch_analysis=None) -> list:
    if not data:
        return []

    lines = []
    lines.append("## 投资者互动")
    lines.append("")

    smry = data.get("summary", {})
    lines.append(f"**机构关注度**: {smry.get('institutional_attention', '数据不足')}")
    lines.append(f"**近12月调研次数**: {smry.get('survey_count_12m', 0)}次 | **参与机构数**: {smry.get('unique_institutions', 0)}家")
    lines.append("")

    ai_narrative = ""
    if batch_analysis and batch_analysis.get('investor'):
        ai_narrative = batch_analysis['investor']
    else:
        ai_narrative = _generate_investor_ai_narrative(data)

    if ai_narrative:
        lines.append("### 🤖 AI投资者关系分析")
        lines.append("")
        lines.append(ai_narrative)
        lines.append("")

    surveys = data.get("survey_records", [])
    if surveys:
        lines.append("### 机构调研记录")
        lines.append("")
        lines.append('<table class="investor-table"><thead><tr><th>日期</th><th>参与机构</th><th>调研主题</th></tr></thead><tbody>')
        for s in surveys[:15]:
            org = s.get("organizers", "机构投资者")[:25]
            theme = s.get("theme", s.get("title", ""))[:40]
            lines.append(f'<tr><td>{s.get("date", "?")}</td><td>{org}</td><td>{theme}</td></tr>')
        lines.append('</tbody></table>')
        lines.append("")

    roadshows = data.get("roadshow_records", [])
    if roadshows:
        lines.append("### 路演与业绩说明会")
        lines.append("")
        lines.append('<table class="investor-table"><thead><tr><th>日期</th><th>类型</th><th>标题</th></tr></thead><tbody>')
        for r in roadshows[:10]:
            title = r.get("title", "")[:50]
            lines.append(f'<tr><td>{r.get("date", "?")}</td><td>{r.get("type", "路演")}</td><td>{title}</td></tr>')
        lines.append('</tbody></table>')
        lines.append("")

    return lines
