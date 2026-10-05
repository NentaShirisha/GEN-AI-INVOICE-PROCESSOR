from rest_framework import serializers
from .models import Invoice, Vendor

class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = '__all__'

class InvoiceSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = ['status', 'extracted_data', 'created_at', 'updated_at']