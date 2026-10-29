# -*- coding: utf-8 -*-
"""
audit_imports.py — 全量导入体检（2026-10-19）
逐个 import scripts/*.py，暴露"能写不能跑"的模块：裸名导入、缺依赖、循环导入。
"""
import sys, os, importlib, traceback, warnings
warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # skill 根
SCRIPTS = os.path.join(ROOT, 'scripts')
sys.path.insert(0, ROOT)
sys.path.insert(0, SCRIPTS)

mods = []
for fn in sorted(os.listdir(SCRIPTS)):
    if not fn.endswith('.py') or fn.startswith('test_'):
        continue
    mods.append('scripts.' + fn[:-3])

OK, FAIL, WARN = [], [], []
# 已知第三方缺失不算代码缺陷，单独归类
THIRD_PARTY_HINT = ('No module named',)
for m in mods:
    try:
        importlib.import_module(m)
        OK.append(m)
    except ModuleNotFoundError as e:
        name = str(e).split("'")[1] if "'" in str(e) else str(e)
        # 判断是第三方包还是本仓库模块
        local = os.path.exists(os.path.join(ROOT, 'scripts', name + '.py')) or \
                os.path.exists(os.path.join(ROOT, name + '.py'))
        (FAIL if local else WARN).append((m, f"ModuleNotFoundError: {name}",
                                          '本地模块缺失/路径错' if local else '第三方包未装'))
    except ImportError as e:
        FAIL.append((m, f"ImportError: {e}", '导入链断裂'))
    except SyntaxError as e:
        FAIL.append((m, f"SyntaxError: line {e.lineno} {e.msg}", '语法错误'))
    except Exception as e:
        FAIL.append((m, f"{type(e).__name__}: {str(e)[:80]}", '执行期异常'))

print("=" * 70)
print(f"导入体检：{len(mods)} 个模块 | OK {len(OK)} | 本地缺陷 {len(FAIL)} | 第三方缺失 {len(WARN)}")
print("=" * 70)
if FAIL:
    print("\n🔴 本地代码缺陷（必须修）")
    for m, err, why in FAIL:
        print(f"  {m:48s} {err}")
        print(f"      → {why}")
if WARN:
    print("\n🟡 第三方包未装（非代码缺陷，但会阻断运行）")
    seen = set()
    for m, err, _ in WARN:
        nm = err.split("'")[1] if "'" in err else err
        if nm not in seen:
            seen.add(nm)
            print(f"  {nm}  ← 影响 {sum(1 for _, e, _ in WARN if (e.split(chr(39))[1] if chr(39) in e else '') == nm)} 个模块")
print(f"\n✅ OK 模块 {len(OK)} 个")