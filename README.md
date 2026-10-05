# GenAI Invoice Processing System

An intelligent invoice processing system powered by AI agents that automatically extracts, validates, and processes invoice data using advanced machine learning models and a multi-agent orchestrator architecture.

## Features

- **Multi-Agent AI Processing**: 6 specialized AI agents work together to process invoices
- **OCR Integration**: Supports multiple OCR engines (Tesseract, EasyOCR) for text extraction
- **AI-Powered Data Extraction**: Uses spaCy NER and BERT transformers for intelligent field extraction
- **Real-time Dashboard**: Web-based interface with real-time processing status updates
- **ERP Integration**: Ready for integration with enterprise systems
- **Compliance Checking**: Automated compliance validation for processed invoices
- **Thread-Safe Processing**: Database-backed session management for concurrent processing

## Architecture

The system consists of 6 specialized agents coordinated by an MCP Orchestrator:

1. **OCR Agent**: Extracts text from invoice images/PDFs using multiple OCR engines
2. **Data Extraction Agent**: Uses AI models (spaCy NER + BERT) to identify and extract key fields
3. **Validation Agent**: Validates extracted data against business rules and cross-field consistency
4. **ERP Integration Agent**: Prepares and formats data for ERP system integration
5. **Compliance Agent**: Checks regulatory compliance and audit requirements
6. **MCP Orchestrator**: Coordinates all agents, manages workflow, and handles error recovery

## Tech Stack

- **Backend**: Python 3.8+, Django 4.2, Django REST Framework
- **AI/ML**: HuggingFace Transformers (BERT NER), spaCy, EasyOCR, Tesseract
- **Computer Vision**: OpenCV for image preprocessing
- **Database**: PostgreSQL (production) / SQLite (development)
- **Queue**: Redis, Celery for async processing (optional)
- **Frontend**: Django Templates, Bootstrap 5, JavaScript
- **Deployment**: Docker, docker-compose for containerization

## Prerequisites

- Python 3.8+
- PostgreSQL (recommended) or SQLite
- Tesseract OCR (for enhanced OCR capabilities)
- Poppler (for PDF processing)

## Installation

1. **Clone the repository** (if applicable) or ensure you have the project files

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Download AI models** (optional but recommended):
   ```bash
   python -m spacy download en_core_web_sm
   ```

5. **Database setup**:
   - For PostgreSQL: Update `DATABASES` in `settings.py`
   - For SQLite: Default configuration works out of the box

6. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

7. **Create superuser** (optional):
   ```bash
   python manage.py createsuperuser
   ```

## Usage

1. **Start the development server**:
   ```bash
   python manage.py runserver
   ```

2. **Access the dashboard**:
   - Open http://127.0.0.1:8000/dashboard/ in your browser

3. **Process an invoice**:
   - Upload an invoice PDF/image through the web interface
   - Watch real-time processing through the agent dashboard
   - View extracted data and processing results

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```env
DEBUG=True
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
REDIS_URL=redis://localhost:6379/0
```

### AI Model Configuration

The system uses the following AI models:
- **spaCy NER**: `en_core_web_sm` for named entity recognition
- **BERT NER**: `dbmdz/bert-large-cased-finetuned-conll03-english` for advanced entity extraction

Models are loaded lazily to optimize memory usage.

## API Endpoints

- `POST /api/process-invoice/`: Upload and process an invoice
- `GET /api/processing-status/<session_id>/`: Check processing status
- `GET /dashboard/`: Web dashboard interface

## Production Deployment

### Using Celery (Recommended for production)

1. **Install Redis**:
   ```bash
   # Using Docker
   docker run -d -p 6379:6379 redis:alpine
   ```

2. **Start Celery worker**:
   ```bash
   celery -A invoice_processor worker --loglevel=info
   ```

3. **Start Celery beat** (for scheduled tasks):
   ```bash
   celery -A invoice_processor beat --loglevel=info
   ```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "invoice_processor.wsgi:application", "--bind", "0.0.0.0:8000"]
```

## Troubleshooting

### Common Issues

1. **AI models not loading**:
   - Ensure internet connection for first-time model downloads
   - Check available disk space (models can be several GB)

2. **OCR not working**:
   - Install Tesseract: `choco install tesseract` (Windows)
   - Install Poppler for PDF processing

3. **Database connection errors**:
   - Verify database credentials in settings.py
   - Ensure PostgreSQL service is running

4. **Memory issues**:
   - Reduce batch size in agent configurations
   - Use Celery for background processing

### Performance Optimization

- Use PostgreSQL instead of SQLite for production
- Enable Redis caching for session data
- Configure Celery for distributed processing
- Use GPU acceleration for AI models (if available)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is proprietary software. All rights reserved.

## Support

For support and questions, please contact the development team.
## Processing Flow

1. **Upload**: Invoice uploaded via web dashboard or API
2. **Agent Coordination**: MCP Orchestrator initializes processing session
3. **OCR Processing**: OCR Agent extracts text using Tesseract/EasyOCR
4. **AI Extraction**: Data Extraction Agent uses spaCy + BERT for field identification
5. **Validation**: Validation Agent checks data consistency and business rules
6. **ERP Preparation**: ERP Integration Agent formats data for enterprise systems
7. **Compliance Check**: Compliance Agent verifies regulatory requirements
8. **Results**: Structured data saved with confidence scores and session tracking

## Agent Details

### OCR Agent
- **Input**: Invoice PDF/image files
- **Processing**: Multi-engine OCR (Tesseract + EasyOCR) with confidence scoring
- **Output**: Extracted text with layout information

### Data Extraction Agent
- **Input**: OCR text from OCR Agent
- **Processing**: AI-powered field extraction using spaCy NER and BERT transformers
- **Output**: Structured invoice fields (vendor, amounts, dates, line items) with confidence scores

### Validation Agent
- **Input**: Extracted data from Data Extraction Agent
- **Processing**: Cross-field validation, business rule checking, data consistency
- **Output**: Validation results with error flags and correction suggestions

### ERP Integration Agent
- **Input**: Validated data from Validation Agent
- **Processing**: Data formatting and mapping for ERP system integration
- **Output**: ERP-ready data structures

### Compliance Agent
- **Input**: Processed invoice data
- **Processing**: Regulatory compliance checking, audit trail generation
- **Output**: Compliance status and audit logs

### MCP Orchestrator
- **Function**: Coordinates all agents, manages session state, handles errors
- **Features**: Thread-safe session management, real-time status updates, error recovery