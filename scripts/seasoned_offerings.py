#!/usr/bin/env python3
"""
增发配股分析模块 (seasoned_offerings)
分析上市公司增发配股情况，包括发行时间、目的、进度、对象、价格、数量等

数据来源: iwencai API (通过 iwencai_adapter.py)

输出字段:
- offering_count: 增发次数
- total_raised: 总募集资金(亿元)
- latest_offering: 最近增发记录
- all_offerings: 所有增发记录
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# 导入iwencai适配器
try:
    from iwencai_adapter import get_seasoned_offerings, log
except ImportError:
    from scripts.iwencai_adapter import get_seasoned_offerings, log


def analyze_seasoned_offerings(
    stock_code: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    分析增发配股记录
    
    Args:
        stock_code: 股票代码
        limit: 返回条数（默认20）
    
    Returns:
        字典，包含分析结果：
        - success: bool
        - offering_count: int (增发次数)
        - total_raised: float (总募集资金，亿元)
        - latest_offering: dict (最近增发记录)
        - all_offerings: list (所有增发记录)
        - source: str (数据来源)
        - error: str (错误信息)
    """
    log(f"分析增发配股记录: {stock_code}", "INFO")
    
    # 获取增发配股数据
    result = get_seasoned_offerings(stock_code, limit=limit)
    
    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "获取数据失败"),
            "source": "iwencai",
        }
    
    offerings = result.get("data", [])
    
    if not offerings:
        return {
            "success": True,
            "offering_count": 0,
            "total_raised": 0,
            "latest_offering": None,
            "all_offerings": [],
            "source": "iwencai",
        }
    
    # 1. 统计增发次数
    offering_count = len(offerings)
    
    # 2. 计算总募集资金
    total_raised = 0
    for o in offerings:
        funds = o.get("募集资金", 0) or o.get("预案募集金额", 0) or 0
        if funds:
            total_raised += float(funds)
    
    # 转换为亿元
    total_raised_yi = total_raised / 100000000 if total_raised else 0
    
    # 3. 最近增发记录
    latest_offering = offerings[0] if offerings else None
    
    return {
        "success": True,
        "offering_count": offering_count,
        "total_raised": round(total_raised_yi, 2),
        "latest_offering": latest_offering,
        "all_offerings": offerings,
        "source": "iwencai",
    }


def generate_report(data: Dict[str, Any]) -> str:
    """生成增发配股分析报告"""
    if not data.get("success"):
        return f"## 增发配股分析\n\n❌ 分析失败: {data.get('error', '未知错误')}\n"
    
    offering_count = data.get("offering_count", 0)
    
    if offering_count == 0:
        return "## 增发配股分析\n\n无增发配股记录\n"
    
    md = "## 增发配股分析\n\n"
    
    # 1. 增发统计
    total_raised = data.get("total_raised", 0)
    md += f"**增发次数**: {offering_count} 次\n"
    md += f"**总募集资金**: {total_raised:.2f} 亿元\n\n"
    
    # 2. 最近增发
    latest = data.get("latest_offering", {})
    if latest:
        md += "**最近增发**:\n"
        md += f"- 预案公告日: {latest.get('预案公告日', 'N/A')}\n"
        md += f"- 目的: {latest.get('目的', 'N/A')}\n"
        md += f"- 进度: {latest.get('进度', 'N/A')}\n"
        
        funds = latest.get('募集资金') or latest.get('预案募集金额')
        if funds:
            md += f"- 募集资金: {float(funds)/100000000:.2f} 亿元\n"
        
        price = latest.get('增发价格')
        if price:
            md += f"- 增发价格: {float(price):.2f} 元/股\n"
        
        qty = latest.get('发行数量')
        if qty:
            md += f"- 发行数量: {float(qty)/100000000:.2f} 股\n"
        
        md += "\n"
    
    # 3. 历史增发列表
    md += "**历史增发记录**:\n"
    for i, o in enumerate(data.get("all_offerings", [])[:5], 1):
        date = o.get('预案公告日', 'N/A')
        purpose = o.get('目的', 'N/A')[:20] if o.get('目的') else 'N/A'
        funds = o.get('募集资金') or o.get('预案募集金额')
        funds_str = f"{float(funds)/100000000:.2f}亿" if funds else 'N/A'
        
        md += f"- {i}. {date} | {purpose} | {funds_str}\n"
    
    return md


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python seasoned_offerings.py <股票代码>")
        sys.exit(1)
    
    stock_code = sys.argv[1]
    
    print("=" * 60)
    print(f"增发配股分析: {stock_code}")
    print("=" * 60)
    
    result = analyze_seasoned_offerings(stock_code)
    
    if result["success"]:
        print(f"\n✅ 分析成功!")
        print(f"   增发次数: {result['offering_count']}")
        print(f"   总募集资金: {result['total_raised']:.2f} 亿元")
        
        if result.get("latest_offering"):
            latest = result["latest_offering"]
            print(f"\n   最近增发:")
            print(f"   - 预案公告日: {latest.get('预案公告日')}")
            print(f"   - 目的: {latest.get('目的')}")
            print(f"   - 进度: {latest.get('进度')}")
    else:
        print(f"\n❌ 分析失败: {result.get('error')}")


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = generate_report(data)
    return ["\n" + md]
