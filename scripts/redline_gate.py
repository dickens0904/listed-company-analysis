# -*- coding: utf-8 -*-
"""
redline_gate.py - 收口红线门禁（P0 新增 · 2026-10-16 审计修复）
==============================================================

对应五段式输出协议两条硬纪律：
    1. 缺口不得写成结论
    2. 路由严格锚定 + 异常即停（不用模拟数据/Plan B）

本模块在 analyze.py 所有维度采集完成后、生成报告与 AI 投资建议之前执行：

    核心维度数据不足/失败 → blocked=True
        ├─ 禁止生成"投资建议/目标价/评级"（AI 分析阶段直接跳过）
        ├─ 报告强制插入 🔴 红灯章节，列出缺口与补齐路径
        └─ 溯源表对应维度标 ❌

核心维度定义（按市场）：
    A股：financial / structure / quote / valuation / annual_pdf
    港股：hk_financial / hk_quote
    美股：us_financial / us_quote
"""

from __future__ import annotations
from typing import Dict, List

from data_source_registry import SOURCE_REGISTRY

# 各市场的核心维度（失败即触发红线）
CRITICAL_DIMS = {
    'a': ['financial', 'structure', 'quote', 'valuation'],
    'cn': ['financial', 'structure', 'quote', 'valuation'],
    'hk': ['hk_financial', 'hk_quote'],
    'us': ['us_financial', 'us_quote'],
}

# 维度级"数据不足"判定：这些键出现即视为不可用（而非空数据）
_INSUFFICIENT_KEYS = ('insufficient',)
_ERROR_KEYS = ('error',)

# 非核心维度，但**缺口时必须阻断特定结论**（2026-10-19 新增）
# legal_risk 缺数据 → 不得写"合规干净/无诉讼无处罚"这类结论
ADVICE_BLOCKING_DIMS = {
    'legal_risk': '不得出具"合规干净/无重大诉讼处罚"等合规结论',
    'intellectual_property': '不得据专利商标做技术壁垒/资产化判断',
}


def _is_failed(result) -> bool:
    """该维度结果是否应判定为"失败/不可用" """
    if not isinstance(result, dict):
        return result is None
    # 显式 insufficient（如 earnings_forecast 的 P0 修复返回值）
    if result.get('insufficient'):
        return True
    # 显式 error（数据源全失败 / 拒绝出结论）
    err = result.get('error')
    if isinstance(err, str) and err.strip():
        return True
    # 源标记为 all_failed
    src = result.get('_meta', {}).get('source') or result.get('source')
    if src == 'all_failed':
        return True
    return False


def _reason(result) -> str:
    if not isinstance(result, dict):
        return '维度无返回（None）'
    if result.get('error'):
        return str(result['error'])[:200]
    src = result.get('_meta', {}).get('source') or result.get('source')
    if src == 'all_failed':
        return '所有数据源均失败'
    return '数据不足（insufficient）'


def evaluate_redline(findings: Dict[str, dict], dims: List[str],
                     market: str = 'a') -> dict:
    """
    评估本次分析是否触达红线。

    Returns:
        {
          'blocked': bool,             # True = 禁止出投资建议/目标价
          'failed_critical': [dim...], # 失败的核心维度
          'insufficient_dims': [dim...], # 所有不足/失败的维度
          'ok_dims': [dim...],
          'notes': {dim: reason},
          'market': str,
        }
    """
    critical = set(CRITICAL_DIMS.get(market, CRITICAL_DIMS['a']))
    failed_critical: List[str] = []
    insufficient: List[str] = []
    ok_dims: List[str] = []
    notes: Dict[str, str] = {}

    for dim in dims:
        result = findings.get(dim)
        if _is_failed(result):
            insufficient.append(dim)
            notes[dim] = _reason(result)
            if dim in critical:
                failed_critical.append(dim)
        else:
            ok_dims.append(dim)

    # 另外： earnings_forecast / valuation 的 insufficient 即使在非核心维度也要拦投资建议；
    # legal_risk / intellectual_property 缺口 → 阻断相应的合规与 IP 结论（不出红灯，只标注）
    advice_blocking = set(failed_critical) | ({'earnings_forecast', 'valuation'} & set(insufficient))
    blocked_conclusions = []
    for dim in ADVICE_BLOCKING_DIMS:
        if dim in insufficient:
            blocked_conclusions.append({'dim': dim, 'note': ADVICE_BLOCKING_DIMS[dim]})

    blocked = bool(failed_critical)
    advice_blocked = bool(advice_blocking)

    return {
        'blocked': blocked,
        'advice_blocked': advice_blocked,
        'failed_critical': failed_critical,
        'insufficient_dims': insufficient,
        'ok_dims': ok_dims,
        'notes': notes,
        'market': market,
        'advice_blocking_dims': sorted(advice_blocking),
        'blocked_conclusions': blocked_conclusions,
    }


def format_redline_markdown(rl: dict) -> str:
    """生成报告用的 🔴 红灯章节"""
    if not rl.get('blocked'):
        # 未触红线：仅提示存在缺口
        if not rl.get('insufficient_dims'):
            return ''
        lines = ['\n## ⚠️ 数据缺口提示\n']
        if rl.get('advice_blocked'):
            lines.append('以下维度数据不足，本次分析**不出具投资评级与目标价**，'
                         '相关章节按"缺口"处理，未做默认值填充：\n')
        else:
            lines.append('以下维度数据不足，相关结论已按"缺口"处理，未做默认值填充：\n')
        for d in rl['insufficient_dims']:
            lines.append(f"- **{d}**：{rl['notes'].get(d, '')}")
        for bc in rl.get('blocked_conclusions') or []:
            lines.append(f"- ⛔ **{bc['dim']}**：{bc['note']}")
        lines.append('')
        return '\n'.join(lines)

    lines = [
        '\n## 🔴 红灯：数据不足，本报告不出具投资建议与目标价\n',
        '> **本节为强制门禁输出。** 核心维度数据源失败或数据不足，',
        '依据"缺口不得写成结论 / 异常即停"纪律，',
        '本次分析**不输出投资评级、目标价、买卖建议**。\n',
        '### 失败的核心维度\n',
    ]
    for d in rl['failed_critical']:
        lines.append(f"- ❌ **{d}**：{rl['notes'].get(d, '')}")
    if rl.get('advice_blocking_dims'):
        lines.append('\n### 连带阻断投资建议的维度\n')
        for d in rl['advice_blocking_dims']:
            if d not in rl['failed_critical']:
                lines.append(f"- ⚠️ {d}：{rl['notes'].get(d, '')}")
    lines.append('\n### 补齐路径\n')
    lines.append('按 `scripts/data_source_registry.py` 的 MCP 映射表取数：\n')
    lines.append('- 财务报表 → `dzh-mcp.getStockCorpProfit / getBalanceSheetMetrics / getStockXjllData`')
    lines.append('- 股权结构 → `dzh-mcp.getF10HolderDetailsData`')
    lines.append('- 实时行情/估值 → `dzh-mcp.getQuoteDyna`')
    lines.append('- 年报正文 → `alphapai-lite-mcp.search_announcements` → `download_announcement_parsing`')
    lines.append('\n补齐后重跑 `python analyze.py --stock <代码> --full`。\n')
    return '\n'.join(lines)


def print_redline(rl: dict):
    """控制台输出"""
    if rl.get('blocked'):
        print(f"\n{'='*60}")
        print("🔴 红线触发：核心维度数据不足，禁止输出投资建议/目标价")
        for d in rl['failed_critical']:
            print(f"   ❌ {d}: {rl['notes'].get(d, '')}")
        print(f"{'='*60}\n")
    elif rl.get('insufficient_dims'):
        print(f"\n⚠️ 数据缺口（未触红线）：{', '.join(rl['insufficient_dims'])}")
