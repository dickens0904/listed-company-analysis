# -*- coding: utf-8 -*-
"""
CLI 工具函数 — 从 analyze.py 提取的纯函数

包含：参数解析、维度标签、维度摘要
"""
from __future__ import annotations
import argparse


def parse_args(args=None):
    """解析命令行参数。args=None 时读取 sys.argv，测试时可传入列表。"""
    parser = argparse.ArgumentParser(description='上市公司/未上市公司全景分析')
    parser.add_argument('--stock', help='股票代码（上市公司）')
    parser.add_argument('--name', help='中文公司名（自动跨市场识别A股/港股/美股）')
    parser.add_argument('--company', help='公司名称（未上市公司）')
    parser.add_argument('--market', default='auto',
                        choices=['auto', 'a', 'hk', 'us'],
                        help="市场: auto=自动识别(默认), a=A股, hk=港股, us=美股")
    parser.add_argument('--dims', default='all',
                        help='分析维度（逗号分隔）')
    parser.add_argument('--full', action='store_true', help='完整分析')
    parser.add_argument('--output', default=None, help='输出目录')
    parser.add_argument('--no-pdf', action='store_true', help='跳过PDF下载')
    parser.add_argument('--no-peer', action='store_true', help='跳过同业对比')
    # 2026-10-20：标的确认校验的逃逸阀。仅在确属同一标的不同简称
    # （如更名过渡期、A/H 双重上市简称不同）时使用。
    parser.add_argument('--force', action='store_true',
                        help='跳过"代码-名称一致性"校验（确属同一标的时用）')
    # 只传代码时的交叉校验源。--stock 与 --name 互斥，所以"只给代码"
    # 场景没有可比对的名字（2026-10-20 法狮龙被误填 603001 正是这个场景）。
    # 用法：analyze.py --stock 605318 --expect 法狮龙
    parser.add_argument('--expect', default='',
                        help='预期公司名/简称，与 --stock 配合做一致性校验；不匹配则终止')
    parser.add_argument('--report-type', dest='report_type', default='all',
                        choices=['annual', 'semi_annual', 'quarterly', 'all'],
                        help='定期报告类型')
    parser.add_argument('--report-years', dest='report_years', type=int, default=1,
                        help='定期报告回溯年数(默认1)')
    parser.add_argument('--ai-report', action='store_true',
                        help='使用 AI 首席分析师进行深度解读（基于商汤 DeepSeek V4 Flash）')
    parser.add_argument('--cleanup', action='store_true',
                        help='清理tmp目录中过期的临时文件/PDF缓存（7天前）')
    parser.add_argument('--cleanup-days', type=int, default=7,
                        help='清理N天前未访问的文件，默认7天')
    parser.add_argument('--tmp-status', action='store_true',
                        help='查看tmp目录使用情况')
    parsed = parser.parse_args(args)
    if not parsed.stock and not parsed.name and not parsed.company and not parsed.cleanup and not parsed.tmp_status:
        parser.error('必须指定 --stock / --name / --company / --cleanup / --tmp-status')
    if parsed.stock and parsed.name:
        parser.error('--stock 和 --name 不能同时使用')
    return parsed


def dim_label(dim: str) -> str:
    """返回维度的中文标签"""
    labels = {
        'announcements': '公告全景', 'financial': '财务报表', 'executives': '高管动态',
        'capital': '资金动作', 'subsidiary': '子公司IPO', 'related': '关联方运作',
        'regulatory': '监管历史', 'structure': '股权结构', 'industry': '行业竞争', 'risk': '综合风险',
        'websearch': '联网搜索', 'annual_pdf': '年报PDF', 'periodic_reports': '定期报告',
        'hk_financial': '港股财务',
        'peer_compare': '同业对比', 'rd_analysis': '研发与利润归因',
        'quote': '实时行情', 'bse_price': '实时行情',
        'multi_year_trend': '多年财务趋势', 'valuation': '估值分析',
        'governance': '公司治理', 'share_history': '股本融资历史',
        'institutional': '机构持仓', 'earnings_forecast': '盈利预测',
        'investor_qa': '投资者互动', 'hkex_announcements': '港交所公告',
        'cross_validation': '隐情交叉验证', 'strategic_opportunity': '战略机遇全景',
        # 新增战略分析维度
        'national_strategy': '国家战略分析', 'industry_analysis': '行业分析',
        'competition': '竞争格局分析', 'product': '产品与商业模式',
        'capacity': '产能分析', 'subcompany': '子公司分析',
        # 新增公告分析维度
        'announcement_timeline': '公告时间线', 'ai_announcement': 'AI公告分析',
        # v3: 招股书备案系统
        'prospectus': '招股说明书', 'prospectus_registry_query': '招股书备案查询',
        # qcc 权威维度（2026-10-19）
        'legal_risk': '法律/合规风险', 'intellectual_property': '知识产权',
    }
    return labels.get(dim, dim)


def dim_summary(dim: str, result) -> str:
    """返回维度的摘要字符串，用于日志输出"""
    # 批量模式：list → 降级为通用描述
    if isinstance(result, list):
        total = len(result)
        ok = sum(1 for r in result if isinstance(r, dict) and r.get('status') == 'trading')
        if dim in ('quote', 'bse_price'):
            return f"批量行情: {total}只 [{ok}只交易中]"
        return f"批量结果: {total}项"

    summaries = {
        'announcements': f"公告{result.get('count',0)}条 | CRITICAL:{result.get('importance_stats',{}).get('critical',0)} MAJOR:{result.get('importance_stats',{}).get('major',0)} ROUTINE:{result.get('importance_stats',{}).get('routine',0)} | 溯源链:{len(result.get('event_chains',{}))}条",
        'financial': f"审计意见: {result.get('audit_opinion','未知')}",
        'executives': f"发现 {result.get('change_count',0)} 条高管变动",
        'capital': f"发现 {result.get('count',0)} 项资金动作",
        'subsidiary': f"辅导期数: {result.get('report_count','未知')}",
        'related': f"发现 {result.get('count',0)} 项运作",
        'regulatory': f"发现 {result.get('count',0)} 条监管记录",
        'industry': f"行业: {result.get('industry_class',{}).get('csrc_industry') or result.get('industry_class',{}).get('sw_industry') or '未知'} | 可比公司{len(result.get('competitors',[]))}家",
        'risk': f"风险等级: {result.get('level','未知')} | 得分: {result.get('score','?')}/100",
        'websearch': "搜索完成",
        'annual_pdf': f"年报: {result.get('year','?')}年 | {result.get('page_count',0)}页" if result and not result.get('error') else "年报: 获取失败",
        'periodic_reports': f"定期报告: 已下载{result.get('summary',{}).get('total_downloaded',0) if isinstance(result.get('summary'), dict) else 0}份" if result and not result.get('error') else "定期报告: 获取失败",
        'hk_financial': f"财务数据: {result.get('profile',{}).get('company_name_cn','?')} | 营收 {result.get('valuation',{}).get('revenue','?')}",
        'cross_validation': f"隐情 {len(result.get('findings',[]))} 条 | 综合风险评分: {result.get('overall_risk_score','?')}/100",
        'peer_compare': f"同业公司: {result.get('peer_count',0)}家 | 对比结论: {result.get('conclusion','N/A')}",
        'rd_analysis': f"主因: {result.get('profit_decomposition',{}).get('primary_cause','未知')} | 研发: {result.get('rd_quality',{}).get('rd_expense_亿','N/A')}亿元(资本化{result.get('rd_quality',{}).get('capitalization_rate','N/A')}%) | {result.get('rd_vs_loss_summary','N/A')}",
        'quote': '行情维度',
        'bse_price': '行情维度',
        'strategic_opportunity': lambda r: f"机遇维度: {len(r.get('opportunities',[]))}条 | 护城河: {'+'.join(r.get('dimensions',{}).get('business_model',{}).get('moat_type',[])[:3]) if r.get('dimensions',{}).get('business_model',{}).get('moat_type') else '未检测'}",
        # v3: 招股书备案系统
        'prospectus': f"招股书: {result.get('market','?').upper()}市场 | 文档{len(result.get('documents',[]))}份 | IPO阶段{len(result.get('ipo_stages',{}))}个" if result else '招股书: 无数据',
        'prospectus_registry_query': f"备案查询: {len(result.get('results',[])) if isinstance(result, dict) else 0}条记录" if result else '备案查询: 无数据',
        'legal_risk': (lambda r: f"命中风险维度 {r.get('signal_count', 0)} 项"
                       f"（严重类 {r.get('severe_count', 0)} 项）"
                       f" | 已回填工具 {len(r.get('tools_backfilled') or [])} 个"
                       f" | 缺口 {len(r.get('gaps') or [])} 项"
                       if r.get('status') == 'ok'
                       else f"🔴 {r.get('status')}: {r.get('error', '')[:60]}"),
        'intellectual_property': (lambda r: f"专利 {r.get('patent_count_returned', 0)} 条"
                                  f" | 商标 {r.get('trademark_count_returned', 0)} 条"
                                  if r.get('status') in ('ok', 'empty')
                                  else f"🔴 {r.get('status')}: {r.get('error', '')[:60]}"),
    }
    val = summaries.get(dim, '')
    if callable(val):
        val = val(result)
    return val
