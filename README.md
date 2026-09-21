# agent-decode

通过场景与源码，逐步理解 Agent 技术栈。

源码学习以 OpenAI Codex 为主，其他开源项目用于有明确价值的对比；最小教学示例与上游真实实现分别讲解。

面向程序员，聚焦协议、实现机制、失败语义与工程取舍，同时覆盖面试中值得准备的技术问题。内容先以中文编写，中文课程完成后再扩展多语言。

从一次 LLM 调用出发，让一个小型教学 Agent 逐步学会使用工具、持续完成任务、管理上下文，并在明确的权限与验证机制下运行。每一步都由当前场景的问题引出新的技术方案，再连接到下一个问题。

## 项目文档

- [第一章：一次 LLM 调用——三类 API 与流式处理](docs/chapters/01-llm-apis-and-streaming.mdx)：Chat Completions、Responses、Messages、SSE、终态与面试追问。
- [第二章：模型说要读文件，文件就会被读取吗？](docs/chapters/02-tool-call-requests.mdx)：工具定义、Schema、调用身份与 Codex 工具路由。
- [第二章代码与运行说明](examples/ch02_tool_call/README.md)：识别工具请求，保留参数与调用 ID，暂不执行工具。
- [第一章代码与运行说明](examples/ch01_llm/README.md)：Python 标准库实现，支持无密钥离线回放与可选真实调用。
- [课程路线草案](docs/curriculum-roadmap.md)：首批六章、知识依赖图、后续专题与章节验收标准。
- [教学参考与源码案例调研](docs/source-study.md)：参考项目的教学方法、固定版本源码入口与多项目对比方向。
- [项目约定](AGENTS.md)：内容编写、网站技术选型与交付要求。

前两章内容与配套示例已编写，其余章节仍在设计中，网站尚未搭建。计划使用 Docusaurus 承载 Markdown/MDX 内容，按需加入 React 交互图解。源码案例与教学简化实现分别标注；离线测试与真实 API 验证分别记录。
