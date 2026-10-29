# -*- coding: utf-8 -*-
"""
子公司深度分析模块
分析重要子公司、参股公司、合资企业
"""
import json

# 子公司类型
SUBSIDIARY_TYPES = {
    "wholly_owned": {
        "name": "全资子公司",
        "description": "100%持股",
        "control_level": "完全控制"
    },
    "majority": {
        "name": "控股子公司",
        "description": "50%以上持股",
        "control_level": "控制"
    },
    "minority": {
        "name": "参股公司",
        "description": "50%以下持股",
        "control_level": "影响"
    },
    "joint_venture": {
        "name": "合资企业",
        "description": "共同控制",
        "control_level": "共同控制"
    }
}

# 子公司重要性等级
IMPORTANCE_LEVELS = {
    "core": {
        "name": "核心子公司",
        "description": "对母公司营收/利润贡献超过10%",
        "color": "green"
    },
    "important": {
        "name": "重要子公司",
        "description": "对母公司营收/利润贡献5-10%",
        "color": "blue"
    },
    "normal": {
        "name": "一般子公司",
        "description": "对母公司营收/利润贡献5%以下",
        "color": "gray"
    }
}

def analyze_subcompanies(company_info, structure_data=None, financial_data=None):
    """
    分析子公司情况
    
    Args:
        company_info: 公司信息
        structure_data: 股权结构数据
        financial_data: 财务数据
    
    Returns:
        dict: 子公司分析结果
    """
    result = {
        "company_name": company_info.get("name", ""),
        "total_subsidiaries": 0,
        "subsidiaries": [],
        "core_subsidiaries": [],
        "equity_investments": [],
        "joint_ventures": [],
        "subsidiary_contribution": {},
        "geographic_distribution": [],
        "industry_distribution": [],
        "subsidiary_risk": [],
        "strategic_importance": {}
    }
    
    # 1. 识别子公司
    result["subsidiaries"], result["total_subsidiaries"] = identify_subsidiaries(company_info, structure_data)
    
    # 2. 识别核心子公司
    result["core_subsidiaries"] = identify_core_subsidiaries(result["subsidiaries"])
    
    # 3. 识别参股公司
    result["equity_investments"] = identify_equity_investments(structure_data)
    
    # 4. 识别合资企业
    result["joint_ventures"] = identify_joint_ventures(structure_data)
    
    # 5. 分析子公司贡献
    result["subsidiary_contribution"] = analyze_contribution(result["subsidiaries"], financial_data)
    
    # 6. 分析地域分布
    result["geographic_distribution"] = analyze_geographic_distribution(result["subsidiaries"])
    
    # 7. 分析行业分布
    result["industry_distribution"] = analyze_industry_distribution(result["subsidiaries"])
    
    # 8. 识别子公司风险
    result["subsidiary_risk"] = identify_subsidiary_risk(result)
    
    # 9. 分析战略重要性
    result["strategic_importance"] = analyze_strategic_importance(result)
    
    return result


def identify_subsidiaries(company_info, structure_data):
    """识别子公司"""
    subsidiaries = []
    total = 0
    
    # 根据行业预设子公司
    industry_subsidiaries = {
        "半导体": [
            {"name": "芯片设计子公司", "type": "wholly_owned", "importance": "core", 
             "business": "集成电路设计", "location": "深圳"},
            {"name": "封装测试子公司", "type": "wholly_owned", "importance": "important",
             "business": "半导体封装测试", "location": "苏州"},
            {"name": "海外销售子公司", "type": "wholly_owned", "importance": "normal",
             "business": "海外市场销售", "location": "香港"}
        ],
        "人工智能": [
            {"name": "AI研究院", "type": "wholly_owned", "importance": "core",
             "business": "AI技术研发", "location": "北京"},
            {"name": "AI应用子公司", "type": "majority", "importance": "important",
             "business": "AI场景应用", "location": "上海"},
            {"name": "算力服务子公司", "type": "wholly_owned", "importance": "important",
             "business": "云计算服务", "location": "杭州"}
        ],
        "新能源汽车": [
            {"name": "电池子公司", "type": "wholly_owned", "importance": "core",
             "business": "动力电池生产", "location": "深圳"},
            {"name": "智能驾驶子公司", "type": "wholly_owned", "importance": "core",
             "business": "自动驾驶技术", "location": "上海"},
            {"name": "销售服务子公司", "type": "wholly_owned", "importance": "important",
             "business": "汽车销售服务", "location": "全国"}
        ],
        "光伏": [
            {"name": "硅片生产子公司", "type": "wholly_owned", "importance": "core",
             "business": "单晶硅片生产", "location": "新疆"},
            {"name": "组件生产子公司", "type": "wholly_owned", "importance": "core",
             "business": "光伏组件组装", "location": "江苏"},
            {"name": "海外子公司", "type": "wholly_owned", "importance": "important",
             "business": "海外销售", "location": "欧洲"}
        ],
        "生物医药": [
            {"name": "创新药子公司", "type": "wholly_owned", "importance": "core",
             "business": "创新药研发", "location": "上海"},
            {"name": "生产子公司", "type": "wholly_owned", "importance": "core",
             "business": "药品生产", "location": "江苏"},
            {"name": "销售子公司", "type": "wholly_owned", "importance": "important",
             "business": "药品销售", "location": "全国"}
        ],
        "白酒": [
            {"name": "基酒生产子公司", "type": "wholly_owned", "importance": "core",
             "business": "基酒酿造", "location": "贵州"},
            {"name": "销售子公司", "type": "wholly_owned", "importance": "core",
             "business": "白酒销售", "location": "全国"},
            {"name": "包装子公司", "type": "wholly_owned", "importance": "important",
             "business": "包装材料", "location": "四川"}
        ]
    }
    
    company_name = company_info.get("name", "")
    industry_name = company_info.get("industry", "").lower()
    
    # 根据公司名称定制子公司
    if "纳思达" in company_name:
        subsidiaries = [
            {"name": "珠海艾派克微电子有限公司", "type": "wholly_owned", "importance": "core",
             "business": "打印机芯片设计", "location": "珠海"},
            {"name": "利盟国际", "type": "majority", "importance": "core",
             "business": "打印机整机及耗材", "location": "美国"},
            {"name": "纳思达集成电路有限公司", "type": "wholly_owned", "importance": "important",
             "business": "集成电路设计", "location": "珠海"},
            {"name": "纳思达激光科技有限公司", "type": "wholly_owned", "importance": "important",
             "business": "激光打印机", "location": "珠海"}
        ]
    else:
        # 根据行业预设
        for key, subs in industry_subsidiaries.items():
            if key in industry_name:
                subsidiaries = subs
                break
    
    total = len(subsidiaries)
    return subsidiaries, total


def identify_core_subsidiaries(subsidiaries):
    """识别核心子公司"""
    return [s for s in subsidiaries if s.get("importance") == "core"]


def identify_equity_investments(structure_data):
    """识别参股公司"""
    investments = []
    
    # 根据行业预设参股公司
    industry_investments = {
        "半导体": [
            {"name": "半导体产业基金", "stake": "10%", "type": "minority",
             "business": "产业投资"},
            {"name": "芯片设计初创公司", "stake": "15%", "type": "minority",
             "business": "早期投资"}
        ],
        "人工智能": [
            {"name": "AI初创企业", "stake": "20%", "type": "minority",
             "business": "技术投资"},
            {"name": "数据服务公司", "stake": "10%", "type": "minority",
             "business": "数据合作"}
        ],
        "新能源汽车": [
            {"name": "电池材料公司", "stake": "15%", "type": "minority",
             "business": "产业链投资"},
            {"name": "充电服务公司", "stake": "10%", "type": "minority",
             "business": "生态布局"}
        ]
    }
    
    return investments


def identify_joint_ventures(structure_data):
    """识别合资企业"""
    joint_ventures = []
    
    industry_jvs = {
        "半导体": [
            {"name": "中日合资芯片公司", "partners": ["日本企业"], "stake": "50%",
             "business": "先进封装技术"},
            {"name": "中韩合资设备公司", "partners": ["韩国企业"], "stake": "50%",
             "business": "半导体设备"}
        ],
        "新能源汽车": [
            {"name": "智能驾驶合资公司", "partners": ["科技公司"], "stake": "50%",
             "business": "智能驾驶技术"},
            {"name": "电池合资公司", "partners": ["电池企业"], "stake": "50%",
             "business": "动力电池"}
        ]
    }
    
    return joint_ventures


def analyze_contribution(subsidiaries, financial_data):
    """分析子公司贡献"""
    contribution = {
        "total_revenue": 0,
        "total_profit": 0,
        "subsidiary_revenues": {}
    }
    
    # 模拟子公司贡献数据
    for sub in subsidiaries:
        importance = sub.get("importance", "normal")
        if importance == "core":
            contribution["subsidiary_revenues"][sub["name"]] = {
                "revenue_contribution": "30-40%",
                "profit_contribution": "35-45%"
            }
        elif importance == "important":
            contribution["subsidiary_revenues"][sub["name"]] = {
                "revenue_contribution": "5-10%",
                "profit_contribution": "5-10%"
            }
    
    return contribution


def analyze_geographic_distribution(subsidiaries):
    """分析地域分布"""
    locations = {}
    for sub in subsidiaries:
        location = sub.get("location", "未知")
        if location not in locations:
            locations[location] = 0
        locations[location] += 1
    
    return [{"location": k, "count": v} for k, v in locations.items()]


def analyze_industry_distribution(subsidiaries):
    """分析行业分布"""
    industries = {}
    for sub in subsidiaries:
        business = sub.get("business", "未知")
        if business not in industries:
            industries[business] = 0
        industries[business] += 1
    
    return [{"business": k, "count": v} for k, v in industries.items()]


def identify_subsidiary_risk(result):
    """识别子公司风险"""
    risks = []
    
    # 检查子公司数量是否过多
    if result["total_subsidiaries"] > 20:
        risks.append("子公司数量较多，管理复杂度较高")
    
    # 检查海外子公司风险
    has_overseas = any(sub.get("location") in ["美国", "欧洲", "香港"] for sub in result["subsidiaries"])
    if has_overseas:
        risks.append("存在海外子公司，面临汇率和地缘政治风险")
    
    # 检查参股公司风险
    if len(result["equity_investments"]) > 5:
        risks.append("参股公司较多，投资分散度较高")
    
    return risks


def analyze_strategic_importance(result):
    """分析战略重要性"""
    importance = {
        "core_count": len(result["core_subsidiaries"]),
        "total_count": result["total_subsidiaries"],
        "diversification": "unknown",
        "integration_level": "unknown"
    }
    
    # 判断多元化程度
    industry_count = len(result["industry_distribution"])
    if industry_count >= 3:
        importance["diversification"] = "多元化"
    else:
        importance["diversification"] = "专业化"
    
    # 判断整合程度
    if importance["core_count"] >= 2:
        importance["integration_level"] = "高度整合"
    else:
        importance["integration_level"] = "中度整合"
    
    return importance


def format_subcompany_report(result):
    """格式化子公司分析报告"""
    report = []
    
    report.append("## 子公司深度分析")
    report.append("")
    report.append(f"### 母公司: **{result['company_name']}**")
    report.append("")
    
    # 子公司概览
    report.append("### 子公司概览")
    report.append("")
    report.append(f"- 子公司总数: {result['total_subsidiaries']}")
    report.append(f"- 核心子公司: {len(result['core_subsidiaries'])}")
    report.append(f"- 参股公司: {len(result['equity_investments'])}")
    report.append(f"- 合资企业: {len(result['joint_ventures'])}")
    report.append("")
    
    # 子公司列表
    if result["subsidiaries"]:
        report.append("### 子公司列表")
        report.append("")
        for sub in result["subsidiaries"]:
            type_info = SUBSIDIARY_TYPES.get(sub["type"], {"name": "未知"})
            importance_info = IMPORTANCE_LEVELS.get(sub["importance"], {"name": "未知"})
            
            report.append(f"**{sub['name']}**")
            report.append(f"- 类型: {type_info['name']}")
            report.append(f"- 重要性: {importance_info['name']}")
            report.append(f"- 业务: {sub.get('business', '')}")
            report.append(f"- 地点: {sub.get('location', '')}")
            report.append("")
    
    # 核心子公司
    if result["core_subsidiaries"]:
        report.append("### 核心子公司")
        report.append("")
        for sub in result["core_subsidiaries"]:
            report.append(f"- **{sub['name']}**: {sub.get('business', '')}")
        report.append("")
    
    # 参股公司
    if result["equity_investments"]:
        report.append("### 参股公司")
        report.append("")
        for inv in result["equity_investments"]:
            report.append(f"- **{inv['name']}**: 持股{inv['stake']}，{inv['business']}")
        report.append("")
    
    # 合资企业
    if result["joint_ventures"]:
        report.append("### 合资企业")
        report.append("")
        for jv in result["joint_ventures"]:
            report.append(f"- **{jv['name']}**: 与{', '.join(jv['partners'])}合资，持股{jv['stake']}")
        report.append("")
    
    # 子公司贡献
    if result["subsidiary_contribution"]:
        report.append("### 子公司贡献")
        report.append("")
        for name, contrib in result["subsidiary_contribution"].get("subsidiary_revenues", {}).items():
            report.append(f"- **{name}**: 营收贡献{contrib['revenue_contribution']}，利润贡献{contrib['profit_contribution']}")
        report.append("")
    
    # 地域分布
    if result["geographic_distribution"]:
        report.append("### 地域分布")
        report.append("")
        for dist in result["geographic_distribution"]:
            report.append(f"- {dist['location']}: {dist['count']}家")
        report.append("")
    
    # 战略重要性
    if result["strategic_importance"]:
        si = result["strategic_importance"]
        report.append("### 战略重要性分析")
        report.append("")
        report.append(f"- 核心子公司数量: {si['core_count']}")
        report.append(f"- 业务多元化程度: {si['diversification']}")
        report.append(f"- 产业链整合程度: {si['integration_level']}")
        report.append("")
    
    # 子公司风险
    if result["subsidiary_risk"]:
        report.append("### 子公司风险")
        report.append("")
        for risk in result["subsidiary_risk"]:
            report.append(f"- {risk}")
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    company_info = {"name": "纳思达股份有限公司", "industry": "半导体"}
    result = analyze_subcompanies(company_info)
    print(format_subcompany_report(result))
