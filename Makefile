# 变量定义
PYTHON := python
PIP := pip
POETRY := poetry
BUILD_TOOL := nuitka

# 获取操作系统类型
ifeq ($(OS),Windows_NT)
    OS_TYPE := Windows
    RM_CMD := if exist
    RM_DIR := rd /s /q
    RM_FILE := del /f /q
    MKDIR := mkdir
else
    UNAME_S := $(shell uname -s)
    ifeq ($(UNAME_S),Linux)
        OS_TYPE := Linux
    endif
    ifeq ($(UNAME_S),Darwin)
        OS_TYPE := Darwin
    endif
    RM_CMD := rm -rf
    RM_DIR := rm -rf
    RM_FILE := rm -f
    MKDIR := mkdir -p
endif

# 默认目标
.DEFAULT_GOAL := help

.PHONY: install
install:  ## 安装项目依赖
	$(POETRY) install

.PHONY: install-dev
install-dev:  ## 安装开发依赖
	$(POETRY) install --with dev

.PHONY: clean
clean:  ## 清理构建和缓存文件
ifeq ($(OS_TYPE),Windows)
	$(RM_CMD) "main.build" $(RM_DIR) "main.build"
	$(RM_CMD) "main.dist" $(RM_DIR) "main.dist"
	$(RM_CMD) "__pycache__" $(RM_DIR) "__pycache__"
	$(RM_CMD) ".pytest_cache" $(RM_DIR) ".pytest_cache"
	$(RM_CMD) ".coverage" $(RM_FILE) ".coverage"
	for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
	for /r %%f in (*.pyc *.pyo *.pyd) do @if exist "%%f" del /f "%%f"
else
	$(RM_CMD) main.build/ main.dist/ __pycache__/ .pytest_cache/ .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "*.egg" -exec rm -rf {} +
endif

.PHONY: test
test:  ## 运行测试
	$(POETRY) run pytest tests/ -v

.PHONY: coverage
coverage:  ## 运行测试覆盖率报告
	$(POETRY) run pytest --cov=src tests/ --cov-report=term-missing

.PHONY: lint
lint:  ## 运行代码检查
	$(POETRY) run flake8 src/ tests/
	$(POETRY) run mypy src/ tests/

.PHONY: format
format:  ## 格式化代码
	$(POETRY) run black src/ tests/
	$(POETRY) run isort src/ tests/

.PHONY: build
build:  ## 构建可执行文件
ifeq ($(OS_TYPE),Windows)
	$(POETRY) run $(BUILD_TOOL) --standalone --msvc=latest --windows-console-mode=disable --enable-plugin=pyside6 --windows-icon-from-ico=assets/app.ico --output-dir=dist --output-filename=FinancialAutomation main.py
else
	$(POETRY) run $(BUILD_TOOL) --standalone --enable-plugin=pyside6 --output-dir=dist --output-filename=FinancialAutomation main.py
endif

.PHONY: requirements
requirements:  ## 导出requirements.txt
	$(POETRY) export -f requirements.txt --output requirements.txt --without-hashes

.PHONY: check
check: lint test  ## 运行所有检查（lint和test）

.PHONY: dist
dist: clean build  ## 构建分发包

.PHONY: dev-setup
dev-setup: install-dev format lint  ## 设置开发环境

.PHONY: help
help:  ## 显示帮助信息
	@echo "使用方法:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' 