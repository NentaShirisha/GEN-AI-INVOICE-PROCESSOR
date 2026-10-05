from django.db import models
from dashboard.models import Invoice

class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('upload', 'Invoice Uploaded'),
        ('ocr', 'OCR Processing'),
        ('extraction', 'AI Extraction'),
        ('validation', 'Validation'),
        ('posting', 'ERP Posting'),
        ('correction', 'Manual Correction'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    details = models.TextField()
    user = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True)

    def __str__(self):
        return f"{self.action} on {self.invoice} at {self.timestamp}"
