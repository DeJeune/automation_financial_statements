from typing import Dict, Any, Union
import json
import asyncio
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image
from src.config.settings import get_settings
from src.prompts.invoice_recognition import get_invoice_recognition_messages, get_category_schema, INVOICE_SYSTEM_PROMPT
from src.utils.logger import logger
from src.config.shift_config import ShiftConfig
from src.utils.value_parser import parse_numeric_value

settings = get_settings()


class InvoiceProcessor:
    """Utility class for processing invoices using Gemini API"""

    def __init__(self, shift_config: ShiftConfig):
        """
        Initialize the Gemini model and Excel updater

        Args:
            shift_config: Configuration for shift-related parameters
        """
        # Configure Gemini
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options={'base_url': settings.GEMINI_BASE_URL})
        self.model = settings.GEMINI_MODEL
        self._last_request_time = 0
        # 6 seconds between requests (10 RPM = 1 request per 6 seconds)
        self.min_request_interval = 6
        self._request_times = []  # Track request timestamps for rolling window
        self.rpm_limit = 10  # Gemini API limit of 10 requests per minute
        self.window_size = 60  # Rolling window size in seconds
        self.shift_config = shift_config

    async def _wait_for_rate_limit(self):
        """Wait if needed to respect rate limits"""
        current_time = asyncio.get_event_loop().time()

        # Clean up old request times
        self._request_times = [
            t for t in self._request_times if current_time - t < self.window_size]

        # Check if we've hit the RPM limit
        if len(self._request_times) >= self.rpm_limit:
            # Calculate wait time until oldest request expires from window
            wait_time = self.window_size - \
                (current_time - self._request_times[0])
            if wait_time > 0:
                logger.info(
                    f"Rate limiting: waiting {wait_time:.2f} seconds to respect RPM limit")
                await asyncio.sleep(wait_time)
                # Clean up again after waiting
                current_time = asyncio.get_event_loop().time()
                self._request_times = [
                    t for t in self._request_times if current_time - t < self.window_size]

        # Ensure minimum interval between requests
        time_since_last_request = current_time - self._last_request_time
        if time_since_last_request < self.min_request_interval:
            wait_time = self.min_request_interval - time_since_last_request
            logger.info(
                f"Rate limiting: waiting {wait_time:.2f} seconds between requests")
            await asyncio.sleep(wait_time)

        # Update tracking
        self._last_request_time = current_time
        self._request_times.append(current_time)

    async def _post_process_json(self, data: Dict[str, Any], category: str) -> Dict[str, Any]:
        """
        Post-process JSON data based on category.

        Args:
            data: Raw JSON data from the model
            category: Image category

        Returns:
            Processed JSON data
        """
        try:
            # Common post-processing for all categories
            processed_data = data.copy()

            # Category-specific post-processing
            if category == "货车帮":
                # Add any 货车帮-specific processing here
                result = await self._process_huochebang(processed_data)
            elif category == "滴滴加油":
                # Add any 滴滴加油-specific processing here
                result = await self._process_didijia(processed_data)
            elif category in ["国通1", "国通2"]:
                # Add any 国通-specific processing here
                result = await self._process_guotong(processed_data, category)
            elif category == "团油":
                result = await self._process_tuanyou(processed_data)
            elif category == "POS":
                result = await self._process_pos(processed_data)
            elif category == "超市销售收入":
                result = await self._process_supermarket(processed_data)
            elif category == "抖音":
                result = await self._process_douyin(processed_data)
                

            return result

        except Exception as e:
            logger.error(f"Error in post-processing JSON data: {str(e)}")
            return data

    async def _process_huochebang(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process 货车帮 invoice data"""
        # Parse values using the utility function with appropriate units and scaling
        diesel_stats = parse_numeric_value(
            processed_data["柴油统计"],
            unit="升"
        )

        # Parse direct discount and station discount separately then sum
        direct_discount = parse_numeric_value(
            processed_data["油站直降"],
            unit="元"
        )
        station_discount = parse_numeric_value(
            processed_data["油站折扣"],
            unit="元"
        )
        diesel_discount = round(direct_discount + station_discount, 2)

        # Parse handling fee and settlement amount
        handling_fee = parse_numeric_value(
            processed_data["服务费"],
            unit="元"
        )
        settlement_amount = parse_numeric_value(
            processed_data["结算金额"],
            unit="元"
        )

        p = {
            'diesel_stats': round(diesel_stats / 3, 2),
            'diesel_discount': round(diesel_discount / 3, 2),
            'handling_fee': round(handling_fee / 3, 2),
            'settlement_amount': round(settlement_amount / 3, 2)
        }

        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 81, 'column': 'E', 'value': p['handling_fee']},
                {'row': 90, 'column': 'C', 'value': p['settlement_amount']}
            ]
        },
            {
            'sheet': '油品优惠明细 2',
            'date': self.shift_config.date.day,
            'updates': [
                {'column': 'AA', 'value': p['diesel_stats']},
                {'column': 'AB', 'value': p['diesel_discount']}
            ]
        }]

        return {
            'updates': updates,
            'processed_data': p
        }

    async def _process_didijia(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process 滴滴加油 invoice"""
        # 实现具体的处理逻辑
        gas_stats = parse_numeric_value(processed_data["油品数量"])
        gas_discount = parse_numeric_value(processed_data["油品优惠合计"])
        handling_fee = parse_numeric_value(processed_data["油品预收金额"]) - \
            parse_numeric_value(processed_data["油品应收金额"])
        settlement_amount = parse_numeric_value(
            processed_data["油品应收金额"])
        p = {
            'gas_stats': round(gas_stats / 3, 2),
            'gas_discount': round(gas_discount / 3, 2),
            'handling_fee': round(handling_fee / 3, 2),
            'settlement_amount': round(settlement_amount / 3, 2)
        }
        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 81, 'column': 'E',
                    'value': p['handling_fee']},
                {'row': 88, 'column': 'C',
                    'value': p['settlement_amount']}
            ]
        },
            {
            'sheet': '油品优惠明细 2',
            'date': self.shift_config.date.day,
            'updates': [
                {'column': 'P', 'value': p['gas_stats']},
                {'column': 'Q', 'value': p['gas_discount']}
            ]
        }
        ]
        return {
            'updates': updates,
            'processed_data': p
        }

    async def _process_guotong(self, processed_data: Dict[str, Any], category: str) -> Dict[str, Any]:
        """Process 国通 invoice"""
        # 实现具体的处理逻辑
        settlement_amount = parse_numeric_value(processed_data["订单金额"]) - \
            parse_numeric_value(processed_data["退款订单金额"])
        p = {
            'settlement_amount': round(settlement_amount / 3, 2)
        }
        if category == "国通1":
            updates = [{
                'sheet': '调价前',
                'updates': [
                    {'row': 92, 'column': 'H',
                        'value': p['settlement_amount']}
                ]
            }]
        elif category == "国通2":
            updates = [{
                'sheet': '调价前',
                'updates': [
                    {'row': 93, 'column': 'H',
                        'value': p['settlement_amount']}
                ]
            }]
        else:
            raise ValueError(f"Invalid category: {category}")

        return {
            'updates': updates,
            'processed_data': p
        }

    async def _process_tuanyou(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process 团油 invoice"""
        # 实现具体的处理逻辑
        gas_stats = parse_numeric_value(
            processed_data["加油升数汇总"],
            unit="升"
        )
        handling_fee = parse_numeric_value(
            processed_data["通道费汇总"],
            unit="元"
        )
        settlement_amount = parse_numeric_value(
            processed_data["实际结算金额汇总"],
            unit="元"
        )
        gas_discount = parse_numeric_value(
            processed_data["加油金额汇总"],
            unit="元"
        ) - settlement_amount - handling_fee
        p = {
            'gas_stats': round(gas_stats / 3, 2),
            'gas_discount': round(gas_discount / 3, 2),
            'handling_fee': round(handling_fee / 3, 2),
            'settlement_amount': round(settlement_amount / 3, 2)
        }
        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 81, 'column': 'E',
                    'value': p['handling_fee']},
                {'row': 89, 'column': 'C',
                    'value': p['settlement_amount']}
            ]},
            {
            'sheet': '油品优惠明细 2',
            'date': self.shift_config.date.day,
            'updates': [
                {'column': 'W', 'value': p['gas_stats']},
                {'column': 'X', 'value': p['gas_discount']}
            ]
        }]
        return {
            'updates': updates,
            'processed_data': p
        }

    async def _process_pos(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process POS invoice"""
        # 实现具体的处理逻辑
        settlement_amount = parse_numeric_value(processed_data["结算总金额"])
        p = {
            'settlement_amount': round(settlement_amount / 3, 2)
        }
        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 80, 'column': 'E', 'value': p['settlement_amount']}
            ]
        }]
        return {
            'updates': updates,
            'processed_data': p
        }

    async def _process_supermarket(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process supermarket invoice"""
        # 实现具体的处理逻辑
        settlement_amount = parse_numeric_value(processed_data["现金"])
        p = {
            'settlement_amount': round(settlement_amount / 3, 2)
        }
        updates = [{
            'sheet': '调价前',
            'updates': [
                {'row': 71, 'column': 'H', 'value': p['settlement_amount']}
            ]
        }]
        return {
            'updates': updates,
            'processed_data': p
        }

    async def process_invoice(self, invoice_image: Union[str, Path, Image.Image], category: str) -> Dict[str, Any]:
        """
        Process invoice image and extract structured information.

        Args:
            invoice_image: Path to the invoice image file or PIL Image object
            category: Category of the image (e.g., "货车帮", "滴滴加油", etc.)

        Returns:
            Dictionary containing structured invoice information

        Raises:
            Exception: If there's an error in processing the invoice
        """
        try:
            # Load and prepare the image
            if isinstance(invoice_image, (str, Path)):
                try:
                    image = Image.open(invoice_image)
                    # Get filename without extension
                    image_name = str(invoice_image.name).strip()
                except Exception as e:
                    logger.error(
                        f"Failed to open image file {invoice_image}: {str(e)}")
                    raise ValueError(f"Failed to open image file: {str(e)}")
            elif isinstance(invoice_image, Image.Image):
                image = invoice_image
                image_name = "uploaded_image"

            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')

            # Wait for rate limit
            await self._wait_for_rate_limit()

            # Get category-specific prompts and schema
            messages = get_invoice_recognition_messages(category, image_name)
            category_schema = get_category_schema(category)

            try:
                # Build config with structured output schema
                config = types.GenerateContentConfig(
                    system_instruction=INVOICE_SYSTEM_PROMPT,
                    max_output_tokens=settings.GEMINI_MAX_TOKENS,
                    temperature=settings.GEMINI_TEMPERATURE,
                    response_mime_type="application/json",
                )
                if category_schema:
                    config.response_schema = category_schema

                # Call Gemini API with image and handle rate limits
                max_retries = 3
                retry_count = 0
                response = None

                while retry_count < max_retries:
                    try:
                        response = self.client.models.generate_content(
                            model=self.model,
                            config=config,
                            contents=[messages[1]["content"], image]
                        )
                        break
                    except Exception as api_error:
                        retry_count += 1
                        if "Rate limit exceeded" in str(api_error) or "quota exceeded" in str(api_error).lower():
                            if retry_count < max_retries:
                                wait_time = (2 ** retry_count) * 5
                                logger.warning(
                                    f"Rate limit hit, waiting {wait_time} seconds before retry {retry_count}/{max_retries}")
                                await asyncio.sleep(wait_time)
                                continue
                        logger.error(
                            f"API call failed on attempt {retry_count}: {str(api_error)}")
                        if retry_count == max_retries:
                            raise ValueError(
                                f"Failed after {max_retries} attempts: {str(api_error)}")
                        continue

                if not response or not response.text:
                    raise ValueError("Empty response from API")

                logger.info(f"Raw API response: {response.text}")

                structured_data = json.loads(response.text)

                if not isinstance(structured_data, dict) or not structured_data:
                    raise ValueError(
                        "Response structure validation failed - expected non-empty dictionary")

                # Post-process the JSON data based on category
                processed_data = await self._post_process_json(
                    structured_data, category)

                return processed_data

            except Exception as api_error:
                logger.error(f"API Error: {str(api_error)}")
                if response:
                    logger.debug(
                        f"API Response: {response.text if hasattr(response, 'text') else 'No response text'}")
                raise ValueError(f"API Error: {str(api_error)}")

        except Exception as e:
            logger.error(f"Error processing invoice image: {str(e)}")
            raise
    
    async def _process_douyin(self, processed_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process 抖音 invoice data from Gemini recognition result.

        Args:
            processed_data: Recognized data with 用户侧划线价合计, 订单实收合计, 预计收入合计

        Returns:
            Dictionary containing processed data and update instructions
        """
        total_voucher_value = parse_numeric_value(processed_data["用户侧划线价合计"])
        total_received = parse_numeric_value(processed_data["订单实收合计"])
        total_merchant_revenue = parse_numeric_value(processed_data["预计收入合计"])

        total_discount = total_voucher_value - total_received
        handling_fee = total_received - total_merchant_revenue
        gas_quantity = total_voucher_value / \
            self.shift_config.gas_price if self.shift_config.gas_price > 0 else 0

        p = {
            'gas_quantity': round(gas_quantity / 3, 2),
            'total_discount': round(total_discount / 3, 2),
            'handling_fee': round(handling_fee / 3, 2),
            'merchant_revenue': round(total_merchant_revenue / 3, 2)
        }

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
            'date': self.shift_config.date.day,
            'updates': [
                {'column': 'AY', 'value': p['gas_quantity']},
                {'column': 'AZ',
                    'value': p['total_discount']},
            ]
        }
        ]

        return {
            'updates': updates,
            'processed_data': p
        }


    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess and validate the image.

        Args:
            image: PIL Image object

        Returns:
            Preprocessed PIL Image object

        Raises:
            ValueError: If image validation fails
        """
        try:
            # Validate input
            if not isinstance(image, Image.Image):
                raise ValueError("Input must be a PIL Image object")

            # Get image dimensions
            try:
                width, height = image.size
            except Exception as e:
                raise ValueError(f"Failed to get image dimensions: {str(e)}")

            # Basic image validation
            if width < 1 or height < 1:
                raise ValueError(f"Invalid image dimensions: {width}x{height}")

            # Resize if image is too small
            min_dimension = 800
            if width < min_dimension or height < min_dimension:
                # Calculate new dimensions maintaining aspect ratio
                ratio = max(min_dimension/width, min_dimension/height)
                new_size = (int(width * ratio), int(height * ratio))
                logger.info(
                    f"Resizing image from {width}x{height} to {new_size[0]}x{new_size[1]}")
                try:
                    image = image.resize(new_size, Image.Resampling.LANCZOS)
                except Exception as e:
                    raise ValueError(f"Failed to resize image: {str(e)}")

            # Check file size
            max_size_mb = 20
            try:
                image_size_mb = (width * height *
                                 len(image.getbands())) / (1024 * 1024)
            except Exception as e:
                raise ValueError(f"Failed to calculate image size: {str(e)}")

            if image_size_mb > max_size_mb:
                logger.info(
                    f"Image size ({image_size_mb:.2f}MB) exceeds limit, attempting compression")
                # Compress image
                quality = 85
                while image_size_mb > max_size_mb and quality > 50:
                    try:
                        # Save to bytes to check size
                        from io import BytesIO
                        buffer = BytesIO()
                        image.save(buffer, format='JPEG', quality=quality)
                        image_size_mb = len(buffer.getvalue()) / (1024 * 1024)
                        quality -= 5
                    except Exception as e:
                        raise ValueError(f"Failed to compress image: {str(e)}")

                if image_size_mb > max_size_mb:
                    raise ValueError(
                        f"Image size ({image_size_mb:.2f}MB) exceeds maximum size even after compression")

                try:
                    # Load the compressed image
                    buffer.seek(0)
                    image = Image.open(buffer)
                except Exception as e:
                    raise ValueError(
                        f"Failed to load compressed image: {str(e)}")

            return image

        except Exception as e:
            logger.error(f"Error preprocessing image: {str(e)}")
            raise ValueError(f"Image preprocessing failed: {str(e)}")
