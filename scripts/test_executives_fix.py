# -*- coding: utf-8 -*-
"""测试 executives.py 修复：过滤制度文件类公告"""
import sys
sys.path.insert(0, '.')
from executives import _classify_exec_change

# 测试 _classify_exec_change 分类结果
test_cases = [
    # (title, expected_type, should_be_in_changes)
    ("关于公司总经理辞职的公告", '辞职/离职', True),
    ("关于聘任公司副总裁的公告", '新任/补选', True),
    ("关于选举公司第五届董事会非独立董事的公告", '换届选举', True),
    ("关于公司董事会任期届满的公告", '换届', True),
    ("关于公司董事会会议决议的公告", '制度文件', False),
    ("关于公司2024年度股东大会决议的公告", '制度文件', False),
    ("关于公司董事收到行政处罚决定书的公告", '制度文件', False),
    ("关于召开2024年年度股东大会的通知", '制度文件', False),
    ("关于公司2024年度报告的公告", '制度文件', False),
    ("关于公司监事会工作报告的公告", '制度文件', False),
    ("关于公司独立董事述职报告的公告", '制度文件', False),
    ("关于公司董事、监事和高级管理人员减持股份进展的公告", '制度文件', False),
    ("关于选举公司职工代表监事的公告", '换届选举', True),
    ("关于补选公司非独立董事的公告", '换届选举', True),
    ("关于公司财务总监离任的公告", '辞职/离职', True),
    ("关于公司董事会秘书辞职的公告", '辞职/离职', True),
    ("关于公司聘任财务总监的公告", '新任/补选', True),
]

passed = 0
failed = 0

for title, expected_type, should_be_in_changes in test_cases:
    actual_type = _classify_exec_change(title)
    would_include = actual_type != '制度文件'
    
    type_ok = actual_type == expected_type
    include_ok = would_include == should_be_in_changes
    
    if type_ok and include_ok:
        status = "✅"
        passed += 1
    else:
        status = "❌"
        failed += 1
        if not type_ok:
            print(f"{status} 类型错误: '{title}' → 预期'{expected_type}', 实际'{actual_type}'")
        if not include_ok:
            print(f"{status} 包含错误: '{title}' → 预期{'包含' if should_be_in_changes else '排除'}, 实际{'包含' if would_include else '排除'}")
    
print(f"\n{'='*50}")
print(f"结果: {passed} 通过, {failed} 失败")
if failed == 0:
    print("🎉 所有测试通过！executives.py 修复验证完成")
else:
    print("⚠️ 有测试失败，需要进一步修复")
    sys.exit(1)
