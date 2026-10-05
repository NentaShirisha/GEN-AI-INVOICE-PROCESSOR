import json
import requests
from .models import ERPMapping
from compliance.models import AuditLog
from dashboard.models import Invoice

class ERPService:
    def __init__(self):
        self.mappings = {}

    def get_mapping(self, erp_system):
        """Get ERP mapping configuration"""
        try:
            mapping = ERPMapping.objects.get(erp_system=erp_system, is_active=True)
            return mapping
        except ERPMapping.DoesNotExist:
            return None

    def transform_invoice_data(self, invoice_data, erp_system):
        """Transform invoice data according to ERP mapping"""
        mapping = self.get_mapping(erp_system)
        if not mapping:
            return None

        transformed_data = {}
        field_mapping = mapping.field_mapping

        for invoice_field, erp_field in field_mapping.items():
            if invoice_field in invoice_data:
                transformed_data[erp_field] = invoice_data[invoice_field]

        return transformed_data

    def post_to_sap(self, data, mapping):
        """Post data to SAP system"""
        # Mock SAP posting
        try:
            # In real implementation, use pyrfc or SAP API
            response = {
                'status': 'success',
                'sap_document_number': '123456789',
                'message': 'Invoice posted successfully'
            }
            return response
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def post_to_oracle(self, data, mapping):
        """Post data to Oracle system"""
        # Mock Oracle posting
        try:
            response = {
                'status': 'success',
                'oracle_document_id': 'ORC123456',
                'message': 'Invoice posted successfully'
            }
            return response
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def post_to_dynamics(self, data, mapping):
        """Post data to Microsoft Dynamics"""
        # Mock Dynamics posting
        try:
            response = {
                'status': 'success',
                'dynamics_id': 'DYN789456',
                'message': 'Invoice posted successfully'
            }
            return response
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def post_invoice(self, invoice, erp_system):
        """Post invoice to specified ERP system"""
        if not invoice.extracted_data:
            return {'status': 'error', 'message': 'No extracted data'}

        transformed_data = self.transform_invoice_data(invoice.extracted_data, erp_system)
        if not transformed_data:
            return {'status': 'error', 'message': 'No mapping found for ERP system'}

        mapping = self.get_mapping(erp_system)

        if erp_system == 'sap':
            result = self.post_to_sap(transformed_data, mapping)
        elif erp_system == 'oracle':
            result = self.post_to_oracle(transformed_data, mapping)
        elif erp_system == 'dynamics':
            result = self.post_to_dynamics(transformed_data, mapping)
        else:
            result = {'status': 'error', 'message': 'Unsupported ERP system'}

        # Log the posting
        AuditLog.objects.create(
            invoice=invoice,
            action='posting',
            details=json.dumps(result),
            user=None
        )

        if result['status'] == 'success':
            invoice.status = 'posted'
            invoice.save()

        return result

    def generate_output_formats(self, invoice_data):
        """Generate different output formats"""
        formats = {
            'json': json.dumps(invoice_data, indent=2),
            'xml': self._generate_xml(invoice_data),
            'idoc': self._generate_idoc(invoice_data)
        }
        return formats

    def _generate_xml(self, data):
        """Generate XML format"""
        xml = "<Invoice>\n"
        for key, value in data.items():
            xml += f"  <{key}>{value}</{key}>\n"
        xml += "</Invoice>"
        return xml

    def _generate_idoc(self, data):
        """Generate IDoc format (simplified)"""
        idoc = "IDOC BEGIN\n"
        idoc += f"INVOICE_NUMBER: {data.get('invoice_number', '')}\n"
        idoc += f"VENDOR: {data.get('vendor', '')}\n"
        idoc += f"AMOUNT: {data.get('total_amount', '')}\n"
        idoc += "IDOC END"
        return idoc

# Singleton instance
erp_service = ERPService()