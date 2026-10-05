from django.db import models

class ERPMapping(models.Model):
    ERP_CHOICES = [
        ('sap', 'SAP'),
        ('oracle', 'Oracle'),
        ('dynamics', 'Microsoft Dynamics'),
    ]

    erp_system = models.CharField(max_length=20, choices=ERP_CHOICES)
    field_mapping = models.JSONField()  # Maps invoice fields to ERP fields
    api_endpoint = models.URLField()
    api_key = models.CharField(max_length=255, blank=True)
    username = models.CharField(max_length=100, blank=True)
    password = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.erp_system} Mapping"
