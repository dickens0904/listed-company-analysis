# -*- coding: utf-8 -*-
"""
silenced_errors.py — 静默异常登记表（2026-10-19 审计新增）
=========================================================

## 为什么要有这个模块

审计发现全 skill 有 **79 处真裸 `except:`**（45 处是纯 `pass`）+
58 处 `except Exception:` 却什么都不做。这类写法的危害不在于语法，
而在于**语义**：

    def parse_something(data):
        try:
            return do_parse(data)
        except:            # ← 吞掉
            pass
        return {}          # ← 调用方以为"查过了，没有"

异常被完全吞掉、无日志 → 上层无法区分
「真的没有这个数据」与「解析炸了」→ 这正是用户反馈
「数据源不可靠，导致分析出来的内容有问题」最隐蔽的来源。

## 制度

1. **禁止静默吞异常**。凡是 catch 后不产出任何可观测信号的，
   必须走本模块 `record()` 登记（至少留下模块名+位置+异常类型+消息）。
2. `record()` 写入模块级内存表，由 `analyze.py` 在维度采集完成后
   汇总进 `results['_silenced_errors']`，并由 `report.py` 渲染成
   「静默降级清单」章节——**让"数据可能不可靠"这件事显式可见**，
   而不是藏在代码里。
3. 报告中的每一条都能被读者追问、复核、追责。

## 用法

    from scripts.silenced_errors import record, dump

    try:
        return do_parse(data)
    except Exception as e:
        record(__name__, 'parse_something', e)
        return {}

    # analyze.py 结束后
    from scripts.silenced_errors import dump
    dump(results)          # 写入 results['_silenced_errors']
"""

from __future__ import annotations

import sys
import traceback
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List

# 模块级登记表：{模块名: [{func, exc_type, message, line_hint, ts}]}
_SILENCED: Dict[str, List[Dict[str, Any]]] = {}

# 同一 (module, func, exc_type) 只记一次，避免循环里刷屏
_SEEN = set()

# 上限保护：单模块最多留 50 条，防止内存爆炸
_MAX_PER_MODULE = 50


def record(module: str, func: str, exc: BaseException, *, note: str = '') -> None:
    """
    登记一个被静默吞掉的异常。

    Args:
        module: 调用方模块名（通常传 __name__）
        func:   出错所在函数名
        exc:    捕获到的异常对象
        note:   可选的上下文说明（如"降级返回空 dict"）
    """
    try:
        exc_type = type(exc).__name__ if exc else 'Unknown'
        msg = str(exc)[:200] if exc else ''
        key = (module, func, exc_type, msg[:80])
        if key in _SEEN:
            return
        _SEEN.add(key)
        lst = _SILENCED.setdefault(module, [])
        if len(lst) >= _MAX_PER_MODULE:
            return
        lst.append({
            'func': func,
            'exc_type': exc_type,
            'message': msg,
            'note': note,
            'ts': datetime.now().strftime('%H:%M:%S'),
        })
    except Exception:          # 登记器自身绝不能抛
        pass


def record_result(module: str, func: str, exc: BaseException,
                  *, result: Any, note: str = '') -> None:
    """登记异常并说明降级成了什么——这是最有价值的上下文。"""
    desc = f'降级返回 {type(result).__name__}'
    if isinstance(result, dict):
        desc += f'{list(result.keys())[:5]}'
    elif isinstance(result, (list, tuple)):
        desc += f'len={len(result)}'
    elif result is None:
        desc = '降级返回 None'
    record(module, func, exc, note=(note + ' / ' + desc).strip(' /'))


def get_silenced() -> Dict[str, List[Dict[str, Any]]]:
    return dict(_SILENCED)


def count() -> int:
    return sum(len(v) for v in _SILENCED.values())


def clear() -> None:
    """测试/重跑用。"""
    _SILENCED.clear()
    _SEEN.clear()


def dump(results: dict) -> int:
    """
    把登记表写进 analyze.py 的 results 字典。

    Returns:
        本次登记的条目数（0 表示全链路无静默降级——健康信号）
    """
    if not isinstance(results, dict):
        return 0
    n = count()
    if not n:
        results['_silenced_errors'] = {
            'total': 0, 'note': '全链路未捕获到静默降级异常', 'by_module': {}
        }
        return 0
    by_mod = {
        m: {'count': len(items),
            'types': dict(Counter(i['exc_type'] for i in items)),
            'items': items[:10]}
        for m, items in sorted(_SILENCED.items(),
                               key=lambda x: -len(x[1]))
    }
    results['_silenced_errors'] = {
        'total': n,
        'module_count': len(_SILENCED),
        'by_module': by_mod,
        'note': ('以下异常被静默捕获，相关维度的数据可能不完整，'
                 '结论须按"需核实"处理——详见报告「静默降级清单」章节'),
    }
    return n


def format_markdown(se: dict) -> str:
    """生成报告用章节。零静默时返回空串（不占版面）。"""
    if not se or not se.get('total'):
        return ''
    lines = [
        '\n## ⚠️ 静默降级清单（数据可靠性提示）\n',
        f"> 共捕获 **{se['total']}** 处被静默吞掉的异常，分布于 "
        f"**{se.get('module_count', 0)}** 个模块。\n",
        "> 这些异常不会让流程失败，但会让相关维度**静默返回空值/默认值**——",
        "> 即「查过了，没有」与「解析炸了」在上层无法区分。",
        "> 引用以下维度结论时须按「需核实」处理。\n",
        '| 模块 | 处数 | 异常类型 | 典型降级结果 |',
        '|---|---|---|---|',
    ]
    for m, info in (se.get('by_module') or {}).items():
        types = '、'.join(f"{k}×{v}" for k, v in
                         sorted(info['types'].items(), key=lambda x: -x[1])[:3])
        sample = (info.get('items') or [{}])[0]
        note = (sample.get('note') or '')[:40]
        lines.append(f"| `{m}` | {info['count']} | {types} | {note} |")
    lines.append("")
    lines.append("**建议**：按上表优先级，为对应模块补日志与显式降级返回，"
                 "或改用 `scripts/silenced_errors.record_result()` 标注降级形态。\n")
    return '\n'.join(lines)


def print_report() -> None:
    """控制台摘要。"""
    n = count()
    if not n:
        print("  ✅ 静默降级：0 处")
        return
    print(f"  ⚠️ 静默降级：{n} 处，分布 {len(_SILENCED)} 个模块")
    for m, items in sorted(_SILENCED.items(), key=lambda x: -len(x[1]))[:8]:
        types = dict(Counter(i['exc_type'] for i in items))
        print(f"     {m}: {len(items)} 处 ({', '.join(types)})")


if __name__ == '__main__':
    # 自测
    try:
        1 / 0
    except ZeroDivisionError as e:
        record(__name__, '_selftest', e, note='自测')
    try:
        {}['x']
    except KeyError as e:
        record_result(__name__, '_selftest2', e, result={})
    _r = {}
    dump(_r)
    print('登记条目：', count())
    print(format_markdown(_r['_silenced_errors']))
    print('—— 二次 dump（重复登记应被去重）——')
    dump(_r)
    print('条目数仍为：', _r['_silenced_errors']['total'])