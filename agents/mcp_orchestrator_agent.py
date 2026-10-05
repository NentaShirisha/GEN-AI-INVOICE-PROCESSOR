"""
MCP Orchestrator Agent (Controller)
==================================

Goal: Route tasks across all agents.

Input: New invoice event
Process:
- Calls extraction  validation  exception handling  ERP integration
- Tracks pipeline state

Output: End-to-end workflow result

Design Choices:
- LLM: Lightweight controller (can even be rule-based, doesn't need training)
- Orchestration: LangGraph / MCP agent framework
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime
from .base_agent import BaseAgent, AgentResult, ProcessingContext
from .data_extraction_agent import DataExtractionAgent
from .validation_agent import ValidationAgent
from .exception_handling_agent import ExceptionHandlingAgent
from .erp_integration_agent import ERPIntegrationAgent
from .audit_logging_agent import AuditLoggingAgent

class MCPOrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__("MCP Orchestrator Agent")
        self.agents = {
            'Data Extraction Agent': DataExtractionAgent(),
            'Validation Agent': ValidationAgent(),
            'Exception Handling Agent': ExceptionHandlingAgent(),
            'ERP Integration Agent': ERPIntegrationAgent(),
            'Audit & Logging Agent': AuditLoggingAgent()
        }
        
        # Define the processing pipeline
        self.pipeline = [
            'Data Extraction Agent',
            'Validation Agent',
            'Exception Handling Agent',
            'ERP Integration Agent',
            'Audit & Logging Agent'
        ]

    def _create_processing_context(self, invoice_id: str, ocr_text: str, 
                                 original_file: str) -> ProcessingContext:
        """Create initial processing context"""
        return ProcessingContext(
            invoice_path=original_file,
            extracted_data={},
            validation_errors=[],
            processing_history=[],
            user_responses={},
            session_id=f"session_{invoice_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            invoice_id=invoice_id,
            original_file=original_file,
            ocr_text=ocr_text,
            validation_results={},
            erp_data={},
            audit_log=[],
            current_stage='initialization'
        )

    def _update_context_with_result(self, context: ProcessingContext, 
                                  result: AgentResult) -> ProcessingContext:
        """Update processing context with agent result"""
        
        # Add to processing history (serialize the result to avoid circular references)
        context.processing_history.append({
            'agent_name': result.agent_name,
            'status': result.status,
            'confidence': result.confidence,
            'timestamp': result.timestamp.isoformat(),
            'message': result.message,
            'data': result.data,  # Keep data as dict
            'next_agent': result.next_agent,
            'requires_user_input': result.requires_user_input,
            'user_question': result.user_question
        })
        
        # Update context data based on agent type
        if result.agent_name == 'Data Extraction Agent':
            # Extract individual fields from the extracted_fields dictionary
            extracted_fields = result.data.get('extracted_fields', {})
            context.extracted_data.update(extracted_fields)
            context.current_stage = 'extraction_complete'
            
        elif result.agent_name == 'Validation Agent':
            context.validation_results = result.data.get('validation_results', {})
            context.current_stage = 'validation_complete'
            
        elif result.agent_name == 'Exception Handling Agent':
            if result.data.get('corrected_data'):
                context.extracted_data = result.data['corrected_data']
            context.current_stage = 'exceptions_handled'
            
        elif result.agent_name == 'ERP Integration Agent':
            context.erp_data = result.data
            context.current_stage = 'erp_integration_complete'
            
        elif result.agent_name == 'Audit & Logging Agent':
            context.audit_log = result.data
            context.current_stage = 'audit_complete'
        
        return context

    def _determine_next_agent(self, current_result: AgentResult, 
                            context: ProcessingContext) -> Optional[str]:
        """Determine which agent to call next based on current result"""
        
        if current_result.next_agent:
            return current_result.next_agent
        
        # Rule-based fallback logic
        if current_result.status == 'error':
            return 'Exception Handling Agent'
        
        elif current_result.status == 'needs_interaction':
            return 'Exception Handling Agent'
        
        # Continue with pipeline
        current_index = self.pipeline.index(current_result.agent_name) if current_result.agent_name in self.pipeline else -1
        
        if current_index >= 0 and current_index < len(self.pipeline) - 1:
            return self.pipeline[current_index + 1]
        
        return None

    def _should_retry_validation(self, context: ProcessingContext) -> bool:
        """Check if validation should be retried after exception handling"""
        # If we just handled exceptions and have corrected data, retry validation
        last_result = context.processing_history[-1] if context.processing_history else None
        
        if (last_result and 
            last_result['agent_name'] == 'Exception Handling Agent' and
            last_result['status'] == 'success'):
            return True
        
        return False

    async def _execute_agent(self, agent_name: str, context: ProcessingContext) -> AgentResult:
        """Execute a specific agent"""
        if agent_name not in self.agents:
            return AgentResult(
                agent_name=agent_name,
                status='error',
                data={'error': f'Agent {agent_name} not found'},
                confidence=0.0,
                timestamp=datetime.now(),
                message=f'Agent {agent_name} not found'
            )
        
        agent = self.agents[agent_name]
        
        try:
            self.logger.info(f"Executing agent: {agent_name}")
            result = await agent.process(context)
            self.logger.info(f"Agent {agent_name} completed with status: {result.status}")
            return result
            
        except Exception as e:
            self.logger.error(f"Agent {agent_name} execution failed: {e}")
            return AgentResult(
                agent_name=agent_name,
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                timestamp=datetime.now(),
                message=f'Agent execution failed: {str(e)}'
            )

    async def process_invoice_pipeline(self, invoice_id: str, ocr_text: str, 
                                     original_file: str) -> Dict[str, Any]:
        """Execute the complete invoice processing pipeline"""
        
        # Initialize context
        context = self._create_processing_context(invoice_id, ocr_text, original_file)
        
        current_agent = 'Data Extraction Agent'
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        while current_agent and iteration < max_iterations:
            iteration += 1
            self.logger.info(f"Pipeline iteration {iteration}: Calling {current_agent}")
            
            # Special handling for retry validation
            if self._should_retry_validation(context) and current_agent == 'Exception Handling Agent':
                current_agent = 'Validation Agent'
            
            # Execute agent
            result = await self._execute_agent(current_agent, context)
            
            # Update context
            context = self._update_context_with_result(context, result)
            
            # Determine next agent
            current_agent = self._determine_next_agent(result, context)
            
            # Break if we need user interaction
            if result.requires_user_input:
                break
        
        # Prepare final result
        final_status = 'completed'
        if any(r['status'] == 'error' for r in context.processing_history):
            final_status = 'failed'
        elif any(r['status'] == 'needs_interaction' for r in context.processing_history):
            final_status = 'waiting_for_user'
        
        return {
            'invoice_id': invoice_id,
            'status': final_status,
            'processing_history': context.processing_history,
            'final_context': {
                'extracted_data': context.extracted_data,
                'validation_results': context.validation_results,
                'erp_data': context.erp_data,
                'audit_log': context.audit_log,
                'current_stage': context.current_stage
            },
            'total_iterations': iteration,
            'requires_user_input': any(r.get('requires_user_input', False) for r in context.processing_history[-1:]),
            'user_question': context.processing_history[-1].get('user_question') if context.processing_history else None
        }

    async def process(self, context: ProcessingContext) -> AgentResult:
        """Main orchestrator process - this is called when the pipeline is complete"""
        try:
            # This agent is typically called at the end of the pipeline
            # It summarizes the entire processing workflow
            
            processing_summary = {
                'total_agents_executed': len(context.processing_history),
                'successful_operations': sum(1 for r in context.processing_history if r.get('status') == 'success'),
                'failed_operations': sum(1 for r in context.processing_history if r.get('status') == 'error'),
                'user_interactions': sum(1 for r in context.processing_history if r.get('status') == 'needs_interaction'),
                'pipeline_completion': 'full' if context.current_stage == 'audit_complete' else 'partial'
            }
            
            # Calculate overall confidence
            confidences = [r.get('confidence', 0) for r in context.processing_history]
            overall_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            message = f"Pipeline orchestration completed: {processing_summary['successful_operations']}/{processing_summary['total_agents_executed']} agents successful"
            
            return self.create_result(
                status='success',
                data={
                    'orchestration_summary': processing_summary,
                    'final_processing_context': {
                        'extracted_data': context.extracted_data,
                        'validation_results': context.validation_results,
                        'erp_data': context.erp_data,
                        'audit_log': context.audit_log
                    }
                },
                confidence=overall_confidence,
                message=message,
                next_agent=None  # End of pipeline
            )

        except Exception as e:
            self.logger.error(f"Orchestrator failed: {e}")
            return self.create_result(
                status='error',
                data={'error': str(e)},
                confidence=0.0,
                message=f"Pipeline orchestration failed: {str(e)}",
                next_agent=None
            )
