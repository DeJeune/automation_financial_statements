from typing import Dict, Any, Union
import json
import asyncio
from pathlib import Path
import google.generativeai as genai
from PIL import Image
from src.config.settings import get_settings
from src.prompts.invoice_recognition import INVOICE_SYSTEM_PROMPT, INVOICE_IMAGE_PROMPT
from src.utils.logger import logger

settings = get_settings()

class InvoiceProcessor:
    """Utility class for processing invoices using Gemini API"""
    
    def __init__(self):
        """Initialize the Gemini model"""
        # Configure Gemini
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(model_name=settings.GEMINI_MODEL, system_instruction=INVOICE_SYSTEM_PROMPT)
        self._last_request_time = 0
        self.min_request_interval = 2  # Minimum time between requests in seconds
    
    async def _wait_for_rate_limit(self):
        """Wait if needed to respect rate limits"""
        current_time = asyncio.get_event_loop().time()
        time_since_last_request = current_time - self._last_request_time
        
        if time_since_last_request < self.min_request_interval:
            wait_time = self.min_request_interval - time_since_last_request
            logger.info(f"Rate limiting: waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)
        
        self._last_request_time = asyncio.get_event_loop().time()
    
    def _prepare_image(self, image: Image.Image) -> Image.Image:
        """Convert image to RGB and get it ready for API"""
        if image.mode not in ['RGB']:
            image = image.convert('RGB')
        return image
    
    async def process_invoice(self, invoice_image: Union[str, Path, Image.Image]) -> Dict[str, Any]:
        """
        Process invoice image and extract structured information.
        
        Args:
            invoice_image: Path to the invoice image file or PIL Image object
            
        Returns:
            Dictionary containing structured invoice information
            
        Raises:
            Exception: If there's an error in processing the invoice
        """
        try:
            # Load and prepare the image
            if isinstance(invoice_image, (str, Path)):
                image = Image.open(invoice_image)
                image_name = Path(invoice_image).stem  # Get filename without extension
            elif isinstance(invoice_image, Image.Image):
                image = invoice_image
                image_name = "uploaded_image"
            else:
                raise ValueError("Invalid image input. Must be a file path or PIL Image object")
            
            # Validate and preprocess image
            image = self.preprocess_image(image)
            image = self._prepare_image(image)
            
            # Wait for rate limit
            await self._wait_for_rate_limit()
            
            # Combine prompts
            prompt = INVOICE_IMAGE_PROMPT.format(image_name=image_name)
            
            try:
                # Call Gemini API with image
                response = self.model.generate_content(
                    contents=[
                        prompt,
                        image
                    ]
                )
                response.resolve()
                
                # Get the complete response
                if response.text:
                    # Try to parse the response directly first
                    try:
                        structured_data = json.loads(response.text)
                    except json.JSONDecodeError:
                        # If direct parsing fails, try to extract JSON from the text
                        start = response.text.find('{')
                        end = response.text.rfind('}') + 1
                        if start >= 0 and end > start:
                            json_str = response.text[start:end]
                            structured_data = json.loads(json_str)
                        else:
                            raise ValueError("No valid JSON found in response")
                    
                    logger.info("Successfully processed invoice image")
                    return structured_data
                else:
                    raise ValueError("Empty response from API")
                
            except Exception as api_error:
                logger.error(f"API Error: {str(api_error)}")
                logger.debug(f"API Response: {response.text if hasattr(response, 'text') else 'No response text'}")
                raise
            
        except Exception as e:
            logger.error(f"Error processing invoice image: {str(e)}")
            raise
    
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
            # Get image dimensions
            width, height = image.size
            
            # Resize if image is too small
            min_dimension = 800
            if width < min_dimension or height < min_dimension:
                # Calculate new dimensions maintaining aspect ratio
                ratio = max(min_dimension/width, min_dimension/height)
                new_size = (int(width * ratio), int(height * ratio))
                logger.info(f"Resizing image from {width}x{height} to {new_size[0]}x{new_size[1]}")
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Check file size
            max_size_mb = 20
            image_size_mb = (width * height * len(image.getbands())) / (1024 * 1024)
            if image_size_mb > max_size_mb:
                # Compress image
                quality = 85
                while image_size_mb > max_size_mb and quality > 50:
                    # Save to bytes to check size
                    from io import BytesIO
                    buffer = BytesIO()
                    image.save(buffer, format='JPEG', quality=quality)
                    image_size_mb = len(buffer.getvalue()) / (1024 * 1024)
                    quality -= 5
                
                if image_size_mb > max_size_mb:
                    raise ValueError(f"Image size ({image_size_mb:.2f}MB) exceeds maximum size even after compression")
                
                # Load the compressed image
                buffer.seek(0)
                image = Image.open(buffer)
            
            return image
            
        except Exception as e:
            logger.error(f"Error preprocessing image: {str(e)}")
            raise ValueError(f"Image preprocessing failed: {str(e)}") 