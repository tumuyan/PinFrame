# 网格视图文件名显示策略分析

## 概述

时间轴网格视图 (`TimelineGridDelegate`) 使用自定义算法处理文件名的换行和省略，以适应有限的显示空间。本文档分析其实现策略。

## 核心组件

### 文本区域计算

```
┌─────────────────────────────────┐
│          ┌─────────┐            │
│          │  图标   │            │
│          │ (icon)  │            │
│          └─────────┘            │
│  ┌─────────────────────────┐    │
│  │      文本区域            │    │
│  │   (text_rect)           │    │
│  │                         │    │
│  └─────────────────────────┘    │
└─────────────────────────────────┘

text_rect.width() = item_rect.width() - 4
text_rect.height() = item_rect.height() - icon_height - 8
```

### 两种显示模式

| 模式 | 配置 | 说明 |
|------|------|------|
| 单行模式 | `show_multiline = False` | 文本居中显示，超出时使用省略号 |
| 多行模式 | `show_multiline = True` | 文本顶对齐，支持多行换行 |

---

## 单行模式 (`_truncate_text_smartly`)

### 处理流程

```
原始文本
    │
    ▼
文本是否适合？ ───Yes──→ 直接返回原文
    │
   No
    │
    ▼
检测切片位置后缀 (如 " [0,0]")
    │
    ├─ 有切片后缀 ──→ main_text + slice_suffix
    │                    │
    │                    ▼
    │               保留 main_text 最后7字符
    │                    │
    │                    ▼
    │               格式: 前缀...后缀7字符[切片位置]
    │
    └─ 无切片后缀 ──→ 保留最后7字符
                         │
                         ▼
                    格式: 前缀...后缀7字符
```

### 示例

| 原始文本 | 可用宽度 | 处理结果 |
|----------|----------|----------|
| `abc.png` | 足够 | `abc.png` |
| `very_long_filename.jpg` | 不足 | `very_...name.jpg` |
| `sprite.png [2,3]` | 不足 | `spr...e.png [2,3]` |

### 算法细节

```python
# 从中间位置开始递减，找到最大可显示的前缀长度
prefix_len = len(main_text) // 2
while prefix_len > 0:
    truncated = main_text[:prefix_len] + "..." + main_suffix + slice_suffix
    if fits:
        return truncated
    prefix_len -= 1

# 兜底：只显示后缀
return "..." + main_suffix + slice_suffix
```

---

## 多行模式 (`_get_multiline_display_text`)

### 处理流程

```
原始文本
    │
    ▼
计算可用行数 = 可用高度 / 行高
    │
    ▼
文本是否适合单行？ ───Yes──→ 返回 [text]
    │
   No
    │
    ▼
检测切片位置后缀
    │
    ▼
分解文本:
┌─────────────────────────────────────────────┐
│ main_prefix (可分割) │ main_suffix (7字符) │ slice_suffix │
└─────────────────────────────────────────────┘
    │
    ▼
逐行处理 (共 num_lines 行)
    │
    ├─ 非最后一行 ──→ 显示 main_prefix 的一部分
    │
    └─ 最后一行 ──→ 必须包含 main_suffix + slice_suffix
```

### 行处理逻辑

#### 非最后一行

```python
# 尽可能多地显示 main_prefix
if remaining_text 适合当前行宽度:
    lines.append(remaining_text)
    remaining_text = ""
else:
    split_pos = _find_best_split_point(...)
    lines.append(remaining_text[:split_pos])
    remaining_text = remaining_text[split_pos:]
```

#### 最后一行

```python
# 必须包含 main_suffix + slice_suffix
if remaining_text 为空:
    lines.append(main_suffix + slice_suffix)
elif 全部内容适合:
    lines.append(remaining_text + main_suffix + slice_suffix)
else:
    # 截断 remaining_text 以腾出空间
    available_width = text_rect.width() - main_suffix_width - slice_width
    best_split = _find_best_split_point(remaining_text, available_width)
    lines.append(remaining_text[:best_split] + main_suffix + slice_suffix)
```

### 示例场景

**输入**: `sample_test_long_file_name.jpg [0,0]`
**可用行数**: 2
**文本区域宽度**: 154px

```
分解结果:
- main_prefix = "sample_test_long_file_n"  (20字符)
- main_suffix = "ame.jpg"                   (7字符)
- slice_suffix = " [0,0]"

第1行 (非最后一行):
- 从 main_prefix 中分割出适合宽度的部分
- 例如: "sample_test_lo" (假设适合)

第2行 (最后一行):
- 必须包含 main_suffix + slice_suffix
- 如果 remaining_text 也能放入: "ng_file_name.jpg [0,0]"
- 否则截断: "ng_fi...ame.jpg [0,0]"
```

---

## 分割点查找 (`_find_best_split_point`)

### 优先级

1. **单词边界优先**: 如果文本包含空格，优先在空格处分割
2. **字符级分割**: 没有空格时，从后向前查找最适合的字符位置

### 算法

```python
def _find_best_split_point(text, max_width):
    # 1. 空文本
    if not text:
        return 0
    
    # 2. 全部适合
    if text_width <= max_width:
        return len(text)
    
    # 3. 单词边界分割
    words = text.split(' ')
    if len(words) > 1:
        # 逐个添加单词，直到超出
        current_line = words[0]
        for word in words[1:]:
            test_line = current_line + ' ' + word
            if test_line 宽度 <= max_width:
                current_line = test_line
            else:
                return len(current_line)
        return len(current_line)
    
    # 4. 字符级分割 (从后向前)
    for i in range(len(text), 0, -1):
        if text[:i] 宽度 <= max_width:
            return i
    
    return 0  # 无法分割
```

---

## 切片位置后缀识别

### 正则表达式

```python
slice_match = re.search(r' \[\d+,\d+\]$', text)
```

### 匹配规则

- ` ` - 前导空格
- `\[` - 左方括号
- `\d+` - 一个或多个数字
- `,` - 逗号分隔符
- `\d+` - 一个或多个数字
- `\]` - 右方括号
- `$` - 字符串结尾

### 示例

| 文本 | 匹配结果 |
|------|----------|
| `sprite.png [0,0]` | ` [0,0]` |
| `image.jpg [12,5]` | ` [12,5]` |
| `normal.png` | 无匹配 |

---

## 设计原则

### 1. 保留关键信息

- **文件扩展名**: 始终保留在 `main_suffix` 中
- **切片位置**: 始终完整显示，不被省略
- **最后7字符**: 包含扩展名，确保文件类型可见

### 2. 多行模式的特殊处理

```
┌──────────────────────────────────────┐
│ 第一行: main_prefix 的部分内容        │ ← 可被截断
├──────────────────────────────────────┤
│ 最后一行: ...main_suffix + slice     │ ← 必须完整
└──────────────────────────────────────┘
```

### 3. 省略号使用

- 单行模式: `前缀...后缀`
- 多行模式: 只在必要时使用 `...`

---

## 问题分析与修复

### 问题: 多行模式下第一行后没有可见字符

**现象**:
```
[GridText Debug] First frame text info:
  - Original text: 'sample_test_long_file_name.jpg [0,0]'
  - Text rect: 154.0x36.0
  - Available lines: 2
  - [Algorithm] main_prefix='sample_test_long_file_n', main_suffix='ame.jpg'
  - [Algorithm] slice_width=32, main_suffix_width=49
  - [Algorithm] Processing line 0, is_last=False, remaining='sample_test_long_file_n'
  - [Algorithm] All remaining fits: 'sample_test_long_file_n'
  - Processed lines (1):      ← 只有1行，缺少 suffix！
      [0] 'sample_test_long_file_n' (width: 142, rect_width: 154.0)
```

**根本原因**:

当 `main_prefix` 适合第一行时，原代码执行 `break` 提前退出循环：

```python
# 原代码 (有 BUG)
if fm.horizontalAdvance(remaining_text) <= text_rect.width():
    lines.append(remaining_text)
    remaining_text = ""
    break  # ← 问题：提前退出，没有处理后续行的 suffix！
```

这导致最后一行（包含 `main_suffix + slice_suffix`）没有被添加。

**修复方案**:

移除 `break`，继续循环处理后续行：

```python
# 修复后
if fm.horizontalAdvance(remaining_text) <= text_rect.width():
    lines.append(remaining_text)
    remaining_text = ""
    # DON'T break here - continue to process remaining lines for suffix
else:
    split_pos = self._find_best_split_point(...)
    lines.append(remaining_text[:split_pos])
    remaining_text = remaining_text[split_pos:]
```

**修复后预期输出**:
```
  - Processed lines (2):
      [0] 'sample_test_long_file_n' (width: 142, rect_width: 154.0)
      [1] 'ame.jpg [0,0]' (width: 81, rect_width: 154.0)
```

**影响范围**:

此问题存在于两个分支：
1. 有 slice suffix 分支 (`main_prefix` → `main_suffix` + `slice_suffix`)
2. 无 slice suffix 分支 (`prefix` → `suffix`)

两处都已修复。

---

## 改进建议

### 1. 统一省略号策略

当前多行模式在非最后一行不添加省略号，可能导致用户误解文本已完整显示。

**建议**: 在非最后一行末尾添加 `...` 提示有更多内容。

### 2. 更智能的分割点

当前字符级分割只考虑宽度，不考虑语义。

**建议**: 考虑在 `_`、`.` 等常见分隔符处优先分割。

### 3. 边界情况处理

- 当 `main_suffix + slice_suffix` 超出宽度时，当前的降级策略是添加 `...` 省略，可考虑更明确的提示
- 当可用行数为 0 时，应直接使用单行模式

### 4. 已修复问题

- ✅ **多行模式下 suffix 丢失**: 当 `main_prefix` 适合第一行时，现在会继续处理后续行显示 suffix

---

## 相关文件

- `src/ui/timeline_grid_delegate.py` - 核心实现
- `src/ui/timeline_grid.py` - 网格视图控件
- `src/ui/timeline_grid_settings.py` - 网格设置界面
