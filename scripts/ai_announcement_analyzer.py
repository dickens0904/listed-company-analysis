# -*- coding: utf-8 -*-
"""
AI公告分析模块
使用商汤DeepSeek进行公告智能分析
"""
import json
import time
from openai import OpenAI
from scripts.llm_config import LLM_CONFIG

# 公告类型定义
ANNOUNCEMENT_CATEGORIES = [
    "业绩报告", "业绩预告", "业绩快报",
    "分红派息", "送股转增",
    "定增募资", "配股", "可转债",
    "收购兼并", "资产重组", "资产注入",
    "股权转让", "股权质押",
    "监管问询", "关注函", "监管处罚",
    "高管变动", "股权激励",
    "对外投资", "子公司动态",
    "诉讼仲裁", "重大合同",
    "其他"
]

# 公告重要性等级
IMPORTANCE_LEVELS = {
    "critical": {
        "name": "重大",
        "description": "可能对股价产生重大影响",
        "color": "red"
    },
    "important": {
        "name": "重要",
        "description": "可能对公司运营产生影响",
        "color": "orange"
    },
    "normal": {
        "name": "一般",
        "description": "常规信息披露",
        "color": "gray"
    }
}

class AIAnnouncementAnalyzer:
    """AI公告分析器"""
    
    def __init__(self):
        self.client = OpenAI(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
        )
    
    def analyze_announcement(self, title, content="", max_retries=3):
        """
        分析单条公告
        
        Args:
            title: 公告标题
            content: 公告内容（可选）
            max_retries: 最大重试次数
        
        Returns:
            dict: 分析结果
        """
        prompt = self._build_analysis_prompt(title, content)
        
        try:
            response = self.client.chat.completions.create(
                model=LLM_CONFIG["model"],
                messages=[
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=LLM_CONFIG["temperature"],
                max_tokens=LLM_CONFIG["max_tokens"],
                stream=False
            )
            
            result = response.choices[0].message.content
            return self._parse_result(result, title, content)
        
        except Exception as e:
            print(f"AI分析失败: {e}")
            if max_retries > 0:
                time.sleep(5)
                return self.analyze_announcement(title, content, max_retries - 1)
        
        # 返回默认分析结果
        return self._get_default_result(title, content)
    
    def analyze_multiple(self, announcements):
        """
        批量分析公告
        
        Args:
            announcements: 公告列表
        
        Returns:
            list: 分析结果列表
        """
        results = []
        for ann in announcements:
            title = ann.get("title", ann.get("NOTICETITLE", ""))
            content = ann.get("content", "")
            analysis = self.analyze_announcement(title, content)
            
            # 合并原始公告信息
            result = {**ann, **analysis}
            results.append(result)
        
        return results
    
    def _get_system_prompt(self):
        """获取系统提示词"""
        return """你是一位资深的证券分析师，擅长分析上市公司公告。请按照以下框架进行分析：

1. **公告分类**：判断公告类型
2. **重要性评估**：评估对公司的影响程度
3. **关键信息提取**：提取核心数据和要点
4. **影响分析**：分析对公司财务、业务、股价的潜在影响
5. **风险提示**：指出潜在风险和不确定性

请输出结构化的JSON格式结果。"""
    
    def _build_analysis_prompt(self, title, content):
        """构建分析提示词"""
        return f"""请分析以下上市公司公告：

**公告标题**：{title}

**公告内容**：{content[:2000] if content else "无详细内容"}

请按照以下格式输出JSON：
{{
    "category": "公告类型",
    "importance": "critical|important|normal",
    "importance_reason": "评估理由",
    "key_points": ["要点1", "要点2"],
    "impact_analysis": "影响分析",
    "risk_factors": ["风险1", "风险2"],
    "summary": "简明摘要"
}}

公告类型可选值：{", ".join(ANNOUNCEMENT_CATEGORIES)}
"""
    
    def _parse_result(self, result, title, content):
        """解析AI返回结果"""
        try:
            # 尝试提取JSON
            start = result.find("{")
            end = result.rfind("}") + 1
            if start != -1 and end != -1:
                json_str = result[start:end]
                return json.loads(json_str)
        except Exception as e:
            print(f"JSON解析失败: {e}")
        
        # 如果解析失败，返回默认结果
        return self._get_default_result(title, content)
    
    def _get_default_result(self, title, content):
        """获取默认分析结果"""
        # 简单的规则匹配
        category = self._simple_classify(title)
        importance = self._simple_importance(title, category)
        
        return {
            "category": category,
            "importance": importance,
            "importance_reason": "基于标题关键词判断",
            "key_points": [f"公告标题: {title}"],
            "impact_analysis": "需要查看完整公告内容进行详细分析",
            "risk_factors": [],
            "summary": f"{title}"
        }
    
    def _simple_classify(self, title):
        """简单分类"""
        category_keywords = {
            "业绩报告": ["年度报告", "半年报", "季度报告", "财务报告"],
            "业绩预告": ["业绩预告", "业绩快报"],
            "分红派息": ["分红", "派息", "分配方案"],
            "送股转增": ["送股", "转增", "配股"],
            "定增募资": ["定增", "非公开发行", "募资"],
            "可转债": ["可转债"],
            "收购兼并": ["收购", "并购", "重组"],
            "资产重组": ["资产重组", "资产注入"],
            "股权转让": ["股权转让"],
            "股权质押": ["股权质押"],
            "监管问询": ["问询函"],
            "关注函": ["关注函"],
            "监管处罚": ["处罚", "警示", "监管函"],
            "高管变动": ["辞职", "聘任", "任免"],
            "股权激励": ["股权激励", "员工持股"],
            "对外投资": ["对外投资", "投资设立"],
            "子公司动态": ["子公司", "孙公司"],
            "诉讼仲裁": ["诉讼", "仲裁"],
            "重大合同": ["重大合同", "中标"]
        }
        
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if keyword in title:
                    return category
        
        return "其他"
    
    def _simple_importance(self, title, category):
        """简单重要性判断"""
        critical_keywords = ["终止", "失败", "损失", "减值", "诉讼", "处罚", "问询"]
        
        if any(k in title for k in critical_keywords):
            return "critical"
        
        important_categories = ["业绩预告", "定增募资", "收购兼并", "资产重组", "监管处罚"]
        if category in important_categories:
            return "important"
        
        return "normal"


def analyze_announcement_risk(announcements):
    """
    分析公告风险
    
    Args:
        announcements: 公告列表
    
    Returns:
        dict: 风险分析结果
    """
    analyzer = AIAnnouncementAnalyzer()
    results = analyzer.analyze_multiple(announcements)
    
    # 统计风险
    risk_summary = {
        "total_announcements": len(results),
        "critical_count": 0,
        "important_count": 0,
        "normal_count": 0,
        "risk_categories": [],
        "risk_summary": "",
        "warnings": []
    }
    
    for result in results:
        importance = result.get("importance", "normal")
        
        if importance == "critical":
            risk_summary["critical_count"] += 1
            risk_summary["warnings"].append(result.get("summary", ""))
        elif importance == "important":
            risk_summary["important_count"] += 1
        else:
            risk_summary["normal_count"] += 1
        
        category = result.get("category")
        if category not in risk_summary["risk_categories"]:
            risk_summary["risk_categories"].append(category)
    
    # 生成风险摘要
    if risk_summary["critical_count"] > 0:
        risk_summary["risk_summary"] = f"发现{risk_summary['critical_count']}条重大风险公告"
    elif risk_summary["important_count"] > 0:
        risk_summary["risk_summary"] = f"发现{risk_summary['important_count']}条重要公告，需关注"
    else:
        risk_summary["risk_summary"] = "近期公告无重大风险"
    
    return {
        "analysis_results": results,
        "risk_summary": risk_summary
    }


def format_ai_analysis_report(analysis_result):
    """格式化AI分析报告"""
    results = analysis_result.get("analysis_results", [])
    risk_summary = analysis_result.get("risk_summary", {})
    
    report = []
    
    report.append("## AI公告深度分析")
    report.append("")
    report.append("### 分析概览")
    report.append("")
    report.append(f"- 分析公告数: {risk_summary.get('total_announcements', 0)}")
    report.append(f"- 重大公告: {risk_summary.get('critical_count', 0)}")
    report.append(f"- 重要公告: {risk_summary.get('important_count', 0)}")
    report.append(f"- 一般公告: {risk_summary.get('normal_count', 0)}")
    report.append("")
    
    # 风险摘要
    report.append("### 风险摘要")
    report.append("")
    report.append(risk_summary.get("risk_summary", "无风险摘要"))
    report.append("")
    
    # 风险警示
    if risk_summary.get("warnings"):
        report.append("### 风险警示")
        report.append("")
        for warning in risk_summary["warnings"]:
            report.append(f"- ⚠️ {warning}")
        report.append("")
    
    # 详细分析
    if results:
        report.append("### 公告详细分析")
        report.append("")
        
        # 按重要性排序
        sorted_results = sorted(results, key=lambda x: {"critical": 0, "important": 1, "normal": 2}[x.get("importance", "normal")])
        
        for result in sorted_results[:10]:  # 只显示前10条
            importance = result.get("importance", "normal")
            importance_info = IMPORTANCE_LEVELS.get(importance, {"name": "未知"})
            
            report.append(f"**{result.get('title', '')}**")
            report.append(f"- 类型: {result.get('category', '')}")
            report.append(f"- 重要性: {importance_info['name']}")
            report.append(f"- 摘要: {result.get('summary', '')}")
            if result.get("impact_analysis"):
                report.append(f"- 影响分析: {result.get('impact_analysis')}")
            if result.get("risk_factors"):
                report.append(f"- 风险因素: {', '.join(result.get('risk_factors'))}")
            report.append("")
    
    return "\n".join(report)


if __name__ == "__main__":
    # 测试示例
    test_announcements = [
        {"title": "关于收到深交所问询函的公告", "content": "公司收到深交所问询函，要求说明关联交易情况"},
        {"title": "2025年度业绩预告", "content": "预计净利润同比增长50%"},
        {"title": "非公开发行股票预案", "content": "拟募集资金10亿元用于新项目"},
        {"title": "高管辞职公告", "content": "总经理因个人原因辞职"}
    ]
    
    print("=== AI公告分析测试 ===")
    
    # 测试单条分析
    analyzer = AIAnnouncementAnalyzer()
    result = analyzer.analyze_announcement(test_announcements[0]["title"], test_announcements[0]["content"])
    print("单条分析结果:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 测试风险分析
    print("\n=== 风险分析测试 ===")
    risk_result = analyze_announcement_risk(test_announcements)
    print(format_ai_analysis_report(risk_result))
