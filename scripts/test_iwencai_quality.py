#!/usr/bin/env python3
"""测试iwencai各维度的数据质量"""
import json
from iwencai_adapter import query_iwencai

# 测试4个维度的数据质量
tests = [
    ('限售解禁', 'restricted_unlock'),
    ('股权质押', 'equity_pledge'), 
    ('监管函', 'regulatory_letters'),
    ('其他重大事项', 'other_major_events'),
]

print('=' * 60)
print('iwencai 数据质量测试 (002180)')
print('=' * 60)

for event_type, dim_name in tests:
    print(f'\n【{event_type}】')
    result = query_iwencai('002180', event_type, limit=5)
    
    if not result['success']:
        print(f'  ❌ 失败: {result.get("error")}')
        continue
    
    data = result.get('data', [])
    print(f'  返回记录数: {len(data)}')
    
    if data:
        # 显示第一条记录的所有字段
        first = data[0]
        print(f'  字段数: {len(first)}')
        print(f'  字段列表: {list(first.keys())[:10]}')
        # 显示部分内容
        for k, v in list(first.items())[:5]:
            val = str(v)[:50] if v else 'N/A'
            print(f'    {k}: {val}')
    else:
        print('  ⚠️ 无数据返回')
