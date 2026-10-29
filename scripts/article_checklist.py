# -*- coding: utf-8 -*-
"""
article_checklist.py — 写作前/后的强制检查清单（2026-10-20）

## 为什么需要它（三次被用户指出遗漏之后）

前三轮遗漏的教训，如果只写进 SKILL.md 的"注意事项"，等于没有约束力——
因为写作时我仍然会按既有路径走（财报 → 财务数字 → 结论），
而漏掉的恰恰是**财报之外的三个维度**：

  ① 决策动因（为什么卖/为什么买）  → 藏在《交易预案》的「背景和目的」
  ② 业务亮点（新客户/新赛道）      → 藏在《投资者关系活动记录表》
  ③ 资本运作（分拆/买壳/再融资）    → 藏在公告标题全量 + 港交所披露

本模块把这三条变成**可执行、可验证的检查项**，
每项给出 PASS / WARN / FAIL，FAIL 未清零不得交付。

## 两种用法

    # 写作前：检查数据底座是否齐备
    python scripts/article_checklist.py <data_dir>

    # 写作后：检查文章是否覆盖了关键要素
    python scripts/article_checklist.py <data_dir> --article 文章.md

## 检查项设计原则

- 只检查**能程序化判定**的（关键词命中 / 字段存在 / 数值口径）
- 不做语义判断（那要靠人），只回答"这块信息你有没有"
- 每个 FAIL 都给出**去哪找**的可执行路径
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

PASS, WARN, FAIL = '✅ PASS', '🟡 WARN', '❌ FAIL'


def _load(data_dir: str) -> Dict[str, Any]:
    return json.load(open(os.path.join(data_dir, 'results.json'), encoding='utf-8'))


def _all_anns(findings: Dict) -> List[Dict]:
    ann = findings.get('announcements') or {}
    out = []
    for k in ('critical_announcements', 'major_announcements', 'routine_announcements'):
        out += (ann.get(k) or [])
    return out


def _ir_texts(findings: Dict) -> List[Tuple[str, str]]:
    """收集投资者关系记录正文"""
    ann = findings.get('announcements') or {}
    out = []
    for a in _all_anns(findings):
        if '投资者' in (a.get('title') or ''):
            c = (a.get('content') or
                 (a.get('extracted_content') or {}).get('full_text_preview') or '')
            if c:
                out.append((f"{a.get('title')}({str(a.get('date'))[:10]})", c))
    for gname, items in ((ann.get('categories') or {}) or {}).items():
        if '投资者关系' in str(gname) and isinstance(items, list):
            for it in items:
                c = (it.get('content') if isinstance(it, dict) else '') or ''
                if c:
                    out.append((str(gname), c))
    return out


# ============================================================
# 检查项
# ============================================================

def check_decision_motive(f: Dict, anns: List[Dict],
                          article_path: str = None) -> List[Tuple[str, str, str]]:
    """
    A. 决策动因（为什么做这个决策）

    🔴 2026-10-20 修正场景错配：原实现只认「重大资产出售/购买预案」的
    《交易背景和目的》。遇到「控制权协议转让」类交易（实测法狮龙 605318）
    会误判 FAIL——它的动因在《详式权益变动报告书》第二节「权益变动的目的」，
    且该章节常在第 13 页之后，5000 字预览里根本取不到。

    改为：**先看文章有没有解释动因**（这才是交付要求），数据层章节作辅助证据。
    """
    res = []
    asset = [a for a in anns
             if re.search(r'出售|收购|重大资产|重组|预案', a.get('title') or '')]
    control = [a for a in anns
               if re.search(r'权益变动报告书|协议转让|表决权委托', a.get('title') or '')]
    if not asset and not control:
        return [('A1', PASS, '无重大交易/控制权转让类公告，本项不适用')]

    art = ''
    if article_path:
        try:
            art = open(article_path, encoding='utf-8').read()
        except Exception:
            pass

    MOTIVE_KW = ('为什么买', '为什么卖', '为什么做', '权益变动的目的', '权益变动目的',
                 '交易的目的', '决策动因', '内在价值的信心', '交易背景和目的', '背景和目的')
    art_hit = [k for k in MOTIVE_KW if k in art]
    data_hit = any(
        k in ((a.get('extracted_content') or {}).get('full_text_preview') or '')
        for a in (asset + control)
        for k in ('背景和目的', '交易目的', '权益变动的目的', '权益变动目的')
    )
    if art_hit:
        res.append(('A1', PASS, '文章已交代交易动因（命中：%s）' % '、'.join(art_hit[:2])))
    elif data_hit:
        res.append(('A1', PASS, '数据层含目的章节，文章需引用其原文'))
    else:
        res.append(('A1', FAIL,
                    '%d 条交易/控制权类公告，文章未交代动因'
                    ' → 须引用目的章节原文（资产交易查《预案》第一节；'
                    '控制权转让查《详式权益变动报告书》第二节「权益变动的目的」）'
                    % (len(asset) + len(control))))

    if control and not asset:
        # 控制权转让场景：查的是"多少钱一股、控制权怎么安排"
        prev = ' '.join(((a.get('extracted_content') or {}).get('full_text_preview') or '')
                        for a in control)
        has_price = bool(re.search(r'[0-9]+\.[0-9]+\s*元/股|每股转让价格|转让价款', prev))
        res.append(('A2', PASS if has_price else WARN,
                    '含每股转让价格与价款总额' if has_price
                    else '未见每股转让价格 → 控制权转让必须写清定价与对价总额'))
        has_ctl = ('表决权委托' in prev) or ('一致行动' in prev)
        res.append(('A3', PASS if has_ctl else WARN,
                    '含表决权委托/一致行动安排 → 已还原控制权实际归属' if has_ctl
                    else '未见表决权安排 → 只看持股比例会误判控制权归属'))
        return res

    # 资产出售/购买场景（原逻辑）
    has_target_fin = any(
        re.search(r'标的公司.{0,40}(净利润|资产负债率|营业收入)',
                  ((a.get('extracted_content') or {}).get('full_text_preview') or ''), re.S)
        for a in asset
    )
    res.append(('A2', PASS if has_target_fin else WARN,
                '含标的公司财务数据' if has_target_fin else '未见标的公司营收/净利/负债率 → 动因缺财务佐证'))

    has_price_caveat = any(
        re.search(r'(基准金额|预估.*对价|减去.*融资负债|净营运资金)',
                  ((a.get('extracted_content') or {}).get('full_text_preview') or ''))
        for a in asset
    )
    res.append(('A3', PASS if has_price_caveat else WARN,
                '公告含对价构成（基准金额/融资负债调整项）→ 可区分实收对价' if has_price_caveat
                else '未见对价构成说明 → 警惕把"基准金额"当"实收对价"写'))
    return res


def check_new_business(f: Dict, anns: List[Dict] = None) -> List[Tuple[str, str, str]]:
    """
    B. 业务亮点：IR 记录里的新客户/新赛道

    🔴 2026-10-20 加降级路径：实测法狮龙（605318）全市场**没有一份
    《投资者关系活动记录表》**，新业务只写在《对外投资设立子公司》公告
    与年报里。原实现在这种情况下直接 WARN 跳过，等于放弃检查。
    → 无 IR 时降级扫描"对外投资/设立/增资/定期报告"类公告全文。
    """
    res = []
    texts = _ir_texts(f)
    source = '投资者关系记录'
    if not texts and anns:
        for a in anns:
            t = a.get('title') or ''
            if not re.search(r'对外投资|设立|增资|子公司|年度报告|半年度报告', t):
                continue
            c = (a.get('content') or
                 (a.get('extracted_content') or {}).get('full_text_preview') or '')
            if c:
                texts.append((t[:34], c))
        source = '公告+年报（无 IR 记录，已降级）'
    if not texts:
        return [('B1', WARN,
                 '既无投资者关系记录，也无投资/年报类公告全文 → 新业务信息可能缺失')]

    joined = '\n'.join(t for _, t in texts)
    res.append(('B1', PASS, f'找到 {len(texts)} 份新业务信息来源（{source}）'))

    # 点名客户（"面向XX科技"、"XX等"）
    # 坑：原正则会把"面向工业自动化领域"里的"工业"当成客户名 → 需排除行业词
    _INDUSTRY_WORDS = {'工业', '汽车', '消费', '工业自动化', '机器人', '新能源',
                       '客户', '市场', '某机器人企业', '行业', '全球'}
    named = set(re.findall(r'面向([\u4e00-\u9fa5A-Za-z]{2,10}(?:科技|智能|技术|股份|电子)?)[、等]', joined))
    named = {n for n in named if n not in _INDUSTRY_WORDS and len(n) >= 3}
    res.append(('B2', PASS if named else WARN,
                f'点名客户：{"、".join(list(named)[:5])}' if named
                else '未见点名客户（只有"某客户"表述则信息量有限）'))

    # 产品型号
    models = set(re.findall(r'(?<![A-Za-z0-9])([A-Z]{1,4}\d{2,4}[A-Z]?\d{0,3})(?![A-Za-z0-9])', joined))
    res.append(('B3', PASS if models else WARN,
                f'产品型号：{"、".join(sorted(models)[:6])}' if models
                else '未见具体产品型号 → 技术描述可能是空话'))

    # 体内/体外
    outside = ('控股股东' in joined and ('旗下' in joined or '开展' in joined))
    res.append(('B4', PASS if outside else WARN,
                '已识别"控股股东体内"业务 → 可避免把体外资产算进上市公司' if outside
                else '未见"控股股东体内"提示 → 若公司提及其他板块，须自查是否在上市公司内'))
    return res


def check_capital_ops(f: Dict, anns: List[Dict]) -> List[Tuple[str, str, str]]:
    """C. 资本运作：分拆/买壳/再融资"""
    res = []
    split = [a for a in anns if '分拆' in (a.get('title') or '')]
    res.append(('C1', PASS if split else WARN,
                f'发现 {len(split)} 条分拆上市公告：' +
                '；'.join(f"{str(a.get('date'))[:10]} {a.get('title')[:32]}" for a in split[:2])
                if split else '未见分拆上市公告（若有需检查是否已终止）'))

    shell = [a for a in anns if re.search(r'要约|收购.*控股|买壳|借壳|境外.*上市|港股|H ?股',
                                          a.get('title') or '')]
    res.append(('C2', PASS if shell else WARN,
                f'发现 {len(shell)} 条壳/境外上市相关公告' if shell
                else 'A 股公告未见买壳/港股动作 → **必须另查港交所披露易 + IR 问答**（A 股未公告≠未发生）'))

    rename = [a for a in anns if re.search(r'变更公司名称|证券简称', a.get('title') or '')]
    res.append(('C3', PASS if rename else WARN,
                f'发现更名公告（战略转向信号）：{rename[-1].get("title","")[:40]}' if rename
                else '未见更名（若已更名需补查战略含义）'))
    return res


def check_number_caliber(f: Dict) -> List[Tuple[str, str, str]]:
    """D. 数字口径（这批 bug 的高发区）"""
    res = []
    gw = ((f.get('ma_deep') or {}).get('goodwill_analysis') or {})
    if gw.get('total_goodwill'):
        ratio = gw.get('goodwill_ratio')
        basis = gw.get('ratio_basis')
        has_beg = gw.get('goodwill_beginning')
        note = f"期末 {gw['total_goodwill']/1e8:.2f} 亿"
        if basis:
            note += f"（占{basis} {ratio:.1f}%）" if ratio else ''
        if has_beg:
            note += f"，期初 {has_beg/1e8:.2f} 亿"
        res.append(('D1', PASS, f'商誉口径明确：{note}'))

    lr = f.get('legal_risk') or {}
    ps = lr.get('pledge_stock') or {}
    if ps.get('total_records'):
        res.append(('D2', PASS if ps.get('active_count') is not None else FAIL,
                    f"质押：总记录 {ps['total_records']} 条，在押 {ps.get('active_count')} 条"
                    + ('（已区分累计 vs 在册）' if ps.get('active_count') is not None
                       else '（未区分在押/已解除 → 高危）')))

    # 盈利预测是否把半年报当年度
    ef = f.get('earnings_forecast') or {}
    bm = ((ef.get('forecast') or {}).get('base_metrics') or {})
    if bm.get('partial_years_excluded'):
        res.append(('D3', PASS, f"盈利预测已排除半年度年份：{bm['partial_years_excluded']}"))

    # --- D4：DCF 是否用真实营收（防回退到默认 100 亿）---
    dcf = ((f.get('valuation') or {}).get('dcf') or {})
    rev = dcf.get('revenue_base_亿')
    missing = dcf.get('data_missing')
    if missing:
        res.append(('D4', PASS, f"DCF 已标数据缺失，拒绝估算（{dcf.get('missing_reason','')[:40]}）"))
    elif rev is not None:
        # 100 亿 / 10% 是历史默认值，出现即为回退
        if abs(rev - 100.0) < 0.01 and abs((dcf.get('net_margin_pct') or 0) - 10.0) < 0.01:
            res.append(('D4', FAIL, 'DCF 基准疑似回退到默认值（营收 100 亿 / 净利率 10%）'))
        else:
            res.append(('D4', PASS,
                        f"DCF 用真实基准：营收 {rev} 亿 / 净利率 {dcf.get('net_margin_pct')}%"))

    # --- D5：MA 评分与风险判定是否自相矛盾（防回退到满分）---
    md = f.get('ma_deep') or {}
    score = md.get('ma_score')
    risk = ((md.get('risk_analysis') or {}).get('overall_risk'))
    if score is not None:
        if risk == '高' and score >= 70:
            res.append(('D5', FAIL, f'口径矛盾：整体风险「高」却给 {score} 分（应封顶 69）'))
        else:
            res.append(('D5', PASS, f'MA 评分 {score} 与整体风险「{risk}」自洽'))

    # --- D6：关联交易占比是否臆造（防回退到硬编码 50%）---
    vc = f.get('value_chain') or {}
    ratio = ((vc.get('upstream') or {}).get('related_supplier_ratio'))
    if ratio is not None:
        if abs(float(ratio) - 50.0) < 0.01:
            res.append(('D6', FAIL, '关联供应商占比为 50.0 —— 疑似回退到硬编码假设值'))
        else:
            res.append(('D6', PASS, f'关联供应商占比 {ratio}%（有实际来源）'))
    elif 'related_supplier_ratio' in (vc.get('upstream') or {}):
        res.append(('D6', PASS, '关联供应商占比未披露 → 正确置 None，未臆造'))

    return res


def check_article_coverage(article_path: str, f: Dict) -> List[Tuple[str, str, str]]:
    """E. 文章覆盖度（写作后）

    🔴 2026-10-20 重要修正：第一版用**泛关键词**判断（"芯片""收购""原因"），
    结果拿**有遗漏的旧版文章**去跑也是全 PASS —— 因为"收购"命中的是"收购利盟"，
    而不是"港股买壳"；"芯片"命中的是业务描述，而不是"宇树供货"。
    **关键词命中 ≠ 内容覆盖**，这种检查器等于摆设。

    现改为**动态实体校验**：从数据层实际抽到的实体（点名客户、分拆公告、
    港股信号、产品型号）反向去文章里找。数据里有、文章里没有 → FAIL。
    """
    txt = open(article_path, encoding='utf-8').read()
    res = []

    # --- E1 点名客户必须在文中出现 ---
    texts = _ir_texts(f)
    joined = '\n'.join(t for _, t in texts)
    _INDUSTRY = {'工业', '汽车', '消费', '工业自动化', '机器人', '新能源',
                 '客户', '市场', '某机器人企业', '行业', '全球'}
    named = {n for n in re.findall(r'面向([\u4e00-\u9fa5A-Za-z]{2,10}(?:科技|智能|技术|股份|电子)?)[、等]', joined)
             if n not in _INDUSTRY and len(n) >= 3}
    if named:
        missing = [n for n in named if n not in txt]
        res.append(('E1', PASS if not missing else FAIL,
                    f'点名客户已写入：{"、".join(n for n in named if n in txt)}' if not missing
                    else f'数据里有客户但文章未提：{missing} → 这是估值溢价来源，必须写'))
    else:
        res.append(('E1', WARN, '数据层未抽到点名客户，本项不适用'))

    # --- E2 产品型号必须出现（至少一个）---
    models = {m for m in re.findall(r'(?<![A-Za-z0-9])([A-Z]{1,4}\d{2,4}[A-Z]?\d{0,3})(?![A-Za-z0-9])',
                                    joined) if len(m) >= 5}
    if models:
        hit = [m for m in models if m in txt]
        res.append(('E2', PASS if hit else WARN,
                    f'产品型号已写入：{hit[:4]}' if hit
                    else f'数据有型号 {sorted(models)[:4]} 但文中未提 → 技术描述可能空泛'))
    else:
        res.append(('E2', WARN, '数据层未抽到产品型号，本项不适用'))

    # --- E3 分拆上市必须在文中出现 ---
    split = [a for a in _all_anns(f) if '分拆' in (a.get('title') or '')]
    if split:
        ok = ('分拆' in txt)
        res.append(('E3', PASS if ok else FAIL,
                    '已写入分拆上市事项' if ok
                    else '数据里有分拆上市公告，文章未提 → 这是资本主线，必须写'))

    # --- E4 境外/港股平台必须出现 ---
    hk_signal = re.search(r'港股|06939|美佳音|借壳|要约|H ?股', joined)
    if hk_signal:
        hit = re.search(r'港股|06939|美佳音|借壳|要约|H ?股', txt)
        res.append(('E4', PASS if hit else FAIL,
                    f'已写入境外平台（命中「{hit.group(0)}」）' if hit
                    else 'IR/公告里有境外上市信号，文章未提 → 查港交所披露'))

    # --- E5 决策动因：必须出现"为什么/原因"且带具体动因词 ---
    has_why = re.search(r'(为什么|原因|动机)', txt)
    has_driver = re.search(r'(外部环境|减值|亏损|负债|监管|审查|债务|现金流)', txt)
    res.append(('E5', PASS if (has_why and has_driver) else FAIL,
                '含动因论述（为什么 + 具体驱动力）' if (has_why and has_driver)
                else '缺决策动因：只有"做了什么"，没写"为什么"'))

    # --- E6 估值口径 ---
    has_val = re.search(r'(PB|PS|PE|市值|估值)', txt)
    res.append(('E6', PASS if has_val else FAIL, '含估值口径' if has_val else '缺估值口径'))

    # --- E7 风险/不确定性 ---
    has_risk = re.search(r'(风险|不确定|诉讼|仲裁|审批)', txt)
    res.append(('E7', PASS if has_risk else FAIL, '含风险提示' if has_risk else '缺风险提示'))

    # --- E8 无台账式字段 ---
    bad = [b for b in ('份公告佐证', '走完 3 个阶段', '数据层级 T', '置信 🟢') if b in txt]
    res.append(('E8', PASS if not bad else FAIL,
                '无台账式字段' if not bad else f'出现台账字段：{bad}'))
    return res


def check_tech_benchmark(f: Dict, article_path: str = None,
                         data_dir: str = None) -> List[Tuple[str, str, str]]:
    """F. 技术对标候选（解决「靠人读」的问题）

    🔴 承认现实：**"可覆盖 TI C2000" 这类表述的对错，程序判断不了**——
    要么懂这个行业，要么去查 TI C2000 到底是什么。

    但可以做到两件事，把"人要读整篇文章"降为"人只看 8 条候选"：
      ① **程序化定位**：把所有"对标/替代/首创/填补/达到…水平"的句子全抽出来；
      ② **反向校验**：文章里一旦出现这类表述，必须能在原文找到对应句
         （防"我编了一个听起来很厉害的技术对标"）。

    这样人只需要判断「这几条对标是不是真的、能不能打」，不用去翻 1500 条公告。
    """
    res = []
    texts = [t for _, t in _ir_texts(f)]
    # 🔴 源文本必须覆盖**全量数据**，不只是 IR 记录：
    # 首次实现只用了 IR + 几个维度 → 把"R50x 可覆盖 TI C2000"误判成自撰，
    # 因为该句在 routine_announcements 的正文里（标题不是"投资者关系"）。
    texts.append(json.dumps(f, ensure_ascii=False))
    # 年报章节也要算（"中国南北极考察选用产品"就在年报社会责任段）
    for fn in ('annual_report_sections.json',):
        p = os.path.join(data_dir, fn) if data_dir else None
        if p and os.path.exists(p):
            try:
                texts.append(open(p, encoding='utf-8').read())
            except Exception:
                pass
    # 🔴 MCP 深解析的公告全文（mcp_mineru/*.md）必须纳入校验源。
    # 否则"引号引用"会因为源文本没落盘而被判成"自撰"——
    # 实测踩过：预案全文只在 tool-results 里，没进 data_dir → 15 处误报。
    if data_dir:
        mdir = os.path.join(data_dir, 'mcp_mineru')
        if os.path.isdir(mdir):
            for fn in os.listdir(mdir):
                if fn.endswith('.md'):
                    try:
                        texts.append(open(os.path.join(mdir, fn), encoding='utf-8').read())
                    except Exception:
                        pass
    joined = '\n'.join(texts)

    # 五类对标句式
    PATTERNS = {
        '对标/替代': r'[^。；\n]{0,40}(?:可覆盖|对标|替代|兼容|pin.?to.?pin)[^。；\n]{0,60}',
        '首创/唯一': r'[^。；\n]{0,30}(?:全球首款|国内首款|行业首款|全球首创|国内首创|唯一)[^。；\n]{0,60}',
        '差距/水平': r'[^。；\n]{0,30}(?:达到[^。；\n]{0,12}水平|接近[^。；\n]{0,15}|落后[^。；\n]{0,15}|领先[^。；\n]{0,15})',
        '填补/打破': r'[^。；\n]{0,30}(?:填补[^。；\n]{0,20}空白|打破[^。；\n]{0,20}垄断)[^。；\n]{0,40}',
        '认证/入选': r'[^。；\n]{0,30}(?:通过[^。；\n]{0,15}认证|入选[^。；\n]{0,25}|获评[^。；\n]{0,25})',
    }

    found: Dict[str, List[str]] = {}
    for label, pat in PATTERNS.items():
        hits = []
        for m in re.finditer(pat, joined):
            s = m.group(0).strip()
            if len(s) < 12:
                continue
            if s not in hits:
                hits.append(s)
        if hits:
            found[label] = hits[:4]

    if not found:
        res.append(('F1', WARN, '数据层未见技术对标类表述（可能确实没有，也可能源头没抓到）'))
        return res

    total = sum(len(v) for v in found.values())
    res.append(('F1', PASS, f'抽出 {total} 条对标类表述，待人工判定真伪：'))
    for label, hits in found.items():
        for h in hits:
            res.append(('  ', '   ', f'[{label}] {h[:88]}'))

    # 反向校验：**只查引号里的内容**（引号＝原文引用，这是硬约束）
    # 🔴 设计修正：第一版把所有"对标类句式"整句拿去比对，结果把作者的评论
    # （"奔图在国产品牌打印机里有真份额"）也当成"需要出处"，产生大量误报。
    # 正确边界：作者判断不需要出处；**打了引号的文字必须是原文**。
    if article_path:
        def _clean(s: str) -> str:
            # 🔴 json.dumps 会把真换行转义成字面量 "\\n"（反斜杠+n），
            # 正则 \s 匹配不到 → 必须先替换掉，否则"中国\n南北极"永远对不上。
            s = s.replace('\\n', '').replace('\\t', '').replace('\\r', '')
            return re.sub(r'[\u00a0\s]+', '', s)

        txt = open(article_path, encoding='utf-8').read()
        src_c = _clean(joined)
        # 抽「」与""内的引用（限 6–60 字，过长多半是段落引用，另作别论）
        quotes = re.findall(r'「([^」]{6,60})」', txt)
        quotes += re.findall(r'“([^”]{6,60})”', txt)
        if quotes:
            bad = []
            for q in quotes:
                q_c = _clean(q)
                # 引用允许被编辑压缩，用"12 字滑窗命中率"判断：任一段 12 字连续命中即视为有源
                hit = any(q_c[i:i + 12] in src_c for i in range(0, max(1, len(q_c) - 11)))
                if not hit and len(q_c) >= 10:
                    bad.append(q)
            res.append(('F2', PASS if not bad else FAIL,
                        f'文中 {len(quotes)} 处引号引用均可回溯原文' if not bad
                        else f'{len(bad)} 处引号内容在数据源找不到（疑似把转述写成引用）：'
                             + '；'.join(f'「{b[:36]}」' for b in bad[:3])))
    return res


# ============================================================

def check_first_mention(article_path: str) -> List[Tuple[str, str, str]]:
    """
    H. 首次提及必须交代出处（2026-10-20 用户指出行文倒错后新增）

    问题原形（实测）：
      line 49  「预案里写得直白，中方中介机构……」
      line 57  「2025 年 3 月的《重大资产出售预案》把理由列得很清楚」
    → 第一次用简称时读者不知道是哪份预案，15 行后才交代。

    规则：泛指文件词（预案/报告书/草案/说明书）的**首次出现**所在段落，
    必须带具体文件名（《…》）或披露日期（20xx 年），否则 FAIL。
    「年报」「公告」这类通用词不查——读者默认指最新一期，不产生歧义。
    """
    txt = open(article_path, encoding='utf-8').read()
    paras = re.split(r'\n\s*\n', txt)
    res = []
    VAGUE = ['预案', '报告书', '草案', '说明书']

    for w in VAGUE:
        # 找首次出现所在段落
        hit = None
        for pi, p in enumerate(paras):
            if w in p:
                hit = (pi, p)
                break
        if not hit:
            continue
        pi, p = hit
        # 段落内是否有具体文件标识
        has_title = '《' in p
        has_date = bool(re.search(r'20\d{2}\s*年', p))
        if has_title or has_date:
            continue
        # 代词回指（「该预案」「这份预案」）且前文已有《》→ 不算违规
        idx = p.find(w)
        prev = ''.join(paras[:pi])
        if '《' in prev and p[max(0, idx - 3):idx] in ('该', '这份', '此', '上述'):
            continue
        snippet = p[max(0, idx - 30):idx + 40].replace('\n', ' ')
        res.append(('H1', FAIL,
                    f'「{w}」首次出现未交代出处（第 {len("".join(paras[:pi]).split(chr(10)))+1} 段）：'
                    f'…{snippet}… → 首次出现须给《文件名》或披露日期'))

    if not res:
        res.append(('H1', PASS, '泛指文件词（预案/报告书/草案/说明书）首次出现均已交代出处'))
    return res


# ---------------------------------------------------------------------------
# I 组：缺口守门（证据包「已知缺口」禁编造清单的程序化兜底）
# ---------------------------------------------------------------------------
# 维度关键词映射：只扫这些维度在正文里的"量化 / 动因推断"表述
_GAP_KEYWORDS = {
    'earnings_forecast': ['盈利预测', '业绩预测', '预测净利', '预测营收', '预测收入'],
    'legal_risk': ['诉讼', '仲裁', '行政处罚', '法律纠纷', '立案调查'],
    'intellectual_property': ['专利', '商标', '知识产权'],
    '法律/IP风险': ['诉讼', '专利', '商标', '行政处罚', '知识产权'],
    '商誉': ['商誉'],
    '目标价': ['目标价', '目标价位', '估值区间'],
}
_NUM_RE = re.compile(r'\d+(?:\.\d+)?\s*(?:亿|万|元|倍|%|％)')
_MOTIVE_RE = re.compile(r'(为了|因为|出于|旨在|看中|相中|为.*战略|押注|赌.*转型)')
_TXN_RE = re.compile(r'(转让|过户|易主|控制权|协议转让|出售|收购|要约)')
# 🔴 全年预测白名单：凡显式标注为"透明算术外推"的句子（季节性外推/非承诺/年化示意/
#    按节奏外推），是证据包"最新报告期→全年预测"的合规落地，不作为缺口维度编造 WARN。
#    无透明度标注的裸预测（如"预测明年营收10亿"）仍照常 WARN。
_FORECAST_OK_RE = re.compile(
    r'(全年.{0,6}预测|季节性外推|线性外推|年化|非承诺|仅为示意|仅供参考|按.{0,4}节奏|外推|滚动12个月|TTM)')


def check_gap_guard(article_path: str, data_dir: str) -> List[Tuple[str, str, str]]:
    """I 组：核对文章是否编造了 evidence_pack「已知缺口」清单里的维度。

    evidence_pack.json 的 known_gaps 是「禁编造清单」。Agent 撰写层已被告知禁止编造，
    本组做程序化兜底：若正文在缺口维度上出现量化表述，或对缺失动因做了推断性表述，
    立即 WARN，提示人工确认 / 删除。不依赖外部模型，只看正文与清单的交集。
    """
    ep = os.path.join(data_dir, 'evidence_pack.json')
    if not os.path.exists(ep):
        return [('I0', WARN, '未找到 evidence_pack.json，缺口守门跳过；请先跑 article_brief.py 生成证据包')]
    try:
        pack = json.load(open(ep, encoding='utf-8'))
    except Exception as e:
        return [('I0', WARN, f'证据包解析失败：{e}')]
    gaps = (pack.get('evidence', {}).get('known_gaps') or [])
    if not gaps:
        return [('I0', PASS, '证据包无已知缺口，缺口守门通过')]

    text = ''
    if article_path and os.path.exists(article_path):
        try:
            text = open(article_path, encoding='utf-8').read()
        except Exception:
            text = ''
    if not text:
        return [('I0', WARN, '未提供文章或文章读取失败，缺口守门仅能检查清单存在性')]

    # 仅对"真实缺口"做守门（排除已显式标注为已覆盖的项）
    real_gaps = [g for g in gaps if g.get('status') not in ('已覆盖', 'OK', 'ok', '正常')]
    items = []
    sentences = re.split(r'[。！？\n;；]', text)
    seen = set()
    for g in real_gaps:
        dim = g.get('dimension', '')
        kws = _GAP_KEYWORDS.get(dim)
        if kws is None:
            continue  # 未知维度不扫描，避免误报
        for kw in kws:
            for s in sentences:
                if kw in s and _NUM_RE.search(s):
                    # 显式标注的透明外推（全年预测/TTM/年化示意/非承诺）→ 合规，跳过
                    if _FORECAST_OK_RE.search(s):
                        continue
                    key = (dim, s.strip()[:60])
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(('I1', WARN,
                                  f'缺口维度[{dim}]在正文出现量化表述：「…{s.strip()[:48]}…」'
                                  f'——违反禁编造清单，请确认该数字来源非缺口维度，否则删除'))
                    break
    # 决策动因原文缺口：若正文对交易做了推断性动因表述，WARN
    # 🔴 排除"护栏/否定句"（如"不能因为易主就默认利好"是反向提醒，不是编造动因）
    _NEG_RE = re.compile(r'(不能|不应|不会|无法|勿|不(是|要|可|能|得|应)|未(能|取|公告)|缺失|缺口|谨慎|警惕|切忌|避免|反而|相反)')
    if any(g.get('dimension') == '决策动因原文' for g in real_gaps) and _TXN_RE.search(text):
        for s in sentences:
            if _MOTIVE_RE.search(s) and _TXN_RE.search(s) and not _NEG_RE.search(s):
                items.append(('I2', WARN,
                              f'决策动因原文缺失，但正文对交易做了推断性动因表述：「…{s.strip()[:48]}…」'
                              f'——违反禁编造清单，只能写已公告的控制权变更事实'))
                break
    if not items:
        items.append(('I0', PASS, '文章未编造证据包缺口清单内的量化维度，缺口守门通过'))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data_dir')
    ap.add_argument('--article', default=None, help='写作后检查文章覆盖度')
    a = ap.parse_args()

    res = _load(a.data_dir)
    f = res.get('findings') or {}
    anns = _all_anns(f)

    groups = [
        ('A. 决策动因（为什么做）', check_decision_motive(f, anns, a.article)),
        ('B. 业务亮点（IR 里的新东西）', check_new_business(f, anns)),
        ('C. 资本运作（改变结构的事）', check_capital_ops(f, anns)),
        ('D. 数字口径（高发 bug 区）', check_number_caliber(f)),
        ('F. 技术对标候选（需人工判定）', check_tech_benchmark(f, a.article, a.data_dir)),
    ]
    # G 组：数字一致性（只在给了文章时跑）
    if a.article:
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
            from check_numbers import build_slots, check as _chk
            _slots = build_slots(f, a.data_dir)
            _res, _bad = _chk(a.article, _slots, a.data_dir)
            _items = []
            for st, msg in _res:
                _items.append(('G1', st.replace('✅ ', '✅ PASS').replace('❌ ', '❌ FAIL')
                               .replace('🟡 ', '🟡 WARN') if not st.startswith(('✅', '❌', '🟡'))
                               else st, msg))
            groups.append(('G. 数字一致性（正文+表格）', _items))
        except Exception as e:
            groups.append(('G. 数字一致性（正文+表格）',
                           [('G1', '🟡 WARN', f'校验器未运行：{e}')]))
    if a.article:
        groups.append(('E. 文章覆盖度', check_article_coverage(a.article, f)))
    # H 组：首次提及出处（防"先简称后全称"的行文倒错）
    if a.article:
        groups.append(('H. 首次提及出处（行文顺序）', check_first_mention(a.article)))
    # I 组：缺口守门（证据包禁编造清单）
    groups.append(('I. 缺口守门（证据包禁编造清单）', check_gap_guard(a.article, a.data_dir)))

    total = dict(fail=0, warn=0, ok=0)
    print('=' * 76)
    print(f'写作检查清单 · {a.data_dir}')
    print('=' * 76)
    for gname, items in groups:
        print(f'\n【{gname}】')
        for code, status, msg in items:
            print(f'  {status}  {code}  {msg}')
            if 'FAIL' in status:
                total['fail'] += 1
            elif 'WARN' in status:
                total['warn'] += 1
            else:
                total['ok'] += 1
    print('\n' + '=' * 76)
    print(f"合计：✅ {total['ok']} ｜ 🟡 {total['warn']} ｜ ❌ {total['fail']}")
    if total['fail']:
        print('🔴 存在 FAIL 项，**补齐前不得交付**。')
    elif total['warn']:
        print('🟡 有 WARN 项，交付前需逐项确认是否真的不适用。')
    else:
        print('🟢 全部通过。')
    return 0 if total['fail'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
