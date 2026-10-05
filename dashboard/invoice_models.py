"""
Extended models for invoice tracking, history, and multi-model processing
"""
from django.db import models
from django.contrib.auth.models import User
from .models import Invoice, Vendor


class InvoiceFile(models.Model):
    """Track uploaded invoice files with complete history"""
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('ocr_pending', 'OCR Pending'),
        ('ocr_completed', 'OCR Completed'),
        ('extraction_pending', 'Extraction Pending'),
        ('extraction_completed', 'Extraction Completed'),
        ('validation_pending', 'Validation Pending'),
        ('validation_completed', 'Validation Completed'),
        ('exception_pending', 'Exception Handling Pending'),
        ('exception_completed', 'Exception Handled'),
        ('erp_pending', 'ERP Integration Pending'),
        ('erp_completed', 'Posted to ERP'),
        ('audit_completed', 'Audit Logged'),
        ('completed', 'Processing Completed'),
        ('failed', 'Processing Failed'),
    ]
    
    # File information
    file = models.FileField(upload_to='invoices/%Y/%m/%d/')
    original_filename = models.CharField(max_length=255)
    file_size = models.IntegerField()
    file_type = models.CharField(max_length=50)
    
    # Processing status
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='uploaded')
    current_stage = models.CharField(max_length=50, default='upload')
    
    # Timestamps
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # User tracking
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Related invoice (created after extraction)
    invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Session tracking
    session_id = models.CharField(max_length=100, unique=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        
    def __str__(self):
        return f"{self.original_filename} - {self.status}"


class ProcessingStage(models.Model):
    """Track each processing stage for an invoice"""
    STAGE_CHOICES = [
        ('upload', 'File Upload'),
        ('ocr', 'OCR Processing'),
        ('extraction', 'Data Extraction'),
        ('validation', 'Validation'),
        ('exception', 'Exception Handling'),
        ('erp', 'ERP Integration'),
        ('audit', 'Audit Logging'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]
    
    invoice_file = models.ForeignKey(InvoiceFile, on_delete=models.CASCADE, related_name='stages')
    stage_name = models.CharField(max_length=20, choices=STAGE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Input/Output tracking
    input_data = models.JSONField(null=True, blank=True)
    output_data = models.JSONField(null=True, blank=True)
    
    # Model information
    model_used = models.CharField(max_length=100, null=True, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    
    # Error tracking
    error_message = models.TextField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    
    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processing_time = models.FloatField(null=True, blank=True)  # in seconds
    
    # Suggestions for next stage
    next_stage_suggestion = models.CharField(max_length=20, null=True, blank=True)
    suggestions = models.JSONField(null=True, blank=True)
    
    class Meta:
        ordering = ['invoice_file', 'started_at']
        unique_together = ['invoice_file', 'stage_name']
        
    def __str__(self):
        return f"{self.invoice_file.original_filename} - {self.stage_name} - {self.status}"


class InvoiceHistory(models.Model):
    """Complete audit trail for invoice processing"""
    ACTION_CHOICES = [
        ('upload', 'File Uploaded'),
        ('ocr_start', 'OCR Started'),
        ('ocr_complete', 'OCR Completed'),
        ('extraction_start', 'Extraction Started'),
        ('extraction_complete', 'Extraction Completed'),
        ('validation_start', 'Validation Started'),
        ('validation_complete', 'Validation Completed'),
        ('validation_failed', 'Validation Failed'),
        ('exception_start', 'Exception Handling Started'),
        ('exception_complete', 'Exception Resolved'),
        ('erp_start', 'ERP Integration Started'),
        ('erp_complete', 'Posted to ERP'),
        ('erp_failed', 'ERP Integration Failed'),
        ('audit_complete', 'Audit Logged'),
        ('manual_review', 'Manual Review Required'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('note_added', 'Note Added'),
    ]
    
    invoice_file = models.ForeignKey(InvoiceFile, on_delete=models.CASCADE, related_name='history')
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    description = models.TextField()
    
    # Data snapshot at this point
    data_snapshot = models.JSONField(null=True, blank=True)
    
    # User tracking
    performed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    performed_by_agent = models.CharField(max_length=100, null=True, blank=True)
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = 'Invoice Histories'
        
    def __str__(self):
        return f"{self.invoice_file.original_filename} - {self.action} at {self.timestamp}"


class ModelSuggestion(models.Model):
    """Store suggestions for next model to run"""
    PRIORITY_CHOICES = [
        ('high', 'High Priority'),
        ('medium', 'Medium Priority'),
        ('low', 'Low Priority'),
    ]
    
    invoice_file = models.ForeignKey(InvoiceFile, on_delete=models.CASCADE, related_name='suggestions')
    current_stage = models.CharField(max_length=50)
    suggested_next_stage = models.CharField(max_length=50)
    
    reason = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    confidence = models.FloatField(default=0.0)
    
    # Conditions for suggestion
    conditions_met = models.JSONField(null=True, blank=True)
    
    # Action status
    is_accepted = models.BooleanField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-priority', '-confidence', '-created_at']
        
    def __str__(self):
        return f"{self.current_stage} → {self.suggested_next_stage} ({self.priority})"


class ValidationIssue(models.Model):
    """Track validation issues found during processing"""
    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('info', 'Information'),
    ]
    
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('resolved', 'Resolved'),
        ('ignored', 'Ignored'),
        ('escalated', 'Escalated'),
    ]
    
    invoice_file = models.ForeignKey(InvoiceFile, on_delete=models.CASCADE, related_name='issues')
    stage = models.CharField(max_length=50)
    
    issue_type = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    
    description = models.TextField()
    field_name = models.CharField(max_length=100, null=True, blank=True)
    expected_value = models.CharField(max_length=255, null=True, blank=True)
    actual_value = models.CharField(max_length=255, null=True, blank=True)
    
    # Resolution
    resolution_notes = models.TextField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-severity', '-created_at']
        
    def __str__(self):
        return f"{self.issue_type} - {self.severity} ({self.status})"
