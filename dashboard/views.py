from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.db.models import Count
from django.utils import timezone
from datetime import date, timedelta
from django.views.decorators.csrf import csrf_exempt
from .models import Invoice, Vendor
from .serializers import InvoiceSerializer, VendorSerializer
# Moved heavy imports to be local to avoid slow startup
# from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
# from ai_extraction.ai_service import ai_service
# from validation.validation_service import validation_service
# from erp_integration.erp_service import erp_service
from ocr.tasks import process_invoice_task
# Removed heavy agent imports from module level
# from agents import MCPOrchestratorAgent
from agents.base_agent import ProcessingContext
from django.contrib.sessions.models import Session
import os
import tempfile
import asyncio
from datetime import datetime
import uuid
import json
import time
import sys
from pathlib import Path
from django.conf import settings


def save_agent_output_to_file(agent_name, agent_result, session_id):
    """Save agent output to JSON file in agents_output folder"""
    try:
        # Create agents_output directory if it doesn't exist
        output_dir = Path(settings.BASE_DIR) / 'agents_output'
        output_dir.mkdir(exist_ok=True)
        
        # Create session-specific subdirectory
        session_dir = output_dir / session_id
        session_dir.mkdir(exist_ok=True)
        
        # Prepare output data
        output_data = {
            'agent_name': agent_name,
            'session_id': session_id,
            'timestamp': datetime.now().isoformat(),
            'status': agent_result.status,
            'confidence': agent_result.confidence,
            'message': agent_result.message,
            'data': agent_result.data,
            'timestamp_iso': agent_result.timestamp.isoformat() if hasattr(agent_result.timestamp, 'isoformat') else str(agent_result.timestamp)
        }
        
        # Save to JSON file
        filename = f"{agent_name.lower().replace(' ', '_')}_output.json"
        filepath = session_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {agent_name} output to {filepath}")
        return str(filepath)
    except Exception as e:
        print(f"Error saving agent output: {e}")
        return None

def _safe_delete_file(file_path, max_retries=5, delay=0.5):
    """Safely delete a file with retry mechanism for Windows file locking issues"""
    if not file_path or not os.path.exists(file_path):
        return
    
    # Force garbage collection to close any file handles before attempting deletion
    import gc
    gc.collect()
    
    for attempt in range(max_retries):
        try:
            # On Windows, add a small delay to allow processes to release file handles
            if sys.platform == 'win32' and attempt > 0:
                time.sleep(delay * (attempt + 1))  # Exponential backoff
            
            # Try to remove the file
            os.unlink(file_path)
            return
        except PermissionError as e:
            if attempt < max_retries - 1:
                # Force garbage collection again
                gc.collect()
                time.sleep(delay * (attempt + 1))
                continue
            else:
                # Log but don't fail - file will be cleaned up by OS temp cleanup
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not delete temp file {file_path} after {max_retries} attempts: {e}")
        except FileNotFoundError:
            # File already deleted, that's fine
            return
        except OSError as e:
            # Windows error 32: file is being used by another process
            # Check for error code 32 (file in use) or errno 32
            is_file_in_use = (
                (hasattr(e, 'winerror') and e.winerror == 32) or
                (hasattr(e, 'errno') and e.errno == 32) or
                (hasattr(e, 'args') and len(e.args) > 0 and '32' in str(e.args))
            )
            
            if attempt < max_retries - 1:
                gc.collect()
                time.sleep(delay * (attempt + 1))
                continue
            else:
                import logging
                logger = logging.getLogger(__name__)
                if is_file_in_use:
                    logger.warning(f"Could not delete temp file {file_path} after {max_retries} attempts (file in use by another process): {e}")
                else:
                    logger.warning(f"OSError deleting temp file {file_path}: {e}")
        except Exception as e:
            if attempt < max_retries - 1:
                gc.collect()
                time.sleep(delay * (attempt + 1))
                continue
            else:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Error deleting temp file {file_path}: {e}")


def update_session_data(session_id, key, value):
    """Safely update session data using Django's Session model"""
    try:
        from django.utils import timezone
        from datetime import timedelta

        # Get or create session
        session_obj, created = Session.objects.get_or_create(
            session_key=session_id,
            defaults={
                'session_data': Session.objects.encode({}),
                'expire_date': timezone.now() + timedelta(days=1)  # Set expiry to 1 day
            }
        )
        session_data = session_obj.get_decoded()

        # Update the data
        if isinstance(key, str) and '.' in key:
            # Handle nested keys like 'agent_results.extraction'
            keys = key.split('.')
            current = session_data
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value
        else:
            session_data[key] = value

        # Save back to session
        session_obj.session_data = Session.objects.encode(session_data)
        session_obj.save()
        return True
    except Exception as e:
        print(f"Error updating session {session_id}: {e}")
        return False

class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer

class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """Trigger invoice processing"""
        invoice = get_object_or_404(Invoice, pk=pk)
        task = process_invoice_task.delay(invoice.id)
        return Response({'task_id': task.id, 'status': 'processing'})

    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
        """Manually validate invoice"""
        from validation.validation_service import validation_service
        invoice = get_object_or_404(Invoice, pk=pk)
        result = validation_service.validate_invoice(invoice)
        return Response(result)

    @action(detail=True, methods=['post'])
    def post_to_erp(self, request, pk=None):
        """Post invoice to ERP"""
        from erp_integration.erp_service import erp_service
        invoice = get_object_or_404(Invoice, pk=pk)
        erp_system = request.data.get('erp_system', 'sap')
        result = erp_service.post_invoice(invoice, erp_system)
        return Response(result)

    @action(detail=False, methods=['post'])
    def process_staged(self, request):
        """Process invoice using staged approach (Stage 1 + Stage 2)"""
        try:
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # Stage 1: Invoice Input Layer - Preprocessing
                from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
                stage1_result = invoice_input_layer.process_input(temp_file_path)

                # Stage 2: OCR & Layout Extraction
                stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])

                # Stage 3: AI Extraction & Validation (enhanced)
                from ai_extraction.ai_service import ai_service
                stage3_results = ai_service.process_invoice_data(stage2_results)

                # Combine results from all pages (take the best results)
                combined_result = self.combine_stage_results(stage3_results)

                # Create invoice record
                invoice_data = self.create_invoice_from_staged_results(combined_result, uploaded_file.name)

                return Response({
                    'status': 'success',
                    'stage1_metadata': stage1_result['metadata'],
                    'stage2_results': len(stage2_results),
                    'stage3_results': combined_result,
                    'invoice': invoice_data
                })

            finally:
                # Clean up temporary file
                os.unlink(temp_file_path)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def combine_stage_results(self, stage3_results):
        """Combine results from multiple pages"""
        if not stage3_results:
            return {}

        # For now, take the first page results (can be enhanced for multi-page logic)
        best_result = max(stage3_results, key=lambda x: x.get('overall_confidence', 0))

        return best_result

    def create_invoice_from_staged_results(self, combined_result, filename):
        """Create invoice record from staged processing results"""
        fields = combined_result.get('extracted_fields', {})

        # Create or get vendor
        vendor_name = None
        if 'vendor_name' in fields:
            vendor_name = fields['vendor_name'].get('value')
            vendor, created = Vendor.objects.get_or_create(
                name=vendor_name,
                defaults={'contact_info': {}}
            )

        # Create invoice
        invoice = Invoice.objects.create(
            invoice_number=fields.get('invoice_number', {}).get('value', f'AUTO-{timezone.now().strftime("%Y%m%d%H%M%S")}'),
            vendor=vendor,
            invoice_date=fields.get('invoice_date', {}).get('value'),
            due_date=fields.get('due_date', {}).get('value'),
            total_amount=fields.get('total_amount', {}).get('value'),
            tax_amount=fields.get('tax_amount', {}).get('value'),
            po_number=fields.get('po_number', {}).get('value'),
            status='processed' if combined_result.get('overall_confidence', 0) > 0.8 else 'needs_review',
            extracted_data={
                'stage_processing': True,
                'confidence_scores': {k: v.get('confidence', 0) for k, v in fields.items() if isinstance(v, dict)},
                'validation_results': combined_result.get('validation_results', {}),
                'needs_review': combined_result.get('needs_review', False),
                'line_items': fields.get('line_items', {}).get('value', [])
            },
            raw_text=combined_result.get('raw_text', ''),
            confidence_score=combined_result.get('overall_confidence', 0.5)
        )

        return InvoiceSerializer(invoice).data

@api_view(['POST'])
def process_data_extraction(request):
    """Process invoice using only the Data Extraction Agent"""
    try:
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name

        try:
            # Step 1: OCR Processing
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Starting OCR processing...")
            
            from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
            stage1_result = invoice_input_layer.process_input(temp_file_path)
            
            if not stage1_result or 'processed_images' not in stage1_result:
                return Response({'error': 'OCR preprocessing failed: No images processed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            logger.info("OCR preprocessing completed, starting text extraction...")
            # Process only first page for speed (can process all pages if needed)
            images_to_process = stage1_result['processed_images'][:1]  # Process first page only for speed
            stage2_results = ocr_layout_extraction.process_document(images_to_process)

            # Combine OCR text
            ocr_text = ' '.join([result.get('text', '') for result in stage2_results if result.get('text')])
            
            if not ocr_text or len(ocr_text.strip()) == 0:
                return Response({
                    'error': 'OCR extraction failed: No text extracted from document',
                    'debug_info': {
                        'stage1_result_keys': list(stage1_result.keys()) if stage1_result else None,
                        'stage2_results_count': len(stage2_results) if stage2_results else 0,
                        'stage2_sample': stage2_results[0] if stage2_results else None
                    }
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            logger.info(f"OCR text extracted ({len(ocr_text)} characters). Starting data extraction...")

            # Step 2: Initialize Data Extraction Agent
            from agents.data_extraction_agent import DataExtractionAgent
            agent = DataExtractionAgent()
            logger.info("Data extraction agent initialized. Processing...")

            context = ProcessingContext(
                invoice_path=uploaded_file.name,
                extracted_data={},
                validation_errors=[],
                processing_history=[],
                user_responses={},
                session_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                invoice_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                original_file=uploaded_file.name,
                ocr_text=ocr_text,
                validation_results={},
                erp_data={},
                audit_log=[],
                current_stage='extraction'
            )

            # Execute agent
            try:
                result = asyncio.run(agent.process(context))
                logger.info("Data extraction completed successfully")
            except Exception as e:
                logger.error(f"Data extraction failed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return Response({
                    'error': f'Data extraction failed: {str(e)}',
                    'agent': 'Data Extraction Agent',
                    'status': 'error'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # Save to JSON file
            session_id = f"individual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            save_agent_output_to_file('Data Extraction Agent', result, session_id)
            
            return Response({
                'agent': 'Data Extraction Agent',
                'status': result.status,
                'confidence': result.confidence,
                'message': result.message,
                'data': result.data,
                'timestamp': result.timestamp.isoformat()
            })

        finally:
            # Clean up temporary file with retry mechanism for Windows
            _safe_delete_file(temp_file_path)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def process_validation(request):
    """Process invoice using only the Validation Agent"""
    try:
        uploaded_file = request.FILES.get('file')
        extracted_data = {}

        if uploaded_file:
            # If file is provided, extract data first
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # Step 1: OCR Processing
                from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
                stage1_result = invoice_input_layer.process_input(temp_file_path)
                stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])

                # Combine OCR text
                ocr_text = ' '.join([result.get('text', '') for result in stage2_results])

                # Step 2: Extract data using Data Extraction Agent
                from agents.data_extraction_agent import DataExtractionAgent
                extraction_agent = DataExtractionAgent()
                extraction_context = ProcessingContext(
                    invoice_path=uploaded_file.name,
                    extracted_data={},
                    validation_errors=[],
                    processing_history=[],
                    user_responses={},
                    session_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    invoice_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    original_file=uploaded_file.name,
                    ocr_text=ocr_text,
                    validation_results={},
                    erp_data={},
                    audit_log=[],
                    current_stage='extraction'
                )
                extraction_result = asyncio.run(extraction_agent.process(extraction_context))
                extracted_data = extraction_result.data.get('extracted_fields', {})

            finally:
                _safe_delete_file(temp_file_path)
        else:
            # Get extracted data from request (would come from previous agent)
            extracted_data = request.data.get('extracted_data', {})

        # Initialize Validation Agent
        from agents.validation_agent import ValidationAgent
        agent = ValidationAgent()

        context = ProcessingContext(
            invoice_path="",
            extracted_data=extracted_data,
            validation_errors=[],
            processing_history=[],
            user_responses={},
            session_id=f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            invoice_id=f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            original_file="",
            ocr_text="",
            validation_results={},
            erp_data={},
            audit_log=[],
            current_stage='validation'
        )

        # Execute agent
        result = asyncio.run(agent.process(context))
        
        # Save to JSON file
        session_id = f"individual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_agent_output_to_file('Validation Agent', result, session_id)

        return Response({
            'agent': 'Validation Agent',
            'status': result.status,
            'confidence': result.confidence,
            'message': result.message,
            'data': result.data,
            'timestamp': result.timestamp.isoformat()
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def process_exception_handling(request):
    """Process invoice using only the Exception Handling Agent"""
    try:
        uploaded_file = request.FILES.get('file')
        extracted_data = {}
        validation_results = {}

        if uploaded_file:
            # If file is provided, process through extraction and validation first
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # Step 1: OCR Processing
                from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
                stage1_result = invoice_input_layer.process_input(temp_file_path)
                stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])
                ocr_text = ' '.join([result.get('text', '') for result in stage2_results])

                # Step 2: Extract data
                from agents.data_extraction_agent import DataExtractionAgent
                extraction_agent = DataExtractionAgent()
                extraction_context = ProcessingContext(
                    invoice_path=uploaded_file.name, extracted_data={}, validation_errors=[],
                    processing_history=[], user_responses={}, session_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    invoice_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}", original_file=uploaded_file.name,
                    ocr_text=ocr_text, validation_results={}, erp_data={}, audit_log=[], current_stage='extraction'
                )
                extraction_result = asyncio.run(extraction_agent.process(extraction_context))
                extracted_data = extraction_result.data.get('extracted_fields', {})

                # Step 3: Validate data
                from agents.validation_agent import ValidationAgent
                validation_agent = ValidationAgent()
                validation_context = ProcessingContext(
                    invoice_path="", extracted_data=extracted_data, validation_errors=[],
                    processing_history=[], user_responses={}, session_id=f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    invoice_id=f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}", original_file="",
                    ocr_text="", validation_results={}, erp_data={}, audit_log=[], current_stage='validation'
                )
                validation_result = asyncio.run(validation_agent.process(validation_context))
                validation_results = validation_result.data.get('validation_results', {})
                # Also include validation output in extracted_data for exception handler
                extracted_data = {
                    'extracted_fields': extracted_data,
                    'validation_results': validation_results,
                    'validation_output': validation_result.data.get('validation_output', {})
                }

            finally:
                _safe_delete_file(temp_file_path)
        else:
            # Get data from request
            extracted_data = request.data.get('extracted_data', {})
            validation_results = request.data.get('validation_results', {})

        # Initialize Exception Handling Agent
        from agents.exception_handling_agent import ExceptionHandlingAgent
        agent = ExceptionHandlingAgent()

        context = ProcessingContext(
            invoice_path="",
            extracted_data=extracted_data if isinstance(extracted_data, dict) else {'extracted_fields': extracted_data},
            validation_errors=[],
            processing_history=[],
            user_responses={},
            session_id=f"exception_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            invoice_id=f"exception_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            original_file="",
            ocr_text="",
            validation_results=validation_results if isinstance(validation_results, dict) else {},
            erp_data={},
            audit_log=[],
            current_stage='exception_handling'
        )

        # Execute agent
        result = asyncio.run(agent.process(context))
        
        # Save to JSON file
        session_id = f"individual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_agent_output_to_file('Exception Handling Agent', result, session_id)

        return Response({
            'agent': 'Exception Handling Agent',
            'status': result.status,
            'confidence': result.confidence,
            'message': result.message,
            'data': result.data,
            'timestamp': result.timestamp.isoformat()
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def process_erp_integration(request):
    """Process invoice using only the ERP Integration Agent"""
    try:
        uploaded_file = request.FILES.get('file')
        extracted_data = {}

        if uploaded_file:
            # If file is provided, extract data first
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # Step 1: OCR Processing
                from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
                stage1_result = invoice_input_layer.process_input(temp_file_path)
                stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])
                ocr_text = ' '.join([result.get('text', '') for result in stage2_results])

                # Step 2: Extract data
                from agents.data_extraction_agent import DataExtractionAgent
                extraction_agent = DataExtractionAgent()
                extraction_context = ProcessingContext(
                    invoice_path=uploaded_file.name, extracted_data={}, validation_errors=[],
                    processing_history=[], user_responses={}, session_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    invoice_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}", original_file=uploaded_file.name,
                    ocr_text=ocr_text, validation_results={}, erp_data={}, audit_log=[], current_stage='extraction'
                )
                extraction_result = asyncio.run(extraction_agent.process(extraction_context))
                extracted_data = extraction_result.data.get('extracted_fields', {})

            finally:
                _safe_delete_file(temp_file_path)
        else:
            # Get data from request
            extracted_data = request.data.get('extracted_data', {})

        # Initialize ERP Integration Agent
        from agents.erp_integration_agent import ERPIntegrationAgent
        agent = ERPIntegrationAgent()

        context = ProcessingContext(
            invoice_path="",
            extracted_data=extracted_data,
            validation_errors=[],
            processing_history=[],
            user_responses={},
            session_id=f"erp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            invoice_id=f"erp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            original_file="",
            ocr_text="",
            validation_results={},
            erp_data={},
            audit_log=[],
            current_stage='erp_integration'
        )

        # Execute agent
        result = asyncio.run(agent.process(context))
        
        # Save to JSON file
        session_id = f"individual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_agent_output_to_file('ERP Integration Agent', result, session_id)

        return Response({
            'agent': 'ERP Integration Agent',
            'status': result.status,
            'confidence': result.confidence,
            'message': result.message,
            'data': result.data,
            'timestamp': result.timestamp.isoformat()
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def process_audit_logging(request):
    """Process invoice using only the Audit & Logging Agent"""
    try:
        uploaded_file = request.FILES.get('file')
        extracted_data = {}
        validation_results = {}

        if uploaded_file:
            # If file is provided, extract and validate data first
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file_path = temp_file.name

            try:
                # Step 1: OCR Processing
                from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
                stage1_result = invoice_input_layer.process_input(temp_file_path)
                stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])
                ocr_text = ' '.join([result.get('text', '') for result in stage2_results])

                # Step 2: Extract data
                from agents.data_extraction_agent import DataExtractionAgent
                extraction_agent = DataExtractionAgent()
                extraction_context = ProcessingContext(
                    invoice_path=uploaded_file.name, extracted_data={}, validation_errors=[],
                    processing_history=[], user_responses={}, session_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    invoice_id=f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}", original_file=uploaded_file.name,
                    ocr_text=ocr_text, validation_results={}, erp_data={}, audit_log=[], current_stage='extraction'
                )
                extraction_result = asyncio.run(extraction_agent.process(extraction_context))
                extracted_data = extraction_result.data.get('extracted_fields', {})

                # Step 3: Validate data
                from agents.validation_agent import ValidationAgent
                validation_agent = ValidationAgent()
                validation_context = ProcessingContext(
                    invoice_path=uploaded_file.name, extracted_data=extracted_data, validation_errors=[],
                    processing_history=[], user_responses={}, session_id=f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    invoice_id=f"validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}", original_file=uploaded_file.name,
                    ocr_text=ocr_text, validation_results={}, erp_data={}, audit_log=[], current_stage='validation'
                )
                validation_result = asyncio.run(validation_agent.process(validation_context))
                validation_results = validation_result.data.get('validation_results', {})
                
                # Build processing history from the agents we ran
                processing_history = [
                    {
                        'agent_name': 'Data Extraction Agent',
                        'status': extraction_result.status,
                        'confidence': extraction_result.confidence,
                        'message': extraction_result.message,
                        'timestamp': extraction_result.timestamp.isoformat()
                    },
                    {
                        'agent_name': 'Validation Agent',
                        'status': validation_result.status,
                        'confidence': validation_result.confidence,
                        'message': validation_result.message,
                        'timestamp': validation_result.timestamp.isoformat()
                    }
                ]
                
                # Structure extracted_data properly
                extracted_data = {
                    'extracted_fields': extracted_data,
                    'validation_results': validation_results
                }

            finally:
                _safe_delete_file(temp_file_path)
        else:
            # Get data from request
            extracted_data = request.data.get('extracted_data', {})
            validation_results = request.data.get('validation_results', {})
            processing_history = request.data.get('processing_history', [])

        # Initialize Audit & Logging Agent
        from agents.audit_logging_agent import AuditLoggingAgent
        agent = AuditLoggingAgent()

        context = ProcessingContext(
            invoice_path="",
            extracted_data=extracted_data if isinstance(extracted_data, dict) else {'extracted_fields': extracted_data},
            validation_errors=[],
            processing_history=processing_history if processing_history else [],
            user_responses={},
            session_id=f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            invoice_id=f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            original_file="",
            ocr_text="",
            validation_results=validation_results if isinstance(validation_results, dict) else {},
            erp_data={},
            audit_log=[],
            current_stage='audit_logging'
        )

        # Execute agent
        result = asyncio.run(agent.process(context))
        
        # Save to JSON file
        session_id = f"individual_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_agent_output_to_file('Audit Logging Agent', result, session_id)

        return Response({
            'agent': 'Audit & Logging Agent',
            'status': result.status,
            'confidence': result.confidence,
            'message': result.message,
            'data': result.data,
            'timestamp': result.timestamp.isoformat()
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    """API endpoint for uploading and processing invoices with staged approach"""
    try:
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name

        try:
            # Stage 1: Invoice Input Layer
            stage1_result = invoice_input_layer.process_input(temp_file_path)

            # Stage 2: OCR & Layout Extraction
            stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])

            # Stage 3: AI Extraction & Validation
            from ai_extraction.ai_service import ai_service
            stage3_results = ai_service.process_invoice_data(stage2_results)

            # Combine and create invoice
            viewset = InvoiceViewSet()
            combined_result = viewset.combine_stage_results(stage3_results)
            invoice_data = viewset.create_invoice_from_staged_results(combined_result, uploaded_file.name)

            return Response({
                'message': 'Invoice processed successfully',
                'invoice_id': invoice_data['id'],
                'status': invoice_data['status'],
                'confidence': combined_result.get('overall_confidence', 0),
                'needs_review': combined_result.get('needs_review', False)
            })

        finally:
            _safe_delete_file(temp_file_path)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
@csrf_exempt
def process_invoice_with_agents(request):
    """Process invoice using the 6-agent pipeline with real-time session-based updates"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        # Generate unique session ID
        session_id = str(uuid.uuid4())

        # Initialize session data using our helper function
        update_session_data(session_id, 'status', 'initialized')
        update_session_data(session_id, 'current_agent', None)
        update_session_data(session_id, 'progress', 0)
        update_session_data(session_id, 'agent_results', {})
        update_session_data(session_id, 'start_time', timezone.now().isoformat())
        update_session_data(session_id, 'file_name', uploaded_file.name)
        update_session_data(session_id, 'file_size', uploaded_file.size)

        # Start background processing
        from threading import Thread

        def process_async():
            temp_file_path = None
            try:
                # Update session: Starting OCR
                update_session_data(session_id, 'status', 'processing')
                update_session_data(session_id, 'current_agent', 'ocr')
                update_session_data(session_id, 'progress', 10)

                # Save uploaded file temporarily
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as temp_file:
                    for chunk in uploaded_file.chunks():
                        temp_file.write(chunk)
                    temp_file_path = temp_file.name

                try:
                    # Step 1: OCR Processing
                    update_session_data(session_id, 'current_agent', 'ocr')
                    update_session_data(session_id, 'progress', 20)

                    from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
                    stage1_result = invoice_input_layer.process_input(temp_file_path)
                    stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])
                    ocr_text = ' '.join([result.get('text', '') for result in stage2_results])

                    # Step 2: Data Extraction Agent
                    update_session_data(session_id, 'current_agent', 'extraction')
                    update_session_data(session_id, 'progress', 30)

                    from agents.data_extraction_agent import DataExtractionAgent
                    extraction_agent = DataExtractionAgent()
                    context = ProcessingContext(
                        invoice_path=uploaded_file.name,
                        extracted_data={},
                        validation_errors=[],
                        processing_history=[],
                        user_responses={},
                        session_id=session_id,
                        invoice_id=session_id,
                        original_file=uploaded_file.name,
                        ocr_text=ocr_text,
                        validation_results={},
                        erp_data={},
                        audit_log=[],
                        current_stage='extraction'
                    )

                    extraction_result = asyncio.run(extraction_agent.process(context))
                    update_session_data(session_id, 'agent_results.extraction', {
                        'status': extraction_result.status,
                        'confidence': extraction_result.confidence,
                        'message': extraction_result.message,
                        'data': extraction_result.data,
                        'timestamp': extraction_result.timestamp.isoformat(),
                        'ai_models': ['spaCy NER (en_core_web_sm)', 'BERT Large Cased (dbmdz/bert-large-cased-finetuned-conll03-english)']
                    })
                    # Save to JSON file
                    save_agent_output_to_file('Data Extraction Agent', extraction_result, session_id)

                    # Step 3: Validation Agent
                    update_session_data(session_id, 'current_agent', 'validation')
                    update_session_data(session_id, 'progress', 45)

                    from agents.validation_agent import ValidationAgent
                    validation_agent = ValidationAgent()
                    context.extracted_data = extraction_result.data.get('extracted_fields', {})
                    context.current_stage = 'validation'

                    validation_result = asyncio.run(validation_agent.process(context))
                    update_session_data(session_id, 'agent_results.validation', {
                        'status': validation_result.status,
                        'confidence': validation_result.confidence,
                        'message': validation_result.message,
                        'data': validation_result.data,
                        'timestamp': validation_result.timestamp.isoformat()
                    })
                    # Save to JSON file
                    save_agent_output_to_file('Validation Agent', validation_result, session_id)
                    request.session.save()

                    # Step 4: Exception Handling Agent
                    update_session_data(session_id, 'current_agent', 'exception')
                    update_session_data(session_id, 'progress', 60)

                    from agents.exception_handling_agent import ExceptionHandlingAgent
                    exception_agent = ExceptionHandlingAgent()
                    context.validation_results = validation_result.data
                    context.current_stage = 'exception_handling'

                    exception_result = asyncio.run(exception_agent.process(context))
                    update_session_data(session_id, 'agent_results.exception', {
                        'status': exception_result.status,
                        'confidence': exception_result.confidence,
                        'message': exception_result.message,
                        'data': exception_result.data,
                        'timestamp': exception_result.timestamp.isoformat()
                    })
                    # Save to JSON file
                    save_agent_output_to_file('Exception Handling Agent', exception_result, session_id)
                    request.session.save()

                    # Step 5: ERP Integration Agent
                    update_session_data(session_id, 'current_agent', 'erp')
                    update_session_data(session_id, 'progress', 75)

                    from agents.erp_integration_agent import ERPIntegrationAgent
                    erp_agent = ERPIntegrationAgent()
                    context.erp_data = {}
                    context.current_stage = 'erp_integration'

                    erp_result = asyncio.run(erp_agent.process(context))
                    update_session_data(session_id, 'agent_results.erp', {
                        'status': erp_result.status,
                        'confidence': erp_result.confidence,
                        'message': erp_result.message,
                        'data': erp_result.data,
                        'timestamp': erp_result.timestamp.isoformat()
                    })
                    # Save to JSON file
                    save_agent_output_to_file('ERP Integration Agent', erp_result, session_id)

                    # Step 6: Audit Logging Agent
                    update_session_data(session_id, 'current_agent', 'audit')
                    update_session_data(session_id, 'progress', 90)

                    from agents.audit_logging_agent import AuditLoggingAgent
                    audit_agent = AuditLoggingAgent()
                    context.audit_log = []
                    context.current_stage = 'audit_logging'

                    audit_result = asyncio.run(audit_agent.process(context))
                    update_session_data(session_id, 'agent_results.audit', {
                        'status': audit_result.status,
                        'confidence': audit_result.confidence,
                        'message': audit_result.message,
                        'data': audit_result.data,
                        'timestamp': audit_result.timestamp.isoformat()
                    })
                    # Save to JSON file
                    save_agent_output_to_file('Audit Logging Agent', audit_result, session_id)

                    # Step 7: Orchestrator (Final Summary)
                    update_session_data(session_id, 'current_agent', 'orchestrator')
                    update_session_data(session_id, 'progress', 100)
                    update_session_data(session_id, 'status', 'completed')

                    # Create final invoice record
                    vendor = None
                    extracted_fields = context.extracted_data
                    if 'vendor_name' in extracted_fields and extracted_fields['vendor_name']:
                        vendor_name = extracted_fields['vendor_name']
                        vendor, created = Vendor.objects.get_or_create(
                            name=vendor_name,
                            defaults={
                                'address': '',
                                'contact_email': '',
                                'contact_phone': '',
                                'tax_id': f'AUTO-{vendor_name[:10]}-{timezone.now().strftime("%Y%m%d")}'
                            }
                        )
                    else:
                        vendor, created = Vendor.objects.get_or_create(
                            name='Unknown Vendor',
                            defaults={
                                'address': '',
                                'contact_email': '',
                                'contact_phone': '',
                                'tax_id': f'AUTO-UNKNOWN-{timezone.now().strftime("%Y%m%d")}'
                            }
                        )

                    # Get agent results from session using Session model
                    agent_results = {}
                    try:
                        session_obj = Session.objects.get(session_key=session_id)
                        session_data = session_obj.get_decoded()
                        agent_results = session_data.get('agent_results', {})
                    except Session.DoesNotExist:
                        pass

                    invoice = Invoice.objects.create(
                        invoice_number=extracted_fields.get('invoice_number', f'AI-{session_id[:8]}'),
                        vendor=vendor,
                        invoice_date=extracted_fields.get('invoice_date') or date.today(),
                        due_date=extracted_fields.get('due_date') or (date.today() + timedelta(days=30)),
                        total_amount=extracted_fields.get('total_amount', 0),
                        tax_amount=extracted_fields.get('tax_amount', 0),
                        currency=extracted_fields.get('currency', 'USD'),
                        status='processed',
                        extracted_data={
                            'agent_processing': True,
                            'session_id': session_id,
                            'pipeline_status': 'completed',
                            'agent_results': agent_results,
                            'raw_text': ocr_text,
                            'confidence_score': 0.8,
                            'po_number': extracted_fields.get('po_number')
                        }
                    )

                    # Update session with invoice_id
                    update_session_data(session_id, 'invoice_id', invoice.id)

                except Exception as e:
                    request.session[session_id]['status'] = 'error'
                    request.session[session_id]['error'] = str(e)
                    request.session.save()
                finally:
                    if temp_file_path:
                        _safe_delete_file(temp_file_path)

            except Exception as e:
                update_session_data(session_id, 'status', 'error')
                update_session_data(session_id, 'error', str(e))
                if temp_file_path:
                    _safe_delete_file(temp_file_path)

        # Start processing in background thread
        processing_thread = Thread(target=process_async)
        processing_thread.daemon = True
        processing_thread.start()

        return JsonResponse({
            'status': 'processing_started',
            'session_id': session_id,
            'message': 'AI processing pipeline started. Check status for real-time updates.'
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def dashboard_view(request):
    """Dashboard view"""
    total_invoices = Invoice.objects.count()
    today = timezone.now().date()
    processed_today = Invoice.objects.filter(created_at__date=today).count()
    error_invoices = Invoice.objects.filter(status='error').count()
    exception_rate = (error_invoices / total_invoices * 100) if total_invoices > 0 else 0

    recent_invoices = Invoice.objects.order_by('-created_at')[:10]

    context = {
        'total_invoices': total_invoices,
        'processed_today': processed_today,
        'exception_rate': round(exception_rate, 2),
        'recent_invoices': recent_invoices,
    }

    return render(request, 'dashboard/dashboard.html', context)

@api_view(['GET'])
def check_processing_status(request, session_id):
    """Check the real-time processing status for a given session"""
    try:
        # Get session data from database
        try:
            session_obj = Session.objects.get(session_key=session_id)
            session_data = session_obj.get_decoded()
        except Session.DoesNotExist:
            return Response({'error': 'Session not found'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'session_id': session_id,
            'status': session_data.get('status', 'unknown'),
            'current_agent': session_data.get('current_agent'),
            'progress': session_data.get('progress', 0),
            'agent_results': session_data.get('agent_results', {}),
            'start_time': session_data.get('start_time'),
            'file_name': session_data.get('file_name'),
            'file_size': session_data.get('file_size'),
            'invoice_id': session_data.get('invoice_id'),
            'error': session_data.get('error')
        })

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@csrf_exempt
def analyze_agent_outputs(request):
    """Analyze all agent outputs from agents_output folder and answer user questions"""
    try:
        data = json.loads(request.body) if request.body else {}
        question = data.get('question', '')
        get_stats = data.get('get_stats', False)
        
        # Get API key from environment
        import os
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            # If dotenv is not available, try to load from environment directly
            pass
        
        # Read all agent output files from agents_output folder
        output_dir = Path(settings.BASE_DIR) / 'agents_output'
        agent_outputs = {}
        
        # Get statistics
        total_sessions = 0
        total_files = 0
        agents_used = set()
        
        if output_dir.exists():
            session_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
            total_sessions = len(session_dirs)
            
            # Get the most recent session directory
            if session_dirs:
                session_dirs_sorted = sorted(session_dirs, key=lambda x: x.stat().st_mtime, reverse=True)
                latest_session = session_dirs_sorted[0]
                
                agent_files = {
                    'data_extraction_agent_output.json': 'Data Extraction Agent',
                    'validation_agent_output.json': 'Validation Agent',
                    'exception_handling_agent_output.json': 'Exception Handling Agent',
                    'erp_integration_agent_output.json': 'ERP Integration Agent',
                    'audit_logging_agent_output.json': 'Audit Logging Agent'
                }
                
                for filename, agent_name in agent_files.items():
                    filepath = latest_session / filename
                    if filepath.exists():
                        total_files += 1
                        agents_used.add(agent_name)
                        try:
                            with open(filepath, 'r', encoding='utf-8') as f:
                                agent_outputs[agent_name] = json.load(f)
                        except Exception as e:
                            print(f"Error reading {filename}: {e}")
        
        # If only requesting statistics
        if get_stats:
            return JsonResponse({
                'statistics': {
                    'total_sessions': total_sessions,
                    'total_files': total_files,
                    'agents_used': len(agents_used)
                }
            })
        
        if not question:
            return JsonResponse({'error': 'Question is required'}, status=400)
        
        if not agent_outputs:
            return JsonResponse({
                'error': 'No agent outputs found. Please process an invoice first.',
                'answer': 'No agent outputs are available yet. Please process an invoice using the pipeline or individual agents first.'
            }, status=404)
        
        # Prefer OpenAI API key if present, otherwise fall back to Google API key
        google_api_key = os.getenv('GOOGLE_API_KEY')
        openai_api_key = os.getenv('OPENAI_API_KEY') or os.getenv('API_KEY')
        
        if not google_api_key and not openai_api_key:
            return JsonResponse({
                'error': 'API key not found in .env file. Please add OPENAI_API_KEY (preferred) or GOOGLE_API_KEY to .env'
            }, status=500)
        
        # If OpenAI key is available, use OpenAI and ignore Google (avoids Gemini quota/model issues)
        if openai_api_key:
            use_google = False
            api_key = openai_api_key
        else:
            use_google = True
            api_key = google_api_key
        
        # Prepare context from all agent outputs
        context_text = "Agent Processing Results:\n\n"
        for agent_name, output_data in agent_outputs.items():
            context_text += f"=== {agent_name} ===\n"
            context_text += f"Status: {output_data.get('status', 'unknown')}\n"
            context_text += f"Confidence: {output_data.get('confidence', 0)}\n"
            context_text += f"Message: {output_data.get('message', '')}\n"
            context_text += f"Data: {json.dumps(output_data.get('data', {}), indent=2)}\n\n"
        
        # Use AI API to analyze and answer the question
        try:
            if use_google:
                # Use Google Gemini API
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                
                prompt = f"""You are an AI assistant analyzing invoice processing results from multiple AI agents.

Here are the outputs from all 5 agents:

{context_text}

User Question: {question}

Please analyze the agent outputs and provide a comprehensive answer to the user's question. 
Focus on the data extracted, validation results, exceptions found, ERP integration status, and audit logs.
Be specific and reference the actual data from the agent outputs."""

                # Try models in order, starting with free tier friendly ones
                # gemini-1.5-flash is typically more available on free tier
                model_names = ['gemini-1.5-flash', 'gemini-1.5-pro']
                model = None
                response = None
                last_error = None
                quota_exceeded = False
                
                for model_name in model_names:
                    try:
                        model = genai.GenerativeModel(model_name)
                        response = model.generate_content(prompt)
                        answer = response.text
                        break
                    except Exception as e:
                        error_str = str(e)
                        last_error = error_str
                        
                        # Check if it's a quota error
                        if '429' in error_str or 'quota' in error_str.lower() or 'rate limit' in error_str.lower() or 'exceeded' in error_str.lower():
                            quota_exceeded = True
                            # Extract retry delay if available
                            if 'retry in' in error_str.lower() or 'retry_delay' in error_str.lower():
                                import re
                                import time
                                retry_match = re.search(r'retry in ([\d.]+)s', error_str, re.IGNORECASE)
                                if retry_match:
                                    retry_seconds = float(retry_match.group(1))
                                    # If retry time is reasonable (< 30 seconds), wait and retry once
                                    if retry_seconds < 30 and model_name == model_names[0]:
                                        wait_time = min(retry_seconds + 2, 15)  # Wait up to 15 seconds
                                        time.sleep(wait_time)
                                        try:
                                            response = model.generate_content(prompt)
                                            answer = response.text
                                            break
                                        except:
                                            pass
                            # If still quota error, try next model or give up
                            if model_name == model_names[-1]:
                                break
                            continue
                        # If it's a 404 (model not found), try next model
                        elif '404' in error_str:
                            continue
                        # For other errors, continue to next model
                        continue
                
                if not response:
                    if quota_exceeded:
                        raise Exception(
                            "⚠️ Google Gemini API quota exceeded. The free tier has rate limits.\n\n"
                            "Solutions:\n"
                            "1. Wait 10-15 minutes and try again\n"
                            "2. Check your quota usage at: https://ai.dev/usage?tab=rate-limit\n"
                            "3. Consider upgrading your Google Cloud plan\n"
                            "4. Or use OpenAI API instead (add OPENAI_API_KEY to .env file)"
                        )
                    else:
                        raise Exception(
                            f"Could not generate response. Error: {last_error[:300] if last_error else 'Unknown error'}\n\n"
                            "Please check:\n"
                            "1. Your API key is valid\n"
                            "2. You have available quota\n"
                            "3. The model is available for your account"
                        )
            else:
                # Use OpenAI API
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                
                prompt = f"""You are an AI assistant analyzing invoice processing results from multiple AI agents.

Here are the outputs from all 5 agents:

{context_text}

User Question: {question}

Please analyze the agent outputs and provide a comprehensive answer to the user's question. 
Focus on the data extracted, validation results, exceptions found, ERP integration status, and audit logs.
Be specific and reference the actual data from the agent outputs."""

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are an expert invoice processing analyst. Analyze agent outputs and answer questions accurately."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=1000
                )
                
                answer = response.choices[0].message.content
            
            return JsonResponse({
                'answer': answer,
                'sources': list(agent_outputs.keys()),
                'agent_outputs_analyzed': len(agent_outputs),
                'agents': list(agent_outputs.keys())
            })
            
        except ImportError as e:
            # Fallback if required package is not installed
            missing_package = 'google-generativeai' if use_google else 'openai'
            return JsonResponse({
                'error': f'{missing_package} package not installed. Please install it: pip install {missing_package}',
                'answer': f'Unable to analyze outputs. {missing_package} package is required.'
            }, status=500)
        except Exception as e:
            api_name = 'Google Gemini' if use_google else 'OpenAI'
            return JsonResponse({
                'error': f'Error calling {api_name} API: {str(e)}',
                'answer': f'Error analyzing outputs: {str(e)}'
            }, status=500)
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@api_view(['GET'])
def check_agent_readiness(request):
    """Check the readiness status of all AI agents"""
    agent_status = {}

    # Define all agents and their modules
    agents_to_check = {
        'extraction': ('agents.data_extraction_agent', 'DataExtractionAgent'),
        'validation': ('agents.validation_agent', 'ValidationAgent'),
        'exception': ('agents.exception_handling_agent', 'ExceptionHandlingAgent'),
        'erp': ('agents.erp_integration_agent', 'ERPIntegrationAgent'),
        'audit': ('agents.audit_logging_agent', 'AuditLoggingAgent'),
        'orchestrator': ('agents.mcp_orchestrator_agent', 'MCPOrchestratorAgent'),
    }

    for agent_name, (module_name, class_name) in agents_to_check.items():
        try:
            # Try to import the module
            module = __import__(module_name, fromlist=[class_name])
            agent_class = getattr(module, class_name)

            # Try to instantiate the agent
            agent_instance = agent_class()

            # Check if agent has required methods
            if hasattr(agent_instance, 'process') and callable(getattr(agent_instance, 'process')):
                agent_status[agent_name] = {
                    'status': 'ready',
                    'message': 'Agent is ready to process',
                    'confidence': 100
                }
            else:
                agent_status[agent_name] = {
                    'status': 'error',
                    'message': 'Agent missing required process method',
                    'confidence': 0
                }

        except ImportError as e:
            agent_status[agent_name] = {
                'status': 'error',
                'message': f'Import error: {str(e)}',
                'confidence': 0
            }
        except Exception as e:
            agent_status[agent_name] = {
                'status': 'error',
                'message': f'Initialization error: {str(e)}',
                'confidence': 0
            }

    return Response(agent_status)


def agent_dashboard_view(request):
    """Agent-based dashboard with real-time processing visualization"""
    total_invoices = Invoice.objects.count()
    today = timezone.now().date()
    processed_today = Invoice.objects.filter(created_at__date=today).count()
    error_invoices = Invoice.objects.filter(status='error').count()
    exception_rate = (error_invoices / total_invoices * 100) if total_invoices > 0 else 0

    recent_invoices = Invoice.objects.order_by('-created_at')[:10]

    context = {
        'total_invoices': total_invoices,
        'processed_today': processed_today,
        'exception_rate': round(exception_rate, 2),
        'recent_invoices': recent_invoices,
    }

    return render(request, 'dashboard/agent_dashboard.html', context)
