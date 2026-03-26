# Demo 4: ACI 信息粒度控制

## 演示目标

通过对同一个 442 行 Python 文件使用不同的读取策略，**实际测量**每种策略的 token 消耗，
直观展示为什么「上下文窗口是稀缺资源」，以及为什么粗粒度 -> 细粒度的漏斗策略不是可选优化，而是 7B 模型在有限上下文下能正常工作的**必要条件**。

## 核心问题：上下文窗口是稀缺资源

一个 7B 模型的上下文窗口通常为 8K-32K tokens。看起来很多？算一下：

- System prompt（含工具定义 + 文件树）：~2000 tokens
- 对话历史（多轮交互累积）：~1000-3000 tokens
- **留给工具输出的空间：只剩 3000-5000 tokens**

如果一次 `cat` 操作就塞入 3600+ tokens，上下文窗口几乎用完。
模型的注意力被大量无关代码淹没，推理质量会**显著下降**。

---

## 实验记录

目标文件：`mvp/tests/large_module.py`（442 行，14629 字符的 Python 数据处理模块）

任务：找到并定位文件中故意留下的 BUG（第 199 行，normalize 函数的除以零错误）

---

### 实验 1: Bash("cat large_module.py") -- 全文输出

```
命令/工具调用: Bash("cat large_module.py")
输出大小: 14629 字符 ≈ 3657 tokens
输出行数: 442 行
```

输出内容:
```
"""
数据处理工具模块 —— Demo 4 演示用大文件

本文件是一个 200+ 行的 Python 模块，用于课程 Demo 4（ACI 信息粒度控制）的演示。
Demo 4 的目的是对比两种读取策略：
...                              （省略 430+ 行）
    except ZeroDivisionError:
        print("  BUG: ZeroDivisionError when all values are the same!")
```

分析: 一次性把 442 行全部塞入上下文，消耗 ~3657 tokens。模型需要从这一大片文本中"大海捞针"找到第 199 行的 BUG。对于 7B 模型来说，注意力被大量无关的 DataRecord、DataValidator、StatisticsCalculator 代码分散，定位效率极低。而且没有行号，后续 Edit 修复时模型无法精确引用位置。

---

### 实验 2: Bash("wc -l large_module.py") -- 先探测文件规模

```
命令/工具调用: Bash("wc -l large_module.py")
输出大小: 55 字符 ≈ 14 tokens
输出行数: 1 行
```

输出内容:
```
442 /root/work/qlzhang/code/coding-agent-internals/mvp/tests/large_module.py
```

分析: 仅 14 tokens 就获知文件有 442 行。这是最廉价的信息获取——知道了"这个文件不小，不应该 cat 全文"，为后续的分页策略提供决策依据。聪明的 Agent 会在 Read 之前先 wc -l 探测。

---

### 实验 3: Read(file) -- 全文读取（带行号）

```
命令/工具调用: Read(file_path="large_module.py")
输出大小: 15589 字符 ≈ 3897 tokens
输出行数: 444 行（含末尾元信息行）
```

输出内容:
```
  1 | """
  2 | 数据处理工具模块 —— Demo 4 演示用大文件
  3 |
  4 | 本文件是一个 200+ 行的 Python 模块，...
  5 | Demo 4 的目的是对比两种读取策略：
...                              （省略 430+ 行）
441 |     except ZeroDivisionError:
442 |         print("  BUG: ZeroDivisionError when all values are the same!")

[442 lines total]
```

分析: 比 cat 还多消耗 240 tokens（行号前缀的开销），总计 ~3897 tokens。虽然行号有助于后续 Edit 操作，但全文读取的根本问题没解决——上下文被占满，模型推理质量下降。全文 Read 只适合小文件（<50 行）。

---

### 实验 4: Read(file, offset=0, limit=20) -- 只看文件头部

```
命令/工具调用: Read(file_path="large_module.py", offset=0, limit=20)
输出大小: 609 字符 ≈ 152 tokens
输出行数: 22 行（含末尾元信息行）
```

输出内容:
```
  1 | """
  2 | 数据处理工具模块 —— Demo 4 演示用大文件
  3 |
  4 | 本文件是一个 200+ 行的 Python 模块，...
  5 | Demo 4 的目的是对比两种读取策略：
  6 | - 策略一：Bash("cat large_module.py") 一次性读入全文（上下文爆炸）
  7 | - 策略二：Read(file, offset=X, limit=Y) 按需精读（保护 token 预算）
...
 18 | - 故意留下的 bug（第 ~180 行附近的边界条件错误）
 19 | """
 20 |

[Showing lines 1-20 of 442 total]
```

分析: 仅 152 tokens！只占全文的 3.9%。但已经获得了关键信息：模块结构概览（4 个类 + 1 个 BUG 在第 ~180 行附近）。元信息 `[Showing lines 1-20 of 442 total]` 告诉模型文件还有 422 行没读，引导它按需继续。

---

### 实验 5: Grep("BUG|bug|TODO", file) -- 定位关键位置

```
命令/工具调用: Grep(pattern="BUG|bug|TODO", path="large_module.py")
输出大小: 634 字符 ≈ 159 tokens
输出行数: 7 行（5 条匹配 + 统计行）
```

输出内容:
```
large_module.py:18:  - 故意留下的 bug（第 ~180 行附近的边界条件错误）
large_module.py:199:         # BUG: 当所有值相同时，max_val == min_val，除以零！
large_module.py:200:         # 这是故意留下的 bug，用于 Demo 3 的 bug 修复演示
large_module.py:433:     # 测试 normalize 的 bug（当所有值相同时）
large_module.py:442:         print("  BUG: ZeroDivisionError when all values are the same!")

[5 matches found]
```

分析: 仅 159 tokens，直接命中目标！5 条匹配结果精准定位了 BUG 在第 199 行。Agent 现在知道应该 Read(offset=195, limit=15) 去精读上下文。这就是漏斗策略的威力——从 442 行 -> 5 行，信息密度提升 88 倍。

---

### 实验 6: Read(file, offset=195, limit=15) -- 精确读取 BUG 所在区域

```
命令/工具调用: Read(file_path="large_module.py", offset=195, limit=15)
输出大小: 654 字符 ≈ 164 tokens
输出行数: 17 行（含末尾元信息行）
```

输出内容:
```
196 |         min_val = min(values)
197 |         max_val = max(values)
198 |
199 |         # BUG: 当所有值相同时，max_val == min_val，除以零！
200 |         # 这是故意留下的 bug，用于 Demo 3 的 bug 修复演示
201 |         range_val = max_val - min_val
202 |
203 |         new_records = []
204 |         for record in dataset.records:
205 |             if record.is_valid():
206 |                 normalized = (record.value - min_val) / range_val
207 |                 new_records.append(DataRecord(
208 |                     value=normalized,
209 |                     timestamp=record.timestamp,
210 |                     label=record.label,

[Showing lines 196-210 of 442 total]
```

分析: 仅 164 tokens，BUG 一目了然！第 201 行 `range_val = max_val - min_val`，当所有值相同时 `range_val = 0`，第 206 行 `/ range_val` 触发除以零。模型现在有足够的上下文来构造 Edit 调用（包含 old_string 的唯一性上下文），而且只消耗了全文 4.2% 的 tokens。

---

### 实验 7: _scan_files() -- 文件树快照（50 行上限）

```
命令/工具调用: client._scan_files()（内嵌在 system prompt 中）
输出大小: 419 字符 ≈ 105 tokens
输出行数: 26 行
```

输出内容:
```
mvp/
  ISSUES.md
  README.md
  requirements.txt
  src/
    adapter.py
    agent_tool.py
    client.py
    main.py
    model_server.py
    parser.py
    task_tools.py
    tools.py
  tests/
    buggy_code.py
    buggy_code.py.bak
    fixed_code.py
    large_module.py
    test_all.py
    test_components.py
    test_day1.py
    test_day1_features.py
    test_qwen3.py
    test_simple.py
  demo/
    demo2_curl_commands.sh
```

分析: 仅 105 tokens 就给了模型完整的项目全景。模型看到 `tests/large_module.py` 就知道目标文件在哪里，看到 `src/tools.py` 就知道工具定义在哪里。50 行上限是精心设计的——对中小项目刚好够用，对大项目也不会撑爆上下文。

---

## Token 消耗对比表

| 策略 | 输出字符数 | 估算 tokens | 占全文% | 信息密度 |
|------|-----------|------------|---------|---------|
| Bash("cat") 全文 | 14,629 | ~3,657 | 100% | 极低：442 行中只有 5 行相关 |
| Read() 全文 | 15,589 | ~3,897 | 106.6% | 极低：比 cat 还多（行号开销） |
| Read(offset=0, limit=20) 头部 | 609 | ~152 | 4.2% | 中等：获得模块结构概览 |
| Grep("BUG\|bug\|TODO") | 634 | ~159 | 4.3% | **极高：5 条精准命中** |
| Read(offset=195, limit=15) 精读 | 654 | ~164 | 4.5% | **极高：BUG 完整上下文** |
| _scan_files() 文件树 | 419 | ~105 | 2.9% | 高：项目全景定位 |
| wc -l 探测 | 55 | ~14 | 0.4% | 高：决策依据 |

**关键对比**：

- 全文读取：~3,900 tokens，信息密度 ≈ 5/442 = **1.1%**
- 漏斗策略（Grep + 精读）：~323 tokens，信息密度 ≈ 5/22 = **22.7%**
- **效率提升：token 节省 92%，信息密度提升 20 倍**

---

## 漏斗策略图

```
   ┌─────────────────────────────────────────────────┐
   │                                                 │
   │  Level 0: 文件树快照                             │
   │  _scan_files() → 26 行, ~105 tokens             │
   │  "项目里有哪些文件？目标在 tests/large_module.py" │
   │                                                 │
   └──────────────────────┬──────────────────────────┘
                          │  知道目标文件
                          ▼
   ┌─────────────────────────────────────────────────┐
   │                                                 │
   │  Level 1: Grep 定位                              │
   │  Grep("BUG|bug", file) → 5 行, ~159 tokens      │
   │  "BUG 在第 199 行，normalize 函数的除零错误"      │
   │                                                 │
   └──────────────────────┬──────────────────────────┘
                          │  知道精确行号
                          ▼
   ┌─────────────────────────────────────────────────┐
   │                                                 │
   │  Level 2: Read 精读                              │
   │  Read(offset=195, limit=15) → 15 行, ~164 tokens │
   │  "range_val = max_val - min_val 在第 201 行，     │
   │   除以 range_val 在第 206 行"                     │
   │                                                 │
   └──────────────────────┬──────────────────────────┘
                          │  有足够上下文
                          ▼
   ┌─────────────────────────────────────────────────┐
   │                                                 │
   │  Level 3: Edit 修复                              │
   │  Edit(old_string="range_val = max_val - min_val",│
   │       new_string="range_val = max_val - min_val  │
   │                   if range_val == 0: ...")        │
   │  精确修复，无需读写全文                            │
   │                                                 │
   └─────────────────────────────────────────────────┘

   总消耗: 105 + 159 + 164 ≈ 428 tokens（全文的 11%）
   vs 全文 cat: 3657 tokens
```

---

## 教学要点

### 1. Read 的 offset/limit 就是 ACI 粒度控制

```python
# 粗粒度：全文读取（小文件可以，大文件不行）
Read(file_path="large_module.py")                    # → 3897 tokens

# 细粒度：按需精读（永远推荐）
Read(file_path="large_module.py", offset=195, limit=15)  # → 164 tokens
```

`offset` 和 `limit` 不是"可选参数"，它们是 ACI 的**核心控制手段**。没有它们，7B 模型在 8K 上下文窗口下几乎无法处理超过 100 行的文件。

### 2. Grep 的 head_limit 就是 ACI 输出控制

```python
# 不限制：在大项目搜 "import" 可能返回 5000 行
Grep(pattern="import", path="/project/src")              # → 上下文爆炸

# 限制输出：默认 50 行，可进一步缩小
Grep(pattern="BUG|bug|TODO", path="large_module.py")     # → 5 行精准命中
```

`head_limit` 默认 50 是精心设计的——超出时返回 `[N more matches not shown]`，引导模型缩小搜索范围。

### 3. 50 行文件树是「刚好够定位」的粗粒度信息

```python
def _scan_files(self) -> str:
    ...
    return '\n'.join(lines[:50])  # 硬编码 50 行上限
```

为什么是 50 行？
- 太少（10 行）：模型看不到项目结构，不知道文件在哪
- 太多（500 行）：大项目的文件树本身就占 1000+ tokens
- 50 行是中小项目的"甜蜜点"——~100 tokens 换来完整的项目导航能力

### 4. 这些不是可选优化，是必要条件

对于上下文窗口充裕的大模型（如 Claude 200K），全文 cat 可能"还行"。
但对于 7B 模型（8K-32K 上下文）：

| 场景 | 全文 cat | 漏斗策略 |
|------|---------|---------|
| 442 行文件 | 3657 tokens，占 8K 的 **46%** | 428 tokens，占 8K 的 **5.4%** |
| System prompt | + 2000 tokens | + 2000 tokens |
| 对话历史 | + 2000 tokens | + 2000 tokens |
| **剩余推理空间** | **仅 343 tokens** | **3572 tokens** |

全文 cat 后模型只剩 343 tokens 用于推理——连一段完整的 Edit 调用都写不完。
漏斗策略保留了 3572 tokens，模型有充足的空间思考、生成工具调用、完成修复。

**结论：ACI 信息粒度控制 = 让小模型做大模型的事。**

---

## 实验环境

- 目标文件: `mvp/tests/large_module.py`（442 行，14629 字节）
- 工具实现: `mvp/src/tools.py`（ReadTool, GrepTool）
- 客户端: `mvp/src/client.py`（_scan_files, get_system_prompt）
- Token 估算: 字符数 / 4（粗估，实际因中英文混合会有偏差）
- 实验日期: 2026-03-26
