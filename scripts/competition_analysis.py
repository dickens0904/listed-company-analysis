# -*- coding: utf-8 -*-
"""
竞争格局分析模块
分析竞争对手、市场份额、差异化优势
"""
import json

# 竞争优势类型
COMPETITIVE_ADVANTAGE_TYPES = {
    "cost_leadership": {
        "name": "成本领先",
        "description": "通过规模经济、效率提升等方式实现成本优势",
        "indicators": ["毛利率", "成本结构", "产能利用率"]
    },
    "differentiation": {
        "name": "差异化",
        "description": "通过产品特性、品牌、服务等形成独特价值",
        "indicators": ["品牌价值", "研发投入", "客户忠诚度"]
    },
    "focus": {
        "name": "聚焦战略",
        "description": "专注于特定细分市场或客户群体",
        "indicators": ["市场定位", "客户集中度", "细分市场份额"]
    },
    "innovation": {
        "name": "创新领先",
        "description": "通过技术创新保持竞争优势",
        "indicators": ["专利数量", "研发投入", "新产品推出频率"]
    }
}

# 市场份额等级
MARKET_SHARE_LEVELS = {
    "dominant": {
        "range": ">30%",
        "description": "市场主导者，具有定价权"
    },
    "leading": {
        "range": "10-30%",
        "description": "市场领先者，具有较强话语权"
    },
    "challenger": {
        "range": "5-10%",
        "description": "市场挑战者，有增长潜力"
    },
    "niche": {
        "range": "<5%",
        "description": "细分市场参与者"
    }
}

def analyze_competition(company_name, industry_name, financial_data=None, market="a"):
    """
    分析竞争格局
    
    Args:
        company_name: 公司名称
        industry_name: 行业名称
        financial_data: 财务数据
        market: 市场类型
    
    Returns:
        dict: 竞争格局分析结果
    """
    result = {
        "company_name": company_name,
        "industry_name": industry_name,
        "market_position": "unknown",
        "market_share": None,
        "competitors": [],
        "competitive_advantages": [],
        "competitive_disadvantages": [],
        "swot_analysis": {
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": []
        },
        "market_concentration": "unknown",
        "entry_barriers": [],
        "key_success_factors": []
    }
    
    # 1. 识别竞争对手
    result["competitors"] = identify_competitors(industry_name, market)
    
    # 2. 判断市场地位
    result["market_position"], result["market_share"] = determine_market_position(company_name, industry_name)
    
    # 3. 分析竞争优势
    result["competitive_advantages"] = analyze_advantages(company_name, industry_name, financial_data)
    
    # 4. 分析竞争劣势
    result["competitive_disadvantages"] = analyze_disadvantages(company_name, industry_name, financial_data)
    
    # 5. SWOT分析
    result["swot_analysis"] = generate_swot(result)
    
    # 6. 市场集中度分析
    result["market_concentration"] = analyze_market_concentration(industry_name)
    
    # 7. 进入壁垒
    result["entry_barriers"] = identify_entry_barriers(industry_name)
    
    # 8. 关键成功因素
    result["key_success_factors"] = identify_key_success_factors(industry_name)
    
    return result


def identify_competitors(industry_name, market="a"):
    """识别竞争对手"""
    competitors = {
        "半导体": {
            "a": [
                {"name": "中芯国际", "position": "领先", "focus": "晶圆制造"},
                {"name": "韦尔股份", "position": "领先", "focus": "半导体设计"},
                {"name": "闻泰科技", "position": "领先", "focus": "半导体封装"},
                {"name": "兆易创新", "position": "挑战者", "focus": "存储芯片"},
                {"name": "北方华创", "position": "领先", "focus": "半导体设备"}
            ],
            "hk": [
                {"name": "中芯国际", "position": "领先", "focus": "晶圆制造"},
                {"name": "华虹半导体", "position": "挑战者", "focus": "晶圆制造"}
            ],
            "us": [
                {"name": "NVIDIA", "position": "主导", "focus": "GPU"},
                {"name": "Intel", "position": "领先", "focus": "CPU"},
                {"name": "AMD", "position": "挑战者", "focus": "CPU/GPU"},
                {"name": "Qualcomm", "position": "领先", "focus": "基带芯片"}
            ]
        },
        "人工智能": {
            "a": [
                {"name": "科大讯飞", "position": "领先", "focus": "语音AI"},
                {"name": "浪潮信息", "position": "领先", "focus": "AI服务器"},
                {"name": "中科曙光", "position": "挑战者", "focus": "AI服务器"},
                {"name": "寒武纪", "position": "挑战者", "focus": "AI芯片"},
                {"name": "三六零", "position": "挑战者", "focus": "AI安全"}
            ],
            "hk": [
                {"name": "百度集团", "position": "领先", "focus": "大模型"},
                {"name": "阿里巴巴", "position": "领先", "focus": "AI+电商"},
                {"name": "腾讯控股", "position": "领先", "focus": "AI+社交"}
            ],
            "us": [
                {"name": "NVIDIA", "position": "主导", "focus": "AI芯片"},
                {"name": "Google", "position": "领先", "focus": "大模型"},
                {"name": "Microsoft", "position": "领先", "focus": "AI+办公"},
                {"name": "Meta", "position": "挑战者", "focus": "AI+社交"}
            ]
        },
        "新能源汽车": {
            "a": [
                {"name": "比亚迪", "position": "主导", "focus": "全产业链"},
                {"name": "宁德时代", "position": "主导", "focus": "动力电池"},
                {"name": "长城汽车", "position": "领先", "focus": "SUV"},
                {"name": "长安汽车", "position": "挑战者", "focus": "智能汽车"},
                {"name": "亿纬锂能", "position": "挑战者", "focus": "动力电池"}
            ],
            "hk": [
                {"name": "比亚迪股份", "position": "主导", "focus": "全产业链"},
                {"name": "蔚来-SW", "position": "挑战者", "focus": "高端智能"},
                {"name": "小鹏-W", "position": "挑战者", "focus": "智能驾驶"},
                {"name": "理想-W", "position": "挑战者", "focus": "增程式"}
            ],
            "us": [
                {"name": "Tesla", "position": "主导", "focus": "智能电动车"},
                {"name": "BYD", "position": "挑战者", "focus": "全产业链"},
                {"name": "NIO", "position": "挑战者", "focus": "高端智能"},
                {"name": "LI", "position": "挑战者", "focus": "增程式"}
            ]
        },
        "光伏": {
            "a": [
                {"name": "隆基绿能", "position": "领先", "focus": "硅片"},
                {"name": "通威股份", "position": "主导", "focus": "电池片"},
                {"name": "晶科能源", "position": "领先", "focus": "组件"},
                {"name": "中环股份", "position": "领先", "focus": "硅片"},
                {"name": "阳光电源", "position": "领先", "focus": "逆变器"}
            ]
        },
        "生物医药": {
            "a": [
                {"name": "恒瑞医药", "position": "领先", "focus": "创新药"},
                {"name": "药明康德", "position": "主导", "focus": "CXO"},
                {"name": "迈瑞医疗", "position": "领先", "focus": "医疗器械"},
                {"name": "智飞生物", "position": "领先", "focus": "疫苗"},
                {"name": "片仔癀", "position": "领先", "focus": "中药"}
            ]
        },
        "白酒": {
            "a": [
                {"name": "贵州茅台", "position": "主导", "focus": "高端白酒"},
                {"name": "五粮液", "position": "领先", "focus": "高端白酒"},
                {"name": "泸州老窖", "position": "领先", "focus": "高端白酒"},
                {"name": "洋河股份", "position": "领先", "focus": "中高端"},
                {"name": "山西汾酒", "position": "挑战者", "focus": "清香型"}
            ]
        }
    }
    
    industry_lower = industry_name.lower()
    
    for key, market_competitors in competitors.items():
        if key.lower() in industry_lower:
            return market_competitors.get(market, [])
    
    return []


def determine_market_position(company_name, industry_name):
    """判断市场地位"""
    # 简化的市场地位判断
    dominant_companies = ["贵州茅台", "宁德时代", "比亚迪", "药明康德", 
                         "NVIDIA", "Tesla", "中芯国际", "百度集团"]
    
    leading_companies = ["五粮液", "泸州老窖", "洋河股份", "恒瑞医药", 
                        "迈瑞医疗", "隆基绿能", "通威股份", "科大讯飞",
                        "浪潮信息", "腾讯控股", "阿里巴巴", "Google", "Microsoft"]
    
    if company_name in dominant_companies:
        return "主导者", ">30%"
    elif company_name in leading_companies:
        return "领先者", "10-30%"
    else:
        return "挑战者", "5-10%"


def analyze_advantages(company_name, industry_name, financial_data):
    """分析竞争优势"""
    advantages = []
    
    # 根据行业特点推断优势
    industry_advantages = {
        "半导体": ["技术研发", "产能规模", "客户关系", "产业链整合"],
        "人工智能": ["技术领先", "数据资源", "算力优势", "生态布局"],
        "新能源汽车": ["品牌力", "技术储备", "渠道网络", "成本控制"],
        "光伏": ["成本优势", "技术路线", "产能规模", "客户资源"],
        "生物医药": ["研发管线", "销售能力", "产能布局", "品牌影响力"],
        "白酒": ["品牌价值", "渠道网络", "产能储备", "定价权"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, adv_list in industry_advantages.items():
        if key.lower() in industry_lower:
            advantages.extend(adv_list)
            break
    
    # 从财务数据推断优势
    if financial_data:
        if isinstance(financial_data, dict):
            # 毛利率高可能代表定价权或成本优势
            if "gross_margin" in financial_data and financial_data["gross_margin"] > 30:
                advantages.append("毛利率优势")
            
            # 研发投入高可能代表创新能力
            if "rd_ratio" in financial_data and financial_data["rd_ratio"] > 5:
                advantages.append("研发投入领先")
    
    return list(set(advantages))


def analyze_disadvantages(company_name, industry_name, financial_data):
    """分析竞争劣势"""
    disadvantages = []
    
    industry_disadvantages = {
        "半导体": ["技术差距", "产能不足", "人才短缺", "资金压力"],
        "人工智能": ["盈利挑战", "监管风险", "技术迭代快"],
        "新能源汽车": ["价格战压力", "电池供应", "智能化短板"],
        "光伏": ["产能过剩", "价格下跌", "贸易摩擦"],
        "生物医药": ["集采压力", "研发风险", "国际化难度"],
        "白酒": ["消费复苏不确定", "库存压力"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, disadv_list in industry_disadvantages.items():
        if key.lower() in industry_lower:
            disadvantages.extend(disadv_list)
            break
    
    return disadvantages


def generate_swot(result):
    """生成SWOT分析"""
    swot = {
        "strengths": result["competitive_advantages"],
        "weaknesses": result["competitive_disadvantages"],
        "opportunities": [],
        "threats": []
    }
    
    # 根据行业添加机会和威胁
    industry_swot = {
        "半导体": {
            "opportunities": ["国产替代", "AI芯片需求", "先进封装"],
            "threats": ["技术封锁", "产能过剩", "地缘政治"]
        },
        "人工智能": {
            "opportunities": ["大模型应用", "行业渗透", "AI Agent"],
            "threats": ["监管政策", "技术竞争", "盈利模式"]
        },
        "新能源汽车": {
            "opportunities": ["渗透率提升", "智能化", "出海"],
            "threats": ["价格战", "补贴退坡", "电池成本"]
        },
        "光伏": {
            "opportunities": ["碳中和", "储能配套", "技术进步"],
            "threats": ["产能过剩", "价格下跌", "贸易保护"]
        },
        "生物医药": {
            "opportunities": ["创新药出海", "老龄化", "消费升级"],
            "threats": ["集采政策", "研发失败", "竞争加剧"]
        },
        "白酒": {
            "opportunities": ["消费升级", "高端化", "国际化"],
            "threats": ["消费疲软", "政策调控", "替代品"]
        }
    }
    
    industry_name = result["industry_name"].lower()
    for key, data in industry_swot.items():
        if key in industry_name:
            swot["opportunities"] = data["opportunities"]
            swot["threats"] = data["threats"]
            break
    
    return swot


def analyze_market_concentration(industry_name):
    """分析市场集中度"""
    concentration = {
        "半导体": "高集中",
        "人工智能": "中高集中",
        "新能源汽车": "中集中",
        "光伏": "中集中",
        "生物医药": "分散",
        "白酒": "中高集中"
    }
    
    industry_lower = industry_name.lower()
    
    for key, level in concentration.items():
        if key.lower() in industry_lower:
            return level
    
    return "中等"


def identify_entry_barriers(industry_name):
    """识别进入壁垒"""
    barriers = {
        "半导体": ["技术壁垒", "资金壁垒", "人才壁垒", "客户壁垒"],
        "人工智能": ["技术壁垒", "数据壁垒", "算力壁垒", "人才壁垒"],
        "新能源汽车": ["资金壁垒", "技术壁垒", "品牌壁垒", "渠道壁垒"],
        "光伏": ["资金壁垒", "规模壁垒", "技术壁垒"],
        "生物医药": ["研发壁垒", "审批壁垒", "资金壁垒", "人才壁垒"],
        "白酒": ["品牌壁垒", "渠道壁垒", "产能壁垒", "地域壁垒"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, barrier_list in barriers.items():
        if key.lower() in industry_lower:
            return barrier_list
    
    return ["资金壁垒", "技术壁垒"]


def identify_key_success_factors(industry_name):
    """识别关键成功因素"""
    factors = {
        "半导体": ["技术领先", "产能规模", "客户粘性", "产业链整合"],
        "人工智能": ["技术创新", "数据积累", "算力资源", "场景落地"],
        "新能源汽车": ["产品力", "品牌力", "成本控制", "智能化"],
        "光伏": ["成本优势", "技术路线", "客户关系", "产能规模"],
        "生物医药": ["研发管线", "商业化能力", "质量合规", "国际化"],
        "白酒": ["品牌价值", "渠道网络", "品质控制", "营销能力"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, factor_list in factors.items():
        if key.lower() in industry_lower:
            return factor_list
    
    return ["技术创新", "客户服务", "成本控制"]


def format_competition_report(result):
    """格式化竞争格局分析报告"""
    report = []
    
    report.append("## 竞争格局分析")
    report.append("")
    report.append(f"### 公司: **{result['company_name']}**")
    report.append(f"### 行业: **{result['industry_name']}**")
    report.append("")
    
    # 市场地位
    report.append(f"### 市场地位: **{result['market_position']}**")
    if result["market_share"]:
        report.append(f"- 预估市场份额: {result['market_share']}")
    report.append("")
    
    # 竞争对手
    if result["competitors"]:
        report.append("### 主要竞争对手")
        report.append("")
        for competitor in result["competitors"]:
            report.append(f"- **{competitor['name']}**: {competitor['position']}，专注于{competitor['focus']}")
        report.append("")
    
    # 竞争优势
    if result["competitive_advantages"]:
        report.append("### 竞争优势")
        report.append("")
        for advantage in result["competitive_advantages"]:
            report.append(f"- {advantage}")
        report.append("")
    
    # 竞争劣势
    if result["competitive_disadvantages"]:
        report.append("### 竞争劣势")
        report.append("")
        for disadvantage in result["competitive_disadvantages"]:
            report.append(f"- {disadvantage}")
        report.append("")
    
    # SWOT分析
    swot = result["swot_analysis"]
    report.append("### SWOT分析")
    report.append("")
    
    if swot["strengths"]:
        report.append("**优势 (Strengths):**")
        for item in swot["strengths"]:
            report.append(f"- {item}")
        report.append("")
    
    if swot["weaknesses"]:
        report.append("**劣势 (Weaknesses):**")
        for item in swot["weaknesses"]:
            report.append(f"- {item}")
        report.append("")
    
    if swot["opportunities"]:
        report.append("**机会 (Opportunities):**")
        for item in swot["opportunities"]:
            report.append(f"- {item}")
        report.append("")
    
    if swot["threats"]:
        report.append("**威胁 (Threats):**")
        for item in swot["threats"]:
            report.append(f"- {item}")
        report.append("")
    
    # 市场集中度
    report.append(f"### 市场集中度: **{result['market_concentration']}**")
    report.append("")
    
    # 进入壁垒
    if result["entry_barriers"]:
        report.append("### 进入壁垒")
        report.append("")
        report.append(", ".join(result["entry_barriers"]))
        report.append("")
    
    # 关键成功因素
    if result["key_success_factors"]:
        report.append("### 关键成功因素")
        report.append("")
        for factor in result["key_success_factors"]:
            report.append(f"- {factor}")
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    result = analyze_competition("纳思达", "半导体", {"gross_margin": 25, "rd_ratio": 8})
    print(format_competition_report(result))
