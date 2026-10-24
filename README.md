# Financial Statements Automation

This project automates the processing and analysis of financial statements using Large Language Models.

支持独立选择日报模板与 T-CD 简表模板，可共用源数据同时填写。原生桌面版计算成功后直接保存到所选模板，并在同目录的“报表备份”文件夹保留写入前原件，无需导出。简表上传油品时间统计、加油明细、充值明细即可填写并交叉校验，油品优惠表可选，详见 [简表填写说明](docs/simple-report.md)。

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

Windows 在 PowerShell 执行 `./scripts/bootstrap-native.ps1`，随后使用 `native/.vendor/nsh/target/debug/nsh.exe`；打包参数改为 `--target windows`。需要 Visual Studio C++ Build Tools、Windows SDK 和 LLVM。`.github/workflows/native.yml` 提供两平台的检查、测试和原生安装包，并供 `release.yml` 复用。合并 PR 不发布；推送 `vX.Y.Z` 标签后，只有 Windows 与 macOS 全部检查及打包成功，才发布 Windows 安装程序和 macOS 应用 ZIP，不再执行 Python / Nuitka 打包。发布前须将 `native/app/nsh.json`、两个原生 crate 的 `Cargo.toml` 及 `native/Cargo.lock` 版本同步更新；标签必须与原生版本一致（当前为 `v2.0.0`），否则在构建前失败。

CI 先执行 `./scripts/bootstrap-native.sh --prepare-only`（Windows 为 `./scripts/bootstrap-native.ps1 -PrepareOnly`）下载、校验并修补 NSH 源码，再恢复 Rust 缓存，最后执行不带参数的引导脚本编译 CLI。仅准备源码时不需要 Rust。三个依赖私有附件的 Rust 测试默认标为忽略；在 `.context/attachments` 中提供对应样本后，执行 `cargo test --locked --manifest-path native/Cargo.toml -p financial-engine --test regression -- --ignored` 显式验证，缺少样本会报错。

界面保留完整日期、上班/交班时间、油价、日报与简表独立模板、多张平台截图、文件预览和日志。点击“计算并保存”后，每张报表独立计算、备份并原子保存回所选模板，成功后可预览；失败不覆盖原文件。模板不能与源数据或其他站点的报表共用同一文件。点击“添加加油站”可在当前加油站后台处理时继续上传其他文件，各站点支持命名、切换、排队、取消排队和独立重置，标签上的 × 用于关闭。重置和关闭标签只清理文件选择及临时预览，不删除已保存报表和备份。后台任务按队列顺序执行，延续现有截图识别限流。配置支持原有 `GEMINI_API_KEY`、`GEMINI_BASE_URL`、`GEMINI_MODEL` 环境变量及 `.env`，也可以在设置页保存。默认油价为 8.23，国通为可选。日志和设置保存在系统用户数据目录的 `Financial Automation` 下；清除日志按钮仅清空当前显示。

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
