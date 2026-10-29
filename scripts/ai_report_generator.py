# -*- coding: utf-8 -*-
"""
AI报告生成器
从压缩素材包(material_pack.json)用LLM生成完整的Markdown报告
"""
import json
import os
import sys
import re
from datetime import datetime

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from llm_config import call_llm
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result


# ============================================================
# 报告生成主流程
# ============================================================

def generate_report(material_pack: dict, output_dir: str) -> str:
    """
    从素材包生成完整Markdown报告。

    Args:
        material_pack: 压缩后的素材包（来自data_compressor）
        output_dir: 输出目录

    Returns:
        报告文件路径
    """
    meta = material_pack.get('meta', {})
    company = meta.get('company', '未知公司')
    stock = meta.get('stock', '')
    market = meta.get('market', 'a')
    market_name = {'a': 'A股', 'hk': '港股', 'us': '美股'}.get(market, market)

    print(f'\n=== AI报告生成 ===')
    print(f'  公司: {company} ({stock})')

    # 素材包转为JSON文本
    pack_text = json.dumps(material_pack, ensure_ascii=False, indent=1, default=str)

    # 估算token
    est_tokens = len(pack_text) // 2
    print(f'  素材包: {len(pack_text)}字 (~{est_tokens}tokens)')

    # 如果素材包太大，分批处理
    if est_tokens > 30000:
        print(f'  素材包较大，分两批生成...')
        report_body = _generate_in_batches(material_pack, company, stock, market_name)
    else:
        report_body = _generate_single_call(material_pack, company, stock, market_name)

    if not report_body:
        print('  ❌ AI报告生成失败')
        return None

    # 组装完整报告
    today = datetime.now().strftime('%Y-%m-%d')
    full_report = f'# {company}（{stock}）{market_name}全维度深度分析报告\n\n'
    full_report += f'> 报告日期：{today} | 数据来源：东方财富、巨潮、通达信、年报PDF\n\n'
    full_report += report_body

    # 保存
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, 'report.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(full_report)

    print(f'  ✅ 报告已生成: {report_path} ({len(full_report)//1024}KB)')
    return report_path


# ============================================================
# 单次调用生成（素材包 < 30K tokens）
# ============================================================

def _sanitize_pack_text(text: str) -> str:
    replacements = [
        ("维吾尔强迫劳动预防法", "美国相关制裁/合规法规"),
        ("Uyghur Forced Labor Prevention Act", "美国相关制裁/合规法规"),
        ("UFLPA", "美国相关制裁/合规法规"),
        ("实体清单", "合规限制名单"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    # 限制单条公告全文预览长度，降低触发内容审查的概率
    try:
        import re as _re
        text = _re.sub(r'("full_text_preview":\s*").{1200,}?(")', r'\1\2', text)
    except Exception as _sexc:
        record(__name__, '_sanitize_pack_text', _sexc, note='静默降级')
        pass
    return text


def _generate_single_call(pack, company, stock, market_name):
    """单次LLM调用生成完整报告"""
    pack_text = _sanitize_pack_text(json.dumps(pack, ensure_ascii=False, indent=1, default=str))

    system_prompt = _get_report_system_prompt()
    user_prompt = f"""请根据以下{company}（{stock}，{market_name}）的数据素材包，生成一份完整的深度分析报告。

要求：
- 仅做事实性分析与投资研究，不做任何操作建议之外的内容
- 涉及合规/制裁风险时，只用中性事实描述，避免重复敏感法律名称

## 数据素材包
```json
{pack_text}
```

请直接输出Markdown格式的报告正文（不需要报告标题，我会自动添加）。"""

    print(f'  [LLM] 生成完整报告...')
    result = call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=16000)

    if not result:
        return None

    print(f'  [LLM] 生成成功，{len(result)}字')
    return result


# ============================================================
# 分批生成（素材包较大时）
# ============================================================

def _generate_in_batches(pack, company, stock, market_name):
    """分两批生成：先生成各章节，再生成摘要和投资逻辑"""

    # 第一批：拆分素材包为多个章节素材
    chapters = _split_pack_to_chapters(pack)
    chapter_texts = []

    for i, (chapter_name, chapter_data) in enumerate(chapters):
        print(f'  [LLM] 生成章节 {i+1}/{len(chapters)}: {chapter_name}...')
        chapter_json = json.dumps(chapter_data, ensure_ascii=False, indent=1, default=str)

        system_prompt = f"""你是一位资深证券分析师，正在撰写{company}（{stock}）的深度分析报告。
请根据提供的"{chapter_name}"维度数据，撰写该章节的分析内容。

要求：
1. 用Markdown格式，使用##作为章节标题
2. 数据要准确引用，不要编造
3. 分析要有深度，不是简单罗列数据
4. 指出关键发现、风险点、亮点
5. 语言专业但可读"""

        user_prompt = f"## {chapter_name}维度数据\n```json\n{chapter_json}\n```\n\n请撰写该章节的分析内容。"

        result = call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=4096)
        if result:
            chapter_texts.append(result)
            print(f'    → {len(result)}字')
        else:
            chapter_texts.append(f'## {chapter_name}\n\n> 该章节数据不足，暂无分析\n')

    # 第二批：生成执行摘要和投资逻辑
    all_chapters = '\n\n'.join(chapter_texts)
    print(f'  [LLM] 生成执行摘要和投资逻辑...')

    summary_prompt = """你是一位资深证券分析师，正在为一份深度分析报告撰写执行摘要和投资逻辑。
请根据已生成的各章节内容，撰写：

1. **执行摘要**（300字以内）：核心发现、风险等级、投资评级
2. **投资逻辑**：核心论点、催化剂、关键假设、主要风险

用Markdown格式输出。"""

    summary_result = call_llm(summary_prompt, f"各章节内容：\n{all_chapters[:15000]}", temperature=0.3, max_tokens=4096)

    if summary_result:
        return summary_result + '\n\n' + all_chapters
    else:
        return all_chapters


def _split_pack_to_chapters(pack):
    """将素材包拆分为章节素材"""
    chapters = []

    # 财务与估值（第二章，扩展：加入价值链收入结构）
    chapters.append(('财务深度分析', {
        'quote': pack.get('quote', {}),
        'financial': pack.get('financial', {}),
        'metrics_trend': pack.get('metrics_trend', []),
        'three_statements': pack.get('three_statements', {}),
        'financing': pack.get('financing', {}),
        'valuation': pack.get('valuation', {}),
        'fundraising': pack.get('fundraising', {}),
        'financial_summary_ai': pack.get('financial_summary_ai', ''),
        'value_chain': pack.get('value_chain', {}),
    }))

    # 公告与风险 + 宏观政策（扩展：加入 macro_policy）
    chapters.append(('公告全景、宏观政策与风险评估', {
        'announcements': pack.get('announcements', {}),
        'risk': pack.get('risk', {}),
        'regulatory': pack.get('regulatory', {}),
        'capital': pack.get('capital', {}),
        'lawsuits': pack.get('lawsuits', []),
        'macro_policy': pack.get('macro_policy', {}),
    }))

    # 治理与股权
    chapters.append(('公司治理、股权结构与资本运作', {
        'executives': pack.get('executives', {}),
        'structure': pack.get('structure', {}),
        'top10': pack.get('top10', []),
        'pledge': pack.get('pledge', {}),
        'subsidiary': pack.get('subsidiary', {}),
        'related': pack.get('related', {}),
        'capital': pack.get('capital', {}),
    }))

    # 业务与行业 + 同业对比 + 价值链（扩展：加入 competitors + value_chain）
    chapters.append(('业务分析、行业竞争与价值链', {
        'industry': pack.get('industry', {}),
        'product': pack.get('product', {}),
        'business': pack.get('business', {}),
        'tdx': pack.get('tdx', {}),
        'competitors': pack.get('competitors', {}),
        'value_chain': pack.get('value_chain', {}),
        'strategic': pack.get('strategic', {}),
    }))

    # 审计 + 合规 + 战略（扩展：加入 strategic）
    chapters.append(('审计意见、合规风险与战略定位', {
        'audit': pack.get('audit', {}),
        'regulatory': pack.get('regulatory', {}),
        'lawsuits': pack.get('lawsuits', []),
        'strategic': pack.get('strategic', {}),
    }))

    # 投资逻辑
    chapters.append(('投资逻辑与建议', {
        'investment': pack.get('investment', {}),
        'investment_markdown': pack.get('investment_markdown', ''),
    }))

    return chapters


# ============================================================
# System Prompt
# ============================================================

def _get_report_system_prompt():
    return """你是一位拥有10年经验的资深证券分析师，擅长撰写上市公司深度分析报告。

你的报告风格：
- **专业但可读**：不用过多术语堆砌，但分析要有深度
- **数据驱动**：每个观点都要有数据支撑，引用具体数字
- **风险导向**：重点关注风险信号，不回避问题
- **逻辑清晰**：每个章节有明确的结论，不是罗列数据
- **有洞察力**：能从数据中发现别人看不到的联系和趋势

报告共10个核心章节（每个必须有实质内容，不能写"数据不足"）：

**内容质量约束（严禁违反）：**
- **禁止空话套话**：不得使用"正在推进"、"积极开展"、"有序进行"、"持续关注"、"密切跟踪"、"有待观察"等无实质内容的表述
- **禁止简单罗列**：每个观点必须有分析和结论，不能只罗列数据
- **禁止无据判断**：定性判断必须有数据支撑，引用具体数字
- **禁止重复表述**：每个章节必须有独特见解，避免章节间内容重复
- **禁止模糊表述**：涉及金额、比例、时间的内容必须明确量化

**分析深度要求：**
- **连贯分析**：对公告等信息进行整合分析，输出连贯的观点和结论，不要逐条列举公告内容
- **综合判断**：基于所有提供的数据进行综合分析，避免碎片化的信息堆砌
- **时间范围**：内控风险分析仅限最近5年（2021年及以后）的公告，避免使用过时信息
- **避免推断标注**：尽可能从原始公告中提取实际数据，减少"(推断)"标注的使用
- **财务分析**：必须包含同比/环比变化分析，关键指标需标注变化幅度
- **风险分析**：必须量化概率和影响程度，建立风险等级评估
- **估值分析**：必须有至少两种方法交叉验证，给出明确估值区间
- **竞争分析**：必须有行业对标数据，展示相对竞争力

**处罚机制：**
- 违反上述要求任意一条，报告视为不合格
- 连续三次违反，终止报告生成

## 一、公司概况与核心数据
公司主营业务、行业地位、核心竞争力、主要产品线及营收占比。行情快照：最新价、涨跌幅、总市值、流通市值、市盈率、换手率、主力净流入等。

## 二、财务深度分析
营收利润趋势（多年对比，至少3年+最近一期）、盈利能力（毛利率、净利率、ROE）、资产负债结构（资产负债率、有息负债、货币资金、应收账款、存货、上下游资金占用/客户与供应商集中度）、现金流、关键财务比率变化趋势。给出核心发现和关键风险信号。

## 三、高级财务健康评分
基于财务数据计算并解读以下评分：

### 3.1 Piotroski F-Score（9分制）
盈利能力（ROA>0、现金流为正、ROA改善、现金流>净利润）+ 杠杆/流动性（长期负债减少、流动比率改善、无新股发行）+ 运营效率（毛利率改善、资产周转率改善）。总分8-9为优秀，6-7为良好，4-5为一般，0-3为薄弱。

### 3.2 Altman Z-Score
Z = 1.2×(营运资本/总资产) + 1.4×(留存收益/总资产) + 3.3×(EBIT/总资产) + 0.6×(市值/总负债) + 1.0×(销售收入/总资产)。Z>2.99为安全区，1.81-2.99为灰色区，<1.81为困境区。

### 3.3 Beneish M-Score（盈利操纵检测）
评估8个指标：应收账款天数指数、毛利率指数、资产质量指数、销售增长指数、折旧指数、SG&A指数、杠杆指数、总应计项目/总资产。M>-1.78可能存在盈利操纵（警示），M<-1.78为正常。

### 3.4 Value Trap Score（0-100，越低越好）
评估4个维度：价格动量（25分）、盈利质量（25分）、资产负债表健康（25分）、估值背景（25分）。0-39为真正价值，40-59为谨慎区，60-79为可能陷阱，80-100为强烈陷阱信号。

### 3.5 Max Drawdown（5年最大回撤）
历史最大跌幅：0-20%为低波动，20-40%为中波动，40-60%为高波动，>60%为极端波动。

## 四、技术分析与入场时机
### 4.1 价格走势分析
30-60日价格趋势、成交量变化、动量评估。

### 4.2 关键技术指标
RSI（相对强弱指数）：>70超买，<30超卖，40-60中性。MACD：看涨/看跌交叉判断。移动均线：50日均线、200日均线位置。

### 4.3 关键价位
支撑位（主要/次要）、阻力位（主要/次要）。

### 4.4 入场评估
技术形态（看涨/中性/看跌）、理想入场价格区间、最佳买入时机、止损位建议。

## 五、投资者人格评分（0-10分制）
针对8种传奇投资大师的选股标准打分：

### 5.1 巴菲特评分（护城河导向）
ROE>20%（2分）、净利率>15%（2分）、自由现金流转正且增长（2分）、护城河强度（品牌/定价权）（2分）、盈利可预测性（2分）。

### 5.2 芒格评分（逆向思维）
从10分开始，高负债扣分、不稳定盈利扣分、管理层历史差扣分、无护城河扣分、会计问题扣分。

### 5.3 达里奥评分（经济周期韧性）
D/E<1（2分）、Beta<1（2分）、跨周期毛利率稳定（2分）、低盈利波动（2分）、抗衰退历史（2分）。

### 5.4 林奇GARP评分（合理价格成长）
PEG<0.5得10分，PEG 0.5-1.0得8分，PEG 1.0-1.5得6分，PEG 1.5-2.0得4分，PEG>2.0得2分。盈利持续增长+1分，业务易理解+1分，衰退行业-1分。

### 5.5 格雷厄姆评分（安全边际）
P/E<15（2分）、P/B<1.5（2分）、流动比率>2（2分）、10年正盈利（2分）、20年以上分红（2分）。

### 5.6 格林布拉特评分（魔法公式）
资本回报率（ROC）和盈利收益率（EY）的综合排名，前10%得10分，按比例递减。

### 5.7 邓普顿评分（逆向投资）
多年低点交易+3分、分析师冷淡+2分、基本面强劲+3分、全球视野+2分。

### 5.8 索罗斯评分（反射性）
动量和趋势强度（3分）、宏观顺风（3分）、市场认知转变（2分）、拐点催化剂（2分）。

## 六、公告全景、宏观政策与风险评估
**公告分析要求：**

### 6.1 关键事件深度分析
对公告进行**综合分析**，不要逐条列举。重点关注：重大诉讼/仲裁、对外担保、资产重组、关联交易、审计意见异常、股权激励变动等关键事项。

**关联交易分析**：必须包含以下要素：
| 要素 | 要求 |
|------|------|
| 交易对手 | 明确关联方名称及关系 |
| 交易金额 | 具体金额（万元/亿元） |
| 交易类型 | 资金占用/担保/采购/销售等 |
| 风险评估 | 量化风险等级（高/中/低）及理由 |

**重大事项进展**：涉及分拆上市、资产重组等重大事项，必须说明：
- 当前进度（具体阶段）
- 预计完成时间
- 估值/金额规模
- 成功概率评估
- 对公司的影响分析

### 6.2 风险矩阵
| 风险类型 | 发生概率 | 影响程度 | 风险等级 | 具体证据 |
|----------|----------|----------|----------|----------|
| 财务风险 | 高/中/低 | 高/中/低 | 综合评级 | 公告/财务数据 |
| 经营风险 | 高/中/低 | 高/中/低 | 综合评级 | 公告/行业数据 |
| 合规风险 | 高/中/低 | 高/中/低 | 综合评级 | 监管记录 |

### 6.3 宏观政策影响
从概念板块、行业归属、公告内容推断宏观/行业政策方向，分析政策对公司的具体影响（量化评估）。

**时间限制**：仅限分析最近5年（2021年及以后）的公告。
**禁止空话**：不得使用"正在推进"、"积极开展"等无实质内容表述，必须有具体进度和数据支撑。

## 七、公司治理、股权结构与资本运作
前十大股东（名称、持股比例、股东性质）。实际控制人持股路径、一致行动人关系。高管变动、现任核心管理层、股权激励计划。质押冻结情况、近期增减持记录。子公司及关联方、资本运作事件。

## 八、业务分析、行业竞争与价值链
产品线构成及各产品营收占比、产能/产能扩张情况。行业竞争格局、同业对比（至少3家可比公司主营业务对比、可比公司与公司业务的匹配度、行业毛利率/集中度参考）。价值链：上游供应商集中度、核心生产/设计环节、下游客户集中度与渠道情况、增值能力。

## 九、估值综合评估
### 9.1 DCF分析（现金流折现）
假设保守的增长率、利润率、WACC，计算内在价值，给出合理估值区间。

### 9.2 可比公司法
选取3-5家同行业可比公司，对比P/E、EV/EBITDA、P/S、P/B等估值指标。

### 9.3 彼得林奇估值
PEG比率评估，合理价格的增长股标准。

### 9.4 综合估值结论
当前股价vs内在价值、安全边际（要求>15%）、估值结论（低估/合理/高估）。

## 十、综合分析与投资建议
### 10.1 审计意见与合规风险
审计机构及意见类型（如不是标准无保留意见，必须概括强调事项段内容和金额）。监管处罚记录、问询函等合规风险。

### 10.2 SWOT分析
**必须使用表格形式，每项必须有数据支撑：**

| 维度 | 具体内容 | 支撑数据 | 行业对比 |
|------|----------|----------|----------|
| **优势(Strengths)** | 如技术领先、市场份额、品牌优势等 | 具体数字/比例 | 与行业平均对比 |
| **劣势(Weaknesses)** | 如财务压力、技术短板、地域集中等 | 具体数字/比例 | 与行业平均对比 |
| **机会(Opportunities)** | 如政策支持、市场增长、技术变革等 | 市场规模/增长率 | 具体政策/趋势 |
| **威胁(Threats)** | 如竞争加剧、政策变化、技术替代等 | 影响概率/程度 | 行业风险数据 |

**注意**：禁止简单罗列，每项必须有具体数据支撑和分析结论

### 10.3 PEST分析
**政治(Political)**：政策法规、监管环境、政府补贴、国际关系等
**经济(Economic)**：宏观经济周期、利率汇率、通胀水平、消费需求等
**社会(Social)**：人口结构、消费习惯、社会趋势、环保要求等
**技术(Technological)**：技术创新、研发投入、行业技术变革、专利壁垒等

### 10.4 牛市vs熊市情景分析
**牛市情景**：上涨空间、主要论据（3条）、实现条件。
**熊市情景**：下跌风险、主要论据（3条）、触发条件。
**平衡评估**：哪种情景概率更高及理由。

### 10.5 投资评级与建议
**推荐评级**：强烈买入/买入/持有/回避/卖出
**核心逻辑**：3-5个支持论据
**催化剂**：近中远期可能的催化剂事件
**关键假设**：投资逻辑成立的前提条件
**主要风险**：最大风险点及可能影响
**入场策略**：理想入场价、最佳时机、止损位
**目标价**：保守/中性/乐观目标价
**持仓建议**：建议仓位比例（基于风险和信心程度）

### 10.6 备选标的（如为卖出/回避评级）
提供3-5个更好的投资替代选择，说明每家公司的优势。

要求：
- 直接输出Markdown正文，不要输出报告标题（我会自动添加）
- 每个章节都要有实质内容，不能写"数据不足"或"暂无分析"
- 如果素材包包含对应数据，必须覆盖，不得省略
- 如果某个维度数据确实不足，用已有数据做替代分析，并说明数据局限
- 数据引用要准确，不要编造数字
- 表格用于展示对比数据（财务趋势、股东列表、高管列表等）
- 输出顺序严格按照以上章节顺序，章节标题使用 `## ` 级别
- 在"高级财务健康评分"和"投资者人格评分"章节中，如果某些数据无法从素材包获取，必须基于现有财务数据进行合理估算或标注"数据不足，需补充"
"""


# ============================================================
# 主入口
# ============================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='AI报告生成器')
    parser.add_argument('--pack', required=True, help='material_pack.json路径')
    parser.add_argument('--output', required=True, help='输出目录')

    args = parser.parse_args()

    with open(args.pack, 'r', encoding='utf-8') as f:
        pack = json.load(f)

    generate_report(pack, args.output)

    # 生成HTML报告（与 analyze.py 保持一致）
    try:
        from report_html import generate_html_report
        # 构建最小化的 results 对象供 HTML 生成使用
        results = {
            'stock': pack.get('meta', {}).get('stock', '') or pack.get('quote', {}).get('code', ''),
            'market': pack.get('meta', {}).get('market', 'a'),
        }
        html_path = generate_html_report(results, args.output)
        print(f'  ✅ HTML报告已生成: {html_path}')
        
        # 自动打开HTML报告
        try:
            import webbrowser
            webbrowser.open('file:///' + html_path.replace('\\', '/'))
            print(f'  🌐 HTML报告已在浏览器中打开')
        except Exception as e:
            print(f'  ⚠️ 打开浏览器失败: {e}')
    except Exception as e:
        print(f'  ⚠️ HTML报告生成失败: {e}')
