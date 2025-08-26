from fastapi import APIRouter, File, UploadFile, Header, Form, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from typing import Union
import io
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from services.mask_service import _require_key, _pick_comfy_url, process_image, get_health_info
import time

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health")
def health(
    x_comfy_url: Union[str, None] = Header(default=None),
    comfy_url: Union[str, None] = Query(default=None)
):
    logger.info("Health check requested")
    # No API key validation required
    
    effective_comfy = _pick_comfy_url(
        form_url=None,
        header_url=x_comfy_url,
        query_url=comfy_url
    )
    
    logger.info("Health check completed successfully")
    return get_health_info(effective_comfy)

@router.post("/mask")
async def mask(
    file: UploadFile = File(...),
    x_comfy_url: Union[str, None] = Header(default=None),
    comfy_url: Union[str, None] = Form(default=None),
    comfy_url_query: Union[str, None] = Query(default=None, alias="comfy_url")
):
    start_time = time.time()
    logger.info(f"Mask request received for file: {file.filename}")
    
    # No API key validation required

    # Pick the effective COMFY_URL based on priority
    effective_comfy = _pick_comfy_url(
        form_url=comfy_url,
        header_url=x_comfy_url,
        query_url=comfy_url_query
    )

    # Read input file
    logger.info("Reading uploaded file...")
    file_bytes = await file.read()
    original_name = file.filename or "image.png"
    logger.info(f"File read: {original_name} ({len(file_bytes)} bytes)")

    # Process the image in a thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        result = await loop.run_in_executor(
            executor, 
            process_image, 
            file_bytes, 
            original_name, 
            effective_comfy
        )
    
    filename, out_bytes = result
    
    total_time = time.time() - start_time
    logger.info(f"Processing completed in {total_time:.1f}s")
    
    # Return appropriate response based on result type
    if filename == "zip":
        # Return zip file
        return StreamingResponse(
            io.BytesIO(out_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{original_name.replace(".zip", "_processed.zip")}"'}
        )
    else:
        # Return single image
        return StreamingResponse(
            io.BytesIO(out_bytes),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        ) 