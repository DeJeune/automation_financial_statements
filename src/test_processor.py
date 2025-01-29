import asyncio
import json
import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Add the project root directory to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.utils.invoice_processor import InvoiceProcessor
from src.utils.logger import logger

async def process_single_image(image_path: Path, timeout: int = 60) -> Optional[dict]:
    """
    Process a single invoice image with timeout.
    
    Args:
        image_path: Path to the image file
        timeout: Timeout in seconds
        
    Returns:
        Optional[dict]: Processed result or None if processing failed
    """
    try:
        processor = InvoiceProcessor()
        
        logger.info(f"Processing image: {image_path.name}")
        
        # Process with timeout
        async with asyncio.timeout(timeout):
            result = await processor.process_invoice(image_path)
        
        # Save the result to a JSON file
        output_file = image_path.with_suffix(".json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Results saved to: {output_file}")
        print(f"\nExtracted Data for {image_path.name}:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        return result
        
    except asyncio.TimeoutError:
        logger.error(f"Timeout processing {image_path.name} after {timeout} seconds")
        return None
    except Exception as e:
        logger.error(f"Error processing {image_path.name}: {str(e)}")
        return None

async def process_multiple_images(image_files: List[Path], max_concurrent: int = 3) -> List[Optional[dict]]:
    """
    Process multiple images with concurrency limit.
    
    Args:
        image_files: List of image paths to process
        max_concurrent: Maximum number of concurrent tasks
        
    Returns:
        List[Optional[dict]]: List of processing results, None for failed items
    """
    # Create a semaphore to limit concurrent tasks
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_with_semaphore(image_path: Path) -> Optional[dict]:
        async with semaphore:
            result = await process_single_image(image_path)
            # Add delay between images to respect rate limits
            await asyncio.sleep(2)
            return result
    
    # Create tasks for all images
    tasks = [process_with_semaphore(image) for image in image_files]
    
    # Run all tasks and gather results
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results and count successes/failures
    successes = sum(1 for r in results if isinstance(r, dict))
    failures = len(results) - successes
    
    logger.info(f"Processing completed: {successes} successful, {failures} failed")
    return results

def get_image_files() -> List[Path]:
    """Get all image files from the images directory"""
    image_dir = Path("src/images")
    return sorted(list(image_dir.glob("*.jpg")) + list(image_dir.glob("*.png")))

async def main() -> None:
    parser = argparse.ArgumentParser(description="Process invoice images")
    parser.add_argument("--index", type=int, help="Index of the image to process (0-based)")
    parser.add_argument("--list", action="store_true", help="List available images")
    parser.add_argument("--all", action="store_true", help="Process all images")
    parser.add_argument("--timeout", type=int, default=90, help="Timeout in seconds for each image")
    parser.add_argument("--max-concurrent", type=int, default=2, help="Maximum number of concurrent processes")
    args = parser.parse_args()
    
    image_files = get_image_files()
    
    if not image_files:
        logger.warning("No image files found in src/images directory")
        return
    
    if args.list:
        print("\nAvailable images:")
        for i, image_file in enumerate(image_files):
            print(f"{i}: {image_file.name}")
        return
    
    try:
        if args.all:
            logger.info(f"Processing all {len(image_files)} images with max {args.max_concurrent} concurrent tasks")
            await process_multiple_images(image_files, args.max_concurrent)
        elif args.index is not None:
            if 0 <= args.index < len(image_files):
                await process_single_image(image_files[args.index], args.timeout)
            else:
                logger.error(f"Invalid image index. Must be between 0 and {len(image_files)-1}")
        else:
            # Process the first image by default
            await process_single_image(image_files[0], args.timeout)
    except KeyboardInterrupt:
        logger.warning("Processing interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    # Set longer timeout for Windows
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Run with custom event loop configuration
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()