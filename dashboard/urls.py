from django.urls import path
from . import views
from . import processing_views

urlpatterns = [
    # Main Dashboard
    path('', views.agent_dashboard_view, name='dashboard'),
    path('legacy/', views.dashboard_view, name='legacy_dashboard'),
    
    # ==================== TRACKING & HISTORY ====================
    path('tracking/', processing_views.invoice_tracking_list, name='tracking_list'),
    path('tracking/<str:session_id>/', processing_views.invoice_detail_tracking, name='tracking_detail'),
    
    # ==================== RUN MODELS PAGE ====================
    path('run-models/', processing_views.run_models_page, name='run_models_page'),
    
    # ==================== Q&A ANALYSIS PAGE ====================
    path('qa-analysis/', processing_views.qa_analysis_page, name='qa_analysis_page'),
    
    # ==================== SEPARATE PROCESSING PAGES ====================
    # Upload Page
    path('upload-page/', processing_views.upload_invoice_page, name='upload_page'),
    
    # OCR Processing Page
    path('ocr/<str:session_id>/', processing_views.ocr_processing_page, name='ocr_processing_page'),
    path('ocr/<str:session_id>/process/', processing_views.process_ocr, name='process_ocr'),
    
    # Data Extraction Page
    path('extraction/<str:session_id>/', processing_views.extraction_processing_page, name='extraction_processing_page'),
    path('extraction/<str:session_id>/process/', processing_views.process_extraction, name='process_extraction_action'),
    
    # Validation Page
    path('validation/<str:session_id>/', processing_views.validation_processing_page, name='validation_processing_page'),
    path('validation/<str:session_id>/process/', processing_views.process_validation, name='process_validation_action'),
    
    # Exception Handling Page
    path('exception/<str:session_id>/', processing_views.exception_processing_page, name='exception_processing_page'),
    path('exception/<str:session_id>/process/', processing_views.process_exception, name='process_exception_action'),
    
    # ERP Integration Page
    path('erp/<str:session_id>/', processing_views.erp_processing_page, name='erp_processing_page'),
    path('erp/<str:session_id>/process/', processing_views.process_erp, name='process_erp_action'),
    
    # Audit Logging Page
    path('audit/<str:session_id>/', processing_views.audit_processing_page, name='audit_processing_page'),
    path('audit/<str:session_id>/process/', processing_views.process_audit, name='process_audit_action'),
    
    # ==================== OLD ENDPOINTS (Legacy) ====================
    path('upload/', views.process_invoice_with_agents, name='upload_invoice'),
    path('process-agents/', views.process_invoice_with_agents, name='process_agents'),
    # Processing status endpoint
    path('processing-status/<str:session_id>/', views.check_processing_status, name='processing_status'),
    # Agent readiness endpoint
    path('agent-readiness/', views.check_agent_readiness, name='agent_readiness'),
    # Individual agent endpoints
    path('process-extraction/', views.process_data_extraction, name='process_extraction'),
    path('process-validation/', views.process_validation, name='process_validation'),
    path('process-exception/', views.process_exception_handling, name='process_exception'),
    path('process-erp/', views.process_erp_integration, name='process_erp'),
    path('process-audit/', views.process_audit_logging, name='process_audit'),
    # Q&A endpoint
    path('analyze-agent-outputs/', views.analyze_agent_outputs, name='analyze_agent_outputs'),
]