from typing import Dict, Any

INVOICE_SYSTEM_PROMPT = """You are an AI assistant specialized in analyzing gas station management system data and reports. You should:

1. Recognize standard Chinese terminology used in gas station operations

2. 对于无法识别或不存在的字段，使用 null 表示

3. 保持数据的原始格式，不要进行格式转换

4. 对于金额相关数据，保留原始精度
"""

# Category-specific prompts
CATEGORY_PROMPTS = {
    "货车帮": """
请分析货车帮加油系统的截图，提取以下关键信息并以JSON格式返回：
- 柴油统计
- 油站折扣
- 油站直降
- 服务费
- 结算金额

返回格式如下:
{
  "柴油统计": "20.06 升",
  "油站折扣": "15.75 元",
  "油站直降": "1.20 元",
  "服务费": "1.60 元",
  "结算金额": "131.45 元"
}
""",
    "滴滴加油": """
请分析滴滴加油系统的截图，提取以下关键信息并以JSON格式返回：
- 油品应收金额
- 油品预收金额
- 油品优惠合计
- 油品数量

返回格式如下:
{
  "油品应收金额": "4849.28",
  "油品预收金额": "5026.42",
  "油品优惠合计": "341.58",
  "油品数量": "682.00"
}
""",
    "国通1": """
请分析国通加油系统(类型1)的截图，提取以下关键信息并以JSON格式返回：
- 订单金额
- 退款订单金额

返回格式如下:
{
  "订单金额": "1000.00",
  "退款订单金额": "100.00"
}
""",
    "国通2": """
请分析国通加油系统(类型2)的截图，提取以下关键信息并以JSON格式返回：
- 订单金额
- 退款订单金额

返回格式如下:
{
  "订单金额": "1000.00",
  "退款订单金额": "100.00"
}
""",
    "团油": """
请分析团油系统的截图，提取以下关键信息并以JSON格式返回：
- 加油升数汇总
- 加油金额汇总
- 实际结算金额汇总
- 通道费汇总

返回格式如下:
{
  "加油升数汇总": "35.71升",
  "加油金额汇总": "300.00元",
  "实际结算金额汇总": "286.29元",
  "通道费汇总": "3.00元"
}
""",
    "POS": """
请分析POS系统的截图，提取以下关键信息并以JSON格式返回：
- 结算总金额

返回格式如下:
{
  "结算总金额": "1000.00元"
}
""",
    "超市销售收入": """
请分析超市销售收入的截图，提取以下关键信息并以JSON格式返回：
- 班次交款（含备用金）下的现金

返回格式如下:
{
  "现金": "1000.00"
}
"""
}

INVOICE_IMAGE_PROMPT = """
Please analyze the provided gas station system image and return the result in strict JSON format. 图片名是{image_name}，图片类别是{category}

{category_specific_prompt}

The response MUST:
1. Start with a single opening curly brace {{
2. End with a single closing curly brace }}
3. Use double quotes for all keys
4. Format all numbers as valid JSON numbers
5. Use null for missing values
6. Use arrays [] for lists
7. all the JSON data should be in Chinese and JSON description is identical to the image's description
"""


def get_invoice_recognition_messages(category: str, image_name: str) -> list[Dict[str, Any]]:
    """
    Generate messages for invoice recognition.

    Args:
        category: The category of the image (e.g., "货车帮", "滴滴加油", etc.)
        image_name: The name of the image file

    Returns:
        List of message dictionaries for the API
    """
    category_prompt = CATEGORY_PROMPTS.get(category, "")
    prompt = INVOICE_IMAGE_PROMPT.format(
        image_name=image_name,
        category=category,
        category_specific_prompt=category_prompt
    )

    return [
        {"role": "system", "content": INVOICE_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
