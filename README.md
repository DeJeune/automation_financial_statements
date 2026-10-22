# Financial Statements Automation

This project automates the processing and analysis of financial statements using Large Language Models.

支持独立上传日报模板与 T-CD 简表模板，可共用源数据同时填写并分别导出。简表上传油品时间统计、加油明细、充值明细即可填写并交叉校验，油品优惠表可选，详见 [简表填写说明](docs/simple-report.md)。

## 原生桌面版（NSH + Rust）

新版位于 `native/`，功能、后台任务和模块职责见 [架构文档](docs/architecture.md)。最终安装包不需要 Python、Node.js 或 Rust 运行时；Python 目录保留用于迁移期间的回归对比。

开发机需要 Rust stable 和对应系统的原生编译工具。以下命令从仓库根目录执行：

```sh
# macOS：下载经过 SHA-256 校验的固定 NSH 源码，应用关闭保护补丁，编译 CLI
./scripts/bootstrap-native.sh
native/.vendor/nsh/target/debug/nsh run native/app/App.tsx

# 格式、lint 和类型检查（Biome、rustfmt、Clippy、NSH）
./scripts/check-native.sh
./scripts/check-native.sh format   # 自动格式化

# 后台与界面测试（使用独立配置目录，关闭自动更新联网）
cargo test --locked --manifest-path native/Cargo.toml -p financial-engine -p financial-desktop
FINANCIAL_DISABLE_UPDATE_CHECK=1 FINANCIAL_DATA_DIR="$PWD/native/target/test-data" \
  native/.vendor/nsh/target/debug/nsh test native/app/App.test.tsx

# macOS 打包
native/.vendor/nsh/target/debug/nsh package native/app/App.tsx --target macos --name FinancialAutomation -o native/package
```

Windows 在 PowerShell 执行 `./scripts/bootstrap-native.ps1`，随后使用 `native/.vendor/nsh/target/debug/nsh.exe`；打包参数改为 `--target windows`。需要 Visual Studio C++ Build Tools、Windows SDK 和 LLVM。`.github/workflows/native.yml` 提供两平台构建及安装包产物；现有 Python 发布流水线暂时保留，不会因本次本地修改自动发布新版。

界面保留完整日期、上班/交班时间、油价、日报与简表独立模板、多张平台截图、文件预览、日志和分别导出。 点击“添加加油站”可在当前加油站后台处理时，继续上传另一日期或加油站的文件；各加油站标签支持命名、切换、排队、取消排队和独立重置，已完成结果分别导出，标签上的 × 用于关闭。后台任务按队列顺序执行，延续现有截图识别限流；状态仅保存在本次应用会话中。配置支持原有 `GEMINI_API_KEY`、`GEMINI_BASE_URL`、`GEMINI_MODEL` 环境变量及 `.env`，也可以在设置页保存。默认油价为 8.23，国通为可选。日志和设置保存在系统用户数据目录的 `Financial Automation` 下；清除日志按钮仅清空当前显示。

## Project Structure
```
.
├── src/                    # Source code
│   ├── api/               # FastAPI endpoints
│   ├── models/            # Model-related code
│   │   └── configs/       # Model configurations
│   ├── utils/             # Utility functions
│   └── config/            # Application configuration
├── tests/                 # Test files
└── docs/                  # Documentation
```

## Setup and Installation

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints for all functions
- Write tests for new features
- Update documentation as needed

## License

[Your License Here]

固定加油站列表会自动保存名称、油价、顺序与当前选择，重启后恢复；每日文件、日期和计算结果不沿用，避免混入上次报表。标签上的 × 用于确认移除站点，“重置当前加油站”仅清理当天任务。
