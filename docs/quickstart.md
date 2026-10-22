# 安装与使用

## 1. 环境

推荐 Ubuntu / Debian 或 Windows WSL2，Python 3.11+。若创建虚拟环境提示缺少 ensurepip，请先安装系统的 `python3-venv` 包。仅界面、普通题和文档导出需要 Python；编程执行额外依赖 Linux bubblewrap；默认平台交付需要 Node.js 20+ 和 Chrome。仅本地生成普通题及运行固定演示时可不安装浏览器组件。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
python -m scripts.doctor
python -m scripts.demo
bash start.sh
```

首次启动会创建空白 `data/review.json`、空来源列表及代码生成的 Excel 模板，不覆盖已有文件。所有本地工作数据都在忽略目录中。`requirements.lock.txt` 是 Linux / Python 3.12 的发布依赖快照，并非历史实验环境锁；其他环境可使用 `requirements.txt` 中的兼容版本范围安装。

`start.cmd` 是 Windows 的 WSL 启动入口，需要先在 WSL 内安装上述依赖。`bash start.sh --port 8877` 可换端口。Ctrl+C 关闭本次启动的 API/Worker；不要同时在多个路径启动同一工作区。WSL 中始终使用同一个大小写规范路径，避免 Windows 挂载盘上的 SQLite WAL 别名问题。

## 2. 模型配置

```bash
cp model-config.example.json model-config.local.json
```

编辑同一个 JSON 对象中的 `base_url`、`model`、`api_key`。示例以 DeepSeek 兼容服务为例，你可以改为支持 Chat Completions 的 HTTPS 服务。`base_url` 写 API 前缀，例如 `https://provider.example/v1`，不要追加 `/chat/completions`。模型须能按提示返回 JSON；字段语义依提供商而定。

```bash
python -m scripts.check_model_connection --check-only  # 只检查格式，不联网
python -m scripts.check_model_connection             # 一次有额度消耗的真实请求
```

也可用 `EDUCODER_MODEL_BASE_URL`、`EDUCODER_MODEL_MODEL`、`EDUCODER_MODEL_API_KEY` 覆盖字段。没有配置文件时，用环境变量还应明确选择 `backend`：建议保留示例文件中的 `"backend": "langchain"`。`trust_env: false` 默认不继承系统代理；网络需要代理时按自己的环境设为 `true`。Key 不应写入前端、截图或提交记录。

## 3. 编程题核验

在 Ubuntu / WSL 安装：

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap gcc g++
# 来源需要 Java 时额外安装 JDK，例如 openjdk-21-jdk
python -m scripts.doctor --programming
```

该检查会在隔离环境运行固定 hello-world，零 API 调用。仅检测到 `bwrap` 文件不代表可用：内核可能禁用了用户命名空间。检查失败通常与用户命名空间或系统安全策略有关，需使用支持该隔离能力的 Linux／WSL 环境。Python 使用 `/usr/bin/python3`，C/C++/Java 使用沙箱可见的系统编译器，不依赖虚拟环境中的自定义编译器。

## 4. 提交真实需求

平台交付前安装浏览器依赖：

```bash
npm ci
```

安装 Chrome，并在导入适配器打开的浏览器中使用自己的教师账号登录头歌；该会话保存在本地 `.browser-profile/`。日常 Chrome 的登录状态不一定与此独立配置目录共享，首次使用需完成登录。浏览器运行在 WSL 外时的配置见下方“浏览器题源读取”。

打开 <http://127.0.0.1:8765/>，填入知识范围、题型和数量，以及课堂“在线考试”列表页完整地址和平台已有的所属课程名称。按平台交付流程运行时，不勾选“仅本地生成”：保存为未发布试卷，配置并回读核对题目和编程用例，之后由教师在平台正式发布。

若只需要文件，勾选“仅本地生成”，无需填写平台目标或登录平台。需要资料时上传带文字层 PDF 或 DOCX，指定它们作为课程范围；课件上传不等于题目能自动覆盖每个知识点，最终仍需教师审阅。

也可以通过本地 API 提交平台交付任务，将示例中的课堂占位符和课程名替换为自己的目标：

```bash
curl -sS http://127.0.0.1:8765/api/agent-start \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"关于排序算法，包含2道单选题、2道判断题和2道填空题。","execute":true,"classroom_url":"https://www.educoder.net/classrooms/<classroom-id>/exercise","course":"你的课程名称"}'
```

平台交付时显式传入 `"execute": true`；仅本地生成时传入 `"execute": false`，可省略 `classroom_url` 和 `course`。

返回任务 ID 后，使用页面查看进度；`GET /api/agent-tasks/<id>` 查看结果，`GET /api/agent-events` 接收 SSE。完成后从任务卡下载 Excel、JSON 和编程评测包。教师评测包包含答案及隐藏用例，应留给教师使用。固定 `demo.py` 导出与网页当前任务状态相互独立，不会把固定题目伪装成模型生成结果。

## 5. 可选能力

**向量检索：**

```bash
python -m pip install -r requirements-retrieval.txt
python -m scripts.index_corpus --vectors --download-model
```

显式下载本地模型权重后，才会在 BM25 外启用向量与 RRF。运行期间不自动下载；缺依赖或权重明确降级 BM25。课程文本会发给你配置的推理服务，本地 embedding 不走远端 embedding API。

**浏览器题源读取：**

```bash
npm ci
```

安装 Chrome 后，HTTP 读取失败时可回退只读浏览器。没有 Node/Chrome 时保留访问失败信息，普通 HTTP 检索仍可使用。WSL 想连接 Windows Chrome 时，显式配置 `EDUCODER_BROWSER_NODE` 为 Windows `node.exe` 的 WSL 路径，`EDUCODER_PLAYWRIGHT_MODULE` 为该 Windows Node 可解析的 Playwright 目录；否则使用 PATH 中的 Node 和项目安装的依赖。可选 `EDUCODER_SOURCE_CDP_URL` 只接受本地调试端口。

**结构化搜索：** 可设置 `EDUCODER_TAVILY_API_KEY`，否则使用已有公开搜索路径；公开来源服务可能限流或拒绝访问。

**仅本地生成：** 勾选页面中的对应选项，或在 API 中设置 `execute=false`，即可导出文件而不交付平台。固定离线演示和 CI 使用本地路径或替身，无需平台账号。平台交付的浏览器和登录准备见上一节；仓库不包含真实课堂地址或会话，上游页面与权限变化可能需要调整适配器。

## 6. 常见运行问题

| 现象 | 处理方式 |
| --- | --- |
| 页面可打开，任务未执行 | 使用 `bash start.sh` 同时启动 API 和 Worker |
| 端口被占用 | 使用 `bash start.sh --port 8877` 指定其他端口 |
| 模型连接失败 | 运行 `python -m scripts.check_model_connection --check-only`，检查地址、权限、余额与限流信息 |
| 编程核验不可用 | 运行 `python -m scripts.doctor --programming`，确认 bubblewrap、系统编译器及用户命名空间可用 |
| 检索仅使用 BM25 | 未安装向量依赖或未准备本地权重时正常降级，向量配置见上文 |
| 扫描 PDF 无法提取内容 | 改用有文字层的 PDF 或 DOCX；直接 PPT 和图片公式暂不完整支持 |

任务需要处理时，可在页面查看失败阶段与已保留成果，修正配置后在原任务继续。本地输出位于 `outputs/`，包括参考答案与隐藏数据，应由教师保管。
