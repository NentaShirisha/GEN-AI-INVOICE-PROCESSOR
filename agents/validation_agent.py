"""
Validation Agent
================

Goal: Verify extracted values against ERP rules + vendor/PO master data.

Input: JSON (from Extraction Agent) + ERP DB context
Process:
- Cross-check Vendor_ID & PO_No with ERP DB (via RAG/vector DB)
- Apply rules: date format, currency consistency, tax % range

Output: Validated JSON with status: valid/invalid and error reasons

Design Choices:
- LLM: Prompt-based reasoning model (few-shot, with rules in system prompt)
- RAG: ERP master data stored in FAISS/Weaviate
- Example prompt: "If PO_No not in DB, mark as Invalid and generate correction suggestions."
"""

import re
from typing import Dict, Any, List
from datetime import datetime
from .base_agent import BaseAgent, AgentResult, ProcessingContext

class ValidationAgent(BaseAgent):
    def __init__(self):
        super().__init__("Validation Agent")
        # Mock ERP database - in production, this would connect to actual ERP
        self.erp_vendors = {
            'VEN001': {'name': 'TechCorp Solutions Inc.', 'tax_id': '123456789'},
            'V001': {'name': 'ABC Corp', 'tax_id': '123456789'},
            'V002': {'name': 'XYZ Supplies', 'tax_id': '987654321'},
            'V003': {'name': 'Tech Solutions Inc', 'tax_id': '456789123'},
        }
        
        self.erp_pos = {
            'PO20250456': {'vendor_id': 'VEN001', 'amount': 3000.00, 'currency': 'USD'},
            'PO-001': {'vendor_id': 'V001', 'amount': 5000.00, 'currency': 'USD'},
            'PO-002': {'vendor_id': 'V002', 'amount': 7500.00, 'currency': 'USD'},
            'PO-003': {'vendor_id': 'V003', 'amount': 3200.00, 'currency': 'USD'},
        }

    def _validate_vendor(self, vendor_name: str, vendor_id: str = None) -> Dict[str, Any]:
        """Validate vendor information against ERP database"""
        result = {'valid': False, 'confidence': 0.0, 'suggestions': []}
        
        # Check if vendor_id exists in ERP
        if vendor_id and vendor_id != 'N/A' and vendor_id in self.erp_vendors:
            erp_vendor = self.erp_vendors[vendor_id]
            result['valid'] = True
            result['confidence'] = 0.9
            result['erp_data'] = erp_vendor
            return result
        
        # If no vendor_id, try to match by name
        if vendor_name and isinstance(vendor_name, str) and len(vendor_name.strip()) > 0:
            vendor_name_lower = vendor_name.lower().strip()
            for vid, vdata in self.erp_vendors.items():
                vdata_name = vdata.get('name', '').lower()
                if vendor_name_lower in vdata_name or vdata_name in vendor_name_lower:
                    result['valid'] = True
                    result['confidence'] = 0.7
                    result['suggested_vendor_id'] = vid
                    result['erp_data'] = vdata
                    result['suggestions'].append(f"Did you mean vendor {vid} ({vdata['name']})?")
                    break
        
        if not result['valid']:
            if not vendor_name and not vendor_id:
                result['suggestions'].append("Vendor information not provided")
            else:
                result['suggestions'].append("Vendor not found in ERP database")
            # Suggest similar vendors
            for vid, vdata in self.erp_vendors.items():
                result['suggestions'].append(f"Available vendor: {vid} - {vdata['name']}")
        
        return result

    def _validate_po(self, po_number: str, vendor_id: str = None) -> Dict[str, Any]:
        """Validate PO information against ERP database"""
        result = {'valid': False, 'confidence': 0.0, 'suggestions': []}
        
        # Check if po_number is None or empty
        if not po_number or po_number == 'N/A':
            result['suggestions'].append("PO number not provided")
            return result
        
        if po_number in self.erp_pos:
            po_data = self.erp_pos[po_number]
            result['valid'] = True
            result['confidence'] = 0.9
            result['erp_data'] = po_data
            
            # Check vendor consistency
            if vendor_id and vendor_id != 'N/A' and po_data['vendor_id'] != vendor_id:
                result['valid'] = False
                result['confidence'] = 0.3
                result['suggestions'].append(f"PO {po_number} belongs to vendor {po_data['vendor_id']}, not {vendor_id}")
            
            return result
        
        # PO not found
        result['suggestions'].append(f"PO {po_number} not found in ERP database")
        # Suggest similar POs
        if po_number and '-' in po_number:
            try:
                po_suffix = po_number.split('-')[-1]
                for po_id in self.erp_pos.keys():
                    if po_suffix in po_id:
                        result['suggestions'].append(f"Did you mean PO: {po_id}?")
            except (AttributeError, IndexError):
                pass
        
        return result

    def _validate_date(self, date_str: str) -> Dict[str, Any]:
        """Validate date format and reasonableness"""
        result = {'valid': False, 'confidence': 0.0, 'parsed_date': None, 'suggestions': []}
        
        if not date_str or date_str == 'N/A' or (isinstance(date_str, str) and len(date_str.strip()) == 0):
            result['suggestions'] = ["Date is required"]
            return result
        
        if not isinstance(date_str, str):
            result['suggestions'] = ["Invalid date format"]
            return result
        
        # Try different date formats
        date_formats = [
            '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d', '%Y-%m-%d',
            '%d/%m/%Y', '%d-%m-%Y', '%B %d, %Y', '%b %d, %Y'
        ]
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                result['valid'] = True
                result['confidence'] = 0.8
                result['parsed_date'] = parsed_date
                
                # Check if date is reasonable (not in future, not too old)
                now = datetime.now()
                if parsed_date > now:
                    result['valid'] = False
                    result['confidence'] = 0.4
                    result['suggestions'] = ["Invoice date cannot be in the future"]
                elif (now - parsed_date).days > 365*2:  # More than 2 years old
                    result['confidence'] = 0.5
                    result['suggestions'] = ["Invoice date seems unusually old"]
                
                break
            except ValueError:
                continue
        
        if not result['valid']:
            result['suggestions'] = ["Invalid date format. Use MM/DD/YYYY or similar"]
        
        return result

    def _validate_amount(self, amount: float, po_number: str = None) -> Dict[str, Any]:
        """Validate amount against PO and business rules"""
        result = {'valid': False, 'confidence': 0.0, 'suggestions': []}
        
        if amount is None:
            result['suggestions'].append("Amount not provided")
            return result
        
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            result['suggestions'].append("Invalid amount format")
            return result
        
        if amount <= 0:
            result['suggestions'].append("Amount must be greater than zero")
            return result
        
        result['valid'] = True
        result['confidence'] = 0.8
        
        # Check against PO amount if available
        if po_number and po_number != 'N/A' and po_number in self.erp_pos:
            po_amount = self.erp_pos[po_number].get('amount', 0)
            if po_amount > 0:
                variance = abs(amount - po_amount) / po_amount
                
                if variance > 0.1:  # More than 10% variance
                    result['confidence'] = 0.6
                    result['suggestions'].append(f"Amount differs from PO amount ({po_amount}) by {variance:.1%}")
        
        # Business rules
        if amount > 100000:  # Large amounts need approval
            result['suggestions'].append("Large amount - may require additional approval")
        
        return result

    async def process(self, context: ProcessingContext) -> AgentResult:
        try:
            # Get extracted fields from context
            extracted_fields = {}
            if hasattr(context, 'extracted_data') and context.extracted_data:
                # If extracted_data is a dict with 'extracted_fields', use that
                if isinstance(context.extracted_data, dict) and 'extracted_fields' in context.extracted_data:
                    extracted_fields = context.extracted_data['extracted_fields']
                else:
                    # Otherwise use extracted_data directly
                    extracted_fields = context.extracted_data
            
            # Extract key fields for validation
            invoice_no = extracted_fields.get('invoice_number') or extracted_fields.get('invoice_no', 'N/A')
            vendor_id = extracted_fields.get('vendor_id') or extracted_fields.get('vendor_ID', 'N/A')
            po_no = extracted_fields.get('po_number') or extracted_fields.get('po_number') or extracted_fields.get('PO_No', 'N/A')
            
            validation_results = {}
            overall_valid = True
            notes_list = []
            
            # Validate vendor
            vendor_name = extracted_fields.get('vendor_name') or extracted_fields.get('vendor_name', '')
            vendor_validation = self._validate_vendor(
                vendor_name if vendor_name else None,
                vendor_id if vendor_id and vendor_id != 'N/A' else None
            )
            validation_results['vendor'] = vendor_validation
            if not vendor_validation['valid']:
                overall_valid = False
                suggestions = vendor_validation.get('suggestions', [])
                if suggestions:
                    notes_list.append(f"Vendor validation failed: {', '.join(suggestions)}")
                else:
                    notes_list.append("Vendor validation failed: Vendor not found")
            else:
                if vendor_validation.get('suggested_vendor_id'):
                    vendor_id = vendor_validation['suggested_vendor_id']
                    notes_list.append(f"Vendor matched: {vendor_id}")
                else:
                    notes_list.append("Vendor validated successfully")
            
            # Validate PO
            po_validation = self._validate_po(
                po_no if po_no and po_no != 'N/A' else None,
                vendor_id if vendor_id and vendor_id != 'N/A' else None
            )
            validation_results['po'] = po_validation
            if not po_validation['valid']:
                overall_valid = False
                suggestions = po_validation.get('suggestions', [])
                if suggestions:
                    notes_list.append(f"PO validation failed: {', '.join(suggestions)}")
                else:
                    notes_list.append("PO validation failed: PO not found")
            else:
                po_data = po_validation.get('erp_data', {})
                po_balance = po_data.get('amount', 0) if po_data else 0
                invoice_amount = extracted_fields.get('total_amount', 0)
                if invoice_amount and po_balance:
                    try:
                        invoice_amount = float(invoice_amount)
                        if invoice_amount <= po_balance:
                            notes_list.append(f"PO balance check: Amount ({invoice_amount}) <= PO balance ({po_balance})")
                        else:
                            overall_valid = False
                            notes_list.append(f"PO balance exceeded: Amount ({invoice_amount}) > PO balance ({po_balance})")
                    except (ValueError, TypeError):
                        pass
                notes_list.append("PO validated successfully")
            
            # Validate date
            invoice_date = extracted_fields.get('invoice_date') or extracted_fields.get('date', '')
            date_validation = self._validate_date(invoice_date if invoice_date else None)
            validation_results['date'] = date_validation
            if not date_validation['valid']:
                overall_valid = False
                suggestions = date_validation.get('suggestions', [])
                if suggestions:
                    notes_list.append(f"Date validation failed: {', '.join(suggestions)}")
                else:
                    notes_list.append("Date validation failed: Invalid date format")
            else:
                notes_list.append("Date validated successfully")
            
            # Validate amount
            total_amount = extracted_fields.get('total_amount', 0)
            try:
                total_amount = float(total_amount) if total_amount else 0
            except (ValueError, TypeError):
                total_amount = 0
            
            amount_validation = self._validate_amount(
                total_amount if total_amount > 0 else None,
                po_no if po_no and po_no != 'N/A' else None
            )
            validation_results['amount'] = amount_validation
            if not amount_validation['valid']:
                overall_valid = False
                suggestions = amount_validation.get('suggestions', [])
                if suggestions:
                    notes_list.append(f"Amount validation failed: {', '.join(suggestions)}")
                else:
                    notes_list.append("Amount validation failed: Invalid amount")
            else:
                notes_list.append("Amount validated successfully")
            
            # Build final validation output in required format
            validation_status = "Pass" if overall_valid else "Fail"
            notes = "; ".join(notes_list) if notes_list else "All validations passed"
            
            # Create output in the required format
            validation_output = {
                "Invoice_No": invoice_no,
                "Vendor_ID": vendor_id,
                "PO_No": po_no,
                "Validation_Status": validation_status,
                "Notes": notes
            }
            
            # Calculate overall confidence
            total_confidence = sum([
                vendor_validation.get('confidence', 0),
                po_validation.get('confidence', 0),
                date_validation.get('confidence', 0),
                amount_validation.get('confidence', 0)
            ])
            overall_confidence = total_confidence / 4 if total_confidence > 0 else 0.5
            
            # Determine next agent
            next_agent = 'ERP Integration Agent' if overall_valid else 'Exception Handling Agent'
            
            result_data = {
                'validation_output': validation_output,
                'validation_results': validation_results,
                'overall_valid': overall_valid,
                'overall_confidence': overall_confidence,
                'requires_review': not overall_valid,
                'error_summary': [suggestion for field_results in validation_results.values() 
                                for suggestion in field_results.get('suggestions', [])],
                'extracted_fields': extracted_fields  # Include for reference
            }
            
            status = 'success' if overall_valid else 'needs_interaction'
            message = f"Validation {validation_status.lower()}ed with {overall_confidence:.2%} confidence"
            
            return self.create_result(
                status=status,
                data=result_data,
                confidence=overall_confidence,
                message=message,
                next_agent=next_agent
            )

        except Exception as e:
            self.logger.error(f"Validation failed: {e}")
            return self.create_result(
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                message=f"Validation failed: {str(e)}",
                next_agent=None
            )
