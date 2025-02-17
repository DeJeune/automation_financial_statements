import os
import pytest


@pytest.fixture(autouse=True)
def setup_test_environment():
    """设置测试环境"""
    # 保存原始环境变量
    original_env = os.environ.get('APP_ENV')

    # 设置测试环境
    os.environ['APP_ENV'] = 'development'

    yield

    # 恢复原始环境变量
    if original_env is not None:
        os.environ['APP_ENV'] = original_env
    else:
        del os.environ['APP_ENV']
