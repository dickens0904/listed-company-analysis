# -*- coding: utf-8 -*-
"""
mcp_mineru_bridge.py — MCP 深解析（MinerU）接入桥
=================================================

## 背景与实测依据（2026-10-19）

MCP 侧有两个公告相关工具，能力边界必须先说清（**均为实调结论，非推测**）：

| MCP 工具 | 实测能力 |
|---|---|
| `search_announcements` | ✅ 按代码/日期检索，002180 返回 **1958 条**（比巨潮 1354 条多） |
| `get_announcement_detail` | ⚠️ **只有元数据，无正文**（标题/日期/类型/hasPdf） |
| `download_announcement_parsing` | ✅ **MinerU 深解析正文**（markdown/json/zip） |
| `download_announcement_pdf` | ✅ 原始 PDF（2020 年那份 17MB 也能下） |

🔴 **MinerU 有时间边界**（分层抽样 6 条实测）：
```
2020-05-18  发行股份购买资产报告书（草案）  ❌ 无深解析
2026-09-17  使用公积金弥补亏损            ✅ 有（金额精确到分）
2026-09-23  对外担保进展                ✅ 有（担保总额 56.85 亿/净资产 18.25%）
```
**2026 = 2/2 全有，2020 = 0/4 全无** → 只覆盖近期公告。
所以 MCP **不能**替代自建 PDF 链路，只能当**第 4 路 fallback**（且主要惠及近期公告）。

## 本模块做什么

把「PDF 抽取失败或内容为空的公告」登记成一份 **MCP 回填计划**（落盘 `mcp_plan.json`），
由主循环（我）用 MCP 工具逐条回填，避免 Python 内部直接调 MCP（不可行）。

同时维护一份**深解析覆盖索引** `mcp_mineru_coverage.json`：
记录每条 art_code 探测到的结果（`hit` / `miss`），
下次跑批**直接查表跳过已知 miss**，不浪费往返（每次失败调用都是一次无谓网络往返）。

## 降级链（本模块插入的位置）

    ① PDF 缓存命中（tmp_paths 兼容层）
    ② 巨潮直连下载 + PyMuPDF      ← 主源
    ③ MCP MinerU 深解析            ← 本模块登记，主循环回填（近年代命中即止，省一次下载）
    ④ 东财/新浪 HTML

## 用法

    # 采集侧（Python）
    from scripts.mcp_mineru_bridge import register_failed_announcements
    plan = register_failed_announcements(data_dir, failed_announcements)
    # → 落盘 mcp_plan_mineru.json，返回待回填条数

    # 主循环（我，用 MCP 工具）逐条调 download_announcement_parsing

    # 回填侧（Python）
    from scripts.mcp_mineru_bridge import save_mineru_result, update_coverage
    save_mineru_result(data_dir, art_code, markdown_text)
    update_coverage(data_dir, art_code, hit=True)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

MINERU_PLAN_FILE = 'mcp_plan_mineru.json'
COVERAGE_FILE = 'mcp_mineru_coverage.json'

# 已知 MinerU 未覆盖的时间边界（实测：2020 年全无）。用于避免对
# 老公告做无谓尝试，也避免把"未探测"误当"已探知 miss"。
KNOWN_UNCOVERED_BEFORE = '2024-01-01'   # 保守：只对 ≥ 此日期的公告尝试 MCP


def _load_coverage(data_dir: str) -> Dict[str, Any]:
    path = os.path.join(data_dir, COVERAGE_FILE)
    if not os.path.exists(path):
        return {'version': 1, 'entries': {}}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'version': 1, 'entries': {}}


def save_coverage(data_dir: str, coverage: Dict[str, Any]) -> str:
    path = os.path.join(data_dir, COVERAGE_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(coverage, f, ensure_ascii=False, indent=2)
    return path


def update_coverage(data_dir: str, art_code: str, hit: bool,
                    note: str = '', pub_date: str = '') -> None:
    """登记一次探测结果。hit=False 时记录日期，便于推断时间边界。"""
    cov = _load_coverage(data_dir)
    cov.setdefault('entries', {})[art_code] = {
        'hit': bool(hit),
        'pub_date': pub_date,
        'note': note[:80],
    }
    # 汇总统计
    entries = cov['entries']
    hits = sum(1 for v in entries.values() if v['hit'])
    cov['stats'] = {
        'total': len(entries),
        'hit': hits,
        'miss': len(entries) - hits,
        'hit_rate': round(hits * 100 / len(entries), 1) if entries else 0,
    }
    save_coverage(data_dir, cov)


def is_known_miss(data_dir: str, art_code: str) -> bool:
    """该 art_code 是否已探知 MinerU 没有深解析结果 → 可跳过，不浪费往返。"""
    cov = _load_coverage(data_dir)
    e = cov.get('entries', {}).get(art_code)
    return bool(e and not e['hit'])


def coverage_report(data_dir: str) -> str:
    cov = _load_coverage(data_dir)
    s = cov.get('stats') or {}
    if not s:
        return ''
    return (f"MinerU 覆盖：{s['hit']}/{s['total']} 命中 "
            f"({s['hit_rate']}%)")


def register_failed_announcements(data_dir: str,
                                  failed: List[Dict[str, Any]],
                                  max_calls: int = 60) -> int:
    """
    把「PDF 抽取失败或内容为空」的公告登记成 MCP 回填计划。

    只登记**近期**公告（MinerU 只覆盖近期，老公告探了也是 miss，白费往返）。

    Args:
        data_dir: 数据目录
        failed: [{'art_code':…, 'title':…, 'date':…}, …]
        max_calls: 单次跑批上限，避免 MCP 回填拖太长（回填是串行的）

    Returns:
        实际登记条数
    """
    todo = []
    for a in failed:
        code = (a.get('art_code') or '').strip()
        if not code:
            continue
        pub = a.get('date') or ''
        # 只对近期公告尝试（实测 MinerU 只覆盖近期）
        if pub and pub < KNOWN_UNCOVERED_BEFORE:
            continue
        # 已探知 miss 的跳过
        if is_known_miss(data_dir, code):
            continue
        todo.append({
            'dim': 'announcement_fulltext',
            'connector': 'alphapai-lite-mcp',
            'tool': 'download_announcement_parsing',
            'params': {
                'documentId': code,
                'documentType': 'announcement',
                'downloadType': 'markdown',
            },
            'art_code': code,
            'title': a.get('title', '')[:60],
            'pub_date': pub,
            'note': 'PDF 抽取失败/为空，MCP MinerU 兜底（仅近期公告命中率高）',
        })
        if len(todo) >= max_calls:
            break

    if not todo:
        return 0
    plan = {
        'generated_by': 'mcp_mineru_bridge',
        'purpose': '公告全文 MinerU 深解析兜底（PDF 失败时）',
        'known_uncovered_before': KNOWN_UNCOVERED_BEFORE,
        'calls': todo,
    }
    path = os.path.join(data_dir, MINERU_PLAN_FILE)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return len(todo)


def save_mineru_result(data_dir: str, art_code: str,
                       markdown_text: str) -> str:
    """
    把 MCP 回填的 MinerU 正文存盘，供 collect 阶段读取回填到公告上。

    落盘到 data_dir/mcp_mineru/{art_code}.md
    """
    out_dir = os.path.join(data_dir, 'mcp_mineru')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f'{art_code}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(markdown_text)
    return path


def load_mineru_results(data_dir: str) -> Dict[str, str]:
    """读取所有已回填的 MinerU 正文 → {art_code: markdown}"""
    out_dir = os.path.join(data_dir, 'mcp_mineru')
    if not os.path.isdir(out_dir):
        return {}
    res = {}
    for fn in os.listdir(out_dir):
        if fn.endswith('.md'):
            code = fn[:-3]
            try:
                with open(os.path.join(out_dir, fn), 'r', encoding='utf-8') as f:
                    res[code] = f.read()
            except Exception:
                continue
    return res


def merge_mineru_into_announcements(findings: Dict[str, Any],
                                    data_dir: str) -> int:
    """
    把已回填的 MinerU 正文合并进 findings['announcements'] 的对应条目，
    覆盖原本空的 extracted_content。

    关键：MCP 正文必须**过一遍 key_facts 抽取**（复用 announcements 的规则），
    否则只有 full_text_preview，下游 deal_story_builder 的全文反哺拿不到
    标的名/金额 —— 等于白回填。

    Returns:
        成功合并条数
    """
    mineru = load_mineru_results(data_dir)
    if not mineru:
        return 0
    # 复用既有事实抽取器（保持与 PDF 链路同一套规则，避免两套口径）
    try:
        from scripts.announcements import _extract_facts_by_type
    except Exception:
        _extract_facts_by_type = None

    ann = findings.get('announcements') or {}
    merged = 0
    for k in ('critical_announcements', 'major_announcements',
              'routine_announcements'):
        for a in (ann.get(k) or []):
            code = a.get('art_code') or ''
            if code not in mineru:
                continue
            text = mineru[code]
            facts = []
            if _extract_facts_by_type:
                try:
                    facts = _extract_facts_by_type(
                        text, a.get('importance_tag', '')) or []
                except Exception:
                    facts = []
            a['extracted_content'] = {
                'full_text_preview': text[:5000],
                'key_facts': facts,          # MCP 正文同样抽事实（下游反哺依赖它）
                'source': 'mcp_mineru',
                'text_length': len(text),
            }
            a['extract_method'] = 'mcp_mineru'
            merged += 1
            update_coverage(data_dir, code, hit=True,
                            note='回填成功', pub_date=a.get('date', ''))
    return merged


if __name__ == '__main__':
    # 冒烟测试
    import tempfile
    d = tempfile.mkdtemp()
    n = register_failed_announcements(d, [
        {'art_code': 'A1', 'title': '近期公告', 'date': '2026-09-17'},   # 应登记
        {'art_code': 'A2', 'title': '老公告', 'date': '2020-05-18'},     # 跳过(早期)
        {'art_code': '', 'title': '无ID', 'date': '2026-09-17'},          # 跳过(无ID)
    ])
    print(f'登记 {n} 条（预期 1，只有近期+有ID 的）')
    print(f'覆盖报告: {coverage_report(d) or "(空)"}')
    update_coverage(d, 'A1', hit=True)
    update_coverage(d, 'A2', hit=False)
    print(f'探测2条后: {coverage_report(d)}')
    print(f'A1 已知命中? {not is_known_miss(d, "A1")} | A2 已知miss? {is_known_miss(d, "A2")}')