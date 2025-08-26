from fastapi import APIRouter, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from typing import List, Optional
import tempfile
import os
import shutil
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from services.rename_service import (
    cleanup_temp_directory, create_zip_from_directory, FaceDetectionProcessor,
    process_zip_file, process_individual_files, create_manifest_file
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/health")
async def health_check():
    """Health check endpoint for n8n."""
    return {"ok": True}

@router.post("/process")
async def process_images(
    background_tasks: BackgroundTasks,
    zip_file: Optional[UploadFile] = File(None, description="Single ZIP file containing images"),
    files: Optional[List[UploadFile]] = File(None, description="Multiple individual image files"),
    return_zip: bool = Form(True, description="Return processed ZIP when true, JSON report when false"),
    min_confidence: float = Form(0.5, description="MediaPipe face detection confidence threshold"),
    max_face_bottom_ratio: float = Form(0.65, description="Maximum face bottom position ratio (0.65 = 65% of image height)"),
    min_face_height_px: int = Form(40, description="Minimum face height in pixels")
):
    """
    Process images for face detection and rename those without valid faces.
    
    Accepts either:
    - zip_file: Single ZIP containing images in any subfolder structure
    - files[]: Multiple individual image files
    
    Returns either:
    - ZIP file with processed images (when return_zip=true)
    - JSON report (when return_zip=false)
    """
    
    logger.info("=== Starting image processing request ===")
    
    # Validate input
    if not zip_file and not files:
        raise HTTPException(status_code=400, detail="Either zip_file or files must be provided")
    
    if zip_file and files:
        raise HTTPException(status_code=400, detail="Provide either zip_file OR files, not both")
    
    # Create temporary directories
    temp_dir = tempfile.mkdtemp()
    input_dir = os.path.join(temp_dir, "input")
    output_dir = os.path.join(temp_dir, "output")
    
    try:
        os.makedirs(input_dir)
        os.makedirs(output_dir)
        
        # Extract uploaded content
        if zip_file:
            if not process_zip_file(zip_file, temp_dir, input_dir):
                raise HTTPException(status_code=400, detail="Failed to process ZIP file")
        else:
            if not process_individual_files(files, input_dir):
                raise HTTPException(status_code=400, detail="Failed to process individual files")
        
        # Process images
        processor = FaceDetectionProcessor(
            min_confidence=min_confidence,
            max_face_bottom_ratio=max_face_bottom_ratio,
            min_face_height_px=min_face_height_px
        )
        
        try:
            # Process images in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                results = await loop.run_in_executor(
                    executor,
                    processor.process_images,
                    input_dir,
                    output_dir
                )
            
            # Add manifest.json to output directory
            create_manifest_file(output_dir, results)
            
            if return_zip:
                # Create ZIP in memory BEFORE cleanup
                zip_buffer = create_zip_from_directory(output_dir)
                
                # Schedule cleanup as background task (after response is sent)
                background_tasks.add_task(cleanup_temp_directory, temp_dir)
                
                # Return the ZIP from memory
                return StreamingResponse(
                    BytesIO(zip_buffer.getvalue()),
                    media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=processed_images.zip"}
                )
            else:
                # Schedule cleanup as background task
                background_tasks.add_task(cleanup_temp_directory, temp_dir)
                # Return JSON report
                return JSONResponse(content=results)
                
        finally:
            processor.cleanup()
            
    except Exception as e:
        logger.error(f"Processing error: {str(e)}", exc_info=True)
        # Schedule cleanup even on error
        background_tasks.add_task(cleanup_temp_directory, temp_dir)
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}") 