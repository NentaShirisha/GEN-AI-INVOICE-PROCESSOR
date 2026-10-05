"""
Exception Handling Agent
========================

Goal: Handle errors/uncertainties by interacting with user.

Input: Error JSON (e.g., Vendor_ID mismatch)
Process:
- LLM reformulates error  user-friendly clarification question
- Accepts user input  converts back into structured JSON update

Output: Corrected JSON

Design Choices:
- LLM: Instruction-tuned for Q&A style
- Dialogue memory: LangChain conversational buffer
- Example: "Vendor ID V9821 not found. Did you mean V9827 (ABC Corp)?"
"""

from typing import Dict, Any, List
from datetime import datetime
from .base_agent import BaseAgent, AgentResult, ProcessingContext

class ExceptionHandlingAgent(BaseAgent):
    def __init__(self):
        super().__init__("Exception Handling Agent")
        self.conversation_history = []

    def _analyze_errors(self, validation_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Analyze validation errors and create user-friendly questions"""
        issues = []
        
        for field, results in validation_results.items():
            if not results.get('valid', True):
                suggestions = results.get('suggestions', [])
                
                if field == 'vendor':
                    if any('not found' in s for s in suggestions):
                        issues.append({
                            'type': 'vendor_not_found',
                            'field': 'vendor_name',
                            'question': f"Vendor '{results.get('original_value', 'Unknown')}' was not found in our system. Could you please provide the correct vendor name or ID?",
                            'suggestions': [s for s in suggestions if 'Available vendor' in s]
                        })
                    elif any('Did you mean' in s for s in suggestions):
                        suggestion = next((s for s in suggestions if 'Did you mean' in s), '')
                        issues.append({
                            'type': 'vendor_suggestion',
                            'field': 'vendor_name',
                            'question': f"Vendor '{results.get('original_value', 'Unknown')}' was not found. {suggestion} Is this correct?",
                            'suggestions': suggestions
                        })
                
                elif field == 'po':
                    if any('not found' in s for s in suggestions):
                        issues.append({
                            'type': 'po_not_found',
                            'field': 'po_number',
                            'question': f"Purchase Order '{results.get('original_value', 'Unknown')}' was not found in our system. Could you please verify the PO number?",
                            'suggestions': [s for s in suggestions if 'Did you mean' in s]
                        })
                    elif any('belongs to vendor' in s for s in suggestions):
                        vendor_mismatch = next((s for s in suggestions if 'belongs to vendor' in s), '')
                        issues.append({
                            'type': 'po_vendor_mismatch',
                            'field': 'po_number',
                            'question': f"PO '{results.get('original_value', 'Unknown')}' {vendor_mismatch}. Should we update the vendor information?",
                            'suggestions': suggestions
                        })
                
                elif field == 'date':
                    issues.append({
                        'type': 'date_format',
                        'field': 'invoice_date',
                        'question': f"The invoice date '{results.get('original_value', 'Unknown')}' appears to be invalid. Could you please provide the correct date in MM/DD/YYYY format?",
                        'suggestions': suggestions
                    })
                
                elif field == 'amount':
                    if any('differs from PO' in s for s in suggestions):
                        amount_issue = next((s for s in suggestions if 'differs from PO' in s), '')
                        issues.append({
                            'type': 'amount_variance',
                            'field': 'total_amount',
                            'question': f"The invoice amount differs from the PO amount. {amount_issue}. Is this variance expected?",
                            'suggestions': suggestions
                        })
        
        return issues

    def _generate_correction_options(self, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate correction options for the user"""
        options = {
            'auto_correct': [],
            'user_input_required': [],
            'suggestions': []
        }
        
        for issue in issues:
            if issue['type'] in ['vendor_suggestion', 'po_suggestion']:
                options['auto_correct'].append({
                    'field': issue['field'],
                    'question': issue['question'],
                    'type': 'confirmation'
                })
            else:
                options['user_input_required'].append({
                    'field': issue['field'],
                    'question': issue['question'],
                    'type': 'input_required'
                })
            
            options['suggestions'].extend(issue.get('suggestions', []))
        
        return options

    def _apply_corrections(self, context: ProcessingContext, user_responses: Dict[str, Any]) -> Dict[str, Any]:
        """Apply user corrections to the extracted data"""
        corrected_data = context.extracted_data.copy()
        
        for field, correction in user_responses.items():
            if field in corrected_data:
                corrected_data[field] = correction
        
        corrected_data['corrections_applied'] = list(user_responses.keys())
        
        return corrected_data

    async def process(self, context: ProcessingContext) -> AgentResult:
        try:
            # Get validation results - handle different formats
            validation_results = {}
            if hasattr(context, 'validation_results') and context.validation_results:
                if isinstance(context.validation_results, dict):
                    validation_results = context.validation_results
                elif isinstance(context.validation_results, bool):
                    # If it's a boolean, we need to get validation results from previous agent
                    validation_results = {}
            
            # Try to get validation results from previous agent results or extracted data
            if not validation_results:
                # Check if we have validation results in extracted_data
                if hasattr(context, 'extracted_data') and isinstance(context.extracted_data, dict):
                    if 'validation_results' in context.extracted_data:
                        validation_results = context.extracted_data['validation_results']
                    # Also check if we have validation output
                    elif 'validation_output' in context.extracted_data:
                        # Extract from validation output
                        validation_output = context.extracted_data.get('validation_output', {})
                        # Create a basic validation_results structure
                        validation_results = {
                            'vendor': {'valid': validation_output.get('Validation_Status') == 'Pass'},
                            'po': {'valid': validation_output.get('Validation_Status') == 'Pass'},
                            'date': {'valid': validation_output.get('Validation_Status') == 'Pass'},
                            'amount': {'valid': validation_output.get('Validation_Status') == 'Pass'}
                        }
            
            # If still no validation results, try to get from previous results
            if not validation_results and hasattr(context, 'previous_results'):
                for result in context.previous_results.values():
                    if isinstance(result, dict) and 'data' in result:
                        if 'validation_results' in result['data']:
                            validation_results = result['data']['validation_results']
                            break
            
            # Analyze validation errors
            issues = self._analyze_errors(validation_results) if validation_results else []
            
            # Get extracted fields for output
            extracted_fields = {}
            if hasattr(context, 'extracted_data') and context.extracted_data:
                if isinstance(context.extracted_data, dict):
                    if 'extracted_fields' in context.extracted_data:
                        extracted_fields = context.extracted_data['extracted_fields']
                    else:
                        extracted_fields = context.extracted_data
                else:
                    # If it's not a dict, try to convert or use empty dict
                    extracted_fields = {}
            
            # Extract key fields - use original values from invoice
            # Try multiple field name variations to get the actual extracted values
            original_invoice_no = (extracted_fields.get('invoice_number') or 
                                  extracted_fields.get('invoice_no') or 
                                  extracted_fields.get('Invoice_No') or
                                  extracted_fields.get('invoice_number') or
                                  'N/A')
            
            original_vendor_id = (extracted_fields.get('vendor_id') or 
                                 extracted_fields.get('vendor_ID') or 
                                 extracted_fields.get('Vendor_ID') or
                                 extracted_fields.get('vendor_name') or
                                 'N/A')
            
            original_po_no = (extracted_fields.get('po_number') or 
                             extracted_fields.get('PO_No') or 
                             extracted_fields.get('po_number') or
                             'N/A')
            
            # If we still have N/A, try to get from validation output if available
            if hasattr(context, 'extracted_data') and isinstance(context.extracted_data, dict):
                validation_output = context.extracted_data.get('validation_output', {})
                if original_invoice_no == 'N/A' and validation_output.get('Invoice_No'):
                    original_invoice_no = validation_output.get('Invoice_No')
                if original_vendor_id == 'N/A' and validation_output.get('Vendor_ID'):
                    original_vendor_id = validation_output.get('Vendor_ID')
                if original_po_no == 'N/A' and validation_output.get('PO_No'):
                    original_po_no = validation_output.get('PO_No')
            
            if not issues:
                # No issues found, proceed to next agent
                return self.create_result(
                    status='success',
                    data={
                        'exception_output': {
                            'Invoice_No': original_invoice_no,
                            'Vendor_ID': original_vendor_id,
                            'PO_No': original_po_no,
                            'Resolution': 'No exceptions found, all validations passed'
                        },
                        'message': 'No exceptions found, proceeding to ERP integration'
                    },
                    confidence=1.0,
                    message='No exceptions to handle',
                    next_agent='ERP Integration Agent'
                )
            
            # Generate correction options
            correction_options = self._generate_correction_options(issues)
            
            # Check if we have user responses to apply
            user_responses = {}
            if isinstance(extracted_fields, dict):
                user_responses = extracted_fields.get('user_corrections', {})
            
            # Build resolution message from issues - collect all issues
            resolution = "No issues found"
            all_resolutions = []
            
            if issues:
                for issue in issues:
                    issue_type = issue.get('type', '')
                    suggestions = issue.get('suggestions', [])
                    
                    if issue_type == 'po_not_found':
                        if suggestions:
                            # Extract PO numbers from suggestions
                            po_matches = [s for s in suggestions if 'PO' in s or 'Did you mean PO' in s]
                            if po_matches:
                                all_resolutions.append(f"PO number not found, possible matches: {', '.join(po_matches)}")
                            else:
                                all_resolutions.append(f"PO number '{original_po_no}' not found in system")
                        else:
                            all_resolutions.append(f"PO number '{original_po_no}' not found in system")
                    
                    elif issue_type == 'vendor_not_found':
                        if suggestions:
                            # Get all available vendor suggestions
                            vendor_matches = [s for s in suggestions if 'Available vendor' in s or 'vendor' in s.lower()]
                            if vendor_matches:
                                # Format: "Vendor not found, possible matches: Available vendor: VEN001 - TechCorp Solutions Inc., Available vendor: V001 - ABC Corp"
                                resolution_text = f"Vendor not found, possible matches: {', '.join(vendor_matches)}"
                                all_resolutions.append(resolution_text)
                            else:
                                all_resolutions.append(f"Vendor '{original_vendor_id}' not found in system")
                        else:
                            all_resolutions.append(f"Vendor '{original_vendor_id}' not found in system")
                    
                    elif issue_type == 'vendor_suggestion':
                        if suggestions:
                            vendor_matches = [s for s in suggestions if 'Did you mean' in s or 'Available vendor' in s]
                            if vendor_matches:
                                all_resolutions.append(f"Vendor suggestion: {', '.join(vendor_matches)}")
                            else:
                                all_resolutions.append(issue.get('question', 'Vendor validation issue'))
                        else:
                            all_resolutions.append(issue.get('question', 'Vendor validation issue'))
                    
                    elif issue_type == 'po_vendor_mismatch':
                        all_resolutions.append(issue.get('question', 'PO vendor mismatch detected'))
                    
                    elif issue_type == 'date_format':
                        all_resolutions.append(issue.get('question', 'Date format issue detected'))
                    
                    elif issue_type == 'amount_variance':
                        all_resolutions.append(issue.get('question', 'Amount variance detected'))
                    
                    else:
                        all_resolutions.append(issue.get('question', 'Validation issue detected'))
                
                # Combine all resolutions
                if all_resolutions:
                    resolution = '; '.join(all_resolutions)
                else:
                    resolution = "Validation issues detected"
            
            # If user provided corrections, apply them
            if user_responses:
                # Update fields based on user responses
                if 'po_number' in user_responses:
                    po_no = user_responses['po_number']
                    resolution = f"User confirmed {po_no}"
                elif 'vendor_id' in user_responses:
                    vendor_id = user_responses['vendor_id']
                    resolution = f"User confirmed vendor {vendor_id}"
                elif 'vendor_name' in user_responses:
                    vendor_id = user_responses.get('vendor_id', vendor_id)
                    resolution = f"User confirmed vendor information"
                
                return self.create_result(
                    status='success',
                    data={
                        'exception_output': {
                            'Invoice_No': original_invoice_no,
                            'Vendor_ID': vendor_id,  # Use corrected value
                            'PO_No': po_no,  # Use corrected value
                            'Resolution': resolution
                        },
                        'corrected_data': extracted_fields,
                        'corrections_applied': list(user_responses.keys()),
                        'message': f'Applied {len(user_responses)} corrections'
                    },
                    confidence=0.8,
                    message='Corrections applied successfully',
                    next_agent='Validation Agent'  # Re-validate after corrections
                )
            else:
                # Need user input - return output format with issues
                primary_issue = issues[0] if issues else {}
                
                return self.create_result(
                    status='needs_interaction',
                    data={
                        'exception_output': {
                            'Invoice_No': original_invoice_no,
                            'Vendor_ID': original_vendor_id,
                            'PO_No': original_po_no,
                            'Resolution': resolution
                        },
                        'issues': issues,
                        'correction_options': correction_options,
                        'requires_user_input': True,
                        'error_log': [issue.get('question', '') for issue in issues],
                        'candidate_corrections': [issue.get('suggestions', []) for issue in issues]
                    },
                    confidence=0.5,
                    message=f'Found {len(issues)} validation issues requiring user input',
                    next_agent=None,
                    requires_user_input=True,
                    user_question=issues[0].get('question', 'Please review and correct the validation issues') if issues else 'Please review validation issues'
                )

        except Exception as e:
            self.logger.error(f"Exception handling failed: {e}")
            return self.create_result(
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                message=f"Exception handling failed: {str(e)}",
                next_agent=None
            )
