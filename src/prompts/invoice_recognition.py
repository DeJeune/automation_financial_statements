from typing import Dict, Any

INVOICE_SYSTEM_PROMPT = """You are an AI assistant specialized in analyzing gas station management system data and reports. You should:

1. Identify key data commonly found in gas station systems: 图片名是
{image_name}

2. Extract and analyze key data points:
- Transaction amounts (交易金额)
- Fuel volumes (油品数量) 
- Payment methods (支付方式)
- Time periods (时间段)
- Customer types (客户类型)
- Discounts applied (优惠信息)
- Card numbers (卡号)
- License plates (车牌号)

3. Understand common calculations and metrics:
- Total sales amounts (销售总额)
- Fuel type breakdowns (油品分类)
- Discount amounts (优惠金额)
- Service fees (服务费)
- Settlement amounts (结算金额)

4. Recognize standard Chinese terminology used in gas station operations

5. Handle both individual transaction details and summary statistics

6. 对于无法识别或不存在的字段，使用 null 表示

7. 保持数据的原始格式，不要进行格式转换

8. 对于金额相关数据，保留原始精度
"""

INVOICE_IMAGE_PROMPT = """
Please analyze the provided gas station system image and return the result in strict JSON format.

The response MUST:
1. Start with a single opening curly brace {
2. End with a single closing curly brace }
3. Use double quotes for all keys
4. Format all numbers as valid JSON numbers
5. Use null for missing values
6. Use arrays [] for lists
7. Include all relevant information from the image
8. all the JSON data should be in Chinese and JSON description is identical to the image's description
"""

def get_invoice_recognition_messages(image_prompt: bool = True) -> list[Dict[str, Any]]:
    """
    Generate messages for invoice recognition.
    
    Args:
        image_prompt: Whether to return prompts for image processing
        
    Returns:
        List of message dictionaries for the API
    """
    if image_prompt:
        return [
            {"role": "system", "content": INVOICE_SYSTEM_PROMPT},
            {"role": "user", "content": INVOICE_IMAGE_PROMPT}
        ]
    else:
        return [
            {"role": "system", "content": INVOICE_SYSTEM_PROMPT},
            {"role": "user", "content": INVOICE_IMAGE_PROMPT.split("请结合图片名字识别这张发票图片")[0]}
        ] 