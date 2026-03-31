# Coding Agent MVP

基于 Qwen 模型的 AI 编程 Agent，实现 Claude Code 协议适配 + ReAct 工具循环。

## 架构

```
Client/Browser ──Claude格式──→ Model Server ──OpenAI格式──→ vLLM serve
                              (协议适配层)                 (GPU 推理引擎)
                              port 9981                    port 8000
```

- **vLLM serve**: GPU 推理，AsyncLLMEngine + continuous batching，支持并发
- **Model Server**: 协议转换（Claude ↔ OpenAI）、工具执行、Demo UI、Dashboard
- **Client**: CLI 交互，完整 ReAct 循环（Read/Write/Edit/Grep/Bash + Agent Team）

## 快速启动

### 环境准备

```bash
cd mvp
pip install -r requirements.txt
pip install vllm    # 需要 CUDA
```

### 一键启动（推荐）

```bash
cd mvp/src

# 传入模型路径，自动检测空闲 GPU、估算显存、启动 vLLM + 适配层
python model_server.py /path/to/model

# 例：
python model_server.py /root/work/qlzhang/code/models/Qwen2.5-Coder-7B-Instruct
python model_server.py /root/work/qlzhang/code/models/Qwen3-Coder-30B-A3B-Instruct
python model_server.py /root/work/qlzhang/code/models/Qwen2.5-Coder-32B-Instruct
```

自动完成：
1. 读取模型 config，估算显存需求（权重大小 → TP 数 + enforce-eager + max-model-len）
2. `nvidia-smi` 检测空闲 GPU
3. 启动 vLLM serve 子进程
4. 轮询等待 vLLM ready
5. 启动协议适配层

Ctrl+C 自动清理 vLLM 子进程。

### 手动指定 GPU

```bash
python model_server.py /path/to/model --gpu 5,6
```

### 连接已有 vLLM

```bash
# 如果已经手动启动了 vLLM
python model_server.py --vllm-url http://localhost:8000
```

### 使用

```bash
# CLI 交互（ReAct Agent）
python mvp/src/main.py <工作目录>
# 例: python mvp/src/main.py mvp/tests

# Web 演示（Chat vs Agent 对比）
# 浏览器打开 http://localhost:9981/demo

# Dashboard（测试结果 + Agent 轨迹）
# 浏览器打开 http://localhost:9981/dashboard

# 健康检查
curl http://localhost:9981/health
```

## 模型显存参考

| 模型 | 类型 | 权重大小 | 自动配置（单卡 80G A800） |
|------|------|---------|--------------------------|
| Qwen2.5-Coder-7B | Dense | ~14 GB | 默认参数，全 context |
| Qwen3-Coder-30B-A3B | MoE (128 experts, 3B active) | ~58 GB | enforce-eager, max_len=16K |
| Qwen2.5-Coder-32B | Dense | ~62 GB | enforce-eager, max_len=16K |

> **MoE 说明**: Qwen3-30B-A3B 每 token 只激活 3B 参数（推理快），但需要加载全部 128 个 expert（~58GB）到显存。

## 同时跑多个模型

用不同端口启动多个实例：

```bash
# GPU 自动分配（分别占用不同的空闲卡）
python model_server.py /path/to/7B --port 9981 --vllm-port 8000
python model_server.py /path/to/30B --port 9982 --vllm-port 8001
```

Demo UI 中点 "Edit" 可添加多个 model server 地址，方便演示切换。

## 文件结构

```
mvp/src/
├── model_server.py   # 一键启动 + 协议适配层 + Web 服务
├── adapter.py        # Claude ↔ OpenAI/Qwen 协议转换
├── parser.py         # 鲁棒工具调用解析（fallback for vLLM）
├── client.py         # CLI Agent 客户端（ReAct 循环）
├── main.py           # CLI 入口
├── agent_tool.py     # Agent/SendMessage 子 Agent 工具
├── team_tools.py     # TeamCreate/TaskCreate/TaskUpdate 等团队工具
├── trajectory.py     # Agent 轨迹记录
├── demo.html         # Chat vs Agent 演示页面
└── dashboard.html    # 测试结果仪表盘
```
