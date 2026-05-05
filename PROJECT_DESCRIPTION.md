# MiMo Code — 项目说明与成果

## 项目概述

MiMo Code 是一款基于小米 MiMo 大模型的终端 AI 编程助手，实现了完整的 **Agent 工具调用闭环**。用户通过命令行与 MiMo 模型交互，模型可自主调用文件读写、代码搜索、Shell 执行等 6 类工具，形成 **感知→推理→执行→验证** 的自动化编程工作流。

项目开源在 GitHub（MIT 协议）。

## 一、核心逻辑流

### 1.1 Agent 长链推理与工具调用循环

MiMo Code 实现了一个**多轮推理-执行循环**，这不是简单的"提问-回答"，而是模型在上下文中逐步推进的链式决策过程。

```
用户: "帮我在 config.py 中添加 DEBUG 开关"

Agent 推理链:

第 1 轮 — 感知
  MiMo 推理: "我需要先了解 config.py 的当前内容"
  工具调用: read_file("config.py")
  工具返回: DEFAULT_HOST = "localhost"\nPORT = 8080

第 2 轮 — 规划与执行
  MiMo 推理: "文件包含 HOST 和 PORT 两个配置项。
            DEBUG 应该放在文件顶部，紧接 import 之后。
            我使用 edit_file 精确替换 HOST 那行，在前面插入 DEBUG。"
  工具调用: edit_file(path="config.py",
                      old_string="DEFAULT_HOST",
                      new_string="DEBUG = False\n\nDEFAULT_HOST")

第 3 轮 — 验证
  MiMo 推理: "修改完成了。我应该验证一下文件是否正确。"
  工具调用: read_file("config.py")
  工具返回: DEBUG = False\n\nDEFAULT_HOST = "localhost"\nPORT = 8080

第 4 轮 — 输出
  MiMo: "已在 config.py 开头添加 DEBUG = False。
         你可以通过设置环境变量 MIMO_DEBUG=true 来开启调试模式。
         修改内容：在 DEFAULT_HOST 上方插入了 DEBUG 开关。"
```

**关键特征**：

- **链式推理**：模型在每个循环轮次基于上一轮的工具结果进行因果推理，决定下一步行动
- **自主决策**：模型自己决定调用哪个工具、传什么参数、何时停止
- **错误纠正**：当 `edit_file` 因匹配不唯一而失败时，模型会调整策略——增加上下文重新尝试或改用 `read_file` 确认精确内容
- **最大 8 轮**：每轮携带完整的工具定义和历史上下文

### 1.2 多 Agent 协同（架构预留）

当前版本为**单 Agent 多工具模式**，但架构上已为多 Agent 协同预留了扩展点：

- **工具级隔离**：每个工具是独立函数，可替换为远程 Agent 调用
- **Session 消息总线**：`Session` 对象维护的消息列表天然支持多角色（user/assistant/tool），可扩展为多 Agent 消息路由
- **工具调用 ID 追踪**：`tool_call_id` 机制支持并发工具调用，是多 Agent 并行执行的基础

未来演进方向：引入 Planner Agent + Executor Agent + Reviewer Agent 三体协同架构。

## 二、项目解决的核心痛点

### 痛点 1：MiMo 模型缺乏终端侧开箱即用的 Agent 工具

**问题**：MiMo-V2.5-Pro 在 Artificial Analysis 榜单上排名全球开源模型并列第一，Agent 能力是其核心卖点。但开发者要在终端中使用 MiMo 的 Agent 能力，目前只能通过 Claude Code / Cursor 等第三方工具间接调用，缺少一个**专为 MiMo 优化的本地终端 Agent**。

**解决**：MiMo Code 是首个专为 MiMo 模型设计的 CLI Agent。它直接调用 MiMo API，无需中间层，充分释放 MiMo-V2.5-Pro 的 100 万 Token 长上下文和工具调用能力。一行 `pip install` 即可使用。

### 痛点 2：现有 AI 编程工具生态绑定，Token 消耗不透明

**问题**：Claude Code、Cursor、Cline 等主流工具深度绑定各自的模型供应商。开发者想试用 MiMo 模型，要么在网页端手动对话（效率低），要么在第三方工具中配置自定义模型（功能受限、Token 用量不可控）。

**解决**：MiMo Code 提供：

- **精确的 Token 统计**：从 API 响应的 `usage` 字段直接解析真实 Token 消耗，而非字符数估算
- **实时用量展示**：每轮对话后显示本轮消耗和会话累计
- **会话持久化**：所有对话历史保存为 JSON，包含 Token 记录，方便开发者评估从其他模型迁移到 MiMo 的成本效益

### 痛点 3：编程 Agent 的"黑盒"问题

**问题**：主流 AI 编程工具对外展示"模型在思考"，但用户看不到模型具体做了什么工具调用、传了什么参数、得到了什么结果。出了问题难以调试。

**解决**：MiMo Code 将所有工具调用**可视化展示**在终端中：

```
  🔧 read_file({"path":"config.py"})
     → DEFAULT_HOST = "localhost" ...
  🔧 edit_file({"path":"config.py","old_string":"DEFAULT_HOST...","new_string":"DEBUG = False\n\nDEFAULT_HOST..."})
     → 已修改 config.py（1 处替换）
```

每一步工具调用、参数、返回值都透明展示，用户可随时中断并纠正方向。这对调试 Agent 行为和建立信任至关重要。

### 痛点 4：多模态模型缺乏便捷的本地测试入口

**问题**：MiMo-V2.5 支持文本、图像、视频、音频全模态输入，但要测试这些能力通常需要写脚本或使用网页端手动上传。

**解决**：MiMo Code 的 `@` 文件引用语法天然支持多模态：

```bash
# 文本分析
@main.py 解释这段代码的逻辑

# 图片分析（自动 base64 编码发送给 MiMo）
@screenshot.png 这个页面的布局有什么问题？如何优化？
```

图片自动检测、自动编码、自动以 OpenAI 多模态格式发送。开发者不用写任何额外代码。

## 三、具体成果

| 维度 | 成果 |
|------|------|
| **代码规模** | 7 个文件，~1200 行 Python 代码 |
| **工具系统** | 6 个工具（read/write/edit/search/list/shell），含命令白名单安全机制 |
| **Agent 循环** | 支持最多 8 轮工具调用链，流式解析 tool_calls 分片 |
| **多模态** | 图片自动编码 + 多模态 content 数组，支持 6 种图片格式 |
| **Token 统计** | API 真实 usage 解析 + 会话级累计统计 |
| **安全设计** | Shell 命令白名单 + 路径遍历防护 + edit 唯一匹配校验 |
| **测试覆盖** | 14 项测试全部通过（CLI/模块/工具/HTTP mock/安全边界） |
| **开源协议** | MIT 协议，GitHub 公开仓库 |

## 四、典型使用场景

| 场景 | 说明 |
|------|------|
| Agent 多轮工具调用 | 模型自主规划并执行多步代码修改，每步基于前一步结果推理 |
| 全项目代码审查 | 多文件 @ 引用一次性加载，模型跨文件分析依赖关系和潜在问题 |
| 长上下文编程会话 | 10+ 轮 Agent 交互持续累积上下文，模型不断深化对项目的理解 |
| 多模态分析 | 截图 + 文本输入，模型分析 UI 布局、设计问题并给出代码级建议 |

## 五、技术架构

```
┌──────────────────────────────────────────┐
│                 main.py                  │
│  CLI 入口 / REPL 循环 / Agent 循环 /      │
│  @文件解析 / 图片处理                    │
└──────┬──────────────┬──────────┬─────────┘
       │              │          │
       ▼              ▼          ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│  tools.py │  │ session.py│  │  mimo_    │
│  6 个工具  │  │ 会话管理  │  │ client.py │
│  安全执行  │  │ JSON 持久化│  │ API 通信  │
│  白名单    │  │ Token 统计│  │ 流式+工具  │
└──────────┘  └──────────┘  │ 多模态编码 │
                            └──────────┘
                                  │
                                  ▼
                        ┌──────────────────┐
                        │  MiMo API        │
                        │  (OpenAI 兼容)    │
                        │  platform.       │
                        │  xiaomimimo.com  │
                        └──────────────────┘
```
