from typing import Dict, Any, Union
from pathlib import Path
import pandas as pd
from src.utils.logger import logger
from src.config.shift_config import ShiftConfig


class TableProcessor:
    """Utility class for processing table files"""

    def __init__(self, shift_config: ShiftConfig):
        """
        初始化表格处理器

        Args:
            output_table_path: 输出表格的路径
            shift_config: 班次相关配置
        """
        self.shift_config = shift_config

    async def process_table(self, table_path: Union[str, Path], category: str) -> Dict[str, Any]:
        """
        Process table file and extract structured information.

        Args:
            table_path: Path to the table file
            category: Category of the table (e.g., "油品时间统计", "油品优惠" etc.)

        Returns:
            Dictionary containing structured table information and update instructions

        Raises:
            Exception: If there's an error in processing the table
        """
        try:
            table_path = Path(table_path)

            # Process based on category
            if category == "油品时间统计":
                result = await self._process_time_statistics(table_path, sheet="调价前")
            elif category == "油品时间统计(调价后)":
                result = await self._process_time_statistics(table_path, sheet="调价后")
            elif category == "油品优惠":
                result = await self._process_discounts(table_path)
            elif category == "加油明细":
                result = await self._process_refuel_details(table_path)
            elif category == "通联":
                result = await self._process_tonglian(table_path)
            elif category == "充值明细":
                result = await self._process_recharge_details(table_path)
            else:
                raise ValueError(f"Unsupported table category: {category}")

            logger.info(
                f"Successfully processed table file for category: {category}")
            return result

        except Exception as e:
            logger.error(f"Error processing table file: {str(e)}")
            raise

    async def _process_time_statistics(self, path: Path, sheet: str = "调价前") -> Dict[str, Any]:
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

            fuel_type_mapping = {
                '0#柴油': 'A',
                '92#汽油': 'B',
                '95#汽油': 'C'
            }

            # 构建更新指令
            updates = []
            for _, row in df.iterrows():
                if pd.notna(row['加油升']):  # 只处理非空值
                    section = fuel_type_mapping.get(row['油品'])
                    if section:
                        updates.append({
                            'sheet': sheet,
                            'section': section,
                            'product_name': row['机号'],
                            'column': 'D',  # D列
                            'value': row['加油升']
                        })

            return {
                'updates': updates,
                'processed_data': {}
            }

        except Exception as e:
            logger.error(f"处理时间统计表格错误: {str(e)}")
            raise

    async def _process_discounts(self, path: Path) -> Dict[str, Any]:
        """Process 油品优惠 table"""
        try:
            df = pd.read_excel(
                path,
                usecols=['油品', '优惠'],  # Only read product and discount columns
            )

            # Initialize discount sums
            gasoline_discount = 0.0  # 汽油优惠总和 (92#和95#)
            diesel_discount = 0.0    # 柴油优惠总和

            # Process each row
            for _, row in df.iterrows():
                product = str(row['油品']).strip()
                discount = float(row['优惠']) if pd.notna(row['优惠']) else 0.0

                # Sum up discounts based on product type
                if '92#' in product or '95#' in product:
                    gasoline_discount += discount
                elif '0#' in product:
                    diesel_discount += discount

            processed_data = {
                'gasoline_discount': round(gasoline_discount / 3, 2),
                'diesel_discount': round(diesel_discount / 3, 2)
            }

            # 构建更新指令
            updates = [{
                'sheet': '油品优惠明细 2',
                'date': self.shift_config.date.day,
                'updates': [
                    {'column': 'G',
                        'value': processed_data['diesel_discount']},
                    {'column': 'J',
                        'value': processed_data['gasoline_discount']}
                ]
            }]

            return {
                'updates': updates,
                'processed_data': processed_data
            }

        except Exception as e:
            logger.error(f"处理优惠表格错误: {str(e)}")
            raise

    async def _process_refuel_details(self, path: Path) -> Dict[str, Any]:
        """Process 加油明细 table"""
        df = pd.read_excel(
            path,
            skiprows=2,  # 跳过前两行
            usecols=['结算金额', '收款方式']
        )

        customer_discount = df[df['收款方式'] == '充值卡收款']['结算金额'].sum()
        electric_discount = df[df['收款方式'] == '电子卡收款']['结算金额'].sum()

        processed_data = {
            'customer_discount': round(customer_discount / 3, 2),
            'electric_discount': round(electric_discount / 3, 2)
        }

        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 76, 'column': 'H',
                    'value': processed_data['customer_discount']},
                {'row': 78, 'column': 'H',
                    'value': processed_data['electric_discount']}
            ]
        }]

        return {
            'updates': updates,
            'processed_data': processed_data
        }

    async def _process_tonglian(self, path: Path) -> Dict[str, Any]:
        """Process 通联 table"""
        # 实现具体的处理逻辑
        df = pd.read_excel(path, skiprows=1, usecols=['原始金额', '收支方向'])
        income = df[df['收支方向'] == '收入']['原始金额'].sum()

        p = {
            'income': round(income / 3, 2)
        }

        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 86, 'column': 'C', 'value': p['income']}
            ]
        }]

        return {
            'updates': updates,
            'processed_data': p
        }

    async def _process_recharge_details(self, path: Path) -> Dict[str, Any]:
        """Process 充值明细表格"""
        try:
            df = pd.read_excel(path, skiprows=2, usecols=['充值金额', '充值赠送', '付款方式'])

            # 将充值金额和充值赠送的 NaN 值填充为 0
            df['充值金额'] = df['充值金额'].fillna(0)
            df['充值赠送'] = df['充值赠送'].fillna(0)

            # 创建在线支付和现金支付的掩码
            online_mask = (df['付款方式'].str.contains('微信|支付宝', na=False))
            cash_mask = (df['付款方式'].str.contains('现金', na=False))
            
            online_recharge = df[online_mask]['充值金额'].sum() + df[online_mask]['充值赠送'].sum()
            cash_recharge = df[cash_mask]['充值金额'].sum() + df[cash_mask]['充值赠送'].sum()

            p = {
                'online_recharge': round(online_recharge / 3, 2),
                'cash_recharge': round(cash_recharge / 3, 2)
            }

            updates = [{
                'sheet': '调价前',
                'updates': [
                    {'row': 73, 'column': 'C', 'value': p['online_recharge']},
                    {'row': 68, 'column': 'C', 'value': p['cash_recharge']}
                ]
            }]

            return {
                'updates': updates,
                'processed_data': p
            }

        except Exception as e:
            logger.error(f"处理充值明细表格错误: {str(e)}")
            raise

