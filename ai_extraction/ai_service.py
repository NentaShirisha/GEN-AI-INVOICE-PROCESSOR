import re
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class AIExtractionService:
    """Enhanced AI service for Stage 2 field extraction and validation"""

    def __init__(self):
        self.device = 'cpu'  # Default to CPU to avoid issues
        logger.info(f"Using device: {self.device}")

        # Lazy load all models - don't load during initialization
        self.ner_pipeline = None
        self.nlp = None
        self.models_loaded = False

    def _load_models(self):
        """Lazy load models only when needed"""
        if self.models_loaded:
            return

        try:
            # Load spaCy
            import spacy
            self.nlp = spacy.load("en_core_web_sm")

            # Load NLTK
            import nltk
            nltk.download('punkt', quiet=True)
            nltk.download('stopwords', quiet=True)
            from nltk.corpus import stopwords
            self.stop_words = set(stopwords.words('english'))

            # Load transformers pipeline
            try:
                from transformers import pipeline
                import torch
                self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
                self.ner_pipeline = pipeline("ner", model="dslim/bert-base-NER", device=0 if self.device == 'cuda' else -1)
            except Exception as e:
                logger.warning(f"BERT NER pipeline loading failed: {e}")
                self.ner_pipeline = None

            self.models_loaded = True
            logger.info("AI models loaded successfully")

        except Exception as e:
            logger.error(f"Model loading error: {e}")
            # Continue without models - use regex-only extraction

    def extract_entities(self, text):
        """Extract entities using spaCy and transformers"""
        self._load_models()

        if not self.nlp:
            return {
                'persons': [],
                'organizations': [],
                'dates': [],
                'money': [],
            }

        doc = self.nlp(text)

        entities = {
            'persons': [ent.text for ent in doc.ents if ent.label_ == 'PERSON'],
            'organizations': [ent.text for ent in doc.ents if ent.label_ == 'ORG'],
            'dates': [ent.text for ent in doc.ents if ent.label_ == 'DATE'],
            'money': [ent.text for ent in doc.ents if ent.label_ == 'MONEY'],
        }

        # Use BERT NER for additional entities
        if self.ner_pipeline:
            try:
                bert_entities = self.ner_pipeline(text)
                for entity in bert_entities:
                    if entity['entity'].startswith('B-PER'):
                        entities['persons'].append(entity['word'])
                    elif entity['entity'].startswith('B-ORG'):
                        entities['organizations'].append(entity['word'])
            except Exception as e:
                logger.error(f"BERT NER extraction failed: {e}")

        return entities

    def extract_invoice_fields(self, text):
        """Extract specific invoice fields from text"""
        fields = {}

        # Invoice number patterns
        invoice_patterns = [
            r'Invoice\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Invoice\s*Number\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Inv\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Bill\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
        ]

        for pattern in invoice_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields['invoice_number'] = {
                    'value': match.group(1),
                    'confidence': 0.95,
                    'source': 'regex'
                }
                break

        # Date patterns
        date_patterns = [
            r'Invoice\s*Date\s*[:\-]?\s*([\d/\-\.]+)',
            r'Date\s*[:\-]?\s*([\d/\-\.]+)',
            r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                # Try to parse date
                try:
                    for fmt in ['%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m-%d-%Y', '%d-%m-%Y', '%Y-%m-%d']:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt)
                            fields['invoice_date'] = {
                                'value': parsed_date.strftime('%Y-%m-%d'),
                                'confidence': 0.90,
                                'source': 'regex'
                            }
                            break
                        except ValueError:
                            continue
                    if 'invoice_date' in fields:
                        break
                except:
                    continue

        # Amount patterns
        amount_patterns = [
            r'Total\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
            r'Amount\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
            r'Grand\s*Total\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
        ]

        for pattern in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    amount = float(match.group(1).replace(',', ''))
                    fields['total_amount'] = {
                        'value': amount,
                        'confidence': 0.85,
                        'source': 'regex'
                    }
                    break
                except ValueError:
                    continue

        # Tax Amount
        tax_patterns = [
            r'Tax\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
            r'GST\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
            r'VAT\s*[:\-]?\s*\$?([\d,]+\.?\d*)',
        ]

        for pattern in tax_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    tax = float(match.group(1).replace(',', ''))
                    fields['tax_amount'] = {
                        'value': tax,
                        'confidence': 0.80,
                        'source': 'regex'
                    }
                    break
                except ValueError:
                    continue

        # PO Number
        po_patterns = [
            r'PO\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
            r'Purchase\s*Order\s*#?\s*[:\-]?\s*([A-Z0-9\-]+)',
        ]

        for pattern in po_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                fields['po_number'] = {
                    'value': match.group(1),
                    'confidence': 0.90,
                    'source': 'regex'
                }
                break

        # Due Date
        due_date_patterns = [
            r'Due\s*Date\s*[:\-]?\s*([\d/\-\.]+)',
            r'Payment\s*Due\s*[:\-]?\s*([\d/\-\.]+)',
        ]

        for pattern in due_date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                try:
                    for fmt in ['%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m-%d-%Y', '%d-%m-%Y', '%Y-%m-%d']:
                        try:
                            parsed_date = datetime.strptime(date_str, fmt)
                            fields['due_date'] = {
                                'value': parsed_date.strftime('%Y-%m-%d'),
                                'confidence': 0.85,
                                'source': 'regex'
                            }
                            break
                        except ValueError:
                            continue
                    if 'due_date' in fields:
                        break
                except:
                    continue

        # Vendor extraction
        entities = self.extract_entities(text)
        if entities['organizations']:
            fields['vendor_name'] = {
                'value': entities['organizations'][0],
                'confidence': 0.80,
                'source': 'ner'
            }

        # Line Items extraction (basic implementation)
        line_items = self.extract_line_items(text)
        if line_items:
            fields['line_items'] = {
                'value': line_items,
                'confidence': 0.75,
                'source': 'regex'
            }

        return fields

    def extract_line_items(self, text):
        """Extract line items from invoice text"""
        lines = text.split('\n')
        line_items = []

        # Look for patterns that might indicate line items
        item_patterns = [
            r'(\d+)\s+(.+?)\s+(\d+(?:\.\d{2})?)\s+(\d+(?:\.\d{2})?)',
            r'(.+?)\s+(\d+)\s+(\d+(?:\.\d{2})?)\s+(\d+(?:\.\d{2})?)',
        ]

        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:
                continue

            for pattern in item_patterns:
                match = re.search(pattern, line)
                if match:
                    try:
                        if len(match.groups()) == 4:
                            qty = int(match.group(1))
                            desc = match.group(2).strip()
                            unit_price = float(match.group(3))
                            total = float(match.group(4))
                        else:
                            desc = match.group(1).strip()
                            qty = int(match.group(2))
                            unit_price = float(match.group(3))
                            total = float(match.group(4))

                        line_items.append({
                            'description': desc,
                            'quantity': qty,
                            'unit_price': unit_price,
                            'total': total
                        })
                        break
                    except (ValueError, IndexError):
                        continue

        return line_items[:10]  # Limit to first 10 items

    def validate_extracted_fields(self, fields):
        """Validate extracted fields for consistency"""
        validation_results = {}

        # Check if total amount matches sum of line items
        if 'line_items' in fields and 'total_amount' in fields:
            line_total = sum(item.get('total', 0) for item in fields['line_items']['value'])
            invoice_total = fields['total_amount']['value']

            if abs(line_total - invoice_total) > 0.01:  # Allow small rounding differences
                validation_results['total_mismatch'] = {
                    'line_total': line_total,
                    'invoice_total': invoice_total,
                    'difference': abs(line_total - invoice_total)
                }

        # Check date consistency
        if 'invoice_date' in fields and 'due_date' in fields:
            try:
                inv_date = datetime.strptime(fields['invoice_date']['value'], '%Y-%m-%d')
                due_date = datetime.strptime(fields['due_date']['value'], '%Y-%m-%d')

                if due_date < inv_date:
                    validation_results['date_inconsistency'] = "Due date is before invoice date"
            except:
                pass

        return validation_results

    def process_extracted_text(self, text):
        """Process the extracted text and return structured data"""
        entities = self.extract_entities(text)
        fields = self.extract_invoice_fields(text)
        validation = self.validate_extracted_fields(fields)

        result = {
            'raw_text': text,
            'entities': entities,
            'extracted_fields': fields,
            'validation_results': validation,
            'overall_confidence': self.calculate_overall_confidence(fields),
            'needs_review': len(validation) > 0 or any(field.get('confidence', 0) < 0.7 for field in fields.values() if isinstance(field, dict))
        }

        return result

    def process_invoice_data(self, stage2_results):
        """Process results from Stage 2 OCR/Layout extraction"""
        processed_results = []

        for page_result in stage2_results:
            # Get OCR text for processing
            ocr_data = page_result.get('ocr_data', {})
            tesseract_text = ""
            if 'tesseract' in ocr_data:
                tesseract_data = ocr_data['tesseract']
                tesseract_text = ' '.join([text for text in tesseract_data.get('text', []) if text.strip()])

            easyocr_text = ""
            if 'easyocr' in ocr_data:
                easyocr_data = ocr_data['easyocr']
                easyocr_text = ' '.join([text for _, text, _ in easyocr_data])

            combined_text = tesseract_text + ' ' + easyocr_text

            # Process with existing method
            result = self.process_extracted_text(combined_text)

            # Merge with Stage 2 fields
            stage2_fields = page_result.get('extracted_fields', {})
            merged_fields = self.merge_fields(stage2_fields, result['extracted_fields'])

            processed_results.append({
                'page_number': page_result['page_number'],
                'raw_text': combined_text,
                'entities': result['entities'],
                'extracted_fields': merged_fields,
                'validation_results': result['validation_results'],
                'overall_confidence': self.calculate_overall_confidence(merged_fields),
                'needs_review': result['needs_review'] or any(field.get('confidence', 0) < 0.7 for field in merged_fields.values() if isinstance(field, dict))
            })

        return processed_results

    def merge_fields(self, stage2_fields, ai_fields):
        """Merge fields from Stage 2 and AI extraction with confidence weighting"""
        merged = {}

        all_field_names = set(stage2_fields.keys()) | set(ai_fields.keys())

        for field_name in all_field_names:
            stage2_field = stage2_fields.get(field_name)
            ai_field = ai_fields.get(field_name)

            if stage2_field and ai_field:
                # Both sources have the field - use higher confidence
                if stage2_field['confidence'] >= ai_field['confidence']:
                    merged[field_name] = stage2_field
                else:
                    merged[field_name] = ai_field
            elif stage2_field:
                merged[field_name] = stage2_field
            elif ai_field:
                merged[field_name] = ai_field

        return merged

    def calculate_overall_confidence(self, fields):
        """Calculate overall extraction confidence"""
        if not fields:
            return 0.0

        confidences = []
        for field in fields.values():
            if isinstance(field, dict) and 'confidence' in field:
                confidences.append(field['confidence'])

        return sum(confidences) / len(confidences) if confidences else 0.5

# Singleton instance
ai_service = AIExtractionService()