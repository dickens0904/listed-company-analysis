# -*- coding: utf-8 -*-
"""完整build_structure集成测试"""
import sys, json, os
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8')
from structure import build_structure

os.makedirs('test_output', exist_ok=True)

def test_full(stock_code, market='A股'):
    print(f"\n{'='*60}")
    print(f"build_structure 完整测试: {stock_code}")
    print(f"{'='*60}")
    result = build_structure(stock_code, market, {}, data_dir='test_output')
    # 输出关键字段
    ac = result.get('actual_controller', {})
    print(f"\n[实控人] i问财优先")
    print(f"  名称: {ac.get('name', 'N/A')}")
    print(f"  来源: {ac.get('source', 'N/A')}")
    print(f"  持股比例: {ac.get('ratio_pct', 'N/A')}")
    sc = result.get('shareholder_changes', [])
    print(f"\n[股东持股变动] 共{len(sc)}条")
    for r in sc[:3]:
        print(f"  {r.get('holder_name','N/A')[:15]} | {r.get('change_type')} | {r.get('ratio_pct')} | {r.get('announce_date')}")
    print(f"\n[前十大股东] AKShare 共{len(result.get('top_shareholders',[]))}条")
    print(f"[流通股东] AKShare 共{len(result.get('circulate_shareholders',[]))}条")
    print(f"[输出文件] test_output/{stock_code}_structure.json")
    return result

# 测试4只股票
for code in ['600519', '000858', '002180', '002259']:
    test_full(code)
