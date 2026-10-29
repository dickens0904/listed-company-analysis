# -*- coding: utf-8 -*-
"""
AI数据质量增强模块
用LLM对采集到的原始数据进行：分类、全文提取、结构化提取、质量补全
"""
import json
import os
import sys
import time

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from llm_config import call_llm


# ============================================================
# 1. 公告智能分类：从标题列表中筛选需要获取全文的公告
# ============================================================

def classify_announcements(announcements: list, company_name: str = '', max_fulltext: int = 50) -> dict:
    """
    用AI对公告列表进行智能分类，筛选出需要获取全文的重要公告。

    Args:
        announcements: 公告列表，每条至少有 title, date 字段
        company_name: 公司名称
        max_fulltext: 最多选取多少条获取全文

    Returns:
        {
            'need_fulltext': [...],   # 需要获取全文的公告（按重要性排序）
            'title_only': [...],      # 只需标题即可的公告
            'classification_log': str # AI分类理由
        }
    """
    if not announcements:
        return {'need_fulltext': [], 'title_only': [], 'classification_log': '无公告'}

    # 构造标题列表给AI（只取最近3年的，避免太长）
    ann_list = []
    for i, ann in enumerate(announcements[:500]):  # 最多处理500条
        title = ann.get('title', '')
        date = ann.get('date', '')
        importance = ann.get('importance', '')
        if title:
            ann_list.append(f"{i}|{date}|{importance}|{title}")

    ann_text = '\n'.join(ann_list)

    system_prompt = """你是一位资深证券分析师助理。你的任务是从公告标题列表中，筛选出对投资分析真正重要的公告。

筛选标准（满足任一即标记为"需要全文"）：
1. 涉及重大资产重组、并购、出售资产
2. 涉及仲裁、诉讼、处罚（金额明确或重大的）
3. 涉及担保、质押、关联交易（需了解具体对象和金额）
4. 涉及股权激励、增减持（需了解具体条款）
5. 涉及子公司分拆IPO、战略合作
6. 年报、半年报、季报（定期报告）
7. 涉及产能扩张、新建基地、新产品
8. 审计意见异常（保留意见、强调事项段）
9. 涉及控制权变更、实控人变动

不需要全文的公告：
- 常规会议通知、决议公告（无实质内容）
- 简单的进展公告（无新信息）
- 独立董事述职报告
- 简式/详式权益变动报告书（除非涉及控制权）

输出格式（严格JSON）：
```json
{
  "need_fulltext": [序号1, 序号2, ...],
  "title_only": [序号3, 序号4, ...],
  "reason": "分类理由简述"
}
```

只输出JSON，不要其他文字。"""

    user_prompt = f"公司：{company_name}\n公告列表（序号|日期|重要性|标题）：\n{ann_text}\n\n请筛选出最多{max_fulltext}条需要获取全文的重要公告。"

    result = call_llm(system_prompt, user_prompt, temperature=0.1, max_tokens=4096)

    if not result:
        # 降级：按原始重要性标签筛选
        return _fallback_classify(announcements, max_fulltext)

    try:
        # 提取JSON
        json_str = result
        if '```json' in result:
            json_str = result.split('```json')[1].split('```')[0]
        elif '```' in result:
            json_str = result.split('```')[1].split('```')[0]

        parsed = json.loads(json_str.strip())
        need_idx = parsed.get('need_fulltext', [])
        title_idx = parsed.get('title_only', [])
        reason = parsed.get('reason', '')

        need_fulltext = [announcements[i] for i in need_idx if i < len(announcements)]
        title_only = [announcements[i] for i in title_idx if i < len(announcements)]

        # 未分类的归入title_only
        classified_idx = set(need_idx) | set(title_idx)
        for i, ann in enumerate(announcements):
            if i not in classified_idx:
                title_only.append(ann)

        print(f"  [AI分类] 需全文: {len(need_fulltext)}条, 仅标题: {len(title_only)}条")
        return {
            'need_fulltext': need_fulltext,
            'title_only': title_only,
            'classification_log': reason
        }

    except Exception as e:
        print(f"  [AI分类] JSON解析失败: {e}, 降级处理")
        return _fallback_classify(announcements, max_fulltext)


def _fallback_classify(announcements, max_fulltext):
    """降级分类：按原始重要性标签筛选"""
    need = []
    title_only = []
    for ann in announcements:
        imp = ann.get('importance', '').upper()
        if imp in ('CRITICAL',) and len(need) < max_fulltext:
            need.append(ann)
        else:
            title_only.append(ann)
    return {'need_fulltext': need, 'title_only': title_only, 'classification_log': '降级:按重要性标签'}


# ============================================================
# 2. 公告全文结构化提取：从全文中提取关键事实
# ============================================================

def extract_announcement_details(full_text: str, title: str, ann_type: str = 'auto') -> dict:
    """
    用AI从公告全文中提取结构化关键信息。

    Args:
        full_text: 公告全文
        title: 公告标题
        ann_type: 公告类型（auto=自动识别）

    Returns:
        结构化提取结果 dict
    """
    if not full_text or len(full_text) < 100:
        return {'error': '全文过短或为空', 'raw_text': full_text}

    # 截取前6000字避免token过多
    text_for_ai = full_text[:6000]

    system_prompt = """你是一位证券分析师，擅长从公告全文中提取关键结构化信息。

请从公告正文中提取以下信息（只提取明确写明的内容，不要推测）：

输出JSON格式：
```json
{
  "event_type": "事件类型（如：对外担保/诉讼仲裁/资产重组/关联交易/股权激励等）",
  "key_parties": {
    "公司": "涉及的上市公司或子公司名称",
    "对手方": "交易对手/原告/被告等",
    "子公司": "涉及的子公司名称（如有）"
  },
  "key_numbers": {
    "金额": "涉及金额（含币种和单位）",
    "持股比例": "涉及的持股比例（如有）",
    "期限": "期限（如有）",
    "其他数字": "其他重要数字"
  },
  "key_dates": {
    "生效日期": "",
    "到期日期": "",
    "审批日期": ""
  },
  "risk_signals": ["风险信号1", "风险信号2"],
  "key_facts": [
    "关键事实1（一句话）",
    "关键事实2",
    "关键事实3"
  ],
  "impact_assessment": "对公司的影响（一句话概括）"
}
```

只输出JSON，不要其他文字。字段无数据填null或空字符串。"""

    user_prompt = f"公告标题：{title}\n\n公告全文：\n{text_for_ai}"

    result = call_llm(system_prompt, user_prompt, temperature=0.1, max_tokens=2048)

    if not result:
        return {'error': 'LLM调用失败', 'raw_preview': full_text[:500]}

    try:
        json_str = result
        if '```json' in result:
            json_str = result.split('```json')[1].split('```')[0]
        elif '```' in result:
            json_str = result.split('```')[1].split('```')[0]

        parsed = json.loads(json_str.strip())
        parsed['_source_title'] = title
        return parsed

    except Exception as e:
        return {'error': f'JSON解析失败: {e}', 'raw_response': result[:500], '_source_title': title}


# ============================================================
# 3. 批量公告处理：分类 + 全文获取 + 结构化提取
# ============================================================

def enrich_announcements(stock_code: str, market: str, announcements: list,
                         company_name: str = '', max_fulltext: int = 30,
                         output_dir: str = None) -> dict:
    """
    完整的公告增强流程：
    1. AI分类 → 筛选重要公告
    2. 获取全文（已有缓存则跳过）
    3. AI结构化提取

    Args:
        stock_code: 股票代码
        market: 市场
        announcements: 原始公告列表
        company_name: 公司名称
        max_fulltext: 最多获取全文的公告数
        output_dir: 输出目录（用于缓存）

    Returns:
        {
            'enriched': [...],          # 增强后的公告列表（含结构化提取）
            'title_only': [...],        # 仅保留标题的公告
            'stats': {...},             # 统计信息
            'classification_log': str
        }
    """
    print(f"  [公告增强] 开始，共{len(announcements)}条公告")

    # 步骤1: AI分类
    classification = classify_announcements(announcements, company_name, max_fulltext)
    need_fulltext = classification['need_fulltext']
    title_only = classification['title_only']

    print(f"  [公告增强] 分类完成: {len(need_fulltext)}条需全文, {len(title_only)}条仅标题")

    # 步骤2: 获取全文 + AI提取
    enriched = []
    cache_dir = os.path.join(output_dir, 'ann_cache') if output_dir else None

    for i, ann in enumerate(need_fulltext):
        title = ann.get('title', '')
        art_code = ann.get('art_code', '')
        ann_id = ann.get('announcement_id', '')

        print(f"  [{i+1}/{len(need_fulltext)}] {title[:40]}...")

        # 检查缓存
        full_text = None
        if cache_dir:
            cache_file = os.path.join(cache_dir, f'{art_code or ann_id}.txt')
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    full_text = f.read()
                print(f"    → 缓存命中")

        # 获取全文
        if not full_text:
            full_text = _fetch_announcement_text(stock_code, art_code, ann, market)
            if full_text and cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_file, 'w', encoding='utf-8') as f:
                    f.write(full_text)

        if full_text:
            ann['full_text'] = full_text
            ann['text_length'] = len(full_text)

            # AI结构化提取
            details = extract_announcement_details(full_text, title)
            ann['ai_extracted'] = details
            print(f"    → 全文{len(full_text)}字, AI提取完成")
        else:
            ann['full_text'] = None
            ann['ai_extracted'] = {'error': '全文获取失败'}
            print(f"    → 全文获取失败")

        enriched.append(ann)
        time.sleep(0.5)  # 避免请求过快

    stats = {
        'total': len(announcements),
        'need_fulltext': len(need_fulltext),
        'title_only': len(title_only),
        'fulltext_success': sum(1 for a in enriched if a.get('full_text')),
        'fulltext_fail': sum(1 for a in enriched if not a.get('full_text')),
        'ai_extracted': sum(1 for a in enriched if a.get('ai_extracted') and not a['ai_extracted'].get('error')),
    }

    print(f"  [公告增强] 完成: {stats['fulltext_success']}条全文成功, {stats['ai_extracted']}条AI提取成功")

    return {
        'enriched': enriched,
        'title_only': title_only,
        'stats': stats,
        'classification_log': classification.get('classification_log', '')
    }


def _fetch_announcement_text(stock_code: str, art_code: str, ann_info: dict, market: str) -> str:
    """获取公告全文（优先PDF下载，备选网页提取）"""
    try:
        parent_dir = os.path.dirname(_scripts_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)

        from scripts.announcements import download_announcement_pdf
        import fitz

        # 优先：下载PDF提取（最可靠）
        pdf_dir = os.path.join(_scripts_dir, 'output', f'{stock_code}_ann_pdf')
        pdf_path = download_announcement_pdf(ann_info, pdf_dir, market)
        if pdf_path and os.path.exists(pdf_path):
            doc = fitz.open(pdf_path)
            pages = min(30, doc.page_count)
            parts = [doc[i].get_text() for i in range(pages)]
            doc.close()
            text = '\n'.join(parts)
            if len(text) > 200:
                return text

        # 备选：网页提取（东方财富需要JS渲染，可能只拿到骨架）
        from scripts.announcements import extract_ann_text_via_browser
        text = extract_ann_text_via_browser(stock_code, art_code)
        if text and len(text) > 500:  # 低于500字大概率是页面骨架
            return text

    except Exception as e:
        print(f"    → 全文获取异常: {e}")

    return None


# ============================================================
# 4. 数据质量报告生成
# ============================================================

def generate_quality_report(results: dict) -> dict:
    """
    对results.json进行全面数据质量评估。

    Returns:
        {
            'overall_score': float,  # 0-100
            'dimensions': [...],     # 每个维度的评分
            'critical_issues': [...], # 关键问题
            'improvement_plan': [...] # 改进建议
        }
    """
    findings = results.get('findings', {})
    stock = results.get('stock', '')
    dims = results.get('dims', [])

    dimensions = []
    critical_issues = []

    # 评估每个维度
    checks = [
        ('quote', '实时行情', lambda d: d.get('success') and d.get('data')),
        ('financial', '财务数据', lambda d: len(d.get('records', [])) > 0),
        ('announcements', '公告全景', lambda d: len(d.get('recent_30', []) if isinstance(d, dict) else d) > 0),
        ('executives', '高管动态', lambda d: len(d.get('changes', [])) > 0),
        ('capital', '资金动作', lambda d: len(d.get('actions', [])) > 0),
        ('subsidiary', '子公司', lambda d: len(d.get('subsidiaries', [])) > 0),
        ('related', '关联方', lambda d: len(d.get('deals', [])) > 0),
        ('regulatory', '监管历史', lambda d: len(d.get('records', [])) > 0),
        ('structure', '股权结构', lambda d: len(d.get('top10', [])) > 0 or bool(d.get('actual_controller'))),
        ('industry', '行业竞争', lambda d: bool(d.get('industry_name'))),
        ('risk', '风险评估', lambda d: d.get('score', 0) > 0),
        ('product_line_intro', '产品产线', lambda d: bool(d.get('main_business')) and len(d.get('products', [])) > 0),
    ]

    for dim_key, dim_name, check_fn in checks:
        data = findings.get(dim_key, {})
        try:
            ok = check_fn(data) if data else False
        except:
            ok = False

        score = 80 if ok else 20

        # 深度评估
        if dim_key == 'announcements' and ok:
            ann_list = data.get('recent_30', []) if isinstance(data, dict) else data
            has_fulltext = sum(1 for a in ann_list if a.get('full_text') or a.get('extracted_content'))
            if has_fulltext == 0 and len(ann_list) > 10:
                score = 50
                critical_issues.append(f'公告维度: {len(ann_list)}条公告均无全文提取')

        if dim_key == 'subsidiary' and not ok:
            critical_issues.append('子公司维度: 数据为空，严重缺失')
            score = 10

        if dim_key == 'product_line_intro' and ok:
            products = data.get('products', [])
            if len(products) == 0:
                score = 40
                critical_issues.append('产品产线: products为空，仅有主营业务描述')

        dimensions.append({
            'key': dim_key,
            'name': dim_name,
            'score': score,
            'status': 'OK' if score >= 60 else 'WEAK' if score >= 30 else 'MISSING'
        })

    overall = sum(d['score'] for d in dimensions) / len(dimensions) if dimensions else 0

    return {
        'overall_score': round(overall, 1),
        'dimensions': dimensions,
        'critical_issues': critical_issues,
        'total_dims': len(dims),
        'evaluated_dims': len(dimensions)
    }


# ============================================================
# 5. 主入口：一键数据增强
# ============================================================

def enrich_data(results: dict, output_dir: str = None, max_ann_fulltext: int = 30) -> dict:
    """
    一键数据增强主入口。

    Args:
        results: 原始 results.json 内容
        output_dir: 输出目录（用于缓存）
        max_ann_fulltext: 最多获取全文的公告数

    Returns:
        增强后的 results dict（原地修改 + 返回）
    """
    stock = results.get('stock', '')
    market = results.get('market', 'a')
    findings = results.get('findings', {})

    # 1. 数据质量评估
    print('\n=== 数据质量评估 ===')
    quality = generate_quality_report(results)
    print(f'  综合评分: {quality["overall_score"]}/100')
    for issue in quality['critical_issues']:
        print(f'  ⚠️ {issue}')

    # 2. 公告增强
    ann_data = findings.get('announcements', {})
    ann_list = ann_data.get('recent_30', []) if isinstance(ann_data, dict) else ann_data
    if ann_list:
        print('\n=== 公告智能增强 ===')
        # 获取公司名称
        company_name = ''
        industry_data = findings.get('industry', {})
        if industry_data:
            company_name = industry_data.get('company_name', '')

        ann_result = enrich_announcements(
            stock, market, ann_list,
            company_name=company_name,
            max_fulltext=max_ann_fulltext,
            output_dir=output_dir
        )
        # 回写到findings
        findings['announcements_enriched'] = ann_result

    # 3. 保存增强后的数据
    if output_dir:
        enriched_path = os.path.join(output_dir, 'data', 'results_enriched.json')
        os.makedirs(os.path.dirname(enriched_path), exist_ok=True)
        with open(enriched_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f'\n  增强数据已保存: {enriched_path}')

    return results


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='AI数据质量增强')
    parser.add_argument('--results', required=True, help='results.json路径')
    parser.add_argument('--output', help='输出目录')
    parser.add_argument('--max-ann', type=int, default=30, help='最多获取全文的公告数')

    args = parser.parse_args()

    with open(args.results, 'r', encoding='utf-8') as f:
        results = json.load(f)

    output_dir = args.output or os.path.dirname(os.path.dirname(args.results))
    enrich_data(results, output_dir, args.max_ann)
