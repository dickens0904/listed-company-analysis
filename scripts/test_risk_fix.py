# -*- coding: utf-8 -*-
"""测试 risk.py 修复：add_signal 去重后才计分"""
import sys
sys.path.insert(0, '.')
from risk import assess_risk

# Case 1: 无重复信号 → 正常计分
findings_normal = {
    'financial': {'audit_opinion': '保留意见', 'key_risks': ['连续亏损3年']},
    'announcements': {'key_events': [{'title': '关于重大诉讼的公告'}]},
    'executives': {'summary': {'warnings': []}},
    'capital': {'risks': []},
    'regulatory': {'summary': {'by_severity': {}}},
    'subsidiary': {'subsidiaries': []},
    'related': {'risks': []},
}
result1 = assess_risk(findings_normal)
print(f"Case 1: score={result1['score']}, signals={len(result1['signals'])}")
# 审计20 + 诉讼15 + 财务5 = 40
assert result1['score'] == 40, f"Expected 40, got {result1['score']}"
assert len(result1['signals']) == 3, f"Expected 3 signals, got {len(result1['signals'])}"
print("✅ Case 1 PASS: 无重复信号正常计分")

# Case 2: 重复财务风险信号 → 不应重复计分
findings_dup = {
    'financial': {'audit_opinion': '标准无保留意见', 'key_risks': ['连续亏损3年', '连续亏损3年', '连续亏损3年']},
    'announcements': {'key_events': []},
    'executives': {'summary': {'warnings': []}},
    'capital': {'risks': []},
    'regulatory': {'summary': {'by_severity': {}}},
    'subsidiary': {'subsidiaries': []},
    'related': {'risks': []},
}
result2 = assess_risk(findings_dup)
print(f"Case 2: score={result2['score']}, signals={len(result2['signals'])}")
# 3条重复的'连续亏损3年'应只计1次 → 5分（不是15分）
assert result2['score'] == 5, f"Expected 5, got {result2['score']}"
assert len(result2['signals']) == 1, f"Expected 1 signal, got {len(result2['signals'])}"
print("✅ Case 2 PASS: 重复信号不重复计分")

# Case 3: 重复高管警告 → 不应重复计分
findings_exec_dup = {
    'financial': {'audit_opinion': '标准无保留意见'},
    'announcements': {'key_events': []},
    'executives': {'summary': {'warnings': ['⚠️ 董事长辞职', '⚠️ 董事长辞职', '⚠️ 董事长辞职']}},
    'capital': {'risks': []},
    'regulatory': {'summary': {'by_severity': {}}},
    'subsidiary': {'subsidiaries': []},
    'related': {'risks': []},
}
result3 = assess_risk(findings_exec_dup)
print(f"Case 3: score={result3['score']}, signals={len(result3['signals'])}")
# 3条重复的'董事长辞职'应只计1次 → 10分（不是30分）
assert result3['score'] == 10, f"Expected 10, got {result3['score']}"
assert len(result3['signals']) == 1, f"Expected 1 signal, got {len(result3['signals'])}"
print("✅ Case 3 PASS: 重复高管警告不重复计分")

# Case 4: 多条不同高管警告 → 分别计分
findings_exec_multi = {
    'financial': {'audit_opinion': '标准无保留意见'},
    'announcements': {'key_events': []},
    'executives': {'summary': {'warnings': ['⚠️ 董事长辞职', '⚠️ 总裁辞职', '⚠️ 董事辞职']}},
    'capital': {'risks': []},
    'regulatory': {'summary': {'by_severity': {}}},
    'subsidiary': {'subsidiaries': []},
    'related': {'risks': []},
}
result4 = assess_risk(findings_exec_multi)
print(f"Case 4: score={result4['score']}, signals={len(result4['signals'])}")
# 董事长10 + 总裁10 + 董事5 = 25分
assert result4['score'] == 25, f"Expected 25, got {result4['score']}"
assert len(result4['signals']) == 3, f"Expected 3 signals, got {len(result4['signals'])}"
print("✅ Case 4 PASS: 不同高管警告分别计分")

# Case 5: 重复资金动作信号 → 不应重复计分
findings_cap_dup = {
    'financial': {'audit_opinion': '标准无保留意见'},
    'announcements': {'key_events': []},
    'executives': {'summary': {'warnings': []}},
    'capital': {'risks': [
        {'risk_signal': '大股东减持'},
        {'risk_signal': '大股东减持'},
        {'risk_signal': '大股东减持'},
    ]},
    'regulatory': {'summary': {'by_severity': {}}},
    'subsidiary': {'subsidiaries': []},
    'related': {'risks': []},
}
result5 = assess_risk(findings_cap_dup)
print(f"Case 5: score={result5['score']}, signals={len(result5['signals'])}")
# 3条重复的'大股东减持'应只计1次 → 5分（不是15分）
assert result5['score'] == 5, f"Expected 5, got {result5['score']}"
assert len(result5['signals']) == 1, f"Expected 1 signal, got {len(result5['signals'])}"
print("✅ Case 5 PASS: 重复资金动作信号不重复计分")

print(f"\n{'='*50}")
print("🎉 所有测试通过！risk.py 去重修复验证完成")
