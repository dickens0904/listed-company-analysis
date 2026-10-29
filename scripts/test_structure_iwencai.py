# -*- coding: utf-8 -*-
"""测试 structure.py 的 i问财集成

⚠️ 规则：股票名称不写死在代码里，必须从 API 动态获取。
    如果 hardcode 名称，一旦公司更名，测试永远带着错误的名字跑。
"""
import sys, json
sys.path.insert(0, 'C:/Users/Administrator/.qclaw/workspace-agent-550df5d1/skills/listed-company-analysis/scripts')
sys.stdout.reconfigure(encoding='utf-8')

from structure import _fetch_actual_controller_iwencai, _fetch_shareholder_changes_iwencai
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result

def _get_stock_name(code):
    """从 i问财 basicinfo 动态获取股票名称，避免 hardcode。"""
    try:
        from iwencai_provider import query_iwencai
        rows = query_iwencai(f"{code} 股票简称")
        if rows and len(rows) > 0:
            return rows[0].get('股票简称', code)
    except Exception as _sexc:
        record(__name__, '_get_stock_name', _sexc, note='静默降级')
        pass
    return code  # fallback 到代码本身

def test_iwencai_functions():
    """测试i问财股权数据获取"""
    test_codes = ["600519", "000858", "002180", "002259"]
    
    for code in test_codes:
        name = _get_stock_name(code)  # 动态获取，不 hardcode
        print(f"\n{'='*60}")
        print(f"测试: {name} ({code})")
        print('='*60)
        
        # 1. 实控人
        print("\n[实控人] i问财:")
        ac = _fetch_actual_controller_iwencai(code)
        if ac:
            print(f"  ✓ 实控人: {ac.get('name', 'N/A')}")
            print(f"  ✓ 来源: {ac.get('source', 'N/A')}")
            print(f"  ✓ 持股比例: {ac.get('ratio_pct', 'N/A')}%")
            print(f"  ✓ 变动类型: {ac.get('control_type', 'N/A')}")
        else:
            print(f"  ✗ 未获取到实控人数据（i问财无数据）")
        
        # 2. 股东持股变动
        print("\n[股东持股变动] i问财:")
        changes = _fetch_shareholder_changes_iwencai(code)
        if changes:
            print(f"  ✓ 获取到 {len(changes)} 条变动记录:")
            for ch in changes[:5]:
                print(f"    - {ch.get('holder_name', 'N/A')} | {ch.get('change_type', 'N/A')} | "
                      f"持股{ch.get('ratio_pct', 'N/A')}% | 公告日:{ch.get('announce_date', 'N/A')}")
        else:
            print(f"  ✗ 未获取到变动数据（i问财无数据）")


if __name__ == "__main__":
    test_iwencai_functions()
