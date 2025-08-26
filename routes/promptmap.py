from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import time
import tempfile
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Optional
import traceback
import uuid
from services.promptmap_service import setup_logging, process_zip_file

logger = setup_logging()
router = APIRouter()

# Request/Response models
class ProcessingResponse:
    def __init__(self, success: bool, message: str, data: Optional[Dict] = None, error: Optional[str] = None):
        self.success = success
        self.message = message
        self.data = data
        self.error = error

@router.get("/")
async def root():
    """Root endpoint with API information"""
    logger.info("Root endpoint accessed")
    return {
        "message": "Image Processing API",
        "version": "1.0.0",
        "description": "API for processing fashion images and generating prompts using OpenAI",
        "endpoints": {
            "/": "API information",
            "/process-images": "Process uploaded zip file with images",
            "/health": "Health check endpoint"
        }
    }

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    logger.debug("Health check endpoint accessed")
    return {"status": "healthy", "timestamp": time.time()}

@router.post("/process-images")
async def process_images(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Zip file containing image folders")
):
    """Process uploaded zip file containing fashion images with comprehensive logging"""
    
    request_id = getattr(request.state, 'request_id', 'unknown')
    logger.info(f"Request {request_id}: Processing images from file: {file.filename}")
    
    # Validate file type
    if not file.filename.endswith('.zip'):
        logger.warning(f"Request {request_id}: Invalid file type: {file.filename}")
        raise HTTPException(status_code=400, detail="File must be a ZIP file")
    
    # Log file details
    logger.info(f"Request {request_id}: File size: {file.size} bytes, Content-Type: {file.content_type}")
    
    try:
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            logger.debug(f"Request {request_id}: Created temp directory: {temp_dir}")
            
            # Save uploaded file
            zip_file_path = temp_dir_path / "uploaded.zip"
            logger.debug(f"Request {request_id}: Saving uploaded file to: {zip_file_path}")
            
            with open(zip_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            logger.info(f"Request {request_id}: File saved successfully, starting processing")
            
            # Process the zip file
            start_time = time.time()
            results = process_zip_file(str(zip_file_path), temp_dir)
            process_time = time.time() - start_time
            
            logger.info(f"Request {request_id}: Processing completed in {process_time:.3f}s")
            
            # Clean up
            if os.path.exists(zip_file_path):
                os.remove(zip_file_path)
                logger.debug(f"Request {request_id}: Cleaned up temporary zip file")
            
            logger.info(f"Request {request_id}: Successfully processed {len(results)} folders")
            
            return ProcessingResponse(
                success=True,
                message=f"Successfully processed {len(results)} folders",
                data={
                    "total_folders": len(results),
                    "results": results,
                    "processing_time": f"{process_time:.3f}s",
                    "request_id": request_id
                }
            )
            
    except Exception as e:
        logger.error(f"Request {request_id}: Error processing images: {e}", exc_info=True)
        return ProcessingResponse(
            success=False,
            message="Error processing images",
            error=str(e)
        ) 