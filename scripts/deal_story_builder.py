# -*- coding: utf-8 -*-
"""
deal_story_builder.py — 交易叙事聚合引擎（2026-10-19）
=====================================================

## 为什么需要它

三幕叙事第一幕原先把 `ma_deep` 的公告**逐条**铺进时间线，结果是：
「纳思达：发行股份购买资产预案」「…预案（修订稿）」「…预案摘要」「董事会关于…的说明」
「…进展公告」… 同一笔交易被拆成十几行，读者看到的是**公告标题流**，
不是**公司干了什么**——这就是"时间线没有灵魂"。

实测证据（002180 奔图科技）：
- 21 条"动作"里，**86% 是同一笔收购的不同程序公告**
- `ma_deep.deals` 共 186 条，公告总数 1354 条，但真实重大交易只有**个位数**

## 本模块做什么

把公告洪水聚合成 **DealStory（交易故事）**：一笔交易 = 一条故事，
带「阶段推进时间线 + 交易要素（标的/对手方/金额/对价方式）+ 战略解读」。

**阶段识别**（依据 A 股公告实践，用实测数据校准）：
    预案/筹划 → 董事会审议 → 股东大会 → 监管受理/审核 → 交割完成 → 终止
每阶段识别出来后，故事会输出「这笔交易走到哪一步了」。

## 严格纪律（沿用本 skill 证据纪律）

1. **缺口不得写成结论**：金额/对手方抽不到就写"未披露"，**绝不推测**。
2. **不生发事实**：战略解读只用公告原文里出现的标的/业务词，不做因果推断。
3. **聚合同源可溯**：每条聚合记录保留其成员公告的 `art_code` 与日期，可回查原文。
4. **聚合置信度**：单条公告 = 🟡（只有标题事实）；≥3 条含阶段推进 + 监管受理 = 🟢。

## 用法

    from scripts.deal_story_builder import build_deal_stories
    stories = build_deal_stories(findings, stock_code='002180')
    # → [{'story_id':…, 'title':…, 'stages':[…], 'first_date':…, 'last_date':…,
    #     'counterparty':…, 'target':…, 'amount':…, 'member_count':…, …}]
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 一、交易阶段识别（实测校准：A 股重组公告的 6 个阶段）
# ============================================================
# 顺序即优先级倒序判断：先判"完成"再判"预案"，避免"预案摘要"被误判为预案
# ⚠️ 顺序即**阅读顺序**（筹划→董事会→股东大会→监管→交割→终止），
#    渲染与"走到哪"的判断都依赖它。2026-10-19 曾把 terminated/completed 放在
#    数组最前，导致脉络显示成「交割完成 → 监管审核 → …」倒序，已修正。
STAGE_ORDER = ['proposed', 'board', 'shareholder', 'regulatory', 'completed', 'terminated']

STAGE_PATTERNS: List[Tuple[str, str, Any]] = [
    ('terminated', '终止/未获通过', re.compile(
        r'(终止|撤回|中止|未获通过|否决|失败|不再实施)')),

    ('completed', '交割完成/实施完毕', re.compile(
        r'(交割.{0,4}完成|过户.{0,4}完成|实施情况|实施完毕|新增股份上市|'
        r'发行情况暨上市|资产交割)')),

    ('regulatory', '监管受理/审核通过/核准', re.compile(
        r'(受理|核准|审核.{0,6}通过|注册生效|证监会.{0,8}(同意|批准)|反馈意见.{0,4}回复)')),

    ('shareholder', '股东大会审议', re.compile(
        r'(股东大会.{0,8}(审议|通过|决议)|临时股东大会)')),

    ('board', '董事会审议', re.compile(
        r'(董事会.{0,10}(审议|决议|通过|同意)|审议通过.{0,6}议案)')),

    ('proposed', '预案/筹划/停牌', re.compile(
        r'(预案|筹划|停牌|签署.{0,8}(框架)?(协议|意向书)|交易方案)')),
]

STAGE_LABELS = {
    'proposed': '筹划预案',
    'board': '董事会审议',
    'shareholder': '股东大会',
    'regulatory': '监管审核',
    'completed': '交割完成',
    'terminated': '终止',
}

# ============================================================
# 二、交易"身份"识别：什么公告属于同一笔交易
# ============================================================
# 用交易类关键词判断"这是一笔交易类公告"
DEAL_KW = re.compile(
    r'(购买资产|出售资产|发行股份.{0,6}购买|收购|股权转让|资产重组|重大资产重组|'
    r'吸收合并|重大资产置换|分拆|引战|战略投资|增资|并购|重组上市|控制权|'
    r'投资协议|股权转让协议|股份转让协议)')

# 提取"标的/对手方"线索：优先从"XX有限公司"这类机构名
_ENTITY_RE = re.compile(
    r'((?:珠海|上海|北京|深圳|广州|杭州|成都|天津|重庆|苏州|南京|青岛|'
    r'宁波|厦门|武汉|西安|长沙|合肥|郑州|济南|大连|福建|广东|江苏|浙江)?'
    r'[\u4e00-\u9fa5]{2,10}'
    r'(?:股份有限公司|有限责任公司|有限公司|集团(?:有限公司)?|控股))')

# 剔除的"伪实体"（2026-10-19 实测扩充）
# 🔴 实测踩坑：最初只剔了「XX证券股份有限公司」，结果
#   「出售 东方证券承销保荐有限公司」「出售 华泰联合证券有限责任公司」
#   被当成"标的"——这两家是**中介机构**（券商/律所/评估/审计），
#   是交易的中介而非交易对象。必须按"机构类型词"整体剔除，
#   而不能只剔「股份有限公司」这一种后缀。
_ENTITY_STOP = re.compile(
    r'(证券|会计师事务所|律师事务所|资产评估|资产管理|融资担保|'
    r'独立财务顾问|财务顾问|保荐|承销|投资银行|商业银行|银行|保险|信托|'
    r'中国证券监督管理委员会|深圳证券交易所|上海证券交易所|北京证券交易所|'
    r'上市公司|本公司|该公司|贵公司|'
    # 泛化的"治理/中介"词（覆盖"XX控股""关于控股"这类非实体）
    r'独立董事|监事会|审计委员会|战略委员会|提名委员会|薪酬委员会)')

# 实体名前的修饰词噪声（「所涉及的」「关于」等不是实体的一部分）
_ENTITY_PREFIX_NOISE = re.compile(
    r'^(关于|所涉及的?|涉及的?|本次|本次交易|拟|公司|重大资产重组涉及|'
    r'重大资产重组|资产重组涉及|重组涉及|与|和|及|及涉及)')

_AMOUNT_RE = re.compile(r'([\d.]+)\s*(亿元|亿|万元|万)')

# 公告标题里的"公司名：正文"前缀（巨潮格式）
_PREFIX_RE = re.compile(r'^\s*([\u4e00-\u9fa5A-Za-z*]{2,12})\s*[::]\s*(.+)$')


def _split_prefix(title: str) -> Tuple[str, str]:
    """拆「纳思达：xxx」→ ('纳思达','xxx')；无前缀则返回 ('', title)"""
    m = _PREFIX_RE.match(title or '')
    if m and len(m.group(2)) > 6:
        return m.group(1), m.group(2)
    return '', title or ''


def _stage_of(text: str) -> Optional[str]:
    """判断阶段。倒序遍历 STAGE_ORDER 的 pattern（pattern 数组已按终态优先）。"""
    for _stage, _label, pat in STAGE_PATTERNS:
        if pat.search(text or ''):
            return _stage
    return None


def _entities(text: str) -> List[str]:
    """
    抽取正文里的机构名。

    2026-10-19 实测修正：
      ① 机构类型词整体剔除（券商/律所/会计/评估/银行…）——否则
         「出售 东方证券承销保荐有限公司」会把中介当标的；
      ② 剥掉前置修饰噪声（"所涉及的""关于"…）——否则实体名变成
         「所涉及的珠海欣威科技有限公司」，聚类键对不上。
    """
    out = []
    for m in _ENTITY_RE.finditer(text or ''):
        e = _ENTITY_PREFIX_NOISE.sub('', m.group(1)).strip()
        if not e:
            continue
        if _ENTITY_STOP.search(e):
            continue
        # 太短或全是通用词的不算实体
        if len(e) < 4:
            continue
        out.append(e)
    return out


def _amount(text: str) -> str:
    m = _AMOUNT_RE.search(text or '')
    return f'{m.group(1)}{m.group(2)}' if m else ''


def _clean_title(raw: str) -> str:
    """去掉「纳思达：」前缀，保留正文标题"""
    _, body = _split_prefix(raw)
    return body.strip()


# 交易类型指纹：按判别力排序，取第一个命中作为分组键。
# 注意：必须用**交易标的性质**而非程序阶段（预案/决议/实施），
# 否则同一笔交易的各阶段会因阶段词不同而被拆开。
_FINGERPRINTS = [
    ('购买资产', re.compile(r'(购买.{0,8}资产|发行股份.{0,8}购买|支付现金.{0,6}购买|'
                           r'发行股份及支付现金.{0,10}购买|重大资产重组.{0,10}购买)')),
    ('出售资产', re.compile(r'(出售.{0,8}资产|出售.{0,6}股权|转让.{0,8}股权|'
                           r'重大资产出售)')),
    ('控制权',   re.compile(r'(控制权|表决权|实际控制人|控制权变更)')),
    ('增资引战', re.compile(r'(增资|战略投资|引入投资|定向增发|非公开发行.{0,6}股票.{0,6}(募集|发行))')),
    ('吸收合并', re.compile(r'(吸收合并|换股合并)')),
    ('分拆',     re.compile(r'(分拆.{0,8}上市|分拆所属子公司)')),
    ('资产置换', re.compile(r'(资产置换|置换资产)')),
]


def _deal_fingerprint(text: str) -> str:
    """取交易类型指纹（用于无标的时的分组键）"""
    t = text or ''
    for label, pat in _FINGERPRINTS:
        if pat.search(t):
            return label
    m = DEAL_KW.search(t)
    return m.group(0) if m else 'other'


# ============================================================
# 三、聚合主逻辑
# ============================================================
def build_deal_stories(findings: Dict[str, Any], stock_code: str = '',
                       use_fulltext: bool = True) -> List[Dict[str, Any]]:
    """
    把公告洪水聚合成交易故事列表。

    Args:
        findings: analyze.py 的 findings
        stock_code: 用于 story_id
        use_fulltext: 是否启用 **PDF 全文反哺**（2026-10-19 新增）。
            标题里没有标的名是常态（标的名写在 PDF 正文），启用后从
            `extracted_content.full_text_preview` 里回抽标的名与金额，
            把「收购（标的未在公告标题中披露）」升级成「收购 珠海奔图电子有限公司」。
            只读已抽取好的文本，**不触发任何新下载**。

    聚合键设计：
      - 主键 = 主要标的实体（实体名）。这是"这笔交易在买什么/卖什么"。
      - 若抽不到实体，退化为按**交易类型指纹 + 时间窗口**聚类。
      这样保证"一笔交易 = 一条故事"，而不是一堆公告碎片。

    Returns:
        按 first_date 排序的故事列表。
    """
    ann = findings.get('announcements') or {}
    all_ann: List[Dict[str, Any]] = []
    for k in ('critical_announcements', 'major_announcements', 'routine_announcements'):
        all_ann.extend(ann.get(k) or [])
    if not all_ann:
        return []

    # 全文反哺索引：art_code → (标的名, 金额)
    ft_index: Dict[str, Tuple[str, str]] = {}
    if use_fulltext:
        ft_index = _build_fulltext_index(all_ann)

    # 预过滤：只保留交易类公告
    deal_anns = [a for a in all_ann
                 if a.get('title') and DEAL_KW.search(a['title'])]
    if not deal_anns:
        return []

    # 🔴 2026-10-19 修正（实测发现）：
    # 「董事会决议公告」「股东大会决议公告」**不含任何交易词**，会被上面的
    # 预过滤直接丢掉 → 一笔交易的阶段脉络只剩"预案"和"交割完成"两端，
    # 中间的审议环节凭空消失（实测 4 条公告被聚成 2 笔，正是这个原因）。
    # 正确做法：**决议类公告先收集，再按时间窗吸附到附近有交易锚点的簇**。
    decision_anns = [a for a in all_ann
                     if a.get('title') and DECISION_KW.search(a['title'])]

    # ── 步骤1：为每条交易公告找"归属实体"──
    # 聚类键的两级策略（2026-10-19 修正）：
    #   实测发现「发行股份及支付现金购买资产…预案」这类标题**抽不到实体名**
    #   （正文里标的写在 PDF 里，不在标题）。若按"类型词"做 key，会把
    #   同一笔交易的不同阶段（预案/董事会/交割）切成多笔——反而更碎。
    #   正确做法：**先按"标的名"分组；抽不到标的的走 fallback 分支**，
    #   fallback 用「交易类型指纹 + 时间窗」归组，保证同一笔交易聚在一起。
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in deal_anns:
        issuer, body = _split_prefix(a.get('title', ''))
        ents = _entities(body)
        if ents:
            key = 'ent::' + ents[0]
        else:
            # 指纹：取最具判别力的交易类型词
            fp = _deal_fingerprint(body)
            key = 'fp::' + fp
        buckets[key].append(a)

    stories: List[Dict[str, Any]] = []
    for key, group in buckets.items():
        # 同一 key 下再按 400 天窗口切分（避免把 2015/2021 两笔同类交易合并）
        sub_stories = _split_by_time_and_type(group)
        for st in sub_stories:
            enriched = _attach_decisions(st, decision_anns)
            story = _story_from_group(enriched, stock_code)
            if story:
                # 全文反哺：补标的名与金额（标题层抽不到是常态）
                if ft_index:
                    story = _apply_fulltext(story, ft_index, stock_code)
                stories.append(story)

    stories.sort(key=lambda s: s.get('first_date') or '')
    return stories


def _split_by_time_and_type(group: List[Dict[str, Any]],
                            window_days: int = 400) -> List[List[Dict[str, Any]]]:
    """
    把同一聚类键下相隔过久的公告切成不同交易。

    2026-10-19 修正：原用 90 天窗口，实测发现**一笔正常 A 股重大重组从预案到
    交割常跨 6–18 个月**（002180 那笔 2020-03 预案 → 2020-11 过户 = 253 天），
    90 天窗口会把**同一笔交易切成两半**（实测 4 条公告被切成 2 笔）。
    故默认放宽到 400 天；若该簇含实体重叠（如两次都买"赛纳"），仍需按实体细分
    ——那种情况由上层 `ent::` 键天然区分，这里不再切。
    """
    from datetime import datetime

    def _d(a):
        try:
            return datetime.strptime(a.get('date', ''), '%Y-%m-%d')
        except Exception:
            return None

    # 按日期排序（无日期的放最后）
    items = sorted(group, key=lambda a: a.get('date') or '9999')
    clusters: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    cur_date = None
    for a in items:
        d = _d(a)
        if cur_date and d and (d - cur_date).days > window_days:
            clusters.append(cur)
            cur = []
        if d:
            cur_date = d
        cur.append(a)
    if cur:
        clusters.append(cur)
    return clusters


def _story_from_group(group: List[Dict[str, Any]],
                      stock_code: str = '') -> Optional[Dict[str, Any]]:
    """由一组同交易公告 → 一条 DealStory"""
    if not group:
        return None

    dates = sorted([a['date'] for a in group if a.get('date')])
    if not dates:
        return None

    # 抽取交易要素（优先从"最完整"的公告抽：预案/实施报告通常要素最全）
    entities = Counter()
    amounts = []
    stage_hits = []      # [(date, stage)]
    for a in group:
        _, body = _split_prefix(a.get('title', ''))
        entities.update(_entities(body))
        amt = _amount(body)
        if amt:
            amounts.append(amt)
        st = _stage_of(a.get('title', ''))
        if st:
            stage_hits.append((a.get('date', ''), st))

    # 阶段推进序列：2026-10-19 修正震荡问题。
    # 原实现按时间顺次 append，实测得到
    #   股东大会→董事会→股东大会→董事会→…（公告标题里的程序词随机出现）
    # 读起来毫无意义。真实一笔交易的阶段是**单调推进**的：
    #   筹划 → 董事会 → 股东大会 → 监管 → 交割（最多中途终止）
    # 故按 STAGE_ORDER 的位次取每个阶段的**最早日期**，
    # 再按位次排序输出，得到"最前沿走到哪"。
    reached: Dict[str, str] = {}
    for a in group:
        st = _stage_of(a.get('title', ''))
        d = a.get('date', '')
        if not st:
            continue
        if st not in reached or d < reached[st]:
            reached[st] = d
    seq = [s for s in STAGE_ORDER if s in reached]      # 单调，不震荡
    stage_dates = {s: reached[s] for s in seq}

    top_entity = entities.most_common(1)[0][0] if entities else ''
    # 金额：取最大值/最完整的一条（避免"10亿元"与"1,234万元"混用，取样本中最常见的量级）
    amount = Counter(amounts).most_common(1)[0][0] if amounts else ''

    story_title = _build_story_title(top_entity, seq, group, stock_code)

    # 置信度：单条公告 = 🟡；含"监管审核"+"交割完成"或 ≥4 条 = 🟢
    has_complete = ('completed' in seq) or ('regulatory' in seq)
    confidence = '🟢' if (has_complete and len(group) >= 3) else ('🟡' if len(group) >= 2 else '⚪')

    return {
        'story_id': f'{stock_code}_{dates[0]}_{top_entity or "deal"}',
        'title': story_title,
        'target': top_entity or '',
        'amount': amount,
        'first_date': dates[0],
        'last_date': dates[-1],
        'duration_days': _span_days(dates),
        'stage_sequence': seq,
        'stage_dates': stage_dates,
        'stage_labels': [STAGE_LABELS.get(s, s) for s in seq],
        'frontier_stage': seq[-1] if seq else '',
        'member_count': len(group),
        'confidence': confidence,
        'members': [{'date': a.get('date', ''), 'title': _clean_title(a.get('title', '')),
                     'stage': _stage_of(a.get('title', '')) or '',
                     'art_code': a.get('art_code', ''),
                     'importance': a.get('importance', '')}
                    for a in sorted(group, key=lambda a: a.get('date') or '')],
    }


def _span_days(dates: List[str]) -> int:
    from datetime import datetime
    try:
        d1 = datetime.strptime(dates[0], '%Y-%m-%d')
        d2 = datetime.strptime(dates[-1], '%Y-%m-%d')
        return (d2 - d1).days
    except Exception:
        return 0


# 决议/审议类公告（不含交易词，需按时间窗吸附到交易簇）
DECISION_KW = re.compile(
    r'(董事会.{0,12}(决议|决议公告|会议)|股东大会.{0,10}(决议|决议公告)|'
    r'临时股东大会|审议通过.{0,8}议案|关联交易.{0,8}(董事会|股东大会))')


def _attach_decisions(cluster: List[Dict[str, Any]],
                      decision_anns: List[Dict[str, Any]],
                      pad_days: int = 10) -> List[Dict[str, Any]]:
    """
    把附近的决议类公告吸附进交易簇，补齐"董事会→股东大会→监管"中间环节。

    🔴 2026-10-19 实测踩坑：pad 一度取 20 天、窗口 400 天，导致
    决议公告把**多笔不相关交易**的公告全吸进同一簇（实测出现
    "284 份公告 / 跨 1851 天"的怪物簇）。原因：
      ① 决议公告本身不含标的/交易词，无法判断它属于哪笔交易；
      ② 只按时间邻近吸附，必然误吸。
    修正（两道闸）：
      1) pad 收紧到 **10 天**（决议通常紧邻交易节点当天或次日）；
      2) **簇跨度熔断**：若吸附后簇的日期跨度 > 400 天，说明混进了
         别的交易 → 放弃吸附（宁可缺证据，不制造假交易）。
    """
    from datetime import datetime, timedelta

    def _d(a):
        try:
            return datetime.strptime(a.get('date', ''), '%Y-%m-%d')
        except Exception:
            return None

    dates = [_d(a) for a in cluster]
    dates = [x for x in dates if x]
    if not dates:
        return cluster
    lo, hi = min(dates), max(dates)
    if (hi - lo).days > 400:              # 原有簇已超长，不吸
        return cluster

    lo_p = lo - timedelta(days=pad_days)
    hi_p = hi + timedelta(days=pad_days)

    attached = list(cluster)
    have = {id(a) for a in cluster}
    extra_dates = list(dates)
    for da in decision_anns:
        if id(da) in have:
            continue
        dd = _d(da)
        if dd and lo_p <= dd <= hi_p:
            attached.append(da)
            extra_dates.append(dd)

    # 熔断校验：吸附后跨度不得超 400 天
    if extra_dates and (max(extra_dates) - min(extra_dates)).days > 400:
        return cluster
    return attached


# ============================================================
# 三·补、PDF 全文反哺（2026-10-19）
# ============================================================
# 问题：交易标题里**普遍没有标的名**（标的名写在 PDF 正文），
#   导致聚合退化为"类型指纹"分组，故事标题只能写「标的未在公告标题中披露」。
# 解决：从已抽取的 `extracted_content.full_text_preview`（**不触发新下载**）
#   回抽 ① 标的名 ② 交易金额，反哺到已有簇上。
# 实测（002180）：「购买其持有的**珠海奔图电子有限公司**」→ 标的名补齐；
#   「涉及金额: 40,301.04万元」→ 金额补齐（此前全是空）。
def _build_fulltext_index(all_ann: List[Dict[str, Any]]) -> Dict[str, Tuple[str, str]]:
    """从公告的已抽取全文建立 art_code → (标的, 金额) 索引"""
    idx: Dict[str, Tuple[str, str]] = {}
    for a in all_ann:
        code = a.get('art_code') or ''
        if not code:
            continue
        ec = a.get('extracted_content')
        if not isinstance(ec, dict):
            continue
        txt = (ec.get('full_text_preview') or ec.get('full_text')
               or ec.get('summary') or '')
        if not txt or len(txt) < 120:
            continue

        # ① 标的：优先「购买其持有的XX」「收购XX」「标的公司XX」
        target = ''
        for pat in (r'(?:购买|收购|受让|增资|出售|转让)(?:其?持有?的?)?'
                    r'([\u4e00-\u9fa5]{2,14}(?:股份有限公司|有限责任公司|有限公司))',
                    r'标的公司[：:]?\s*([\u4e00-\u9fa5]{2,14}(?:股份有限公司|有限责任公司|有限公司))',
                    r'交易标的[：:]?\s*([\u4e00-\u9fa5]{2,14}(?:股份有限公司|有限责任公司|有限公司))'):
            m = re.search(pat, txt)
            if m:
                cand = m.group(1)
                if not _ENTITY_STOP.search(cand):
                    target = cand
                    break

        # ② 金额：优先 key_facts 里的「涉及金额」
        amount = ''
        for f in (ec.get('key_facts') or []):
            m = re.search(r'([\d,]+\.?\d*)\s*(亿元|万元|万美元|亿美元)', str(f))
            if m:
                amount = f'{m.group(1)}{m.group(2)}'
                break
        if not amount:
            m = re.search(r'(?:交易(?:价格|对价)|作价)[^\d]{0,12}([\d,]+\.?\d*)\s*(亿元|万元)', txt)
            if m:
                amount = f'{m.group(1)}{m.group(2)}'

        if target or amount:
            idx[code] = (target, amount)
    return idx


def _apply_fulltext(story: Dict[str, Any], ft_index: Dict[str, Tuple[str, str]],
                    stock_code: str) -> Dict[str, Any]:
    """把全文反哺的标的/金额应用到故事上（标题为空时补，空值不覆盖已有值）"""
    if not ft_index:
        return story
    tgt_hits: List[str] = []
    amt_hits: List[str] = []
    for m in story.get('members', []):
        code = m.get('art_code') or ''
        hit = ft_index.get(code)
        if not hit:
            continue
        if hit[0]:
            tgt_hits.append(hit[0])
        if hit[1]:
            amt_hits.append(hit[1])

    # 标的名：取出现频次最高者（跨多份公告印证，可信度更高）
    if not story.get('target') and tgt_hits:
        story['target'] = Counter(tgt_hits).most_common(1)[0][0]
        story['target_source'] = 'PDF全文'
    elif tgt_hits:
        # 已有目标但与全文不一致 → 记一条提示，不静默覆盖
        top = Counter(tgt_hits).most_common(1)[0][0]
        if top != story['target']:
            story['_target_conflict'] = f"标题解析={story['target']} / 全文={top}"
    if not story.get('amount') and amt_hits:
        story['amount'] = Counter(amt_hits).most_common(1)[0][0]
        story['amount_source'] = 'PDF全文'

    # 重算标题（标的名可能刚补上）
    story['title'] = _build_story_title(
        story.get('target', ''), story.get('stage_sequence', []),
        [], stock_code)
    return story


def _build_story_title(entity: str, seq: List[str],
                       group: List[Dict[str, Any]], stock_code: str) -> str:
    """
    造一个"有灵魂"的标题：<动作> <标的> · <阶段概括>

    例：
      "收购 珠海艾派克微电子有限公司 · 已完成交割（3 个阶段）"
      "出售 利盟国际有限公司 · 已推进至董事会审议"
    阶段概括不再嵌进括号，避免与标题的括号叠成 "已完成交割（走完 5 个阶段）" 这类冗余。
    """
    stage_txt = _stage_summary(seq)
    if entity:
        verb = _infer_verb(group)
        # 实体名本身可能已含动词（「出售利盟国际有限公司」被抽成了实体），
        # 此时直接拼会得到「出售 出售利盟国际有限公司」——去重前缀。
        if entity.startswith(verb):
            return f'{entity} · {stage_txt}'
        return f'{verb} {entity} · {stage_txt}'
    # 无标的时也补上动词，至少说清是"收购/出售"而非光秃秃一句阶段
    return f'{_infer_verb(group)}（标的未在公告标题中披露）· {stage_txt}'


def _infer_verb(group: List[Dict[str, Any]]) -> str:
    """从一组公告推断动作动词"""
    joined = ' '.join(a.get('title', '') for a in group[:6])
    if re.search(r'(出售|转让|出售资产|转让股权)', joined):
        return '出售'
    if re.search(r'(吸收合并)', joined):
        return '吸收合并'
    if re.search(r'(控制权|表决权|实际控制人)', joined):
        return '收购控制权'
    if re.search(r'(增资|战略投资|引战)', joined):
        return '增资引入'
    if re.search(r'(购买资产|发行股份.{0,6}购买|收购|发行股份购买)', joined):
        return '收购'
    return '重大交易'


def _stage_summary(seq: List[str]) -> str:
    """阶段概括（seq 已保证单调，不震荡）"""
    if not seq:
        return '交易进行中'
    if 'terminated' in seq:
        return '已终止'
    if 'completed' in seq:
        return f'已完成交割（走完 {len(seq)} 个阶段）'
    labels = [STAGE_LABELS.get(s, s) for s in seq]
    return '已推进至' + labels[-1] + f'（{len(seq)} 个阶段）'


# ============================================================
# 四、渲染（Markdown 片段，供 narrative 装配；HTML 由 narrative 侧渲染）
# ============================================================

def render_story_markdown(story: Dict[str, Any], indent: int = 0) -> str:
    """把一笔交易故事渲染成 Markdown 列表项（带灵魂的那种）"""
    pad = ' ' * indent
    L = []
    L.append(f"{pad}- **{story['title']}**")
    meta = []
    if story.get('amount'):
        meta.append(f"金额 {story['amount']}")
    if story.get('duration_days'):
        meta.append(f"跨 {story['duration_days']} 天")
    meta.append(f"{story['member_count']} 份公告佐证")
    L.append(f"{pad}  - {' ｜ '.join(meta)} [{story['confidence']}]")
    # 推进脉络：用 stage_dates（单调），不逐条罗列所有公告
    sd = story.get('stage_dates') or {}
    if sd:
        # 按 STAGE_ORDER 正序（筹划→董事会→股东大会→监管→交割）渲染，
        # 不能直接用 story['stage_sequence']——那个是为了取"最前沿"按位次排的，
        # 顺序与阅读顺序相反（terminated/completed 排在最前）。
        flow = [f"{sd[s]} {STAGE_LABELS.get(s, s)}"
                for s in STAGE_ORDER if s in sd]
        L.append(f"{pad}  - 推进脉络：{' → '.join(flow)}")
    return '\n'.join(L)


def render_story_html(story: Dict[str, Any]) -> str:
    """把一笔交易故事渲染成 HTML 卡片（带灵魂的那种）"""
    from html import escape
    meta = []
    if story.get('amount'):
        meta.append(f"金额 {escape(story['amount'])}")
    if story.get('duration_days'):
        meta.append(f"跨 {story['duration_days']} 天")
    meta.append(f"{story['member_count']} 份公告佐证")

    sd = story.get('stage_dates') or {}
    flow = [f"{sd[s]} {STAGE_LABELS.get(s, s)}" for s in STAGE_ORDER if s in sd]
    flow_txt = ' → '.join(flow)

    conf_cls = {'🟢': 'g', '🟡': 'y', '⚪': ''}.get(story['confidence'], 'y')
    return (f'<div class="hyp">'
            f'<div class="hd"><strong>{escape(story["title"])}</strong>'
            f'<span class="tag {conf_cls}">{escape(story["confidence"])} 置信</span></div>'
            f'<div class="note">{" ｜ ".join(meta)}</div>'
            f'<div class="note">推进脉络：{escape(flow_txt)}</div>'
            f'</div>')


if __name__ == '__main__':
    # 冒烟测试
    sample = {
        'announcements': {
            'critical_announcements': [
                {'date': '2020-03-02', 'title': '纳思达：发行股份及支付现金购买资产并募集配套资金暨关联交易预案',
                 'art_code': 'A1', 'importance': 'critical'},
                {'date': '2020-06-01', 'title': '纳思达：第八届董事会第十次会议决议公告',
                 'art_code': 'A2', 'importance': 'critical'},
                {'date': '2020-07-01', 'title': '纳思达：2020年第二次临时股东大会决议公告',
                 'art_code': 'A3', 'importance': 'critical'},
                {'date': '2020-11-10', 'title': '纳思达：关于发行股份及支付现金购买资产之标的资产过户完成的公告',
                 'art_code': 'A4', 'importance': 'critical'},
            ],
        }
    }
    stories = build_deal_stories(sample, '002180')
    print(f'聚出 {len(stories)} 笔交易（输入 4 条公告）\n')
    for s in stories:
        print(render_story_markdown(s))