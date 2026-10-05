"""
Intelligent Invoice Processing Agents
=====================================

This module implements the 6 specialized agents for intelligent invoice processing:

1. Data Extraction Agent - Extracts structured fields from OCR text
2. Validation Agent - Validates extracted data against ERP rules
3. Exception Handling Agent - Handles errors and user interactions
4. ERP Integration Agent - Integrates with ERP systems
5. Audit & Logging Agent - Maintains compliance and traceability
6. MCP Orchestrator Agent - Coordinates the entire pipeline
"""

from abc import ABC, abstractmethod
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import asyncio
from dataclasses import dataclass


@dataclass
class AgentResult:
    """Standardized result format for all agents"""
    agent_name: str
    status: str  # 'success', 'error', 'waiting', 'processing'
    data: Dict[str, Any]
    confidence: float
    timestamp: datetime
    message: str
    next_agent: Optional[str] = None
    requires_user_input: bool = False
    user_question: Optional[str] = None


@dataclass
class ProcessingContext:
    """Context shared between agents during processing"""
    invoice_path: str
    extracted_data: Dict[str, Any]
    validation_errors: List[str]
    processing_history: List[AgentResult]
    user_responses: Dict[str, Any]
    session_id: str
    # Additional fields for MCP Orchestrator
    invoice_id: Optional[str] = None
    original_file: Optional[str] = None
    ocr_text: Optional[str] = None
    validation_results: Optional[Dict[str, Any]] = None
    erp_data: Optional[Dict[str, Any]] = None
    audit_log: Optional[List[Dict[str, Any]]] = None
    current_stage: Optional[str] = None


class BaseAgent(ABC):
    """Abstract base class for all invoice processing agents"""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    async def process(self, context: ProcessingContext) -> AgentResult:
        """Process the invoice data and return results"""
        pass

    def create_result(self,
                     status: str,
                     data: Dict[str, Any],
                     confidence: float,
                     message: str,
                     next_agent: Optional[str] = None,
                     requires_user_input: bool = False,
                     user_question: Optional[str] = None) -> AgentResult:
        """Create a standardized agent result"""
        return AgentResult(
            agent_name=self.name,
            status=status,
            data=data,
            confidence=confidence,
            timestamp=datetime.now(),
            message=message,
            next_agent=next_agent,
            requires_user_input=requires_user_input,
            user_question=user_question
        )