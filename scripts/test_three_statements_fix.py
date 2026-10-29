# -*- coding: utf-8 -*-
"""测试 three_statements.py 修复：gross_profit 计算"""
import sys
sys.path.insert(0, '.')
from three_statements import ThreeStatementsExtractor

# 创建实例（需要一个假的pdf_path，因为parse_income_statement不依赖PDF）
class MockExtractor(ThreeStatementsExtractor):
    def __init__(self):
        pass  # 跳过__init__中对pdf_path的依赖

parser = MockExtractor()

# Case 1: 有毛利行 → 直接提取
rows_case1 = [
    ['营业收入', 1000, 800],
    ['营业成本', 600, 500],
    ['毛利', 400, 300],
    ['营业利润', 200, 150],
]
result1 = parser.parse_income_statement(rows_case1)
assert result1['gross_profit'] == (400, 300), f"Expected (400, 300), got {result1['gross_profit']}"
print("✅ Case 1 PASS: 毛利行直接提取")

# Case 2: 无毛利行 → 回退计算 revenue - operating_cost
rows_case2 = [
    ['营业收入', 1000, 800],
    ['营业成本', 600, 500],
    ['营业利润', 200, 150],
]
result2 = parser.parse_income_statement(rows_case2)
assert result2['gross_profit'] == (400, 300), f"Expected (400, 300), got {result2['gross_profit']}"
print("✅ Case 2 PASS: 回退计算 revenue - operating_cost")

# Case 3: revenue 有值但 operating_cost 为 None → gross_profit 应为 None
rows_case3 = [
    ['营业收入', 1000, 800],
    ['营业利润', 200, 150],
]
result3 = parser.parse_income_statement(rows_case3)
assert result3['gross_profit'] is None, f"Expected None, got {result3['gross_profit']}"
print("✅ Case 3 PASS: operating_cost 缺失时 gross_profit 为 None")

# Case 4: revenue 和 operating_cost 都缺失 → gross_profit 应为 None
rows_case4 = [
    ['营业利润', 200, 150],
]
result4 = parser.parse_income_statement(rows_case4)
assert result4['gross_profit'] is None, f"Expected None, got {result4['gross_profit']}"
print("✅ Case 4 PASS: 两者缺失时 gross_profit 为 None")

# Case 5: revenue tuple 含 None 元素 → 安全处理不崩溃
rows_case5 = [
    ['营业收入', 1000, None],
    ['营业成本', 600, None],
    ['营业利润', 200, None],
]
result5 = parser.parse_income_statement(rows_case5)
assert result5['gross_profit'] == (400, None), f"Expected (400, None), got {result5['gross_profit']}"
print("✅ Case 5 PASS: 含 None 元素安全处理")

# Case 6: 毛利率不应被提取为 gross_profit
rows_case6 = [
    ['营业收入', 1000, 800],
    ['营业成本', 600, 500],
    ['毛利率', 40, 37.5],
    ['营业利润', 200, 150],
]
result6 = parser.parse_income_statement(rows_case6)
assert result6['gross_profit'] == (400, 300), f"Expected (400, 300) from fallback, got {result6['gross_profit']}"
print("✅ Case 6 PASS: 毛利率不被误提取为 gross_profit")

# Case 7: 有毛利行优先于回退计算
rows_case7 = [
    ['营业收入', 1000, 800],
    ['营业成本', 600, 500],
    ['毛利', 350, 280],  # API 返回值可能与 revenue - cost 不同
    ['营业利润', 200, 150],
]
result7 = parser.parse_income_statement(rows_case7)
assert result7['gross_profit'] == (350, 280), f"Expected (350, 280), got {result7['gross_profit']}"
print("✅ Case 7 PASS: 直接提取优先于回退计算")

print(f"\n{'='*50}")
print("🎉 所有测试通过！three_statements.py gross_profit 修复验证完成")
