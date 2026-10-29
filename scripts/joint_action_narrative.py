# -*- coding: utf-8 -*-
"""
joint_action_narrative.py — 联合动作「三幕叙事」引擎
=====================================================

Skill 本质
---------
本 skill 的用途不是出一份"证券分析报告"，而是：

    采集一家上市公司**境内外联合动作**（并购、合资、引战、出海、股权变动、
    技术合作……）的海量数据，再用**叙事手法**讲述公司
        · 第一幕·过往  —— 从哪来（动作编年）
        · 第二幕·现状  —— 现在站在哪（此刻坐标）
        · 第三幕·下一步 —— 去哪（公司既定计划 + 财中推断机会）

证据骨架沿用五段式纪律：叙事里每句关于动作的事实，都带一手源 + 置信度；
缺口不编成结论（见 redline_gate）。

数据来源（均来自本 skill 既有采集模块的输出 JSON，无需重复采集）
----------------------------------------------------------------
  related_deals / related_deals.json          并购/重组/关联交易/要约等联合动作事件
  ma_deep / ma_deep.json                      收并购深度事件
  financing_structure / financing_structure.json  定增/引战/发债/股权激励
  subsidiary / subsidiary.json                子公司分拆/IPO 辅导
  capital / capital.json                      募资/套保/补流等资金动作
  cross_market(_discovery) / cross_market*.json  境内外关联实体（出海/跨境）
  strategic_opportunity / strategic_opportunity.json  年报 MD&A 既定战略计划
  capital_operation_inference / *.json         财中视角资本运作推断与机会
  announcements / announcements.json          重大公告（补充既定计划线索）

用法
----
  from scripts.joint_action_narrative import fetch_joint_action_narrative

  result = fetch_joint_action_narrative('002180', 'a', data_dir='output/002180_20261019/data')
  print(result['narrative_md'])  # 三幕叙事 Markdown

命令行
------
  python scripts/joint_action_narrative.py <股票代码> --market a --data-dir output/<code>_<date>/data
  # 产物：<data_dir>/joint_action_narrative.md  +  joint_action_narrative.json
"""
import sys
import os
import re
import json
import glob
from datetime import datetime
from typing import Dict, List, Optional, Any

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# ============================================================
# 1. 联合动作分类法（4 大类，对应 2026-10-19 用户确认范围）
# ============================================================

JOINT_ACTION_CATEGORIES = {
    'ma_restructure': {
        'label': '并购重组/资产交易',
        'subtypes': ['资产收购', '资产出售', '资产重组', '分拆上市', '借壳/反向收购', '吸收合并'],
    },
    'jv_cooperation': {
        'label': '合资/战略合作',
        'subtypes': ['合资/JV', '战略协议', '生态合作', '渠道合作', '技术合作'],
    },
    'financing': {
        'label': '融资/引战/定增',
        'subtypes': ['定向增发', '配股', '可转债', '引战投', '发债', '股权激励/员工持股'],
    },
    'global_equity_tech': {
        'label': '出海/股权/技术',
        'subtypes': ['海外产能/研发/渠道', '境外实体/SPV', '股权变动', '专利/技术合作'],
    },
}

# 分类关键词（用于把零散 title/type 归到大类）
_CLASSIFY_RULES = [
    ('ma_restructure', ['收购', '重组', '出售', '分拆', '借壳', '反向收购', '资产注入',
                        '资产置换', '并购', '合并', '剥离', '置出']),
    ('financing', ['定增', '增发', '配股', '可转债', '引战', '战略投资', '发债', '债券',
                   '股权激励', '员工持股', '募资', '配融']),
    ('jv_cooperation', ['合资', '合营', '战略合作', '战略协议', '战略合作协议', '生态',
                        '框架协议', '合作', '联合体']),
    ('global_equity_tech', ['境外', '海外', '出海', '香港', 'hk', '美国', '美股', '新加坡',
                            '开曼', 'bvi', '国际', '全球', 'spv', '专利', '技术合作',
                            '股权转让', '股权变动', '增持', '减持', '质押', '回购']),
]


def classify_category(text: str) -> str:
    """把一段文字归到 4 大类之一。命中多个时按规则优先级取首个。

    2026-10-19：修复"兜底全归并购重组"——实跑 002180 时「对外担保」
    「资产出售」等非并购动作被全部塞进 ma_restructure，导致第一幕
    "动作重心集中于并购重组"失真。现补关键词 + 兜底改判中性类。
    """
    t = (text or '').lower()
    for cat, kws in _CLASSIFY_RULES:
        if any(k in t for k in kws):
            return cat
    # 兜底：按语义就近归类，避免"什么都算并购"
    if re.search(r'(担保|授信|额度)', t):
        return 'financing'          # 对外担保属资金安排
    if re.search(r'(出售|转让|剥离|处置)', t):
        return 'ma_restructure'      # 资产处置仍属资产交易大类
    return 'jv_cooperation'          # 其余（合作/协议/其他）归中性类


_OVERSEAS_KW = ['境外', '海外', '出海', '香港', 'hong kong', 'hk', '美国', '美股', 'us',
                '新加坡', 'singapore', '开曼', 'cayman', 'bvi', '国际', 'global', '德国',
                '日本', '韩国', '欧洲', '东南亚', '越南', '印度', '墨西哥', '马来西亚',
                '泰国', '英国', '英国', '离岸']


def infer_geography(text: str) -> str:
    """推断动作地域：境内 / 境外·跨境。"""
    t = (text or '').lower()
    if any(k in t for k in _OVERSEAS_KW):
        return '境外·跨境'
    return '境内'


# ============================================================
# 2. 联合动作事件模型
# ============================================================

class JointActionEvent:
    """一条联合动作事件（叙事的最小事实单元）。"""

    __slots__ = ('date', 'category', 'subtype', 'title', 'parties', 'geography',
                 'amount', 'source_module', 'tier', 'confidence', 'summary',
                 'actionability', 'doc_role')

    def __init__(self, date=None, category='ma_restructure', subtype='', title='',
                 parties=None, geography='境内', amount='', source_module='', tier='T?',
                 confidence='🟡', summary='', actionability='action', doc_role=''):
        self.date = date                  # 'YYYY-MM-DD' / 'YYYY' / None
        self.category = category
        self.subtype = subtype
        self.title = title
        self.parties = parties or []       # 合作/交易对手方
        self.geography = geography
        self.amount = amount
        self.source_module = source_module
        self.tier = tier                  # 数据层级 T1-MCP / T2-OFFICIAL ...
        self.confidence = confidence       # 🟢 / 🟡 / 🔴
        self.summary = summary
        # 2026-10-19 审计：公告洪水过滤。actionability='action' 是真正的交易动作；
        # 'procedure' 是中介机构/程序性文件（进展公告/独立董事意见/核查意见…），默认不入时间线。
        self.actionability = actionability
        self.doc_role = doc_role

    def to_dict(self):
        return {
            'date': self.date,
            'category': self.category,
            'category_label': JOINT_ACTION_CATEGORIES.get(self.category, {}).get('label', self.category),
            'subtype': self.subtype,
            'title': self.title,
            'parties': self.parties,
            'geography': self.geography,
            'amount': self.amount,
            'source_module': self.source_module,
            'tier': self.tier,
            'confidence': self.confidence,
            'summary': self.summary,
            'actionability': self.actionability,
            'doc_role': self.doc_role,
        }


# ============================================================
# 2.5 公告洪水过滤（2026-10-19 审计 · 实跑暴露）
# ============================================================
# 实跑 002180 得 225 条"事件"，其中 **52% 是流程性文件**：
#   「独立董事关于…的独立意见」「持续督导意见」「法律意见书」「业绩承诺实现情况说明」
#   「申请受理的公告」「进展公告」「问询函回复」…
# 这些是**同一笔交易的程序副产品**，不是联合动作本身。全放进时间线 =
#   真正的"收购赛纳打印""引入大基金"被几百行文书埋掉，叙事彻底失效。
# 故按标题把公告分成两类：
#   action    —— 真正的交易/动作（成交、交割、签署、收购、增资、设立…）
#   procedure —— 程序性/中介机构文件（默认不入时间线，只计数）
PROCEDURE_PATTERNS = [
    (r'独立董事', '独立董事意见'),
    (r'法律意见书|法律意见|合规意见', '法律意见'),
    (r'核查意见|督导意见|持续督导', '中介核查'),
    (r'业绩承诺|盈利预测|实现情况', '业绩承诺文件'),
    (r'进展公告', '进展公告'),
    (r'问询函|反馈意见|回复|审核问询', '监管问询'),
    (r'备考|备考财务|模拟合并', '备考报表'),
    (r'报告书（草案）|报告书\(草案\)|报告书（修订稿）|报告书摘要|报告书\(修订稿\)', '重组报告书'),
    (r'发行过程|认购对象|发行方案|募集资金|验资', '发行文件'),
    (r'可行性分析|申请文件|备案|核准申请|受理的公告|注册批复|批复的公告', '审批文件'),
    (r'董事会决议|监事会决议|股东大会决议|表决结果|决议公告', '决议文件'),
    (r'停牌公告|复牌公告', '停复牌'),
    (r'风险提示|澄清公告|致歉公告|说明公告$', '程序性公告'),
    (r'摘要$|编号$', '摘要'),
    (r'授权委托|独立财务顾问|证券服务机构|评估机构|律师事务所|会计师事务所', '中介机构文件'),
    (r'价值评估|评估说明|评估报告|估值|审计报告|财务报表及审计|鉴证', '评估/审计文件'),
    (r'对照表|差异|附表|明细表|清单|汇总表', '数据附表'),
    (r'提示性公告|风险提示性|关注函|监管函|问询', '监管提示'),
    (r'筹划.{0,12}停牌前|停牌前一个交易日|前十(大|名)股东', '停牌配套披露'),
    (r'发行价格和发行数量|调整发行|定价基准日|发行方案.{0,6}调整', '发行调整'),
    (r'继续停牌', '继续停牌'),
    (r'(不构成|符合).{0,20}(规定|办法|指引|准则).{0,10}(条|款)?的?(说明|意见)', '合规自证文件'),
    (r'重组上市|重组管理|监管指引第?\d+号', '监管适用说明'),
    (r'重组报告书.{0,8}(修订|修正|修订说明)|修订说明的公告', '报告书修订'),
    (r'(完备性|合规性|有效性|合法性)', '程序性说明'),
    (r'差异对照表|附表|明细表|清单$|汇总表', '数据附表'),
]
_ACTION_HINTS = re.compile(
    r'(收购|购买|出售|转让|增资|投资|设立|成立|签署|达成|完成|交割|过户|终止|解除|'
    r'控股|并表|注入|置入|置出|借壳|重组|并购|合资|合作|协议|中标|授予|取得|剥离|退出|'
    r'放弃.{0,8}权|回购|减持|增持|质押|担保|配股|定增|发行股份|募集配套资金|关联交易|权益分派|'
    r'续聘|聘任|辞任|换届)')

_COMPILED_PROC = [(re.compile(p), role) for p, role in PROCEDURE_PATTERNS]


def classify_actionability(title: str) -> tuple:
    """
    判断一条公告是「真正的联合动作」还是「程序性文件」。

    Returns:
        ('action'|'procedure', doc_role)
        doc_role 为程序性文件的具体类别（action 时为 ''）

    规则（顺序敏感）：
      1. 命中任一程序性特征 → procedure（程序特征比动作词更具体，
         「关于重大资产重组的进展公告」含"重组"但仍是程序文件）
      2. 命中动作动词 → action
      3. 都不命中 → procedure / 未识别（保守：宁可不入主线，不编结论）
    """
    t = str(title or '').strip()
    if not t:
        return 'procedure', '空标题'
    for pat, role in _COMPILED_PROC:
        if pat.search(t):
            return 'procedure', role
    if _ACTION_HINTS.search(t):
        return 'action', ''
    return 'procedure', '未识别（保守排除）'

def _load_json(path: str) -> Optional[dict]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _load_named(data_dir: str, *names) -> Optional[dict]:
    """在 data_dir 中按文件名（含子串）取第一个存在的 JSON。"""
    if not data_dir:
        return None
    for name in names:
        # 直接匹配
        p = os.path.join(data_dir, name if name.endswith('.json') else name + '.json')
        d = _load_json(p)
        if d is not None:
            return d
        # 子串匹配
        matches = glob.glob(os.path.join(data_dir, '*' + name + '*.json'))
        for m in matches:
            d = _load_json(m)
            if d is not None:
                return d
    return None


def _load_findings(data_dir: str) -> dict:
    """优先 results.json['findings']，否则返回空。"""
    res = _load_named(data_dir, 'results')
    if isinstance(res, dict) and 'findings' in res:
        return res['findings'] or {}
    return {}


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# ============================================================
# 4. 事件抽取（从既有模块输出）
# ============================================================

def _norm_date(val) -> Optional[str]:
    if not val:
        return None
    s = str(val).strip()
    m = re.search(r'(\d{4})[-/年.]?(\d{1,2})?[-/月.]?(\d{1,2})?', s)
    if not m:
        return None
    y = m.group(1)
    mo = m.group(2)
    d = m.group(3)
    if mo and d:
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    if mo:
        return f"{y}-{int(mo):02d}"
    return y


def extract_events(data_dir: str) -> List[JointActionEvent]:
    """从既有模块输出中防御式抽取联合动作事件。"""
    findings = _load_findings(data_dir)
    events: List[JointActionEvent] = []

    # --- 4.1 related_deals：并购/重组/关联交易/要约 ---
    rd = findings.get('related_deals') or _load_named(data_dir, 'related_deals') or {}
    for d in _as_list(rd.get('deals')):
        if not isinstance(d, dict):
            continue
        title = d.get('title') or d.get('summary') or ''
        if not title:
            continue
        cat = classify_category(title + ' ' + str(d.get('type', '')))
        geo = d.get('geography') or infer_geography(title)
        events.append(JointActionEvent(
            date=_norm_date(d.get('date')),
            category=cat,
            subtype=str(d.get('type', '') or JOINT_ACTION_CATEGORIES[cat]['label']),
            title=title,
            parties=_as_list(d.get('parties')) if isinstance(d.get('parties'), (list,)) else [],
            geography=geo,
            amount=str(d.get('amount', '') or ''),
            source_module='related_deals',
            tier='T1-MCP' if d.get('_meta', {}).get('tier') else 'T2-OFFICIAL',
            confidence='🟢' if d.get('_meta', {}).get('source') else '🟡',
        ))

    # --- 4.2 ma_deep：收并购深度事件 ---
    md = findings.get('ma_deep') or _load_named(data_dir, 'ma_deep') or {}
    for d in _as_list(md.get('deals')):
        if not isinstance(d, dict):
            continue
        title = d.get('title') or d.get('name') or d.get('summary') or ''
        if not title:
            continue
        cat = classify_category(title + ' ' + str(d.get('type', '')))
        events.append(JointActionEvent(
            date=_norm_date(d.get('date')),
            category=cat,
            subtype=str(d.get('type', '') or '资产交易'),
            title=title,
            geography=d.get('geography') or infer_geography(title),
            amount=str(d.get('amount', '') or ''),
            source_module='ma_deep',
            tier='T1-MCP' if d.get('_meta', {}).get('tier') else 'T2-OFFICIAL',
            confidence='🟢' if d.get('_meta', {}).get('source') else '🟡',
        ))

    # --- 4.5 legal_risk / intellectual_property（qcc 权威源 · 2026-10-19 接线） ---
    # 这些不是"联合动作"，而是**现状幕的风险与资产底盘**：诉讼/质押/处罚/失信
    # 属被动发生的事实，须带 qcc 计数口径入叙事（未回填则不编）。
    lr = findings.get('legal_risk') or {}
    _sig = [s for s in _as_list(lr.get('signals')) if isinstance(s, dict) and (s.get('label') or s.get('domain'))]
    if _sig:
        sev = [s for s in _sig if s.get('level') == 'severe']
        defd = [s for s in _sig if '被告' in str(s.get('label', ''))]
        # 🔴 2026-10-19：质押口径必须走**明细来源**（stock_pledge/equity_pledge，
        # 有 active_count=当前在押）。risk_scan 的「股权质押 46 条」是**历史累计**
        # （含已解除），拿它当在押数会严重高估——实测 46 vs 真实在押 7。
        pled_detail = [s for s in _sig
                       if s.get('domain') in ('stock_pledge', 'equity_pledge')]
        pled_scan = [s for s in _sig if s.get('domain') == 'company_risk'
                     and ('质押' in str(s.get('label', ''))
                          or '出质' in str(s.get('label', '')))]
        pled = pled_detail if pled_detail else pled_scan
        parts = []
        if defd:
            parts.append("被诉方面：" + "；".join(s.get('statement') or s['label'] for s in defd))
        if sev:
            other = [s for s in sev if s not in defd]
            if other:
                parts.append("严重类风险维度：" + "；".join(
                    f"{s['label']} {s.get('count', '')} 条" for s in other))
        if pled:
            parts.append("股权质押/出质：" + "；".join(
                f"{s['label']} 在押 {s.get('count')} 条" for s in pled))
        unverified = [s for s in _sig if not s.get('corroborated')]
        tail = (f"（以上 {len(unverified)}/{len(_sig)} 项尚未获第二独立来源印证，属需核实的疑点）"
                if unverified else "（已获本地交叉印证）")
        events.append(JointActionEvent(
            date='',
            category=classify_category('合规风险 质押 诉讼 失信'),
            subtype='合规/法律风险（现状事实）',
            title='；'.join(parts) + tail,
            geography='境内',
            source_module='legal_risk',
            tier='T1-MCP',
            confidence='🟢' if any(s.get('corroborated') for s in sev) else '🟡',
        ))

    ip = findings.get('intellectual_property') or {}
    pat = ip.get('patent') or {}
    tmk = ip.get('trademark') or {}
    if pat.get('total') or tmk.get('total'):
        ip_bits = []
        if pat.get('tool_reported_total') or pat.get('total'):
            ip_bits.append(f"专利 {pat.get('tool_reported_total') or pat['total']} 条"
                           f"（在权/授权 {pat.get('in_force_count', 0)}，"
                           f"放弃或权终止 {pat.get('abandoned_or_terminated_count', 0)}）")
        if tmk.get('total'):
            ip_bits.append(f"商标 {tmk.get('tool_reported_total') or tmk['total']} 条"
                           f"（无效/驳回 {tmk.get('invalid_or_rejected_count', 0)}）")
        events.append(JointActionEvent(
            date='',
            category=classify_category('技术专利 商标 知识产权'),
            subtype='知识产权底盘（现状事实）',
            title='知识产权存量：' + '，'.join(ip_bits)
                  + '（"有 N 条"不等于"N 项在权壁垒"，评估壁垒以在权为准）',
            geography='境内',
            source_module='intellectual_property',
            tier='T1-MCP',
            confidence='🟢',
        ))

    # --- 4.3 financing_structure / capital：融资/引战/资金动作 ---
    for key, mod in [('financing_structure', 'financing_structure'), ('capital', 'capital')]:
        src = findings.get(key) or _load_named(data_dir, mod) or {}
        for d in _as_list(src.get('deals') or src.get('events') or src.get('items') or src.get('actions')):
            if not isinstance(d, dict):
                continue
            title = d.get('title') or d.get('name') or d.get('summary') or d.get('desc') or ''
            if not title:
                continue
            cat = classify_category(title)
            events.append(JointActionEvent(
                date=_norm_date(d.get('date')),
                category=cat,
                subtype=str(d.get('type', '') or JOINT_ACTION_CATEGORIES[cat]['label']),
                title=title,
                geography=d.get('geography') or infer_geography(title),
                amount=str(d.get('amount', '') or ''),
                source_module=mod,
                tier='T1-MCP' if d.get('_meta', {}).get('tier') else 'T2-OFFICIAL',
                confidence='🟢' if d.get('_meta', {}).get('source') else '🟡',
            ))

    # --- 4.4 subsidiary：子公司分拆/IPO 辅导 ---
    sub = findings.get('subsidiary') or findings.get('subsidiary_ipo') or _load_named(data_dir, 'subsidiary') or {}
    for s in _as_list(sub.get('csrc_tutoring') or sub.get('ipo_progress') or sub.get('list')):
        if not isinstance(s, dict):
            continue
        title = s.get('report_title') or s.get('company_name') or s.get('title') or ''
        if not title:
            continue
        events.append(JointActionEvent(
            date=_norm_date(s.get('date') or s.get('publish_time')),
            category='ma_restructure',
            subtype='分拆上市/IPO辅导',
            title=f"子公司 IPO 辅导：{title}",
            geography='境内',
            source_module='subsidiary',
            tier='T1-MCP' if s.get('_meta', {}).get('tier') else 'T2-OFFICIAL',
            confidence='🟢' if s.get('_meta', {}).get('source') else '🟡',
        ))

    # --- 4.5 cross_market：境内外关联实体（出海/跨境） ---
    cm = (findings.get('cross_market') or findings.get('cross_market_scan')
          or _load_named(data_dir, 'cross_market') or _load_named(data_dir, 'cross_market_discovery') or {})
    for f in _as_list(cm.get('final_findings') or cm.get('discovered_entities')):
        if not isinstance(f, dict):
            continue
        name = f.get('entity_name') or f.get('name') or f.get('listed_name') or ''
        if not name:
            continue
        rel = f.get('relation_type') or f.get('relation', '')
        conf = f.get('confidence', 'low')
        events.append(JointActionEvent(
            date=None,
            category='global_equity_tech',
            subtype='境外实体/SPV',
            title=f"境外/跨市场关联实体：{name}（{f.get('market','')} {f.get('code','')}）",
            parties=[rel] if rel else [],
            geography='境外·跨境',
            source_module='cross_market_discovery',
            tier='T1-MCP' if cm.get('_meta', {}).get('tier') else 'T2-OFFICIAL',
            confidence='🟢' if conf == 'high' else ('🟡' if conf == 'medium' else '🔴'),
        ))

    # --- 4.6 capital_operation_inference：确认层(第7层)公告信号 → 实事件 ---
    # 三落点合并（① findings ② findings.ai_analysis ③ 独立文件），与
    # extract_caizhong_inference 同源修复：旧版只读 ① 会漏掉另两路的 signals
    _coi_sigs = []
    for blob in (findings.get('capital_operation_inference') or {},
                 (findings.get('ai_analysis') or {}).get('capital_operation_inference') or {},
                 _load_named(data_dir, 'capital_operation_inference') or {}):
        if isinstance(blob, dict):
            for s in _as_list(blob.get('signals')):
                if isinstance(s, dict) and s not in _coi_sigs:
                    _coi_sigs.append(s)
    for s in _coi_sigs:
        if s.get('layer') != 7:   # 仅取"正式公告确认"信号，避免把推断当事实
            continue
        events.append(JointActionEvent(
            date=_norm_date(s.get('date')),
            category=classify_category(s.get('text', '')),
            subtype='公告确认',
            title=s.get('text', ''),
            geography=infer_geography(s.get('text', '')),
            source_module='capital_operation_inference',
            tier='T1-MCP' if s.get('_meta', {}).get('tier') else 'T2-OFFICIAL',
            confidence='🟢' if s.get('strength') == 'strong' else '🟡',
        ))

    # --- 4.7 deal_story_builder：把公告洪水聚合成「交易故事」（2026-10-19）
    # 🔴 动机：原先第一幕铺的是 ma_deep 公告**逐条**流水，实测 21 条"动作"里
    #   86% 是同一笔收购的不同程序公告——读者看到的是"公告标题流"，
    #   不是"公司干了什么"。这里改为聚合：1354 条公告 → 数十笔交易故事，
    #   每笔带阶段推进脉络（筹划→董事会→股东大会→监管→交割），这才有灵魂。
    story_events: List[JointActionEvent] = []
    covered_keys: set = set()
    try:
        from scripts.deal_story_builder import build_deal_stories
        _all_stories = build_deal_stories(findings, stock_code='__code__')
        for st in _all_stories:
            # 记录被该故事吸收的成员公告（用于后续从 ma_deep 流水中剔除）
            for m_ in st.get('members', []):
                if m_.get('date'):
                    covered_keys.add((m_['date'], (m_.get('title') or '')[:30]))
            if (st.get('member_count') or 0) < 3:
                continue      # 只有 1-2 份公告佐证的聚类不值得单列（证据不足）
            title = st.get('title', '')
            if not title:
                continue
            sd = st.get('stage_dates') or {}
            from scripts.deal_story_builder import STAGE_LABELS as _SL
            flow = ' → '.join(
                f"{sd[s]} {_SL.get(s, s)}" for s in
                ('proposed', 'board', 'shareholder', 'regulatory', 'completed', 'terminated')
                if s in sd)
            amt_txt = f"　金额 {st['amount']}" if st.get('amount') else ''
            story_events.append(JointActionEvent(
                date=st.get('first_date'),
                category=classify_category(title),
                subtype=f"交易故事（{st.get('member_count', 0)} 份公告佐证）",
                title=f"{title}{amt_txt}",
                summary=flow,
                geography='境内',
                amount='',          # 金额已在标题里，避免渲染时重复显示
                source_module='deal_story_builder',
                tier='T2-OFFICIAL',
                confidence=st.get('confidence', '🟡'),
            ))
    except Exception as _sexc:      # noqa: BLE001
        try:
            from scripts.silenced_errors import record
            record(__name__, 'extract_events', _sexc, note='交易故事聚合失败')
        except Exception:
            pass

    # 覆盖去重：已被交易故事吸收的公告条目不再单独入线。
    # 否则 172 条 ma_deep 公告会把 18 笔交易故事彻底淹没（实测正是如此）。
    # ⚠️ 匹配键必须两侧口径一致：ma_deep 的 title 带「纳思达：」前缀，
    #    而 deal_story 的 member title 已 _clean_title() 去掉前缀 → 直接比会全不匹配。
    if story_events and covered_keys:
        from scripts.deal_story_builder import _clean_title as _ct
        events = [e for e in events
                  if not (e.source_module in ('ma_deep', 'related_deals')
                          and e.date
                          and ((e.date, _ct(e.title)[:30]) in covered_keys
                               or (e.date, (e.title or '')[:30]) in covered_keys))]
    events.extend(story_events)


    # 去重（同 title + 同 date）+ 标注动作性
    seen, uniq = set(), []
    for e in events:
        k = (e.date, e.title[:40])
        if k in seen:
            continue
        seen.add(k)
        # 公告洪水过滤（2026-10-19）：qcc 现状事实强制入主线；其余按标题判定
        if e.source_module in ('legal_risk', 'intellectual_property'):
            e.actionability, e.doc_role = 'action', ''
        else:
            e.actionability, e.doc_role = classify_actionability(e.title)
        uniq.append(e)
    return uniq


def _extract_mdna_goals(fp_text: str) -> List[Dict[str, Any]]:
    """
    从年报 MD&A「公司未来发展的展望」原文抽取结构化计划条目。

    深交所年报格式（实测 002180）：
        十一、公司未来发展的展望
        （1）打印机全产业链业务发展与经营展望
        展望未来，公司打印机业务将持续扩大全球市场份额…
        （2）集成电路业务发展与经营展望
        …

    产出每条：{index, title, gist}，gist = 该分支首段的关键句（截断）。
    只做**抽取**不做改写——原文即证据，AI/渲染层不得生发。
    """
    if not fp_text or len(fp_text) < 40:
        return []
    text = fp_text.replace('\r', '')
    # 分支起点：（1）/（一）/1. 等
    pat = re.compile(r'（([1-9１-９])）\s*([^\n]{4,60})')
    ms = list(pat.finditer(text))
    out: List[Dict[str, Any]] = []
    for i, m in enumerate(ms):
        nxt = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        body = text[m.end():nxt].strip()
        # gist：取第一段中含"将/拟/计划/展望"的句子
        gist = ''
        for sent in re.split(r'[。；\n]', body):
            s = sent.strip()
            if len(s) >= 12 and re.search(r'(将|拟|计划|展望|持续|推进|加强|提升|布局)', s):
                gist = s + '。'
                break
        if not gist and body:
            gist = body[:80]
        out.append({'index': m.group(1), 'title': m.group(2).strip(), 'gist': gist})
    # 无编号层级时兜底：取含展望关键词的首段
    if not out:
        for sent in re.split(r'[。\n]', text):
            s = sent.strip()
            if len(s) >= 20 and re.search(r'(展望未来|公司将|公司将持续|发展战略)', s):
                out.append({'index': '1', 'title': '公司未来发展展望', 'gist': s + '。'})
                break
    return out


def extract_stated_plan(data_dir: str) -> Dict[str, Any]:
    """抽取'公司既定计划'（来自年报 MD&A + 公告），用于第三幕。"""
    findings = _load_findings(data_dir)
    so = findings.get('strategic_opportunity') or _load_named(data_dir, 'strategic_opportunity') or {}
    dims = so.get('dimensions', {}) if isinstance(so, dict) else {}
    sp = dims.get('strategic_positioning', {}) if isinstance(dims, dict) else {}

    goals = _as_list(sp.get('development_goals'))
    vision = sp.get('vision', '')
    industry_position = sp.get('industry_position', '')
    opportunities = _as_list(so.get('opportunities')) if isinstance(so, dict) else []

    # 🔴 2026-10-19：既定计划的第一数据源 = 年报 MD&A「公司未来发展的展望」
    # 实测 002180 修复前 mdda 只取到 443 字（被「重要提示」引述截断），
    # 修复后 34,910 字 → future_plan 章节有真实战略文本。
    # 这里做两件事：① 结构化抽成计划条目 ② 提供原文供 LLM/渲染兜底。
    ar_sections = _load_named(data_dir, 'annual_report_sections') or {}
    mdaa = ar_sections.get('mdaa') or ar_sections.get('future_plan') or ''
    mdaa_sections = ar_sections.get('mdaa_sections') or {}
    fp_text = mdaa_sections.get('future_plan') or ''
    mdna_goals = _extract_mdna_goals(fp_text) if fp_text else []

    # 公告里的"拟/将/计划"线索
    # 2026-10-19 审计：原实现只按"拟/将/计划 + 投资/建设/…"正则抓，
    # 结果把「董事会关于本次交易符合《重组管理办法》第十一条规定的说明」这类
    # **程序性文件**误当成"公司既定计划"（实跑 002180 4 条全是这类）。
    # 现复用 classify_actionability 二次过滤：程序性文件一律不进既定计划。
    anns = findings.get('announcements') or _load_named(data_dir, 'announcements') or {}
    plan_hits = []
    for a in _as_list(anns.get('critical_announcements') or anns.get('major_announcements') or anns.get('announcements')):
        if not isinstance(a, dict):
            continue
        t = a.get('title', '')
        if re.search(r'(拟|将|计划|预计|推进|加快|布局|规划)', t) and re.search(r'(投资|建设|设立|收购|合作|研发|扩产|上市)', t):
            act, _role = classify_actionability(t)
            if act != 'action':      # 洪水过滤：程序性文件不是"计划"
                continue
            plan_hits.append({'date': _norm_date(a.get('date') or a.get('publish_time')), 'title': t})
    plan_hits.sort(key=lambda x: x.get('date') or '', reverse=True)

    return {
        'vision': vision,
        'industry_position': industry_position,
        'development_goals': goals,
        'opportunities': opportunities,
        'announcement_plans': plan_hits[:8],
        # 供 build_narrative 判断 MD&A 是"抽了没提取到"还是"压根没抽章节"
        'annual_section_keys': list((_load_named(data_dir, 'annual_report_sections') or {}).keys()),
        # 🔴 2026-10-19 新增：年报 MD&A 原文与结构化计划条目
        'mdna_future_plan_text': fp_text,
        'mdna_goals': mdna_goals,
    }


def extract_caizhong_inference(data_dir: str) -> Dict[str, Any]:
    """
    抽取「财中视角：资本运作推断与机会」用于第三幕。

    🔴 2026-10-19 修复读取路径不一致（AI 推断拿不到的问题）
    ------------------------------------------------------------
    同一份 capital_operation_inference 数据有**三个落点**，旧版只读第一个：

      ① findings['capital_operation_inference']                 规则引擎（prelim）
      ② findings['ai_analysis']['capital_operation_inference']  ← 🔴 含 ai_analysis
      ③ data/capital_operation_inference.json                  独立文件

    `ai_unified_analyzer` 把 `infer_with_ai()` 的结果只挂在 ②（分析.py 阶段2），
    ①③ 只有 signals + preliminary_hypotheses。旧版读 ①③ → 第三幕永远拿不到
    LLM 推断，只能降级显示规则引擎初步假说。现在按优先级**合并三源**：
      ai_analysis：② 优先（最新且带 AI 推断），①③ 兜底
      preliminary_hypotheses / signals：三源取并集去重

    同时记录 `_provenance`（每部分来自哪个落点）与 `_diagnostics`（为什么缺），
    缺 AI 推断时把原因写进第三幕，而不是静默降级。
    """
    findings = _load_findings(data_dir)
    ai_root = findings.get('ai_analysis') or {}

    src_ai = ai_root.get('capital_operation_inference') or {}      # ②
    src_fin = findings.get('capital_operation_inference') or {}     # ①
    src_file = _load_named(data_dir, 'capital_operation_inference') or {}  # ③

    provenance = {}

    # ---- AI 推断：② 优先 → ① ③ 兜底 ----
    ai: Dict[str, Any] = {}
    for tag, blob in (('findings.ai_analysis', src_ai),
                      ('findings', src_fin),
                      ('capital_operation_inference.json', src_file)):
        if not isinstance(blob, dict):
            continue
        cand = blob.get('ai_analysis')
        if isinstance(cand, dict) and cand.get('hypotheses'):
            ai = cand
            provenance['ai_analysis'] = tag
            break
    if not ai:
        provenance['ai_analysis'] = None

    # ---- 规则引擎：① ③（② 是 ① 的超集副本） ----
    prelim = []
    for blob in (src_fin, src_file, src_ai):
        for h in _as_list(blob.get('preliminary_hypotheses') if isinstance(blob, dict) else None):
            if isinstance(h, dict) and h not in prelim:
                prelim.append(h)
    if prelim:
        provenance['preliminary_hypotheses'] = 'findings + capital_operation_inference.json'

    signal_count = 0
    for blob in (src_fin, src_file, src_ai):
        if isinstance(blob, dict) and blob.get('signal_count'):
            signal_count = blob['signal_count']
            break

    out = {
        'preliminary_hypotheses': prelim,
        'ai_hypotheses': _as_list(ai.get('hypotheses')),
        'signal_chain_analysis': ai.get('signal_chain_analysis', ''),
        'missing_signals': _as_list(ai.get('missing_signals')),
        'monitoring_checklist': _as_list(ai.get('monitoring_checklist')),
        'overall_assessment': ai.get('overall_assessment', ''),
        'signal_count': signal_count,
        '_provenance': provenance,
    }

    # ---- 诊断：为什么没有 AI 推断（写进第三幕，不静默降级）----
    diags = []
    if not out['ai_hypotheses']:
        if not signal_count and not prelim:
            diags.append('capital_operation_inference 未采集到任何资本运作信号'
                         '（须先跑 capital 维度，再由 ai_unified_analyzer 阶段2 触发 infer_with_ai）')
        elif not ai:
            diags.append('规则引擎已出初步假说，但 AI 推断（ai_analysis）缺失——'
                         '通常是 analyze.py 阶段2 未跑、红灯门禁跳过 AI，或 infer_with_ai 的 LLM 调用失败/返回非 JSON')
        else:
            diags.append('ai_analysis 已回填但 hypotheses 为空')
        if signal_count == 0:
            diags.append('提示：infer_with_ai 仅在 signal_count > 0 时触发，零信号时不会有 AI 推断')
    out['_diagnostics'] = diags
    return out


# ============================================================
# 5. 三幕叙事装配
# ============================================================

def _norm_conf(c) -> str:
    return {'high': '高', 'medium': '中', 'low': '低'}.get(str(c).lower(), str(c))


def _sort_events(events: List[JointActionEvent]):
    def key(e):
        if e.date:
            return (0, e.date)
        return (1, '')
    return sorted(events, key=key)


def build_narrative(stock_code: str, company_name: str, market: str,
                   events: List[JointActionEvent],
                   stated_plan: Dict[str, Any],
                   caizhong_inference: Dict[str, Any]) -> Dict[str, Any]:
    """把事件 + 计划/推断装配成三幕叙事结构（确定性，所有事实来自事件/源）。"""
    evs = _sort_events(events)
    undated = [e for e in evs if not e.date]
    # 🔴 口径隔离：qcc 法律/知识产权是"现状事实"，不是"联合动作"，
    # 不得计入第一幕的"可考动作共 N 条"（否则把诉讼/专利当成公司主动动作）
    FACT_MODULES = ('legal_risk', 'intellectual_property')
    fact_evs = [e for e in evs if e.source_module in FACT_MODULES]
    # 🔴 公告洪水过滤（2026-10-19 实跑暴露：225 条里 52% 是流程性文件）
    # 只有真正的交易动作进主线；程序性文件单独计数，供"证据厚度"参考，不铺进时间线
    non_fact = [e for e in evs if e.source_module not in FACT_MODULES]
    action_evs = [e for e in non_fact if e.actionability == 'action']
    proc_evs = [e for e in non_fact if e.actionability != 'action']
    dated = [e for e in action_evs if e.date]   # 动作编年只算有日期的联合动作

    # 聚合
    cat_counts: Dict[str, int] = {}
    geo_counts: Dict[str, int] = {}
    for e in action_evs:
        cat_counts[e.category] = cat_counts.get(e.category, 0) + 1
        geo_counts[e.geography] = geo_counts.get(e.geography, 0) + 1

    dated = [e for e in action_evs if e.date]   # 动作编年只算有日期的联合动作
    years = sorted({e.date[:4] for e in dated if e.date and len(e.date) >= 4})
    span = f"{years[0]}–{years[-1]}" if years else "（事件时间不全）"
    n_overseas = geo_counts.get('境外·跨境', 0)

    # 头条事件：优先并购/融资 + 强动作词，且取**最早**那笔（奠基性动作，
    # 不是最新的进展）。2026-10-19 审计：原实现取 dated[0]，2015 首个条目恰是
    #「董事会关于本次交易符合《重组规定》第四条的说明」，作头条不合适。
    headline = None
    strong = re.compile(r'(收购|购买|出售|增资|控股|交割|完成|注入|并购|重组上市|借壳|合资)')
    for e in dated:
        if e.category in ('ma_restructure', 'financing') and strong.search(e.title):
            headline = e
            break
    if not headline:
        for e in dated:
            if strong.search(e.title):
                headline = e
                break
    if not headline and dated:
        headline = dated[0]

    # ---------- 第一幕·过往 ----------
    if not action_evs:
        act1_overview = (
            f"{company_name}（{stock_code}）**本次采集未取得带日期的联合动作事件**"
            f"（可考动作 0 条）。缺口不得写成结论——"
            f"须补采 `related_deals` / `ma_deep` / `capital` / `cross_market_discovery` 等模块后重跑，"
            f"否则「过往轨迹」这一幕不具备可考证据。"
        )
    else:
        act1_overview = (
            f"自 {span} 起，{company_name}（{stock_code}）围绕资本与产业版图展开了一系列"
            f"境内外联合动作，可考动作事件共 {len(action_evs)} 条"
            + (f"，其中境外·跨境动作 {n_overseas} 条" if n_overseas else "")
            + "。动作重心集中于"
            + ("、".join(JOINT_ACTION_CATEGORIES[c]['label'] for c in cat_counts) or "（分类待补）")
            + "。"
        )
        if headline:
            hl_loc = "境外" if headline.geography == '境外·跨境' else "境内"
            act1_overview += (
                f"其中最具标志性的一笔是{hl_loc}的「{headline.title}」"
                f"（{headline.date or '时间待核'}，来源：{headline.source_module}）。"
            )
    if fact_evs:
        act1_overview += (
            f"（另有 {len(fact_evs)} 条法律/知识产权类**现状事实**不计入动作统计，"
            f"见第二幕风险与资产底盘。）"
        )
    if proc_evs:
        import collections as _c
        _roles = _c.Counter(e.doc_role or '程序性文件' for e in proc_evs)
        _top = "、".join(f"{k} {v} 条" for k, v in _roles.most_common(4))
        act1_overview += (
            f"（已滤除 {len(proc_evs)} 条程序性公告——{_top}——"
            f"这类文件是同一笔交易的程序副产品，不是独立动作，仅计入证据厚度。）"
        )

    # ---------- 第二幕·现状 ----------
    recent = dated[-5:] if dated else []
    recent_txt = "；".join(f"{e.date} {e.title}" for e in recent) if recent else "（近期动作数据不足）"
    act2_overview = (
        f"截至最新可考数据，{company_name}的联合动作版图已成型："
        + (f"公司自身定位为「{stated_plan.get('industry_position','')}」。" if stated_plan.get('industry_position') else "")
        + f"最近一轮可考动作为：{recent_txt}。"
    )
    if n_overseas:
        act2_overview += f"境外·跨境布局已渗透至 {n_overseas} 个可识别实体，出海与跨境资本运作成为其版图的显性特征。"

    act2_bullets = []
    # 现状事实底盘（qcc 法律/合规 + 知识产权）：被动发生的事实，不混入"动作"叙述
    _risk_ev = [e for e in undated if e.source_module == 'legal_risk']
    _ip_ev = [e for e in undated if e.source_module == 'intellectual_property']
    for e in _risk_ev + _ip_ev:
        act2_bullets.append(f"{e.subtype}：{e.title} _[源:{e.source_module} · {e.tier} · 置信{e.confidence}]_")
    if stated_plan.get('vision'):
        act2_bullets.append(f"战略愿景（公司披露）：{stated_plan['vision']}")
    if stated_plan.get('industry_position'):
        act2_bullets.append(f"行业坐标：{stated_plan['industry_position']}")
    if geo_counts:
        act2_bullets.append("动作地域分布：" + "，".join(f"{k} {v} 条" for k, v in geo_counts.items()))
    if n_overseas:
        act2_bullets.append(f"境外实体/SPV：{n_overseas} 个（详见跨境关联发现）")
    if not act2_bullets:
        act2_bullets.append("（现状坐标数据不足，需补采集）")

    # ---------- 第三幕·下一步 ----------
    act3_stated = []
    # 🔴 2026-10-19：第一顺位 = 年报 MD&A「公司未来发展的展望」（公司自述计划）
    mdna_goals = stated_plan.get('mdna_goals') or []
    for g in mdna_goals:
        t = g.get('title', '')
        gist = g.get('gist', '')
        act3_stated.append(f"**[{g.get('index','')}] {t}**"
                           + (f"（{g.get('source') or '年报MD&A'}）：{gist}" if gist else ""))
    # 第二顺位：strategic_opportunity 抽出的 development_goals
    for g in (stated_plan.get('development_goals') or []):
        act3_stated.append(f"{g}")
    # 第三顺位：公告里的"拟/将/计划"线索（经洪水过滤）
    if stated_plan.get('announcement_plans'):
        act3_stated.extend([f"[{p.get('date','?')}] {p.get('title','')}" for p in stated_plan['announcement_plans']])
    if not act3_stated:
        # 如实分级：区分「公告被洪水过滤掉」与「年报本就没抽 MD&A 章节」
        # （data_dir 不可用，从 stated_plan 带入的 annual_keys 判断）
        _ar_keys = stated_plan.get('annual_section_keys') or []
        _fp = stated_plan.get('mdna_future_plan_text') or ''
        _has_mdna = bool(_fp) and len(_fp) >= 40
        _note = (f"年报 MD&A 已抽出「公司未来发展的展望」{len(_fp)} 字，"
                 f"但未能切分出结构化目标" if _has_mdna else
                 f"**年报解析器未抽取 MD&A「公司未来发展的展望」章节**"
                 f"（已抽 {len(_ar_keys)} 个章节，无未来展望类）——这是数据层缺口，"
                 f"须扩 `scripts/pdf_download.py` / `annual_report_extractor.py` 的章节识别")
        _note = ("年报已抽出 MD&A 章节但未提取到发展目标" if _has_mdna else
                 f"**年报解析器未抽取 MD&A「发展展望/未来计划」章节**"
                 f"（已抽 {len(_ar_keys)} 个章节，无战略/展望类）——这是数据层缺口，"
                 f"须扩 `scripts/pdf_download.py` / `annual_report_extractor.py` 的章节识别")
        act3_stated.append(
            f"（公司既定计划披露不足：公告中「拟/将/计划 + 投资/建设/收购」条目"
            f"经洪水过滤后无可用项（多为程序性文件）。{_note}。缺口不得写成结论。）"
        )

    ci = caizhong_inference
    act3_inferred = []
    for h in ci.get('ai_hypotheses') or []:
        act3_inferred.append({
            'type': h.get('type', '未知'), 'confidence': _norm_conf(h.get('confidence', '中')),
            'logic': h.get('logic_chain', ''), 'next': h.get('expected_next', ''),
            'timeline': h.get('timeline', ''),
            'impact': h.get('impact_on_stock', ''),
            'origin': 'AI 推断',
        })
    for h in ci.get('preliminary_hypotheses') or []:
        act3_inferred.append({
            'type': h.get('type', '未知'), 'confidence': _norm_conf(h.get('confidence', '中')),
            'logic': h.get('logic', ''), 'next': '', 'timeline': '',
            'impact': '', 'origin': '规则引擎初步假说',
        })

    return {
        'stock_code': stock_code,
        'company_name': company_name,
        'market': market,
        'event_count': len(action_evs),
        'fact_count': len(fact_evs),
        'procedure_count': len(proc_evs),
        'span': span,
        'category_counts': cat_counts,
        'geo_counts': geo_counts,
        'act1': {'overview': act1_overview, 'events': [e.to_dict() for e in action_evs]},
        'act2': {'overview': act2_overview, 'bullets': act2_bullets,
                 'recent': [e.to_dict() for e in recent],
                 'facts': [e.to_dict() for e in fact_evs]},
        'act3': {
            'stated_plan': act3_stated,
            'caizhong_inference': act3_inferred,
            'signal_chain_analysis': ci.get('signal_chain_analysis', ''),
            'signal_count': ci.get('signal_count', 0),
            'missing_signals': ci.get('missing_signals', []),
            'monitoring_checklist': ci.get('monitoring_checklist', []),
            'overall_assessment': ci.get('overall_assessment', ''),
            'provenance': ci.get('_provenance', {}),
            'diagnostics': ci.get('_diagnostics', []),
        },
        'generated_at': datetime.now().isoformat(),
    }


# ============================================================
# 6. Markdown 渲染（每句事实带证据脚注）
# ============================================================

def _ev_line(e: dict) -> str:
    geo = f"〔{e['geography']}〕" if e['geography'] != '境内' else ""
    amt = f" · 金额 {e['amount']}" if e.get('amount') else ""
    flow = (f"\n    - 推进脉络：{e['summary']}" if e.get('summary') else "")
    return (f"- **{e.get('date') or '时间待核'}** 〔{e['category_label']}/{e.get('subtype','')}〕{geo}"
            f"{e.get('title','')}{amt}{flow}"
            f"  _[源:{e.get('source_module','')} · 置信{e.get('confidence','🟡')}]_")


def render_markdown(n: Dict[str, Any]) -> str:
    L = []
    L.append(f"# {n['company_name']}（{n['stock_code']}）· 联合动作三幕叙事")
    L.append("")
    L.append("> 本叙事由 listed-company-analysis 采集的境内外联合动作数据装配而成。"
             "每一笔动作均标注来源与置信度；**缺口不编结论**。")
    L.append("")
    L.append(f"**总览**：可考事件 {n['event_count']} 条 · 时间跨度 {n['span']} · "
             + " · ".join(f"{JOINT_ACTION_CATEGORIES[c]['label']} {v}" for c, v in n['category_counts'].items()))
    L.append("")

    # 第一幕
    L.append("## 第一幕 · 过往 —— 从哪来（动作编年）")
    L.append("")
    L.append(n['act1']['overview'])
    L.append("")
    L.append("### 动作时间线（证据）")
    L.append("")
    for e in n['act1']['events']:
        L.append(_ev_line(e))
    L.append("")

    # 第二幕
    L.append("## 第二幕 · 现状 —— 现在站在哪（此刻坐标）")
    L.append("")
    L.append(n['act2']['overview'])
    L.append("")
    L.append("### 当前坐标")
    L.append("")
    for b in n['act2']['bullets']:
        L.append(f"- {b}")
    L.append("")

    # 第三幕
    L.append("## 第三幕 · 下一步 —— 去哪（既定计划 + 财中推断）")
    L.append("")
    L.append("### 3.1 公司既定计划（来自公告/年报 MD&A）")
    L.append("")
    for s in n['act3']['stated_plan']:
        L.append(f"- {s}")
    L.append("")
    L.append("### 3.2 财中视角：资本运作机会与推断（非公司披露，仅供参考）")
    L.append("")
    a3 = n['act3']
    if a3.get('signal_chain_analysis'):
        L.append(f"**信号链分析**：{a3['signal_chain_analysis']}")
        L.append("")
    if a3.get('caizhong_inference'):
        L.append(f"*（基于 {a3.get('signal_count', 0)} 条资本运作信号；"
                 f"AI 推断来源：{(a3.get('provenance') or {}).get('ai_analysis') or '无'}）*")
        L.append("")
        for i, h in enumerate(a3['caizhong_inference'], 1):
            conf_icon = {'高': '🟢', '中': '🟡', '低': '⚪'}.get(h.get('confidence', '中'), '🟡')
            origin = h.get('origin', '')
            L.append(f"**推断{i}：{h.get('type','')}** {conf_icon} 置信{h.get('confidence','中')}"
                     + (f" _[{origin}]_" if origin else ""))
            if h.get('logic'):
                L.append(f"- 逻辑链：{h['logic']}")
            if h.get('next'):
                L.append(f"- 预期下一步：{h['next']}")
            if h.get('timeline'):
                L.append(f"- 时间窗口：{h['timeline']}")
            if h.get('impact'):
                L.append(f"- 股价影响路径：{h['impact']}")
            L.append("")
    else:
        L.append("- （暂无可用的资本运作推断）")
        for d in a3.get('diagnostics') or []:
            L.append(f"  - ⚠️ {d}")
        if not (a3.get('diagnostics') or []):
            L.append("  - 建议补充 cross_market_discovery + capital_operation_inference 采集")
    L.append("")
    if a3.get('diagnostics') and a3.get('caizhong_inference'):
        for d in a3['diagnostics']:
            L.append(f"> ⚠️ {d}")
        L.append("")
    if a3.get('overall_assessment'):
        L.append(f"**综合评估**：{a3['overall_assessment']}")
        L.append("")
    L.append("### 3.3 待验证缺口与跟踪要点（下一步动作）")
    L.append("")
    for m in n['act3']['missing_signals']:
        L.append(f"- ❓ 待补信号：{m}")
    for c in n['act3']['monitoring_checklist']:
        L.append(f"- 👁 跟踪要点：{c}")
    if not (n['act3']['missing_signals'] or n['act3']['monitoring_checklist']):
        L.append("- （无显著待验证缺口）")
    L.append("")
    L.append("---")
    L.append(f"_生成时间：{n['generated_at']} · 数据源：related_deals / ma_deep / financing_structure / "
             f"subsidiary / cross_market / strategic_opportunity / capital_operation_inference_")
    L.append("")
    L.append("_数据源分层：legal_risk / intellectual_property 为 **T1-MCP（qcc-company 工商权威源）**，"
             "其余动作类模块为 T2-OFFICIAL / T3-API 不等；"
             "qcc 计数为服务端聚合终值、**未跨维加总**，工具截断时占比不可外推。_")
    return "\n".join(L)


# ============================================================
# 6. HTML 渲染（2026-10-19 · 人类阅读首选交付物）
# ============================================================
# 为什么加 HTML：Markdown 是给机器/归档看的，人读要滚几十屏纯文本、
# 看不出层次。三幕叙事本质是"讲故事"，更需要版式承载。
# 设计取向（中性学术/研报风，**刻意不用任何品牌色**——本 skill 是通用
# 分析工具，不是某家机构的出品物；且智放本身非资本公司，不应承载金融 VI）：
#   · 衬线标题 + 无衬线正文，中文用系统字体栈（离线可读、打印友好）
#   · 三幕用色带区分（蓝/绿/琥珀，均为低饱和学术色）
#   · 证据脚注做成小号 tag，视觉上"退后"但不隐藏
#   · 时间线用左侧竖线 + 圆点，扫读友好
#   · 顶部关键指标卡，一眼看清规模
#   · 响应式 + @media print（A4 可直接打印/导出 PDF）

_CSS = """
:root{
  --ink:#1a1d21; --ink-2:#4a5158; --ink-3:#7b848c;
  --line:#e3e6ea; --line-2:#f0f2f4; --bg:#ffffff; --bg-2:#fafbfc;
  --act1:#3d5a80; --act1-bg:#f2f5f9;
  --act2:#2f6b5f; --act2-bg:#f1f7f5;
  --act3:#8a6520; --act3-bg:#faf6ee;
  --warn:#9c3d2e; --warn-bg:#fbf2f0;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg-2); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei",sans-serif;
  font-size:15px; line-height:1.75;
}
.page{max-width:920px; margin:0 auto; padding:48px 32px 96px; background:var(--bg)}
header.doc{border-bottom:2px solid var(--ink); padding-bottom:20px; margin-bottom:8px}
h1{font-size:26px; line-height:1.35; margin:0 0 8px; font-weight:600; letter-spacing:-.2px}
.sub{color:var(--ink-3); font-size:13px; font-family:ui-monospace,Menlo,Consolas,monospace}
.lede{margin:20px 0 28px; padding:14px 18px; background:var(--bg-2);
  border-left:3px solid var(--line); color:var(--ink-2); font-size:14px; border-radius:0 4px 4px 0}
.metrics{display:grid; grid-template-columns:repeat(auto-fit,minmax(118px,1fr));
  gap:12px; margin:0 0 40px}
.metric{border:1px solid var(--line); border-radius:6px; padding:12px 14px; background:var(--bg)}
.metric .k{font-size:11px; color:var(--ink-3); letter-spacing:.3px; margin-bottom:4px}
.metric .v{font-size:19px; font-weight:600; font-variant-numeric:tabular-nums; line-height:1.2}
section.act{margin:0 0 44px; border-radius:8px; overflow:hidden;
  border:1px solid var(--line); background:var(--bg)}
.act-head{padding:16px 22px; border-bottom:1px solid var(--line)}
.act-head h2{margin:0; font-size:19px; font-weight:600; letter-spacing:-.1px}
.act-head .q{color:var(--ink-3); font-size:13px; margin-top:3px}
.a1 .act-head{background:var(--act1-bg); border-left:4px solid var(--act1)}
.a2 .act-head{background:var(--act2-bg); border-left:4px solid var(--act2)}
.a3 .act-head{background:var(--act3-bg); border-left:4px solid var(--act3)}
.act-body{padding:22px}
.act-body h3{font-size:15px; font-weight:600; margin:26px 0 10px;
  padding-bottom:6px; border-bottom:1px solid var(--line-2)}
.act-body h3:first-child{margin-top:0}
.overview{font-size:15px; line-height:1.8; color:var(--ink); margin:0 0 4px}
.note{font-size:13px; color:var(--ink-3); margin:10px 0 0; line-height:1.7}
ul.b{list-style:none; padding:0; margin:12px 0 0}
ul.b>li{padding:9px 0 9px 20px; position:relative; border-bottom:1px solid var(--line-2)}
ul.b>li:last-child{border-bottom:0}
ul.b>li::before{content:""; position:absolute; left:2px; top:17px;
  width:5px; height:5px; border-radius:50%; background:var(--ink-3)}
ol.tl{list-style:none; padding:4px 0 0; margin:14px 0 0; border-left:2px solid var(--line); }
ol.tl>li{position:relative; padding:12px 0 12px 22px; border-bottom:1px solid var(--line-2)}
ol.tl>li:last-child{border-bottom:0}
ol.tl>li::before{content:""; position:absolute; left:-6px; top:20px;
  width:8px; height:8px; border-radius:50%; background:var(--act1);
  border:2px solid var(--bg)}
ol.tl .dt{font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12px;
  color:var(--act1); font-weight:600; letter-spacing:.2px}
ol.tl .tx{margin:3px 0 0; line-height:1.7}
ol.tl .flow{margin:5px 0 0; font-size:13px; color:var(--act1);
  padding-left:10px; border-left:2px solid var(--act1-bg); line-height:1.65}
.tag{display:inline-block; font-size:11px; line-height:1.6; padding:1px 7px;
  border-radius:3px; background:var(--line-2); color:var(--ink-2);
  margin-right:6px; vertical-align:1px; white-space:nowrap}
.tag.c{background:#eef2f7; color:var(--act1)}
.tag.geo{background:#f0f4f8; color:var(--ink-2)}
.tag.g{background:#e6f2ef; color:var(--act2)}
.tag.y{background:#faf1de; color:var(--act3)}
.tag.r{background:var(--warn-bg); color:var(--warn)}
.src{display:block; font-size:11px; color:var(--ink-3); margin-top:5px;
  font-family:ui-monospace,Menlo,Consolas,monospace}
.facts{margin:14px 0 0; padding:14px 18px; background:var(--warn-bg);
  border-radius:6px; border:1px solid #f0dedb}
.facts h4{margin:0 0 8px; font-size:13px; font-weight:600; color:var(--warn)}
.facts p{margin:0 0 8px; font-size:13.5px; line-height:1.7}
.facts p:last-child{margin-bottom:0}
.callout{margin:14px 0 0; padding:12px 16px; border:1px dashed var(--line);
  border-radius:6px; color:var(--ink-2); font-size:13.5px; background:var(--bg-2)}
.callout b{color:var(--warn)}
.hyp{border:1px solid var(--line); border-radius:6px; padding:14px 18px; margin:10px 0; background:var(--bg)}
.hyp .hd{display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; margin-bottom:6px}
.hyp .hd strong{font-size:15px; font-weight:600}
.hyp dl{margin:0; display:grid; grid-template-columns:max-content 1fr; gap:4px 14px; font-size:13.5px}
.hyp dt{color:var(--ink-3); white-space:nowrap}
.hyp dd{margin:0; line-height:1.65}
.empty{margin:12px 0 0; padding:12px 16px; background:var(--bg-2);
  border-left:3px solid var(--line); color:var(--ink-3); font-size:13.5px; border-radius:0 4px 4px 0}
.empty ul{margin:8px 0 0; padding-left:18px}
footer.doc{margin-top:44px; padding-top:18px; border-top:1px solid var(--line);
  font-size:12px; color:var(--ink-3); line-height:1.8}
@media (max-width:640px){
  .page{padding:28px 18px 64px}
  h1{font-size:21px} .act-head h2{font-size:17px}
  .hyp dl{grid-template-columns:1fr} .hyp dt{margin-top:4px}
}
@media print{
  body{background:#fff; font-size:11.5pt}
  .page{max-width:none; padding:0}
  section.act{break-inside:avoid; border-color:#ccc}
  .a1 .act-head,.a2 .act-head,.a3 .act-head{background:#f5f5f5 !important; -webkit-print-color-adjust:exact; print-color-adjust:exact}
  ol.tl>li::before{-webkit-print-color-adjust:exact; print-color-adjust:exact}
  .facts{-webkit-print-color-adjust:exact; print-color-adjust:exact}
}
"""


def _esc(s: Any) -> str:
    """
    HTML 转义——所有插值必须过这里（叙事文本含公告原文，不可信）。

    还负责**剥离 Markdown 残留**：结构里的若干字段（act1.overview、
    act3.stated_plan）由 build_narrative 用 Markdown 星号加粗，渲染进 HTML 时
    不能把 `**` 当字面量吐给读者 → 转成 <b> 或直接去掉。
    """
    s = '' if s is None else str(s)
    # **强调** → <b>（仅此处允许的富文本，其余一律纯文本）
    s = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
    s = (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
          .replace('"', '&quot;').replace("'", '&#39;'))
    # 上一步把 <b> 也转义了，这里还原（受控内容，非用户输入）
    s = s.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    return s


def _esc_t(s: Any) -> str:
    """纯文本转义（用于 overview 等含 Markdown 的长段落，去掉星号但不加粗）。"""
    s = '' if s is None else str(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)      # 去掉标记
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
             .replace('"', '&quot;').replace("'", '&#39;'))


def _conf_tag(conf: str) -> str:
    """置信度 → tag。🟢🟡🔴 语义色，无品牌色。"""
    m = {'🟢': ('g', '高置信'), '🟡': ('y', '中置信'), '🔴': ('r', '低置信')}
    cls, label = m.get(str(conf), ('y', '置信未标'))
    return f'<span class="tag {cls}">{label}</span>'


def render_html(n: Dict[str, Any]) -> str:
    """
    把三幕叙事渲染为独立可读 HTML（人类首选交付物）。

    与 render_markdown 的关系：**同源双渲染**——两者读同一个
    `build_narrative()` 返回的结构，事实完全一致，只是呈现媒介不同。
    HTML 不引入任何新事实（同样遵守"缺口不编结论"）。
    """
    if not n:
        return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<title>联合动作三幕叙事</title></head><body>'
                '<p>数据不足，未生成叙事。</p></body></html>')

    a1, a2, a3 = n['act1'], n['act2'], n['act3']
    prov = a3.get('provenance') or {}

    # ── 顶部指标卡 ──
    metrics = [
        ('可考动作', f"{n['event_count']} 条"),
        ('时间跨度', n.get('span') or '—'),
        ('现状事实', f"{n.get('fact_count', 0)} 条"),
        ('已滤程序公告', f"{n.get('procedure_count', 0)} 条"),
        ('推断条数', f"{len(a3.get('caizhong_inference') or [])} 条"),
    ]
    m_html = ''.join(
        f'<div class="metric"><div class="k">{_esc(k)}</div>'
        f'<div class="v">{_esc(v)}</div></div>' for k, v in metrics)

    P: List[str] = []
    P.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    P.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    P.append(f'<title>{_esc(n["company_name"])}（{_esc(n["stock_code"])}）'
             f'· 联合动作三幕叙事</title>')
    P.append(f'<style>{_CSS}</style></head><body><div class="page">')

    # ── 头部 ──
    P.append('<header class="doc">')
    P.append(f'<h1>{_esc(n["company_name"])}（{_esc(n["stock_code"])}）'
             f'· 联合动作三幕叙事</h1>')
    P.append(f'<div class="sub">市场 {_esc(n.get("market",""))} ｜ '
             f'生成于 {_esc(n.get("generated_at",""))}</div>')
    P.append('</header>')

    P.append('<div class="lede">本叙事由境内外<b>联合动作</b>数据装配而成——'
             '并购重组、合资合作、融资引战、出海与股权技术。'
             '每一笔动作均标注来源与置信度；'
             '<b>数据缺口不写成结论</b>。'
             '法律与知识产权数据来自工商权威源，其计数为服务端聚合终值、'
             '未跨维加总。</div>')

    P.append(f'<div class="metrics">{m_html}</div>')

    # ── 第一幕 ──
    P.append('<section class="act a1"><div class="act-head">'
             '<h2>第一幕 · 过往</h2>'
             '<div class="q">从哪来 —— 可考的联合动作编年</div></div>'
             '<div class="act-body">')
    P.append('<h3>轨迹概述</h3>')
    P.append(f'<p class="overview">{_esc_t(a1["overview"])}</p>')
    evs = a1.get('events') or []
    if evs:
        P.append('<h3>动作时间线</h3><ol class="tl">')
        for e in evs:
            date = e.get('date') or '时间待核'
            tags = f'<span class="tag c">{_esc(e.get("category_label",""))}</span>'
            if e.get('subtype'):
                tags += f'<span class="tag">{_esc(e["subtype"])}</span>'
            if e.get('geography') and e['geography'] != '境内':
                tags += f'<span class="tag geo">{_esc(e["geography"])}</span>'
            if e.get('amount'):
                tags += f'<span class="tag y">金额 {_esc(e["amount"])}</span>'
            amt = f'（金额 {_esc(e["amount"])}）' if e.get('amount') else ''
            P.append(f'<li><div class="dt">{_esc(date)}</div>'
                     f'<div>{tags}</div>'
                     f'<div class="tx">{_esc(e.get("title",""))}{amt}</div>'
                     + (f'<div class="flow">{_esc(e["summary"])}</div>'
                        if e.get('summary') else '')
                     + f'<span class="src">来源 {_esc(e.get("source_module",""))}'
                     f' · 数据层级 {_esc(e.get("tier",""))} · '
                     f'置信 {_esc(e.get("confidence",""))}</span></li>')
        P.append('</ol>')
    else:
        P.append('<div class="empty">未取得带日期的联合动作事件，'
                 '「过往轨迹」这一幕不具备可考证据。'
                 '需补采并购/资金/关联/跨境等模块后重跑。</div>')
    P.append('</div></section>')

    # ── 第二幕 ──
    P.append('<section class="act a2"><div class="act-head">'
             '<h2>第二幕 · 现状</h2>'
             '<div class="q">现在站在哪 —— 此刻坐标与风险底盘</div></div>'
             '<div class="act-body">')
    P.append('<h3>坐标概述</h3>')
    P.append(f'<p class="overview">{_esc_t(a2["overview"])}</p>')

    facts = a2.get('facts') or []
    if facts:
        P.append('<h3>风险与资产底盘</h3>')
        P.append('<div class="facts"><h4>以下为被动发生的现状事实，'
                 '非公司主动动作；计数为权威源原样引用</h4>')
        for f in facts:
            P.append(f'<p>{_esc_t(f.get("title",""))}'
                     f'<span class="src">来源 {_esc(f.get("source_module",""))}'
                     f' · {_esc(f.get("tier",""))} · 置信 {_esc(f.get("confidence",""))}'
                     f'</span></p>')
        P.append('</div>')

    bullets = [b for b in (a2.get('bullets') or [])
               if not any(f.get('source_module') in ('legal_risk', 'intellectual_property')
                          and b.startswith(f.get('subtype', '')) for f in facts)]
    if bullets:
        P.append('<h3>其他坐标</h3><ul class="b">')
        for b in bullets:
            P.append(f'<li>{_esc(b)}</li>')
        P.append('</ul>')
    P.append('</div></section>')

    # ── 第三幕 ──
    P.append('<section class="act a3"><div class="act-head">'
             '<h2>第三幕 · 下一步</h2>'
             '<div class="q">去哪 —— 公司既定计划与财中视角推断</div></div>'
             '<div class="act-body">')

    P.append('<h3>3.1 公司既定计划</h3>')
    P.append('<div class="callout" style="border-style:solid">'
             '来自公司自身披露（公告标题 / 年报 MD&A「公司未来发展的展望」），'
             '<b>属公司口径</b>。</div>')
    stated = a3.get('stated_plan') or []
    if stated:
        P.append('<ul class="b">')
        for s in stated:
            P.append(f'<li>{_esc(s)}</li>')     # 统一转义（不含任何预置 HTML）
        P.append('</ul>')

    P.append('<h3>3.2 财中视角：资本运作机会与推断</h3>')
    P.append('<div class="callout" style="border-style:solid">'
             '<b>非公司披露</b>，系基于公开信号的推断，仅供参考。</div>')
    hyps = a3.get('caizhong_inference') or []
    if hyps:
        if a3.get('signal_count'):
            src = (prov.get('ai_analysis') or '规则引擎')
            P.append(f'<div class="note">基于 {a3["signal_count"]} 条资本运作信号；'
                     f'推断来源：{_esc(src)}</div>')
        for i, h in enumerate(hyps, 1):
            P.append('<div class="hyp"><div class="hd">'
                     f'<strong>推断 {i} · {_esc(h.get("type",""))}</strong>'
                     + _conf_tag('🟢' if h.get('confidence') == '高' else
                                 ('🟡' if h.get('confidence') == '中' else '🔴'))
                     + f'<span class="tag">{_esc(h.get("origin",""))}</span>'
                     '</div><dl>')
            for label, key in (('逻辑链', 'logic'), ('预期下一步', 'next'),
                               ('时间窗口', 'timeline'), ('股价影响路径', 'impact')):
                if h.get(key):
                    P.append(f'<dt>{label}</dt><dd>{_esc(h[key])}</dd>')
            P.append('</dl></div>')
    else:
        P.append('<div class="empty">暂无可用的资本运作推断。<ul>')
        for d in (a3.get('diagnostics') or []):
            P.append(f'<li>{_esc(d)}</li>')
        P.append('</ul></div>')
    if a3.get('overall_assessment'):
        P.append('<h3>综合评估</h3>')
        P.append(f'<p class="overview">{_esc_t(a3["overall_assessment"])}</p>')
    for d in (a3.get('diagnostics') or []) if hyps else []:
        P.append(f'<div class="callout"><b>待补</b>：{_esc(d)}</div>')

    P.append('<h3>3.3 待验证缺口与跟踪要点</h3>')
    gaps = a3.get('missing_signals') or []
    mon = a3.get('monitoring_checklist') or []
    if gaps or mon:
        P.append('<ul class="b">')
        for g in gaps:
            P.append(f'<li><span class="tag r">待补信号</span>{_esc(g)}</li>')
        for m in mon:
            P.append(f'<li><span class="tag y">跟踪要点</span>{_esc(m)}</li>')
        P.append('</ul>')
    else:
        P.append('<div class="empty">无显著待验证缺口。</div>')

    P.append('</div></section>')

    # ── 页脚 ──
    P.append('<footer class="doc">')
    P.append('数据源：公告（巨潮/交易所）· 财务报表（东方财富）· '
             '工商权威数据（企查查：法律风险/知识产权）· 年报 MD&A。'
             '数据层级：T1-MCP 工商权威源 > T2-OFFICIAL 官方披露 > '
             'T3-API 公开接口 > T0 本地复合计算。<br>')
    P.append('纪律：计数逐字引用、绝不跨维加总；工具截断时占比不可外推至全量；'
             '单源不下实锤；缺口不写成结论。')
    P.append('</footer>')
    P.append('</div></body></html>')
    return '\n'.join(P)


# ============================================================
# 7. 入口
# ============================================================

def fetch_joint_action_narrative(stock_code: str, market: str = 'a',
                                 data_dir: str = None,
                                 company_name: str = '') -> Dict[str, Any]:
    """主入口：加载数据 → 抽取事件 → 装配三幕 → 渲染 → 落盘。"""
    result = {'stock_code': stock_code, 'market': market, 'success': False, 'error': None}

    if not data_dir or not os.path.isdir(data_dir):
        result['error'] = f"数据目录不存在：{data_dir}"
        return result

    # 公司名解析
    if not company_name:
        res = _load_named(data_dir, 'results')
        if isinstance(res, dict):
            company_name = (res.get('company_name_resolved')
                            or res.get('company_name') or '')
        if not company_name:
            # 从 structure / basic_info 取
            st = _load_named(data_dir, 'structure') or {}
            company_name = (st.get('company_profile', {}).get('name', '')
                            if isinstance(st, dict) else '')
    if not company_name:
        company_name = f"股票{stock_code}"

    events = extract_events(data_dir)
    stated_plan = extract_stated_plan(data_dir)
    caizhong_inference = extract_caizhong_inference(data_dir)

    narrative = build_narrative(stock_code, company_name, market, events, stated_plan, caizhong_inference)
    md = render_markdown(narrative)
    html = render_html(narrative)

    narrative['narrative_md'] = md
    narrative['narrative_html_path'] = None      # 落盘后回填
    result['narrative'] = narrative
    result['narrative_md'] = md
    result['narrative_html'] = html
    result['success'] = True

    # 落盘（HTML 为人类首选交付物；MD/JSON 供归档与机器消费）
    try:
        json_path = os.path.join(data_dir, 'joint_action_narrative.json')
        md_path = os.path.join(data_dir, 'joint_action_narrative.md')
        html_path = os.path.join(data_dir, 'joint_action_narrative.html')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(narrative, f, ensure_ascii=False, indent=2)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)
        narrative['narrative_html_path'] = html_path
        result['narrative_html_path'] = html_path
    except Exception as e:
        result['error'] = f"落盘失败：{e}"

    return result


def generate_report_section(narrative: dict) -> List[str]:
    """供 analyze.py 报告集成的章节渲染。"""
    if not narrative:
        return ["\n## 联合动作三幕叙事\n", "*数据不足，未生成叙事。*\n"]
    return render_markdown(narrative).split("\n")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='联合动作三幕叙事引擎')
    ap.add_argument('stock', help='股票代码')
    ap.add_argument('--market', default='a', help='市场 a/hk/us')
    ap.add_argument('--data-dir', required=True, help='analyze.py 产出的 data 目录')
    ap.add_argument('--company', default='', help='公司名（可选，默认自动解析）')
    ap.add_argument('--no-open', action='store_true', help='生成后不自动打开 HTML')
    args = ap.parse_args()

    r = fetch_joint_action_narrative(args.stock, args.market, args.data_dir, args.company)
    if not r['success']:
        print(f"❌ 失败：{r['error']}")
        sys.exit(1)

    n = r['narrative']
    print(f"✅ 三幕叙事生成完成"
          f"（动作 {n['event_count']} 条 · 现状事实 {n.get('fact_count',0)} 条"
          f" · 已滤程序公告 {n.get('procedure_count',0)} 条"
          f" · 跨度 {n['span']}）")
    d = args.data_dir
    print(f"   人类阅读（首选）：{os.path.join(d, 'joint_action_narrative.html')}")
    print(f"   归档/机器消费   ：{os.path.join(d, 'joint_action_narrative.md')}"
          f" / .json")

    if not args.no_open:
        # 在浏览器打开 HTML（Windows 用 os.startfile，macOS/Linux 用 open/xdg-open）
        hp = os.path.join(d, 'joint_action_narrative.html')
        try:
            if sys.platform.startswith('win'):
                os.startfile(hp)          # noqa: S606
            elif sys.platform == 'darwin':
                os.system(f'open "{hp}"')
            else:
                os.system(f'xdg-open "{hp}"')
        except Exception as e:
            print(f"   （自动打开失败，可手动打开：{e}）")
