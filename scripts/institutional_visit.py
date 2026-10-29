#!/usr/bin/env python3
"""
机构调研分析模块 (institutional_visit)
分析上市公司接受机构调研的情况，包括调研频次、参与机构、关注焦点、管理层回应等

数据来源: iwencai API (通过 iwencai_adapter.py)

输出字段:
- visit_count: 调研次数
- visit_trend: 月度趋势
- institution_types: 机构类型分布 (基金/保险/社保/QFII等)
- focus_topics: 关注焦点 (从内容中提取)
- management_response: 管理层回应态度
- latest_visit: 最近调研记录
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

# 导入iwencai适配器
# 兼容两种调用方式：
#   ① 作为包内模块被 `scripts.institutional_visit` 导入（sys.path 含项目根，不含 scripts/）
#   ② 作为顶层脚本直接运行（sys.path 含 scripts/）
# 旧版裸名 `from iwencai_adapter import ...` 在 ① 情形下 ImportError → dispatcher 导入即崩，
# analyze.py 完全无法启动（2026-10-19 实跑暴露）。
try:
    from iwencai_adapter import get_institutional_visits, log
except ImportError:
    from scripts.iwencai_adapter import get_institutional_visits, log


# 机构类型关键词映射
INSTITUTION_TYPE_KEYWORDS = {
    "基金": ["基金", "资产管理", "私募基金"],
    "保险": ["保险", "人寿保险", "财产保险"],
    "社保": ["社保", "养老保险", "养老金"],
    "QFII": ["QFII", "外资", "境外机构"],
    "券商": ["券商", "证券", "投行"],
    "银行": ["银行", "信托"],
    "其他": [],
}


def analyze_institutional_visits(
    stock_code: str,
    months: int = 12,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    分析机构调研记录
    
    Args:
        stock_code: 股票代码
        months: 查询最近N个月的数据（默认12个月）
        limit: 返回条数（默认50）
    
    Returns:
        字典，包含分析结果：
        - success: bool
        - visit_count: int (调研次数)
        - visit_trend: list (月度趋势，格式：[{"month": "2026-01", "count": 3}, ...])
        - institution_types: dict (机构类型分布，格式：{"基金": 10, "保险": 5, ...})
        - focus_topics: list (关注焦点列表)
        - management_response: str (管理层回应态度)
        - latest_visit: dict (最近调研记录)
        - all_visits: list (所有调研记录)
        - error: str (错误信息)
    """
    log(f"分析机构调研记录: {stock_code} (最近{months}个月)", "INFO")
    
    # 获取调研数据
    result = get_institutional_visits(stock_code, months=months, limit=limit)
    
    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "获取数据失败"),
            "source": "iwencai",
        }
    
    visits = result.get("data", [])
    
    if not visits:
        return {
            "success": True,
            "visit_count": 0,
            "visit_trend": [],
            "institution_types": {},
            "focus_topics": [],
            "management_response": "无机构调研记录",
            "latest_visit": None,
            "all_visits": [],
            "source": "iwencai",
        }
    
    # 1. 统计调研次数
    visit_count = len(visits)
    
    # 2. 分析月度趋势
    visit_trend = analyze_visit_trend(visits)
    
    # 3. 分析机构类型分布
    institution_types = analyze_institution_types(visits)
    
    # 4. 提取关注焦点
    focus_topics = extract_focus_topics(visits)
    
    # 5. 分析管理层回应态度
    management_response = analyze_management_response(visits)
    
    # 6. 最近调研记录
    latest_visit = visits[0] if visits else None
    
    return {
        "success": True,
        "visit_count": visit_count,
        "visit_trend": visit_trend,
        "institution_types": institution_types,
        "focus_topics": focus_topics,
        "management_response": management_response,
        "latest_visit": latest_visit,
        "all_visits": visits,
        "source": "iwencai",
    }


def analyze_visit_trend(visits: List[Dict]) -> List[Dict]:
    """分析月度趋势"""
    # 按月份统计
    monthly_counts = {}
    
    for visit in visits:
        visit_date = visit.get("调研日期", "")
        if len(visit_date) >= 6:  # 至少YYYYMM
            month = f"{visit_date[:4]}-{visit_date[4:6]}"
            monthly_counts[month] = monthly_counts.get(month, 0) + 1
    
    # 转换为列表并排序
    trend = [
        {"month": month, "count": count}
        for month, count in sorted(monthly_counts.items(), reverse=True)
    ]
    
    return trend[:12]  # 最近12个月


def analyze_institution_types(visits: List[Dict]) -> Dict[str, int]:
    """分析机构类型分布"""
    type_counts = {inst_type: 0 for inst_type in INSTITUTION_TYPE_KEYWORDS.keys()}
    
    for visit in visits:
        # 从"机构家数字段"或"内容"中推断机构类型
        institution_count = visit.get("机构家数", 0)
        
        if institution_count and institution_count > 0:
            # 简单处理：假设所有机构都是混合类型
            # 更准确的分析需要解析"内容"字段
            content = visit.get("内容", "")
            
            for inst_type, keywords in INSTITUTION_TYPE_KEYWORDS.items():
                if inst_type == "其他":
                    continue
                for keyword in keywords:
                    if keyword in content:
                        type_counts[inst_type] += 1
                        break
    
    # 过滤掉0
    return {k: v for k, v in type_counts.items() if v > 0}


def extract_focus_topics(visits: List[Dict]) -> List[str]:
    """提取关注焦点（从内容中提取关键词）"""
    topics = set()
    
    # 常见关注焦点关键词
    topic_keywords = [
        "业绩", "营收", "净利润", "毛利率", "成本", "价格",
        "产能", "产量", "销量", "市场份额", "竞争",
        "研发", "技术", "专利", "创新",
        "芯片", "处理器", "主控", "驱动",
        "供应链", "原材料", "供应商", "库存",
        "海外", "出口", "国际", "北美", "欧洲",
        "股权", "控制权", "质押", "减持",
        "定增", "增发", "配股", "融资",
        "重组", "并购", "收购",
    ]
    
    for visit in visits:
        content = visit.get("内容", "")
        
        if not content:
            continue
        
        # 简单关键词匹配
        for keyword in topic_keywords:
            if keyword in content:
                topics.add(keyword)
    
    return list(topics)[:10]  # 最多10个


def analyze_management_response(visits: List[Dict]) -> str:
    """分析管理层回应态度"""
    if not visits:
        return "无记录"
    
    # 分析最近几次调研的内容
    positive_keywords = ["积极", "详细", "充分", "有信心", "增长", "突破", "领先"]
    negative_keywords = ["不确定", "无法", "困难", "挑战", "下滑", "下降"]
    neutral_keywords = ["正常", "稳定", "符合", "预期"]
    
    response_count = {"积极": 0, "中性": 0, "谨慎": 0}
    
    for visit in visits[:5]:  # 最近5次
        content = visit.get("内���", "")
        
        if not content:
            continue
        
        has_positive = any(kw in content for kw in positive_keywords)
        has_negative = any(kw in content for kw in negative_keywords)
        
        if has_positive and not has_negative:
            response_count["积极"] += 1
        elif has_negative and not has_positive:
            response_count["谨慎"] += 1
        else:
            response_count["中性"] += 1
    
    # 判断总体态度
    if response_count["积极"] >= 2:
        return "积极正面"
    elif response_count["谨慎"] >= 2:
        return "谨慎保守"
    else:
        return "中性务实"


def generate_report(data: Dict[str, Any]) -> str:
    """生成机构调研分析报告"""
    if not data.get("success"):
        return f"## 机构调研分析\n\n❌ 分析失败: {data.get('error', '未知错误')}\n"
    
    visit_count = data.get("visit_count", 0)
    
    if visit_count == 0:
        return "## 机构调研分析\n\n近12个月无机构调研记录\n"
    
    md = "## 机构调研分析\n\n"
    
    # 1. 调研频次
    md += f"**调研频次**: 近12个月共 {visit_count} 次机构调研\n\n"
    
    # 2. 月度趋势
    trend = data.get("visit_trend", [])
    if trend:
        md += "**月度趋势**:\n"
        for item in trend[:6]:  # 最近6个月
            md += f"- {item['month']}: {item['count']} 次\n"
        md += "\n"
    
    # 3. 机构类型
    inst_types = data.get("institution_types", {})
    if inst_types:
        md += "**机构类型分布**:\n"
        for inst_type, count in sorted(inst_types.items(), key=lambda x: x[1], reverse=True):
            md += f"- {inst_type}: {count} 家\n"
        md += "\n"
    
    # 4. 关注焦点
    topics = data.get("focus_topics", [])
    if topics:
        md += f"**关注焦点**: {', '.join(topics)}\n\n"
    
    # 5. 管理层回应
    response = data.get("management_response", "无记录")
    md += f"**管理层回应**: {response}\n\n"
    
    # 6. 最近调研
    latest = data.get("latest_visit", {})
    if latest:
        md += "**最近调研**:\n"
        md += f"- 日期: {latest.get('调研日期', 'N/A')}\n"
        md += f"- 方式: {latest.get('方式', 'N/A')}\n"
        md += f"- 机构家数: {latest.get('机构家数', 'N/A')}\n"
        md += f"- 接待人员: {latest.get('接待人员', 'N/A')}\n"
        
        # 内容摘要（截取前200字）
        content = latest.get("内容", "")
        summary = content[:200] + "..." if len(content) > 200 else content
        md += f"\n**内容摘要**: {summary}\n"
    
    return md


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python institutional_visit.py <股票代码> [months]")
        sys.exit(1)
    
    stock_code = sys.argv[1]
    months = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    
    print("=" * 60)
    print(f"机构调研分析: {stock_code} (最近{months}个月)")
    print("=" * 60)
    
    result = analyze_institutional_visits(stock_code, months=months)
    
    if result["success"]:
        print(f"\n✅ 分析成功!")
        print(f"   调研次数: {result['visit_count']}")
        print(f"   机构类型: {result['institution_types']}")
        print(f"   关注焦点: {result['focus_topics']}")
        print(f"   管理层回应: {result['management_response']}")
        
        if result.get("latest_visit"):
            latest = result["latest_visit"]
            print(f"\n   最近调研:")
            print(f"   - 日期: {latest.get('调研日期')}")
            print(f"   - 机构家数: {latest.get('机构家数')}")
    else:
        print(f"\n❌ 分析失败: {result.get('error')}")


def generate_report_section(data: dict) -> list:
    if not data:
        return []
    md = generate_report(data)
    return ["\n" + md]