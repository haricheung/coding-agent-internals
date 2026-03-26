#!/bin/bash
# ==========================================================================
# Demo 2: tool_use 协议拆解 —— curl 命令对
#
# 本脚本用于课程 Demo 2（10:00 tool calling 环节），
# 通过两个 curl 请求让观众直观看到 tool calling 的本质：
#   请求 1: 普通对话（无工具）→ 模型只能「说」
#   请求 2: 带工具定义 → 模型可以「做」（生成 tool_use 请求）
#
# 使用前提：
#   1. 启动 model_server: python model_server.py <model_path>
#   2. 确认服务健康: curl http://localhost:9981/health
#
# 使用方式：
#   可以整体运行: bash demo2_curl_commands.sh
#   也可以逐个复制到终端演示（推荐，方便讲解停顿）
# ==========================================================================

SERVER="http://localhost:9981"

echo "============================================"
echo "Demo 2: tool_use 协议拆解"
echo "============================================"

# --------------------------------------------------------------------------
# 健康检查：确认 model_server 已启动
# --------------------------------------------------------------------------
echo ""
echo ">>> Step 0: 健康检查"
echo "curl $SERVER/health"
echo ""
curl -s "$SERVER/health" | python3 -m json.tool
echo ""

# --------------------------------------------------------------------------
# 请求 1: 普通对话（无工具定义）
# --------------------------------------------------------------------------
# 观众观察点：
#   - 请求中没有 tools 字段
#   - 模型只能用文字回答，无法实际读取文件
#   - 这就是「开环」—— 模型只能「说」不能「做」
# --------------------------------------------------------------------------
echo "============================================"
echo ">>> 请求 1: 普通对话（无工具）"
echo "    观察：模型只能用文字描述，无法操作文件"
echo "============================================"
echo ""

curl -N "$SERVER/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant."},
      {"role": "user", "content": "Read the file /tmp/test.py and tell me what it does."}
    ],
    "max_new_tokens": 256,
    "temperature": 0.7
  }'

echo ""
echo ""

# --------------------------------------------------------------------------
# 请求 2: 带工具定义的对话
# --------------------------------------------------------------------------
# 观众观察点：
#   - 请求中多了 tools 字段，包含 Read 工具的 JSON Schema 定义
#   - 模型生成 <tool_call> 标签包裹的 JSON（而非文字描述）
#   - response 中出现 tool_use content block 和 stop_reason: "tool_use"
#   - 这就是「闭环」—— 模型可以「做」，客户端执行后再回传结果
#
# 教学要点：
#   tool calling 不是什么 tokenizer 魔法，就是：
#   1. 请求中带上工具的 JSON Schema（像 API 文档一样）
#   2. 模型生成调用请求（像写 API 调用代码一样）
#   3. 客户端解析、执行、回传结果（像 API 网关一样）
# --------------------------------------------------------------------------
echo "============================================"
echo ">>> 请求 2: 带工具定义（有 Read 工具）"
echo "    观察：模型生成 tool_use 请求，而非文字描述"
echo "============================================"
echo ""

curl -N "$SERVER/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "tools": [
      {
        "name": "Read",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "input_schema": {
          "type": "object",
          "properties": {
            "file_path": {
              "type": "string",
              "description": "The absolute path to the file to read"
            }
          },
          "required": ["file_path"]
        }
      }
    ],
    "messages": [
      {"role": "system", "content": "You are a helpful coding assistant. Use tools to interact with the filesystem."},
      {"role": "user", "content": "Read the file /tmp/test.py and tell me what it does."}
    ],
    "max_new_tokens": 256,
    "temperature": 0.7
  }'

echo ""
echo ""
echo "============================================"
echo "Demo 2 完成"
echo ""
echo "对比两个请求的 response："
echo "  请求 1: stop_reason='end_turn', 纯文本回答"
echo "  请求 2: stop_reason='tool_use', 包含 tool_use block"
echo ""
echo "这就是 tool calling 的全部秘密："
echo "  传了工具定义 → 模型知道可以调工具 → 生成结构化调用请求"
echo "  没传工具定义 → 模型只能用文字回答 → 无法与外部世界交互"
echo "============================================"
