from django.db import models
from django.contrib.auth.models import User

class Vendor(models.Model):
    name = models.CharField(max_length=255)
    address = models.TextField()
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20)
    tax_id = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Invoice(models.Model):
    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('processing', 'Processing'),
        ('extracted', 'Extracted'),
        ('validated', 'Validated'),
        ('posted', 'Posted to ERP'),
        ('error', 'Error'),
    ]

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, null=True, blank=True)
    invoice_number = models.CharField(max_length=100)
    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='USD')
    file = models.FileField(upload_to='invoices/', null=True, blank=True)
    extracted_data = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='uploaded')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional fields used in the views
    po_number = models.CharField(max_length=100, null=True, blank=True)
    raw_text = models.TextField(null=True, blank=True)
    confidence_score = models.FloatField(default=0.0)

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.vendor.name}"
