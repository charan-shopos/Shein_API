import json
import os
import base64
import time
import random
import re
import zipfile
import tempfile
import shutil
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image
from io import BytesIO
from openai import OpenAI
from datetime import datetime
import traceback
import uuid

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, continue without it

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-actual-api-key-here")
PROMPT_LIBRARY_FILE = "PromptMap n8n Working/promptlib.json"

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger(__name__)

def setup_logging():
    """Setup comprehensive logging with file rotation and console output"""
    
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("image_processing_api")
    logger.setLevel(logging.DEBUG)
    
    # Prevent duplicate handlers
    if logger.handlers:
        logger.handlers.clear()
    
    # Console handler with INFO level
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s'
    )
    console_handler.setFormatter(console_format)
    
    # File handler with DEBUG level and rotation
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/api.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(funcName)s:%(lineno)d | %(message)s | %(pathname)s:%(lineno)d'
    )
    file_handler.setFormatter(file_format)
    
    # Error file handler for errors only
    error_handler = logging.handlers.RotatingFileHandler(
        "logs/errors.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_format)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    
    return logger

def api_call_with_retry(func, max_retries=3, delay=1):
    """Retry API calls with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            wait_time = delay * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time:.2f}s: {e}")
            time.sleep(wait_time)

def encode_image_with_resizing(image_path, max_size=1024, quality=85):
    """Encode image to base64 with resizing for OpenAI API"""
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Resize if too large
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Save to buffer with specified quality
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
            buffer.seek(0)
            
            # Encode to base64
            image_data = buffer.getvalue()
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            logger.debug(f"Image encoded: {os.path.basename(image_path)} -> {len(base64_image)} chars, size: {img.size}")
            return base64_image, img.size
            
    except Exception as e:
        logger.error(f"Error encoding image {image_path}: {e}")
        raise e

def load_prompt_library():
    """Load the prompt library from JSON file"""
    try:
        with open(PROMPT_LIBRARY_FILE, 'r', encoding='utf-8') as f:
            prompt_library = json.load(f)
        logger.info(f"Prompt library loaded: {len(prompt_library)} prompts")
        return prompt_library
    except Exception as e:
        logger.error(f"Error loading prompt library: {e}")
        raise e

# Gender file functionality removed - now using auto-detection

def find_matching_prompt(background_name, prompt_library):
    """Find the best matching prompt for a background with priority-based matching"""
    logger.debug(f"Finding matching prompt for background: {background_name}")
    
    # Priority 1: Exact match
    if background_name in prompt_library:
        logger.debug(f"Exact match found: {background_name}")
        return prompt_library[background_name], background_name
    
    # Priority 2: If background has _women, try without it
    if background_name.endswith('_women'):
        base_name = background_name[:-7]  # Remove '_women'
        logger.debug(f"Trying without _women suffix: {background_name} → {base_name}")
        for prompt_key in prompt_library.keys():
            if prompt_key.lower() == base_name.lower():
                logger.debug(f"Match found without _women: {base_name} → {prompt_key}")
                return prompt_library[prompt_key], prompt_key
    
    # Priority 3: Try partial match
    for prompt_key in prompt_library.keys():
        if (background_name.lower() in prompt_key.lower() or 
            prompt_key.lower() in background_name.lower()):
            logger.debug(f"Partial match found: {background_name} → {prompt_key}")
            return prompt_library[prompt_key], prompt_key
    
    logger.warning(f"No matching prompt found for background: {background_name}")
    return None, None

def detect_gender_from_image(image_path):
    """Detect gender from the person/model in the image using OpenAI with logging"""
    logger.info(f"Detecting gender from image: {os.path.basename(image_path)}")
    
    def _detect_gender_internal():
        try:
            base64_image, new_size = encode_image_with_resizing(image_path, max_size=1024, quality=85)

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": """You are a visual analysis expert. Your task is to identify the gender of the person/model in the image.

IMPORTANT RULES:
- Look at the PERSON/MODEL in the image, not the clothing
- Analyze facial features, body structure, and overall appearance
- Consider hair style, facial features, body proportions
- Focus on the human subject, not the garments they're wearing
- If you can see a face, use facial features as the primary indicator

Respond with ONLY 'Men' or 'Women' based on the person's gender."""},
                    {"role": "user", "content": [
                        {"type": "text", "text": "What is the gender of the person/model in this image? Look at the person themselves, not their clothing. Respond with only 'Men' or 'Women'."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]}
                ],
                max_tokens=15
            )
            
            response_text = response.choices[0].message.content.strip()
            logger.debug(f"OpenAI gender detection response: '{response_text}'")
            
            # Check for 'women' first since 'men' is a substring of 'women'
            if 'women' in response_text.lower():
                logger.info(f"Gender detected: Women")
                return 'Women'
            elif 'men' in response_text.lower():
                logger.info(f"Gender detected: Men")
                return 'Men'
            else:
                logger.warning(f"Could not parse gender from response: '{response_text}'")
                return None
                
        except Exception as e:
            logger.error(f"Error in gender detection internal function: {e}", exc_info=True)
            raise e
    
    return api_call_with_retry(_detect_gender_internal)

def select_all_images_per_folder(base_folder):
    """Select all images from each subfolder with logging, handles both nested and flat structures"""
    logger.info(f"Selecting images from base folder: {base_folder}")
    logger.info(f"Base folder exists: {os.path.exists(base_folder)}")
    logger.info(f"Base folder is directory: {os.path.isdir(base_folder)}")
    
    folder_images = {}
    
    if not os.path.exists(base_folder):
        logger.error(f"Base folder not found: {base_folder}")
        return folder_images
        
    logger.debug(f"Scanning base folder: {base_folder}")
    items = os.listdir(base_folder)
    logger.debug(f"Items in base folder: {items}")
    
    # Check if this is a flat structure (all items are files) or nested structure (has directories)
    has_directories = any(os.path.isdir(os.path.join(base_folder, item)) for item in items)
    
    if has_directories:
        logger.info("Detected nested folder structure")
        # Process nested folders as before
        for folder in sorted(items):
            folder_path = os.path.join(base_folder, folder)
            logger.debug(f"Checking item: {folder} (path: {folder_path})")
            
            if os.path.isdir(folder_path):
                logger.debug(f"Item is directory: {folder}")
                try:
                    # Get all image files
                    all_files = os.listdir(folder_path)
                    logger.debug(f"Files in {folder}: {all_files}")
                    
                    image_files = [img for img in all_files 
                                  if img.lower().endswith(('.jpg', '.png', '.jpeg'))]
                    logger.debug(f"Image files in {folder}: {image_files}")
                    
                    if not image_files:
                        logger.warning(f"No images found in folder: {folder}")
                        continue
                    
                    # Sort images and prioritize MODEL images first
                    image_files.sort()
                    
                    # Reorder to put MODEL images first
                    model_images = [img for img in image_files if 'MODEL' in img.upper()]
                    other_images = [img for img in image_files if 'MODEL' not in img.upper()]
                    sorted_images = model_images + other_images
                    
                    # Create full paths for all images
                    image_paths = [os.path.join(folder_path, img) for img in sorted_images]
                    folder_images[folder] = image_paths
                    
                    logger.info(f"Folder {folder}: {len(image_paths)} images selected ({len(model_images)} model images)")
                    
                except Exception as e:
                    logger.error(f"Error accessing folder {folder}: {e}", exc_info=True)
                    continue
    else:
        logger.info("Detected flat structure - creating virtual folders")
        # Handle flat structure - create virtual folders based on image names
        all_files = [item for item in items if os.path.isfile(os.path.join(base_folder, item))]
        image_files = [img for img in all_files if img.lower().endswith(('.jpg', '.png', '.jpeg'))]
        
        if not image_files:
            logger.warning("No image files found in flat structure")
            return folder_images
        
        logger.info(f"Found {len(image_files)} images in flat structure")
        
        # Group images by common prefixes or create individual folders
        if len(image_files) == 1:
            # Single image - create a folder with the image name
            image_name = os.path.splitext(image_files[0])[0]
            folder_name = f"single_{image_name}"
            image_paths = [os.path.join(base_folder, image_files[0])]
            folder_images[folder_name] = image_paths
            logger.info(f"Created single image folder: {folder_name}")
            
        else:
            # Multiple images - try to group them intelligently
            # First, try to find common prefixes
            prefixes = {}
            for img in image_files:
                # Remove extension and common suffixes
                base_name = os.path.splitext(img)[0]
                # Remove common suffixes like _001, _002, etc.
                clean_name = re.sub(r'_\d+$', '', base_name)
                if clean_name not in prefixes:
                    prefixes[clean_name] = []
                prefixes[clean_name].append(img)
            
            # Create folders for each prefix group
            for prefix, images in prefixes.items():
                if len(images) == 1:
                    folder_name = f"single_{prefix}"
                else:
                    folder_name = f"group_{prefix}"
                
                # Sort images and prioritize MODEL images first
                images.sort()
                model_images = [img for img in images if 'MODEL' in img.upper()]
                other_images = [img for img in images if 'MODEL' not in img.upper()]
                sorted_images = model_images + other_images
                
                # Create full paths for all images
                image_paths = [os.path.join(base_folder, img) for img in sorted_images]
                folder_images[folder_name] = image_paths
                
                logger.info(f"Created folder {folder_name}: {len(image_paths)} images ({len(model_images)} model images)")
    
    logger.info(f"Total folders processed: {len(folder_images)}")
    return folder_images

def generate_comprehensive_folder_description(image_paths):
    """Generate a comprehensive clothing description for an entire folder by analyzing all images with logging"""
    logger.info(f"Generating comprehensive description for folder with {len(image_paths)} images")
    
    def _generate_comprehensive_description_internal():
        try:
            # Analyze first image to get base description
            first_image_path = image_paths[0]
            logger.debug(f"Analyzing first image: {os.path.basename(first_image_path)}")
            
            base64_image, new_size = encode_image_with_resizing(first_image_path, max_size=1024, quality=85)

            prompt = """You are a fashion analysis expert. Analyze this image and provide a comprehensive clothing description.

IMPORTANT: This image is part of a folder containing multiple images of the same outfit from different angles. Your task is to provide the MOST COMPLETE and ACCURATE description possible by carefully examining all visible details.

Describe the outfit in this exact format:
'Wearing a [color] [fit] [type of upper clothing] with [notable design/detail], paired with [color] [fit] [type of lower clothing] with [notable design/detail], and completed with [footwear].'

Be specific about:
- Colors (exact shades if possible)
- Fit (loose, fitted, oversized, etc.)
- Fabric types (cotton, silk, denim, etc.)
- Design details (buttons, zippers, patterns, textures)
- Accessories visible in the image

Respond with ONLY the description, no additional text."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a fashion analysis expert. Provide detailed, accurate clothing descriptions."},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]}
                ],
                max_tokens=200
            )
            
            description = response.choices[0].message.content.strip()
            logger.debug(f"Generated description: {description[:100]}...")
            return description
            
        except Exception as e:
            logger.error(f"Error generating comprehensive description: {e}", exc_info=True)
            raise e
    
    return api_call_with_retry(_generate_comprehensive_description_internal)

def clean_description(description):
    """Clean and format the description text"""
    if not description:
        return ""
    
    # Remove quotes and extra whitespace
    cleaned = description.strip().strip('"').strip("'")
    
    # Ensure it starts with 'Wearing'
    if not cleaned.lower().startswith('wearing'):
        cleaned = f"Wearing {cleaned}"
    
    # Clean up extra spaces and punctuation
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip()
    
    return cleaned

def get_available_style_files():
    """Get list of available style image files"""
    import os
    style_folder = "Final Workflow n8n Working/style_images2"
    try:
        if os.path.exists(style_folder):
            files = os.listdir(style_folder)
            # Remove extensions and .DS_Store files
            available_files = set()
            for file in files:
                if file.endswith(('.jpg', '.jpeg', '.png')) and not file.startswith('.'):
                    # Remove extension
                    name = os.path.splitext(file)[0]
                    available_files.add(name)
            return available_files
        return set()
    except Exception as e:
        logger.error(f"Error reading style files: {e}")
        return set()

def select_background_with_fallback(prompt_library, gender, max_attempts=10):
    """Select a background that has a corresponding style image file"""
    available_style_files = get_available_style_files()
    logger.debug(f"Found {len(available_style_files)} available style files")
    
    available_backgrounds = list(prompt_library.keys())
    if not available_backgrounds:
        return None
    
    # Try to find a background that has a corresponding style file
    for attempt in range(max_attempts):
        selected_background = random.choice(available_backgrounds)
        
        # Apply gender modification
        modified_background = modify_backgrounds_for_gender([selected_background], gender)[0]
        
        # Check if the style file exists
        if modified_background in available_style_files:
            logger.info(f"Selected background with available style file: {selected_background} → {modified_background}")
            return selected_background
        else:
            logger.debug(f"Attempt {attempt + 1}: {modified_background} not found in style files, trying another...")
    
    # If no exact match found, try to find any background for the gender
    gender_suffix = "_women" if gender == "Women" else ""
    fallback_options = []
    
    for bg_name in available_style_files:
        if gender == "Women" and bg_name.endswith("_women"):
            # Find corresponding prompt library key
            for prompt_key in available_backgrounds:
                if prompt_key.endswith("_women") and modify_backgrounds_for_gender([prompt_key], gender)[0] == bg_name:
                    fallback_options.append(prompt_key)
                    break
        elif gender == "Men" and not bg_name.endswith("_women"):
            # Find corresponding prompt library key  
            for prompt_key in available_backgrounds:
                if modify_backgrounds_for_gender([prompt_key], gender)[0] == bg_name:
                    fallback_options.append(prompt_key)
                    break
    
    if fallback_options:
        selected = random.choice(fallback_options)
        logger.warning(f"Used fallback background for {gender}: {selected}")
        return selected
    
    # Last resort - just pick any background
    selected = random.choice(available_backgrounds)
    logger.error(f"No suitable background found for {gender}, using random: {selected}")
    return selected

def modify_backgrounds_for_gender(backgrounds, gender):
    """Modify background names based on detected gender"""
    if not backgrounds:
        return backgrounds
    
    modified_backgrounds = []
    for background in backgrounds:
        if gender == 'Women' and not background.endswith('_women'):
            modified_background = f"{background}_women"
            logger.debug(f"Modified background for women: {background} → {modified_background}")
        elif gender == 'Men' and background.endswith('_women'):
            modified_background = background[:-7]  # Remove '_women'
            logger.debug(f"Modified background for men: {background} → {modified_background}")
        else:
            modified_background = background
            logger.debug(f"No modification needed: {background}")
        
        modified_backgrounds.append(modified_background)
    
    return modified_backgrounds

def process_zip_file(zip_file_path, temp_dir):
    """Process the uploaded ZIP file and return results"""
    try:
        logger.info(f"Processing ZIP file: {zip_file_path}")
        
        # Extract ZIP file
        extract_path = os.path.join(temp_dir, "extracted")
        os.makedirs(extract_path, exist_ok=True)
        
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
        
        logger.info(f"ZIP extracted to: {extract_path}")
        
        # Load prompt library
        prompt_library = load_prompt_library()
        
        # Get all images organized by folder
        folder_images = select_all_images_per_folder(extract_path)
        
        if not folder_images:
            logger.warning("No folders with images found in ZIP")
            return []
        
        # Process each folder
        results = []
        for folder_name, image_paths in folder_images.items():
            try:
                logger.info(f"Processing folder: {folder_name} with {len(image_paths)} images")
                
                # Detect gender from first image
                gender = detect_gender_from_image(image_paths[0])
                if not gender:
                    logger.warning(f"Could not detect gender for {folder_name}, using default")
                    gender = 'Women'  # Default to women
                
                # Select background with smart fallback to ensure style file exists
                selected_background = select_background_with_fallback(prompt_library, gender)
                if not selected_background:
                    logger.warning(f"No suitable background found for {folder_name}")
                
                # Generate comprehensive description
                comprehensive_description = generate_comprehensive_folder_description(image_paths)
                clean_comprehensive_description = clean_description(comprehensive_description)
                logger.info(f"Description generated for {folder_name}: {clean_comprehensive_description[:100]}...")
                
                # Modify background based on gender
                modified_background = modify_backgrounds_for_gender([selected_background], gender)[0] if selected_background else ""
                
                # Find matching prompt
                logger.debug(f"Finding matching prompt for folder: {folder_name}")
                selected_prompt = None
                selected_style_image = ""
                
                if modified_background:
                    prompt, prompt_key = find_matching_prompt(modified_background, prompt_library)
                    if prompt:
                        selected_prompt = prompt
                        selected_style_image = prompt_key
                        logger.debug(f"Prompt found for {folder_name}: {prompt_key}")
                
                # Generate final prompt text
                if selected_prompt:
                    final_text = selected_prompt.replace("Wearing,", f"{clean_comprehensive_description},")
                    final_text = final_text.replace("wearing,", f"{clean_comprehensive_description},")
                    final_text = final_text.replace("Wearing", clean_comprehensive_description)
                    final_text = final_text.replace("wearing", clean_comprehensive_description)
                    logger.debug(f"Final prompt text generated for {folder_name}")
                else:
                    logger.warning(f"No matching prompt found for {folder_name}, using description only")
                    final_text = clean_comprehensive_description
                
                # Create result
                folder_result = {
                    "folder_id": folder_name,
                    "description": clean_comprehensive_description,
                    "background_suggestion": modified_background,
                    "gender": gender,
                    "text": final_text,
                    "style_image": selected_style_image
                }
                
                results.append(folder_result)
                logger.info(f"Successfully processed folder: {folder_name}")
                
            except Exception as e:
                logger.error(f"Error processing folder {folder_name}: {e}", exc_info=True)
                # Add error result
                error_result = {
                    "folder_id": folder_name,
                    "description": f"Error: {str(e)}",
                    "background_suggestion": "",
                    "gender": "",
                    "text": f"Error: {str(e)}",
                    "style_image": ""
                }
                results.append(error_result)
        
        logger.info(f"Zip file processing completed. {len(results)} folders processed")
        return results
        
    except Exception as e:
        logger.error(f"Error processing zip file: {str(e)}", exc_info=True)
        raise Exception(f"Error processing zip file: {str(e)}") 