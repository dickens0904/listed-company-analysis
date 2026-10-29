#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合测试所有 iwencai 技能，看看各自返回什么格式
"""
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from iwencai_provider import query_iwencai, SKILL_VERSIONS

# 测试查询词（通用）
test_query = '贵州茅台'

print("="*80)
print("综合测试 iwencai 所有技能")
print("="*80)
print(f"已安装技能: {list(SKILL_VERSIONS.keys())}")
print("="*80)

results_summary = []

for skill_id in SKILL_VERSIONS.keys():
    print(f"\n{'='*80}")
    print(f"测试技能: {skill_id}")
    print(f"{'='*80}")
    
    result = query_iwencai(
        skill_id=skill_id,
        query=test_query,
        page=1,
        limit=3
    )
    
    if result['success']:
        datas = result['datas']
        print(f"✅ 成功 | 返回 {len(datas)} 条，共 {result['code_count']} 条")
        print(f"使用查询: {result['query_used']}")
        
        if datas:
            # 打印第一条数据的所有字段
            first = datas[0]
            fields = list(first.keys())
            print(f"字段列表 ({len(fields)} 个): {fields}")
            print("第一条数据示例:")
            for k, v in list(first.items())[:10]:  # 最多显示10个字段
                print(f"  {k}: {v}")
            if len(first) > 10:
                print(f"  ... (共 {len(first)} 个字段，仅显示前 10 个)")
            
            results_summary.append({
                'skill_id': skill_id,
                'success': True,
                'fields': fields,
                'sample': dict(list(first.items())[:5])
            })
        else:
            print("⚠️ 无数据")
            results_summary.append({
                'skill_id': skill_id,
                'success': True,
                'fields': [],
                'sample': {}
            })
    else:
        print(f"❌ 失败: {result['error']}")
        results_summary.append({
            'skill_id': skill_id,
            'success': False,
            'error': result['error']
        })

# 打印汇总
print("\n" + "="*80)
print("测试汇总")
print("="*80)
for r in results_summary:
    skill_id = r['skill_id']
    if r['success']:
        fields_count = len(r['fields'])
        print(f"✅ {skill_id:30s} | 字段数: {fields_count:3d} | 示例字段: {r['fields'][:5] if r['fields'] else '无'}")
    else:
        print(f"❌ {skill_id:30s} | 失败: {r.get('error', '未知错误')}")

print("\n" + "="*80)
print("测试完成")
print("="*80)
