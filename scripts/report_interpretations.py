# -*- coding: utf-8 -*-
"""
report.py - 上市公司分析报告生成器（解读导向版）

核心原则：报告不是数据列表，是分析结论。
每个模块必须：
1. 识别数据中的模式（时间聚类/频率异常/矛盾信号）
2. 生成有支撑的推断和结论
3. 标注风险等级和关注点
4. 不dump原始数据，只呈现提炼后的观点

新增解读函数：
- _interpret_executives: 高管变动深度解读
- _interpret_announcements: 重大公告内容解读
- _interpret_audit_opinion: 审计意见原文提取+结论
- _interpret_regulatory: 中介机构意见解读
- _interpret_dividend: 利润分配意图分析
"""