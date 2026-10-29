# -*- coding: utf-8 -*-
"""
产品与商业模式分析模块
分析核心产品、技术壁垒、盈利模式
"""
import json

# 商业模式类型
BUSINESS_MODELS = {
    "B2B": {
        "description": "企业对企业模式",
        "characteristics": ["大额订单", "长期合作", "客户集中度高"],
        "revenue_stability": "高"
    },
    "B2C": {
        "description": "企业对消费者模式",
        "characteristics": ["小额高频", "品牌重要", "营销投入大"],
        "revenue_stability": "中"
    },
    "B2B2C": {
        "description": "企业对企业对消费者模式",
        "characteristics": ["渠道依赖", "利润分成", "规模效应"],
        "revenue_stability": "中高"
    },
    "SAAS": {
        "description": "软件即服务模式",
        "characteristics": ["订阅收入", "高毛利率", "客户粘性"],
        "revenue_stability": "高"
    },
    "Platform": {
        "description": "平台模式",
        "characteristics": ["双边网络", "网络效应", "轻资产"],
        "revenue_stability": "中"
    },
    "Hardware": {
        "description": "硬件产品模式",
        "characteristics": ["重资产", "供应链管理", "技术迭代"],
        "revenue_stability": "中"
    }
}

# 收入结构类型
REVENUE_STRUCTURE_TYPES = {
    "product": "产品销售",
    "service": "服务收入",
    "subscription": "订阅收入",
    "licensing": "授权收入",
    "advertising": "广告收入",
    "commission": "佣金收入",
    "other": "其他收入"
}

def analyze_product_and_business(company_info, industry_info, financial_data=None):
    """
    分析产品与商业模式
    
    Args:
        company_info: 公司信息
        industry_info: 行业信息
        financial_data: 财务数据
    
    Returns:
        dict: 分析结果
    """
    result = {
        "company_name": company_info.get("name", ""),
        "core_products": [],
        "product_matrix": {},
        "technology_barriers": [],
        "business_model": "unknown",
        "business_model_details": {},
        "revenue_structure": {},
        "customer_structure": {},
        "pricing_strategy": "unknown",
        "growth_strategy": [],
        "moat_analysis": {
            "moat_type": [],
            "strength": "unknown"
        }
    }
    
    # 1. 分析核心产品
    result["core_products"], result["product_matrix"] = analyze_core_products(company_info, industry_info)
    
    # 2. 分析技术壁垒
    result["technology_barriers"] = analyze_technology_barriers(company_info, industry_info)
    
    # 3. 判断商业模式
    result["business_model"], result["business_model_details"] = identify_business_model(company_info, industry_info)
    
    # 4. 分析收入结构
    result["revenue_structure"] = analyze_revenue_structure(financial_data)
    
    # 5. 分析客户结构
    result["customer_structure"] = analyze_customer_structure(company_info, industry_info)
    
    # 6. 判断定价策略
    result["pricing_strategy"] = identify_pricing_strategy(industry_info)
    
    # 7. 分析增长策略
    result["growth_strategy"] = identify_growth_strategy(company_info, industry_info)
    
    # 8. 护城河分析
    result["moat_analysis"] = analyze_moat(result)
    
    return result


def analyze_core_products(company_info, industry_info):
    """分析核心产品"""
    from industry_db import get_industry_data
    
    products = []
    product_matrix = {
        "core": [],
        "growth": [],
        "new": []
    }
    
    industry_name = industry_info.get("industry", "")
    company_name = company_info.get("name", "")
    
    # 使用行业数据库获取产品矩阵
    industry_data = get_industry_data(industry_name)
    matrix = industry_data.get("product_matrix", {})
    
    if matrix:
        product_matrix = matrix
        products = matrix.get("core", []) + matrix.get("growth", []) + matrix.get("new", [])
    
    # 根据公司名称细化产品
    if "纳思达" in company_name:
        products = ["打印机芯片", "打印耗材", "集成电路设计", "打印机整机"]
        product_matrix = {
            "core": ["打印机芯片", "打印耗材"],
            "growth": ["集成电路设计"],
            "new": ["打印机整机"]
        }
    
    return products, product_matrix


def analyze_technology_barriers(company_info, industry_info):
    """分析技术壁垒"""
    from industry_db import get_industry_data
    
    industry_name = industry_info.get("industry", "")
    industry_data = get_industry_data(industry_name)
    
    return industry_data.get("technology_barriers", ["技术积累", "人才储备", "资金投入", "客户关系"])


def identify_business_model(company_info, industry_info):
    """识别商业模式"""
    from industry_db import get_industry_data
    
    industry_name = industry_info.get("industry", "")
    industry_data = get_industry_data(industry_name)
    business_model = industry_data.get("business_model", {})
    
    return business_model.get("model", "B2B"), business_model.get("details", {"description": "企业对企业模式", "revenue_stability": "中"})


def analyze_revenue_structure(financial_data):
    """分析收入结构"""
    structure = {
        "product_sales": 0,
        "service_revenue": 0,
        "subscription": 0,
        "other": 0,
        "total": 0
    }
    
    if financial_data and isinstance(financial_data, dict):
        # 从财务数据中提取收入构成
        if "revenue_composition" in financial_data:
            comp = financial_data["revenue_composition"]
            structure["product_sales"] = comp.get("product", 0)
            structure["service_revenue"] = comp.get("service", 0)
            structure["subscription"] = comp.get("subscription", 0)
            structure["other"] = comp.get("other", 0)
            structure["total"] = sum([structure["product_sales"], 
                                     structure["service_revenue"], 
                                     structure["subscription"], 
                                     structure["other"]])
        else:
            # 默认值
            structure["product_sales"] = 80
            structure["service_revenue"] = 15
            structure["subscription"] = 3
            structure["other"] = 2
            structure["total"] = 100
    
    return structure


def analyze_customer_structure(company_info, industry_info):
    """分析客户结构"""
    from industry_db import get_industry_data
    
    industry_name = industry_info.get("industry", "")
    industry_data = get_industry_data(industry_name)
    
    structure = {
        "customer_type": industry_data.get("customer_types", ["企业客户", "政府客户", "个人消费者", "海外客户"]),
        "customer_concentration": "unknown",
        "geographic_distribution": industry_data.get("geographic_dist", ["中国大陆", "海外市场"])
    }
    
    # 判断客户集中度
    if "汽车厂商" in structure["customer_type"] or "运营商" in structure["customer_type"]:
        structure["customer_concentration"] = "高"
    elif "个人消费者" in structure["customer_type"]:
        structure["customer_concentration"] = "低"
    else:
        structure["customer_concentration"] = "中"
    
    return structure


def identify_pricing_strategy(industry_info):
    """识别定价策略"""
    from industry_db import get_industry_data
    
    industry_name = industry_info.get("industry", "")
    industry_data = get_industry_data(industry_name)
    
    return industry_data.get("pricing_strategy", "市场定价")


def identify_growth_strategy(company_info, industry_info):
    """识别增长策略"""
    from industry_db import get_industry_data
    
    industry_name = industry_info.get("industry", "")
    industry_data = get_industry_data(industry_name)
    
    return industry_data.get("growth_strategies", ["产品创新", "市场拓展", "技术升级", "并购整合"])


def analyze_moat(result):
    """分析护城河"""
    moat_analysis = {
        "moat_type": [],
        "strength": "unknown"
    }
    
    business_model = result.get("business_model", "")
    technology_barriers = result.get("technology_barriers", [])
    business_model_details = result.get("business_model_details", {})
    
    # 根据商业模式和壁垒判断护城河类型
    if business_model == "B2B":
        moat_analysis["moat_type"].append("客户粘性")
        moat_analysis["moat_type"].append("转换成本")
    
    if business_model == "SAAS" or business_model == "Platform":
        moat_analysis["moat_type"].append("网络效应")
    
    if "专利" in str(technology_barriers) or "研发" in str(technology_barriers):
        moat_analysis["moat_type"].append("技术壁垒")
    
    if "品牌" in str(technology_barriers):
        moat_analysis["moat_type"].append("品牌优势")
    
    if "规模" in str(technology_barriers):
        moat_analysis["moat_type"].append("规模经济")
    
    # 判断护城河强度
    if len(moat_analysis["moat_type"]) >= 3:
        moat_analysis["strength"] = "强"
    elif len(moat_analysis["moat_type"]) == 2:
        moat_analysis["strength"] = "中"
    else:
        moat_analysis["strength"] = "弱"
    
    return moat_analysis


def format_product_report(result):
    """格式化产品与商业模式分析报告"""
    report = []
    
    report.append("## 产品与商业模式分析")
    report.append("")
    report.append(f"### 公司: **{result['company_name']}**")
    report.append("")
    
    # 核心产品
    if result["core_products"]:
        report.append("### 核心产品")
        report.append("")
        for product in result["core_products"]:
            report.append(f"- {product}")
        report.append("")
    
    # 产品矩阵
    if result["product_matrix"]:
        report.append("### 产品矩阵")
        report.append("")
        if result["product_matrix"]["core"]:
            report.append(f"**核心产品:** {', '.join(result['product_matrix']['core'])}")
        if result["product_matrix"]["growth"]:
            report.append(f"**成长产品:** {', '.join(result['product_matrix']['growth'])}")
        if result["product_matrix"]["new"]:
            report.append(f"**创新产品:** {', '.join(result['product_matrix']['new'])}")
        report.append("")
    
    # 技术壁垒
    if result["technology_barriers"]:
        report.append("### 技术壁垒")
        report.append("")
        for barrier in result["technology_barriers"]:
            report.append(f"- {barrier}")
        report.append("")
    
    # 商业模式
    report.append(f"### 商业模式: **{result['business_model']}**")
    if result["business_model_details"]:
        report.append(f"- 描述: {result['business_model_details'].get('description', '')}")
        report.append(f"- 收入稳定性: {result['business_model_details'].get('revenue_stability', '')}")
    report.append("")
    
    # 收入结构
    if result["revenue_structure"]:
        rs = result["revenue_structure"]
        report.append("### 收入结构")
        report.append("")
        report.append(f"- 产品销售: {rs.get('product_sales', 0)}%")
        report.append(f"- 服务收入: {rs.get('service_revenue', 0)}%")
        report.append(f"- 订阅收入: {rs.get('subscription', 0)}%")
        report.append(f"- 其他收入: {rs.get('other', 0)}%")
        report.append("")
    
    # 客户结构
    if result["customer_structure"]:
        cs = result["customer_structure"]
        report.append("### 客户结构")
        report.append("")
        if cs["customer_type"]:
            report.append(f"- 客户类型: {', '.join(cs['customer_type'])}")
        report.append(f"- 客户集中度: {cs.get('customer_concentration', '')}")
        if cs["geographic_distribution"]:
            report.append(f"- 地域分布: {', '.join(cs['geographic_distribution'])}")
        report.append("")
    
    # 定价策略
    report.append(f"### 定价策略: {result['pricing_strategy']}")
    report.append("")
    
    # 增长策略
    if result["growth_strategy"]:
        report.append("### 增长策略")
        report.append("")
        for strategy in result["growth_strategy"]:
            report.append(f"- {strategy}")
        report.append("")
    
    # 护城河分析
    if result["moat_analysis"]:
        ma = result["moat_analysis"]
        report.append("### 护城河分析")
        report.append("")
        report.append(f"- 护城河类型: {', '.join(ma['moat_type'])}")
        report.append(f"- 护城河强度: {ma['strength']}")
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    company_info = {"name": "纳思达股份有限公司"}
    industry_info = {"industry": "半导体"}
    result = analyze_product_and_business(company_info, industry_info)
    print(format_product_report(result))
