# Financial Statements Automation

This project automates the processing and analysis of financial statements using Large Language Models.

支持独立上传日报模板与 T-CD 简表模板，可共用源数据同时填写并分别导出。简表上传油品时间统计、加油明细、充值明细即可填写并交叉校验，油品优惠表可选，详见 [简表填写说明](docs/simple-report.md)。

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
