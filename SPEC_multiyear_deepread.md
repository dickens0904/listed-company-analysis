# SPEC: listed-company-analysis 技能改进计划

## 背景
用户反馈：
1. skill中要增加3年的财报分析
2. 所有公告目前只是拿了个标题，所有的推测都是基于标题，并不是深度解读

## 一、3年财报分析改进

### ✅ 已完成 (2026-05-11)

#### 1.1 新增多年度对比函数
- 创建 `scripts/financials_multiyear.py` (约200行)
- 函数 `fetch_financial_multi_year` 支持获取10年+财务数据
- 函数 `format_multi_year_summary` 生成Markdown对比表格
- 趋势分析：营收/净利/毛利率/ROE趋势
- 风险识别：亏损、由盈转亏、营收大幅下滑

#### 1.2 集成到主流程
- 修改 `scripts/analyze.py` 第66-80行，在获取财务数据后自动调用多年度分析
- 修改 `scripts/report.py`，在财务报表章节后输出多年度对比
- 数据来源：东方财富API（40期财务数据，覆盖10年+）

#### 1.3 测试验证
- ✅ 002259（升达林业）测试通过
- 成功获取40期数据（2016-2026）
- 输出包含趋势分析+核心指标对比表

#### 1.4 待优化
- 扣非净利润数据缺失（API返回null，需从年报PDF补充）✅ 已添加fallback
- 资产负债率等字段缺失（需从年报PDF提取）✅ 已添加fallback

---

## 二、公告深度解读改进

### ✅ 已完成 (2026-05-11)

#### 2.1 新增深度分析函数
- 在 `scripts/announcements.py` 新增 `deep_analyze_announcement` 函数（约150行）
- 输入：标题、正文、事件类型、发布日期
- 输出：facts/intent/impact/nature/follow_up/confidence
- 意图推断：基于事件类型的11种管理意图映射
- 影响分析：基于金额规模判断（1亿+/1000万+/其他）
- 事项性质：利好/利空/中性判断
- 后续关注：基于事件类型的9种关注点映射

#### 2.2 ✅ 已集成到主流程
- 在 `fetch_announcements` 函数中添加深度分析调用（约第970行）
- CRITICAL公告自动调用 deep_analyze_announcement
- 结果存储在 ann['deep_analysis'] 字段

---

## 三、财务字段PDF补充

### ✅ 已完成 (2026-05-11)

#### 3.1 新增PDF提取章节
- 修改 `scripts/annual_extract.py`
- 新增 'financial_key_data' 章节：主要会计数据
- 新增 'balance_sheet_key' 章节：资产负债表关键数据

#### 3.2 新增财务指标提取函数
- 添加 `AnnualReportExtractor.extract_financial_metrics()` 方法
- 可提取字段：扣非净利润、资产负债率、营业收入、净利润、总资产、总负债、加权ROE
- 测试验证：920262提取成功
  - 扣非净利润: 40,680,050.87 元
  - 资产负债率: 30.29%
  - 营业收入: 600,068,310.60 元

#### 3.3 新增PDF fallback函数
- 添加 `extract_financial_from_pdf()` 函数到 `scripts/financials_multiyear.py`
- 当API数据缺失时自动从年报PDF补充
- 测试验证：920262 2025年提取成功

### 待完成
- 自动调用fallback：当API返回null时自动从PDF补充（需在主函数中进一步集成）