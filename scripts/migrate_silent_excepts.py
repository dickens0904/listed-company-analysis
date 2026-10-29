# -*- coding: utf-8 -*-
"""
migrate_silent_excepts.py — 批量把静默吞异常改造为可观测（2026-10-19 审计）
=========================================================================

用途：把 `except:`/`except Exception:` 后**什么都不产出**的写法，
统一改为"登记到 silenced_errors + 保留原降级行为"。

安全策略（自动化改代码必须有护栏）：
1. **只改 handler 体为空/pass 的节点**——已有 print/log 的不动
   （那些已可观测，只是格式不统一，属人工整理范畴）。
2. **降级行为完全保留**：原来 `return {}` 的仍然 `return {}`，
   只在前面插一行 `record_result(...)`。绝不改变控制流。
3. **不碰有 except 配对语义或 re-raise 的**。
4. **改完必须 py_compile + AST 校验**，失败自动回滚该文件。
5. **幂等**：已插入登记的（含 silenced_errors 标记）不重复插入。

用法：
    python scripts/migrate_silent_excepts.py            # 试运行（--dry-run）
    python scripts/migrate_silent_excepts.py --apply    # 实际写入
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')
MARK = 'silenced_errors'      # 判重标记

# 不迁移的文件（一次性脚本 / 已废弃 / 本工具自身）
SKIP_FILES = {'migrate_silent_excepts.py', 'silenced_errors.py',
              'audit_imports.py', 'test_actionability.py',
              'setup.py', 'analyze.py'}
SKIP_DIRS = ('_deprecated', '_dev_scratch')


def _is_empty_handler(h: ast.ExceptHandler) -> bool:
    """handler 体是否「什么都没有」——只有 pass 或空 = 静默。"""
    body = [s for s in h.body if not (isinstance(s, ast.Expr)
                                      and isinstance(s.value, ast.Constant))]
    if not body:
        return True
    return len(body) == 1 and isinstance(body[0], ast.Pass)


def _already_migrated(src_lines: list, h: ast.ExceptHandler) -> bool:
    seg = '\n'.join(src_lines[h.lineno - 1:h.end_lineno])
    return MARK in seg


def migrate_file(path: str, apply: bool = False):
    """
    对单个文件做迁移。返回 (changed, n_records, notes)
    """
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()
    if MARK in src:
        return False, 0, ['已迁移过，跳过']

    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return False, 0, [f'语法错误，跳过: {e}']

    src_lines = src.split('\n')
    mod = 'scripts.' + os.path.basename(path)[:-3]

    # 收集 (handler, indent, has_return, ret_expr)
    edits = []      # (lineno, [new_lines])
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            if h.type is None or (isinstance(h.type, ast.Name)
                                  and h.type.id in ('Exception', 'BaseException')):
                pass
            else:
                continue                      # 只管裸/Exception 型
            if not _is_empty_handler(h):
                continue                      # 已有可观测产出，不动
            if _already_migrated(src_lines, h):
                continue

            # 缩进：handler 首行的前导空白
            hline = src_lines[h.lineno - 1]
            indent = hline[:len(hline) - len(hline.lstrip())]
            unit = '    '
            body_indent = indent + unit

            # handler 的 as 名字（注意：name 在 ExceptHandler 上，Try 上没有）
            exc_var = h.name

            # 降级形态：body 里是否 return
            rets = [s for s in h.body if isinstance(s, ast.Return)]
            if rets:
                r = rets[0]
                ret_expr = ast.unparse(r.value) if r.value else 'None'
            else:
                ret_expr = None

            if exc_var:
                # 有 `as e`：在 handler body 首行插入登记（原 body 保留）
                call = (f"record_result(__name__, '{_guess_func(src_lines, h)}', {exc_var}, "
                        + (f"result={ret_expr}, " if ret_expr else "")
                        + "note='静默降级')")
                edits.append((h.lineno, [body_indent + call]))
            else:
                # 裸 except / except Exception 无 as：
                # **替换** handler 头为 `except Exception as _sexc:`，
                # 并在 body 首行插入登记（原 body 保留）。
                # 关键：替换而非插入，否则原 except 行会残留 → 语法错误。
                call = (f"record(__name__, '{_guess_func(src_lines, h)}', _sexc, "
                        f"note='静默降级')")
                edits.append((h.lineno, [
                    f"{indent}except Exception as _sexc:",
                    body_indent + call,
                ], True))   # replace=True

            n += 1

    if not edits:
        return False, 0, ['无静默 handler']

    # 构造新源码（从后往前处理，避免行号漂移）
    new_lines = list(src_lines)
    for item in sorted(edits, key=lambda x: -x[0]):
        lineno, ins = item[0], item[1]
        replace = len(item) > 2 and item[2]
        if replace:
            # **替换** handler 头（删原行）+ 插登记行。
            # 关键：原 except 行必须被替换掉，否则会出现两个连续 except → 语法错误。
            new_lines[lineno - 1:lineno] = ins
        else:
            # 在该行之后插入（不改原行）
            new_lines[lineno:lineno] = ins

    new_src = '\n'.join(new_lines)

    # ── 护栏：语法校验 ──
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        return False, 0, [f'🔴 改造后语法错误，已放弃: line {e.lineno} {e.msg}']

    if apply:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(path, f'{path}.bak_{ts}')       # 备份
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_src)
        # 确保 import 存在
        _ensure_import(path)

    return True, n, [f'已登记 {n} 处']


def _guess_func(lines, h):
    """向上找最近的 def 名。"""
    for i in range(h.lineno - 2, -1, -1):
        s = lines[i].lstrip()
        if s.startswith('def ') or s.startswith('async def '):
            name = s.split('def ', 1)[1].split('(')[0].strip()
            return name or '<module>'
        if s.startswith('class '):
            break
    return '<module>'


def _ensure_import(path: str):
    """补 silenced_errors 的 import（幂等）。"""
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()
    if 'from scripts.silenced_errors import' in src or \
       'from silenced_errors import' in src:
        return
    lines = src.split('\n')
    # 插到最后一个顶层 import 之后
    idx = 0
    for i, s in enumerate(lines[:60]):
        if s.startswith('import ') or s.startswith('from '):
            idx = i + 1
    ins = ('try:    # 2026-10-19 审计：静默降级登记\n'
           '    from scripts.silenced_errors import record, record_result\n'
           'except ImportError:\n'
           '    from silenced_errors import record, record_result')
    lines[idx:idx] = ins.split('\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='实际写入（默认试运行）')
    ap.add_argument('--only', default='', help='只处理指定文件（逗号分隔）')
    args = ap.parse_args()

    only = set(x.strip() for x in args.only.split(',') if x.strip())
    total_changed = total_rec = 0
    files = []

    for fn in sorted(os.listdir(SCRIPTS)):
        if not fn.endswith('.py'):
            continue
        if fn in SKIP_FILES:
            continue
        if any(fn.startswith(d) or d in fn for d in SKIP_DIRS):
            continue
        if only and fn not in only:
            continue
        p = os.path.join(SCRIPTS, fn)
        changed, n, notes = migrate_file(p, apply=args.apply)
        if changed:
            total_changed += 1
            total_rec += n
            files.append((fn, n))
        if n or notes and notes[0].startswith('无静默') is False:
            print(f'  {fn:38s} {notes[0]}')

    print('=' * 60)
    mode = '已写入' if args.apply else '试运行（加 --apply 生效）'
    print(f'{mode}：{total_changed} 个文件，共登记 {total_rec} 处静默降级')
    if args.apply and total_changed:
        # 全量语法校验
        bad = []
        for fn, _ in files:
            p = os.path.join(SCRIPTS, fn)
            r = subprocess.run([sys.executable, '-m', 'py_compile', p],
                               capture_output=True)
            if r.returncode != 0:
                bad.append((fn, r.stderr.decode('utf-8', 'ignore')[:120]))
        if bad:
            print('\n🔴 编译失败：')
            for fn, err in bad:
                print(f'  {fn}: {err}')
            print('  备份文件已留（*.bak_*），可用 git 或备份回滚。')
            return 1
        print('✅ 全部文件编译通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())