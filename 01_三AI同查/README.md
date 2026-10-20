# 三AI同查：使用说明

## 桌面测试界面

双击 `start_desktop.bat` 打开本地窗口。粘贴完整题干及选项，在题目框按回车或点击“开始三模型答题”发送；Shift+回车换行。三个模型固定同时请求，每个模型完成后立即在自己的列中显示答案或错误，无需等待其他模型；综合分析在三路都完成后显示。底部显示完成进度与耗时。可“载入示例”“清空题目”“复制完整结果”，完成一题后继续输入下一题。

也可点击“上传图片”选择一张 PNG/JPEG 题目截图，或复制截图后点击“粘贴图片”。题目框中 Ctrl+V 遇到剪贴板图片时附加截图，普通文字仍按原方式粘贴。附件行显示缩略图，可“移除图片”；“清空题目”同时清除文字和截图。支持只发图片，以及图片加补充文字；只发图片时自动要求识别题目和完整选项并作答。建议截图包含完整题干及选项，图片模糊时结果可能有误。

每次只附一张图片，源文件及转换后的 PNG 均最多 10 MiB，宽高均不超过 8192 像素。图片选择后仅在窗口内存保存；发送时将当次图片和题目放入独立临时目录，请求结束、停止或关闭窗口后删除，关闭或清空时释放图片内存。复制结果不包含图片数据或文件路径。发送时三家模型各自接收同一张截图，消耗对应 API 的图片用量；仍保留原模型、思考档位及并行逐条显示方式。

三个模型均通过 API 调用。默认使用已保存的加密密钥、GPT `gpt-6.1-sol / medium`、千问 `qwen3.8-max`、DeepSeek `deepseek-flash` 和本机 GPT 代理 `http://127.0.0.1:7897`；窗口内可修改代理，或留空使用系统网络，并调整每路超时。请求在后台运行，关闭窗口会停止当前请求并清理临时题目文件。界面不保存测试题历史。

点击“配置三模型 API”，或双击 `configure_apis.bat`，打开 DeepSeek、千问、GPT 三个标签页。选择要更换的模型，隐藏输入新密钥并填写 Base URL，点击“保存此模型”；可继续切换标签配置其他模型，最后关闭窗口。保存后下一次答题生效，无需重启程序；保存一家不会覆盖另外两家的配置。密钥留空会保留已有密钥，便于只修改地址。

自 v1.3.0 起，答题窗口提供“思考档位”按钮，分别选择 GPT 的低/中/高/更高/最高、千问的关闭/低/中/更高、DeepSeek V4.1 Flash 的关闭/低/高/最高。保存后立即更新三列标题，下一次答题使用新档位，重启仍保留。首次保持原来的 GPT 中档、其余两家关闭；档位保存在 `data/thinking.json`，与密钥独立。思考开启时增加输出预算；仍可能因平台限制或复杂题耗时而失败，错误会显示在对应模型中。

桌面按钮选择的档位优先；直接使用启动脚本时，可通过 `OPENAI_REASONING_EFFORT`、`QWEN_REASONING_EFFORT`、`DEEPSEEK_REASONING_EFFORT` 覆盖。千问允许 `off/low/medium/xhigh`，DeepSeek 允许 `off/low/high/max`，GPT 允许 `low/medium/high/xhigh/max`。`off` 表示关闭思考，GPT 不支持 `off`。模型名保持不变，DeepSeek 官方调用名 `deepseek-flash` 对应 V4.1 Flash。

地址需填写该密钥所属平台提供的 HTTPS Base URL，不要填写完整 `/responses` 或 `/chat/completions` 请求地址。GPT 默认 `https://api.openai.com/v1`，千问默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`，DeepSeek 默认 `https://api.deepseek.com`。OpenAI 官方 API 单独计费，ChatGPT 登录不能代替 API 密钥。

此入口使用 Windows 自带的 WinForms 组件，无需安装 Tkinter 或其他界面依赖；独立调用现有核心答题链。淘汰赛模考入口在相邻的 `02_淘汰赛模考/start.bat`。

## 三模型固定并行答题（命令行）

在项目目录打开 PowerShell，运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_solver.ps1 -GptProxy http://127.0.0.1:7897 "AIGC 的英文全称是什么？"
```

`run_solver.ps1` 使用本目录 `data/api-keys.dpapi.json` 中此前保存的 Windows DPAPI 加密密钥；仅当前 Windows 用户在本机可解密，不输出密钥。该文件被 Git 忽略；换电脑时重新设置环境变量。环境变量中的密钥优先于加密文件，也可用 `-CredentialFile` 指定同格式加密文件。

上述命令使用本机已有的 `7897` 端口代理。可直连 API 的电脑省略 `-GptProxy`，其他代理修改该地址。代理仅作用于 GPT 的 HTTP 请求，不改变 Qwen/DeepSeek 的网络配置。直接运行 Python 时可用环境变量 `OPENAI_PROXY_URL` 设置该代理；旧的 `-CodexProxy` 参数及 `CODEX_PROXY_URL` 环境变量仍兼容。

三家的配置均可在统一窗口中修改。原有 `configure_qwen.ps1` 和 `configure_openai.bat` 仍可使用。已有 API 密钥或地址环境变量时仍优先使用环境变量，需同时更新或清除旧值。

也可自行设置 `OPENAI_API_KEY`、`QWEN_API_KEY`（或 `DASHSCOPE_API_KEY`）和 `DEEPSEEK_API_KEY`，直接运行，无需额外安装 Python 依赖。第三方 GPT API 同时设置对应的 `OPENAI_BASE_URL`。环境变量优先于加密文件中的配置；如环境变量中有旧密钥或地址，需更新或清除：

```powershell
python solver.py "题干及选项"
python solver.py --file question.txt
python solver.py --image question.png
python solver.py --image question.jpg "请回答截图中的第二题"
```

PowerShell 启动脚本对应使用 `-Image question.png`；可同时指定 `-Question` 或 `-File` 补充说明。图片通过原生视觉接口提交：GPT Responses 使用 `input_text` 与 `input_image`；Qwen/DeepSeek Chat 使用 `text` 与 `image_url`。图片均为内联 data URL，不上传到额外图床。纯文字请求的接口格式保持原样。协议见 [OpenAI 图片输入说明](https://developers.openai.com/api/docs/guides/images-vision)、[DeepSeek 视觉说明](https://api-docs.deepseek.com/guides/vision/)、[千问视觉说明](https://docs.modelstudio.console.alibabacloud.com/zh/model-studio/vision)。自定义网关也需要支持对应模型的图片输入。

不带题目参数运行可输入多行题干及选项，以空行结束。`question.txt` 使用 UTF-8 编码；一份文件包含一道题。PowerShell 启动脚本对应使用 `-File question.txt`，可用 `-Timeout 180` 调整默认 120 秒的每路超时；Python 参数为 `--timeout 180`。

每道题固定用三个线程同时发起 GPT、Qwen、DeepSeek 请求，无条件调用 GPT，无串行判断或补充裁决。三家均通过 HTTP API 调用，GPT 使用配置的 OpenAI 兼容端点，千问和 DeepSeek 分别使用自己的端点和密钥。GPT 不再启动 Codex CLI。三家只接收同一题目和通用答题格式说明，互不共享答案；不读取原有题库，不使用训练、微调或 RAG。

GPT 默认指定 `gpt-6.1-sol`、推理强度 `medium`，使用 Responses 的 `reasoning.effort` 和 `max_output_tokens`，严格 JSON 输出且不传工具。可用 `OPENAI_MODEL`、`OPENAI_REASONING_EFFORT` 覆盖，接口见 [OpenAI Docs](https://developers.openai.com/api/docs/guides/migrate-to-responses)。第三方端点需要支持这些参数及模型 ID；返回错误时会显示在 GPT 列中，其他两家仍照常答题。

默认 Qwen 模型为 `qwen3.8-max`，调用 ID 见 [Qwen3.8-Max 官方文档](https://help.aliyun.com/zh/model-studio/qwen3-8-max)。DeepSeek 为 `deepseek-flash`。两家 API 模型可分别设置 `QWEN_MODEL`、`DEEPSEEK_MODEL`。API 端点由 `QWEN_BASE_URL` 和 `DEEPSEEK_BASE_URL` 配置；Qwen 的端点地域须匹配密钥。协议参考 [Qwen 官方文档](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope) 和 [DeepSeek 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

输出固定为题目、GPT、Qwen、DeepSeek、综合分析，每家显示答案和简短理由。比较时统一全角字符、多选字母顺序、判断题常见写法；简答题仅按规范化文本比较，同义表述可能被判为不一致。一家失败仍显示其他两家的结果，并标明无法完整比较。退出码：`0` 三路成功，`1` 至少一路失败，`2` 输入错误。三家一致不代表答案一定正确。

模考平台说明见相邻的 `02_淘汰赛模考/README.md`。


## 文件分类

- `start_desktop.bat`：双击打开三AI同查桌面窗口。
- `solver.py`、`desktop.ps1`、`run_solver.ps1`：答题程序及启动组件。
- `configure_qwen.ps1`：千问配置工具。
- `configure_openai.bat`、`configure_openai.ps1`：GPT API 密钥和地址配置工具。
- `configure_apis.bat`、`configure_apis.ps1`：三模型 API 统一配置入口。
- `data/`：原有加密API配置，已从公共数据目录移入本板块。
- `tests/`：三模型与桌面界面的现有验证文件。

验证：在本文件夹使用可用 Python 运行 `python -m unittest discover -s tests -v`。使用免安装包的隔离 Python 时，用 `python.exe -c "import sys,unittest; sys.path.insert(0,'.'); unittest.main(module=None,argv=['unittest','discover','-s','tests','-v'])"` 加载源码。测试使用模拟接口与临时配置，不需要真实 API 密钥；包含图片请求格式、非法图片、真实 WinForms 控件及临时文件清理验证。

米醋 API 使用 https://www.micuapi.ai/v1 或该平台提供的其他兼容地址。程序按其外接文档使用 Responses 协议和指定的 User-Agent；仅在该平台的已知主机名下添加这个请求头。分组需支持 GPT/Codex 及所填模型。
