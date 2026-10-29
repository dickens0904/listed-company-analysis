# -*- coding: utf-8 -*-
"""
国家战略分析模块
分析公司业务与国家战略的契合度
"""
import json
import re

# 国家战略新兴产业分类（根据国家发改委定义）
STRATEGIC_INDUSTRIES = {
    "新一代信息技术": [
        "半导体", "集成电路", "芯片", "软件", "人工智能", "大数据", "云计算",
        "物联网", "5G", "通信", "量子计算", "区块链", "工业互联网"
    ],
    "高端装备制造": [
        "机器人", "数控机床", "航空航天", "轨道交通", "智能制造", "工业机器人",
        "自动化设备", "精密仪器", "传感器"
    ],
    "新能源": [
        "光伏", "太阳能", "风电", "水电", "核电", "新能源汽车", "电池",
        "储能", "充电桩", "氢能", "燃料电池"
    ],
    "新材料": [
        "稀土", "石墨烯", "锂电池材料", "半导体材料", "碳纤维", "复合材料",
        "高温合金", "超导材料", "纳米材料"
    ],
    "生物产业": [
        "生物医药", "医疗器械", "基因检测", "疫苗", "生物制药", "医疗设备",
        "体外诊断", "中药创新"
    ],
    "节能环保": [
        "环保设备", "污水处理", "固废处理", "大气治理", "节能设备", "绿色建筑",
        "碳减排", "CCUS", "碳中和"
    ],
    "数字创意": [
        "数字媒体", "游戏", "影视", "动漫", "虚拟现实", "增强现实", "元宇宙"
    ],
    "现代交通": [
        "新能源汽车", "智能汽车", "自动驾驶", "车联网", "轨道交通", "航空"
    ]
}

# 国家规划关键词
NATIONAL_PLAN_KEYWORDS = {
    "十四五规划": [
        "科技创新", "双循环", "高质量发展", "供给侧改革", "数字经济",
        "乡村振兴", "绿色发展", "共同富裕", "现代化经济体系"
    ],
    "中国制造2025": [
        "智能制造", "工业4.0", "两化融合", "高端装备", "质量强国",
        "绿色制造", "服务型制造", "人才为本"
    ],
    "双碳目标": [
        "碳达峰", "碳中和", "绿色低碳", "新能源", "节能减排", "可再生能源",
        "清洁能源", "低碳技术", "碳交易"
    ],
    "数字中国": [
        "数字经济", "数字政府", "数字社会", "数据要素", "智慧城市",
        "数字基础设施", "数据安全"
    ]
}

# 政策支持类型
POLICY_SUPPORT_TYPES = [
    "税收优惠", "研发费用加计扣除", "政府补贴", "产业基金",
    "政府采购", "土地优惠", "人才政策", "出口退税"
]

def analyze_national_strategy(company_info, industry_info, financial_data):
    """
    分析公司与国家战略的契合度
    
    Args:
        company_info: 公司基本信息
        industry_info: 行业信息
        financial_data: 财务数据（包含政府补助等）
    
    Returns:
        dict: 国家战略分析结果
    """
    result = {
        "strategic_fit_score": 0,
        "strategic_industries": [],
        "policy_alignments": [],
        "policy_support_indicators": [],
        "government_subsidy_analysis": {},
        "suggestions": []
    }
    
    # 1. 识别所属战略产业
    industry_text = f"{industry_info.get('industry', '')} {company_info.get('business_scope', '')}"
    for industry_name, keywords in STRATEGIC_INDUSTRIES.items():
        for keyword in keywords:
            if keyword in industry_text or keyword in company_info.get('name', ''):
                result["strategic_industries"].append({
                    "industry": industry_name,
                    "matched_keywords": keyword
                })
                break
    
    # 2. 分析政策契合度
    business_desc = f"{company_info.get('business_scope', '')} {industry_info.get('description', '')}"
    for plan_name, keywords in NATIONAL_PLAN_KEYWORDS.items():
        matched = []
        for keyword in keywords:
            if keyword in business_desc:
                matched.append(keyword)
        if matched:
            result["policy_alignments"].append({
                "plan": plan_name,
                "matched_keywords": matched,
                "relevance": len(matched) / len(keywords)
            })
    
    # 3. 分析政策支持指标
    # 检查财务数据中的政府补助
    if financial_data:
        subsidy_amount = 0
        subsidy_trend = "stable"
        
        # 查找政府补助相关数据
        if isinstance(financial_data, dict):
            # 从多种可能的字段中查找政府补助
            possible_fields = ["government_subsidy", "government_grant", "subsidy", "grant", "政府补助"]
            for field in possible_fields:
                if field in financial_data:
                    subsidy_amount = financial_data[field]
                    break
            
            # 分析补助趋势
            if "subsidy_history" in financial_data:
                history = financial_data["subsidy_history"]
                if len(history) >= 2:
                    recent = history[-1]
                    previous = history[-2]
                    if recent > previous * 1.5:
                        subsidy_trend = "increasing"
                    elif recent < previous * 0.5:
                        subsidy_trend = "decreasing"
        
        result["government_subsidy_analysis"] = {
            "amount": subsidy_amount,
            "trend": subsidy_trend,
            "significance": "high" if subsidy_amount > 0 else "none"
        }
        
        # 根据补助情况判断政策支持
        if subsidy_amount > 0:
            result["policy_support_indicators"].append("政府补助")
    
    # 4. 计算战略契合度分数
    base_score = len(result["strategic_industries"]) * 20
    policy_score = sum(p["relevance"] for p in result["policy_alignments"]) * 30
    support_score = len(result["policy_support_indicators"]) * 10
    
    result["strategic_fit_score"] = min(100, base_score + policy_score + support_score)
    
    # 5. 生成建议
    if result["strategic_fit_score"] >= 80:
        result["suggestions"].append("公司业务高度契合国家战略方向，政策支持力度大")
    elif result["strategic_fit_score"] >= 50:
        result["suggestions"].append("公司业务与国家战略有一定契合度，建议关注政策动态")
    else:
        result["suggestions"].append("公司业务与国家战略契合度较低，需关注政策风险")
    
    return result


def get_strategic_industry_details(industry_name):
    """获取战略产业详细信息"""
    industry_details = {
        "新一代信息技术": {
            "description": "以集成电路、人工智能、云计算、大数据等为代表的信息技术产业",
            "policy_support": "国家大力扶持，列入战略性新兴产业重点发展方向",
            "growth_driver": "数字化转型需求、技术创新突破"
        },
        "高端装备制造": {
            "description": "智能制造装备、航空航天装备、轨道交通装备等高端制造业",
            "policy_support": "中国制造2025核心领域，进口替代政策支持",
            "growth_driver": "产业升级需求、自主可控趋势"
        },
        "新能源": {
            "description": "太阳能、风能、新能源汽车等清洁能源产业",
            "policy_support": "双碳目标核心领域，高额补贴支持",
            "growth_driver": "碳中和政策、能源结构转型"
        },
        "新材料": {
            "description": "高性能复合材料、半导体材料、新能源材料等",
            "policy_support": "关键材料自主可控战略",
            "growth_driver": "高端制造需求、技术突破"
        },
        "生物产业": {
            "description": "生物医药、医疗器械、基因技术等",
            "policy_support": "健康中国战略重点领域",
            "growth_driver": "人口老龄化、健康意识提升"
        },
        "节能环保": {
            "description": "环保设备、节能技术、碳减排产业",
            "policy_support": "双碳目标驱动，环保法规趋严",
            "growth_driver": "环保政策、碳中和目标"
        },
        "数字创意": {
            "description": "数字媒体、游戏、虚拟现实等文化创意产业",
            "policy_support": "数字经济战略支持",
            "growth_driver": "消费升级、技术创新"
        },
        "现代交通": {
            "description": "新能源汽车、智能网联汽车、轨道交通",
            "policy_support": "新能源汽车补贴、智能交通政策",
            "growth_driver": "电动化趋势、智能化升级"
        }
    }
    
    return industry_details.get(industry_name, {})


def format_strategy_report(result):
    """格式化国家战略分析报告"""
    report = []
    
    report.append("## 国家战略契合度分析")
    report.append("")
    report.append(f"### 战略契合度评分: **{result['strategic_fit_score']}/100**")
    report.append("")
    
    # 战略产业匹配
    if result["strategic_industries"]:
        report.append("### 所属战略产业")
        report.append("")
        for industry in result["strategic_industries"]:
            details = get_strategic_industry_details(industry["industry"])
            report.append(f"- **{industry['industry']}**")
            report.append(f"  - 匹配关键词: {industry['matched_keywords']}")
            if details:
                report.append(f"  - 产业描述: {details.get('description', '')}")
                report.append(f"  - 政策支持: {details.get('policy_support', '')}")
        report.append("")
    
    # 政策契合度
    if result["policy_alignments"]:
        report.append("### 国家规划契合度")
        report.append("")
        for alignment in result["policy_alignments"]:
            relevance_pct = int(alignment["relevance"] * 100)
            report.append(f"- **{alignment['plan']}**: 契合度 {relevance_pct}%")
            report.append(f"  - 匹配关键词: {', '.join(alignment['matched_keywords'])}")
        report.append("")
    
    # 政策支持指标
    if result["policy_support_indicators"]:
        report.append("### 政策支持指标")
        report.append("")
        report.append(", ".join(result["policy_support_indicators"]))
        report.append("")
    
    # 政府补助分析
    if result["government_subsidy_analysis"]:
        subsidy = result["government_subsidy_analysis"]
        report.append("### 政府补助分析")
        report.append("")
        report.append(f"- 补助金额: {subsidy['amount']:,} 元" if subsidy['amount'] else "- 无公开数据")
        report.append(f"- 趋势: {subsidy['trend']}")
        report.append(f"- 重要性: {subsidy['significance']}")
        report.append("")
    
    # 建议
    if result["suggestions"]:
        report.append("### 分析建议")
        report.append("")
        for suggestion in result["suggestions"]:
            report.append(f"- {suggestion}")
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    test_company = {
        "name": "纳思达股份有限公司",
        "business_scope": "半导体芯片设计、打印机耗材、集成电路制造"
    }
    
    test_industry = {
        "industry": "半导体",
        "description": "专注于集成电路芯片设计与制造，属于新一代信息技术产业"
    }
    
    test_financial = {
        "government_subsidy": 50000000,
        "subsidy_history": [30000000, 40000000, 50000000]
    }
    
    result = analyze_national_strategy(test_company, test_industry, test_financial)
    print(format_strategy_report(result))
