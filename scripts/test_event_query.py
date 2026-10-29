#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 hithink-event-query 的返回字段
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from iwencai_provider import query_iwencai

# 测试查询：贵州茅台的业绩预告
test_queries = [
    '贵州茅台 业绩预告',
    '贵州茅台 增发配股',
    '贵州茅台 股权质押',
    '贵州茅台 限售解禁',
    '贵州茅台 机构调研',
    '贵州茅台 监管函',
    '贵州茅台 股东大会',
]

print("="*80)
print("测试 hithink-event-query 返回字段")
print("="*80)

for query in test_queries:
    print(f"\n查询: {query}")
    print("-" * 80)
    
    result = query_iwencai(
        skill_id='hithink-event-query',
        query=query,
        page=1,
        limit=3
    )
    
    if result['success']:
        datas = result['datas']
        print(f"✅ 成功 | 返回 {len(datas)} 条，共 {result['code_count']} 条")
        
        if datas:
            # 打印第一条数据的所有字段
            first = datas[0]
            print(f"字段列表: {list(first.keys())}")
            print("第一条数据:")
            for k, v in first.items():
                print(f"  {k}: {v}")
        else:
            print("⚠️ 无数据")
    else:
        print(f"❌ 失败: {result['error']}")

print("\n" + "="*80)
print("测试完成")
print("="*80)
