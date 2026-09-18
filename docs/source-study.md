# 教学参考与源码案例调研

调研日期：2026-09-17。本文保留初版调研证据；2026-09-18 起根据项目决策以 Codex 为主，Pi 等作为补充。当前安排见 [课程路线](curriculum-roadmap.md)。首章现已按读者要求纳入三类 API 与流式处理，[第一章](chapters/01-llm-apis-and-streaming.mdx)补充了官方 SDK 的固定版本证据。

## 调研范围与证据边界

本次只读检查已检出的本地 Git 快照、文档和关键实现，未更新上游、未运行这些项目的测试，也未进行真实模型调用。所列提交不代表上游最新版本。检查时这些参考仓库均无工作区修改。

下方源码链接由已核实的 origin 和提交构成，用于固定阅读版本；文件、符号和行号在本地快照中核对过，未联网验证链接可访问性。本文不声称任何未运行的功能通过了验证。

| 项目 | 上游仓库 | 本次提交 | 研究深度 |
| --- | --- | --- | --- |
| learn-claude-code | [shareAI-lab/learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) | `0dcafa2ae053a1ddd6a72f265431104b08a5aa13` | README、初始章节与代码、后续章节结构 |
| Pi | [earendil-works/pi](https://github.com/earendil-works/pi) | `71dca871bc80b6bc97be37f0ca3189399d651fff` | 循环、工具执行边界与 Provider 定点检查 |
| Hermes Agent | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | `7b6e0d3848cea58a1e784c80cccd446073e78828` | 循环预算、工具分发与分段调度 |
| Codex | [openai/codex](https://github.com/openai/codex) | `5b1d6560181680f95cde95c14ed042acc02248ed` | 请求构造、工具路由、继续条件与审批边界 |
| Gemini CLI | [google-gemini/gemini-cli](https://github.com/google-gemini/gemini-cli) | `9c1b0a610534d6f8120964cf2672c07807d8fc90` | 权限策略入口定位 |
| AgentScope | [agentscope-ai/agentscope](https://github.com/agentscope-ai/agentscope) | `254c81a41c454c0cccb4cb2e2be4dac12989163c` | 状态驱动循环入口定位 |
| LangChain | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | `15b5f57b3d78071be7cf9d7acf71aa8264b2f191` | Agent 状态图构建入口定位 |

## 教学参考：借鉴递进方法，重新划分首章

`learn-claude-code` 明确说明它是理解设计后自行构建的课程，不是照抄源码。因此可以引用其教学组织方式，不能由其 Python 实现推断 Claude Code 产品的实际行为。

| 观察 | 固定版本证据 | 对课程的影响 |
| --- | --- | --- |
| 当前根目录采用 17 章；旧 `agents/` 目录是另一套章节布局 | [README-zh.md：版本说明](https://github.com/shareAI-lab/learn-claude-code/blob/0dcafa2ae053a1ddd6a72f265431104b08a5aa13/README-zh.md#L235) | 引用时明确版本与章节路径，避免混用编号 |
| 首章从“人替模型执行命令并回传结果”的问题引出循环 | [s01 README：问题](https://github.com/shareAI-lab/learn-claude-code/blob/0dcafa2ae053a1ddd6a72f265431104b08a5aa13/s01_agent_loop/README.zh.md#L12) | 保留场景与新问题之间的衔接 |
| 首章已包含 bash 定义、字符串禁用检查、Shell 执行和模型循环 | [s01 code.py：工具与循环](https://github.com/shareAI-lab/learn-claude-code/blob/0dcafa2ae053a1ddd6a72f265431104b08a5aa13/s01_agent_loop/code.py#L58-L115) | 拆成 C01–C04，先用受限只读工具；不把字符串检查当作系统沙箱 |
| 第二章通过替换工具分发保留循环主体 | [s02 README：解决方案](https://github.com/shareAI-lab/learn-claude-code/blob/0dcafa2ae053a1ddd6a72f265431104b08a5aa13/s02_tool_use/README.zh.md#L20) | 每章标出相对上一章的最小变化 |
| 后期并非所有章节都严格累积；s17 使用更小工具池单独讲目标续跑 | [README-zh.md：后期阶段](https://github.com/shareAI-lab/learn-claude-code/blob/0dcafa2ae053a1ddd6a72f265431104b08a5aa13/README-zh.md#L264) | 高级主题允许独立分支，写清前置和集成关系 |
| 项目说明“理解核心设计，然后自己构建” | [README-zh.md：教学定位](https://github.com/shareAI-lab/learn-claude-code/blob/0dcafa2ae053a1ddd6a72f265431104b08a5aa13/README-zh.md#L474) | 单独标记教学重建与真实源码案例 |

我们保留“一个问题推动一次机制变化”的方式，先完成一次调用、工具请求、宿主执行与回传、循环四个独立学习目标，再扩展工程机制。

## 主要源码学习项目：Codex

源码学习以 Codex 为主。此版本的核心循环在 `session/turn.rs`；先理解最小机制，再沿以下入口阅读真实工程边界。

| 学习问题 | 文件与符号 | 已核实内容 |
| --- | --- | --- |
| API 请求有哪些显式字段？ | [`client.rs` · `build_responses_request`](https://github.com/openai/codex/blob/5b1d6560181680f95cde95c14ed042acc02248ed/codex-rs/core/src/client.rs#L881-L901) | 构造 Responses 请求，包含 `input`、`tools`、`tool_choice`、流式和并行调用等字段 |
| 输出项目怎样成为工具调用？ | [`tools/router.rs` · `build_tool_call`](https://github.com/openai/codex/blob/5b1d6560181680f95cde95c14ed042acc02248ed/codex-rs/core/src/tools/router.rs#L242-L296) | 将不同 `ResponseItem` 转换为内部调用，保留调用 ID 与参数载荷；转换不等于执行 |
| 工具执行怎样推动下一轮？ | [`stream_events_utils.rs` · 工具请求分支](https://github.com/openai/codex/blob/5b1d6560181680f95cde95c14ed042acc02248ed/codex-rs/core/src/stream_events_utils.rs#L332-L344) | 创建工具执行 future，同时设置 `needs_follow_up` |
| 工具之外还有什么继续条件？ | [`session/turn.rs` · `run_turn`](https://github.com/openai/codex/blob/5b1d6560181680f95cde95c14ed042acc02248ed/codex-rs/core/src/session/turn.rs#L535-L565) | 综合模型后续需要与待处理输入；[停止阶段](https://github.com/openai/codex/blob/5b1d6560181680f95cde95c14ed042acc02248ed/codex-rs/core/src/session/turn.rs#L642-L671)还涉及 stop hook |
| 谁把权限判断与环境接起来？ | [`tools/orchestrator.rs` · `ToolOrchestrator::run`](https://github.com/openai/codex/blob/5b1d6560181680f95cde95c14ed042acc02248ed/codex-rs/core/src/tools/orchestrator.rs#L125-L220) | 取得执行环境与权限，匹配跳过审批、禁止或需要审批等分支；用于 C06 的定点阅读 |

这只能证明上述代码边界，不能证明各平台的隔离效果。S01 编写前还需跟踪实际执行器、平台 Sandbox 与测试，并运行对应平台实验。

## 补充案例：Pi

Pi 的源码边界适合定点对照，但不再作为课程主案例。Provider 中仍有大量协议适配逻辑，C01 不应要求读者先理解整个文件。

| 学习问题 | 文件与符号 | 已核实内容 |
| --- | --- | --- |
| Agent 内部上下文怎样变成模型输入？ | [`agent-loop.ts` · `streamAssistantResponse`](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/agent/src/agent-loop.ts#L279-L310) | 经过 `transformContext`、`convertToLlm`，构造含 `systemPrompt`、`messages`、`tools` 的上下文后调用流函数 |
| 真正在哪调用 Messages API？ | [`anthropic-messages.ts` · 请求调用](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/ai/src/api/anthropic-messages.ts#L577) | 调用 `client.beta.messages.create(params, requestOptions).asResponse()`；仅定点核实，不据此概括整个 Provider |
| 工具描述怎样进入请求？ | [`anthropic-messages.ts` · `params.tools`](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/ai/src/api/anthropic-messages.ts#L1103) | 请求参数包含转换后的工具定义，可衔接 C02 与 P01 |
| 谁校验和执行工具？ | [`agent-loop.ts` · `prepareToolCall` 及相邻执行逻辑](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/agent/src/agent-loop.ts#L607-L710) | 查找工具、校验参数、调用前检查、取消检查与实际执行分开 |
| 一轮之后如何继续？ | [`agent-loop.ts` · `runLoop`](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/agent/src/agent-loop.ts#L156-L270) | 检查模型错误／取消、收集工具请求、执行并追加结果，还处理停止钩子与 follow-up 队列 |
| 多个工具怎样安排执行？ | [`agent-loop.ts` · `executeToolCalls`](https://github.com/earendil-works/pi/blob/71dca871bc80b6bc97be37f0ca3189399d651fff/packages/agent/src/agent-loop.ts#L409-L424) | 此处依据配置及工具声明对整个批次选择顺序或并行 |

教学中的“没有工具请求就结束”是最小模型。讲真实 `runLoop` 时必须补上错误、取消、停止钩子与后续输入，不能声称二者完全一致。

## 补充案例：Hermes 的预算与工具调度

当前快照已把职责拆到多个模块，不沿用“所有核心逻辑都在一个小型 `run_agent.py` 循环里”的旧印象。

| 学习问题 | 文件与符号 | 已核实内容 |
| --- | --- | --- |
| 对话入口在哪里？ | [`turn_facade.py` · `run_conversation`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/agent/turn_facade.py#L22-L54) | 门面转发到 `agent.conversation_loop.run_conversation` |
| 怎样控制循环次数？ | [`conversation_loop.py` · 循环控制](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/agent/conversation_loop.py#L1513-L1555) | 同时考虑 API 调用计数、共享迭代预算与 grace call；根据响应进入工具轮次或文本结束处理 |
| 工具轮次怎样接入执行器？ | [`turn_tool_round.py` · `run_tool_round`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/agent/turn_tool_round.py#L152) | 通过 `agent._execute_tool_calls(...)` 执行调用集合 |
| 怎样选择执行方式？ | [`run_agent.py` · `AIAgent._execute_tool_calls`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/run_agent.py#L1274-L1296) | 多调用先规划执行段，再进入顺序、并行或分段执行器 |
| 为什么要分段？ | [`tool_dispatch_helpers.py` · `_plan_tool_batch_segments`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/agent/tool_dispatch_helpers.py#L155-L206) | 按路径读写冲突组织批次；读／读重叠允许并行，涉及写的冲突结束当前段，未知作用域形成顺序屏障 |

可形成的首个横向比较是：**同一轮出现多个工具请求，宿主如何决定能否并行？**

- Pi 在上述分发层对整个批次选择顺序或并行，依据配置和工具声明。
- Hermes 在上述分发层结合能力与路径冲突切分执行段。
- 对比实验应覆盖独立读取、读写同一文件、未知作用域与取消。源码已说明策略差异，但尚未运行实验，不能给出吞吐量或安全性排名；路径冲突调度也不等于安全沙箱。
- 首批 C03、C04 仍先串行执行，完成基础后再引入这个对比，避免把并发带进第一个工具实验。

## 后续候选：已定位，尚未完成机制解析

| 项目 | 待研究问题 | 起点与当前边界 |
| --- | --- | --- |
| Gemini CLI | 权限判断怎样结合工具参数与 MCP 来源？ | [`policy-engine.ts` · `PolicyEngine.check`](https://github.com/google-gemini/gemini-cli/blob/9c1b0a610534d6f8120964cf2672c07807d8fc90/packages/core/src/policy/policy-engine.ts#L600-L647)。已定位元数据、参数与工具类型处理；未核实全部优先级或隔离效果 |
| AgentScope | 如何显式选择 reasoning、acting、exit？ | [`_agent.py` · `_reply_impl` 内部循环](https://github.com/agentscope-ai/agentscope/blob/254c81a41c454c0cccb4cb2e2be4dac12989163c/src/agentscope/agent/_agent.py#L1124-L1215)。已定位 `_next_action` 和状态分支；未追踪所有状态及异常路径 |
| LangChain | 如何把循环表示成模型／工具状态图？ | [`factory.py` · `StateGraph` 构建](https://github.com/langchain-ai/langchain/blob/15b5f57b3d78071be7cf9d7acf71aa8264b2f191/libs/langchain_v1/langchain/agents/factory.py#L1187)及[节点添加](https://github.com/langchain-ai/langchain/blob/15b5f57b3d78071be7cf9d7acf71aa8264b2f191/libs/langchain_v1/langchain/agents/factory.py#L1543-L1547)。未完整解析条件边与 middleware 顺序 |
| Hermes | 记忆如何写入、加载和控制作用域？ | [`tools/memory_tool.py`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/tools/memory_tool.py#L172)及[`MemoryProvider`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/agent/memory_provider.py#L75)。仅定位，不把存在入口当作完整机制证据 |
| Hermes | Skill 如何发现、加载和维护？ | [`tools/skills_tool.py`](https://github.com/NousResearch/hermes-agent/blob/7b6e0d3848cea58a1e784c80cccd446073e78828/tools/skills_tool.py)。仅定位，留待 X02 专题 |

MCP 全链路、Plan Mode 权限切换、持久任务恢复、完整 Memory 生命周期与 Evolution 评估尚未完成源码核实，优先从 Codex 跟踪实现，再决定是否需要其他项目补充；不能把尚未核实的能力预先归给 Codex。

## 后续研究与停止条件

首批选材已有足够依据，可以进入 C01 样章。深入每个案例时再完成：固定提交 → 跟踪调用链 → 找到相关测试 → 运行最小实验 → 写出适用条件与限制。上游变更后更新快照和引用，不让新旧版本结论混用。

课程不需要先读完所有仓库。对当前章节而言，能解释核心机制、展示可观察行为并标清证据边界，即可进入下一章；未解决的问题留在专题研究任务中。
