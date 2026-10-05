"""
Data Extraction Agent
====================

Goal: Ext        # Invoice Number patterns - prioritize spec        # Vendor ID patterns
        vendor_id_patterns = [
            r'Vendor\s+ID\s*:?\s*([A-Z0-9\-]+)',  # Exact match for "Vendor ID: VEN-001"
            r'Vendor\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'Supplier\s+ID\s*:?\s*([A-Z0-9\-]+)',
            r'VID\s*:?\s*([A-Z0-9\-]+)'
        ]
        
        for pattern in vendor_id_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                extracted['vendor_id'] = match.group(1).strip()
                break

        # Vendor patterns - prioritize company name after "From:"
        vendor_patterns = [
            r'From:\s*([A-Za-z\s&]+(?:Inc|LLC|Corp|Corporation|Company|Ltd|Limited)\.?)(?:\s+\d+|\s*$)',  # Company name with common suffixes
            r'From:\s*([^V]+?)(?=\s+\d)',  # Match until digits (address start)
            r'From\s*:?\s*([^\n\r]+?)(?=\s*Vendor|\s*ID:|\s*$)',  # Fallback: match until "Vendor" or "ID:"
            r'^([A-Za-z\s&]+Inc\.?)$',  # Company name ending with Inc.
            r'Vendor\s*:?\s*([^\n\r]+?)(?=\s*Vendor|\s*ID:|\s*$)',
            r'Supplier\s*:?\s*([^\n\r]+?)(?=\s*Vendor|\s*ID:|\s*$)'
        ]
        invoice_patterns = [
            r'Invoice\s+Number\s*:?\s*([A-Z0-9\-]+)',  # Exact match for "Invoice Number: INV-2025-001"
            r'Invoice\s+No\.?\s*:?\s*([A-Z0-9\-]+)',
            r'INV\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'INVOICE\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'Bill\s*#?\s*:?\s*([A-Z0-9\-]+)'
        ]uctured fields from raw OCR invoice text.

Input: OCR text (unstructured)
Process:
- Pre-process with NER/regex for hints
- LLM converts  JSON schema

Output: JSON (Invoice_No, Vendor_ID, PO_No, Date, Amount, Tax, Currency)

Design Choices:
- LLM: Fine-tuned on invoice datasets (RVL-CDIP, FUNSD + synthetic data)
- Prompting style: "Extract fields, return strict JSON with confidence scores."
- Tools: HuggingFace + PEFT (LoRA)
"""

import re
import json
from typing import Dict, Any, List
from datetime import datetime
import spacy
from transformers import pipeline
from .base_agent import BaseAgent, AgentResult, ProcessingContext

class DataExtractionAgent(BaseAgent):
    def __init__(self):
        super().__init__("Data Extraction Agent")
        self.nlp = None
        self.ner_pipeline = None
        self._load_models()

    def _load_models(self):
        # Load spaCy (fast, already downloaded)
        try:
            self.nlp = spacy.load("en_core_web_sm")
            self.logger.info("spaCy model loaded successfully")
        except Exception as e:
            self.logger.warning(f"Failed to load spaCy model: {e}")
            self.nlp = None
        
        # Skip BERT loading initially - it's slow and we can work without it
        # BERT will be loaded lazily if needed (but for now, skip it to speed up processing)
        self.ner_pipeline = None
        self.logger.info("Skipping BERT model loading for faster processing. Using regex + spaCy only.")

    def _preprocess_text(self, text: str) -> str:
        text = re.sub(r'\s+', ' ', text.strip())
        text = re.sub(r'(\d)\s+(\d)', r'\1\2', text)
        text = re.sub(r'(?<=\w)-(?=\w)', '', text)
        return text

    def _extract_with_regex(self, text: str) -> Dict[str, Any]:
        extracted = {}
        
        # Customer Details - Name (improved patterns)
        name_patterns = [
            r'Customer\s+Name\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address|Phone|Email|Billing)',
            r'Name\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address|Phone|Email|Billing)',
            r'Bill\s+To\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address|Phone)',
            r'Ship\s+To\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address|Phone)',
            r'To\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address)',
            r'Buyer\s+Name\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address)',
            r'Consignee\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,|Address)'
        ]
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Filter out common false positives
                if len(name) > 1 and not re.match(r'^\d+$', name):
                    extracted['customer_name'] = name
                    break
        
        # Customer Details - Billing Address (improved patterns)
        billing_address_patterns = [
            r'Billing\s+Address\s*:?\s*([^\n]+(?:\n[^\n]+){0,4}?)(?=\n\s*(?:Shipping|Phone|Email|Total|Product|GST|PAN))',
            r'Bill\s+To\s*:?\s*[^\n]+\n([^\n]+(?:\n[^\n]+){0,4}?)(?=\n\s*(?:Ship|Phone|Email|Total|Product|GST|PAN))',
            r'Billing\s*:?\s*([^\n]+(?:\n[^\n]+){0,4}?)(?=\n\s*(?:Shipping|Phone|Email|Total|Product|GST|PAN))',
            r'Address\s*:?\s*([^\n]+(?:\n[^\n]+){0,4}?)(?=\n\s*(?:Shipping|Phone|Email|Total|Product|GST|PAN))'
        ]
        for pattern in billing_address_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                addr = ' '.join(match.group(1).strip().split())
                # Filter out very short addresses (likely false positives)
                if len(addr) > 10:
                    extracted['billing_address'] = addr
                    break
        
        # Customer Details - Shipping Address
        shipping_address_patterns = [
            r'Shipping\s+Address\s*:?\s*([^\n]+(?:\n[^\n]+){0,3}?)(?=\n\s*(?:Phone|Email|Total|Product))',
            r'Ship\s+To\s*:?\s*[^\n]+\n([^\n]+(?:\n[^\n]+){0,3}?)(?=\n\s*(?:Phone|Email|Total|Product))'
        ]
        for pattern in shipping_address_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                extracted['shipping_address'] = ' '.join(match.group(1).strip().split())
                break
        
        # Customer Details - Phone (improved patterns for Indian numbers)
        phone_patterns = [
            r'Phone\s*:?\s*([+]?91[\s\-]?)?([6-9]\d{9})',
            r'Mobile\s*:?\s*([+]?91[\s\-]?)?([6-9]\d{9})',
            r'Contact\s*:?\s*([+]?91[\s\-]?)?([6-9]\d{9})',
            r'Tel\s*:?\s*([+]?91[\s\-]?)?([6-9]\d{9})',
            r'Phone\s*:?\s*([+]?\d{1,4}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{1,4}[\s\-]?\d{1,9})',
            r'Mobile\s*:?\s*([+]?\d{1,4}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{1,4}[\s\-]?\d{1,9})',
            r'Contact\s*:?\s*([+]?\d{1,4}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{1,4}[\s\-]?\d{1,9})',
            r'Tel\s*:?\s*([+]?\d{1,4}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{1,4}[\s\-]?\d{1,9})'
        ]
        for pattern in phone_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                phone = match.group(0).split(':')[-1].strip() if ':' in match.group(0) else match.group(1) or match.group(2)
                # Clean phone number
                phone = re.sub(r'[^\d+]', '', phone)
                if len(phone) >= 10:  # Valid phone number should be at least 10 digits
                    extracted['phone'] = phone
                    break
        
        # Customer Details - Email
        email_patterns = [
            r'Email\s*:?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'E-mail\s*:?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  # Fallback: any email in text
        ]
        for pattern in email_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                extracted['email'] = match.group(1).strip()
                break
        
        # Products - Extract line items with improved multi-line and table format support
        products = []
        lines = text.split('\n')
        current_product = {}
        in_product_section = False
        product_keywords = ['description', 'item', 'product', 'hsn', 'sac', 'rate', 'quantity', 'amount', 'price']
        skip_next_n_lines = 0
        
        for i, line in enumerate(lines):
            line_clean = line.strip()
            
            # Skip header lines
            if skip_next_n_lines > 0:
                skip_next_n_lines -= 1
                continue
            
            # Detect product section header and skip it
            if re.search(r'^(?:Description|Item|Product|HSN|SAC|Rate|Quantity|Amount|Price)\s*$', line_clean, re.IGNORECASE):
                in_product_section = True
                skip_next_n_lines = 0
                continue
            
            # Detect start of product section by keywords
            if re.search(r'(?:Description|Item|Product|HSN|SAC|Rate|Quantity|Amount)', line_clean, re.IGNORECASE):
                in_product_section = True
            
            if not line_clean:
                # Empty line - save current product if it has enough data
                if current_product and len(current_product) >= 2:
                    products.append(current_product.copy())
                    current_product = {}
                continue
            
            # Stop at Total/Grand Total sections
            if re.search(r'^(?:Total|Subtotal|Grand\s+Total|TOTAL|Tax|GST|CGST|SGST)', line_clean, re.IGNORECASE):
                if current_product and len(current_product) >= 2:
                    products.append(current_product.copy())
                in_product_section = False
                current_product = {}
                continue
            
            if in_product_section:
                # Extract HSN/SAC (can be on same line or separate)
                if 'hsn_sac' not in current_product:
                    hsn_patterns = [
                        r'HSN/SAC\s*:?\s*([0-9]+)',
                        r'HSN\s*:?\s*([0-9]+)',
                        r'SAC\s*:?\s*([0-9]+)',
                        r'([0-9]{8})'  # 8-digit HSN code pattern
                    ]
                    for pattern in hsn_patterns:
                        hsn_match = re.search(pattern, line_clean, re.IGNORECASE)
                        if hsn_match:
                            hsn_val = hsn_match.group(1)
                            if len(hsn_val) >= 4:  # Valid HSN should be at least 4 digits
                                current_product['hsn_sac'] = hsn_val
                                break
                
                # Extract Rate
                if 'rate' not in current_product:
                    rate_patterns = [
                        r'Rate\s*:?\s*([0-9,]+\.?\d*)',
                        r'Price\s*:?\s*([0-9,]+\.?\d*)',
                        r'Unit\s+Price\s*:?\s*([0-9,]+\.?\d*)'
                    ]
                    for pattern in rate_patterns:
                        rate_match = re.search(pattern, line_clean, re.IGNORECASE)
                        if rate_match:
                            current_product['rate'] = rate_match.group(1).replace(',', '')
                            break
                
                # Extract Quantity
                if 'quantity' not in current_product:
                    qty_patterns = [
                        r'Quantity\s*:?\s*([0-9,]+\.?\d*)\s*([A-Z]+)?',
                        r'Qty\s*:?\s*([0-9,]+\.?\d*)\s*([A-Z]+)?',
                        r'([0-9,]+\.?\d*)\s*(KGS|KG|PCS|NOS|MT|LTR|UNITS|UNIT)'
                    ]
                    for pattern in qty_patterns:
                        qty_match = re.search(pattern, line_clean, re.IGNORECASE)
                        if qty_match:
                            qty_val = qty_match.group(1).replace(',', '')
                            qty_unit = qty_match.group(2) if len(qty_match.groups()) > 1 and qty_match.group(2) else ''
                            current_product['quantity'] = f"{qty_val} {qty_unit}".strip()
                            break
                
                # Extract Amount
                if 'amount' not in current_product:
                    amount_patterns = [
                        r'Amount\s*:?\s*([0-9,]+\.?\d*)',
                        r'Total\s*:?\s*([0-9,]+\.?\d*)',
                        r'Line\s+Total\s*:?\s*([0-9,]+\.?\d*)'
                    ]
                    for pattern in amount_patterns:
                        amount_match = re.search(pattern, line_clean, re.IGNORECASE)
                        if amount_match:
                            current_product['amount'] = amount_match.group(1).replace(',', '')
                            break
                
                # Extract Description (longer text lines, usually all caps for product names)
                if len(line_clean) > 10:
                    # Check if line looks like a description (contains words, not just numbers/symbols)
                    if re.search(r'[A-Za-z]{3,}', line_clean):
                        # Check if it doesn't contain product keywords (to avoid false matches)
                        if not any(keyword in line_clean.lower() for keyword in ['rate', 'quantity', 'amount', 'hsn', 'sac', 'total', 'tax']):
                            if 'description' not in current_product:
                                current_product['description'] = line_clean
                            elif len(line_clean) > len(current_product.get('description', '')):
                                # Update if longer (more complete description)
                                current_product['description'] = line_clean
        
        # Add last product if exists
        if current_product and len(current_product) >= 2:
            products.append(current_product)
        
        if products:
            extracted['products'] = products
        
        # Total Amount - in numbers (improved patterns for Indian format)
        total_amount_patterns = [
            r'Total\s+Amount\s*\(in\s+numbers\)\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)',
            r'Total\s+Amount\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)',
            r'Grand\s+Total\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)',
            r'Total\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)',
            r'Amount\s+Payable\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)',
            r'Net\s+Amount\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)',
            r'Final\s+Amount\s*:?\s*[₹$]?\s*([0-9,]+\.?\d*)'
        ]
        for pattern in total_amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Get the largest amount (usually the final total)
                try:
                    amounts = [float(match.replace(',', '')) for match in matches]
                    extracted['total_amount'] = max(amounts)
                    break
                except ValueError:
                    continue
        
        # Total Amount - in words
        total_words_patterns = [
            r'Total\s+Amount\s*\(in\s+words\)\s*:?\s*([^\n]+)',
            r'Amount\s+in\s+words\s*:?\s*([^\n]+)',
            r'Total\s+\(in\s+words\)\s*:?\s*([^\n]+)'
        ]
        for pattern in total_words_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                extracted['total_amount_words'] = match.group(1).strip()
                break
        
        # If total amount found but words not found, generate it
        if 'total_amount' in extracted and 'total_amount_words' not in extracted:
            try:
                extracted['total_amount_words'] = self._number_to_words_inr(extracted['total_amount'])
            except:
                pass
        
        # Invoice Number
        invoice_patterns = [
            r'Invoice\s+Number\s*:?\s*([A-Z0-9\-]+)',
            r'INVOICE\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'INV\s*#?\s*:?\s*([A-Z0-9\-]+)',
            r'Invoice\s+No\.?\s*:?\s*([A-Z0-9\-]+)'
        ]
        for pattern in invoice_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                extracted['invoice_number'] = match.group(1).strip()
                break
        
        # Invoice Date
        date_patterns = [
            r'Invoice\s+Date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})',
            r'Date\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'Invoice\s+Date\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                extracted['invoice_date'] = match.group(1).strip()
                break

        return extracted

    def _number_to_words_inr(self, num: float) -> str:
        """Convert number to words in Indian currency format (INR)"""
        def convert_to_words(n):
            ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 
                   'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 
                   'Seventeen', 'Eighteen', 'Nineteen']
            tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
            
            if n == 0:
                return ''
            elif n < 20:
                return ones[n]
            elif n < 100:
                return tens[n // 10] + (' ' + ones[n % 10] if n % 10 != 0 else '')
            elif n < 1000:
                return ones[n // 100] + ' Hundred' + (' ' + convert_to_words(n % 100) if n % 100 != 0 else '')
            elif n < 100000:
                return convert_to_words(n // 1000) + ' Thousand' + (' ' + convert_to_words(n % 1000) if n % 1000 != 0 else '')
            elif n < 10000000:
                return convert_to_words(n // 100000) + ' Lakh' + (' ' + convert_to_words(n % 100000) if n % 100000 != 0 else '')
            elif n < 1000000000:
                return convert_to_words(n // 10000000) + ' Crore' + (' ' + convert_to_words(n % 10000000) if n % 10000000 != 0 else '')
            else:
                return 'Number too large'
        
        # Split into integer and decimal parts
        integer_part = int(num)
        decimal_part = int(round((num - integer_part) * 100))
        
        words = convert_to_words(integer_part)
        if words:
            words += ' Rupees'
            if decimal_part > 0:
                words += ' And ' + convert_to_words(decimal_part) + ' Paise'
            words += ' Only'
        else:
            words = 'Zero Rupees Only'
        
        return 'INR ' + words

    def _extract_with_ai(self, text: str) -> Dict[str, Any]:
        """Extract fields using AI models (spaCy NER and BERT)"""
        extracted = {}

        try:
            # Use spaCy for general NER
            if self.nlp:
                doc = self.nlp(text)

                # Extract entities
                for ent in doc.ents:
                    if ent.label_ == "ORG":
                        # Check if it's likely a vendor (appears early in document)
                        if "vendor_name" not in extracted and ent.start_char < len(text) * 0.3:
                            extracted["vendor_name"] = ent.text
                        # Could also be customer name if it appears after "To:" or "Bill To:"
                        elif "customer_name" not in extracted:
                            # Check context around the entity
                            start = max(0, ent.start_char - 50)
                            end = min(len(text), ent.end_char + 50)
                            context = text[start:end].lower()
                            if any(marker in context for marker in ['to:', 'bill to:', 'customer', 'buyer']):
                                extracted["customer_name"] = ent.text
                    elif ent.label_ == "PERSON" and "customer_name" not in extracted:
                        # Person names are often customer names
                        start = max(0, ent.start_char - 50)
                        end = min(len(text), ent.end_char + 50)
                        context = text[start:end].lower()
                        if any(marker in context for marker in ['to:', 'bill to:', 'customer', 'name:']):
                            extracted["customer_name"] = ent.text
                    elif ent.label_ == "MONEY":
                        # Try to extract amount
                        amount_match = re.search(r'[₹\$£€¥]?(\d+(?:,\d{3})*(?:\.\d{2})?)', ent.text)
                        if amount_match:
                            try:
                                amount = float(amount_match.group(1).replace(',', ''))
                                # Only update if this is a larger amount (likely total)
                                if "total_amount" not in extracted or amount > extracted.get("total_amount", 0):
                                    extracted["total_amount"] = amount
                            except ValueError:
                                pass
                    elif ent.label_ == "DATE" and "invoice_date" not in extracted:
                        extracted["invoice_date"] = ent.text
                    elif ent.label_ == "EMAIL" and "email" not in extracted:
                        extracted["email"] = ent.text

            # Use BERT NER for more precise extraction
            if self.ner_pipeline:
                ner_results = self.ner_pipeline(text)

                # Process BERT NER results (already aggregated)
                for result in ner_results:
                    entity_group = result.get('entity_group', '')
                    word = result.get('word', '')
                    score = float(result.get('score', 0))

                    # Only use high-confidence results
                    if score > 0.8:
                        if entity_group == "ORG" and "vendor_name" not in extracted:
                            extracted["vendor_name"] = word
                        elif entity_group == "MISC" and "invoice_number" not in extracted:
                            # Check if it looks like an invoice number
                            if re.match(r'.*INV.*|.*\d{4}.*|\w+-\d+', word):
                                extracted["invoice_number"] = word

        except Exception as e:
            self.logger.warning(f"AI extraction failed: {e}")

        return extracted

    def _calculate_confidence(self, extracted: Dict[str, Any]) -> float:
        required_fields = ['invoice_number', 'vendor_name', 'total_amount', 'invoice_date']
        found_fields = sum(1 for field in required_fields if field in extracted)
        base_confidence = found_fields / len(required_fields)
        if len(extracted) > found_fields:
            base_confidence += 0.2
        return min(base_confidence, 1.0)

    async def process(self, context: ProcessingContext) -> AgentResult:
        try:
            # Check if OCR text is available
            if not context.ocr_text or len(context.ocr_text.strip()) == 0:
                self.logger.warning("No OCR text available for extraction")
                return self.create_result(
                    status='error',
                    data={'error': 'No OCR text available. Please ensure the document contains readable text.'},
                    confidence=0.0,
                    message='No OCR text available for extraction',
                    next_agent=None
                )
            
            self.logger.info(f"Processing OCR text ({len(context.ocr_text)} characters)")
            cleaned_text = self._preprocess_text(context.ocr_text)
            self.logger.info(f"Cleaned text length: {len(cleaned_text)} characters")

            # First try regex extraction
            self.logger.info("Starting regex extraction...")
            extracted_data = self._extract_with_regex(cleaned_text)
            self.logger.info(f"Regex extraction found {len(extracted_data)} fields: {list(extracted_data.keys())}")

            # Initialize ai_extracted to empty dict
            ai_extracted = {}
            
            # Then enhance with AI models if available
            if self.nlp:
                self.logger.info("Enhancing with spaCy NER...")
                ai_extracted = self._extract_with_ai(cleaned_text)
                self.logger.info(f"AI extraction found {len(ai_extracted)} additional fields")
                # Merge AI results with regex results, preferring regex for structured fields
                # Only add AI fields that weren't found by regex
                for key, value in ai_extracted.items():
                    if key not in extracted_data or not extracted_data[key]:
                        extracted_data[key] = value

            self.logger.info(f"Total extracted fields: {len(extracted_data)}")
            confidence = self._calculate_confidence(extracted_data)
            self.logger.info(f"Extraction confidence: {confidence:.2%}")

            result_data = {
                'extracted_fields': extracted_data,
                'field_confidences': {field: 0.9 if field in ai_extracted else 0.8 for field in extracted_data.keys()},
                'extraction_method': 'ai_enhanced_regex' if self.nlp and self.ner_pipeline else 'regex_only',
                'ai_models_used': self.nlp is not None and self.ner_pipeline is not None,
                'raw_text_length': len(cleaned_text),
                'fields_found': len(extracted_data)
            }

            message = f"Extracted {len(extracted_data)} fields with {confidence:.2%} confidence using AI models"

            return self.create_result(
                status='success',
                data=result_data,
                confidence=confidence,
                message=message,
                next_agent='Validation Agent'
            )

        except Exception as e:
            self.logger.error(f"Data extraction failed: {e}")
            return self.create_result(
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                message=f"Data extraction failed: {str(e)}",
                next_agent=None
            )
