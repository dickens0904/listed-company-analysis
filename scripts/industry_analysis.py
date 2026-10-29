# -*- coding: utf-8 -*-
"""
行业分析模块
分析行业发展趋势、政策影响、技术变革
"""
import json
import requests

# 行业发展阶段定义
INDUSTRY_STAGES = {
    "萌芽期": {
        "characteristics": ["技术不成熟", "市场规模小", "商业模式待验证", "风险高"],
        "investment_rating": "高风险"
    },
    "成长期": {
        "characteristics": ["技术快速进步", "市场规模扩大", "竞争格局形成", "增长快"],
        "investment_rating": "机遇期"
    },
    "成熟期": {
        "characteristics": ["技术成熟", "市场饱和", "竞争激烈", "增长稳定"],
        "investment_rating": "稳健"
    },
    "衰退期": {
        "characteristics": ["技术落后", "市场萎缩", "需求下降", "转型压力"],
        "investment_rating": "谨慎"
    }
}

# 行业生命周期判断指标
LIFECYCLE_INDICATORS = {
    "growth_rate_high": "成长期",
    "growth_rate_moderate": "成熟期",
    "growth_rate_low": "衰退期",
    "tech_investment_high": "萌芽期/成长期",
    "market_concentration_low": "成长期",
    "market_concentration_high": "成熟期"
}

# 行业政策影响评估
POLICY_IMPACT_LEVELS = {
    "positive_high": "强利好",
    "positive_medium": "利好",
    "neutral": "中性",
    "negative_medium": "利空",
    "negative_high": "强利空"
}

def analyze_industry(stock_code, industry_name, market="a"):
    """
    分析行业发展趋势
    
    Args:
        stock_code: 股票代码
        industry_name: 行业名称
        market: 市场类型 (a/hk/us)
    
    Returns:
        dict: 行业分析结果
    """
    result = {
        "industry_name": industry_name,
        "market_stage": "unknown",
        "market_size": {},
        "growth_trend": {},
        "policy_impact": "neutral",
        "policy_details": [],
        "tech_trends": [],
        "competitive_landscape": {},
        "key_drivers": [],
        "challenges": [],
        "opportunities": [],
        "industry_peers": []
    }
    
    # 1. 判断行业生命周期阶段
    result["market_stage"] = infer_market_stage(industry_name)
    
    # 2. 分析政策影响
    result["policy_impact"], result["policy_details"] = analyze_policy_impact(industry_name)
    
    # 3. 识别技术趋势
    result["tech_trends"] = identify_tech_trends(industry_name)
    
    # 4. 分析竞争格局
    result["competitive_landscape"] = analyze_competitive_landscape(industry_name)
    
    # 5. 识别关键驱动因素
    result["key_drivers"] = identify_key_drivers(industry_name)
    
    # 6. 分析挑战与机遇
    result["challenges"] = identify_challenges(industry_name)
    result["opportunities"] = identify_opportunities(industry_name)
    
    # 7. 识别可比公司
    result["industry_peers"] = get_industry_peers(industry_name, market)
    
    return result


def infer_market_stage(industry_name):
    """根据行业名称推断生命周期阶段"""
    # 新兴行业关键词
    emerging_keywords = ["人工智能", "AI", "半导体", "芯片", "量子", "区块链", 
                        "新能源", "光伏", "风电", "储能", "氢能", "生物", 
                        "基因", "创新药", "机器人", "智能制造"]
    
    # 成熟行业关键词
    mature_keywords = ["银行", "地产", "钢铁", "煤炭", "有色", "化工", 
                       "纺织", "家电", "零售", "食品", "饮料"]
    
    # 衰退行业关键词
    declining_keywords = ["传统", "纸", "印刷", "纺织", "自行车"]
    
    industry_lower = industry_name.lower()
    
    for keyword in emerging_keywords:
        if keyword.lower() in industry_lower:
            return "成长期"
    
    for keyword in declining_keywords:
        if keyword.lower() in industry_lower:
            return "衰退期"
    
    for keyword in mature_keywords:
        if keyword.lower() in industry_lower:
            return "成熟期"
    
    return "成长期"  # 默认


def analyze_policy_impact(industry_name):
    """分析政策对行业的影响"""
    policy_details = []
    impact = "neutral"
    
    # 利好政策行业
    positive_policies = {
        "新能源": ["双碳目标", "新能源补贴", "绿色电力交易"],
        "半导体": ["国产替代", "集成电路产业基金", "芯片法案"],
        "人工智能": ["新一代人工智能发展规划", "数字中国"],
        "生物医药": ["健康中国", "创新药审批改革"],
        "高端制造": ["中国制造2025", "智能制造"],
        "光伏": ["光伏补贴", "整县推进", "BIPV"],
        "储能": ["新型储能规划", "储能补贴"],
        "机器人": ["机器人产业发展规划"]
    }
    
    # 中性政策行业
    neutral_policies = {
        "消费": ["促消费政策", "消费升级"],
        "金融": ["金融稳定", "对外开放"]
    }
    
    # 潜在利空行业
    negative_policies = {
        "房地产": ["房住不炒", "三道红线"],
        "教培": ["双减政策"],
        "互联网": ["反垄断", "数据安全"]
    }
    
    industry_lower = industry_name.lower()
    
    for policy_industry, policies in positive_policies.items():
        if policy_industry.lower() in industry_lower:
            policy_details.extend(policies)
            impact = "positive_high" if len(policies) >= 2 else "positive_medium"
            break
    
    if impact == "neutral":
        for policy_industry, policies in neutral_policies.items():
            if policy_industry.lower() in industry_lower:
                policy_details.extend(policies)
                impact = "neutral"
                break
    
    if impact == "neutral":
        for policy_industry, policies in negative_policies.items():
            if policy_industry.lower() in industry_lower:
                policy_details.extend(policies)
                impact = "negative_high" if len(policies) >= 2 else "negative_medium"
                break
    
    return impact, policy_details


def identify_tech_trends(industry_name):
    """识别行业技术趋势"""
    tech_trends = {
        "半导体": ["先进制程", "Chiplet", "RISC-V", "AI芯片", "3D堆叠"],
        "人工智能": ["大模型", "AGI", "多模态", "边缘计算", "AI Agent"],
        "新能源汽车": ["智能驾驶", "固态电池", "800V高压", "车联网"],
        "光伏": ["TOPCon", "HJT", "钙钛矿", "N型电池"],
        "生物医药": ["ADC药物", "基因编辑", "AI制药", "细胞治疗"],
        "机器人": ["人形机器人", "协作机器人", "自主导航", "力控技术"],
        "云计算": ["边缘计算", "混合云", "AI云服务", "算力网络"],
        "消费电子": ["折叠屏", "AI功能", "卫星通信", "快充"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, trends in tech_trends.items():
        if key.lower() in industry_lower:
            return trends
    
    return ["技术升级", "数字化转型"]


def analyze_competitive_landscape(industry_name):
    """分析竞争格局"""
    landscapes = {
        "半导体": {
            "market_structure": "寡头垄断",
            "key_players": ["台积电", "三星", "英特尔", "中芯国际"],
            "barriers": ["技术壁垒", "资金壁垒", "人才壁垒"]
        },
        "人工智能": {
            "market_structure": "头部集中",
            "key_players": ["OpenAI", "谷歌", "微软", "百度", "阿里"],
            "barriers": ["数据壁垒", "算力壁垒", "算法壁垒"]
        },
        "新能源汽车": {
            "market_structure": "竞争激烈",
            "key_players": ["特斯拉", "比亚迪", "蔚来", "小鹏", "理想"],
            "barriers": ["品牌壁垒", "技术壁垒", "渠道壁垒"]
        },
        "光伏": {
            "market_structure": "产能过剩",
            "key_players": ["隆基绿能", "通威股份", "晶科能源"],
            "barriers": ["成本壁垒", "规模壁垒"]
        },
        "生物医药": {
            "market_structure": "分散",
            "key_players": ["恒瑞医药", "药明康德", "智飞生物"],
            "barriers": ["研发壁垒", "审批壁垒"]
        }
    }
    
    industry_lower = industry_name.lower()
    
    for key, landscape in landscapes.items():
        if key.lower() in industry_lower:
            return landscape
    
    return {
        "market_structure": "竞争格局正在形成",
        "key_players": [],
        "barriers": []
    }


def identify_key_drivers(industry_name):
    """识别行业关键驱动因素"""
    drivers = {
        "半导体": ["国产替代需求", "AI算力需求", "数据中心建设"],
        "人工智能": ["大模型应用落地", "企业数字化转型", "AI+行业渗透"],
        "新能源汽车": ["渗透率提升", "政策补贴", "技术迭代"],
        "光伏": ["碳中和目标", "成本下降", "全球需求"],
        "生物医药": ["创新药出海", "老龄化需求", "消费升级"],
        "机器人": ["人口老龄化", "制造业升级", "AI赋能"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, driver_list in drivers.items():
        if key.lower() in industry_lower:
            return driver_list
    
    return ["需求增长", "技术进步", "政策支持"]


def identify_challenges(industry_name):
    """识别行业挑战"""
    challenges = {
        "半导体": ["技术封锁", "产能过剩", "高端人才短缺"],
        "人工智能": ["监管政策", "数据安全", "盈利模式"],
        "新能源汽车": ["价格战", "电池原材料涨价", "充电基础设施"],
        "光伏": ["产能过剩", "价格下跌", "贸易摩擦"],
        "生物医药": ["集采压力", "研发失败风险", "国际化挑战"],
        "房地产": ["政策调控", "资金压力", "库存高企"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, challenge_list in challenges.items():
        if key.lower() in industry_lower:
            return challenge_list
    
    return ["竞争加剧", "成本上升"]


def identify_opportunities(industry_name):
    """识别行业机遇"""
    opportunities = {
        "半导体": ["国产替代空间大", "AI芯片需求爆发", "先进封装"],
        "人工智能": ["千行百业渗透", "Agent应用", "垂直领域落地"],
        "新能源汽车": ["智能化升级", "出海机会", "储能协同"],
        "光伏": ["储能配套", "绿氢", "钙钛矿技术"],
        "生物医药": ["创新药出海", "医美需求", "CXO外包"],
        "机器人": ["人形机器人", "服务机器人", "AI融合"]
    }
    
    industry_lower = industry_name.lower()
    
    for key, opp_list in opportunities.items():
        if key.lower() in industry_lower:
            return opp_list
    
    return ["行业整合", "技术创新"]


def get_industry_peers(industry_name, market="a"):
    """获取行业可比公司"""
    peers = {
        "半导体": {
            "a": ["中芯国际", "韦尔股份", "闻泰科技", "兆易创新", "北方华创"],
            "hk": ["中芯国际", "华虹半导体", "晶门科技"],
            "us": ["NVDA", "INTC", "AMD", "QCOM"]
        },
        "人工智能": {
            "a": ["科大讯飞", "三六零", "浪潮信息", "中科曙光", "寒武纪"],
            "hk": ["百度集团", "阿里巴巴", "腾讯控股"],
            "us": ["NVDA", "GOOGL", "MSFT", "META"]
        },
        "新能源汽车": {
            "a": ["比亚迪", "宁德时代", "长城汽车", "长安汽车", "亿纬锂能"],
            "hk": ["比亚迪股份", "蔚来-SW", "小鹏-W", "理想-W"],
            "us": ["TSLA", "LI", "NIO", "XPEV"]
        },
        "光伏": {
            "a": ["隆基绿能", "通威股份", "晶科能源", "中环股份", "阳光电源"],
            "hk": ["晶科能源", "天合光能"],
            "us": ["JKS", "CSIQ", "ENPH"]
        },
        "生物医药": {
            "a": ["恒瑞医药", "药明康德", "智飞生物", "迈瑞医疗", "片仔癀"],
            "hk": ["药明生物", "康希诺生物", "信达生物"],
            "us": ["JNJ", "PFE", "MRNA"]
        },
        "白酒": {
            "a": ["贵州茅台", "五粮液", "泸州老窖", "洋河股份", "山西汾酒"],
            "hk": [],
            "us": []
        }
    }
    
    industry_lower = industry_name.lower()
    
    for key, market_peers in peers.items():
        if key.lower() in industry_lower:
            return market_peers.get(market, [])
    
    return []


def format_industry_report(result):
    """格式化行业分析报告"""
    report = []
    
    report.append("## 行业分析")
    report.append("")
    report.append(f"### 行业名称: **{result['industry_name']}**")
    report.append("")
    
    # 生命周期阶段
    stage_info = INDUSTRY_STAGES.get(result["market_stage"], {})
    report.append(f"### 行业生命周期: **{result['market_stage']}**")
    report.append("")
    if stage_info:
        report.append("**阶段特征:**")
        report.append("")
        for char in stage_info["characteristics"]:
            report.append(f"- {char}")
        report.append("")
        report.append(f"**投资评级:** {stage_info['investment_rating']}")
        report.append("")
    
    # 政策影响
    report.append("### 政策影响评估")
    report.append("")
    report.append(f"- **综合评级:** {POLICY_IMPACT_LEVELS.get(result['policy_impact'], result['policy_impact'])}")
    if result["policy_details"]:
        report.append("- **相关政策:**")
        for policy in result["policy_details"]:
            report.append(f"  - {policy}")
    report.append("")
    
    # 技术趋势
    if result["tech_trends"]:
        report.append("### 技术发展趋势")
        report.append("")
        for trend in result["tech_trends"]:
            report.append(f"- {trend}")
        report.append("")
    
    # 竞争格局
    if result["competitive_landscape"]:
        landscape = result["competitive_landscape"]
        report.append("### 竞争格局")
        report.append("")
        if landscape.get("market_structure"):
            report.append(f"- **市场结构:** {landscape['market_structure']}")
        if landscape.get("key_players"):
            report.append(f"- **主要玩家:** {', '.join(landscape['key_players'])}")
        if landscape.get("barriers"):
            report.append("- **进入壁垒:**")
            for barrier in landscape["barriers"]:
                report.append(f"  - {barrier}")
        report.append("")
    
    # 关键驱动因素
    if result["key_drivers"]:
        report.append("### 关键驱动因素")
        report.append("")
        for driver in result["key_drivers"]:
            report.append(f"- {driver}")
        report.append("")
    
    # 挑战与机遇
    if result["challenges"]:
        report.append("### 行业挑战")
        report.append("")
        for challenge in result["challenges"]:
            report.append(f"- {challenge}")
        report.append("")
    
    if result["opportunities"]:
        report.append("### 行业机遇")
        report.append("")
        for opportunity in result["opportunities"]:
            report.append(f"- {opportunity}")
        report.append("")
    
    # 可比公司
    if result["industry_peers"]:
        report.append("### 可比公司")
        report.append("")
        report.append(", ".join(result["industry_peers"]))
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    result = analyze_industry("002180", "半导体", "a")
    print(format_industry_report(result))
