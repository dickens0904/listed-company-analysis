# -*- coding: utf-8 -*-
"""
check_numbers.py — 文章数字一致性校验（2026-10-20）

## 解决什么问题

E 组只查"有没有提到"，不查"写得对不对"。
实证风险：把商誉**期初 135.09 亿**写成"商誉 135 亿"（读者理解成期末），
把营收 45.64 写成 54.64，把 -7.18 写成 7.18（丢负号）——这些 E 组全查不出来。

## 做法：语义词 × 数值槽位

不追求"校验所有数字"（文章里有大量行业数据、日期、百分比，全查必误报），
只校验**有明确语义归属的财务数字**：

    文中出现「商誉 …… 6.22 亿」 → 6.22 必须等于 goodwill_ending
    文中出现「期初商誉 135 亿」   → 必须是 goodwill_beginning
    文中出现「2025 年营收 165 亿」 → 必须等于该年 revenue
    文中出现「市值 218 亿」       → 必须等于 market_cap
    ……

判定：
  · 数值与语义槽位匹配（容差 2%）        → PASS
  · 数值落在**另一个**槽位（张冠李戴）    → FAIL（最危险：135 当期末）
  · 数值不在任何槽位（可能是外部数据）    → WARN（列出供人工确认）

## 用法
    python scripts/check_numbers.py <data_dir> <article.md>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

TOL = 0.02  # 2% 容差（覆盖"约""近"等模糊表述与四舍五入）


def _f(x) -> Optional[float]:
    try:
        return round(float(x) / 1e8, 2)
    except (TypeError, ValueError):
        return None


def build_slots(f: Dict, data_dir: str) -> List[Dict[str, Any]]:
    """构建「语义槽位 → 合法数值」表"""
    slots: List[Dict[str, Any]] = []

    def add(name, value, labels, unit='亿'):
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        slots.append({'slot': name, 'value': v, 'labels': labels, 'unit': unit})

    # 商誉（区分期初/期末 —— 这是最容易被写错的一对）
    # 🔴 标签必须**互斥**：第一版两个槽位都挂"商誉"，导致附近出现"商誉"时
    # 两个标签等距 → 被判歧义跳过 → 破坏测试（期末改期初）竟然 PASS。
    # 现改为各自专属标签，并覆盖常见表述（表格"期末商誉"、正文"商誉从…降到…"）。
    gw = ((f.get('ma_deep') or {}).get('goodwill_analysis') or {})
    gw_end, gw_beg = _f(gw.get('total_goodwill')), _f(gw.get('goodwill_beginning'))
    if gw_end is not None:
        slots.append({'slot': '商誉_期末', 'value': gw_end, 'unit': '亿',
                      'labels': ['期末商誉', '商誉期末', '期末余额', '商誉降至',
                                 '商誉降到', '商誉仅剩', '商誉只剩']})
    if gw_beg is not None:
        slots.append({'slot': '商誉_期初', 'value': gw_beg, 'unit': '亿',
                      'labels': ['期初商誉', '商誉期初', '期初余额', '商誉从']})

    # 年度序列
    series = []
    for r in ((f.get('financial') or {}).get('records') or []):
        d = str(r.get('REPORTDATE') or '')[:10]
        if not d.endswith('12-31'):
            continue
        yr = d[:4]
        if any(s['year'] == yr for s in series):
            continue
        rev, npf = _f(r.get('TOTAL_OPERATE_INCOME')), _f(r.get('PARENT_NETPROFIT'))
        if rev is None:
            continue
        series.append({'year': yr, 'revenue': rev, 'net_profit': npf})
    for s in series:
        add(f'营收_{s["year"]}', s['revenue'], [f'{s["year"]} 年营收', '营业收入', '营收'])
        if s.get('net_profit') is not None:
            add(f'净利_{s["year"]}', s['net_profit'],
                [f'{s["year"]} 年净利', '归母净利', '净利润', '亏损', '赚'])

    # 估值
    cur = ((f.get('valuation') or {}).get('current') or {})
    add('市值', cur.get('market_cap_亿'), ['市值'])
    for k, lb in (('pb', 'PB'), ('ps', 'PS')):
        v = cur.get(k)
        if v is not None:
            slots.append({'slot': lb, 'value': round(float(v), 2), 'labels': [lb, f'{lb} 倍'], 'unit': '倍'})

    # 当期（半年度）
    latest_half = None
    for r in ((f.get('financial') or {}).get('records') or []):
        d = str(r.get('REPORTDATE') or '')[:10]
        if d and not d.endswith('12-31'):
            latest_half = {'date': d, 'revenue': _f(r.get('TOTAL_OPERATE_INCOME')),
                           'net_profit': _f(r.get('PARENT_NETPROFIT'))}
            break
    if latest_half and latest_half.get('revenue'):
        yr = latest_half['date'][:4]
        add(f'营收_{yr}H1', latest_half['revenue'], [f'{yr} 上半年', f'{yr}H1', '上半年营收'])
        if latest_half.get('net_profit') is not None:
            add(f'净利_{yr}H1', latest_half['net_profit'], [f'{yr} 上半年', f'{yr}H1'])

    return slots


def check_tables(txt: str, slots: List[Dict[str, Any]]) -> Tuple[List[tuple], int]:
    """校验 Markdown 财务表格（年度 × 营收/净利）

    🔴 为什么单独处理：表格里数字与语义被 `|` 隔开，且年份是独立单元格
    （"| 2025 | 165.15 亿 |"），正文的"就近标签"逻辑完全覆盖不到。
    而表格恰恰是**最容易错位**的地方——改一行数据、错一列，肉眼很难发现。
    """
    lines = txt.split('\n')
    results, bad = [], 0
    year_slots = {s['slot'].split('_')[-1]: s for s in slots if s['slot'].startswith('营收_')}

    i = 0
    while i < len(lines):
        ln = lines[i]
        if '|' not in ln or not re.search(r'营业收入|营收', ln):
            i += 1
            continue
        headers = [c.strip().strip('*') for c in ln.strip().strip('|').split('|')]
        rev_col = next((j for j, h in enumerate(headers) if '营收' in h or '营业收入' in h), None)
        np_col = next((j for j, h in enumerate(headers) if '净利' in h), None)
        if rev_col is None:
            i += 1
            continue
        # 跳过分隔行
        j = i + 2
        while j < len(lines) and lines[j].strip().startswith('|'):
            cells = [c.strip() for c in lines[j].strip().strip('|').split('|')]
            if len(cells) > max(rev_col, 1):
                m = re.search(r'(20\d{2})', cells[0])
                if m:
                    yr = m.group(1)
                    # 营收
                    if yr in year_slots and rev_col < len(cells):
                        mm = re.search(r'(-?[\d.]+)\s*亿', cells[rev_col])
                        if mm:
                            v = float(mm.group(1))
                            expect = year_slots[yr]['value']
                            if abs(v - expect) > max(0.06, abs(expect) * TOL):
                                bad += 1
                                results.append(('❌ FAIL',
                                                f'表格 {yr} 年营收写 {v} 亿，数据源为 {expect} 亿'))
                    # 净利
                    np_slot = next((s for s in slots if s['slot'] == f'净利_{yr}'), None)
                    if np_slot and np_col is not None and np_col < len(cells):
                        mm = re.search(r'(-?[\d.]+)\s*亿', cells[np_col])
                        if mm:
                            v = float(mm.group(1))
                            expect = np_slot['value']
                            if abs(abs(v) - abs(expect)) > max(0.06, abs(expect) * TOL):
                                bad += 1
                                results.append(('❌ FAIL',
                                                f'表格 {yr} 年净利写 {v} 亿，数据源为 {expect} 亿'))
                            elif (v > 0) != (expect > 0):
                                bad += 1
                                results.append(('❌ FAIL',
                                                f'表格 {yr} 年净利符号错：写 {v}，应为 {expect}'))
            j += 1
        i = j if j > i else i + 1
    return results, bad


def check(article: str, slots: List[Dict[str, Any]], data_dir: str) -> Tuple[List[tuple], int]:
    """只校验**合并报表口径**的关键数字，避免外部数据（预案/行业）造成的噪音

    🔴 第一版把语境窗口开到 40 字，一个句子里"商誉/营收/净利"同时命中，
    导致 7.18 亿（2025 净利）被判"张冠李戴"——误报率高到没法用。

    现收紧为：
      · 窗口 15 字，且**只取最近的唯一语义标签**（重叠则跳过）
      · 只校验 4 类：商誉期末 / 商誉期初 / 本公司年度营收 / 本公司年度净利
      · 其余数值（预案数据、行业数据、外部引用）一律**不校验、不报**，避免噪音
    """
    txt = open(article, encoding='utf-8').read()
    results: List[tuple] = []
    bad = 0

    STRICT_SLOTS = {'商誉_期末', '商誉_期初'}
    for s in slots:
        if s['slot'].startswith(('营收_', '净利_')) and 'H1' not in s['slot']:
            STRICT_SLOTS.add(s['slot'])

    # 每个语义标签 → 位置列表，用于就近匹配
    label_pos: List[Tuple[str, int, str]] = []   # (label, pos, slot)
    for s in slots:
        if s['slot'] not in STRICT_SLOTS:
            continue
        for lb in s['labels']:
            if len(lb) < 2:      # 过短的标签（"赚"）易误触
                continue
            for m in re.finditer(re.escape(lb), txt):
                label_pos.append((lb, m.start(), s['slot']))

    # 🔴 区间句式豁免："商誉从 135 亿降到 6.22 亿" 里两个数都合法，
    # 就近匹配会把 6.22 误配给"商誉从"（期初）→ 误报。
    # 凡出现 "从…降/升到…" 结构的句子，整句跳过数字校验。
    skip_spans = []
    for m in re.finditer(r'[^。；\n]{0,30}从[^。；\n]{0,30}(?:降|升|变|减|增)到[^。；\n]{0,20}', txt):
        skip_spans.append((m.start(), m.end()))

    def _in_skip(pos: int) -> bool:
        return any(a <= pos <= b for a, b in skip_spans)

    mismatches = []
    for m in re.finditer(r'(-?[\d,]+\.?\d*)\s*亿', txt):
        if _in_skip(m.start()):
            continue
        try:
            v = float(m.group(1).replace(',', ''))
        except ValueError:
            continue
        num_pos = m.start()
        # 找 15 字内最近的标签，且必须唯一（第二个标签距离差太近则跳过）
        # "商誉从"这类紧邻型标签窗口收窄到 8 字，避免跨到区间终点
        def _win(lb: str) -> int:
            return 8 if lb.endswith(('从', '降至', '降到')) else 15
        near = sorted(((abs(p - num_pos), lb, slot) for lb, p, slot in label_pos
                       if abs(p - num_pos) <= _win(lb)))[:2]
        if not near:
            continue
        if len(near) == 2 and near[0][0] == near[1][0]:
            continue          # 等距歧义 → 跳过
        _, lb, slot = near[0]
        target = next(s for s in slots if s['slot'] == slot)
        if abs(abs(v) - abs(target['value'])) <= max(0.06, abs(target['value']) * TOL):
            continue
        # 🔴 标签明确命中（如"2025 年营收""期末商誉"）但数值不符 → 一律 FAIL。
        # 第一版只在"该值恰好属于另一个槽位"时才报，结果"把 165 写成 156"这类
        # 单纯的写错被静默放过（破坏测试实测漏判）。现已收紧。
        other = [s for s in slots if s['slot'] in STRICT_SLOTS
                 and abs(abs(v) - abs(s['value'])) <= max(0.06, abs(s['value']) * TOL)
                 and s['slot'] != slot]
        mismatches.append((v, lb, slot, other[0]['slot'] if other else None,
                           other[0]['value'] if other else target['value'], m.start()))

    for v, lb, want, got, ref, pos in mismatches:
        bad += 1
        ctx = txt[max(0, pos - 26):pos + 12].replace('\n', ' ')
        if got:
            detail = f'语义应为 {want}（{ref} 亿），但该值实属 {got}'
        else:
            detail = f'语义应为 {want}（{ref} 亿），但文中写 {v} 亿'
        results.append(('❌ FAIL', f'{v} 亿 @「{lb}」：{detail}｜…{ctx}…'))

    # 表格校验
    tbl_results, tbl_bad = check_tables(txt, slots)
    results.extend(tbl_results)
    bad += tbl_bad

    if not mismatches and not tbl_bad:
        results.append(('✅ PASS', '关键财务数字（含正文与表格）与数据源一致'))
    return results, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data_dir')
    ap.add_argument('article')
    a = ap.parse_args()
    res = json.load(open(os.path.join(a.data_dir, 'results.json'), encoding='utf-8'))
    slots = build_slots(res.get('findings') or {}, a.data_dir)
    print(f'数值槽位 {len(slots)} 个：' +
          '、'.join(s['slot'] for s in slots[:12]) + '…')
    results, bad = check(a.article, slots, a.data_dir)
    print()
    for st, msg in results:
        print(f'  {st}  {msg}')
    print(f'\n结论：{"❌ 有张冠李戴" if bad else "🟢 通过"}')
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
