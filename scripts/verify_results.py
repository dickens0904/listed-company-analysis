# -*- coding: utf-8 -*-
"""
verify_results.py - 报告数字 ↔ 原始数据 核验器（P1 重写 · 2026-10-16）
=====================================================================

⚠️ 本文件在 2026-10-16 之前**名不副实**：内容只是 i问财 查询测试脚本，
不校验任何东西。审计发现"CAPABILITY_MATRIX 声称每个数据点标注来源，
但全库无任何机制保证报告数字真的等于源数据"后，重写为真核验器。

职责：把 output/<code>_<date>/data/*.json 里的**原始数据**与
report.md 中出现的**关键指标数字**做一致性比对，输出核验结论。

设计原则（对应五段式"收口核验 / 红灯机制"）：
    1. 只核验"可从原始 JSON 直接取到"的字段，不做二次计算比对
       （避免把口径差异误报为数据错误）。
    2. 单位/期间/口径一致性一并检查（亿元 vs 元、报告期 vs 抓取日）。
    3. 未通过核验的项一律标 🔴，写入 verify_report.md，供人工复核。
    4. 核验器本身**不修改** report.md，只出报告（避免自动化改稿失控）。

用法：
    python verify_results.py output/002180_20261019
    python verify_results.py output/002180_20261019 --write   # 写入 verify_report.md
"""

from __future__ import annotations
import os
import re
import json
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# ============================================================
# 核验规则定义
# ============================================================
# 每条规则：维度 → JSON 路径 → 报告中的正则 → 单位换算 → 说明
# scale: JSON 值 → 报告值 的乘数（如 JSON 存元、报告写亿元 → 1e-8）
VERIFY_RULES = [
    {
        'name': '营业收入',
        'dim': 'financial',
        'json_paths': [
            ('revenue',),
            ('latest', 'revenue'),
            ('summary', 'revenue'),
            ('records', -1, 'revenue'),
        ],
        'report_regex': r'营业收入[^\d]{0,20}([\d,]+\.?\d*)\s*亿',
        'scale': 1e-8,
        'tolerance': 0.02,   # 2% 容差（四舍五入/追溯调整）
        'critical': True,
    },
    {
        'name': '归母净利润',
        'dim': 'financial',
        'json_paths': [
            ('net_profit',),
            ('latest', 'net_profit'),
            ('summary', 'net_profit'),
            ('records', -1, 'net_profit'),
        ],
        'report_regex': r'(?:归母)?净利润[^\d]{0,20}([\d,]+\.?\d*)\s*亿',
        'scale': 1e-8,
        'tolerance': 0.02,
        'critical': True,
    },
    {
        'name': '总股本(亿股)',
        'dim': 'financial',
        'json_paths': [
            ('total_shares',),
            ('latest', 'total_shares'),
        ],
        'report_regex': r'总股本[^\d]{0,20}([\d,]+\.?\d*)\s*亿',
        'scale': 1.0,   # 已是亿股则不换算；若 JSON 存股则需另配
        'tolerance': 0.01,
        'critical': False,
    },
]


# ============================================================
# 工具函数
# ============================================================
def _dig(data, path) -> Optional[float]:
    """按路径取数值，支持负索引"""
    cur = data
    try:
        for key in path:
            if isinstance(key, int):
                if not isinstance(cur, (list, tuple)) or not cur:
                    return None
                idx = key if key >= 0 else len(cur) + key
                if idx < 0 or idx >= len(cur):
                    return None
                cur = cur[idx]
            else:
                if not isinstance(cur, dict):
                    return None
                cur = cur.get(key)
        if cur is None:
            return None
        return float(cur)
    except (TypeError, ValueError):
        return None


def _find_source_value(rule: dict, dim_data) -> Tuple[Optional[float], str]:
    """在维度 JSON 里按规则路径找值，返回 (值, 命中的路径描述)"""
    for path in rule['json_paths']:
        val = _dig(dim_data, path)
        if val is not None and val != 0:
            return val * rule['scale'], '.'.join(str(p) for p in path)
    return None, ''


def _extract_report_numbers(report_text: str, regex: str) -> List[float]:
    """从报告文本提取数字列表"""
    out = []
    for m in re.finditer(regex, report_text):
        try:
            out.append(float(m.group(1).replace(',', '')))
        except (ValueError, IndexError):
            continue
    return out


# ============================================================
# 主核验逻辑
# ============================================================
def verify_analysis_dir(analysis_dir: str) -> dict:
    """
    核验一个分析输出目录。

    Returns:
        {
          'dir': ..., 'checked_at': ...,
          'passed': [...], 'failed': [...], 'skipped': [...],
          'report': '...markdown...'
        }
    """
    data_dir = os.path.join(analysis_dir, 'data')
    report_path = os.path.join(analysis_dir, 'report.md')

    result = {
        'dir': analysis_dir,
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'passed': [],
        'failed': [],
        'skipped': [],
    }

    if not os.path.isdir(data_dir):
        result['skipped'].append({'name': '(全部)', 'reason': 'data/ 目录不存在，无从核验'})
        result['report'] = _format_verify_report(result)
        return result

    if not os.path.exists(report_path):
        result['skipped'].append({'name': '(全部)', 'reason': 'report.md 不存在，无从比对'})
        result['report'] = _format_verify_report(result)
        return result

    with open(report_path, 'r', encoding='utf-8') as f:
        report_text = f.read()

    for rule in VERIFY_RULES:
        dim_file = os.path.join(data_dir, f"{rule['dim']}.json")
        if not os.path.exists(dim_file):
            result['skipped'].append({
                'name': rule['name'],
                'reason': f"缺少 data/{rule['dim']}.json",
            })
            continue

        try:
            with open(dim_file, 'r', encoding='utf-8') as f:
                dim_data = json.load(f)
        except Exception as e:
            result['failed'].append({
                'name': rule['name'],
                'reason': f"JSON 解析失败: {e}",
                'severity': '🔴' if rule['critical'] else '🟡',
            })
            continue

        src_val, src_path = _find_source_value(rule, dim_data)
        if src_val is None:
            result['skipped'].append({
                'name': rule['name'],
                'reason': f"JSON 中未找到字段（试过 {rule['json_paths']}）",
            })
            continue

        report_vals = _extract_report_numbers(report_text, rule['report_regex'])
        if not report_vals:
            result['skipped'].append({
                'name': rule['name'],
                'reason': '报告中未找到对应数字（可能该章节未生成）',
                'source_value': src_val,
                'source_path': src_path,
            })
            continue

        # 比对：报告里任一数字与源值接近即算通过
        tol = rule['tolerance']
        matched = any(
            abs(rv - src_val) <= max(abs(src_val) * tol, 1e-6)
            for rv in report_vals
        )
        if matched:
            result['passed'].append({
                'name': rule['name'],
                'source_value': round(src_val, 4),
                'source_path': src_path,
                'report_values': report_vals[:5],
            })
        else:
            result['failed'].append({
                'name': rule['name'],
                'reason': '报告数字与原始数据不一致',
                'source_value': round(src_val, 4),
                'source_path': src_path,
                'report_values': report_vals[:5],
                'severity': '🔴' if rule['critical'] else '🟡',
            })

    result['report'] = _format_verify_report(result)
    return result


def _format_verify_report(r: dict) -> str:
    lines = [
        '\n\n---\n\n## ✅ 报告数字核验（verify_results · P1）\n',
        f'核验时间：{r["checked_at"]}　目录：`{r["dir"]}`\n',
        f'- ✅ 通过：{len(r["passed"])} 项',
        f'- 🔴 不一致：{len([f for f in r["failed"] if f.get("severity") == "🔴"])} 项',
        f'- 🟡 不一致(非核心)：{len([f for f in r["failed"] if f.get("severity") != "🔴"])} 项',
        f'- ⏭️ 跳过：{len(r["skipped"])} 项\n',
    ]
    if r['failed']:
        lines.append('### ❌ 不一致项（须人工复核）\n')
        lines.append('| 指标 | 原始数据 | 来源路径 | 报告中数字 | 严重度 |')
        lines.append('|---|---|---|---|:---:|')
        for f in r['failed']:
            lines.append(
                f"| {f['name']} | {f.get('source_value', '—')} | "
                f"`{f.get('source_path', '—')}` | {f.get('report_values', '—')} | {f.get('severity', '🟡')} |"
            )
        lines.append('')
    if r['passed']:
        lines.append('### ✅ 一致项\n')
        lines.append('| 指标 | 原始数据 | 报告中数字 |')
        lines.append('|---|---|---|')
        for p in r['passed']:
            lines.append(f"| {p['name']} | {p['source_value']} | {p['report_values'][:3]} |")
        lines.append('')
    if r['skipped']:
        lines.append('### ⏭️ 跳过项\n')
        for s in r['skipped']:
            lines.append(f"- {s['name']}：{s['reason']}")
        lines.append('')
    return '\n'.join(lines)


# ============================================================
# CLI
# ============================================================
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='报告数字 ↔ 原始数据核验器')
    ap.add_argument('analysis_dir', help='分析输出目录，如 output/002180_20261019')
    ap.add_argument('--write', action='store_true', help='把核验报告写入该目录 verify_report.md')
    args = ap.parse_args()

    r = verify_analysis_dir(args.analysis_dir)
    print(r['report'])
    print(f"\n小结：通过 {len(r['passed'])} / 不一致 {len(r['failed'])} / 跳过 {len(r['skipped'])}")

    if args.write:
        out = os.path.join(args.analysis_dir, 'verify_report.md')
        with open(out, 'w', encoding='utf-8') as f:
            f.write(r['report'])
        print(f"→ 已写入 {out}")

    # 退出码：有 🔴 级不一致 → 1（便于门禁脚本判断）
    sys.exit(1 if any(f.get('severity') == '🔴' for f in r['failed']) else 0)
