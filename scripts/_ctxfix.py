# -*- coding: utf-8 -*-
"""
_ctxfix.py - 双运行上下文兼容垫片（2026-10-21）
=============================================

🔴 真实根因（实测，比"路径没加"更阴）：
    本 skill 有 200+ 处 `from scripts.xxx import ...`。报错
    `No module named 'scripts.safe_request'` 并不是因为"没找到 scripts"，
    而是 **pywin32 的 site-packages\\win32\\scripts 目录以"命名空间包"身份抢占了
    `scripts` 这个名字**（该目录无 __init__.py，但 PEP 420 命名空间包照样 import 成功）：

        >>> import scripts
        >>> scripts.__path__
        ['C:\\\\...\\\\site-packages\\\\win32\\\\scripts']     ← 是 pywin32 的目录！

    于是 `import scripts` 不报错、`from scripts.safe_request` 必然失败。
    `python scripts/analyze.py` 之所以正常，是因为 analyze.py 先把 skill 根插到
    sys.path[0]，先命中真包；而 `cd scripts && python -c ...` 就命中 pywin32。

方案：
    判断 `scripts.__path__` 是否包含本文件所在目录——是则不动；否则强制用指向本目录
    的包覆盖 `sys.modules['scripts']`（含 scripts.safe_request 等已污染子模块清理）。

用法（务必放在任何 `from scripts.` 之前）：
    import _ctxfix  # noqa: F401
    from scripts.safe_request import safe_get
"""

import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))


def _path_ok(mod) -> bool:
    try:
        paths = [os.path.abspath(p) for p in (getattr(mod, '__path__', []) or [])]
    except Exception:
        return False
    return _HERE in paths


def install() -> bool:
    """确保 sys.modules['scripts'] 指向本目录。返回是否做了覆盖。"""
    cur = sys.modules.get('scripts')
    if cur is not None and _path_ok(cur):
        return False

    # 清理被抢占的 scripts.* 子模块（它们来自 pywin32 等目录，不能复用）
    for name in [n for n in list(sys.modules) if n == 'scripts' or n.startswith('scripts.')]:
        sys.modules.pop(name, None)

    pkg = types.ModuleType('scripts')
    pkg.__path__ = [_HERE]
    pkg.__file__ = os.path.join(_HERE, '__init__.py')
    pkg.__package__ = 'scripts'
    sys.modules['scripts'] = pkg
    try:  # 保证 `import scripts.xxx` 能拿到同目录模块
        if _HERE not in sys.path:
            sys.path.insert(0, _HERE)
    except Exception:
        pass
    return True


_OVERRIDDEN = install()

if __name__ == '__main__':
    import scripts
    print('scripts.__path__ =', list(getattr(scripts, '__path__', [])))
    print('overridden =', _OVERRIDDEN)
