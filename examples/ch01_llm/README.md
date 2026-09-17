# 第一章：一次 LLM 调用

Python 3.10+，仅使用标准库。这个例子显式展示三种 API 的请求结构、普通响应解析和 SSE 流式处理，不是通用模型 SDK，也不执行工具。

## 离线运行

从仓库根目录执行：

```bash
python3 examples/ch01_llm/client.py --api chat --demo --stream
python3 examples/ch01_llm/client.py --api responses --demo --stream
python3 examples/ch01_llm/client.py --api messages --demo --stream
```

`--demo` 回放程序内手写的合成数据，不读取凭据、不联网，不能证明真实模型调用成功。去掉 `--stream` 可以观察非流式结果；流式模式把文本增量写入 stdout，把终止状态和 usage 写入 stderr。

## 真实调用

Chat Completions 和 Responses 从 `OPENAI_API_KEY` 读取凭据；Messages 从 `ANTHROPIC_API_KEY` 读取凭据。先在本地环境中设置相应变量，再指定账号可用的模型 ID：

```bash
python3 examples/ch01_llm/client.py --api responses --model YOUR_MODEL_ID --stream
```

`YOUR_MODEL_ID` 是占位符。模型必须支持请求中的参数；不同模型的能力不能只凭 API 形状推断。示例只访问官方端点，不接受自定义代理端点，不自动重试，不跟随重定向。

检查将发送的请求体（不联网、不显示鉴权头）：

```bash
python3 examples/ch01_llm/client.py --api messages --model YOUR_MODEL_ID --stream --show-request
```

`--prompt` 可覆盖默认的仓库问题。程序不会读取仓库；改变提示词也不会让模型自动获得本地文件。

## 阅读代码

- `build_request`：三种请求字段的差异。
- `sse_events`：先增量解码 UTF-8，再按空行分帧，最后交给调用方解析 JSON；支持 LF、CR、CRLF、开头的 BOM、注释和多行 data。
- `parse_response` / `parse_stream`：各 API 的内容、usage 和终止语义。
- `call`：HTTP 请求与网络读取。60 秒是 socket 操作超时，不是整次生成的总时限。
- `demo`：供离线练习与测试使用的合成协议片段。

流式结果可能已经显示部分文本，但最终仍失败。Chat 必须收到成功的 `finish_reason` 和 `[DONE]`；Responses 必须收到 `response.completed`；Messages 必须收到成功的 `stop_reason` 和 `message_stop`。达到输出上限、流中错误或连接提前结束均返回非零退出码。`output_text.done` 只结束一个文本部分，不代表整个 Responses 请求完成，也不会被再次追加到答案。

失败时，程序把已解析的部分结果及 usage 标记为 `PARTIAL RESULT`，非流式文本也会保留；流式文本已经输出，不会重复打印。错误仅保留有长度与字符限制的结构化标识，如 `code`、`type` 和 `incomplete_details.reason`，不输出上游错误正文。默认输出预算为 512；对包含推理 token 的模型，这不等于 512 个可见输出 token。

这是有意收窄的文本示例：未实现工具、多模态、扩展思考事件、重连、通用事件重排或全部服务端扩展。Responses 最终结果中的 reasoning 元数据不当作正文；其他未支持的输出类型或事件会明确报错。OpenAI 文本拒绝内容以 `refused` 标记；Anthropic 的 `refusal` 终止原因会返回非零退出码。usage 保留各 API 原始字段；Messages 的累计计数覆盖旧值，不逐事件相加。

## 验证

```bash
python3 -m unittest discover -s examples/ch01_llm -v
python3 -m py_compile examples/ch01_llm/client.py examples/ch01_llm/test_client.py
```

测试覆盖协议解析与离线行为，未调用收费 API，也不能替代服务端兼容性验证。
