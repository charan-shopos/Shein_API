from fastapi import APIRouter, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional
import os
import tempfile
import shutil
import zipfile
import time
import logging
from datetime import datetime
import traceback
from services.workflow_service import (
    setup_logging, verify_required_files, extract_zip_to_temp,
    load_json_file, ensure_http_protocol, process_images_api,
    workflow_path
)
import json

logger = setup_logging()
router = APIRouter()

# Request/Response models
class ProcessingStatus(BaseModel):
    task_id: str
    status: str
    message: str
    progress: Optional[int] = None

class ProcessingRequest(BaseModel):
    task_id: str
    images_zip: str
    masks_zip: str
    prompts_json: str

# Global storage for processing tasks
processing_tasks = {}

@router.post("/process_images")
async def process_images(
    images_zip: UploadFile = File(...),
    masks_zip: UploadFile = File(...),
    prompts_json: UploadFile = File(...),
    comfyui_url: str = Form(...),
    background_tasks: BackgroundTasks = None
):
    """Process images using the workflow"""
    try:
        logger.info("=== REQUEST PROCESSING START ===")
        
        # Verify required files exist
        if not verify_required_files():
            raise HTTPException(status_code=500, detail="Required files missing")
        
        # Create temporary directory for processing
        temp_dir = tempfile.mkdtemp()
        logger.info(f"Created temporary directory: {temp_dir}")
        
        try:
            # Create subdirectories
            input_dir = os.path.join(temp_dir, "input_images")
            masks_dir = os.path.join(temp_dir, "masks")
            output_dir = os.path.join(temp_dir, "output")
            
            os.makedirs(input_dir, exist_ok=True)
            os.makedirs(masks_dir, exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
            
            # Extract uploaded ZIP files
            logger.info("Extracting uploaded ZIP files...")
            
            if not extract_zip_to_temp(images_zip, input_dir):
                raise HTTPException(status_code=400, detail="Failed to extract images ZIP")
            
            if not extract_zip_to_temp(masks_zip, masks_dir):
                raise HTTPException(status_code=400, detail="Failed to extract masks ZIP")
            
            # Load prompts JSON
            prompts_content = await prompts_json.read()
            try:
                prompts_data = json.loads(prompts_content.decode('utf-8'))
                logger.info(f"Loaded prompts JSON with {len(prompts_data)} entries")
                
                # Convert list format to dict format if needed
                if isinstance(prompts_data, list) and len(prompts_data) > 0:
                    # PromptMap returns [{"folder_id": {...}}], convert to {"folder_id": {...}}
                    converted_data = {}
                    for item in prompts_data:
                        if isinstance(item, dict):
                            converted_data.update(item)
                    prompts_data = converted_data
                    logger.info(f"Converted list format to dict format: {len(prompts_data)} entries")
                
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"Invalid prompts JSON: {str(e)}")
            
            # Load workflow JSON
            workflow = load_json_file(workflow_path)
            if not workflow:
                raise HTTPException(status_code=500, detail="Failed to load workflow JSON")
            
            # Call the processing function directly (synchronously)
            logger.info("Starting image processing - this will wait for ComfyUI to complete ALL images...")
            try:
                process_images_api(
                    workflow,
                    ensure_http_protocol(comfyui_url),
                    prompts_data,
                    input_dir,
                    masks_dir,
                    output_dir,
                    "SYNC_PROCESSING"
                )
                logger.info("Image processing completed successfully")
            except Exception as e:
                logger.error(f"Image processing failed: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Image processing failed: {str(e)}")
            
            # Create ZIP file from output directory
            logger.info("Creating final ZIP file...")
            
            # Check if we actually have processed images
            if not os.path.exists(output_dir) or not os.listdir(output_dir):
                logger.error("No processed images found in output directory")
                raise HTTPException(status_code=500, detail="No processed images were generated")
            
            # List all processed images
            all_files = []
            for root, dirs, files in os.walk(output_dir):
                for file in files:
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        all_files.append(os.path.join(root, file))
            
            logger.info(f"Found {len(all_files)} processed images: {[os.path.basename(f) for f in all_files]}")
            
            if not all_files:
                logger.error("No image files found in output directory")
                raise HTTPException(status_code=500, detail="No image files were generated")
            
            output_zip_path = os.path.join(temp_dir, f"processed_images_{int(time.time())}.zip")
            
            with zipfile.ZipFile(output_zip_path, 'w') as zipf:
                # Add all processed images to ZIP
                for file_path in all_files:
                    arcname = os.path.relpath(file_path, output_dir)
                    zipf.write(file_path, arcname)
                    logger.info(f"Added to ZIP: {arcname}")
            
            logger.info(f"ZIP file created: {output_zip_path}")
            logger.info(f"ZIP file size: {os.path.getsize(output_zip_path)} bytes")
            
            # Read the ZIP file content
            with open(output_zip_path, 'rb') as zip_file:
                zip_content = zip_file.read()
            
            logger.info("=== REQUEST PROCESSING COMPLETED SUCCESSFULLY ===")
            

            # Return the ZIP file directly
            return Response(
                content=zip_content,
                media_type='application/zip',
                headers={
                    'Content-Disposition': f'attachment; filename="processed_images.zip"',
                    'Content-Length': str(len(zip_content))
                }
            )
            
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
                logger.info("Temporary directory cleaned up")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary directory: {e}")
            
    except Exception as e:
        # Log the full error for debugging
        logger.error(f"Unexpected error in process_images endpoint: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Return a more specific error message
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/status/{task_id}", response_model=ProcessingStatus)
async def get_status(task_id: str):
    """Get the status of a processing task"""
    if task_id not in processing_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return ProcessingStatus(**processing_tasks[task_id])

@router.get("/download/{task_id}")
async def download_results(task_id: str):
    """Download the processed images ZIP file"""
    if task_id not in processing_tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if processing_tasks[task_id]["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed yet")
    
    # Create ZIP file from output directory
    output_zip_path = f"output_{task_id}.zip"
    
    try:
        with zipfile.ZipFile(output_zip_path, 'w') as zipf:
            # Add all processed images to ZIP
            output_dir = f"temp_output_{task_id}"
            if os.path.exists(output_dir):
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, output_dir)
                        zipf.write(file_path, arcname)
        
        # Return the ZIP file
        return FileResponse(
            output_zip_path,
            media_type='application/zip',
            filename=f"processed_images_{task_id}.zip"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create download: {str(e)}")

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()} 