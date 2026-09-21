# 第二章：让模型提出工具调用请求

Python 3.10+，仅标准库。在第一章的 OpenAI Responses 请求上增加 `read_file` 自定义函数定义，解析完整响应后停止。这里没有工具执行器，不读取目标文件、不提交 `function_call_output`，也没有 Agent Loop。

## 离线观察三种结果

从仓库根目录执行：

```bash
python3 examples/ch02_tool_call/client.py --demo tool
python3 examples/ch02_tool_call/client.py --demo text
python3 examples/ch02_tool_call/client.py --demo mixed
```

这些是明确标记的合成数据，不是模型实测结果，不读取 API 凭据，也不联网。分别展示工具请求、纯文本、文本与工具请求混合的响应。程序复用第一章的请求基础字段、官方 URL、鉴权头和禁止重定向逻辑；不会修改第一章示例。

## 查看请求与真实调用

```bash
python3 examples/ch02_tool_call/client.py --model YOUR_MODEL_ID --show-request
python3 examples/ch02_tool_call/client.py --model YOUR_MODEL_ID
```

`YOUR_MODEL_ID` 替换为账号可用且支持此工具配置的模型。第一条只打印请求体，不联网、不显示鉴权头。第二条从环境变量 `OPENAI_API_KEY` 读取凭据，向官方 Responses 端点发送一次非流式请求。可用 `--prompt` 覆盖问题；不会从当前目录自动搜集文件内容。

请求使用 `tool_choice: auto`，模型可以直接输出文本，也可以请求工具。`parallel_tool_calls: false` 限制本次生成的并行调用；解析器仍扫描全部 `output`，离线测试也覆盖多条调用，不靠 `output[0]` 或请求配置来猜响应形状。示例不保证模型一定请求 `README.md`。

## 解析到哪里为止

`parse_response` 要求响应及文本/函数条目已完成，检查响应结构、已知工具名称、非空且唯一的 `call_id`、条目 `id`，并把完整 `arguments` 字符串解码为 JSON 对象。拒绝不完整 JSON、非对象、重复 JSON 键和非 JSON 数值常量。`reasoning` 条目不作为正文或工具调用。

- `response_id` 标识整个响应。
- `calls[].item_id` 来自函数条目的可选 `id`，标识输出条目；未提供时保留为 `null`。
- `calls[].call_id` 用于后续关联工具结果，不能拿条目 ID 或响应 ID 替代。
- `calls[].arguments` 仍是待校验的数据；`validation: pending` 不代表 Schema 验证成功。
- `execution: not_executed` 表明程序没有执行任何请求。

服务端的 `strict: true` 不替代宿主侧校验。这里故意保留 `{"path":123}`、多余字段或 `../../outside` 等对象为待校验数据，既不声称实现完整 JSON Schema 验证，也不授权任何路径。下一章才处理参数校验、路径边界和实际执行。

不完整响应、未知输出、未知工具和协议错误以非零退出码结束。拒绝内容单独输出在 `refusals`，CLI 返回非零退出码；不会把拒绝当成普通回答或可执行请求。网络不自动重试，60 秒是 socket 操作超时。

## 验证

```bash
python3 -m unittest discover -s examples/ch02_tool_call -v
python3 -m py_compile examples/ch02_tool_call/client.py examples/ch02_tool_call/test_client.py
```

测试使用独立手写的响应对象，覆盖混合输出、多个调用、ID 关联、无效参数编码、不完整响应、拒绝及离线模式。未调用真实模型 API。
