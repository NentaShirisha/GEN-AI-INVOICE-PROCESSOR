"""
Separate views for each processing stage with model chaining
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.contrib import messages
from datetime import datetime
import json
import uuid
import os

from .invoice_models import (
    InvoiceFile, ProcessingStage, InvoiceHistory, 
    ModelSuggestion, ValidationIssue
)
from .models import Invoice, Vendor


# ==================== FILE TRACKING & HISTORY ====================

def invoice_tracking_list(request):
    """List all uploaded invoices with their processing status"""
    invoice_files = InvoiceFile.objects.all().select_related('invoice', 'uploaded_by')
    
    context = {
        'invoice_files': invoice_files,
        'title': 'Invoice Tracking & History'
    }
    return render(request, 'dashboard/tracking_list.html', context)


def run_models_page(request):
    """Page to select and run individual AI models or complete pipeline"""
    invoice_files = InvoiceFile.objects.all().order_by('-uploaded_at')
    
    context = {
        'invoice_files': invoice_files,
        'title': 'Run AI Models'
    }
    return render(request, 'dashboard/run_models_page.html', context)


def invoice_detail_tracking(request, session_id):
    """Detailed tracking view for a specific invoice"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get all stages
    stages = ProcessingStage.objects.filter(invoice_file=invoice_file).order_by('started_at')
    
    # Get history
    history = InvoiceHistory.objects.filter(invoice_file=invoice_file)
    
    # Get suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        is_accepted=None
    )
    
    # Get issues
    issues = ValidationIssue.objects.filter(invoice_file=invoice_file, status='open')
    
    context = {
        'invoice_file': invoice_file,
        'stages': stages,
        'history': history,
        'suggestions': suggestions,
        'issues': issues,
        'title': f'Tracking: {invoice_file.original_filename}'
    }
    return render(request, 'dashboard/tracking_detail.html', context)


# ==================== UPLOAD PAGE ====================

def upload_invoice_page(request):
    """Separate page for invoice upload"""
    if request.method == 'POST' and request.FILES.get('invoice_file'):
        uploaded_file = request.FILES['invoice_file']
        
        # Create session ID
        session_id = str(uuid.uuid4())
        
        # Create InvoiceFile record
        invoice_file = InvoiceFile.objects.create(
            file=uploaded_file,
            original_filename=uploaded_file.name,
            file_size=uploaded_file.size,
            file_type=uploaded_file.content_type,
            session_id=session_id,
            uploaded_by=request.user if request.user.is_authenticated else None,
            status='uploaded',
            current_stage='upload'
        )
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='upload',
            description=f'File uploaded: {uploaded_file.name}',
            performed_by=request.user if request.user.is_authenticated else None
        )
        
        # Create suggestion for next stage
        ModelSuggestion.objects.create(
            invoice_file=invoice_file,
            current_stage='upload',
            suggested_next_stage='ocr',
            reason='File uploaded successfully. OCR processing is the next logical step to extract text from the invoice.',
            priority='high',
            confidence=1.0
        )
        
        messages.success(request, f'Invoice uploaded successfully! Session ID: {session_id}')
        return redirect('ocr_processing_page', session_id=session_id)
    
    context = {
        'title': 'Upload Invoice'
    }
    return render(request, 'dashboard/upload_page.html', context)


# ==================== OCR PROCESSING PAGE ====================

def ocr_processing_page(request, session_id):
    """Separate page for OCR processing"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get or create OCR stage
    ocr_stage, created = ProcessingStage.objects.get_or_create(
        invoice_file=invoice_file,
        stage_name='ocr',
        defaults={'status': 'pending'}
    )
    
    # Get previous suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        current_stage='upload'
    )
    
    context = {
        'invoice_file': invoice_file,
        'stage': ocr_stage,
        'suggestions': suggestions,
        'title': 'OCR Processing'
    }
    return render(request, 'dashboard/ocr_page.html', context)


@require_http_methods(["POST"])
def process_ocr(request, session_id):
    """Process OCR for the invoice"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Update stage
    ocr_stage = ProcessingStage.objects.get(invoice_file=invoice_file, stage_name='ocr')
    ocr_stage.status = 'processing'
    ocr_stage.started_at = timezone.now()
    ocr_stage.save()
    
    # Update invoice file status
    invoice_file.status = 'ocr_pending'
    invoice_file.current_stage = 'ocr'
    invoice_file.save()
    
    # Log history
    InvoiceHistory.objects.create(
        invoice_file=invoice_file,
        action='ocr_start',
        description='OCR processing started',
        performed_by_agent='OCR Service'
    )
    
    try:
        # TODO: Integrate actual OCR processing
        from ocr.ocr_service import InvoiceInputLayer, OCRLayoutExtraction
        input_layer = InvoiceInputLayer()
        ocr_layer = OCRLayoutExtraction()
        
        # Get file path
        file_path = invoice_file.file.path
        
        # Validate and preprocess file
        file_info = input_layer.validate_file(file_path)
        
        # Perform OCR (placeholder - actual implementation needed)
        ocr_result = {
            'text': 'OCR text extraction placeholder',
            'confidence': 0.85,
            'file_info': file_info
        }
        
        # Update stage with results
        ocr_stage.status = 'completed'
        ocr_stage.completed_at = timezone.now()
        ocr_stage.output_data = ocr_result
        ocr_stage.processing_time = (ocr_stage.completed_at - ocr_stage.started_at).total_seconds()
        ocr_stage.confidence_score = ocr_result.get('confidence', 0.0)
        ocr_stage.save()
        
        # Update invoice file
        invoice_file.status = 'ocr_completed'
        invoice_file.save()
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='ocr_complete',
            description='OCR processing completed successfully',
            data_snapshot=ocr_result,
            performed_by_agent='OCR Service'
        )
        
        # Create suggestion for next stage
        ModelSuggestion.objects.create(
            invoice_file=invoice_file,
            current_stage='ocr',
            suggested_next_stage='extraction',
            reason='OCR completed successfully. Text extracted. Next step is data extraction using AI.',
            priority='high',
            confidence=ocr_result.get('confidence', 0.8)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'OCR processing completed',
            'next_stage_url': f'/extraction/{session_id}/',
            'output': ocr_result
        })
        
    except Exception as e:
        ocr_stage.status = 'failed'
        ocr_stage.error_message = str(e)
        ocr_stage.save()
        
        invoice_file.status = 'failed'
        invoice_file.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== DATA EXTRACTION PAGE ====================

def extraction_processing_page(request, session_id):
    """Separate page for data extraction"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get OCR stage output (input for extraction)
    ocr_stage = ProcessingStage.objects.filter(
        invoice_file=invoice_file,
        stage_name='ocr',
        status='completed'
    ).first()
    
    # Get or create extraction stage
    extraction_stage, created = ProcessingStage.objects.get_or_create(
        invoice_file=invoice_file,
        stage_name='extraction',
        defaults={
            'status': 'pending',
            'input_data': ocr_stage.output_data if ocr_stage else None
        }
    )
    
    # Get suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        current_stage='ocr'
    )
    
    context = {
        'invoice_file': invoice_file,
        'stage': extraction_stage,
        'ocr_output': ocr_stage.output_data if ocr_stage else None,
        'suggestions': suggestions,
        'title': 'Data Extraction'
    }
    return render(request, 'dashboard/extraction_page.html', context)


@require_http_methods(["POST"])
def process_extraction(request, session_id):
    """Process data extraction using AI"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get extraction stage
    extraction_stage = ProcessingStage.objects.get(invoice_file=invoice_file, stage_name='extraction')
    extraction_stage.status = 'processing'
    extraction_stage.started_at = timezone.now()
    extraction_stage.save()
    
    # Update invoice file
    invoice_file.status = 'extraction_pending'
    invoice_file.current_stage = 'extraction'
    invoice_file.save()
    
    # Log history
    InvoiceHistory.objects.create(
        invoice_file=invoice_file,
        action='extraction_start',
        description='Data extraction started',
        performed_by_agent='Data Extraction Agent'
    )
    
    try:
        # Get input from OCR stage
        ocr_stage = ProcessingStage.objects.get(
            invoice_file=invoice_file,
            stage_name='ocr'
        )
        
        # TODO: Integrate actual extraction agent (currently placeholder)
        # The actual agent is async and requires proper context setup
        # from agents.data_extraction_agent import DataExtractionAgent
        # agent = DataExtractionAgent()
        # extraction_result = await agent.process(ocr_stage.output_data)
        
        # Placeholder extraction result
        extraction_result = {
            'invoice_number': 'INV-2025-001',
            'vendor_name': 'Acme Corporation',
            'vendor_id': 'VEN-12345',
            'po_number': 'PO-2025-456',
            'invoice_date': '2025-01-15',
            'due_date': '2025-02-15',
            'subtotal': 1250.00,
            'tax': 125.00,
            'total_amount': 1375.00,
            'currency': 'USD',
            'line_items': [
                {
                    'description': 'Professional Services',
                    'quantity': 10,
                    'unit_price': 100.00,
                    'amount': 1000.00
                },
                {
                    'description': 'Consulting Hours',
                    'quantity': 5,
                    'unit_price': 50.00,
                    'amount': 250.00
                }
            ],
            'confidence': 0.92,
            'ocr_input_used': True
        }
        
        # Update stage
        extraction_stage.status = 'completed'
        extraction_stage.completed_at = timezone.now()
        extraction_stage.output_data = extraction_result
        extraction_stage.processing_time = (extraction_stage.completed_at - extraction_stage.started_at).total_seconds()
        extraction_stage.model_used = 'OpenAI GPT-4'
        extraction_stage.confidence_score = extraction_result.get('confidence', 0.0)
        extraction_stage.save()
        
        # Update invoice file
        invoice_file.status = 'extraction_completed'
        invoice_file.save()
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='extraction_complete',
            description='Data extraction completed successfully',
            data_snapshot=extraction_result,
            performed_by_agent='Data Extraction Agent'
        )
        
        # Create suggestion for next stage
        ModelSuggestion.objects.create(
            invoice_file=invoice_file,
            current_stage='extraction',
            suggested_next_stage='validation',
            reason='Data extraction completed. Extracted fields need validation against business rules.',
            priority='high',
            confidence=extraction_result.get('confidence', 0.85)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Data extraction completed',
            'next_stage_url': f'/validation/{session_id}/',
            'output': extraction_result
        })
        
    except Exception as e:
        extraction_stage.status = 'failed'
        extraction_stage.error_message = str(e)
        extraction_stage.save()
        
        invoice_file.status = 'failed'
        invoice_file.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== VALIDATION PAGE ====================

def validation_processing_page(request, session_id):
    """Separate page for validation"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get extraction output (input for validation)
    extraction_stage = ProcessingStage.objects.filter(
        invoice_file=invoice_file,
        stage_name='extraction',
        status='completed'
    ).first()
    
    # Get or create validation stage
    validation_stage, created = ProcessingStage.objects.get_or_create(
        invoice_file=invoice_file,
        stage_name='validation',
        defaults={
            'status': 'pending',
            'input_data': extraction_stage.output_data if extraction_stage else None
        }
    )
    
    # Get suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        current_stage='extraction'
    )
    
    # Get any existing issues
    issues = ValidationIssue.objects.filter(invoice_file=invoice_file)
    
    context = {
        'invoice_file': invoice_file,
        'stage': validation_stage,
        'extraction_output': extraction_stage.output_data if extraction_stage else None,
        'suggestions': suggestions,
        'issues': issues,
        'title': 'Validation'
    }
    return render(request, 'dashboard/validation_page.html', context)


@require_http_methods(["POST"])
def process_validation(request, session_id):
    """Process validation"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get validation stage
    validation_stage = ProcessingStage.objects.get(invoice_file=invoice_file, stage_name='validation')
    validation_stage.status = 'processing'
    validation_stage.started_at = timezone.now()
    validation_stage.save()
    
    # Update invoice file
    invoice_file.status = 'validation_pending'
    invoice_file.current_stage = 'validation'
    invoice_file.save()
    
    # Log history
    InvoiceHistory.objects.create(
        invoice_file=invoice_file,
        action='validation_start',
        description='Validation started',
        performed_by_agent='Validation Agent'
    )
    
    try:
        # Get input from extraction stage
        extraction_stage = ProcessingStage.objects.get(
            invoice_file=invoice_file,
            stage_name='extraction'
        )
        
        # TODO: Integrate actual validation agent (currently placeholder)
        # from agents.validation_agent import ValidationAgent
        # agent = ValidationAgent()
        # validation_result = await agent.process(extraction_stage.output_data)
        
        # Placeholder validation result
        validation_result = {
            'is_valid': True,
            'issues': [
                {
                    'type': 'format',
                    'severity': 'low',
                    'description': 'Date format could be standardized',
                    'field': 'invoice_date',
                    'expected': 'YYYY-MM-DD',
                    'actual': extraction_stage.output_data.get('invoice_date') if extraction_stage.output_data else 'N/A'
                }
            ],
            'warnings': ['Total amount matches line items sum'],
            'passed_rules': ['vendor_exists', 'amount_positive', 'date_valid'],
            'confidence': 0.88
        }
        
        # Create validation issues if any
        if validation_result.get('issues'):
            for issue in validation_result['issues']:
                ValidationIssue.objects.create(
                    invoice_file=invoice_file,
                    stage='validation',
                    issue_type=issue.get('type', 'Unknown'),
                    severity=issue.get('severity', 'medium'),
                    description=issue.get('description', ''),
                    field_name=issue.get('field'),
                    expected_value=issue.get('expected'),
                    actual_value=issue.get('actual')
                )
        
        # Update stage
        validation_stage.status = 'completed'
        validation_stage.completed_at = timezone.now()
        validation_stage.output_data = validation_result
        validation_stage.processing_time = (validation_stage.completed_at - validation_stage.started_at).total_seconds()
        validation_stage.model_used = 'Rule-based + AI'
        validation_stage.save()
        
        # Update invoice file
        invoice_file.status = 'validation_completed'
        invoice_file.save()
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='validation_complete',
            description=f'Validation completed. Found {len(validation_result.get("issues", []))} issues.',
            data_snapshot=validation_result,
            performed_by_agent='Validation Agent'
        )
        
        # Determine next stage based on validation results
        if validation_result.get('issues'):
            next_stage = 'exception'
            reason = f'Validation found {len(validation_result["issues"])} issues. Exception handling required.'
            priority = 'high'
        else:
            next_stage = 'erp'
            reason = 'Validation passed. Ready for ERP integration.'
            priority = 'high'
        
        ModelSuggestion.objects.create(
            invoice_file=invoice_file,
            current_stage='validation',
            suggested_next_stage=next_stage,
            reason=reason,
            priority=priority,
            confidence=validation_result.get('confidence', 0.9)
        )
        
        next_url = f'/exception/{session_id}/' if next_stage == 'exception' else f'/erp/{session_id}/'
        
        return JsonResponse({
            'success': True,
            'message': 'Validation completed',
            'next_stage_url': next_url,
            'output': validation_result,
            'issues_count': len(validation_result.get('issues', []))
        })
        
    except Exception as e:
        validation_stage.status = 'failed'
        validation_stage.error_message = str(e)
        validation_stage.save()
        
        invoice_file.status = 'failed'
        invoice_file.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== EXCEPTION HANDLING PAGE ====================

def exception_processing_page(request, session_id):
    """Separate page for exception handling"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get validation output
    validation_stage = ProcessingStage.objects.filter(
        invoice_file=invoice_file,
        stage_name='validation',
        status='completed'
    ).first()
    
    # Get or create exception stage
    exception_stage, created = ProcessingStage.objects.get_or_create(
        invoice_file=invoice_file,
        stage_name='exception',
        defaults={
            'status': 'pending',
            'input_data': validation_stage.output_data if validation_stage else None
        }
    )
    
    # Get issues
    issues = ValidationIssue.objects.filter(invoice_file=invoice_file, status='open')
    
    # Get suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        current_stage='validation'
    )
    
    context = {
        'invoice_file': invoice_file,
        'stage': exception_stage,
        'validation_output': validation_stage.output_data if validation_stage else None,
        'issues': issues,
        'suggestions': suggestions,
        'title': 'Exception Handling'
    }
    return render(request, 'dashboard/exception_page.html', context)


@require_http_methods(["POST"])
def process_exception(request, session_id):
    """Process exception handling"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get exception stage
    exception_stage = ProcessingStage.objects.get(invoice_file=invoice_file, stage_name='exception')
    exception_stage.status = 'processing'
    exception_stage.started_at = timezone.now()
    exception_stage.save()
    
    # Update invoice file
    invoice_file.status = 'exception_pending'
    invoice_file.current_stage = 'exception'
    invoice_file.save()
    
    # Log history
    InvoiceHistory.objects.create(
        invoice_file=invoice_file,
        action='exception_start',
        description='Exception handling started',
        performed_by_agent='Exception Handling Agent'
    )
    
    try:
        # Get input from validation stage
        validation_stage = ProcessingStage.objects.get(
            invoice_file=invoice_file,
            stage_name='validation'
        )
        
        # TODO: Integrate actual exception handling agent (currently placeholder)
        # from agents.exception_handling_agent import ExceptionHandlingAgent
        # agent = ExceptionHandlingAgent()
        # exception_result = await agent.process(validation_stage.output_data)
        
        # Placeholder exception handling result
        exception_result = {
            'exceptions_handled': 1,
            'auto_resolved': ['date_format_standardized'],
            'manual_review_required': [],
            'corrections_made': {
                'invoice_date': '2025-01-15'
            },
            'confidence': 0.90
        }
        
        # Update stage
        exception_stage.status = 'completed'
        exception_stage.completed_at = timezone.now()
        exception_stage.output_data = exception_result
        exception_stage.processing_time = (exception_stage.completed_at - exception_stage.started_at).total_seconds()
        exception_stage.save()
        
        # Update invoice file
        invoice_file.status = 'exception_completed'
        invoice_file.save()
        
        # Resolve issues
        issues = ValidationIssue.objects.filter(invoice_file=invoice_file, status='open')
        for issue in issues:
            issue.status = 'resolved'
            issue.resolution_notes = 'Resolved by Exception Handling Agent'
            issue.resolved_at = timezone.now()
            issue.save()
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='exception_complete',
            description='Exception handling completed',
            data_snapshot=exception_result,
            performed_by_agent='Exception Handling Agent'
        )
        
        # Suggest next stage
        ModelSuggestion.objects.create(
            invoice_file=invoice_file,
            current_stage='exception',
            suggested_next_stage='erp',
            reason='Exceptions resolved. Ready for ERP integration.',
            priority='high',
            confidence=0.95
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Exception handling completed',
            'next_stage_url': f'/erp/{session_id}/',
            'output': exception_result
        })
        
    except Exception as e:
        exception_stage.status = 'failed'
        exception_stage.error_message = str(e)
        exception_stage.save()
        
        invoice_file.status = 'failed'
        invoice_file.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== ERP INTEGRATION PAGE ====================

def erp_processing_page(request, session_id):
    """Separate page for ERP integration"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get previous stage output
    prev_stage = ProcessingStage.objects.filter(
        invoice_file=invoice_file,
        stage_name__in=['exception', 'validation'],
        status='completed'
    ).order_by('-completed_at').first()
    
    # Get or create ERP stage
    erp_stage, created = ProcessingStage.objects.get_or_create(
        invoice_file=invoice_file,
        stage_name='erp',
        defaults={
            'status': 'pending',
            'input_data': prev_stage.output_data if prev_stage else None
        }
    )
    
    # Get suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        suggested_next_stage='erp'
    ).order_by('-created_at')[:1]
    
    context = {
        'invoice_file': invoice_file,
        'stage': erp_stage,
        'previous_output': prev_stage.output_data if prev_stage else None,
        'suggestions': suggestions,
        'title': 'ERP Integration'
    }
    return render(request, 'dashboard/erp_page.html', context)


@require_http_methods(["POST"])
def process_erp(request, session_id):
    """Process ERP integration"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get ERP stage
    erp_stage = ProcessingStage.objects.get(invoice_file=invoice_file, stage_name='erp')
    erp_stage.status = 'processing'
    erp_stage.started_at = timezone.now()
    erp_stage.save()
    
    # Update invoice file
    invoice_file.status = 'erp_pending'
    invoice_file.current_stage = 'erp'
    invoice_file.save()
    
    # Log history
    InvoiceHistory.objects.create(
        invoice_file=invoice_file,
        action='erp_start',
        description='ERP integration started',
        performed_by_agent='ERP Integration Agent'
    )
    
    try:
        # Get previous stage output
        prev_stage = ProcessingStage.objects.filter(
            invoice_file=invoice_file,
            stage_name__in=['exception', 'validation'],
            status='completed'
        ).order_by('-completed_at').first()
        
        # TODO: Integrate actual ERP agent (currently placeholder)
        # from agents.erp_integration_agent import ERPIntegrationAgent
        # agent = ERPIntegrationAgent()
        # erp_result = await agent.process(prev_stage.output_data if prev_stage else {})
        
        # Placeholder ERP integration result
        erp_result = {
            'erp_status': 'posted',
            'erp_invoice_id': 'ERP-INV-2025-12345',
            'erp_transaction_id': 'TXN-789456',
            'posting_date': timezone.now().isoformat(),
            'erp_system': 'SAP',
            'success': True,
            'message': 'Invoice successfully posted to ERP system'
        }
        
        # Update stage
        erp_stage.status = 'completed'
        erp_stage.completed_at = timezone.now()
        erp_stage.output_data = erp_result
        erp_stage.processing_time = (erp_stage.completed_at - erp_stage.started_at).total_seconds()
        erp_stage.save()
        
        # Update invoice file
        invoice_file.status = 'erp_completed'
        invoice_file.save()
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='erp_complete',
            description='Posted to ERP successfully',
            data_snapshot=erp_result,
            performed_by_agent='ERP Integration Agent'
        )
        
        # Suggest final stage
        ModelSuggestion.objects.create(
            invoice_file=invoice_file,
            current_stage='erp',
            suggested_next_stage='audit',
            reason='ERP integration completed. Audit logging is the final step.',
            priority='medium',
            confidence=1.0
        )
        
        return JsonResponse({
            'success': True,
            'message': 'ERP integration completed',
            'next_stage_url': f'/audit/{session_id}/',
            'output': erp_result
        })
        
    except Exception as e:
        erp_stage.status = 'failed'
        erp_stage.error_message = str(e)
        erp_stage.save()
        
        invoice_file.status = 'failed'
        invoice_file.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== AUDIT LOGGING PAGE ====================

def audit_processing_page(request, session_id):
    """Separate page for audit logging"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get ERP output
    erp_stage = ProcessingStage.objects.filter(
        invoice_file=invoice_file,
        stage_name='erp',
        status='completed'
    ).first()
    
    # Get or create audit stage
    audit_stage, created = ProcessingStage.objects.get_or_create(
        invoice_file=invoice_file,
        stage_name='audit',
        defaults={
            'status': 'pending',
            'input_data': erp_stage.output_data if erp_stage else None
        }
    )
    
    # Get complete history
    history = InvoiceHistory.objects.filter(invoice_file=invoice_file)
    
    # Get suggestions
    suggestions = ModelSuggestion.objects.filter(
        invoice_file=invoice_file,
        current_stage='erp'
    )
    
    context = {
        'invoice_file': invoice_file,
        'stage': audit_stage,
        'erp_output': erp_stage.output_data if erp_stage else None,
        'complete_history': history,
        'suggestions': suggestions,
        'title': 'Audit Logging'
    }
    return render(request, 'dashboard/audit_page.html', context)


@require_http_methods(["POST"])
def process_audit(request, session_id):
    """Process audit logging"""
    invoice_file = get_object_or_404(InvoiceFile, session_id=session_id)
    
    # Get audit stage
    audit_stage = ProcessingStage.objects.get(invoice_file=invoice_file, stage_name='audit')
    audit_stage.status = 'processing'
    audit_stage.started_at = timezone.now()
    audit_stage.save()
    
    try:
        # Get all stages data
        all_stages = ProcessingStage.objects.filter(invoice_file=invoice_file)
        
        # TODO: Integrate actual audit agent (currently placeholder)
        # from agents.audit_logging_agent import AuditLoggingAgent
        # agent = AuditLoggingAgent()
        # audit_result = await agent.process(audit_data)
        
        # Compile all data for audit
        audit_data = {
            'invoice_file': invoice_file.original_filename,
            'session_id': invoice_file.session_id,
            'stages': [
                {
                    'name': stage.stage_name,
                    'status': stage.status,
                    'output': stage.output_data,
                    'processing_time': stage.processing_time
                }
                for stage in all_stages
            ]
        }
        
        # Placeholder audit result
        audit_result = {
            'audit_id': f'AUDIT-{invoice_file.session_id[:8]}',
            'timestamp': timezone.now().isoformat(),
            'total_stages': all_stages.count(),
            'completed_stages': all_stages.filter(status='completed').count(),
            'total_processing_time': sum([s.processing_time or 0 for s in all_stages]),
            'compliance_check': 'passed',
            'audit_trail_complete': True,
            'summary': 'All stages completed successfully with full audit trail'
        }
        
        # Update stage
        audit_stage.status = 'completed'
        audit_stage.completed_at = timezone.now()
        audit_stage.output_data = audit_result
        audit_stage.processing_time = (audit_stage.completed_at - audit_stage.started_at).total_seconds()
        audit_stage.save()
        
        # Update invoice file
        invoice_file.status = 'completed'
        invoice_file.completed_at = timezone.now()
        invoice_file.save()
        
        # Log history
        InvoiceHistory.objects.create(
            invoice_file=invoice_file,
            action='audit_complete',
            description='Audit logging completed. Processing finished.',
            data_snapshot=audit_result,
            performed_by_agent='Audit Logging Agent'
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Audit logging completed. Processing finished!',
            'completion_url': f'/tracking/{session_id}/',
            'output': audit_result
        })
        
    except Exception as e:
        audit_stage.status = 'failed'
        audit_stage.error_message = str(e)
        audit_stage.save()
        
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== Q&A ANALYSIS PAGE ====================

def qa_analysis_page(request):
    """AI-powered Q&A page to analyze all processed invoices"""
    context = {
        'title': 'Invoice Q&A Analysis'
    }
    return render(request, 'dashboard/qa_analysis_page.html', context)
