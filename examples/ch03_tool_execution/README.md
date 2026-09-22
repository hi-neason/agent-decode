# 第三章：执行工具并把结果交回模型

在仓库根目录运行，使用 Python 3 标准库。示例复用前两章的请求配置和响应验证，不增加依赖。

```bash
python3 examples/ch03_tool_execution/client.py --demo
python3 -m unittest examples.ch03_tool_execution.test_client -v
python3 examples/ch03_tool_execution/client.py --model YOUR_MODEL --show-request
```

`--demo` 不联网、不读取凭据。它在临时目录生成一份教学 README，真正执行受限的文件读取，再由手写模拟响应引用工具结果。第二次回答不是模型生成，也不证明模型会正确使用工具。

## 真实调用

创建专用样本目录，只放愿意发给模型的文件，设置 `OPENAI_API_KEY` 后运行：

```bash
mkdir -p /tmp/agent-decode-ch03-sample
# 自行在这个目录中准备 README.md 等可公开的样本文件。
python3 examples/ch03_tool_execution/client.py \
  --model YOUR_MODEL \
  --root /tmp/agent-decode-ch03-sample
```

真实调用必须显式提供 `--root`，没有默认工作目录。目录中的文件内容会作为工具结果发送到 OpenAI Responses API；目录也应避免密钥等私密文件。模型需支持 Responses API、自定义函数及请求中的推理内容回传选项。本次实现只完成离线验证，未调用真实模型。

## 一次执行批次，两次模型请求

1. `build_request` 沿用第二章的 `read_file` 定义，使用 `store=false`，请求 `reasoning.encrypted_content`。
2. `inspect_response` 复用第二章的响应结构、完成状态和调用 ID 检查。工具名和参数验证移动到执行阶段，使未知工具、坏参数可以分别得到错误结果；原始响应不被修改。
3. `dispatch` 从 `REGISTRY` 查找白名单处理器，解码参数、拒绝重复 JSON 键和非 JSON 数字，再验证字段与路径。每个可配对的调用都得到一个 `function_call_output`。
4. `read_file` 打开受信任根目录下的普通 UTF-8 文件，最多读取 4097 字节以判断是否超过 4096 字节上限。截断只舍弃上限处未完成的 UTF-8 字符，其他无效编码仍返回错误。
5. 第二个请求保留原用户输入和**第一次完整的原始 `output`**，包括 reasoning、文本和函数调用，追加工具结果。`call_id` 使用原值；没有用响应 ID 或输出项 ID 替代。
6. 第二个响应无论是否继续请求工具都停止。`further_calls_not_executed` 表示下一批请求尚未执行，留待第四章引入 Agent Loop。

首个响应只有文本时只发一次请求。任一响应包含 refusal 都停止；第一次 refusal 即使混有函数调用也不执行工具。每次响应必须完整成功后才进入下一步；损坏的协议结构、重复或缺失的调用 ID 不能安全配对，会终止流程，而非伪造结果。

## 结果与错误

工具结果 `output` 是 JSON **字符串**，应用内部结构为：

```json
{"ok":true,"data":{"path":"README.md","content":"示例内容","truncated":false,"returned_bytes":12,"byte_limit":4096}}
```

失败示例：

```json
{"ok":false,"error":{"code":"file_not_found"}}
```

错误码包括 `unknown_tool`、`invalid_arguments`、`invalid_path`、`file_not_found`、`not_regular_file`、`invalid_utf8`、`file_access_denied`、`io_error`。访问权限或路径组件被拒绝使用 `file_access_denied`；磁盘 I/O 故障、描述符耗尽等其他系统错误使用 `io_error`，不暴露底层异常文本。这是教学应用自定义的协议，不是 Responses API 的固定错误格式。单次工具失败会交回模型，不阻止同一批其他调用处理；API/传输失败则停止，不自动重试。

CLI 返回 0 表示完成这个有限流程或首次无调用；不保证所有工具成功，也不证明模型回答正确。拒绝、未执行的后续调用、协议或传输失败返回非零状态。查看 `tool_outputs` 中每个 `ok` 判断具体执行结果。

## 文件访问边界

本例要求 macOS/Linux 等支持 `dir_fd`、`O_DIRECTORY`、`O_NOFOLLOW` 和 `O_NONBLOCK` 的 POSIX 环境；不支持时直接报错，不退化为不安全的字符串拼接。根目录由调用者提供并信任其选择过程，最终目录本身不允许是符号链接。

对模型提供的相对路径，拒绝绝对路径、`..`、`.`、空路径段、反斜杠和 NUL；逐级使用目录描述符和 `O_NOFOLLOW` 打开，避免“先 resolve 检查，再按路径打开”的符号链接替换窗口。叶子节点使用非阻塞打开并通过 `fstat` 只允许普通文件，FIFO 不会阻塞等待写入。所有描述符通过 `finally` 关闭。

这只是教学用的文件读取边界，不是通用 Sandbox：可信样本目录不应被恶意进程并发重命名或修改，不提供硬链接/挂载隔离、文件快照、进程隔离、网络权限、超时取消或指令注入防护。示例也未实现持久化执行日志；若工具执行后第二次 API 调用失败，不能把这理解成“工具没有执行”。本章只有读取动作；有副作用的工具需要进一步设计重试与幂等性。
