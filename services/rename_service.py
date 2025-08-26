import tempfile
import os
import shutil
import zipfile
from typing import List, Optional, Set, Dict, Any
import json
import cv2
import mediapipe as mp
import logging
from io import BytesIO

logger = logging.getLogger(__name__)

def cleanup_temp_directory(temp_dir: str):
    """Background task to clean up temporary directory."""
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"Temporary directory cleaned up: {temp_dir}")
    except Exception as e:
        logger.error(f"Error cleaning up temp directory: {str(e)}")

def create_zip_from_directory(directory: str) -> BytesIO:
    """Create a ZIP file from a directory and return it as BytesIO buffer."""
    zip_buffer = BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, directory)
                zipf.write(file_path, arcname)
    
    # Verify ZIP contents
    zip_buffer.seek(0)
    with zipfile.ZipFile(zip_buffer, 'r') as verify_zip:
        zip_contents = verify_zip.namelist()
        logger.info(f"ZIP created with {len(zip_contents)} files")
    
    # Reset buffer position for reading
    zip_buffer.seek(0)
    return zip_buffer

class FaceDetectionProcessor:
    def __init__(self, min_confidence: float = 0.5, max_face_bottom_ratio: float = 0.65, min_face_height_px: int = 40):
        self.min_confidence = min_confidence
        self.max_face_bottom_ratio = max_face_bottom_ratio
        self.min_face_height_px = min_face_height_px
        
        # Initialize MediaPipe
        mp_face_detection = mp.solutions.face_detection
        self.face_detection = mp_face_detection.FaceDetection(
            model_selection=1, 
            min_detection_confidence=min_confidence
        )
    
    def is_face_visible_mediapipe(self, img_path: str) -> bool:
        """Check if image has a valid face according to the specified rules."""
        image = cv2.imread(img_path)
        if image is None:
            return False
        
        height, _, _ = image.shape
        results = self.face_detection.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

        if not results.detections:
            return False

        for detection in results.detections:
            bbox = detection.location_data.relative_bounding_box
            y_min = bbox.ymin
            box_height = bbox.height

            # Convert normalized coordinates to pixels
            face_top = int(y_min * height)
            face_bottom = int((y_min + box_height) * height)

            # Check face bottom ≤ 0.65 * image_height and face height ≥ 40px
            if face_bottom > height * self.max_face_bottom_ratio or (face_bottom - face_top) < self.min_face_height_px:
                continue
            return True

        return False
    
    def next_closeup_name(self, existing_names: Set[str], ext: str) -> str:
        """Generate next available closeup name avoiding collisions."""
        index = 1
        while True:
            new_name = f"closeup({index}){ext}"
            if new_name not in existing_names:
                return new_name
            index += 1
    
    def process_images(self, input_dir: str, output_dir: str) -> Dict[str, Any]:
        """Process all images in the input directory tree and copy to output with renaming."""
        logger.info(f"Processing images from {input_dir} to {output_dir}")
        
        # Get all image files recursively
        image_files = []
        for root, dirs, files in os.walk(input_dir):
            for file in files:
                if file.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp')):
                    image_files.append(os.path.join(root, file))
        
        logger.info(f"Found {len(image_files)} image files to process")
        
        if not image_files:
            return {
                "total_images": 0,
                "processed_images": 0,
                "renamed_images": 0,
                "skipped_images": 0,
                "errors": [],
                "processing_details": []
            }
        
        # Process each image
        processed_count = 0
        renamed_count = 0
        skipped_count = 0
        errors = []
        processing_details = []
        existing_names = set()
        
        for img_path in image_files:
            try:
                # Get relative path from input directory
                rel_path = os.path.relpath(img_path, input_dir)
                filename = os.path.basename(img_path)
                name, ext = os.path.splitext(filename)
                
                # Check if face is visible
                has_face = self.is_face_visible_mediapipe(img_path)
                
                if has_face:
                    # Keep original name
                    new_filename = filename
                    renamed = False
                    reason = "Face detected - kept original name"
                else:
                    # Generate new closeup name
                    new_filename = self.next_closeup_name(existing_names, ext)
                    existing_names.add(new_filename)
                    renamed = True
                    reason = "No valid face detected - renamed to closeup"
                
                # Create output path
                output_path = os.path.join(output_dir, new_filename)
                
                # Copy file to output
                shutil.copy2(img_path, output_path)
                
                # Update counters
                processed_count += 1
                if renamed:
                    renamed_count += 1
                else:
                    skipped_count += 1
                
                # Add to processing details
                processing_details.append({
                    "original_file": rel_path,
                    "new_filename": new_filename,
                    "renamed": renamed,
                    "reason": reason,
                    "face_detected": has_face
                })
                
                logger.info(f"Processed: {rel_path} -> {new_filename} ({'renamed' if renamed else 'kept'})")
                
            except Exception as e:
                error_msg = f"Error processing {img_path}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                continue
        
        # Create results summary
        results = {
            "total_images": len(image_files),
            "processed_images": processed_count,
            "renamed_images": renamed_count,
            "skipped_images": skipped_count,
            "errors": errors,
            "processing_details": processing_details
        }
        
        logger.info(f"Processing completed: {processed_count} processed, {renamed_count} renamed, {skipped_count} skipped, {len(errors)} errors")
        return results
    
    def cleanup(self):
        """Clean up MediaPipe resources."""
        if hasattr(self, 'face_detection'):
            self.face_detection.close()
            logger.info("MediaPipe face detection cleaned up")

def process_zip_file(zip_file, temp_dir: str, input_dir: str) -> bool:
    """Process uploaded ZIP file and extract to input directory."""
    try:
        logger.info(f"Processing ZIP file: {zip_file.filename}")
        
        # Handle ZIP file upload
        if not zip_file.filename.lower().endswith('.zip'):
            raise ValueError("zip_file must be a ZIP file")
        
        # Save ZIP to temp location
        zip_path = os.path.join(temp_dir, "upload.zip")
        
        # Reset file pointer and read content
        zip_file.file.seek(0)
        with open(zip_path, "wb") as f:
            shutil.copyfileobj(zip_file.file, f)
        
        # Extract ZIP
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(input_dir)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to process ZIP file: {str(e)}")
        return False

def process_individual_files(files: List, input_dir: str) -> bool:
    """Process individual uploaded files."""
    try:
        logger.info(f"Processing {len(files)} individual files")
        
        for file in files:
            if file.filename:
                file_path = os.path.join(input_dir, file.filename)
                with open(file_path, "wb") as f:
                    shutil.copyfileobj(file.file, f)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to process individual files: {str(e)}")
        return False

def create_manifest_file(output_dir: str, results: Dict[str, Any]) -> str:
    """Create manifest.json file in output directory."""
    try:
        manifest_path = os.path.join(output_dir, "manifest.json")
        with open(manifest_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Manifest file created: {manifest_path}")
        return manifest_path
        
    except Exception as e:
        logger.error(f"Failed to create manifest file: {str(e)}")
        return None 