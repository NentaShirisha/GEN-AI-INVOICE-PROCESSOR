"""
Audit & Logging Agent
=====================

Goal: Maintain full traceability for compliance.

Input: Logs from all agents
Process:
- LLM summarizes anomalies, user interventions, processing time
- Generates compliance-ready reports

Output: Audit JSON + human-readable summary

Design Choices:
- LLM: Small summarization model (distilBART, GPT-3.5-level)
- Example output: "Invoice INV-45678 flagged for Vendor mismatch, corrected by user  posted successfully."
"""

import json
from typing import Dict, Any, List
from datetime import datetime
from .base_agent import BaseAgent, AgentResult, ProcessingContext

class AuditLoggingAgent(BaseAgent):
    def __init__(self):
        super().__init__("Audit & Logging Agent")

    def _calculate_processing_metrics(self, processing_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate processing time and performance metrics"""
        if not processing_history:
            return {}
        
        start_time = None
        end_time = None
        agent_times = {}
        
        for result in processing_history:
            timestamp = result.get('timestamp')
            agent_name = result.get('agent_name', 'Unknown')
            
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            if start_time is None or timestamp < start_time:
                start_time = timestamp
            if end_time is None or timestamp > end_time:
                end_time = timestamp
            
            if agent_name not in agent_times:
                agent_times[agent_name] = []
            agent_times[agent_name].append(timestamp)
        
        total_time = (end_time - start_time).total_seconds() if start_time and end_time else 0
        
        return {
            'total_processing_time_seconds': total_time,
            'start_time': start_time.isoformat() if start_time else None,
            'end_time': end_time.isoformat() if end_time else None,
            'agents_executed': list(agent_times.keys()),
            'agent_count': len(agent_times)
        }

    def _analyze_anomalies(self, processing_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze processing history for anomalies and issues"""
        anomalies = []
        
        for result in processing_history:
            status = result.get('status', 'unknown')
            confidence = result.get('confidence', 1.0)
            agent_name = result.get('agent_name', 'Unknown')
            
            # Check for errors
            if status == 'error':
                anomalies.append({
                    'type': 'error',
                    'severity': 'high',
                    'agent': agent_name,
                    'message': result.get('message', 'Unknown error'),
                    'timestamp': result.get('timestamp')
                })
            
            # Check for low confidence
            elif confidence < 0.5:
                anomalies.append({
                    'type': 'low_confidence',
                    'severity': 'medium',
                    'agent': agent_name,
                    'confidence': confidence,
                    'message': f'Low confidence score: {confidence:.2%}',
                    'timestamp': result.get('timestamp')
                })
            
            # Check for user interactions
            elif status == 'needs_interaction':
                anomalies.append({
                    'type': 'user_interaction',
                    'severity': 'low',
                    'agent': agent_name,
                    'message': 'Required user input for processing',
                    'timestamp': result.get('timestamp')
                })
        
        return anomalies

    def _generate_compliance_report(self, context: ProcessingContext, 
                                  metrics: Dict[str, Any], 
                                  anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate compliance-ready audit report"""
        
        # Get extracted fields - handle different data structures
        extracted_fields = {}
        if hasattr(context, 'extracted_data') and context.extracted_data:
            if isinstance(context.extracted_data, dict):
                if 'extracted_fields' in context.extracted_data:
                    extracted_fields = context.extracted_data['extracted_fields']
                else:
                    extracted_fields = context.extracted_data
        
        report = {
            'audit_header': {
                'invoice_id': context.invoice_id,
                'original_file': context.original_file,
                'processing_date': datetime.now().isoformat(),
                'compliance_standard': 'SOX_AI_Processing_v1.0'
            },
            'processing_summary': {
                'total_agents': len(context.processing_history),
                'successful_agents': sum(1 for r in context.processing_history if r.get('status') == 'success'),
                'failed_agents': sum(1 for r in context.processing_history if r.get('status') == 'error'),
                'user_interactions': sum(1 for r in context.processing_history if r.get('status') == 'needs_interaction'),
                'processing_time_seconds': metrics.get('total_processing_time_seconds', 0)
            },
            'invoice_data': {
                'invoice_number': extracted_fields.get('invoice_number'),
                'vendor_name': extracted_fields.get('vendor_name'),
                'vendor_id': extracted_fields.get('vendor_id'),
                'po_number': extracted_fields.get('po_number'),
                'total_amount': extracted_fields.get('total_amount'),
                'invoice_date': extracted_fields.get('invoice_date'),
                'final_status': 'processed' if not anomalies else 'flagged_for_review'
            },
            'anomalies': anomalies,
            'agent_history': context.processing_history,
            'validation_results': context.validation_results,
            'erp_integration': context.erp_data
        }
        
        return report

    def _generate_human_readable_summary(self, report: Dict[str, Any]) -> str:
        """Generate human-readable summary of the audit"""
        summary_parts = []
        
        # Header
        invoice_num = report['invoice_data'].get('invoice_number', 'Unknown')
        summary_parts.append(f" Audit Summary for Invoice {invoice_num}")
        summary_parts.append("=" * 50)
        
        # Processing overview
        proc = report['processing_summary']
        summary_parts.append(f"  Processing Time: {proc['processing_time_seconds']:.1f} seconds")
        summary_parts.append(f" Agents Executed: {proc['total_agents']} total")
        summary_parts.append(f" Successful: {proc['successful_agents']}")
        
        if proc['failed_agents'] > 0:
            summary_parts.append(f" Failed: {proc['failed_agents']}")
        
        if proc['user_interactions'] > 0:
            summary_parts.append(f" User Interactions: {proc['user_interactions']}")
        
        # Invoice details
        inv = report['invoice_data']
        summary_parts.append(f"\n Invoice Details:")
        summary_parts.append(f"   Vendor: {inv.get('vendor_name', 'Unknown')}")
        summary_parts.append(f"   Amount: ")
        summary_parts.append(f"   Date: {inv.get('invoice_date', 'Unknown')}")
        summary_parts.append(f"   PO: {inv.get('po_number', 'N/A')}")
        
        # Anomalies
        anomalies = report['anomalies']
        if anomalies:
            summary_parts.append(f"\n  Issues Found: {len(anomalies)}")
            for anomaly in anomalies:
                severity_icon = {'high': '', 'medium': '', 'low': ''}.get(anomaly['severity'], '')
                summary_parts.append(f"   {severity_icon} {anomaly['type'].replace('_', ' ').title()}: {anomaly['message']}")
        else:
            summary_parts.append(f"\n No anomalies detected")
        
        # Final status
        status = report['invoice_data']['final_status']
        if status == 'processed':
            summary_parts.append(f"\n Final Status: Successfully Processed")
        else:
            summary_parts.append(f"\n  Final Status: Flagged for Review")
        
        return "\n".join(summary_parts)

    async def process(self, context: ProcessingContext) -> AgentResult:
        try:
            # Get extracted fields for final structured invoice
            extracted_fields = {}
            if hasattr(context, 'extracted_data') and context.extracted_data:
                if isinstance(context.extracted_data, dict):
                    if 'extracted_fields' in context.extracted_data:
                        extracted_fields = context.extracted_data['extracted_fields']
                    else:
                        extracted_fields = context.extracted_data
            
            # Extract key fields for output
            invoice_no = (extracted_fields.get('invoice_number') or 
                         extracted_fields.get('invoice_no') or 
                         extracted_fields.get('Invoice_No') or 
                         'N/A')
            vendor_id = (extracted_fields.get('vendor_id') or 
                        extracted_fields.get('vendor_ID') or 
                        extracted_fields.get('Vendor_ID') or
                        extracted_fields.get('vendor_name') or
                        'N/A')
            po_no = (extracted_fields.get('po_number') or 
                    extracted_fields.get('PO_No') or 
                    extracted_fields.get('po_number') or
                    'N/A')
            
            # Calculate processing metrics
            metrics = self._calculate_processing_metrics(context.processing_history)
            
            # Analyze anomalies
            anomalies = self._analyze_anomalies(context.processing_history)
            
            # Generate compliance report
            compliance_report = self._generate_compliance_report(context, metrics, anomalies)
            
            # Generate human-readable summary
            human_summary = self._generate_human_readable_summary(compliance_report)
            
            # Build final structured invoice
            final_structured_invoice = {
                'Invoice_No': invoice_no,
                'Vendor_ID': vendor_id,
                'PO_No': po_no,
                'Invoice_Date': extracted_fields.get('invoice_date') or extracted_fields.get('date') or 'N/A',
                'Total_Amount': extracted_fields.get('total_amount') or extracted_fields.get('amount') or 'N/A',
                'Currency': extracted_fields.get('currency') or 'USD',
                'Status': compliance_report['invoice_data'].get('final_status', 'processed')
            }
            
            # Build end-to-end process log
            process_log = []
            for i, history_item in enumerate(context.processing_history, 1):
                process_log.append({
                    'step': i,
                    'agent': history_item.get('agent_name', 'Unknown'),
                    'status': history_item.get('status', 'unknown'),
                    'timestamp': history_item.get('timestamp', ''),
                    'message': history_item.get('message', ''),
                    'confidence': history_item.get('confidence', 0)
                })
            
            result_data = {
                'audit_output': {
                    'Final_Structured_Invoice': final_structured_invoice,
                    'End_to_End_Process_Log': process_log,
                    'Processing_Summary': {
                        'Total_Agents': len(context.processing_history),
                        'Successful': sum(1 for r in context.processing_history if r.get('status') == 'success'),
                        'Failed': sum(1 for r in context.processing_history if r.get('status') == 'error'),
                        'Processing_Time_Seconds': metrics.get('total_processing_time_seconds', 0),
                        'Anomalies_Count': len(anomalies)
                    }
                },
                'compliance_report': compliance_report,
                'human_readable_summary': human_summary,
                'processing_metrics': metrics,
                'anomalies_count': len(anomalies),
                'audit_complete': True
            }
            
            # Determine confidence based on anomalies
            confidence = 0.9 if not anomalies else 0.7
            
            return self.create_result(
                status='success',
                data=result_data,
                confidence=confidence,
                message=f'Audit completed with {len(anomalies)} anomalies detected',
                next_agent=None  # Pipeline complete
            )

        except Exception as e:
            self.logger.error(f"Audit logging failed: {e}")
            return self.create_result(
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                message=f"Audit logging failed: {str(e)}",
                next_agent=None
            )
