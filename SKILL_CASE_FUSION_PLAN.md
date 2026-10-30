# listed-company-analysis × 智数分析专家团案例 · 融合方案

> 配套文档：本方案把 WorkBuddy 官网案例《用 WorkBuddy 专家团吃透十年年报》的研究范式，
> 反哺进 `listed-company-analysis` skill，补齐其「文本语义量化 / 理论框架整合 / 多智能体分工 / 咨询报告形态」四项短板。
> 文档日期：2026-10-28。

---

## 0. 总体判断

两者是**同一目标的两套实现**，互为镜子：

| 维度 | 官网案例（智数分析专家团） | listed-company-analysis skill |
|---|---|---|
| 定位 | 通用研究范式（多智能体+双线交叉+理论骨架） | 工程化深度评论引擎 |
| 数据源 | 巨潮 PDF 爬虫 + 网页搜索（T4/T5） | **MCP 优先**（Wind/dzh/qcc/alphapai，T1） |
| 质保 | 人工抽查 3–5 个数字 | **45+ 项硬门禁**（缺口守门/数字一致性） |
| 文本分析 | **MD&A 词频/LDA/叙事强度/热力图** | 仅定向抽取（赛道曝光/营收归因） |
| 理论 | **6 大 MBA 理论 + 整合文档** | 仅波特价值链有理论味 |
| 交付 | HTML 咨询报告（指标卡+雷达图+附录） | 2000–3500 字通俗评论 |
| 形态 | 多智能体 5 角色并行 | 单 Agent 读证据包写 |

**结论**：skill 在「数据可靠性 + 质保铁律」上远超案例；案例在「文本语义量化 + 理论框架整合 + 多智能体分工 + 咨询报告形态」上领先 skill。
融合方向 = **用 skill 的基座+门禁作底座，套用案例的方法论与呈现**，形成「可复现 + 可信 + 可读」的完整研究引擎。

---

## 1. 短板清单（skill 落后案例的部分）

| # | 缺口 | 案例对应能力 | 现状 |
|---|---|---|---|
| G1 | MD&A 文本语义量化 | 词频矩阵 / LDA / 叙事强度轨迹 | skill 仅有定向抽取，无系统量化 |
| G2 | 叙事 vs 事实偏离检测 | 「叙事解耦」r=−0.275、亏损年叙事韧性 | skill 无此维度 |
| G3 | 理论框架整合 | 6 大 MBA 理论 + integration.md | skill 仅价值链零散 |
| G4 | 多智能体分工 | 编排/检索/数据科学/撰写/可视化 5 角色 | skill 单 Agent 写 |
| G5 | 咨询报告形态 | HTML 报告（指标卡+问题卡片+雷达图+附录 A–D） | skill 仅通俗评论 |
| G6 | 泛化复用模板 | 占位符提示词模板 | skill 无上手模板 |

---

## 2. 融合架构（目标态）

```
① 采集层（skill 基座 analyze.py，MCP 优先）  ── 全维度 results.json
② 文本语义层（★新增 mda_semantic.py）        ── 词频矩阵/LDA/叙事强度/偏离检测
③ 证据包层（article_brief.py）               ── 并入语义层产出，降噪不降维
④ 理论框架层（★新增 theoretical_framework.py）─ 6 大 MBA 理论打分+整合文档
⑤ Agent 撰写层（双形态）
   ├ 形态A：通俗评论文章（现状，2000–3500 字）
   └ 形态B：咨询报告（★新增 --format report，结构化+图表+附录）
⑥ 校验层（article_checklist.py 45+ 门禁）     ── 缺口守门/数字一致性（skill 强项，案例无）
⑦ 多智能体编排（★新增 专家团模式指令）        ─ 检索/数据工程/分析/可视化/成稿 5 角色
```

★ = 本次/本期需新增或强化。

---

## 3. 分阶段落地计划

### 阶段一（本次已交付 ✅）
- **G1 文本语义量化**：新增 `scripts/mda_semantic.py`（分词/词频矩阵/叙事强度/LDA/偏离检测，全部落盘）。
- **G6 泛化复用模板 + G5 咨询报告形态章节**：写入 `SKILL.md`（见「泛化复用模板」「咨询报告模式」两章）。
- 本方案文档 `SKILL_CASE_FUSION_PLAN.md`。

### 阶段二（✅ 已交付）
- **G2 偏离检测并入证据包**：`article_brief.py` 读取 `mda_semantic_out/narrative_vs_fact.json`，在证据包加 `narrative_vs_fact` 维度；`article_checklist.py` 加 J 组「叙事解耦守门」（偏离结论须有 r 值与年序列支撑，不得凭印象写"叙事与事实背离"）。✅
- **G5 形态B 落地**：新增 `scripts/report_advisory.py`，消费 evidence_pack + mda_semantic_out/* + theoretical_framework_out/*，离线生成单文件 HTML 咨询报告（执行摘要+6 指标卡+六理论整合+雷达图+问题卡片+战略建议+叙事轨迹/词频热力图+附录 A–D），中性学术配色；SKILL.md 形态 B 触发方式已更新。✅

### 阶段三（深化 ✅ 2026-10-28 已交付）
- **G3 理论框架层**：新增 `scripts/theoretical_framework.py`，实现动态能力/RBV·VRIO/波特价值链/数字化成熟度/平台战略与网络效应/TAM 六框架的「维度→指标→打分」映射，产出 `theoretical_framework.json` + `theoretical_framework_integration.md`（每框架附实证数据，可用维度<2 整体 data_gap）。并**并入证据包**：`article_brief.py` 新增 `_load_theoretical_framework()` 读 `theoretical_framework_out/theoretical_framework.json` 进 `evidence.theoretical_framework`；`article_checklist.py` 新增 **K 组「理论框架守门」**（引用某理论评级须有六维打分支撑，引用 data_gap 框架当结论直接 FAIL）。
- **G4 专家团模式**：`SKILL.md` 新增「🤝 专家团模式」章节（5 角色 + 触发方式 + 执行次序 + 角色纪律）；新增 `scripts/orchestrate_expert_team.py`，产出 5 角色任务清单（manifest JSON + dispatch markdown），**不另搭 LLM API**，由本会话 Agent 逐角色执行、基座与门禁不变。
- **反哺案例**：新增 `CASE_ENHANCEMENT_PATCH.md`，把 skill 的 45+ 门禁、MCP 优先数据源、`data_gap` 缺口腔体提炼为「案例增强补丁」三道护栏（门禁替代人工抽查 / MCP 优先压降二手源 / 缺口不编结论），回帖到案例讨论（案例当前只"人工抽查 3–5 个数字"，质保最弱）。

阶段三验证：
- `theoretical_framework.py` 对样例财务+MD&A 跑通，6 框架中 4 个评出整体分、2 个（平台战略/TAM）因外部维度缺失诚实 data_gap；`_load_theoretical_framework` 与 K 组门禁单测通过（引用 data_gap 框架→FAIL，引用已评分框架→PASS）。
- `orchestrate_expert_team.py` 跑通，产出 5 角色 + 6 步顺序 + 5 条门禁。
- 全部模块 `py_compile` 通过；已同步到本机活体 skill（`C:/Users/dicke/.workbuddy/skills/listed-company-analysis`，跨机器通配）。

---

## 4. 模块接口约定（mda_semantic.py）

输入（三选一）：
- `python scripts/mda_semantic.py 2020.pdf 2021.pdf --years 2020,2021`
- `python scripts/mda_semantic.py --corpus ./pdfs --years 2019,2020,2021`
- `python scripts/mda_semantic.py --mdaa-json mdaa_by_year.json`

可选：`--lexicon digital_transform.json`（主题词典）、`--financial-json financials.json`（财务年序列，触发偏离检测）、`--lda 4`、`--no-lda`、`--output dir`

输出（落盘）：
- `word_freq_matrix.csv` 词频矩阵（词 × 年）
- `narrative_intensity.json` 叙事强度轨迹（密度/千词，按年×主题）
- `lda_topics.json` LDA 主题（sklearn 可用时；否则 `data_gap` 显式标注）
- `narrative_vs_fact.json` 叙事 vs 事实偏离（Pearson r，需 `--financial-json`）
- `mda_semantic_report.md` / `mda_semantic_result.json` 摘要与状态

纪律：不静默异常（降级进 `result['errors']`）；缺口不编结论（年数<3 或指标缺失标 `data_gap`）；全部中间计算落盘可复算。

---

## 5. 验收标准（融合后）

- [x] `mda_semantic.py` 对 3+ 年 MD&A 可跑通，产出 4 类文件，重跑一致
- [x] 偏离检测对「叙事强度↔研发投入」能复现案例式 r≈−0.3 量级（解耦信号）
- [x] `article_checklist.py` 新增 J 组后，旧稿含"叙事背离"无数据支撑必须 FAIL
- [x] 咨询报告形态含指标卡+雷达图+附录 A–D，离线可开（`report_advisory.py` 端到端验证通过）
- [x] 理论框架层每框架有实证数据，产出 `theoretical_framework_integration.md`
- [x] 专家团模式 5 角色编排器 `orchestrate_expert_team.py` 产出任务清单
- [x] 反哺案例补丁 `CASE_ENHANCEMENT_PATCH.md` 已写
- [ ] 泛化复用模板可套用到「数字化转型/ESG/运营效率」等至少 3 类主题

---

## 6. 风险与边界

- **分词质量**：jieba 缺失时正则 2-gram 降级，仅作线索，客户材料禁用（仿 skill 对 `--auto` 规则的红标纪律）。
- **LDA 稳定性**：小语料（<5 年）主题易抖；sklearn 缺失必须显式 data_gap，不得用随机种子伪装确定。
- **偏离检测误导**：Pearson 只测线性相关，叙事与事实可能非线性；结论须配代表性原文句，不单靠 r。
- **合规**：文本挖掘指标（叙事强度/数字化投入估算）非官方口径，引用前须与年报原文核对（同案例「安全与限制」）。

---

## 7. 跨机器路径解析（🔴 通配，勿硬编码用户名）

⚠️ **踩坑记录**：记忆里曾写活体路径 `C:\Users\Administrator\.workbuddy\skills\listed-company-analysis`，
但本机实际账号是 **dicke**（`Administrator` 用户不存在）。硬编码用户名会让同步脚本在
换机器/换账号时直接失效。所有涉及本机 skill 目录的代码与脚本必须**通配**。

### 通配约定（新增 `scripts/skill_path.py`）
```python
from skill_path import resolve_skill_root
root = resolve_skill_root('listed-company-analysis')
# 解析优先级：
#   1. 环境变量 WORKBUDDY_SKILLS（用户显式指定）→ $WORKBUDDY_SKILLS/listed-company-analysis
#   2. 否则 os.path.expanduser('~/.workbuddy/skills')（Windows 自动展开为
#      %USERPROFILE%\.workbuddy\skills，不依赖具体用户名）
```

### 增量同步回本机（工作区副本 → 本机活体，保持单一事实源）
```bash
# 从 skill 根目录运行；排除 .git / 本地凭据 / 缓存 / 运行产物
rsync -a \
  --exclude='.git' --exclude='.tushare_token' --exclude='.em_api_key' \
  --exclude='__pycache__' --exclude='output' \
  "E:/BaiduSyncdisk/财中金控/项目库/龙头计划/listed-company-analysis/" \
  "$(python scripts/skill_path.py)/"
# 注：$(python scripts/skill_path.py) 输出本机活体根，跨机器无需改路径
```

### 反向（本机活体 → 龙头计划 zip）
打包仍走活体根目录 `package_skill.py`（git archive 覆盖目标 zip），与用户名无关。

