import pytesseract
import easyocr
import pdfplumber
import cv2
import numpy as np
from PIL import Image
import os
import io
import pdf2image
import fitz  # PyMuPDF
from datetime import datetime

class InvoiceInputLayer:
    """Stage 1: Invoice Input Layer - Preprocessing and format handling"""

    def __init__(self):
        self.supported_formats = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tiff']

    def validate_file(self, file_path):
        """Validate uploaded file format and size"""
        if not os.path.exists(file_path):
            raise ValueError("File does not exist")

        file_extension = os.path.splitext(file_path)[1].lower()
        if file_extension not in self.supported_formats:
            raise ValueError(f"Unsupported file format: {file_extension}")

        # Check file size (max 10MB)
        file_size = os.path.getsize(file_path)
        if file_size > 10 * 1024 * 1024:
            raise ValueError("File size exceeds 10MB limit")

        return {
            'filename': os.path.basename(file_path),
            'file_type': file_extension,
            'file_size': file_size,
            'upload_timestamp': datetime.now().isoformat()
        }

    def convert_pdf_to_images(self, pdf_path, dpi=300):
        """Convert PDF pages to images using PyMuPDF (primary) or pdf2image (fallback)"""
        # Try PyMuPDF first (doesn't require poppler)
        try:
            doc = fitz.open(pdf_path)
            images = []
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=dpi)
                img = Image.open(io.BytesIO(pix.tobytes()))
                images.append(img)
            doc.close()
            return images
        except Exception as e1:
            # Fallback to pdf2image if PyMuPDF fails
            try:
                images = pdf2image.convert_from_path(pdf_path, dpi=dpi)
                return images
            except Exception as e2:
                raise Exception(f"PDF conversion failed: PyMuPDF error: {str(e1)}, pdf2image error: {str(e2)}. Please ensure poppler is installed if using pdf2image.")

    def preprocess_image(self, image):
        """Preprocess image for better OCR accuracy"""
        # Convert PIL to OpenCV format
        if isinstance(image, Image.Image):
            img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        else:
            img = image.copy()

        # Step 1: Grayscale conversion
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # Step 2: Simple noise reduction (faster than fastNlMeansDenoising)
        denoised = cv2.medianBlur(gray, 3)

        # Step 3: Skip deskewing for speed (can be added back if needed)
        deskewed = denoised

        # Step 4: Resize/normalize for OCR (optimal size for Tesseract)
        # Skip upscaling for speed - only downscale very large images
        height, width = deskewed.shape
        if height > 2000 or width > 2000:
            # Downscale very large images only
            scale_factor = min(2000 / height, 2000 / width)
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            resized = cv2.resize(deskewed, (new_width, new_height), interpolation=cv2.INTER_AREA)
        else:
            resized = deskewed

        # Step 5: Simple contrast enhancement (faster)
        enhanced = cv2.convertScaleAbs(resized, alpha=1.1, beta=5)

        return enhanced

    def deskew_image(self, image):
        """Deskew scanned image to correct rotation"""
        # Find all contours
        contours, _ = cv2.findContours(image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return image

        # Find the largest contour (likely the main content)
        largest_contour = max(contours, key=cv2.contourArea)

        # Get minimum area rectangle
        rect = cv2.minAreaRect(largest_contour)
        angle = rect[2]

        # Correct angle if needed
        if angle < -45:
            angle = 90 + angle

        # Rotate image
        if abs(angle) > 0.5:  # Only rotate if skew is significant
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            return rotated

        return image

    def process_input(self, file_path):
        """Main processing function for Stage 1 - optimized for speed"""
        # Validate file
        metadata = self.validate_file(file_path)

        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension == '.pdf':
            # Try to extract text directly from PDF first (much faster for text-based PDFs)
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    pdf_text = []
                    for page in pdf.pages[:1]:  # Process first page only for speed
                        text = page.extract_text()
                        if text:
                            pdf_text.append(text)
                    
                    if pdf_text and len(' '.join(pdf_text).strip()) > 50:
                        # If we got substantial text, return it directly (skip OCR)
                        return {
                            'metadata': metadata,
                            'processed_images': [{
                                'page_number': 1,
                                'image': None,  # No image needed
                                'original_pil': None,
                                'direct_text': ' '.join(pdf_text)  # Direct text extraction
                            }],
                            'total_pages': len(pdf.pages),
                            'direct_text_extraction': True
                        }
            except Exception as e:
                # If pdfplumber fails, fall back to OCR
                print(f"PDF text extraction failed, using OCR: {e}")
            
            # Convert PDF to images for OCR (only if direct extraction failed)
            images = self.convert_pdf_to_images(file_path)
            processed_images = []

            # Process only first page for speed
            for i, img in enumerate(images[:1]):
                processed = self.preprocess_image(img)
                processed_images.append({
                    'page_number': i + 1,
                    'image': processed,
                    'original_pil': img
                })

            return {
                'metadata': metadata,
                'processed_images': processed_images,
                'total_pages': len(images)
            }
        else:
            # Process single image
            img = Image.open(file_path)
            processed = self.preprocess_image(img)

            return {
                'metadata': metadata,
                'processed_images': [{
                    'page_number': 1,
                    'image': processed,
                    'original_pil': img
                }],
                'total_pages': 1
            }

class OCRLayoutExtraction:
    """Stage 2: OCR & Layout Extraction - Advanced text and structure extraction"""

    def __init__(self):
        # Initialize OCR engines
        self.tesseract_config = '--oem 3 --psm 6'
        self._easyocr_reader = None  # Lazy initialization
        self.use_easyocr = False  # Disable EasyOCR by default for speed
        
        # Check if Tesseract is available
        self.tesseract_available = False
        try:
            pytesseract.get_tesseract_version()
            self.tesseract_available = True
            print("Tesseract OCR found. Using Tesseract for faster processing.")
        except Exception:
            self.tesseract_available = False
            print("Warning: Tesseract OCR not found. EasyOCR will be used (slower).")
            self.use_easyocr = True  # Only use EasyOCR if Tesseract is not available

        # Initialize LayoutLM/Donut models (placeholder for now)
        self.layout_model_available = False
        try:
            # We'll add LayoutLM initialization here when available
            pass
        except:
            pass
    
    @property
    def easyocr_reader(self):
        """Lazy initialization of EasyOCR reader"""
        if self._easyocr_reader is None:
            try:
                # EasyOCR will download models on first use - this can take time
                # Set gpu=False to use CPU (faster initialization, slower processing)
                self._easyocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            except Exception as e:
                print(f"Warning: EasyOCR initialization failed: {e}")
                # Return a dummy reader that won't crash
                class DummyReader:
                    def readtext(self, image):
                        return []
                self._easyocr_reader = DummyReader()
        return self._easyocr_reader

    def extract_text_with_bounding_boxes(self, image):
        """Extract text with bounding box information - optimized for speed"""
        tesseract_data = None
        easyocr_result = None
        
        # Prioritize Tesseract (much faster than EasyOCR)
        if self.tesseract_available:
            try:
                tesseract_data = pytesseract.image_to_data(image, config=self.tesseract_config, output_type=pytesseract.Output.DICT)
                # If Tesseract worked, skip EasyOCR for speed
                if tesseract_data and len(tesseract_data.get('text', [])) > 0:
                    return {
                        'tesseract': tesseract_data,
                        'easyocr': []  # Skip EasyOCR for speed
                    }
            except Exception as e:
                print(f"Warning: Tesseract OCR failed: {e}")
                self.tesseract_available = False
                tesseract_data = None

        # Only use EasyOCR if Tesseract is not available or failed
        if self.use_easyocr and not self.tesseract_available:
            try:
                # EasyOCR can be slow on first use (downloading models)
                # Only use if absolutely necessary
                import time
                start_time = time.time()
                easyocr_result = self.easyocr_reader.readtext(image)
                elapsed = time.time() - start_time
                if elapsed > 30:  # If it took more than 30 seconds, warn
                    print(f"Warning: EasyOCR took {elapsed:.1f} seconds. This is normal on first use.")
            except Exception as e:
                print(f"Warning: EasyOCR failed: {e}")
                easyocr_result = []

        return {
            'tesseract': tesseract_data,
            'easyocr': easyocr_result or []
        }

    def detect_layout_regions(self, image):
        """Detect key regions in the invoice layout"""
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # Apply thresholding
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Find contours to identify text blocks
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        regions = []
        height, width = image.shape[:2]

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)

            # Filter small contours and very large ones
            if w > 50 and h > 10 and w < width * 0.9 and h < height * 0.9:
                # Classify region type based on position and size
                region_type = self.classify_region(x, y, w, h, width, height)
                regions.append({
                    'bbox': (x, y, x+w, y+h),
                    'type': region_type,
                    'confidence': 0.8  # Placeholder
                })

        return regions

    def classify_region(self, x, y, w, h, img_width, img_height):
        """Classify region type based on position and dimensions"""
        # Simple heuristic-based classification
        if y < img_height * 0.2:
            return 'header'
        elif y > img_height * 0.8:
            return 'footer'
        elif x < img_width * 0.3 and y < img_height * 0.5:
            return 'vendor_info'
        elif w > img_width * 0.6:
            return 'line_items'
        elif x > img_width * 0.7:
            return 'totals'
        else:
            return 'other'

    def extract_structured_fields(self, ocr_data, layout_regions):
        """Extract structured invoice fields from OCR data"""
        tesseract_data = ocr_data.get('tesseract')
        easyocr_data = ocr_data.get('easyocr', [])

        # Combine text from both OCR engines
        combined_text = self.combine_ocr_results(tesseract_data, easyocr_data)

        # Extract specific fields using regex and layout information
        fields = {}

        # Invoice number patterns
        import re
        invoice_patterns = [
            r'Invoice\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Invoice\s*Number\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Inv\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Bill\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
        ]

        for pattern in invoice_patterns:
            match = re.search(pattern, combined_text, re.IGNORECASE)
            if match:
                fields['invoice_number'] = {
                    'value': match.group(1),
                    'confidence': 0.95
                }
                break

        # Date patterns
        date_patterns = [
            r'Invoice\s*Date\s*[:\-]?\s*([\d/\-\.]+)',
            r'Date\s*[:\-]?\s*([\d/\-\.]+)',
            r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        ]

        for pattern in date_patterns:
            match = re.search(pattern, combined_text, re.IGNORECASE)
            if match:
                fields['invoice_date'] = {
                    'value': match.group(1),
                    'confidence': 0.90
                }
                break

        # Amount patterns
        amount_patterns = [
            r'Total\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
            r'Amount\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
            r'Grand\s*Total\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
        ]

        for pattern in amount_patterns:
            match = re.search(pattern, combined_text, re.IGNORECASE)
            if match:
                fields['total_amount'] = {
                    'value': float(match.group(1).replace(',', '')),
                    'confidence': 0.85
                }
                break

        # Vendor extraction (look in vendor_info regions)
        vendor_text = self.extract_region_text(combined_text, layout_regions, 'vendor_info')
        if vendor_text:
            fields['vendor_name'] = {
                'value': vendor_text.strip(),
                'confidence': 0.80
            }

        # Line items extraction (placeholder - would need more sophisticated table detection)
        fields['line_items'] = {
            'value': [],  # Would be populated by table extraction logic
            'confidence': 0.70
        }

        return fields

    def combine_ocr_results(self, tesseract_data, easyocr_data):
        """Combine results from multiple OCR engines"""
        texts = []
        
        # Extract text from Tesseract if available
        if tesseract_data and isinstance(tesseract_data, dict) and 'text' in tesseract_data:
            tesseract_text = ' '.join([text for text in tesseract_data['text'] if text.strip()])
            if tesseract_text:
                texts.append(tesseract_text)
        
        # Extract text from EasyOCR if available
        if easyocr_data:
            try:
                easyocr_text = ' '.join([text for _, text, _ in easyocr_data])
                if easyocr_text:
                    texts.append(easyocr_text)
            except (ValueError, IndexError):
                # Handle different EasyOCR result formats
                try:
                    easyocr_text = ' '.join([item[1] if len(item) > 1 else str(item) for item in easyocr_data])
                    if easyocr_text:
                        texts.append(easyocr_text)
                except Exception:
                    pass

        # Return combined text or empty string if both failed
        return ' '.join(texts) if texts else ''

    def extract_region_text(self, full_text, regions, region_type):
        """Extract text from specific layout regions"""
        # Placeholder - would need bounding box matching
        # For now, return a portion of text based on region type
        if region_type == 'vendor_info':
            # Extract first part of text (likely vendor info)
            words = full_text.split()[:10]  # First 10 words
            return ' '.join(words)
        return None

    def calculate_overall_confidence(self, fields):
        """Calculate overall extraction confidence"""
        if not fields:
            return 0.0

        confidences = [field['confidence'] for field in fields.values() if isinstance(field, dict) and 'confidence' in field]
        return sum(confidences) / len(confidences) if confidences else 0.5

    def process_document(self, processed_images):
        """Main processing function for Stage 2 - optimized for speed"""
        results = []

        for page_data in processed_images:
            # Check if we have direct text extraction (from pdfplumber - much faster)
            if 'direct_text' in page_data and page_data.get('direct_text'):
                combined_text = page_data['direct_text']
                results.append({
                    'page_number': page_data['page_number'],
                    'text': combined_text,
                    'ocr_data': {'tesseract': None, 'easyocr': []},
                    'layout_regions': [],
                    'extracted_fields': {},
                    'overall_confidence': 0.95,  # High confidence for direct extraction
                    'needs_review': False
                })
                continue
            
            image = page_data.get('image')
            if image is None:
                continue

            # Extract text with bounding boxes (optimized - skips EasyOCR if Tesseract works)
            ocr_data = self.extract_text_with_bounding_boxes(image)

            # Combine OCR text from both engines
            combined_text = self.combine_ocr_results(
                ocr_data.get('tesseract'),
                ocr_data.get('easyocr', [])
            )

            # Skip expensive layout detection and field extraction for speed
            # These are not needed for basic data extraction
            layout_regions = []  # Skip layout detection for speed
            fields = {}  # Skip field extraction here - will be done by extraction agent

            # Calculate confidence based on text length
            overall_confidence = min(0.9, len(combined_text) / 500) if combined_text else 0.0

            results.append({
                'page_number': page_data['page_number'],
                'text': combined_text,  # Add the combined OCR text
                'ocr_data': ocr_data,
                'layout_regions': layout_regions,
                'extracted_fields': fields,
                'overall_confidence': overall_confidence,
                'needs_review': overall_confidence < 0.8
            })

        return results

# Singleton instances
invoice_input_layer = InvoiceInputLayer()
ocr_layout_extraction = OCRLayoutExtraction()