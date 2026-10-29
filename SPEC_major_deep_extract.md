# SPEC: MAJOR公告全文深度分析升级

## 目标
将CRITICAL公告的深度提取逻辑扩展到MAJOR公告，实现：
- CRITICAL + MAJOR公告：全文提取 → deep_analyze_announcement综合结论
- Routine公告：保持标题分类（不变）

## 修改文件
`scripts/announcements.py`

## 修改内容

### 1. 深度提取范围扩展（原第945-999行）

**Before**:
```python
if deep_extract and data_dir and critical_list:
    # 只处理 critical_list
```

**After**:
```python
# CRITICAL + MAJOR公告统一深度提取
deep_extract_targets = critical_list[:max_critical]
# MAJOR：限制数量避免token爆炸，保留最重要的类型
major_deep = [
    ann for ann in major_list
    if any(tag in ann.get('importance_tag', '') for tag in [
        '高管变动', '股权激励', '诉讼仲裁', '监管函', '关联交易',
        '定增', '回购', '增持', '减持', '重大合同'
    ])
][:max_major]   # max_major 设为 10
deep_extract_targets.extend(major_deep)
```

### 2. 溯源范围扩展（原第1001-1018行）

**Before**:
```python
if trace_events and critical_list:
    # 只溯源 CRITICAL
```

**After**:
```python
if trace_events and (critical_list or major_list):
    # 溯源 CRITICAL + MAJOR 中重要事件类型
    for ann in list(critical_list) + list(major_list):
        tag = ann.get('importance_tag', '')
        if tag in traced_tags:
            continue
        traced_tags.add(tag)
        ...
```

## 参数调整

| 参数 | 原值 | 新值 | 说明 |
|------|------|------|------|
| max_critical | 5 | 5 | 不变 |
| max_major | - | 10 | 新增，MAJOR深挖上限 |
| max_pages (PDF) | 20 | 15 | MAJOR公告可减少页数 |

## 预期效果

| 公告类型 | 标题分类 | 正文提取 | AI深度分析 | 事件溯源 |
|---------|---------|---------|-----------|---------|
| CRITICAL | ✅ | ✅ xbrowser→PDF | ✅ | ✅ |
| **MAJOR** | ✅ | **✅ 新增** | **✅ 新增** | **✅ 新增** |
| ROUTINE | ✅ | ❌ | ❌ | ❌ |

## 影响评估
- token消耗：MAJOR×10×deep_analyze ≈ CRITICAL×5×1.5，约3倍增量
- 时间：约增加50-80%运行时间
- 输出质量：MAJOR级别的高管/股权激励/诉讼/监管/关联交易将有完整分析

## 验收标准
- [x] CRITICAL公告行为不变
- [x] MAJOR公告新增 extracted_content + deep_analysis 字段
- [x] 事件溯源覆盖MAJOR重要类型
- [x] report.py已更新MAJOR深度分析渲染