from datetime import date, datetime
import re
import pandas as pd
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet
from pathlib import Path
from typing import Any, Dict, List, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def process_table_data() -> None:
    """处理Excel表格数据并保留原有格式

    功能：
    1. 使用pandas读取源数据文件并处理第三列数据
    2. 先清空目标文件中待更新的列
    3. 使用openpyxl更新目标文件中的对应数据
    4. 保留目标文件原有格式和样式

    异常：
        FileNotFoundError: 当源文件或目标文件不存在时
        ValueError: 当数据处理过程中出现无效数据时
    """
    # 创建输出目录
    output_dir = Path("output/table")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_file = "tables/抖音_20250208_151906.xlsx"
    target_file = "output/table/T-XW5-1.xlsx"

    try:
        result = process_douyin(source_file)
        updates = result['updates']
        print(updates)
        # workbook = openpyxl.load_workbook(target_file)

        # for update in updates:
        #     sheet_name = update['sheet']
        #     sheet = workbook[sheet_name]

        #     # 根据区域和机号更新数据
        #     target_section = update['section']
        #     if target_section in ['A', 'B', 'C']:
        #         current_section = None
        #         for row in sheet.iter_rows(min_row=3):
        #             # 如果当前行的section不为空，更新current_section
        #             if row[0].value is not None:
        #                 current_section = row[0].value.strip()

        #             # 使用current_section进行匹配
        #             if current_section == target_section:
        #                 product_name = row[1].value  # B列是机号
        #                 if not product_name:  # 跳过空行
        #                     continue
        #                 # 转换为字符串进行比较
        #                 normalized_product_name = normalize_product_name(
        #                     product_name)
        #                 normalized_update_name = normalize_product_name(
        #                     update['product_name'])
        #                 if normalized_product_name == normalized_update_name:
        #                     col_idx = get_column_index(update['column'])
        #                     row[col_idx].value = update['value']
        #                     break

        # # Save with optimization
        # workbook.save(target_file)
        # workbook.close()

    except FileNotFoundError as e:
        logger.error(f"文件不存在: {e}")
        raise
    except ValueError as e:
        logger.error(f"数据处理错误: {e}")
        raise
    except Exception as e:
        logger.error(f"处理过程中出现错误: {e}")
        raise


def process_time_statistics(path: Path) -> Dict[str, Any]:
    """Process 油品时间统计 table"""
    try:
        # 按第三列（C列）分组并处理数据
        df = pd.read_excel(
            path,
            skiprows=2,  # 跳过前两行
            usecols=[1, 2, 3],  # 只读取B、C、D列
            names=['机号', '油品', '加油升']
        )
        # 数据清洗和处理
        df['加油升'] = pd.to_numeric(df['加油升'], errors='coerce') / 3  # 数值处理
        df['加油升'] = df['加油升'].round(2)  # 保留两位小数

        # 清理油品列的空格
        df['油品'] = df['油品'].str.strip()

        # 油品类型与sheet区域的映射
        fuel_type_mapping = {
            '0#柴油': 'A',
            '92#汽油': 'B',
            '95#汽油': 'C'
        }

        # 构建更新指令
        updates = []
        for _, row in df.iterrows():
            if pd.notna(row['加油升']):  # 只处理非空值
                # 根据油品类型确定对应的区域
                section = fuel_type_mapping.get(row['油品'])
                if section:
                    updates.append({
                        'sheet': '调价前',
                        'section': section,  # 添加区域信息
                        'product_name': row['机号'],
                        'column': 'D',  # D列
                        'value': row['加油升']
                    })

        return {
            'updates': updates,
            'processed_data': df
        }

    except Exception as e:
        logger.error(f"处理时间统计表格错误: {str(e)}")
        raise


def process_douyin(path: Path) -> Dict[str, Any]:
    """Process 抖音 table for voucher transactions.

    Args:
        path: Path to the Douyin transaction file
        selected_work_start_time: Start time of the work period (only time part is used)
        selected_shift_time: End time of the work period (only time part is used)
        gas_price: Current gas price per unit

    Returns:
        Dictionary containing processed data and update instructions
    """
    try:
        df = pd.read_excel(
            path, usecols=['核销时间', '商品名称', '实际核销数量', '订单实收', '商家应得'])

        # Convert verification time strings to datetime
        df['核销时间'] = pd.to_datetime(df['核销时间'])

        start_datetime = datetime.strptime(
            "2025-02-05 08:00:00", "%Y-%m-%d %H:%M:%S")
        end_datetime = datetime.strptime(
            "2025-02-06 08:00:00", "%Y-%m-%d %H:%M:%S")

        gas_price = 7.25

        # 直接使用完整的datetime进行比较，处理跨天的情况
        mask = (df['核销时间'] >= start_datetime) & (df['核销时间'] <= end_datetime)

        filtered_df = df[mask]

        # Extract voucher amounts and calculate total value
        def extract_voucher_amount(product_name: str) -> float:
            try:
                # Extract the number before "元" from strings like "【春节不打烊】186代200元汽油代金券"
                amount = float(
                    ''.join(filter(str.isdigit, product_name.split('元')[0][-4:])))
                print(amount)
                return amount
            except Exception:
                logger.warning(
                    f"Could not extract voucher amount from: {product_name}")
                return 0.0

        filtered_df['voucher_amount'] = filtered_df['商品名称'].apply(
            extract_voucher_amount)
        total_voucher_value = (
            filtered_df['voucher_amount'] * filtered_df['实际核销数量']).sum()

        # Calculate required metrics
        total_received = filtered_df['订单实收'].sum()
        total_merchant_revenue = filtered_df['商家应得'].sum()
        total_discount = total_voucher_value - total_received
        handling_fee = total_received - total_merchant_revenue
        gas_quantity = total_voucher_value / \
            gas_price if gas_price > 0 else 0

        p = {
            'gas_quantity': round(gas_quantity / 3, 2),
            'total_discount': round(total_discount / 3, 2),
            'handling_fee': round(handling_fee / 3, 2),
            'merchant_revenue': round(total_merchant_revenue / 3, 2)
        }

        # Prepare updates similar to other methods
        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 81, 'column': 'E',
                    'value': p['handling_fee']},
                {'row': 93, 'column': 'C',
                    'value': p['merchant_revenue']}
            ]
        },
            {
            'sheet': '油品优惠明细 2',
            'date': end_datetime.day,
            'updates': [
                {'column': 'AV', 'value': p['gas_quantity']},
                {'column': 'AW',
                    'value': p['total_discount']},
            ]
        }
        ]

        return {
            'updates': updates,
            'processed_data': p
        }

    except Exception as e:
        logger.error(f"Error processing Douyin table: {str(e)}")
        raise

def extract_voucher_amount(product_name: str) -> float:
    # Extract the number before "元" from strings like "【春节不打烊】186代200元汽油代金券（XXXX）"
    print(product_name.split('元')[0][-4:])
    match = re.search(r'(\d+)元', product_name)
    if match:
        amount = float(match.group(1))
        return amount
    else:
        return 0.0

def get_column_index(column: str) -> int:
    """
    Convert Excel column letter(s) to zero-based index.
    Supports both single letter (A-Z) and double letter (AA-ZZ) columns.

    Args:
        column: Column letter(s) (e.g., 'A', 'B', 'AA', 'AB', etc.)

    Returns:
        Zero-based column index
    """
    result = 0
    for char in column.upper():
        result = result * 26 + (ord(char) - ord('A') + 1)
    return result - 1  # Convert to 0-based index


def normalize_product_name(name: str) -> str:
    """
    Normalize product name (油枪序号) to a standard format.
    Removes '号' suffix if present and returns the number as string.

    Args:
        name: The product name to normalize

    Returns:
        Normalized product name
    """
    if not name:
        return ""
    # Convert to string and remove any whitespace
    name_str = str(name).strip()
    # Remove '号' suffix if present
    if name_str.endswith('号'):
        name_str = name_str[:-1]
    return name_str


if __name__ == "__main__":
    print(extract_voucher_amount("【春节不打烊】186代200元汽油代金券（XXXX）"))
