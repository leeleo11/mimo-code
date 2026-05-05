"""
Tool definitions and executor for MiMo Code Agent loop.

Registered tools:
  read_file   — read file contents (text and image)
  write_file  — create or overwrite file
  edit_file   — find-and-replace in file
  list_dir    — list directory contents
  search_code — grep across project files
  run_shell   — execute read-only shell commands (whitelisted)
"""

import json
import mimetypes
import subprocess
from pathlib import Path

# ---- Tool JSON Schema Definitions ----

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的完整内容。支持文本文件和图片（png/jpg/gif/webp）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作目录的文件路径",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建新文件或完全覆盖已有文件的内容。仅用于创建和完整重写，不要用于局部修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作目录的文件路径",
                    },
                    "content": {
                        "type": "string",
                        "description": "要写入的完整文件内容",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "在文件中查找并精确替换指定字符串。old_string 必须在文件中唯一匹配一次。类似 sed 的 s/old/new/。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作目录的文件路径",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "要被替换的原字符串（必须精确匹配，包含空白字符）",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "替换后的新字符串",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出目录中的文件和子目录。可指定递归深度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于工作目录的目录路径，默认 '.'",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "递归深度（1=仅当前层，默认2）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "在项目文件中搜索匹配的文本或正则表达式。类似 grep。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "搜索关键词或正则表达式",
                    },
                    "glob": {
                        "type": "string",
                        "description": "文件名过滤，如 '*.py' 或 '*.{js,ts}'",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "执行只读 shell 命令。允许的命令：ls, cat, git status/log/diff, grep, find, wc, head, tail, which, python --version, pip list, echo。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的 shell 命令（仅限只读白名单命令）",
                    },
                },
                "required": ["command"],
            },
        },
    },
]

# ---- Whitelist for run_shell ----

READ_ONLY_COMMANDS = {
    "ls", "dir", "cat", "head", "tail", "wc", "grep", "find",
    "which", "where", "echo", "pwd", "env", "date", "whoami",
}

ALLOWED_PREFIXES = [
    "git status", "git log", "git diff", "git branch", "git show",
    "git stash list", "git remote", "git config",
    "python --version", "python3 --version",
    "python -V", "python3 -V",
    "pip list", "pip show",
    "node --version", "npm list", "npm -v",
]


def _is_safe_command(command: str) -> bool:
    """Check if a shell command is in the read-only whitelist."""
    cmd = command.strip()
    if not cmd:
        return False

    # Check exact matches
    base = cmd.split()[0].lower() if cmd.split() else ""
    if base in READ_ONLY_COMMANDS:
        return True

    # Check prefix matches
    cmd_lower = cmd.lower()
    for prefix in ALLOWED_PREFIXES:
        if cmd_lower.startswith(prefix):
            return True

    return False


# ---- Tool Implementations ----

def _resolve(workspace: str, rel_path: str) -> Path:
    """Resolve a user-provided path relative to workspace, preventing traversal."""
    base = Path(workspace).resolve()
    target = (base / rel_path).resolve()
    # Prevent directory traversal
    if not str(target).startswith(str(base)):
        raise ValueError(f"路径越界: {rel_path}")
    return target


def tool_read_file(args: dict, workspace: str) -> str:
    path = _resolve(workspace, args["path"])
    if not path.exists():
        return f"错误: 文件不存在: {args['path']}"
    if not path.is_file():
        return f"错误: 不是文件: {args['path']}"

    # Image files return a marker (actual encoding handled by caller)
    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        size_kb = path.stat().st_size / 1024
        return (
            f"[图片文件] {args['path']} ({size_kb:.0f}KB, {ext})\n"
            f"图片内容已作为多模态输入发送给模型。"
        )

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        # Truncate very large files
        max_lines = 500
        lines = content.split("\n")
        if len(lines) > max_lines:
            content = "\n".join(lines[:max_lines])
            content += f"\n\n... (文件共 {len(lines)} 行，已截断前 {max_lines} 行)"
        return content
    except Exception as e:
        return f"错误: 读取失败: {e}"


def tool_write_file(args: dict, workspace: str) -> str:
    path = _resolve(workspace, args["path"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(args["content"], encoding="utf-8")
        action = "已覆盖" if existed else "已创建"
        lines = args["content"].count("\n") + 1
        return f"{action} {args['path']} ({lines} 行, {len(args['content'])} 字符)"
    except Exception as e:
        return f"错误: 写入失败: {e}"


def tool_edit_file(args: dict, workspace: str) -> str:
    path = _resolve(workspace, args["path"])
    if not path.exists():
        return f"错误: 文件不存在: {args['path']}"

    old = args["old_string"]
    new = args["new_string"]

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"错误: 读取失败: {e}"

    count = content.count(old)
    if count == 0:
        return f"错误: 文件中未找到要替换的字符串。请确认 old_string 内容与文件完全一致（注意空白字符）。"
    if count > 1:
        return f"错误: old_string 在文件中出现了 {count} 次。请提供更多上下文使匹配唯一。"

    new_content = content.replace(old, new, 1)
    try:
        path.write_text(new_content, encoding="utf-8")
        return f"已修改 {args['path']}（1 处替换）"
    except Exception as e:
        return f"错误: 写入失败: {e}"


def tool_list_dir(args: dict, workspace: str) -> str:
    path_str = args.get("path", ".")
    depth = max(1, min(5, args.get("depth", 2)))
    path = _resolve(workspace, path_str)

    if not path.exists():
        return f"错误: 目录不存在: {path_str}"
    if not path.is_dir():
        return f"错误: 不是目录: {path_str}"

    lines = []
    _walk_dir(path, path, depth, 1, lines, max_items=200)

    if not lines:
        return f"目录为空: {path_str}"
    return "\n".join(lines)


def _walk_dir(base: Path, current: Path, max_depth: int, current_depth: int,
              lines: list, prefix: str = "", max_items: int = 200):
    """Recursive directory listing helper."""
    if current_depth > max_depth or len(lines) >= max_items:
        return

    try:
        entries = sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        lines.append(f"{prefix}  [权限不足]")
        return

    for entry in entries:
        if len(lines) >= max_items:
            lines.append(f"{prefix}  ... (已达到 {max_items} 项上限)")
            return
        rel = entry.relative_to(base)
        if entry.is_dir():
            lines.append(f"{prefix}📁 {rel}/")
            _walk_dir(base, entry, max_depth, current_depth + 1, lines, prefix + "  ", max_items)
        else:
            size = entry.stat().st_size
            size_str = f"{size / 1024:.1f}KB" if size > 1024 else f"{size}B"
            lines.append(f"{prefix}📄 {rel.name} ({size_str})")


def tool_search_code(args: dict, workspace: str) -> str:
    pattern = args["pattern"]
    glob_filter = args.get("glob", "")

    base = Path(workspace).resolve()
    results = []
    max_results = 30

    # Determine files to search
    if glob_filter:
        files = list(base.rglob(glob_filter))
    else:
        # Default: text/code files, skip binaries and hidden dirs
        text_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
                     ".yaml", ".yml", ".md", ".txt", ".toml", ".cfg", ".ini", ".sh",
                     ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".java", ".rb", ".php",
                     ".xml", ".svg", ".sql", ".env", ".gitignore"}
        all_files = list(base.rglob("*"))
        files = [f for f in all_files
                 if f.suffix in text_exts
                 and ".git/" not in str(f)
                 and "__pycache__" not in str(f)
                 and "node_modules" not in str(f)]

    for f in files[:200]:  # Limit search scope
        if len(results) >= max_results:
            break
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(content.split("\n"), 1):
                if pattern.lower() in line.lower():
                    rel = f.relative_to(base)
                    results.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(results) >= max_results:
                        break
        except (PermissionError, OSError):
            continue

    if not results:
        return f"未找到匹配 '{pattern}' 的内容"
    return f"搜索 '{pattern}' 找到 {len(results)} 条结果:\n" + "\n".join(results)


def tool_run_shell(args: dict, workspace: str) -> str:
    command = args["command"].strip()
    if not _is_safe_command(command):
        return (
            f"错误: 命令 '{command}' 不在白名单中。\n"
            f"出于安全考虑，仅允许只读命令。允许的命令: {sorted(READ_ONLY_COMMANDS)}"
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=workspace,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[退出码: {result.returncode}]"
        return output.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误: 命令超时 (30s)"
    except Exception as e:
        return f"错误: 执行失败: {e}"


# ---- Tool Executor ----

TOOL_HANDLERS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
    "list_dir": tool_list_dir,
    "search_code": tool_search_code,
    "run_shell": tool_run_shell,
}


def execute_tool(tool_call: dict, workspace: str) -> str:
    """Execute a single tool call and return the result string."""
    name = tool_call["function"]["name"]
    handler = TOOL_HANDLERS.get(name)

    if not handler:
        return f"错误: 未知工具 '{name}'"

    try:
        args = json.loads(tool_call["function"]["arguments"])
    except json.JSONDecodeError as e:
        return f"错误: 工具参数 JSON 解析失败: {e}"

    return handler(args, workspace)
