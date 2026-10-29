# AI 首席分析师功能使用指南

## 环境安装

### 一键安装（推荐）

#### Windows 用户
```cmd
# 双击运行或在命令行执行
install_deps.bat
```

#### PowerShell 用户
```powershell
.\install_deps.ps1
```

#### 手动安装
```bash
# 进入 skill 目录
cd skills/listed-company-analysis

# 安装所有依赖
pip install -r requirements.txt
```

### 依赖已包含：
- `openai>=1.50.0 - 商汤 API 客户端
- `pandas` - 数据处理
- `requests` - HTTP 请求
- `PyMuPDF` - PDF 处理
- `akshare` - 金融数据
- `matplotlib` - 图表

---

## 功能简介

本功能使用**商汤 DeepSeek V4 Flash** 模型，按照顶级券商首席分析师的能力进行上市公司深度分析。

## 使用方法

### 基本用法

```bash
# 1. 先进行数据收集（完整分析）
python analyze.py --stock 002180 --full

# 2. 然后使用 AI 首席分析师进行深度解读
python analyze.py --stock 002180 --ai-report
```

### 一步完成（推荐）

```bash
# 一次性完成数据收集 + AI 分析
python analyze.py --stock 002180 --full --ai-report
```

### 指定分析维度

```bash
python analyze.py --stock 002180 \
  --dims multi_year_trend,valuation,governance \
  --ai-report
```

## AI 分析师能力

### 分析框架

1. **投资亮点**
   - 核心竞争优势
   - 增长驱动因素
   - 战略价值

2. **风险提示**
   - 经营风险
   - 财务风险
   - 行业风险
   - 治理风险

3. **估值判断**
   - 当前估值水平
   - 相对估值（PE/PB）
   - 绝对估值参考

4. **投资建议**
   - 评级（买入/持有/减持）
   - 目标价参考
   - 关键催化剂
   - 跟踪要点

## 配置说明

### API 配置

文件：`scripts/llm_config.py`

```python
LLM_CONFIG = {
    "provider": "sensenova",
    "model": "deepseek-v4-flash",
    "api_key": "sk-L9oSBsdCye45ES7JV39zPxlPGaG5yTm5",
    "base_url": "https://token.sensenova.cn/v1",
    "temperature": 0.3,
    "max_tokens": 8192,
}
```

### 模型选择

当前使用：`deepseek-v4-flash`

可选模型（在 `llm_config.py` 中修改）：
- `sensenova-6.7-flash-lite` - 轻量级，更快
- `deepseek-v4-flash` - 高性能，支持推理

## 输出文件

```
output/{股票代码}_{日期}/
├── report.md              # 数据分析报告
├── analyst_report.md      # AI 首席分析师报告 ← 新增
└── data/
    └── results.json       # 原始数据
```

## 示例输出

```
============================================================
🤖 AI 首席分析师分析中...
============================================================

📊 分析股票: 002180
🏢 所属行业: 半导体
⏳ 正在调用 DeepSeek V4 Flash 进行深度分析...

✅ AI 分析完成，耗时 12.3 秒

✅ 首席分析师报告已保存: output/002180_20260522/analyst_report.md
```

## 注意事项

1. **API 额度**：DeepSeek V4 Flash 每5小时150次调用限制
2. **网络连接**：需要能访问 `https://token.sensenova.cn`
3. **数据完整性**：建议先完成 `--full` 分析，确保 AI 有足够数据
4. **分析耗时**：深度分析通常需要 10-30 秒

## 故障排除

### API 调用失败

```bash
# 检查 API 配置
python -c "from scripts.llm_config import LLM_CONFIG; print(LLM_CONFIG)"

# 测试 API 连接
python -c "
from openai import OpenAI
client = OpenAI(
    base_url='https://token.sensenova.cn/v1',
    api_key='sk-L9oSBsdCye45ES7JV39zPxlPGaG5yTm5'
)
resp = client.chat.completions.create(
    model='deepseek-v4-flash',
    messages=[{'role': 'user', 'content': '你好'}]
)
print(resp.choices[0].message.content)
"
```

### 报告生成失败

1. 确保已完成数据收集（`--full`）
2. 检查 `scripts/ai_analyst.py` 是否存在
3. 查看错误日志输出

## 更新日志

- **2026-05-22**: 初始版本，集成商汤 DeepSeek V4 Flash
