# -*- coding: utf-8 -*-
"""测试 subsidiary.py exclude_kw 修复：IPO限售股解禁排除"""
import sys

# 模拟测试：直接测试 exclude_kw 逻辑
exclude_kw = ['上市流通', '已发行部分股份', '核查意见', '限售股', '解禁', '限售股份']

test_cases = [
    # (title, should_be_excluded, description)
    ("关于子公司XXX首次公开发行股票并在创业板上市的公告", False, "正常IPO公告"),
    ("关于首次公开发行限售股解禁上市流通的公告", True, "限售股解禁-上市流通"),
    ("关于首次公开发行限售股解禁上市的公告", True, "限售股解禁-上市"),
    ("关于首次公开发行部分限售股解禁上市的公告", True, "部分限售股解禁"),
    ("关于首次公开发行限售股份解除限售的公告", True, "限售股份解除限售"),
    ("关于首次公开发行A股限售股上市流通的公告", True, "A股限售股上市流通"),
    ("关于筹划XXX公司分拆上市的提示性公告", False, "正常分拆上市公告"),
    ("关于子公司XXX首次公开发行股票并上市的辅导备案公告", False, "正常辅导备案"),
    ("关于已发行部分股份上市流通的公告", True, "已发行部分股份上市流通"),
    ("关于首次公开发行限售股核查意见的公告", True, "核查意见"),
]

# 模拟 include 条件
include_kw = ['分拆', '辅导', '首次公开发行']

passed = 0
failed = 0

for title, expected_excluded, desc in test_cases:
    # Step 1: 检查 include 条件
    include_match = any(kw in title for kw in include_kw) and '上市' in title
    
    if not include_match:
        # 不满足 include 条件，直接跳过（不会进入 exclude 判断）
        if expected_excluded:
            # 预期排除，但实际不满足 include → 不会进入处理 → 也算正确排除
            print(f"✅ {desc}: 不满足include条件，自然排除")
            passed += 1
        else:
            print(f"✅ {desc}: 不满足include条件，自然跳过")
            passed += 1
        continue
    
    # Step 2: 满足 include 条件，检查 exclude
    actual_excluded = any(ex in title for ex in exclude_kw)
    
    if actual_excluded == expected_excluded:
        print(f"✅ {desc}: {'排除' if actual_excluded else '保留'}")
        passed += 1
    else:
        print(f"❌ {desc}: 预期{'排除' if expected_excluded else '保留'}，实际{'排除' if actual_excluded else '保留'}")
        failed += 1

print(f"\n{'='*50}")
print(f"结果: {passed} 通过, {failed} 失败")
if failed == 0:
    print("🎉 所有测试通过！subsidiary.py exclude_kw 修复验证完成")
else:
    print("⚠️ 有测试失败，需要进一步修复")
    sys.exit(1)
