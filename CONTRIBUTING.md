# 开发与发布

先按[安装与使用](docs/quickstart.md)准备 Python 3.11+ 环境，并完成可编辑安装。
以下命令均从仓库根目录执行。运行机制与边界见[系统架构](docs/architecture.md)。

## 目录约定

```text
CourseAgent/
├── src/courseagent/     # Python 服务、Agent、检索与核验
│   ├── __main__.py      # python -m courseagent
│   ├── paths.py         # 工作区根目录与只读资源位置
│   ├── web/             # 本地工作台 HTML / JavaScript
│   ├── browser/         # Node.js 题源读取与平台适配器
│   └── _vendor/         # 第三方实现、参考文件与许可证
├── tests/               # Python 离线回归；browser/ 为浏览器测试
├── scripts/             # 演示、环境检查、评估与发布工具
├── docs/                # 使用、架构与实验评估
├── examples/            # 原创固定输入
├── evaluations/         # 脱敏历史实验与数值汇总
└── .github/             # GitHub Actions 与 Issue 模板
```

`pyproject.toml` 定义 Python 包和命令行入口；`requirements*.txt` 分别提供兼容依赖、
固定快照和可选检索依赖，`package.json` 管理浏览器依赖与测试命令。

`data/`、`outputs/`、`.browser-profile/`、`.runtime/` 和 `*.local.json` 属于本地工作区，
由 `.gitignore` 排除。源码使用 `src` 布局，本地数据仍在仓库根目录读写；
静态页面和浏览器脚本由 `paths.py` 定位。

## 测试与构建

```bash
# 原创固定输入，阻断真实模型传输
python scripts/test_public.py
# API / Worker 子进程恢复、导出与 SSE 回放
python -m scripts.evaluate_infrastructure
# 固定示例的 Excel、JSON 与教师评测包导出
python -m scripts.demo

# 浏览器适配器使用本地页面测试
npm ci
npx playwright install chromium
npm test
npm run test:adapters
```

编程执行测试需要 Linux bubblewrap 与对应系统编译器。三个可选向量测试依赖 FAISS，
应单独报告跳过项。CI 使用 Python 3.12 和锁定依赖，无需模型凭据或平台登录。

单独运行 Python 套件：

```bash
python -m tests.run_offline_tests tests.test_api_service
```

检查源码包与 wheel：

```bash
python -m pip install build
python -m build
```

历史实验的数值复算命令集中在[实验记录](evaluations/README.md)。复算不发起模型请求，
也不重新进行内容评分；实验记录保留首次尝试、失败结果和重跑实际开销。

## 修改与反馈

正常任务默认平台交付，用户可选择仅本地生成。离线测试与 CI 使用本地路径或替身，不连接真实课堂。涉及任务租约、恢复、验证指纹和交付适配器的改动，应补充对应回归。
Bug 或 PR 请说明观察到的行为、最小原创复现输入和已完成的检查，移除凭据、账号信息、
课程材料和隐藏测试。运行与数据边界见 [SECURITY.md](SECURITY.md)。

## 发布到 GitHub

本目录即仓库根目录。`scripts/public_manifest.json` 是发布文件白名单，增加或移动文件时
同步更新清单，再检查并导出干净快照：

```bash
python scripts/audit_public.py
python scripts/export_public.py --output ../CourseAgent-github-release
```

先完成上文测试与构建。导出目标必须不存在；工具只复制清单文件，在目标目录生成
`PUBLIC_RELEASE_MANIFEST.json` 哈希收据，并在旁边生成 ZIP。本地数据、输出、会话、
配置、环境和缓存不进入快照。

在导出目录检查文件后，初始化 Git 仓库并添加自己的 GitHub 远端。保留许可证、
第三方归属说明和脱敏实验记录。历史实验仍按原有口径展示，发布整理不产生新的模型性能结论。
