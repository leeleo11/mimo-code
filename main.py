#!/usr/bin/env python3
"""
MiMo Code — Terminal AI coding assistant powered by Xiaomi MiMo models.

Usage:
  mimo                     Start interactive chat (default: mimo-v2-flash)
  mimo -m pro              Use MiMo-V2.5-Pro model with Agent mode
  mimo -c "explain"        One-shot: explain the code in current directory
  mimo --no-agent          Disable tool calling (plain chat mode)
  mimo --save session      Save session on exit

Set MIMO_API_KEY env var or pass --api-key.
"""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from mimo_client import IMAGE_EXTENSIONS, MiMoClient
from session import Session
from tools import TOOLS, execute_tool

# Maximum tool-calling rounds per user message
MAX_TOOL_ROUNDS = 8


def build_system_prompt(workspace: str, agent_mode: bool = True) -> str:
    """Build a coding-focused system prompt with workspace context."""
    cwd = Path(workspace).resolve()
    files_hint = ""
    try:
        entries = sorted(cwd.iterdir())[:30]
        names = [f"{'[D]' if e.is_dir() else '[F]'} {e.name}" for e in entries]
        files_hint = "\n".join(names) if names else "(empty directory)"
    except (PermissionError, OSError):
        files_hint = "(cannot read directory)"

    prompt = f"""You are MiMo Code, an expert AI coding assistant powered by Xiaomi MiMo.

WORKSPACE: {cwd}
Working directory contents:
{files_hint}

CAPABILITIES:
- Read, analyze, and explain code
- Generate code snippets with explanations
- Answer programming questions across languages and frameworks
- Debug issues and suggest fixes
- Provide architectural advice"""

    if agent_mode:
        prompt += """
- Read files, write new files, and make precise edits
- Search code across the project
- Execute safe shell commands to inspect the environment

TOOL USAGE GUIDELINES:
- Use read_file before attempting to edit — never guess file contents
- Use search_code to find where symbols are defined or used
- For edits, use edit_file with the exact old_string (copy from read_file output)
- Use write_file only for new files or complete rewrites
- When using run_shell, prefer git/listing commands over destructive operations
- After making changes, summarize what you did and why"""

    prompt += """

RULES:
- Keep responses concise and actionable
- Format code blocks with language markers (```python, ```javascript, etc.)
- When referencing files, use the full path
- If the user's request is ambiguous, ask one clarifying question before proceeding
- For multi-step tasks, outline the plan before writing code"""

    return prompt


def run_repl(client: MiMoClient, session: Session, args):
    """Run interactive chat REPL with optional Agent loop."""
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.live import Live
    from rich.text import Text

    console = Console()
    model_name = client.model_display_name()
    agent_mode = not args.no_agent

    console.print()
    console.print(
        Panel.fit(
            f"[bold]MiMo Code[/bold]  [dim]— 终端 AI 编程助手[/dim]\n"
            f"模型: [bold cyan]{model_name}[/bold cyan]  |  "
            f"上下文: [bold cyan]{client.context_window}[/bold cyan]  |  "
            f"Agent: [bold cyan]{'开启' if agent_mode else '关闭'}[/bold cyan]  |  "
            f"工作目录: [bold cyan]{client.workspace}[/bold cyan]\n\n"
            f"输入 [bold]/help[/bold] 查看命令  |  "
            f"[bold]@文件名[/bold] 引用文件  |  "
            f"[bold]@图片.png[/bold] 多模态  |  "
            f"[bold]Ctrl+C[/bold] 中断  |  "
            f"[bold]/quit[/bold] 退出",
            title="🚀 欢迎",
            border_style="bright_blue",
        )
    )

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]再见！[/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        if user_input.startswith("/"):
            handled = handle_command(user_input, client, session, console, args)
            if handled == "quit":
                break
            # Update agent_mode in case it was toggled
            agent_mode = not args.no_agent
            continue

        # Resolve @file references (text + image)
        resolved_input = resolve_file_refs(user_input, client)
        image_parts = []
        if isinstance(resolved_input, tuple):
            resolved_input, image_parts = resolved_input

        # Build user message (support multi-modal content array)
        if image_parts and client.supports_multimodal():
            user_content = [{"type": "text", "text": resolved_input}] + image_parts
            session.add_user(user_content)
            console.print(
                f"[dim]已加载文本+{len(image_parts)} 张图片上下文[/dim]"
            )
        else:
            session.add_user(resolved_input)
            # Warn if images were dropped
            if image_parts:
                console.print(
                    f"[yellow]警告: {len(image_parts)} 张图片被忽略（模型 {client.model_key} 不支持多模态，请使用 v25 或 omni）[/yellow]"
                )

        # Run Agent loop or simple chat
        console.print()
        if agent_mode:
            _run_agent_turn(client, session, console)
        else:
            _run_simple_turn(client, session, console)

        # Show usage
        usage = session.current_usage()
        console.print(
            f"\n[dim]Tokens: 本轮 ~{usage['last_tokens']:,} | "
            f"会话累计 ~{usage['total_tokens']:,} | "
            f"轮次: {usage['turns']} | "
            f"模型: {model_name}[/dim]"
        )

    # Save session on exit
    if args.save:
        path = session.save(args.save)
        console.print(f"\n[dim]会话已保存到 {path}[/dim]")


def _run_simple_turn(client: MiMoClient, session: Session, console):
    """Simple chat without tool calling."""
    from rich.markdown import Markdown
    from rich.live import Live
    from rich.text import Text

    messages = session.build_messages()
    accumulated = ""

    try:
        with Live(Text("思考中...", style="dim"), console=console, refresh_per_second=15) as live:
            first_chunk = True
            for chunk in client.chat_stream(messages):
                if first_chunk:
                    accumulated = chunk
                    first_chunk = False
                else:
                    accumulated += chunk
                live.update(Markdown(accumulated, code_theme="one-dark"))
    except KeyboardInterrupt:
        console.print("\n[dim]已中断[/dim]")
        accumulated += "\n\n*[interrupted by user]*"
    except Exception as e:
        console.print(f"\n[bold red]错误:[/bold red] {e}")
        return

    session.add_assistant(accumulated)


def _run_agent_turn(client: MiMoClient, session: Session, console):
    """Run a single Agent turn with tool-calling loop."""
    from rich.markdown import Markdown
    from rich.live import Live
    from rich.text import Text

    tools = TOOLS if client.model_key != "flash" else None
    tool_rounds_this_turn = 0

    for iteration in range(MAX_TOOL_ROUNDS):
        messages = session.build_messages()
        text_accumulated = ""
        tool_calls_accumulated: list[dict] = []

        try:
            with Live(Text("思考中..." if iteration == 0 else "继续处理...", style="dim"),
                      console=console, refresh_per_second=15) as live:
                first_chunk = True
                for event in client.chat(messages, tools=tools):
                    if event["type"] == "text":
                        if first_chunk:
                            text_accumulated = event["content"]
                            first_chunk = False
                        else:
                            text_accumulated += event["content"]
                        live.update(Markdown(text_accumulated, code_theme="one-dark"))

                    elif event["type"] == "tool_calls":
                        tool_calls_accumulated = event["tool_calls"]
                        live.stop()
        except KeyboardInterrupt:
            console.print("\n[dim]已中断[/dim]")
            text_accumulated += "\n\n*[interrupted by user]*"
            session.add_assistant(text_accumulated)
            return
        except Exception as e:
            console.print(f"\n[bold red]错误:[/bold red] {e}")
            return

        # No tool calls — we're done
        if not tool_calls_accumulated:
            session.add_assistant(text_accumulated)
            return

        # Tool calls present — show and execute
        tool_rounds_this_turn += 1

        # Show pre-tool text if any
        pre_text = text_accumulated.strip() if text_accumulated else None
        if pre_text:
            console.print(f"[dim italic]{pre_text}[/dim italic]")

        # Record assistant message with tool calls
        session.add_assistant_with_tools(text_accumulated, tool_calls_accumulated)

        # Execute each tool
        for tc in tool_calls_accumulated:
            fn_name = tc["function"]["name"]
            try:
                args_short = tc["function"]["arguments"]
                if len(args_short) > 80:
                    args_short = args_short[:77] + "..."
            except Exception:
                args_short = "?"

            console.print(f"  [bold yellow]🔧[/bold yellow] [cyan]{fn_name}[/cyan]({args_short})")

            result = execute_tool(tc, client.workspace)
            session.add_tool_result(tc["id"], fn_name, result)

            # Show truncated result
            result_preview = result[:200].replace("\n", " ")
            if len(result) > 200:
                result_preview += "..."
            console.print(f"  [dim]   → {result_preview}[/dim]")

    # Exceeded max rounds
    console.print(f"\n[yellow]已达到最大工具调用轮次 ({MAX_TOOL_ROUNDS})，请用 /continue 继续或简化请求。[/yellow]")


def resolve_file_refs(text: str, client: MiMoClient) -> str | tuple[str, list[dict]]:
    """Resolve @file references.

    Returns:
      - plain str if no images were referenced
      - (str, list[image_parts]) tuple if images were found (for multi-modal)
    """
    import glob as glob_mod

    contexts = []
    image_parts = []
    resolved_parts = []
    base = Path(client.workspace)

    for word in text.split():
        if not (word.startswith("@") and len(word) > 1):
            resolved_parts.append(word)
            continue

        pattern = word[1:]
        full_pattern = str(base / pattern)

        if "*" in pattern or "?" in pattern:
            matches = glob_mod.glob(full_pattern, recursive=True)
            for match in matches[:5]:
                _include_file(match, contexts, image_parts, client)
        else:
            file_path = base / pattern
            if file_path.is_file():
                _include_file(str(file_path), contexts, image_parts, client)
            else:
                resolved_parts.append(word)

    result = " ".join(resolved_parts)
    if contexts:
        result += "\n\n<referenced_files>\n" + "\n\n".join(contexts) + "\n</referenced_files>"

    if image_parts:
        return result, image_parts
    return result


def _include_file(file_path: str, contexts: list, image_parts: list, client: MiMoClient):
    """Add file to either text contexts or image parts depending on type."""
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in IMAGE_EXTENSIONS:
        encoded = client.encode_image(path)
        if encoded:
            image_parts.append(encoded)
        return

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        contexts.append(f"--- {path} ---\n{content}")
    except Exception:
        pass


# ===== Slash Commands =====

def handle_command(cmd: str, client: MiMoClient, session: Session, console, args) -> str | None:
    """Handle slash commands. Returns 'quit' to exit."""
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command in ("/quit", "/exit"):
        return "quit"

    elif command == "/help":
        console.print("""
[bold]MiMo Code 命令:[/bold]
  [cyan]/help[/cyan]          显示此帮助
  [cyan]/model[/cyan] <id>    切换模型 (flash / pro / v25 / omni)
  [cyan]/agent[/cyan] [on|off] 开启/关闭 Agent 工具调用模式
  [cyan]/tokens[/cyan]        显示 Token 使用统计
  [cyan]/clear[/cyan]         清除当前会话历史
  [cyan]/save[/cyan] [name]   保存当前会话
  [cyan]/load[/cyan] <name>   加载历史会话
  [cyan]/list[/cyan]          列出已保存的会话
  [cyan]/system[/cyan] <msg>  设置系统提示词
  [cyan]/workspace[/cyan] <path> 切换工作目录
  [cyan]/shell[/cyan] <cmd>   执行 shell 命令
  [cyan]/continue[/cyan]      继续上一轮 Agent 任务
  [cyan]/quit[/cyan]          退出

[bold]文件引用:[/bold]
  [cyan]@filename[/cyan]      将文本文件内容包含在上下文中
  [cyan]@image.png[/cyan]     引用图片（需 v25 或 omni 模型）
  [cyan]@src/**/*.py[/cyan]   Glob 模式匹配
  [cyan]@dir/[/cyan]          列出目录结构
""")

    elif command == "/model":
        if arg:
            client.set_model(arg)
            console.print(f"[green]已切换到模型: {client.model_display_name()}[/green]")
            if not client.supports_multimodal():
                console.print("[yellow]注意: 当前模型不支持多模态图片输入[/yellow]")
            if client.model_key == "flash":
                console.print("[yellow]注意: Flash 模型不支持 tool calling，Agent 模式需要 Pro/V2.5/Omni[/yellow]")
        else:
            console.print(f"当前模型: [cyan]{client.model_display_name()}[/cyan]")

    elif command == "/agent":
        if arg in ("on", "开"):
            args.no_agent = False
            console.print("[green]Agent 模式已开启[/green]")
            session.set_system(build_system_prompt(client.workspace, True))
        elif arg in ("off", "关"):
            args.no_agent = True
            console.print("[yellow]Agent 模式已关闭[/yellow]")
            session.set_system(build_system_prompt(client.workspace, False))
        else:
            state = "开启" if not args.no_agent else "关闭"
            console.print(f"Agent 模式: [cyan]{state}[/cyan] 使用 /agent on|off 切换")

    elif command == "/tokens":
        usage = session.current_usage()
        console.print(
            f"[bold]Token 使用统计:[/bold]\n"
            f"  本轮: [cyan]{usage['last_tokens']:,}[/cyan]\n"
            f"  会话总计: [cyan]{usage['total_tokens']:,}[/cyan]\n"
            f"  对话轮次: [cyan]{usage['turns']}[/cyan]\n"
            f"  工具调用轮次: [cyan]{usage.get('tool_rounds', 0)}[/cyan]"
        )

    elif command == "/clear":
        turns = session.clear()
        console.print(f"[green]已清除 {turns} 轮对话历史[/green]")

    elif command == "/save":
        name = arg or None
        path = session.save(name)
        console.print(f"[green]会话已保存到 {path}[/green]")

    elif command == "/load":
        if not arg:
            console.print("[red]用法: /load <会话名称>[/red]")
        else:
            try:
                session.load(arg)
                console.print(f"[green]已加载会话: {arg}[/green]")
            except FileNotFoundError:
                console.print(f"[red]会话 '{arg}' 不存在[/red]")

    elif command == "/list":
        files = session.list_sessions()
        if files:
            console.print("[bold]已保存的会话:[/bold]")
            for f in files:
                console.print(f"  [cyan]{f.stem}[/cyan]")
        else:
            console.print("[dim]暂无保存的会话[/dim]")

    elif command == "/system":
        if arg:
            session.set_system(arg)
            console.print(f"[green]系统提示词已更新[/green]")
        else:
            sys_msg = session.get_system()
            console.print(f"[bold]当前系统提示词:[/bold]\n[dim]{sys_msg}[/dim]")

    elif command == "/workspace":
        if arg:
            new_path = Path(arg).resolve()
            if new_path.is_dir():
                client.set_workspace(str(new_path))
                session.set_system(build_system_prompt(str(new_path), not args.no_agent))
                console.print(f"[green]工作目录已切换到: {new_path}[/green]")
            else:
                console.print(f"[red]目录不存在: {arg}[/red]")

    elif command == "/shell":
        if not arg:
            console.print("[red]用法: /shell <命令>[/red]")
        else:
            console.print(f"[dim]$ {arg}[/dim]")
            try:
                result = subprocess.run(
                    shlex.split(arg),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=client.workspace,
                    shell=False,
                )
                if result.stdout:
                    console.print(result.stdout)
                if result.stderr:
                    console.print(f"[yellow]{result.stderr}[/yellow]")
                console.print(f"[dim]退出码: {result.returncode}[/dim]")
            except subprocess.TimeoutExpired:
                console.print("[red]命令超时 (30s)[/red]")
            except FileNotFoundError:
                console.print(f"[red]命令未找到: {arg.split()[0]}[/red]")
            except Exception as e:
                console.print(f"[red]执行失败: {e}[/red]")

    else:
        console.print(f"[red]未知命令: {command}[/red] 输入 /help 查看可用命令")

    return None


# ===== Entry Point =====

def main():
    parser = argparse.ArgumentParser(
        description="MiMo Code — Terminal AI coding assistant powered by Xiaomi MiMo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mimo                        Start interactive chat (agent mode, flash model)
  mimo -m pro                 Use MiMo-V2.5-Pro with agent tool calling
  mimo -m v25 -c "analyze"    Use multi-modal model for one-shot
  mimo --no-agent             Plain chat without tool calling
  mimo --save my-session      Save session on exit

Set MIMO_API_KEY environment variable or use --api-key.
Apply for free tokens: https://100t.xiaomimimo.com
Platform: https://platform.xiaomimimo.com
        """,
    )
    parser.add_argument("-m", "--model", default="flash",
                        choices=["flash", "pro", "v25", "omni", "tts"],
                        help="Model to use (default: flash)")
    parser.add_argument("-c", "--command", help="One-shot command (non-interactive)")
    parser.add_argument("-s", "--session", help="Load saved session by name")
    parser.add_argument("--save", help="Save session on exit with this name")
    parser.add_argument("--api-key", help="MiMo API key (or set MIMO_API_KEY env var)")
    parser.add_argument("--base-url", help="Custom API base URL")
    parser.add_argument("-w", "--workspace", default=".",
                        help="Working directory (default: current)")
    parser.add_argument("--tokens", action="store_true",
                        help="Show token usage and exit")
    parser.add_argument("--system", help="Custom system prompt")
    parser.add_argument("--no-agent", action="store_true",
                        help="Disable Agent tool calling (plain chat mode)")

    args = parser.parse_args()

    # Get API key
    api_key = args.api_key or os.environ.get("MIMO_API_KEY")
    if not api_key:
        print("错误: 未设置 API Key。请通过以下方式之一设置：")
        print("  1. 环境变量: export MIMO_API_KEY=your-key")
        print("  2. 命令行参数: --api-key your-key")
        print("\n免费申请 MiMo Token: https://100t.xiaomimimo.com")
        sys.exit(1)

    # Initialize session
    session = Session()

    # Build system prompt
    if args.system:
        session.set_system(args.system)
    else:
        session.set_system(build_system_prompt(args.workspace, not args.no_agent))

    # Load saved session
    if args.session:
        try:
            session.load(args.session)
            print(f"已加载会话: {args.session}")
        except FileNotFoundError:
            print(f"会话 '{args.session}' 不存在，使用新会话")

    # Initialize client
    client = MiMoClient(
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
        workspace=args.workspace,
    )

    # Token usage mode
    if args.tokens:
        usage = session.current_usage()
        print(f"Token 使用统计:")
        print(f"  会话总计: {usage['total_tokens']:,}")
        print(f"  对话轮次: {usage['turns']}")
        print(f"  工具调用轮次: {usage.get('tool_rounds', 0)}")
        return

    # One-shot mode
    if args.command:
        session.add_user(args.command)
        print()
        try:
            for chunk in client.chat_stream(session.build_messages()):
                print(chunk, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n错误: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Interactive REPL
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.prompt import Prompt
        from rich.live import Live
        from rich.text import Text
        _ = (Console, Markdown, Panel, Prompt, Live, Text)
    except ImportError:
        print("需要安装 rich 库: pip install rich")
        sys.exit(1)

    run_repl(client, session, args)


if __name__ == "__main__":
    main()
