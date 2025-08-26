import os, time, json, io, requests, zipfile, logging
import asyncio
import aiohttp
from typing import Union
from fastapi import HTTPException

# ========= Config via ENV =========
WORKFLOW_JSON   = os.getenv("WORKFLOW_JSON", "Mask n8n Working/JSON.json")  # path to the JSON file in the original folder
INPUT_NODE_ID   = str(os.getenv("INPUT_NODE_ID", "54"))    # your "Load Image" node id
OUTPUT_NODE_ID  = str(os.getenv("OUTPUT_NODE_ID", "455"))  # node that exposes the mask
POLL_INTERVAL_S = float(os.getenv("POLL_INTERVAL_S", "5"))
POLL_TIMEOUT_S  = float(os.getenv("POLL_TIMEOUT_S", "120"))
MAX_RETRIES     = int(os.getenv("MAX_RETRIES", "3"))
logger = logging.getLogger(__name__)

def _require_key(x_api_key: Union[str, None]):
    # API key validation removed - no authentication required
    logger.info("API key validation bypassed - no authentication required")

def _pick_comfy_url(form_url: Union[str, None] = None, header_url: Union[str, None] = None, query_url: Union[str, None] = None) -> str:
    """Pick the first non-empty COMFY_URL from form field > header > query param"""
    for url in [form_url, header_url, query_url]:
        if url and url.strip():
            # Normalize with trailing slash
            normalized = url.rstrip('/') + '/'
            logger.info(f"Using ComfyUI URL: {normalized}")
            return normalized
    # No URL provided - raise error since hardcoded fallback is unreliable
    logger.error("No comfy_url provided via form field, header (x-comfy-url), or query parameter")
    raise HTTPException(status_code=400, detail="comfy_url must be provided via form field, header (x-comfy-url), or query parameter")

def _upload_to_comfy(img_bytes: bytes, original_name: str, base_url: str) -> str:
    stamped = f"{int(time.time()*1000)}_{original_name}"
    logger.info(f"Uploading image '{original_name}' to ComfyUI as '{stamped}'")
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            logger.debug(f"Upload attempt {attempt + 1}/{MAX_RETRIES}")
            r = requests.post(
                f"{base_url.rstrip('/')}/upload/image",
                files={"image": (stamped, img_bytes)},
                timeout=60,
            )
            r.raise_for_status()
            logger.info(f"Successfully uploaded '{stamped}' to ComfyUI")
            return stamped
        except Exception as e:
            last_err = e
            logger.warning(f"Upload attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying in 2 seconds...")
                time.sleep(2)
    logger.error(f"All upload attempts failed for '{original_name}': {last_err}")
    raise HTTPException(status_code=502, detail=f"Upload failed: {last_err}")

def _queue_prompt(graph: dict, base_url: str) -> str:
    logger.info("Queueing prompt to ComfyUI...")
    r = requests.post(f"{base_url.rstrip('/')}/prompt", json={"prompt": graph}, timeout=60)
    r.raise_for_status()
    pid = r.json().get("prompt_id")
    if not pid:
        logger.error("ComfyUI did not return prompt_id")
        raise HTTPException(status_code=500, detail="ComfyUI did not return prompt_id")
    logger.info(f"Prompt queued successfully with ID: {pid}")
    return pid

def _poll_history(prompt_id: str, base_url: str) -> dict:
    logger.info(f"Polling for results from prompt {prompt_id}...")
    start_time = time.time()
    deadline = time.time() + POLL_TIMEOUT_S
    poll_count = 0
    
    while time.time() < deadline:
        poll_count += 1
        elapsed = time.time() - start_time
        logger.debug(f"Poll {poll_count}: {elapsed:.1f}s elapsed, {deadline - time.time():.1f}s remaining")
        
        r = requests.get(f"{base_url.rstrip('/')}/history/{prompt_id}", timeout=60)
        if r.status_code == 200:
            hist = r.json()
            if hist and prompt_id in hist:
                outputs = hist[prompt_id].get("outputs", {})
                node = outputs.get(OUTPUT_NODE_ID)
                if not node:
                    for _, v in outputs.items():
                        if v.get("images"):
                            node = v
                            break
                if node and node.get("images"):
                    total_time = time.time() - start_time
                    logger.info(f"Results received after {total_time:.1f}s and {poll_count} polls")
                    return hist
        else:
            logger.warning(f"Poll {poll_count} returned status {r.status_code}")
        
        time.sleep(POLL_INTERVAL_S)
    
    total_time = time.time() - start_time
    logger.error(f"Timed out after {total_time:.1f}s and {poll_count} polls")
    raise HTTPException(status_code=504, detail="Timed out waiting for ComfyUI")

def _fetch_first_image(history: dict, prompt_id: str, base_url: str) -> bytes:
    logger.info("Fetching processed image from ComfyUI...")
    outputs = history[prompt_id]["outputs"]
    node = outputs.get(OUTPUT_NODE_ID)
    if not node:
        for _, v in outputs.items():
            if v.get("images"):
                node = v
                break
    if not node or not node.get("images"):
        logger.error("No output images found in ComfyUI response")
        raise HTTPException(status_code=500, detail="No output images found")

    info = node["images"][0]  # {'filename','subfolder','type'}
    logger.info(f"Found output image: {info.get('filename', 'unknown')} in {info.get('subfolder', 'root')}")
    
    params = {
        "filename": info["filename"],
        "subfolder": info.get("subfolder", ""),
        "type": info.get("type", "output"),
    }
    r = requests.get(f"{base_url.rstrip('/')}/view", params=params, timeout=120)
    r.raise_for_status()
    image_size = len(r.content)
    logger.info(f"Successfully fetched image ({image_size} bytes)")
    return r.content

def _process_single_image(img_bytes: bytes, original_name: str, base_url: str, graph: dict) -> tuple[str, bytes]:
    """Process a single image and return (filename, processed_image_bytes)"""
    logger.info(f"Processing single image: {original_name}")
    start_time = time.time()
    
    # Upload to ComfyUI
    comfy_name = _upload_to_comfy(img_bytes, original_name, base_url)
    
    # Set the input node's image
    node = graph.get(INPUT_NODE_ID) or graph.get(int(INPUT_NODE_ID))
    if not node:
        logger.error(f"Input node {INPUT_NODE_ID} not found in workflow JSON")
        raise HTTPException(status_code=500, detail=f"Input node {INPUT_NODE_ID} not found in workflow JSON")
    node.setdefault("inputs", {})["image"] = comfy_name
    logger.debug(f"Set input node {INPUT_NODE_ID} image to: {comfy_name}")
    
    # Queue and poll
    pid = _queue_prompt(graph, base_url)
    history = _poll_history(pid, base_url)
    
    # Fetch result
    out_bytes = _fetch_first_image(history, pid, base_url)
    
    total_time = time.time() - start_time
    logger.info(f"Completed processing '{original_name}' in {total_time:.1f}s")
    return original_name, out_bytes

def _is_zip_file(filename: str) -> bool:
    """Check if file is a zip file based on extension"""
    is_zip = filename.lower().endswith('.zip')
    logger.info(f"File '{filename}' detected as {'ZIP' if is_zip else 'single image'}")
    return is_zip

def _extract_images_from_zip(zip_bytes: bytes) -> list[tuple[str, bytes]]:
    """Extract images from zip file, return list of (filename, image_bytes)"""
    logger.info("Extracting images from ZIP file...")
    images = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zip_file:
            total_files = len(zip_file.filelist)
            logger.info(f"ZIP contains {total_files} total files")
            
            for i, file_info in enumerate(zip_file.filelist, 1):
                filename = file_info.filename
                # Skip directories and non-image files
                if file_info.is_dir():
                    logger.debug(f"Skipping directory: {filename}")
                    continue
                
                # Check if it's an image file
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')):
                    try:
                        image_bytes = zip_file.read(filename)
                        images.append((filename, image_bytes))
                        logger.info(f"Extracted image {i}/{total_files}: {filename} ({len(image_bytes)} bytes)")
                    except Exception as e:
                        logger.warning(f"Failed to extract corrupted file {filename}: {e}")
                        continue
                else:
                    logger.debug(f"Skipping non-image file: {filename}")
    except Exception as e:
        logger.error(f"Failed to read ZIP file: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid zip file: {e}")
    
    if not images:
        logger.error("No valid image files found in ZIP")
        raise HTTPException(status_code=400, detail="No valid image files found in zip")
    
    logger.info(f"Successfully extracted {len(images)} images from ZIP")
    return images

def _create_zip_response(processed_images: list[tuple[str, bytes]], original_filename: str) -> bytes:
    """Create a zip file containing all processed images and return as bytes"""
    logger.info(f"Creating ZIP response with {len(processed_images)} processed images...")
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, image_bytes in processed_images:
            # Clean filename to avoid path traversal issues
            safe_filename = os.path.basename(filename)
            zip_file.writestr(safe_filename, image_bytes)
            logger.debug(f"Added to ZIP: {safe_filename} ({len(image_bytes)} bytes)")
    
    zip_buffer.seek(0)
    zip_size = len(zip_buffer.getvalue())
    
    logger.info(f"ZIP response created: {zip_size} bytes")
    return zip_buffer.getvalue()

def process_image(file_bytes: bytes, original_name: str, comfy_url: str) -> tuple[str, bytes]:
    """Main function to process an image and return (filename, processed_image_bytes)"""
    # Load workflow JSON once
    try:
        logger.info(f"Loading workflow from: {WORKFLOW_JSON}")
        with open(WORKFLOW_JSON, "r", encoding="utf-8") as f:
            graph = json.load(f)
        logger.info("Workflow JSON loaded successfully")
    except Exception as e:
        logger.error(f"Failed to read workflow JSON: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read workflow JSON '{WORKFLOW_JSON}': {e}")

    # Check if it's a zip file or single image
    if _is_zip_file(original_name):
        # Handle zip file with multiple images
        logger.info("Processing ZIP file with multiple images...")
        images = _extract_images_from_zip(file_bytes)
        processed_images = []
        
        # Process each image sequentially
        for i, (filename, image_bytes) in enumerate(images, 1):
            logger.info(f"Processing image {i}/{len(images)}: {filename}")
            try:
                # Create a copy of the graph for each image to avoid conflicts
                graph_copy = json.loads(json.dumps(graph))
                result = _process_single_image(image_bytes, filename, comfy_url, graph_copy)
                processed_images.append(result)
                logger.info(f"Successfully processed image {i}/{len(images)}: {filename}")
            except Exception as e:
                logger.error(f"Failed to process image {filename}: {e}")
                # Continue processing other images even if one fails
                continue
        
        if not processed_images:
            logger.error("Failed to process any images from ZIP")
            raise HTTPException(status_code=500, detail="Failed to process any images from zip")
        
        logger.info(f"ZIP processing completed: {len(processed_images)}/{len(images)} images successful")
        
        # Return zip file with all processed images
        return "zip", _create_zip_response(processed_images, original_name)
        
    else:
        # Handle single image (original functionality)
        logger.info("Processing single image...")
        result = _process_single_image(file_bytes, original_name, comfy_url, graph)
        filename, out_bytes = result
        
        logger.info("Single image processing completed")
        return filename, out_bytes

def get_health_info(comfy_url: str) -> dict:
    """Get health information"""
    return {
        "ok": True,
        "comfy_url": comfy_url,
        "workflow_json": WORKFLOW_JSON,
        "input_node_id": INPUT_NODE_ID,
        "output_node_id": OUTPUT_NODE_ID,
        "authentication": "disabled"
    } 