# listed-company-analysis 技能增强技术规格

**版本**：v2.1
**更新日期**：2026-05-25
**状态**：待实施

---

## 一、总体架构

### 1.1 增强目标

基于现有31维度能力，补充以下关键模块：

| 模块 | 优先级 | 状态 |
|------|--------|------|
| 价值链分析 | P0 | 待实现 |
| 收并购深度分析 | P0 | 待实现 |
| 战略叙事生成 | P1 | 待实现 |
| 竞争格局图谱 | P1 | 待实现 |
| 子公司深度分析 | P1 | 待实现 |

### 1.2 新增分析维度

```
新增维度（5个）
├── value_chain      # 价值链分析 ← P0
├── ma_deep          # 收并购深度分析 ← P0
├── strategic_narrative # 战略叙事生成 ← P1
├── competition_map   # 竞争格局图谱 ← P1
└── subcompany_deep   # 子公司深度分析 ← P1
```

---

## 二、P0 模块详细规格

### 2.1 价值链分析模块（value_chain_analysis.py）

#### 2.1.1 模块职责

从年报、业务概述、产销量等章节提取公司价值链定位，分析：
- 上游：供应商依赖度、原材料成本占比、议价能力
- 中游：产能利用率、良品率、核心技术壁垒
- 下游：客户集中度、销售渠道掌控力、品牌溢价

#### 2.1.2 数据来源

| 环节 | 数据来源 | 提取方式 |
|------|---------|---------|
| 上游 | 年报"供应商"章节 | annual_extract.py |
| 中游 | 年报"主要产品/产能"章节 | annual_extract.py |
| 下游 | 年报"前五客户/销售渠道"章节 | annual_extract.py |
| 补充 | 东方财富"产销量"数据 | financials.py |

#### 2.1.3 函数设计

```python
# 文件：scripts/value_chain_analysis.py

class ValueChainAnalyzer:
    def __init__(self, annual_sections: dict, financials: dict):
        """初始化分析器

        Args:
            annual_sections: 年报章节提取结果（来自 annual_extract.py）
            financials: 财务数据（来自 financials.py）
        """
        self.sections = annual_sections
        self.financials = financials
        self.upstream = {}
        self.midstream = {}
        self.downstream = {}

    def analyze_upstream(self) -> dict:
        """分析上游（供应商端）

        Returns:
            {
                'supplier_concentration': float,   # 供应商集中度（前五占比）
                'top5_supplier_ratio': str,        # "XX%"
                'related_supplier_ratio': float,   # 关联交易供应商占比
                'raw_material_cost_ratio': float, # 原材料成本占营收比
                'supplier_risk': str,              # 高/中/低
                'bargaining_power': str,            # 强/中/弱
                'key_findings': list               # 关键发现
            }
        """
        pass

    def analyze_midstream(self) -> dict:
        """分析中游（生产制造端）

        Returns:
            {
                'capacity_utilization': float,     # 产能利用率
                'good_rate': float,                # 良品率
                'production_scale': str,            # 产能规模描述
                'tech_barrier': list,               # 技术壁垒列表
                'capex_intensity': float,           # Capex占营收比
                'production_efficiency': str,      # 高/中/低
                'key_findings': list
            }
        """
        pass

    def analyze_downstream(self) -> dict:
        """分析下游（客户端）

        Returns:
            {
                'customer_concentration': float,    # 客户集中度（前五占比）
                'sales_model': str,                 # 直销/经销/混合
                'channel_control': str,             # 强/中/弱
                'brand_premium': float,            # 品牌溢价指数
                'customer_loyalty': str,            # 高/中/低
                'key_findings': list
            }
        """
        pass

    def generate_value_chain_report(self) -> dict:
        """生成完整价值链报告

        Returns:
            {
                'upstream': {...},
                'midstream': {...},
                'downstream': {...},
                'value_chain_score': int,           # 0-100 综合评分
                'strengths': list,                  # 优势
                'weaknesses': list,                 # 劣势
                'opportunities': list,              # 机会
                'threats': list,                    # 威胁
                'summary': str                      # 一句话总结
            }
        """
        pass


def fetch_value_chain(stock_code: str, market: str = 'a',
                      data_dir: str = None) -> dict:
    """价值链分析主入口

    Args:
        stock_code: 股票代码
        market: 市场（a/hk/us）
        data_dir: 数据输出目录

    Returns:
        完整的价值链分析报告
    """
    pass
```

#### 2.1.4 提取规则

**上游供应商提取**：
```
关键词：["前五名供应商", "供应商", "采购", "原材料"]
提取字段：
  - 前五供应商采购额占比
  - 是否存在关联交易供应商
  - 原材料成本占比（成本表推算）
  - 应付账款周转天数
```

**中游生产提取**：
```
关键词：["产能", "产量", "销量", "产能利用率", "在建工程"]
提取字段：
  - 各类产品产能
  - 产能利用率（产量/产能）
  - 在建工程转固进度
  - 研发投入占比
```

**下游销售提取**：
```
关键词：["前五名客户", "销售模式", "渠道", "经销商"]
提取字段：
  - 前五客户销售占比
  - 直销/经销比例
  - 销售费用率
  - 品牌相关费用
```

#### 2.1.5 评分体系

```
价值链综合评分（0-100）

上游得分（33分）：
  - 供应商集中度 < 30%: +15分
  - 供应商集中度 30-50%: +8分
  - 原材料成本占比 < 40%: +10分
  - 应付账款周期 > 行业平均: +8分

中游得分（34分）：
  - 产能利用率 > 80%: +15分
  - 研发投入占比 > 5%: +10分
  - Capex占比适中(5-15%): +9分

下游得分（33分）：
  - 客户集中度 < 30%: +15分
  - 销售费用率 < 行业平均: +10分
  - 渠道掌控力强: +8分
```

#### 2.1.6 集成方式

在 `dispatcher.py` 中添加：

```python
# dispatcher.py 新增

from scripts.value_chain_analysis import fetch_value_chain

elif dim == 'value_chain':
    return fetch_value_chain(stock, market, data_dir)
```

在 `report.py` 中添加：

```python
# report.py 新增章节

def _section_value_chain(data):
    """第24章：价值链分析"""
    vc = data.get('value_chain', {})

    section = f"""
## 24. 价值链分析

### 24.1 上游分析（供应商端）
- 供应商集中度：{vc.get('upstream', {}).get('top5_supplier_ratio', 'N/A')}
- 关联交易供应商占比：{vc.get('upstream', {}).get('related_supplier_ratio', 'N/A')}%
- 供应商议价能力：{vc.get('upstream', {}).get('bargaining_power', 'N/A')}
- 关键发现：{vc.get('upstream', {}).get('key_findings', [])}

### 24.2 中游分析（生产制造端）
- 产能利用率：{vc.get('midstream', {}).get('capacity_utilization', 'N/A')}
- 技术壁垒：{vc.get('midstream', {}).get('tech_barrier', [])}
- 生产效率：{vc.get('midstream', {}).get('production_efficiency', 'N/A')}
- 关键发现：{vc.get('midstream', {}).get('key_findings', [])}

### 24.3 下游分析（客户端）
- 客户集中度：{vc.get('downstream', {}).get('customer_concentration', 'N/A')}
- 销售模式：{vc.get('downstream', {}).get('sales_model', 'N/A')}
- 渠道掌控力：{vc.get('downstream', {}).get('channel_control', 'N/A')}
- 关键发现：{vc.get('downstream', {}).get('key_findings', [])}

### 24.4 综合评估
- 价值链评分：{vc.get('value_chain_score', 'N/A')}/100
- 核心优势：{vc.get('strengths', [])}
- 主要劣势：{vc.get('weaknesses', [])}
- 风险提示：{vc.get('threats', [])}
"""
    return section
```

---

### 2.2 收并购深度分析模块（ma_deep_analysis.py）

#### 2.2.1 模块职责

在现有 `related_deals.py` 基础上，增加：
- 收购标的公司的基本面分析
- 收购协同效应评估
- 收购后业绩追踪
- 商誉减值风险预警

#### 2.2.2 函数设计

```python
# 文件：scripts/ma_deep_analysis.py

class MADeepAnalyzer:
    def __init__(self, related_deals: dict, financials: dict,
                 annual_sections: dict):
        self.deals = related_deals.get('deals', [])
        self.financials = financials
        self.sections = annual_sections

    def analyze_deal(self, deal: dict) -> dict:
        """深度分析单个收购交易

        Args:
            deal: related_deals.py 中的单笔交易

        Returns:
            {
                'deal_id': str,
                'deal_type': str,              # 资产收购/股权收购
                'target_info': {
                    'name': str,               # 标的公司名称
                    'industry': str,           # 所属行业
                    'main_business': str,      # 主营业务
                    'financial_summary': dict   # 简要财务数据
                },
                'valuation': {
                    'deal_value': float,      # 交易金额（万元）
                    'pe_ratio': float,         # 收购PE倍数
                    'pb_ratio': float,         # 收购PB倍数
                    'premium': float,          # 溢价率
                },
                'synergy': {
                    'expected': str,           # 预期协同效应
                    'timeline': str,           # 实现时间线
                    'confidence': str,         # 高/中/低
                },
                'post_integration': {
                    'status': str,             # 已完成/进行中/未启动
                    'performance': dict,       # 业绩表现
                    'issues': list,            # 整合问题
                },
                'goodwill_risk': {
                    'goodwill_amount': float,  # 商誉金额
                    'goodwill_ratio': float,   # 商誉占净资产比
                    'impairment_risk': str,    # 高/中/低
                    'impairment_history': list # 历史减值记录
                },
                'risk_level': str,             # 高/中/低
                'recommendation': str          # 投资建议
            }
        """
        pass

    def analyze_all_deals(self) -> dict:
        """分析所有收购交易"""
        pass

    def generate_ma_report(self) -> dict:
        """生成完整MA分析报告"""
        pass


def fetch_ma_deep_analysis(stock_code: str, market: str = 'a',
                          data_dir: str = None) -> dict:
    """收并购深度分析主入口"""
    pass
```

#### 2.2.3 评估维度

**收购标的分析**：
```
1. 标的公司的行业地位
2. 标的公司财务健康度（营收/利润/负债）
3. 标的公司与母公司的业务协同性
4. 收购对价的合理性（相对估值）
```

**协同效应评估**：
```
1. 收入协同：渠道共享、客户导流、新市场进入
2. 成本协同：采购议价、生产规模、管理费用
3. 战略协同：产业链整合、技术获取、牌照获取
```

**商誉风险评估**：
```
风险等级 = f(商誉金额, 商誉占净资产比, 业绩承诺完成率, 历史减值)

高风险特征：
  - 商誉占净资产 > 50%
  - 业绩承诺连续2年未完成
  - 行业景气度下行
  - 收购溢价 > 10倍PE
```

#### 2.2.4 集成方式

```python
# dispatcher.py 新增

from scripts.ma_deep_analysis import fetch_ma_deep_analysis

elif dim == 'ma_deep':
    # 需要先运行 related 获取基础数据
    related = fetch_related_deals(stock, market, data_dir)
    return fetch_ma_deep_analysis(stock, market, data_dir)
```

---

## 三、P1 模块详细规格

### 3.1 战略叙事生成模块（strategic_narrative.py）

#### 3.1.1 模块职责

整合多维度数据，自动生成公司战略叙事：
- 公司愿景与定位
- 核心竞争优势
- 战略执行路径
- 风险与挑战
- 未来展望

#### 3.1.2 输入数据

```python
class StrategicNarrativeGenerator:
    """战略叙事生成器

    需要整合以下数据：
    - value_chain: 价值链分析结果
    - industry: 行业竞争格局
    - financials: 财务报表分析
    - governance: 公司治理
    - related_deals: 收并购活动
    - announcements: 重大公告
    """

    def __init__(self, all_data: dict):
        self.data = all_data

    def generate_narrative(self) -> dict:
        """生成战略叙事

        Returns:
            {
                'vision': str,           # 公司愿景
                'positioning': str,     # 市场定位
                'core_advantages': list, # 核心优势
                'strategy_path': str,    # 战略路径
                'execution_status': str, # 执行状态
                'risks_challenges': list,
                'outlook': str,          # 未来展望
                'investment_thesis': str # 投资逻辑
            }
        """
        pass
```

### 3.2 竞争格局图谱模块（competition_map.py）

#### 3.2.1 模块职责

- 自动识别行业主要竞争者
- 绘制市场份额变化图
- 标注竞争优势/劣势
- 生成竞争护城河分析

#### 3.2.2 输出格式

```python
class CompetitionMapGenerator:
    def generate_competition_map(self) -> dict:
        """生成竞争格局图谱

        Returns:
            {
                'market_size': str,         # 市场规模
                'market_growth': str,       # 市场增速
                'players': [
                    {
                        'name': str,
                        'market_share': float,
                        'revenue': float,
                        'strengths': list,
                        'weaknesses': list
                    }
                ],
                'our_position': dict,      # 目标公司定位
                'competitive_advantages': list,
                'barriers_to_entry': list,
                'threats': list,
                'map_url': str             # 可视化图表路径
            }
        """
        pass
```

---

## 四、数据流与集成

### 4.1 数据流图

```
analyze.py (主入口)
    │
    ├── dispatcher.py (维度调度)
    │   ├── value_chain_analysis.py    ← P0新增
    │   ├── ma_deep_analysis.py        ← P0新增
    │   ├── strategic_narrative.py      ← P1新增
    │   └── competition_map.py          ← P1新增
    │
    ├── 数据采集层
    │   ├── financials.py
    │   ├── structure.py
    │   ├── related_deals.py
    │   └── annual_extract.py
    │
    └── AI分析层
        ├── ai_analyst.py
        └── llm_config.py
    │
    └── 报告生成
        └── report.py (新增章节24-28)
```

### 4.2 维度调用顺序

```python
# analyze.py 中新增的维度顺序

DIM_ORDER = [
    # 基础数据采集（第一批）
    'quote',           # 1. 实时行情
    'financial',       # 2. 财务报表
    'announcements',   # 3. 公告全景

    # 股权与治理（第二批）
    'structure',       # 4. 股权结构
    'governance',      # 5. 公司治理
    'share_history',   # 6. 股本融资

    # 经营分析（第三批）
    'executives',      # 7. 高管动态
    'related',         # 8. 关联方运作 ← MA分析依赖此数据
    'subsidiary',      # 9. 子公司分拆
    'capital',         # 10. 资金动作

    # 战略分析（第四批）← P0/P1新增
    'value_chain',     # 11. 价值链分析 ← 新增
    'industry',        # 12. 行业竞争
    'competition_map', # 13. 竞争格局图谱 ← 新增

    # 深度分析（第五批）
    'multi_year_trend', # 14. 多年财务
    'valuation',        # 15. 估值分析
    'peer_compare',     # 16. 同业对比

    # AI综合（最后）
    'risk',            # 17. 综合风险
    'strategic_narrative',  # 18. 战略叙事 ← 新增
]
```

---

## 五、报告章节更新

### 5.1 完整报告结构（28章节）

```
report.md - 上市公司全景战略分析报告
├── 1. 执行摘要
├── 2. 公告全景
├── 3. 实时行情
├── 4. 财务报表分析
├── 5. 高管动态
├── 6. 资金动作
├── 7. 子公司分拆IPO追踪
├── 8. 关联方资本运作
│   └── 8.1 收并购深度分析 ← 新增子章节
├── 9. 监管历史
├── 10. 股权结构分析
├── 11. 行业竞争格局
├── 12. 同业财务对比
├── 13. 研发与利润归因
├── 14. 综合风险评级
├── 15. 多年财务趋势
├── 16. 盈利预测与情景分析
├── 17. 估值分析
├── 18. 公司治理深度分析
├── 19. 股本变动与融资历史
├── 20. 机构持仓与筹码分析
├── 21. 战略意图综合分析
│   ├── 21.1 战略叙事 ← 新增
│   └── 21.2 竞争格局图谱 ← 新增
├── 22. 年报PDF分析
├── 23. 信息缺失清单
├── 24. 价值链分析 ← 新增章节
│   ├── 24.1 上游分析（供应商端）
│   ├── 24.2 中游分析（生产制造端）
│   ├── 24.3 下游分析（客户端）
│   └── 24.4 综合评估
├── 25. 收并购深度分析 ← 新增章节
│   ├── 25.1 历史收购回顾
│   ├── 25.2 标的资产分析
│   ├── 25.3 协同效应评估
│   ├── 25.4 整合效果追踪
│   └── 25.5 商誉风险预警
├── 26. 竞争格局图谱 ← 新增章节
│   ├── 26.1 市场规模与增速
│   ├── 26.2 竞争者定位
│   ├── 26.3 竞争优势分析
│   └── 26.4 进入壁垒
├── 27. 战略叙事 ← 新增章节
│   ├── 27.1 公司愿景与定位
│   ├── 27.2 核心竞争优势
│   ├── 27.3 战略执行路径
│   └── 27.4 未来展望
└── 28. 全维度战略报告 ← 新增章节
    ├── 28.1 投资逻辑总结
    ├── 28.2 关键风险提示
    └── 28.3 跟踪要点
```

---

## 六、实施计划

### 6.1 P0阶段（第1-2周）

| 任务 | 负责模块 | 预计工时 |
|------|---------|---------|
| 价值链分析模块开发 | value_chain_analysis.py | 3天 |
| 价值链章节集成到report.py | report.py | 1天 |
| 收并购深度分析模块开发 | ma_deep_analysis.py | 4天 |
| MA章节集成到report.py | report.py | 1天 |
| 单元测试与调试 | - | 2天 |

### 6.2 P1阶段（第3-4周）

| 任务 | 负责模块 | 预计工时 |
|------|---------|---------|
| 战略叙事生成模块 | strategic_narrative.py | 3天 |
| 竞争格局图谱模块 | competition_map.py | 3天 |
| 章节集成与联调 | report.py | 2天 |
| AI提示词优化 | llm_config.py | 1天 |
| 端到端测试 | - | 2天 |

---

## 七、验收标准

### 7.1 P0验收

**价值链分析**：
- [ ] 能从年报提取前五供应商占比
- [ ] 能计算供应商集中度
- [ ] 能分析产能利用率
- [ ] 能识别销售模式
- [ ] 综合评分输出合理

**收并购分析**：
- [ ] 能识别所有收购交易
- [ ] 能提取交易金额和标的
- [ ] 能评估商誉风险等级
- [ ] 能生成整合效果评价

### 7.2 P1验收

**战略叙事**：
- [ ] 能生成结构化战略叙事
- [ ] 逻辑连贯，无明显矛盾
- [ ] 关键信息无遗漏

**竞争格局**：
- [ ] 能识别行业主要玩家
- [ ] 能标注市场份额
- [ ] 能生成护城河分析

---

## 八、已知限制

1. **数据依赖**：年报PDF提取质量直接影响价值链分析准确性
2. **港股/美股**：部分数据源不可用，需要fallback逻辑
3. **AI生成**：战略叙事依赖LLM质量，需持续优化提示词
4. **实时性**：年报数据为年度更新，实时性有限

---

**文档状态**：✅ 技术规格完成
**下一步**：开始P0模块开发
