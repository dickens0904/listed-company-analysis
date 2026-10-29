#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 iwencai_provider.py
"""
import sys
import os

# 添加 scripts 目录到 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 检查 API Key
api_key = os.environ.get('IWENCAI_API_KEY', '')
if not api_key:
    print("❌ 未找到 IWENCAI_API_KEY 环境变量")
    print("请先配置: $env:IWENCAI_API_KEY='your-api-key'")
    sys.exit(1)

print(f"✅ IWENCAI_API_KEY 已配置 (前10字符: {api_key[:10]}...)")

# 导入模块
try:
    from iwencai_provider import query_iwencai, query_basicinfo, fetch_all_pages
    print("✅ iwencai_provider 模块导入成功")
except Exception as e:
    print(f"❌ 模块导入失败: {e}")
    sys.exit(1)

# 测试 1: 基本查询（hithink-basicinfo-query）
print("\n" + "="*60)
print("测试 1: hithink-basicinfo-query - 查询贵州茅台基本信息")
print("="*60)

result = query_iwencai(
    skill_id='hithink-basicinfo-query',
    query='贵州茅台 股票代码 股票简称 实控人',
    page=1,
    limit=5
)

if result['success']:
    print(f"✅ 成功 | 返回 {len(result['datas'])} 条，共 {result['code_count']} 条")
    print(f"使用查询: {result['query_used']}")
    print("-" * 60)
    for i, item in enumerate(result['datas'][:3], 1):
        print(f"{i}. {item}")
    if len(result['datas']) > 3:
        print(f"... 共 {len(result['datas'])} 条，仅显示前 3 条")
else:
    print(f"❌ 失败: {result['error']}")

# 测试 2: 事件查询（hithink-event-query）
print("\n" + "="*60)
print("测试 2: hithink-event-query - 查询贵州茅台最近公告")
print("="*60)

result2 = query_iwencai(
    skill_id='hithink-event-query',
    query='贵州茅台 最近公告',
    page=1,
    limit=5
)

if result2['success']:
    print(f"✅ 成功 | 返回 {len(result2['datas'])} 条，共 {result2['code_count']} 条")
    print(f"使用查询: {result2['query_used']}")
    print("-" * 60)
    for i, item in enumerate(result2['datas'][:3], 1):
        print(f"{i}. {item}")
    if len(result2['datas']) > 3:
        print(f"... 共 {len(result2['datas'])} 条，仅显示前 3 条")
else:
    print(f"❌ 失败: {result2['error']}")

# 测试 3: 自动翻页（fetch_all_pages）
print("\n" + "="*60)
print("测试 3: fetch_all_pages - 自动翻页获取所有数据")
print("="*60)

all_datas = fetch_all_pages(
    skill_id='hithink-basicinfo-query',
    query='A股 股票代码 股票简称',
    max_pages=2,
    limit=10
)

print(f"✅ 成功获取 {len(all_datas)} 条数据（最多翻 2 页）")
if all_datas:
    print("前 3 条:")
    for i, item in enumerate(all_datas[:3], 1):
        code = item.get('股票代码', item.get('code', 'N/A'))
        name = item.get('股票简称', item.get('name', 'N/A'))
        print(f"  {i}. {code} - {name}")

print("\n" + "="*60)
print("所有测试完成")
print("="*60)
