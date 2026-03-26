#!/usr/bin/env python3
"""
全量集成测试套件 —— MVP 所有组件的回归保障

本测试文件覆盖 MVP 的全部功能模块，是每次代码变更后的回归测试基线。
运行方式：cd mvp/src && python ../tests/test_all.py

测试覆盖范围（对应 Day 1-4 交付物）：

    Day 1-2 基础工具层：
    - TestReadTool:   文件读取 + 分页 + 行号 + 边界情况
    - TestWriteTool:  文件写入 + 目录创建 + 覆盖
    - TestEditTool:   精确替换 + 唯一性检查 + 错误处理
    - TestGrepTool:   正则搜索 + 递归 + head_limit + 跳过规则
    - TestBashTool:   命令执行 + 超时 + 工作目录

    Day 2 协议层：
    - TestParser:     三策略解析（XML / 代码块 / 裸 JSON）+ 双格式兼容
    - TestAdapter:    Claude ↔ Qwen 双向转换 + 消息转换 + 响应转换

    Day 3 任务管理：
    - TestTaskStore:  CRUD + 状态机 + 线程安全 + 重置
    - TestTaskTools:  TaskCreate / TaskUpdate / TaskList 工具行为

    Day 4 Agent Team：
    - TestAgentTool:  工具定义 + 参数验证（不测实际推理，需要 model_server）

    集成层：
    - TestClientIntegration:  工具注册 + 工具定义格式 + 全链路兼容性

测试设计原则：
    1. 每个 test 方法测试一个独立行为，命名为 test_<行为>
    2. 使用 tmpdir 隔离文件系统操作，测试结束后自动清理
    3. 不依赖 model_server（纯单元测试），Agent 工具只验证接口不验证推理
    4. 测试用例按「正常路径 → 边界情况 → 错误处理」顺序组织
"""

import os
import sys
import unittest
import tempfile
import shutil
import threading

# 确保能导入 src 目录下的模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# ===========================================================================
# Day 1-2: 基础工具测试
# ===========================================================================

class TestReadTool(unittest.TestCase):
    """
    Read 工具测试：文件读取 + 分页 + 行号。

    测试场景覆盖：
    - 读取完整文件（最常见场景）
    - 使用 offset/limit 分页（大文件 ACI 控制）
    - 行号格式正确性（模型依赖行号做定位）
    - 元信息正确性（总行数、显示范围）
    - 边界情况（空文件、offset 超出范围、文件不存在）
    """

    def setUp(self):
        """创建临时目录和测试文件。"""
        self.tmpdir = tempfile.mkdtemp()
        # 创建 100 行测试文件
        self.test_file = os.path.join(self.tmpdir, 'test.py')
        with open(self.test_file, 'w') as f:
            for i in range(100):
                f.write(f'line_{i} = {i}\n')
        # 创建空文件
        self.empty_file = os.path.join(self.tmpdir, 'empty.py')
        with open(self.empty_file, 'w') as f:
            pass

    def tearDown(self):
        """清理临时目录。"""
        shutil.rmtree(self.tmpdir)

    def test_read_full_file(self):
        """读取完整文件：返回所有行 + 行号 + 总行数。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path=self.test_file)
        # 第一行应该带行号
        self.assertIn('  1 | line_0 = 0', result)
        # 最后一行
        self.assertIn('100 | line_99 = 99', result)
        # 总行数信息
        self.assertIn('100 lines total', result)

    def test_read_with_offset_and_limit(self):
        """分页读取：offset=10, limit=5 应返回第 11-15 行。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path=self.test_file, offset=10, limit=5)
        self.assertIn('11 | line_10 = 10', result)
        self.assertIn('15 | line_14 = 14', result)
        # 不应包含第 16 行
        self.assertNotIn('16 |', result)
        # 范围信息
        self.assertIn('Showing lines 11-15 of 100', result)

    def test_read_offset_only(self):
        """只传 offset 不传 limit：从 offset 读到文件末尾。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path=self.test_file, offset=95)
        self.assertIn('96 | line_95 = 95', result)
        self.assertIn('100 | line_99 = 99', result)
        self.assertIn('Showing lines 96-100 of 100', result)

    def test_read_limit_only(self):
        """只传 limit 不传 offset：从头读 limit 行。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path=self.test_file, limit=3)
        self.assertIn('1 | line_0 = 0', result)
        self.assertIn('3 | line_2 = 2', result)
        self.assertNotIn('4 |', result)

    def test_read_offset_past_end(self):
        """offset 超出文件范围：返回空内容 + 范围信息。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path=self.test_file, offset=200, limit=10)
        self.assertIn('Showing lines', result)

    def test_read_empty_file(self):
        """读取空文件：返回 0 lines total。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path=self.empty_file)
        self.assertIn('0 lines total', result)

    def test_read_file_not_found(self):
        """文件不存在：返回 Error 开头的错误信息。"""
        from tools import ReadTool
        tool = ReadTool()
        result = tool.execute(file_path='/nonexistent/file.py')
        self.assertTrue(result.startswith('Error'))
        self.assertIn('not found', result)


class TestWriteTool(unittest.TestCase):
    """Write 工具测试：文件写入 + 目录创建。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_write_new_file(self):
        """写入新文件：文件应被创建，内容正确。"""
        from tools import WriteTool
        tool = WriteTool()
        path = os.path.join(self.tmpdir, 'new.py')
        result = tool.execute(file_path=path, content='print("hello")\n')
        self.assertIn('Successfully', result)
        with open(path) as f:
            self.assertEqual(f.read(), 'print("hello")\n')

    def test_write_creates_parent_dirs(self):
        """写入嵌套路径：父目录应被自动创建。"""
        from tools import WriteTool
        tool = WriteTool()
        path = os.path.join(self.tmpdir, 'a', 'b', 'c', 'deep.py')
        result = tool.execute(file_path=path, content='x = 1')
        self.assertIn('Successfully', result)
        self.assertTrue(os.path.exists(path))

    def test_write_overwrites_existing(self):
        """覆盖已有文件：原内容被替换。"""
        from tools import WriteTool
        tool = WriteTool()
        path = os.path.join(self.tmpdir, 'existing.py')
        with open(path, 'w') as f:
            f.write('old content')
        tool.execute(file_path=path, content='new content')
        with open(path) as f:
            self.assertEqual(f.read(), 'new content')


class TestEditTool(unittest.TestCase):
    """
    Edit 工具测试：精确替换 + 唯一性检查。

    唯一性检查是 Edit 工具最重要的安全特性，
    这里重点测试三种情况：唯一匹配、不存在、多次匹配。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.tmpdir, 'code.py')
        with open(self.test_file, 'w') as f:
            f.write(
                'def calculate(x, y):\n'
                '    result = x + y  # addition\n'
                '    return result\n'
                '\n'
                'def validate(data):\n'
                '    if data is None:\n'
                '        return False\n'
                '    return True\n'
            )

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_edit_unique_match(self):
        """唯一匹配：正常替换，文件内容更新。"""
        from tools import EditTool
        tool = EditTool()
        result = tool.execute(
            file_path=self.test_file,
            old_string='result = x + y  # addition',
            new_string='result = x * y  # multiplication'
        )
        self.assertIn('Successfully', result)
        with open(self.test_file) as f:
            content = f.read()
            self.assertIn('x * y', content)
            self.assertNotIn('x + y', content)

    def test_edit_preserves_other_content(self):
        """替换不影响其他内容。"""
        from tools import EditTool
        tool = EditTool()
        tool.execute(
            file_path=self.test_file,
            old_string='result = x + y  # addition',
            new_string='result = x - y  # subtraction'
        )
        with open(self.test_file) as f:
            content = f.read()
            # validate 函数应完好
            self.assertIn('def validate(data):', content)
            self.assertIn('return True', content)

    def test_edit_not_found(self):
        """old_string 不存在：返回错误 + 文件预览。"""
        from tools import EditTool
        tool = EditTool()
        result = tool.execute(
            file_path=self.test_file,
            old_string='this string does not exist',
            new_string='replacement'
        )
        self.assertTrue(result.startswith('Error'))
        self.assertIn('not found', result)
        # 应包含文件前几行作为定位提示
        self.assertIn('def calculate', result)

    def test_edit_non_unique(self):
        """old_string 出现多次：返回错误 + 出现次数。"""
        from tools import EditTool
        tool = EditTool()
        # 'return' 在文件中出现 3 次（return result, return False, return True）
        result = tool.execute(
            file_path=self.test_file,
            old_string='return',
            new_string='yield'
        )
        self.assertTrue(result.startswith('Error'))
        self.assertIn('3 times', result)

    def test_edit_file_not_found(self):
        """文件不存在：返回错误。"""
        from tools import EditTool
        tool = EditTool()
        result = tool.execute(
            file_path='/nonexistent/file.py',
            old_string='a',
            new_string='b'
        )
        self.assertTrue(result.startswith('Error'))

    def test_edit_multiline(self):
        """多行替换：old_string 和 new_string 可以包含换行符。"""
        from tools import EditTool
        tool = EditTool()
        result = tool.execute(
            file_path=self.test_file,
            old_string='    if data is None:\n        return False',
            new_string='    if data is None:\n        raise ValueError("data cannot be None")'
        )
        self.assertIn('Successfully', result)
        with open(self.test_file) as f:
            self.assertIn('raise ValueError', f.read())


class TestGrepTool(unittest.TestCase):
    """
    Grep 工具测试：正则搜索 + 递归 + head_limit。

    重点测试：
    - 目录递归搜索（跳过 .git 等）
    - head_limit 截断（ACI 输出控制）
    - 正则表达式支持
    - 边界情况（无匹配、非法正则）
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # 创建测试目录结构
        os.makedirs(os.path.join(self.tmpdir, 'src'))
        os.makedirs(os.path.join(self.tmpdir, '.git'))  # 应被跳过

        with open(os.path.join(self.tmpdir, 'src', 'main.py'), 'w') as f:
            f.write('import os\nimport sys\n\ndef main():\n    print("hello")\n')
        with open(os.path.join(self.tmpdir, 'src', 'utils.py'), 'w') as f:
            f.write('import os\n\ndef helper():\n    return 42\n')
        # .git 目录下的文件不应被搜索
        with open(os.path.join(self.tmpdir, '.git', 'config'), 'w') as f:
            f.write('import os\n')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_grep_directory_recursive(self):
        """目录递归搜索：在多个文件中找到匹配。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern='import os', path=self.tmpdir)
        self.assertIn('main.py', result)
        self.assertIn('utils.py', result)

    def test_grep_skips_hidden_dirs(self):
        """跳过隐藏目录：.git 下的文件不应出现在结果中。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern='import os', path=self.tmpdir)
        self.assertNotIn('.git', result)

    def test_grep_single_file(self):
        """单文件搜索。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(
            pattern='def main',
            path=os.path.join(self.tmpdir, 'src', 'main.py')
        )
        self.assertIn('def main', result)
        self.assertIn('1 matches', result)

    def test_grep_regex(self):
        """正则表达式搜索。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern=r'def \w+\(\)', path=self.tmpdir)
        self.assertIn('def main()', result)
        self.assertIn('def helper()', result)

    def test_grep_with_line_numbers(self):
        """输出格式包含行号。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(
            pattern='def main',
            path=os.path.join(self.tmpdir, 'src', 'main.py')
        )
        # 格式：文件路径:行号: 内容
        self.assertIn(':4:', result)  # def main 在第 4 行

    def test_grep_head_limit(self):
        """head_limit 截断：超出限制的匹配不显示。"""
        from tools import GrepTool
        tool = GrepTool()
        # 创建大量匹配的文件
        many_file = os.path.join(self.tmpdir, 'many.txt')
        with open(many_file, 'w') as f:
            for i in range(100):
                f.write(f'match_{i}\n')
        result = tool.execute(pattern='match_', path=many_file, head_limit=5)
        # 只显示 5 条
        self.assertEqual(result.count('match_'), 5)
        # 提示总匹配数
        self.assertIn('100 matches', result)

    def test_grep_no_match(self):
        """无匹配结果。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern='zzzzz_no_match', path=self.tmpdir)
        self.assertIn('No matches', result)

    def test_grep_invalid_regex(self):
        """非法正则表达式：返回错误。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern='[invalid', path=self.tmpdir)
        self.assertTrue(result.startswith('Error'))

    def test_grep_path_not_found(self):
        """路径不存在：返回错误。"""
        from tools import GrepTool
        tool = GrepTool()
        result = tool.execute(pattern='test', path='/nonexistent/path')
        self.assertTrue(result.startswith('Error'))


class TestBashTool(unittest.TestCase):
    """Bash 工具测试：命令执行 + 错误处理。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_bash_simple_command(self):
        """简单命令执行。"""
        from tools import BashTool
        tool = BashTool(working_dir=self.tmpdir)
        result = tool.execute(command='echo hello world')
        self.assertIn('hello world', result)

    def test_bash_working_directory(self):
        """命令在指定工作目录下执行。"""
        from tools import BashTool
        tool = BashTool(working_dir=self.tmpdir)
        # 在 tmpdir 下创建文件
        with open(os.path.join(self.tmpdir, 'marker.txt'), 'w') as f:
            f.write('found')
        result = tool.execute(command='cat marker.txt')
        self.assertIn('found', result)

    def test_bash_nonzero_exit(self):
        """非零退出码：包含退出码信息。"""
        from tools import BashTool
        tool = BashTool(working_dir=self.tmpdir)
        result = tool.execute(command='exit 42')
        self.assertIn('Return code: 42', result)

    def test_bash_stderr(self):
        """stderr 输出：包含 STDERR 标记。"""
        from tools import BashTool
        tool = BashTool(working_dir=self.tmpdir)
        result = tool.execute(command='echo error >&2')
        self.assertIn('STDERR', result)

    def test_bash_timeout(self):
        """命令超时：返回超时错误。"""
        from tools import BashTool
        tool = BashTool(working_dir=self.tmpdir)
        result = tool.execute(command='sleep 60')
        self.assertIn('timed out', result)


# ===========================================================================
# Day 2: 协议层测试
# ===========================================================================

class TestParser(unittest.TestCase):
    """
    Parser 测试：三策略解析 + 双格式兼容。

    三种包裹格式：XML 标签、代码块、裸 JSON
    两种 JSON 格式：MVP v1（tool/parameters）、Qwen 原生（name/arguments）
    """

    def test_parse_xml_qwen_format(self):
        """XML 标签 + Qwen 原生格式。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"name": "Read", "arguments": {"file_path": "/tmp/a"}}</tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Read')
        self.assertEqual(tc[0].parameters, {'file_path': '/tmp/a'})

    def test_parse_xml_v1_format(self):
        """XML 标签 + MVP v1 格式。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"tool": "Write", "parameters": {"file_path": "/tmp/a", "content": "hi"}}</tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Write')

    def test_parse_code_block(self):
        """代码块包裹。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '```json\n{"name": "Grep", "arguments": {"pattern": "def", "path": "/tmp"}}\n```'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Grep')

    def test_parse_bare_json(self):
        """裸 JSON（无包裹）。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            'Let me search. {"name": "Bash", "arguments": {"command": "ls"}}'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Bash')

    def test_parse_multiple_tool_calls(self):
        """多个工具调用。"""
        from parser import parse_tool_calls
        text = (
            '<tool_call>{"name": "Read", "arguments": {"file_path": "/a"}}</tool_call>\n'
            '<tool_call>{"name": "Read", "arguments": {"file_path": "/b"}}</tool_call>'
        )
        tc = parse_tool_calls(text)
        self.assertEqual(len(tc), 2)

    def test_parse_no_tool_calls(self):
        """纯文本（无工具调用）。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls('This is just a regular response with no tool calls.')
        self.assertEqual(len(tc), 0)

    def test_parse_orphan_close_tag(self):
        """孤立闭标签（小模型常见格式残缺）。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '{"name": "Read", "arguments": {"file_path": "/tmp/x"}} </tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Read')

    def test_parse_string_arguments(self):
        """arguments 为字符串（小模型偶尔输出 JSON 字符串而非对象）。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"name": "Bash", "arguments": "{\\"command\\": \\"ls\\"}"}</tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].parameters, {'command': 'ls'})

    def test_sanitize_trailing_comma(self):
        """尾部逗号修复。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"name": "Read", "arguments": {"file_path": "/tmp/a",}}</tool_call>'
        )
        self.assertEqual(len(tc), 1)

    def test_sanitize_js_line_comment(self):
        """JS 单行注释修复：// comment 应被剥离后正确解析。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"name": "Edit", "arguments": {\n'
            '  "file_path": "/tmp/a.py",  // target file\n'
            '  "old_string": "x = 1",\n'
            '  "new_string": "x = 2"\n'
            '}}</tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Edit')
        self.assertEqual(tc[0].parameters['file_path'], '/tmp/a.py')

    def test_sanitize_js_line_comment_preserves_urls(self):
        """JS 注释剥离不应破坏字符串内的 // (如 URL)。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"name": "Bash", "arguments": {'
            '"command": "curl https://example.com/api"'
            '}}</tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertIn('https://example.com/api', tc[0].parameters['command'])

    def test_sanitize_js_block_comment(self):
        """JS 块注释修复：/* ... */ 应被剥离后正确解析。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '<tool_call>{"name": "Read", "arguments": '
            '{"file_path": /* path */ "/tmp/a.py"}}</tool_call>'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Read')

    def test_code_block_any_language(self):
        """代码块：非标准语言标识符（javascript）应能匹配。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '```javascript\n{"name": "Bash", "arguments": {"command": "ls"}}\n```'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Bash')

    def test_code_block_with_js_comments(self):
        """代码块 + JS 注释：两重修复叠加。"""
        from parser import parse_tool_calls
        tc = parse_tool_calls(
            '```json\n{"name": "Edit", "arguments": {\n'
            '  "file_path": "/tmp/a.py",  // This must appear exactly once\n'
            '  "old_string": "total += numbers[i + 1]",\n'
            '  "new_string": "total += numbers[i]"\n'
            '}}\n```'
        )
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0].tool_name, 'Edit')


class TestAdapter(unittest.TestCase):
    """
    Adapter 测试：Claude ↔ Qwen 双向转换。
    """

    def test_tools_conversion(self):
        """Claude 工具定义 → Qwen 格式。"""
        from adapter import claude_tools_to_qwen
        claude_tools = [{
            'name': 'Read',
            'description': 'Read a file',
            'input_schema': {
                'type': 'object',
                'properties': {'file_path': {'type': 'string'}},
                'required': ['file_path']
            }
        }]
        qwen_tools = claude_tools_to_qwen(claude_tools)
        self.assertEqual(len(qwen_tools), 1)
        self.assertEqual(qwen_tools[0]['type'], 'function')
        self.assertEqual(qwen_tools[0]['function']['name'], 'Read')
        self.assertIn('parameters', qwen_tools[0]['function'])

    def test_messages_text(self):
        """纯文本消息转换。"""
        from adapter import claude_messages_to_qwen
        msgs = [
            {'role': 'system', 'content': 'You are helpful.'},
            {'role': 'user', 'content': 'Hello'}
        ]
        result = claude_messages_to_qwen(msgs)
        self.assertEqual(result[0], {'role': 'system', 'content': 'You are helpful.'})
        self.assertEqual(result[1], {'role': 'user', 'content': 'Hello'})

    def test_messages_tool_use(self):
        """tool_use content blocks → Qwen tool_calls 结构。"""
        from adapter import claude_messages_to_qwen
        msgs = [{
            'role': 'assistant',
            'content': [
                {'type': 'text', 'text': 'Let me read.'},
                {'type': 'tool_use', 'id': 'toolu_123', 'name': 'Read',
                 'input': {'file_path': '/tmp/a'}}
            ]
        }]
        result = claude_messages_to_qwen(msgs)
        self.assertEqual(result[0]['role'], 'assistant')
        self.assertIn('tool_calls', result[0])
        self.assertEqual(result[0]['tool_calls'][0]['function']['name'], 'Read')

    def test_messages_tool_result(self):
        """tool_result → Qwen tool role message。"""
        from adapter import claude_messages_to_qwen
        msgs = [{
            'role': 'user',
            'content': [
                {'type': 'tool_result', 'tool_use_id': 'toolu_123',
                 'content': 'file contents'}
            ]
        }]
        result = claude_messages_to_qwen(msgs)
        self.assertEqual(result[0]['role'], 'tool')
        self.assertEqual(result[0]['content'], 'file contents')

    def test_response_tool_use(self):
        """Qwen <tool_call> → Claude tool_use response。"""
        from adapter import qwen_response_to_claude
        resp = qwen_response_to_claude(
            'Let me read.\n<tool_call>\n'
            '{"name": "Read", "arguments": {"file_path": "/tmp/a"}}\n'
            '</tool_call>'
        )
        self.assertEqual(resp['stop_reason'], 'tool_use')
        self.assertEqual(resp['role'], 'assistant')
        tool_uses = [b for b in resp['content'] if b['type'] == 'tool_use']
        self.assertEqual(len(tool_uses), 1)
        self.assertEqual(tool_uses[0]['name'], 'Read')
        self.assertTrue(tool_uses[0]['id'].startswith('toolu_'))

    def test_response_end_turn(self):
        """纯文本 → end_turn 响应。"""
        from adapter import qwen_response_to_claude
        resp = qwen_response_to_claude('The bug is fixed.')
        self.assertEqual(resp['stop_reason'], 'end_turn')
        self.assertEqual(resp['content'][0]['text'], 'The bug is fixed.')

    def test_response_multiple_tool_uses(self):
        """多个 tool_call → 多个 tool_use blocks。"""
        from adapter import qwen_response_to_claude
        resp = qwen_response_to_claude(
            'Reading two files.\n'
            '<tool_call>{"name": "Read", "arguments": {"file_path": "/a"}}</tool_call>\n'
            '<tool_call>{"name": "Read", "arguments": {"file_path": "/b"}}</tool_call>'
        )
        tool_uses = [b for b in resp['content'] if b['type'] == 'tool_use']
        self.assertEqual(len(tool_uses), 2)

    def test_response_code_block_tool_use(self):
        """代码块格式的 tool_call → 正确返回 tool_use + stop_reason。"""
        from adapter import qwen_response_to_claude
        resp = qwen_response_to_claude(
            'I will run the command.\n'
            '```json\n{"name": "Bash", "arguments": {"command": "ls"}}\n```'
        )
        self.assertEqual(resp['stop_reason'], 'tool_use')
        tool_uses = [b for b in resp['content'] if b['type'] == 'tool_use']
        self.assertEqual(len(tool_uses), 1)
        self.assertEqual(tool_uses[0]['name'], 'Bash')
        # 前面的文本应作为 text block
        text_blocks = [b for b in resp['content'] if b['type'] == 'text']
        self.assertTrue(len(text_blocks) >= 1)
        self.assertIn('I will run the command', text_blocks[0]['text'])

    def test_response_code_block_with_js_comments(self):
        """代码块 + JS 注释：完整链路测试（解析成功 + stop_reason=tool_use）。"""
        from adapter import qwen_response_to_claude
        resp = qwen_response_to_claude(
            'Sure! I will fix the bug.\n'
            '```json\n{"name": "Edit", "arguments": {\n'
            '  "file_path": "/tmp/a.py",  // target file\n'
            '  "old_string": "x = 1",\n'
            '  "new_string": "x = 2"\n'
            '}}\n```'
        )
        self.assertEqual(resp['stop_reason'], 'tool_use')
        tool_uses = [b for b in resp['content'] if b['type'] == 'tool_use']
        self.assertEqual(len(tool_uses), 1)
        self.assertEqual(tool_uses[0]['name'], 'Edit')


# ===========================================================================
# Day 3: 任务管理测试
# ===========================================================================

class TestTaskStore(unittest.TestCase):
    """
    TaskStore 测试：CRUD + 状态机 + 线程安全。
    """

    def setUp(self):
        from task_tools import TaskStore
        self.store = TaskStore()

    def test_create(self):
        """创建任务：自动分配 ID，初始状态 pending。"""
        task = self.store.create('Fix bug')
        self.assertEqual(task['id'], '1')
        self.assertEqual(task['status'], 'pending')
        self.assertEqual(task['description'], 'Fix bug')

    def test_auto_increment_id(self):
        """ID 自增。"""
        self.store.create('Task A')
        t2 = self.store.create('Task B')
        self.assertEqual(t2['id'], '2')

    def test_update_status(self):
        """更新状态。"""
        self.store.create('Task A')
        result = self.store.update('1', 'in_progress')
        self.assertEqual(result['status'], 'in_progress')
        result = self.store.update('1', 'completed')
        self.assertEqual(result['status'], 'completed')

    def test_update_invalid_status(self):
        """无效状态：返回 None。"""
        self.store.create('Task A')
        result = self.store.update('1', 'invalid')
        self.assertIsNone(result)

    def test_update_missing_task(self):
        """不存在的任务：返回 None。"""
        result = self.store.update('999', 'completed')
        self.assertIsNone(result)

    def test_list_all(self):
        """列出所有任务（按 ID 排序）。"""
        self.store.create('Task A')
        self.store.create('Task B')
        tasks = self.store.list_all()
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]['id'], '1')
        self.assertEqual(tasks[1]['id'], '2')

    def test_get(self):
        """获取单个任务。"""
        self.store.create('Task A')
        task = self.store.get('1')
        self.assertEqual(task['description'], 'Task A')

    def test_get_missing(self):
        """获取不存在的任务：返回 None。"""
        self.assertIsNone(self.store.get('999'))

    def test_reset(self):
        """重置清空所有任务和 ID 计数器。"""
        self.store.create('Task A')
        self.store.create('Task B')
        self.store.reset()
        self.assertEqual(len(self.store.list_all()), 0)
        # ID 应该重新从 1 开始
        t = self.store.create('Task C')
        self.assertEqual(t['id'], '1')

    def test_thread_safety(self):
        """线程安全：多线程并发创建任务不丢数据。"""
        def create_tasks():
            for _ in range(50):
                self.store.create('concurrent task')

        threads = [threading.Thread(target=create_tasks) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(self.store.list_all()), 200)

    def test_returns_copies(self):
        """返回值是副本，修改不影响存储。"""
        self.store.create('Task A')
        task = self.store.get('1')
        task['status'] = 'hacked'
        # 存储中的任务不应被影响
        original = self.store.get('1')
        self.assertEqual(original['status'], 'pending')


class TestTaskTools(unittest.TestCase):
    """TaskCreate / TaskUpdate / TaskList 工具行为测试。"""

    def setUp(self):
        from task_tools import TaskStore, TaskCreateTool, TaskUpdateTool, TaskListTool
        self.store = TaskStore()
        self.create_tool = TaskCreateTool(self.store)
        self.update_tool = TaskUpdateTool(self.store)
        self.list_tool = TaskListTool(self.store)

    def test_create_tool(self):
        """TaskCreate 返回任务信息。"""
        result = self.create_tool.execute(description='Fix bug in utils.py')
        self.assertIn('Created task #1', result)
        self.assertIn('Fix bug', result)

    def test_update_tool_in_progress(self):
        """TaskUpdate → in_progress。"""
        self.create_tool.execute(description='Task A')
        result = self.update_tool.execute(task_id='1', status='in_progress')
        self.assertIn('🔄', result)

    def test_update_tool_completed(self):
        """TaskUpdate → completed。"""
        self.create_tool.execute(description='Task A')
        result = self.update_tool.execute(task_id='1', status='completed')
        self.assertIn('✅', result)

    def test_update_tool_missing_task(self):
        """TaskUpdate 不存在的任务。"""
        result = self.update_tool.execute(task_id='999', status='completed')
        self.assertTrue(result.startswith('Error'))

    def test_update_tool_invalid_status(self):
        """TaskUpdate 无效状态。"""
        self.create_tool.execute(description='Task A')
        result = self.update_tool.execute(task_id='1', status='invalid')
        self.assertTrue(result.startswith('Error'))

    def test_list_tool_markdown(self):
        """TaskList 返回 Markdown 格式。"""
        self.create_tool.execute(description='Task A')
        self.create_tool.execute(description='Task B')
        self.update_tool.execute(task_id='1', status='completed')
        result = self.list_tool.execute()
        self.assertIn('## Tasks', result)
        self.assertIn('[x] #1', result)  # completed
        self.assertIn('[ ] #2', result)  # pending
        self.assertIn('1/2 completed', result)

    def test_list_tool_empty(self):
        """TaskList 空列表。"""
        result = self.list_tool.execute()
        self.assertIn('No tasks', result)


# ===========================================================================
# Day 4: Agent Team 测试
# ===========================================================================

class TestAgentTool(unittest.TestCase):
    """
    Agent 工具测试（仅验证接口，不测实际推理）。

    实际的子 Agent 执行需要连接 model_server，
    这里只测工具定义、参数验证和 TaskStore 交互。
    """

    def test_tool_definition(self):
        """Agent 工具定义包含必要字段。"""
        from agent_tool import AgentTool
        from task_tools import TaskStore
        tool = AgentTool('http://localhost:9981', '/tmp', TaskStore())
        self.assertEqual(tool.name, 'Agent')
        self.assertIn('prompt', tool.parameters['properties'])
        self.assertIn('task_id', tool.parameters['properties'])
        self.assertEqual(tool.parameters['required'], ['prompt'])

    def test_get_agent_tool(self):
        """get_agent_tool 返回正确的工具字典。"""
        from agent_tool import get_agent_tool
        from task_tools import TaskStore
        tools = get_agent_tool('http://localhost:9981', '/tmp', TaskStore())
        self.assertIn('Agent', tools)
        self.assertEqual(len(tools), 1)

    def test_agent_with_missing_task(self):
        """Agent 关联不存在的 task_id：返回错误。"""
        from agent_tool import AgentTool
        from task_tools import TaskStore
        store = TaskStore()
        tool = AgentTool('http://localhost:9981', '/tmp', store)
        # 不创建任何任务，直接关联 task_id
        result = tool.execute(prompt='Fix bug', task_id='999')
        self.assertIn('Error', result)
        self.assertIn('not found', result)


# ===========================================================================
# 集成测试
# ===========================================================================

class TestClientIntegration(unittest.TestCase):
    """
    客户端集成测试：验证所有组件正确组装。

    不测试实际推理（需要 model_server），
    只测试工具注册、定义格式、全链路兼容性。
    """

    def test_all_tools_registered(self):
        """客户端应注册全部 9 个工具。"""
        from tools import get_tools
        from task_tools import get_task_tools, TaskStore
        from agent_tool import get_agent_tool
        store = TaskStore()
        all_tools = {}
        all_tools.update(get_tools(working_dir='/tmp'))
        all_tools.update(get_task_tools(store))
        all_tools.update(get_agent_tool('http://localhost:9981', '/tmp', store))
        self.assertEqual(len(all_tools), 9)
        expected = [
            'Read', 'Write', 'Edit', 'Grep', 'Bash',
            'TaskCreate', 'TaskUpdate', 'TaskList', 'Agent'
        ]
        for name in expected:
            self.assertIn(name, all_tools)

    def test_tool_definitions_format(self):
        """所有工具定义符合 Claude API 格式。"""
        from tools import get_tools
        from task_tools import get_task_tools, TaskStore
        from agent_tool import get_agent_tool
        from client import get_tool_definitions
        store = TaskStore()
        all_tools = {}
        all_tools.update(get_tools(working_dir='/tmp'))
        all_tools.update(get_task_tools(store))
        all_tools.update(get_agent_tool('http://localhost:9981', '/tmp', store))
        defs = get_tool_definitions(all_tools)
        self.assertEqual(len(defs), 9)
        for d in defs:
            # 每个定义必须包含 name, description, input_schema
            self.assertIn('name', d)
            self.assertIn('description', d)
            self.assertIn('input_schema', d)
            # input_schema 必须是 JSON Schema 对象
            self.assertEqual(d['input_schema']['type'], 'object')
            self.assertIn('properties', d['input_schema'])

    def test_adapter_handles_all_tools(self):
        """适配层能正确转换所有工具的 tool_use。"""
        from adapter import qwen_response_to_claude
        # 测试每个工具名都能被正确解析为 tool_use block
        tool_names = [
            'Read', 'Write', 'Edit', 'Grep', 'Bash',
            'TaskCreate', 'TaskUpdate', 'TaskList', 'Agent'
        ]
        for tool_name in tool_names:
            resp = qwen_response_to_claude(
                f'<tool_call>{{"name": "{tool_name}", '
                f'"arguments": {{"key": "value"}}}}</tool_call>'
            )
            tool_uses = [b for b in resp['content'] if b['type'] == 'tool_use']
            self.assertEqual(len(tool_uses), 1, f'Failed for {tool_name}')
            self.assertEqual(tool_uses[0]['name'], tool_name)

    def test_task_store_isolation(self):
        """不同 TaskStore 实例之间互不干扰。"""
        from task_tools import TaskStore
        store_a = TaskStore()
        store_b = TaskStore()
        store_a.create('Task in A')
        self.assertEqual(len(store_a.list_all()), 1)
        self.assertEqual(len(store_b.list_all()), 0)


# ===========================================================================
# 入口
# ===========================================================================

if __name__ == '__main__':
    # 使用 verbosity=2 显示每个测试方法的名称和结果
    unittest.main(verbosity=2)
