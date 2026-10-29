# -*- coding: utf-8 -*-
"""
产能分析模块
分析产能利用率、扩产计划、产能分布
"""
import json

# 产能利用率等级
CAPACITY_UTILIZATION_LEVELS = {
    "high": {
        "range": ">80%",
        "description": "产能充分利用，市场需求旺盛",
        "implication": "可能存在产能瓶颈，有扩产需求"
    },
    "medium": {
        "range": "60-80%",
        "description": "产能利用合理，供需平衡",
        "implication": "运营效率良好"
    },
    "low": {
        "range": "<60%",
        "description": "产能利用率不足",
        "implication": "可能存在产能过剩或需求不足"
    }
}

# 产能扩张类型
EXPANSION_TYPES = {
    "organic": "内生增长",
    "acquisition": "并购扩张",
    "joint_venture": "合资合作",
    "greenfield": "新建产能"
}

def analyze_capacity(company_info, industry_info, financial_data=None, announcements=None):
    """
    分析产能情况
    
    Args:
        company_info: 公司信息
        industry_info: 行业信息
        financial_data: 财务数据
        announcements: 公告数据
    
    Returns:
        dict: 产能分析结果
    """
    result = {
        "company_name": company_info.get("name", ""),
        "industry_name": industry_info.get("industry", ""),
        "total_capacity": None,
        "capacity_utilization": "unknown",
        "capacity_utilization_level": "unknown",
        "capacity_distribution": [],
        "expansion_plans": [],
        "capacity_trend": "stable",
        "capex_analysis": {},
        "capacity_risk": [],
        "future_outlook": ""
    }
    
    # 1. 估算产能规模
    result["total_capacity"] = estimate_total_capacity(company_info, industry_info, financial_data)
    
    # 2. 分析产能利用率
    result["capacity_utilization"], result["capacity_utilization_level"] = analyze_utilization(company_info, financial_data)
    
    # 3. 分析产能分布
    result["capacity_distribution"] = analyze_distribution(company_info, industry_info)
    
    # 4. 分析扩产计划
    result["expansion_plans"] = analyze_expansion_plans(company_info, industry_info, announcements)
    
    # 5. 分析产能趋势
    result["capacity_trend"] = analyze_trend(financial_data)
    
    # 6. 分析资本支出
    result["capex_analysis"] = analyze_capex(financial_data)
    
    # 7. 分析产能风险
    result["capacity_risk"] = identify_capacity_risk(result)
    
    # 8. 生成未来展望
    result["future_outlook"] = generate_outlook(result)
    
    return result


def estimate_total_capacity(company_info, industry_info, financial_data):
    """估算产能规模"""
    industry_name = industry_info.get("industry", "").lower()
    
    # 不同行业的产能单位和估算方法
    capacity_estimates = {
        "半导体": {"unit": "万片/月", "estimate": "根据固定资产规模估算"},
        "新能源汽车": {"unit": "万辆/年", "estimate": "根据产量和产能利用率估算"},
        "光伏": {"unit": "GW", "estimate": "根据产量和产能利用率估算"},
        "生物医药": {"unit": "亿元产值", "estimate": "根据营收规模估算"},
        "白酒": {"unit": "万千升", "estimate": "根据基酒储备估算"},
        "消费电子": {"unit": "万台", "estimate": "根据出货量估算"}
    }
    
    for key, info in capacity_estimates.items():
        if key in industry_name:
            return f"约{get_default_capacity(key)} {info['unit']}"
    
    return "未明确"


def get_default_capacity(industry_key):
    """获取默认产能估算值"""
    defaults = {
        "半导体": "10-50",
        "新能源汽车": "50-200",
        "光伏": "10-50",
        "生物医药": "50-200",
        "白酒": "10-50",
        "消费电子": "1000-5000"
    }
    return defaults.get(industry_key, "10-100")


def analyze_utilization(company_info, financial_data):
    """分析产能利用率"""
    utilization = "unknown"
    level = "unknown"
    
    if financial_data and isinstance(financial_data, dict):
        # 从财务数据获取利用率
        if "capacity_utilization" in financial_data:
            utilization = financial_data["capacity_utilization"]
            
            if utilization > 80:
                level = "high"
            elif utilization >= 60:
                level = "medium"
            else:
                level = "low"
    
    # 如果没有数据，根据行业特点推断
    if utilization == "unknown":
        industry_trends = {
            "半导体": ("70-85%", "medium"),
            "新能源汽车": ("60-75%", "medium"),
            "光伏": ("50-70%", "medium"),
            "生物医药": ("70-80%", "medium"),
            "白酒": ("60-70%", "medium"),
            "消费电子": ("60-80%", "medium")
        }
        
        industry_name = company_info.get("industry", "").lower()
        for key, values in industry_trends.items():
            if key in industry_name:
                utilization, level = values
                break
    
    return utilization, level


def analyze_distribution(company_info, industry_info):
    """分析产能地域分布"""
    distribution = []
    
    industry_distributions = {
        "半导体": ["长三角", "珠三角", "京津冀", "成渝"],
        "新能源汽车": ["长三角", "珠三角", "中部地区"],
        "光伏": ["长三角", "西北", "西南"],
        "生物医药": ["长三角", "珠三角", "京津冀"],
        "白酒": ["贵州", "四川", "江苏"],
        "消费电子": ["珠三角", "长三角"]
    }
    
    industry_name = industry_info.get("industry", "").lower()
    
    for key, regions in industry_distributions.items():
        if key in industry_name:
            distribution = regions
            break
    
    return distribution


def analyze_expansion_plans(company_info, industry_info, announcements):
    """分析扩产计划"""
    plans = []
    
    industry_plans = {
        "半导体": [
            {"project": "先进制程扩产", "investment": "大", "timeline": "1-3年"},
            {"project": "封装测试产能", "investment": "中", "timeline": "1-2年"}
        ],
        "新能源汽车": [
            {"project": "新工厂建设", "investment": "大", "timeline": "1-2年"},
            {"project": "产能升级", "investment": "中", "timeline": "6-12月"}
        ],
        "光伏": [
            {"project": "N型产能扩张", "investment": "大", "timeline": "6-18月"},
            {"project": "组件产能", "investment": "中", "timeline": "6-12月"}
        ],
        "生物医药": [
            {"project": "产能扩建", "investment": "中", "timeline": "1-2年"},
            {"project": "CDMO产能", "investment": "大", "timeline": "1-3年"}
        ],
        "白酒": [
            {"project": "基酒产能", "investment": "大", "timeline": "3-5年"},
            {"project": "灌装产能", "investment": "中", "timeline": "1-2年"}
        ],
        "消费电子": [
            {"project": "新产线", "investment": "中", "timeline": "6-12月"},
            {"project": "自动化升级", "investment": "中", "timeline": "6-18月"}
        ]
    }
    
    industry_name = industry_info.get("industry", "").lower()
    
    for key, industry_plans_list in industry_plans.items():
        if key in industry_name:
            plans = industry_plans_list
            break
    
    # 从公告中提取扩产信息
    if announcements and isinstance(announcements, list):
        for ann in announcements:
            if "扩产" in ann.get("title", "") or "产能" in ann.get("title", ""):
                plans.append({
                    "project": ann.get("title", "未知项目"),
                    "investment": "待确认",
                    "timeline": ann.get("date", "未知")
                })
    
    return plans


def analyze_trend(financial_data):
    """分析产能趋势"""
    if financial_data and isinstance(financial_data, dict):
        if "capacity_history" in financial_data:
            history = financial_data["capacity_history"]
            if len(history) >= 2:
                recent = history[-1]
                previous = history[-2]
                if recent > previous * 1.1:
                    return "increasing"
                elif recent < previous * 0.9:
                    return "decreasing"
    
    return "stable"


def analyze_capex(financial_data):
    """分析资本支出"""
    capex = {
        "capex_amount": None,
        "capex_trend": "stable",
        "capex_intensity": "unknown"
    }
    
    if financial_data and isinstance(financial_data, dict):
        if "capex" in financial_data:
            capex["capex_amount"] = financial_data["capex"]
        
        if "capex_history" in financial_data:
            history = financial_data["capex_history"]
            if len(history) >= 2:
                recent = history[-1]
                previous = history[-2]
                if recent > previous * 1.2:
                    capex["capex_trend"] = "increasing"
                elif recent < previous * 0.8:
                    capex["capex_trend"] = "decreasing"
        
        # 计算资本支出强度
        if "revenue" in financial_data and capex["capex_amount"]:
            intensity = (capex["capex_amount"] / financial_data["revenue"]) * 100
            capex["capex_intensity"] = f"{intensity:.1f}%"
    
    return capex


def identify_capacity_risk(result):
    """识别产能风险"""
    risks = []
    
    # 根据产能利用率判断风险
    if result["capacity_utilization_level"] == "low":
        risks.append("产能利用率不足，可能存在产能过剩")
    
    if result["capacity_utilization_level"] == "high":
        risks.append("产能利用率过高，可能存在供应瓶颈")
    
    # 根据趋势判断风险
    if result["capacity_trend"] == "decreasing":
        risks.append("产能呈下降趋势，需关注原因")
    
    # 根据资本支出判断风险
    capex = result["capex_analysis"]
    if capex.get("capex_trend") == "increasing":
        risks.append("资本支出大幅增加，需关注投资回报")
    
    return risks


def generate_outlook(result):
    """生成未来展望"""
    utilization = result["capacity_utilization_level"]
    trend = result["capacity_trend"]
    has_plans = len(result["expansion_plans"]) > 0
    
    if utilization == "high" and trend == "increasing" and has_plans:
        return "产能利用率高，公司有明确扩产计划，未来产能将持续增长"
    elif utilization == "high" and not has_plans:
        return "产能利用率高，但暂无明确扩产计划，可能存在供应瓶颈"
    elif utilization == "low":
        return "产能利用率较低，需关注需求端变化或产能优化措施"
    else:
        return "产能状况稳定，运营效率良好"


def format_capacity_report(result):
    """格式化产能分析报告"""
    report = []
    
    report.append("## 产能分析")
    report.append("")
    report.append(f"### 公司: **{result['company_name']}**")
    report.append(f"### 行业: **{result['industry_name']}**")
    report.append("")
    
    # 产能规模
    report.append("### 产能规模")
    report.append("")
    report.append(f"- 总产能: {result['total_capacity']}")
    report.append("")
    
    # 产能利用率
    report.append("### 产能利用率")
    report.append("")
    report.append(f"- 利用率: {result['capacity_utilization']}")
    
    if result["capacity_utilization_level"] in CAPACITY_UTILIZATION_LEVELS:
        level_info = CAPACITY_UTILIZATION_LEVELS[result["capacity_utilization_level"]]
        report.append(f"- 等级: {level_info['range']}")
        report.append(f"- 描述: {level_info['description']}")
        report.append(f"- 含义: {level_info['implication']}")
    report.append("")
    
    # 产能分布
    if result["capacity_distribution"]:
        report.append("### 产能分布")
        report.append("")
        report.append(", ".join(result["capacity_distribution"]))
        report.append("")
    
    # 扩产计划
    if result["expansion_plans"]:
        report.append("### 扩产计划")
        report.append("")
        for plan in result["expansion_plans"]:
            report.append(f"- **{plan['project']}**")
            report.append(f"  - 投资规模: {plan['investment']}")
            report.append(f"  - 时间规划: {plan['timeline']}")
        report.append("")
    
    # 产能趋势
    report.append(f"### 产能趋势: **{result['capacity_trend']}**")
    report.append("")
    
    # 资本支出分析
    if result["capex_analysis"]:
        capex = result["capex_analysis"]
        report.append("### 资本支出分析")
        report.append("")
        if capex["capex_amount"]:
            report.append(f"- 资本支出金额: {capex['capex_amount']:,} 元")
        report.append(f"- 支出趋势: {capex['capex_trend']}")
        if capex["capex_intensity"] != "unknown":
            report.append(f"- 资本支出强度: {capex['capex_intensity']}")
        report.append("")
    
    # 产能风险
    if result["capacity_risk"]:
        report.append("### 产能风险")
        report.append("")
        for risk in result["capacity_risk"]:
            report.append(f"- {risk}")
        report.append("")
    
    # 未来展望
    report.append("### 未来展望")
    report.append("")
    report.append(result["future_outlook"])
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    company_info = {"name": "纳思达股份有限公司"}
    industry_info = {"industry": "半导体"}
    result = analyze_capacity(company_info, industry_info)
    print(format_capacity_report(result))
