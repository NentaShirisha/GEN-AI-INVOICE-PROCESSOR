"""
ERP Integration Agent
=====================

Goal: Push validated invoices into ERP (SAP/Oracle/MS Dynamics).

Input: Validated JSON
Process:
- Map JSON  ERP schema (IDoc/XML/CSV)
- Call ERP API / staging table

Output: Confirmation or error log

Design Choices:
- LLM: Instruction-based transformer for JSON  ERP XML mapping
- Tools: SAP BAPI/IDoc APIs or REST endpoints
- Example: {"Invoice_No": "INV-45678", "Vendor_ID": "V9821"}  <INVOICE><ID>INV-45678</ID><VENDOR>V9821</VENDOR></INVOICE>
"""

import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, List
from datetime import datetime
from .base_agent import BaseAgent, AgentResult, ProcessingContext

class ERPIntegrationAgent(BaseAgent):
    def __init__(self):
        super().__init__("ERP Integration Agent")
        # Mock ERP system - in production, this would connect to actual ERP
        self.erp_systems = {
            'sap': {'type': 'SAP', 'endpoint': 'sap.company.com', 'format': 'idoc'},
            'oracle': {'type': 'Oracle', 'endpoint': 'oracle.company.com', 'format': 'xml'},
            'dynamics': {'type': 'Dynamics', 'endpoint': 'dynamics.company.com', 'format': 'json'}
        }

    def _map_to_sap_idoc(self, invoice_data: Dict[str, Any]) -> str:
        """Map invoice data to SAP IDoc format"""
        extracted = invoice_data.get('extracted_fields', {})
        
        # Create IDoc XML structure
        idoc = ET.Element("IDOC")
        idoc.set("BEGIN", "1")
        
        # EDI_DC40 - Control record
        control = ET.SubElement(idoc, "EDI_DC40")
        ET.SubElement(control, "IDOCTYP").text = "INVOIC02"
        ET.SubElement(control, "MESTYP").text = "INVOIC"
        ET.SubElement(control, "SNDPOR").text = "AI_INVOICE"
        ET.SubElement(control, "SNDPRT").text = "LS"
        ET.SubElement(control, "SNDPRN").text = "AI_SYSTEM"
        
        # E1EDK01 - Header
        header = ET.SubElement(idoc, "E1EDK01")
        ET.SubElement(header, "BELNR").text = extracted.get('invoice_number', '')
        ET.SubElement(header, "BUDAT").text = extracted.get('invoice_date', '')
        ET.SubElement(header, "WAERK").text = "USD"  # Default currency
        
        # E1EDKA1 - Vendor
        vendor = ET.SubElement(idoc, "E1EDKA1")
        vendor.set("PARVW", "LF")  # Vendor role
        ET.SubElement(vendor, "LIFNR").text = extracted.get('vendor_id', '')
        ET.SubElement(vendor, "NAME1").text = extracted.get('vendor_name', '')
        
        # E1EDP01 - Item
        item = ET.SubElement(idoc, "E1EDP01")
        ET.SubElement(item, "POSEX").text = "1"
        ET.SubElement(item, "MENGE").text = "1"
        ET.SubElement(item, "MENEE").text = "EA"
        ET.SubElement(item, "NETWR").text = str(extracted.get('total_amount', 0))
        
        # Convert to string
        return ET.tostring(idoc, encoding='unicode', method='xml')

    def _map_to_oracle_xml(self, invoice_data: Dict[str, Any]) -> str:
        """Map invoice data to Oracle XML format"""
        extracted = invoice_data.get('extracted_fields', {})
        
        # Create Oracle XML structure
        invoice = ET.Element("Invoice")
        invoice.set("xmlns", "http://xmlns.oracle.com/apps/financials/payables/invoices/invoiceService/")
        
        # Invoice Header
        header = ET.SubElement(invoice, "InvoiceHeader")
        ET.SubElement(header, "InvoiceNumber").text = extracted.get('invoice_number', '')
        ET.SubElement(header, "InvoiceDate").text = extracted.get('invoice_date', '')
        ET.SubElement(header, "InvoiceAmount").text = str(extracted.get('total_amount', 0))
        ET.SubElement(header, "InvoiceCurrencyCode").text = "USD"
        
        # Supplier
        supplier = ET.SubElement(header, "Supplier")
        ET.SubElement(supplier, "SupplierNumber").text = extracted.get('vendor_id', '')
        ET.SubElement(supplier, "SupplierName").text = extracted.get('vendor_name', '')
        
        # Invoice Lines
        lines = ET.SubElement(invoice, "InvoiceLines")
        line = ET.SubElement(lines, "InvoiceLine")
        ET.SubElement(line, "LineNumber").text = "1"
        ET.SubElement(line, "LineAmount").text = str(extracted.get('total_amount', 0))
        ET.SubElement(line, "PONumber").text = extracted.get('po_number', '')
        
        return ET.tostring(invoice, encoding='unicode', method='xml')

    def _map_to_dynamics_json(self, invoice_data: Dict[str, Any]) -> str:
        """Map invoice data to Dynamics 365 JSON format"""
        extracted = invoice_data.get('extracted_fields', {})
        
        dynamics_data = {
            "dataAreaId": "USMF",
            "InvoiceAccount": extracted.get('vendor_id', ''),
            "InvoiceDate": extracted.get('invoice_date', ''),
            "DueDate": extracted.get('due_date', ''),
            "DocumentDate": extracted.get('invoice_date', ''),
            "InvoiceId": extracted.get('invoice_number', ''),
            "PurchaseOrder": extracted.get('po_number', ''),
            "Lines": [{
                "LineNumber": 1,
                "ItemId": "SERVICE",
                "Name": "Invoice Processing Service",
                "Quantity": 1,
                "UnitPrice": extracted.get('total_amount', 0),
                "LineAmount": extracted.get('total_amount', 0)
            }]
        }
        
        return json.dumps(dynamics_data, indent=2)

    def _call_erp_api(self, erp_system: str, mapped_data: str, data_format: str) -> Dict[str, Any]:
        """Mock ERP API call - in production, this would make actual HTTP requests"""
        try:
            # Simulate API call
            import time
            time.sleep(0.5)  # Simulate network delay
            
            # Mock success response
            if erp_system in self.erp_systems:
                return {
                    'success': True,
                    'erp_system': erp_system,
                    'transaction_id': f"ERP-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    'status': 'posted',
                    'message': f'Invoice successfully posted to {self.erp_systems[erp_system]["type"]}'
                }
            else:
                return {
                    'success': False,
                    'error': f'Unsupported ERP system: {erp_system}'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'ERP API call failed: {str(e)}'
            }

    def _validate_erp_mapping(self, mapped_data: str, data_format: str) -> Dict[str, Any]:
        """Validate the mapped ERP data"""
        validation_result = {
            'valid': True,
            'warnings': [],
            'errors': []
        }
        
        try:
            if data_format == 'xml':
                # Validate XML structure
                ET.fromstring(mapped_data)
            elif data_format == 'json':
                # Validate JSON structure
                json.loads(mapped_data)
            elif data_format == 'idoc':
                # IDoc is XML-based
                ET.fromstring(mapped_data)
        except Exception as e:
            validation_result['valid'] = False
            validation_result['errors'].append(f'Invalid {data_format} format: {str(e)}')
        
        return validation_result

    async def process(self, context: ProcessingContext) -> AgentResult:
        try:
            # Determine target ERP system (default to SAP)
            erp_system = context.erp_data.get('target_system', 'sap')
            
            if erp_system not in self.erp_systems:
                return self.create_result(
                    status='error',
                    data={'error': f'Unsupported ERP system: {erp_system}'},
                    confidence=0.0,
                    message=f'ERP system {erp_system} is not supported',
                    next_agent=None
                )
            
            erp_config = self.erp_systems[erp_system]
            
            # Map data to ERP format
            if erp_config['format'] == 'idoc':
                mapped_data = self._map_to_sap_idoc(context.extracted_data)
            elif erp_config['format'] == 'xml':
                mapped_data = self._map_to_oracle_xml(context.extracted_data)
            elif erp_config['format'] == 'json':
                mapped_data = self._map_to_dynamics_json(context.extracted_data)
            else:
                mapped_data = json.dumps(context.extracted_data, indent=2)
            
            # Validate mapping
            validation = self._validate_erp_mapping(mapped_data, erp_config['format'])
            
            if not validation['valid']:
                return self.create_result(
                    status='error',
                    data={
                        'error': 'ERP mapping validation failed',
                        'validation_errors': validation['errors']
                    },
                    confidence=0.0,
                    message='ERP data mapping validation failed',
                    next_agent=None
                )
            
            # Call ERP API
            api_result = self._call_erp_api(erp_system, mapped_data, erp_config['format'])
            
            if api_result['success']:
                result_data = {
                    'erp_system': erp_system,
                    'transaction_id': api_result.get('transaction_id'),
                    'mapped_data': mapped_data,
                    'api_response': api_result,
                    'integration_status': 'success'
                }
                
                return self.create_result(
                    status='success',
                    data=result_data,
                    confidence=0.9,
                    message=f'Invoice successfully integrated with {erp_config["type"]}',
                    next_agent='Audit & Logging Agent'
                )
            else:
                return self.create_result(
                    status='error',
                    data={
                        'error': api_result.get('error', 'Unknown ERP error'),
                        'erp_system': erp_system,
                        'mapped_data': mapped_data
                    },
                    confidence=0.0,
                    message=f'ERP integration failed: {api_result.get("error", "Unknown error")}',
                    next_agent='Exception Handling Agent'
                )

        except Exception as e:
            self.logger.error(f"ERP integration failed: {e}")
            return self.create_result(
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                message=f"ERP integration failed: {str(e)}",
                next_agent=None
            )
