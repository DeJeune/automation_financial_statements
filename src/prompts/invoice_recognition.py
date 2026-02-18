from typing import Dict, Any, Optional

INVOICE_SYSTEM_PROMPT = """You are an AI assistant specialized in analyzing gas station management system data and reports. You should:

1. Recognize standard Chinese terminology used in gas station operations

2. 对于无法识别或不存在的字段，使用 null 表示

3. 保持数据的原始格式，不要进行格式转换

4. 对于金额相关数据，保留原始精度
"""

# Category-specific schemas for structured output
CATEGORY_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "货车帮": {
        "type": "OBJECT",
        "properties": {
            "柴油统计": {"type": "STRING", "description": "柴油加油升数，例如 '20.06 升'", "nullable": True},
            "油站折扣": {"type": "STRING", "description": "油站折扣金额，例如 '15.75 元'", "nullable": True},
            "油站直降": {"type": "STRING", "description": "油站直降金额，例如 '1.20 元'", "nullable": True},
            "服务费": {"type": "STRING", "description": "服务费金额，例如 '1.60 元'", "nullable": True},
            "结算金额": {"type": "STRING", "description": "结算金额，例如 '131.45 元'", "nullable": True},
        },
        "required": ["柴油统计", "油站折扣", "油站直降", "服务费", "结算金额"],
    },
    "滴滴加油": {
        "type": "OBJECT",
        "properties": {
            "油品应收金额": {"type": "STRING", "description": "油品应收金额，例如 '4849.28'", "nullable": True},
            "油品预收金额": {"type": "STRING", "description": "油品预收金额，例如 '5026.42'", "nullable": True},
            "油品优惠合计": {"type": "STRING", "description": "油品优惠合计，例如 '341.58'", "nullable": True},
            "油品数量": {"type": "STRING", "description": "油品数量（升），例如 '682.00'", "nullable": True},
        },
        "required": ["油品应收金额", "油品预收金额", "油品优惠合计", "油品数量"],
    },
    "国通1": {
        "type": "OBJECT",
        "properties": {
            "订单金额": {"type": "STRING", "description": "订单金额，例如 '1000.00'", "nullable": True},
            "退款订单金额": {"type": "STRING", "description": "退款订单金额，例如 '100.00'", "nullable": True},
        },
        "required": ["订单金额", "退款订单金额"],
    },
    "国通2": {
        "type": "OBJECT",
        "properties": {
            "订单金额": {"type": "STRING", "description": "订单金额，例如 '1000.00'", "nullable": True},
            "退款订单金额": {"type": "STRING", "description": "退款订单金额，例如 '100.00'", "nullable": True},
        },
        "required": ["订单金额", "退款订单金额"],
    },
    "团油": {
        "type": "OBJECT",
        "properties": {
            "加油升数汇总": {"type": "STRING", "description": "加油升数汇总，例如 '35.71升'", "nullable": True},
            "加油金额汇总": {"type": "STRING", "description": "加油金额汇总，例如 '300.00元'", "nullable": True},
            "实际结算金额汇总": {"type": "STRING", "description": "实际结算金额汇总，例如 '286.29元'", "nullable": True},
            "通道费汇总": {"type": "STRING", "description": "通道费汇总，例如 '3.00元'", "nullable": True},
        },
        "required": ["加油升数汇总", "加油金额汇总", "实际结算金额汇总", "通道费汇总"],
    },
    "POS": {
        "type": "OBJECT",
        "properties": {
            "结算总金额": {"type": "STRING", "description": "结算总金额，例如 '1000.00元'", "nullable": True},
        },
        "required": ["结算总金额"],
    },
    "超市销售收入": {
        "type": "OBJECT",
        "properties": {
            "现金": {"type": "STRING", "description": "班次交款（含备用金）下的现金金额，例如 '1000.00'", "nullable": True},
        },
        "required": ["现金"],
    },
    "抖音": {
        "type": "OBJECT",
        "properties": {
            "用户侧划线价合计": {"type": "STRING", "description": "用户侧划线价的求和值，例如 '1300'", "nullable": True},
            "订单实收合计": {"type": "STRING", "description": "订单实收的求和值，例如 '1213'", "nullable": True},
            "预计收入合计": {"type": "STRING", "description": "预计收入的求和值，例如 '1196.45'", "nullable": True},
        },
        "required": ["用户侧划线价合计", "订单实收合计", "预计收入合计"],
    },
}

# Category-specific prompts (simplified, schema handles structure)
CATEGORY_PROMPTS: Dict[str, str] = {
    "货车帮": "请分析货车帮加油系统的截图，提取柴油统计、油站折扣、油站直降、服务费、结算金额。",
    "滴滴加油": "请分析滴滴加油系统的截图，提取油品应收金额、油品预收金额、油品优惠合计、油品数量。",
    "国通1": "请分析国通加油系统(类型1)的截图，提取订单金额、退款订单金额。",
    "国通2": "请分析国通加油系统(类型2)的截图，提取订单金额、退款订单金额。",
    "团油": "请分析团油系统的截图，提取加油升数汇总、加油金额汇总、实际结算金额汇总、通道费汇总。",
    "POS": "请分析POS系统的截图，提取结算总金额。",
    "超市销售收入": "请分析超市销售收入的截图，提取班次交款（含备用金）下的现金金额。",
    "抖音": "请分析抖音来客的团购对账截图，提取表格最后一行求和/合计行中的用户侧划线价合计、订单实收合计、预计收入合计。",
}

INVOICE_IMAGE_PROMPT = """请分析加油站系统截图并提取数据。图片名是{image_name}，图片类别是{category}。

{category_specific_prompt}

请严格按照 schema 定义的字段返回数据，保留原始数值和单位。无法识别的字段使用 null。
"""


def get_category_schema(category: str) -> Optional[Dict[str, Any]]:
    """
    Get the structured output schema for a category.

    Args:
        category: The category of the image

    Returns:
        JSON Schema dict, or None if category has no schema
    """
    return CATEGORY_SCHEMAS.get(category)


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
