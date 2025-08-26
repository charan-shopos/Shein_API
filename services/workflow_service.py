import json
import os
import time
import requests
import uuid
import zipfile
import tempfile
import shutil
from urllib.parse import urlparse
from PIL import Image
import io
import logging
from datetime import datetime

# Configuration
workflow_path = 'Final Workflow n8n Working/Comfi_workflow.json'
background_image_path = 'Final Workflow n8n Working/WhiteBackground_Template.png'
style_folder = 'Final Workflow n8n Working/style_images2'

# Constants
MAX_RETRIES = 3
POLLING_TIMEOUT = 500
POLLING_INTERVAL = 5
RETRY_DELAY = 2

logger = logging.getLogger(__name__)

def setup_logging():
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f'{log_dir}/api_processing_{timestamp}.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def ensure_http_protocol(url):
    parsed_url = urlparse(url)
    if parsed_url.scheme not in ['http', 'https']:
        return f"http://{url}"
    return url

def load_json_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        logger.error(f"File {filepath} not found")
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in {filepath}")
    return None

def verify_required_files():
    required = {
        'Background': background_image_path,
        'Workflow': workflow_path,
        'Style Folder': style_folder
    }
    missing = []
    for desc, path in required.items():
        if not os.path.exists(path):
            missing.append(f"{desc} ({path})")
    if missing:
        logger.error(f"Missing required files: {', '.join(missing)}")
        return False
    return True

def extract_zip_to_temp(zip_file, extract_path: str) -> bool:
    """Extract uploaded ZIP file to temporary directory"""
    logger.info(f"=== ZIP EXTRACTION START ===")
    logger.info(f"Filename: {zip_file.filename}")
    
    try:
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        temp_zip_path = os.path.join(temp_dir, zip_file.filename)
        
        # Save uploaded file to temp location
        with open(temp_zip_path, 'wb') as temp_file:
            shutil.copyfileobj(zip_file.file, temp_file)
        
        # Extract ZIP file
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        
        # List extracted contents
        extracted_files = []
        for root, dirs, files in os.walk(extract_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, extract_path)
                extracted_files.append(rel_path)
        
        logger.info(f"Extracted {len(extracted_files)} files:")
        for file in extracted_files[:10]:  # Show first 10 files
            logger.info(f"  - {file}")
        if len(extracted_files) > 10:
            logger.info(f"  ... and {len(extracted_files) - 10} more files")
        
        # Clean up temp files
        shutil.rmtree(temp_dir)
        
        logger.info(f"=== ZIP EXTRACTION COMPLETED ===")
        return True
        
    except Exception as e:
        logger.error(f"Failed to extract ZIP file: {str(e)}")
        # Clean up temp files on error
        try:
            if 'temp_dir' in locals():
                shutil.rmtree(temp_dir)
        except:
            pass
        return False

def upload_image_with_retry(image_path: str, server_url: str, make_unique: bool = False) -> str:
    """Upload image to ComfyUI server with retry logic"""
    if not os.path.exists(image_path):
        logger.error(f"Image file not found: {image_path}")
        return None
    
    for attempt in range(MAX_RETRIES):
        try:
            with open(image_path, 'rb') as image_file:
                files = {'image': image_file}
                
                if make_unique:
                    # Add timestamp to filename to make it unique
                    filename = os.path.basename(image_path)
                    name, ext = os.path.splitext(filename)
                    timestamp = int(time.time() * 1000)
                    unique_filename = f"{name}_{timestamp}{ext}"
                    files = {'image': (unique_filename, image_file)}
                
                response = requests.post(f"{server_url.rstrip('/')}/upload/image", files=files, timeout=60)
                response.raise_for_status()
                
                result = response.json()
                uploaded_filename = result.get('name', os.path.basename(image_path))
                logger.info(f"Successfully uploaded {image_path} as {uploaded_filename}")
                return uploaded_filename
                
        except Exception as e:
            logger.warning(f"Upload attempt {attempt + 1} failed: {str(e)}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                logger.error(f"All upload attempts failed for {image_path}")
                return None
    
    return None

def get_required_style_images(prompts_data: dict) -> list:
    """Extract unique style image names from prompts data"""
    if not prompts_data:
        return []
    
    style_images = set()
    for product_data in prompts_data.values():
        if isinstance(product_data, dict):
            style = product_data.get('style_image')
            if style:
                style_images.add(style)
    
    return list(style_images)

def find_style_file_matches(required_styles: list) -> dict:
    """Find actual file paths that match required style names"""
    style_matches = {}
    
    if not os.path.exists(style_folder):
        logger.error(f"Style folder not found: {style_folder}")
        return style_matches
    
    # Get all files in style folder
    style_files = []
    for root, dirs, files in os.walk(style_folder):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                style_files.append(os.path.join(root, file))
    
    logger.info(f"Found {len(style_files)} style files in {style_folder}")
    
    # Try to match required styles with actual files
    for style_name in required_styles:
        best_match = None
        best_score = 0
        
        for file_path in style_files:
            filename = os.path.basename(file_path)
            name_without_ext = os.path.splitext(filename)[0]
            
            # Calculate similarity score
            score = 0
            if style_name.lower() in name_without_ext.lower():
                score += 1
            if name_without_ext.lower() in style_name.lower():
                score += 1
            
            # Exact match gets highest score
            if style_name.lower() == name_without_ext.lower():
                score += 10
            
            if score > best_score:
                best_score = score
                best_match = file_path
        
        if best_match and best_score > 0:
            style_matches[style_name] = best_match
            logger.info(f"Matched style '{style_name}' to file: {os.path.basename(best_match)}")
        else:
            logger.warning(f"No match found for style: {style_name}")
    
    return style_matches

def update_workflow(workflow: dict, input_filename: str, mask_filename: str, bg_filename: str, style_filename: str, prompt_data: dict) -> dict:
    """Update workflow with new image filenames and prompt data"""
    try:
        # Create a copy of the workflow to avoid modifying the original
        updated_workflow = json.loads(json.dumps(workflow))
        
        # Update input image node (assuming node ID 454)
        if '454' in updated_workflow:
            updated_workflow['454']['inputs']['image'] = input_filename
            logger.info(f"Updated input image node 454 with: {input_filename}")
        
        # Update mask image node (assuming node ID 439)
        if '439' in updated_workflow:
            updated_workflow['439']['inputs']['image'] = mask_filename
            logger.info(f"Updated mask image node 439 with: {mask_filename}")
        
        # Update background image node (assuming node ID 256)
        if '256' in updated_workflow:
            updated_workflow['256']['inputs']['image'] = bg_filename
            logger.info(f"Updated background image node 256 with: {bg_filename}")
        
        # Update style image node (assuming node ID 110)
        if '110' in updated_workflow:
            updated_workflow['110']['inputs']['image'] = style_filename
            logger.info(f"Updated style image node 110 with: {style_filename}")
        
        # Update prompt text node (assuming node ID 448)
        if '448' in updated_workflow:
            prompt_text = prompt_data.get('text', 'Generate a scene with the provided image and style')
            updated_workflow['448']['inputs']['string'] = prompt_text
            logger.info(f"Updated prompt text node 448 with: {prompt_text[:50]}...")
        
        return updated_workflow
        
    except Exception as e:
        logger.error(f"Failed to update workflow: {str(e)}")
        return None

def submit_workflow_to_comfyui(workflow: dict, server_url: str) -> str:
    """Submit workflow to ComfyUI and return prompt ID"""
    try:
        prompt_url = f"{server_url.rstrip('/')}/prompt"
        
        logger.info(f"Submitting workflow to: {prompt_url}")
        logger.info(f"Workflow has {len(workflow)} nodes")
        
        response = requests.post(prompt_url, json={'prompt': workflow}, timeout=120)
        response.raise_for_status()
        
        result = response.json()
        prompt_id = result.get('prompt_id')
        
        if prompt_id:
            logger.info(f"Successfully submitted workflow, got prompt ID: {prompt_id}")
            return prompt_id
        else:
            logger.error("ComfyUI response missing prompt_id")
            return None
            
    except Exception as e:
        logger.error(f"Failed to submit workflow to ComfyUI: {str(e)}")
        return None



def download_processed_image(prompt_id: str, server_url: str, output_path: str) -> bool:
    """Download the processed image from ComfyUI server"""
    try:
        logger.info(f"Waiting for ComfyUI to complete prompt: {prompt_id}")
        
        # Poll for completion
        start_time = time.time()
        max_attempts = POLLING_TIMEOUT // POLLING_INTERVAL
        
        for attempt in range(max_attempts):
            try:
                history_response = requests.get(f"{server_url.rstrip('/')}/history/{prompt_id}", timeout=30)
                history_response.raise_for_status()
                history = history_response.json()
                
                if prompt_id in history:
                    logger.info(f"ComfyUI completed prompt: {prompt_id}")
                    break
                    
            except requests.RequestException as e:
                logger.warning(f"Failed to get history (attempt {attempt + 1}): {e}")
                
            elapsed = time.time() - start_time
            if elapsed >= POLLING_TIMEOUT:
                logger.error(f"Timeout after {elapsed:.1f} seconds waiting for prompt: {prompt_id}")
                return False
                
            time.sleep(POLLING_INTERVAL)
        else:
            logger.error(f"Failed to get completion status for prompt: {prompt_id}")
            return False
        
        # Find the output image - specifically look for Node 15 like the working api.py
        outputs = history[prompt_id].get('outputs', {})
        preview_node = outputs.get("15", {})  # Node 15 output - matches working api.py
        
        if not preview_node or 'images' not in preview_node:
            logger.error(f"No output images found in Node 15 for prompt: {prompt_id}")
            logger.error(f"Available output nodes: {list(outputs.keys())}")
            # Fallback to any node with images
            for node_id, node_output in outputs.items():
                if 'images' in node_output and node_output['images']:
                    logger.warning(f"Using fallback node {node_id} instead of Node 15")
                    preview_node = node_output
                    break
            
            if not preview_node or 'images' not in preview_node:
                logger.error(f"No output images found in any node for prompt: {prompt_id}")
                return False
        
        # Get all images (like the working api.py does)
        images = preview_node['images']
        logger.info(f"Found {len(images)} output images from Node 15")
        
        # Download all variant images (up to 4 like the original api.py)
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        base_dir = os.path.dirname(output_path)
        ext = os.path.splitext(output_path)[1]
        
        downloaded_count = 0
        for idx, image_info in enumerate(images[:4]):  # Limit to 4 variants like original
            try:
                # Create variant filename like original: base_name_variant_1.jpg, base_name_variant_2.jpg, etc.
                if idx == 0:
                    # First image keeps the original name
                    variant_path = output_path
                else:
                    # Additional variants get numbered
                    variant_path = os.path.join(base_dir, f"{base_name}_variant_{idx + 1}{ext}")
                
                # Download the image
                params = {
                    'filename': image_info['filename'],
                    'subfolder': image_info.get('subfolder', ''),
                    'type': image_info.get('type', 'output')
                }
                
                image_response = requests.get(f"{server_url.rstrip('/')}/view", params=params, timeout=60)
                image_response.raise_for_status()
                
                # Save the image
                with open(variant_path, 'wb') as f:
                    f.write(image_response.content)
                
                logger.info(f"Downloaded variant {idx + 1}: {variant_path}")
                downloaded_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to download variant {idx + 1}: {str(e)}")
                continue
        
        if downloaded_count > 0:
            logger.info(f"Successfully downloaded {downloaded_count} image variants")
            return True
        else:
            logger.error("Failed to download any image variants")
            return False
        
    except Exception as e:
        logger.error(f"Failed to download processed image: {str(e)}")
        return False

def process_images_api(workflow: dict, server_url: str, prompts_data: dict, input_folder: str, mask_folder: str, output_folder: str, task_id: str = None):
    """Main function to process images using the workflow"""
    try:
        # Check if this is synchronous processing
        is_sync = task_id == "SYNC_PROCESSING"
        
        logger.info("Starting to process images...")
        
        # Step 1: Upload background image
        logger.info(f"Attempting to upload background image to ComfyUI server: {server_url}")
        bg_filename = upload_image_with_retry(background_image_path, server_url, make_unique=True)
        if not bg_filename:
            error_msg = f"Failed to upload background file to ComfyUI server. Please check if the server at {server_url} is running and accessible."
            logger.error(error_msg)
            raise Exception(error_msg)
        
        # Step 2: Get all required style images from prompts.json
        required_styles = get_required_style_images(prompts_data)
        
        if not required_styles:
            error_msg = "No style images referenced in prompts.json"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        logger.info(f"Found {len(required_styles)} unique style images referenced in prompts.json")
        
        # Step 3: Find matching files for each required style
        style_file_matches = find_style_file_matches(required_styles)
        
        # Check if we found all required styles
        missing_styles = [style for style in required_styles if style not in style_file_matches]
        if missing_styles:
            error_msg = f"Cannot proceed. Missing required style images: {', '.join(missing_styles)}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        logger.info(f"Found matching files for all {len(required_styles)} required style images")
        
        # Step 4: Upload only the required style images
        style_images = {}
        upload_failures = []
        
        for style_name, file_path in style_file_matches.items():
            logger.info(f"Uploading required style image: {os.path.basename(file_path)} -> {style_name}")
            uploaded_filename = upload_image_with_retry(file_path, server_url, make_unique=True)
            
            if uploaded_filename:
                style_images[style_name] = uploaded_filename
                logger.info(f"Successfully uploaded style image for '{style_name}'")
            else:
                upload_failures.append(style_name)
                logger.error(f"Failed to upload style image for '{style_name}'")
        
        # Check if all uploads succeeded
        if upload_failures:
            error_msg = f"Cannot proceed. Failed to upload style images: {', '.join(upload_failures)}"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        logger.info(f"Successfully uploaded all {len(style_images)} required style images")

        # Step 5: Process all images that have matching masks
        logger.info("Starting image processing - processing all images with matching masks")
        
        # Get all image files from input_images directory
        input_images = [f for f in os.listdir(input_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        logger.info(f"Found {len(input_images)} images in input_images directory: {input_images}")
        
        # Get all mask files from masks directory
        mask_files = [f for f in os.listdir(mask_folder) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        logger.info(f"Found {len(mask_files)} masks in masks directory: {mask_files}")
        
        # Find matching pairs (image + mask with same base name)
        matching_pairs = []
        for image_file in input_images:
            image_base = os.path.splitext(image_file)[0]
            mask_jpg = f"{image_base}.jpg"
            mask_png = f"{image_base}.png"
            
            if mask_jpg in mask_files or mask_png in mask_files:
                mask_file = mask_jpg if mask_jpg in mask_files else mask_png
                matching_pairs.append((image_file, mask_file))
                logger.info(f"Found matching pair: {image_file} -> {mask_file}")
            else:
                logger.warning(f"No mask found for {image_file}, skipping")
        
        logger.info(f"Found {len(matching_pairs)} matching image-mask pairs to process")
        
        if not matching_pairs:
            raise Exception("No matching image-mask pairs found")
        
        # Get default prompt and style from the first product (or use defaults)
        default_prompt = "Generate a scene with the provided image and style"
        default_style = "Urban street"
        
        if prompts_data:
            # Use the first product's settings for all images
            first_product_data = list(prompts_data.values())[0]
            if isinstance(first_product_data, dict):
                default_prompt = first_product_data.get("text", default_prompt)
                default_style = first_product_data.get("style_image", default_style)
        
        logger.info(f"Using default prompt: {default_prompt[:100]}...")
        logger.info(f"Using default style: {default_style}")
        
        # Get style filename
        if default_style not in style_images:
            logger.warning(f"Style image '{default_style}' not found, using first available style")
            default_style = list(style_images.keys())[0] if style_images else "Urban street"
        
        style_filename = style_images[default_style]
        logger.info(f"Using style image: {style_filename}")
        
        # Create output directory
        output_dir = os.path.join(output_folder, "processed_images")
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Created output directory: {output_dir}")
        
        # Process each matching pair
        successful_images = 0
        failed_images = 0
        
        for idx, (image_file, mask_file) in enumerate(matching_pairs):
            logger.info(f"Processing pair {idx + 1}/{len(matching_pairs)}: {image_file} + {mask_file}")
            
            try:
                input_path = os.path.join(input_folder, image_file)
                mask_path = os.path.join(mask_folder, mask_file)
                
                # Upload images to ComfyUI
                input_filename = upload_image_with_retry(input_path, server_url, make_unique=True)
                mask_filename = upload_image_with_retry(mask_path, server_url, make_unique=True)
                
                if not input_filename or not mask_filename:
                    logger.error(f"Failed to upload input image or mask: {input_path}")
                    failed_images += 1
                    continue

                # Create the prompt data
                prompt_data = {
                    "text": default_prompt
                }

                updated_workflow = update_workflow(
                    workflow, input_filename, mask_filename, bg_filename, style_filename, prompt_data
                )
                
                if not updated_workflow:
                    logger.error(f"Failed to update workflow for {image_file}")
                    failed_images += 1
                    continue
                
                # Submit workflow to ComfyUI
                prompt_id = submit_workflow_to_comfyui(updated_workflow, server_url)
                if not prompt_id:
                    logger.error(f"Failed to submit workflow for {image_file}")
                    failed_images += 1
                    continue
                
                # Download processed image (includes waiting for completion)
                output_filename = f"processed_{image_file}"
                output_path = os.path.join(output_dir, output_filename)
                
                if download_processed_image(prompt_id, server_url, output_path):
                    successful_images += 1
                    logger.info(f"Successfully processed: {image_file}")
                else:
                    failed_images += 1
                    logger.error(f"Failed to download processed image for {image_file}")
                
            except Exception as e:
                logger.error(f"Error processing {image_file}: {str(e)}")
                failed_images += 1
                continue
        
        logger.info(f"Processing completed: {successful_images} successful, {failed_images} failed")
        
        if successful_images == 0:
            raise Exception("No images were processed successfully")
        
        return True
        
    except Exception as e:
        logger.error(f"Image processing failed: {str(e)}")
        raise e 