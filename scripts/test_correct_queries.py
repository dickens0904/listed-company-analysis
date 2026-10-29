#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用正确的查询词测试各 iwencai 技能，看看实际返回字段
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from iwencai_provider import query_iwencai

# 每个技能的正确查询词（从 SKILL.md 示例提取）
test_cases = [
    {
        'skill_id': 'hithink-basicinfo-query',
        'query': '贵州茅台 实控人 前十大股东 公司概况',
        'desc': '基本信息：实控人 + 股东 + 公司概况'
    },
    {
        'skill_id': 'hithink-event-query',
        'query': '贵州茅台 业绩预告 限售解禁 监管函',
        'desc': '事件数据：业绩预告 + 限售解禁 + 监管函'
    },
    {
        'skill_id': 'hithink-industry-query',
        'query': '贵州茅台 行业分类 行业PE 行业排名',
        'desc': '行业数据：行业分类 + 行业PE + 排名'
    },
    {
        'skill_id': 'hithink-macro-query',
        'query': 'GDP CPI PMI 最新数据',
        'desc': '宏观数据：GDP + CPI + PMI'
    },
    {
        'skill_id': 'hithink-market-query',
        'query': 'A股 涨跌幅排行 成交额排行',
        'desc': '市场数据：涨跌幅 + 成交额排行'
    },
]

print("="*80)
print("用正确查询词测试 iwencai 各技能")
print("="*80)

for test in test_cases:
    skill_id = test['skill_id']
    query = test['query']
    desc = test['desc']
    
    print(f"\n{'='*80}")
    print(f"技能: {skill_id}")
    print(f"说明: {desc}")
    print(f"查询: {query}")
    print(f"{'='*80}")
    
    result = query_iwencai(
        skill_id=skill_id,
        query=query,
        page=1,
        limit=3
    )
    
    if result['success']:
        datas = result['datas']
        print(f"✅ 成功 | 返回 {len(datas)} 条，共 {result['code_count']} 条")
        
        if datas:
            # 打印所有数据的字段（合并去重）
            all_fields = set()
            for item in datas:
                all_fields.update(item.keys())
            all_fields = sorted(all_fields)
            
            print(f"所有字段 ({len(all_fields)} 个):")
            for f in all_fields:
                print(f"  - {f}")
            
            print("\n第一条数据:")
            first = datas[0]
            for k, v in first.items():
                print(f"  {k}: {v}")
        else:
            print("⚠️ 无数据")
            print(f"chunks_info: {result.get('chunks_info', {})}")
    else:
        print(f"❌ 失败: {result['error']}")

print("\n" + "="*80)
print("测试完成")
print("="*80)
