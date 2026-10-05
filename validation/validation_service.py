from dashboard.models import Vendor, Invoice
from compliance.models import AuditLog
import json

class ValidationService:
    def __init__(self):
        self.mock_erp_data = {
            'vendors': [
                {'name': 'ABC Corp', 'tax_id': '123456789'},
                {'name': 'XYZ Ltd', 'tax_id': '987654321'},
            ]
        }

    def validate_vendor(self, vendor_data):
        """Validate vendor against ERP master data"""
        vendor_name = vendor_data.get('name', '')
        tax_id = vendor_data.get('tax_id', '')

        for vendor in self.mock_erp_data['vendors']:
            if vendor['name'].lower() == vendor_name.lower() or vendor['tax_id'] == tax_id:
                return True, vendor

        return False, None

    def validate_invoice_data(self, extracted_data):
        """Validate extracted invoice data"""
        errors = []
        warnings = []

        # Check required fields
        required_fields = ['invoice_number', 'invoice_date', 'total_amount', 'vendor']
        for field in required_fields:
            if field not in extracted_data or not extracted_data[field]:
                errors.append(f"Missing required field: {field}")

        # Validate vendor
        if 'vendor' in extracted_data:
            is_valid, vendor_info = self.validate_vendor({'name': extracted_data['vendor']})
            if not is_valid:
                warnings.append(f"Vendor '{extracted_data['vendor']}' not found in ERP system")

        # Validate amounts
        if 'total_amount' in extracted_data:
            try:
                amount = float(extracted_data['total_amount'].replace(',', ''))
                if amount <= 0:
                    errors.append("Total amount must be positive")
            except ValueError:
                errors.append("Invalid total amount format")

        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'validated_data': extracted_data
        }

    def validate_invoice(self, invoice):
        """Validate a complete invoice"""
        if not invoice.extracted_data:
            return {'is_valid': False, 'errors': ['No extracted data found']}

        validation_result = self.validate_invoice_data(invoice.extracted_data)

        # Log validation
        AuditLog.objects.create(
            invoice=invoice,
            action='validation',
            details=json.dumps(validation_result),
            user=None
        )

        return validation_result

# Singleton instance
validation_service = ValidationService()