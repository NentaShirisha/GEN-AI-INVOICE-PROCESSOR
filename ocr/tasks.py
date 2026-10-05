from celery import shared_task
from dashboard.models import Invoice
from ocr.ocr_service import invoice_input_layer, ocr_layout_extraction
from ai_extraction.ai_service import ai_service
from validation.validation_service import validation_service
from erp_integration.erp_service import erp_service
from compliance.models import AuditLog
import json
import os

@shared_task
def process_invoice_task(invoice_id):
    """Async task to process an invoice end-to-end using staged approach"""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        invoice.status = 'processing'
        invoice.save()

        # Step 1: Invoice Input Layer - Preprocessing
        file_path = invoice.file.path
        stage1_result = invoice_input_layer.process_input(file_path)

        # Step 2: OCR & Layout Extraction
        stage2_results = ocr_layout_extraction.process_document(stage1_result['processed_images'])

        # Step 3: AI Extraction & Validation
        stage3_results = ai_service.process_invoice_data(stage2_results)

        # Combine results from all pages (take the best results)
        if stage3_results:
            best_result = max(stage3_results, key=lambda x: x.get('overall_confidence', 0))

            # Update invoice with extracted data
            extracted_fields = best_result.get('extracted_fields', {})

            # Update invoice fields if confidence is high enough
            if best_result.get('overall_confidence', 0) > 0.7:
                if 'invoice_number' in extracted_fields and extracted_fields['invoice_number']['confidence'] > 0.8:
                    invoice.invoice_number = extracted_fields['invoice_number']['value']
                if 'total_amount' in extracted_fields and extracted_fields['total_amount']['confidence'] > 0.8:
                    invoice.total_amount = extracted_fields['total_amount']['value']
                if 'invoice_date' in extracted_fields and extracted_fields['invoice_date']['confidence'] > 0.8:
                    invoice.invoice_date = extracted_fields['invoice_date']['value']
                if 'due_date' in extracted_fields and extracted_fields['due_date']['confidence'] > 0.8:
                    invoice.due_date = extracted_fields['due_date']['value']
                if 'tax_amount' in extracted_fields and extracted_fields['tax_amount']['confidence'] > 0.8:
                    invoice.tax_amount = extracted_fields['tax_amount']['value']
                if 'po_number' in extracted_fields and extracted_fields['po_number']['confidence'] > 0.8:
                    invoice.po_number = extracted_fields['po_number']['value']

            # Store all extracted data
            invoice.extracted_data = {
                'stage_processing': True,
                'confidence_scores': {k: v.get('confidence', 0) for k, v in extracted_fields.items() if isinstance(v, dict)},
                'validation_results': best_result.get('validation_results', {}),
                'needs_review': best_result.get('needs_review', False),
                'line_items': extracted_fields.get('line_items', {}).get('value', []),
                'raw_text': best_result.get('raw_text', '')
            }

            invoice.confidence_score = best_result.get('overall_confidence', 0.5)
            invoice.status = 'processed' if best_result.get('overall_confidence', 0) > 0.8 else 'needs_review'
        else:
            invoice.status = 'error'
            invoice.extracted_data = {'error': 'Failed to process invoice'}

        invoice.save()

        # Log the processing
        AuditLog.objects.create(
            invoice=invoice,
            action='processed',
            details=json.dumps({
                'stage1_pages': stage1_result.get('total_pages', 0),
                'stage2_results': len(stage2_results),
                'stage3_results': len(stage3_results),
                'final_confidence': invoice.confidence_score
            })
        )

        return {'status': 'success', 'invoice_id': invoice.id, 'confidence': invoice.confidence_score}

    except Exception as e:
        invoice = Invoice.objects.get(id=invoice_id)
        invoice.status = 'error'
        invoice.extracted_data = {'error': str(e)}
        invoice.save()

        AuditLog.objects.create(
            invoice=invoice,
            action='error',
            details=json.dumps({'error': str(e)})
        )

        return {'status': 'error', 'error': str(e)}

        AuditLog.objects.create(
            invoice=invoice,
            action='ocr',
            details=f"OCR completed for {invoice.file.name}",
            user=None
        )

        # Step 2: AI Extraction
        extracted_data = ai_service.process_extracted_text(extracted_text)
        invoice.extracted_data = extracted_data
        invoice.save()

        AuditLog.objects.create(
            invoice=invoice,
            action='extraction',
            details=json.dumps(extracted_data),
            user=None
        )

        # Step 3: Validation
        validation_result = validation_service.validate_invoice(invoice)
        if not validation_result['is_valid']:
            invoice.status = 'error'
            invoice.save()
            return {'status': 'error', 'message': 'Validation failed', 'errors': validation_result['errors']}

        invoice.status = 'validated'
        invoice.save()

        # Step 4: ERP Posting (mock)
        erp_result = erp_service.post_invoice(invoice, 'sap')  # Default to SAP

        return {
            'status': 'success',
            'invoice_id': invoice_id,
            'extracted_data': extracted_data,
            'validation': validation_result,
            'erp_posting': erp_result
        }

    except Exception as e:
        invoice.status = 'error'
        invoice.save()
        return {'status': 'error', 'message': str(e)}