# 🚀 Automation Dashboard API

A unified FastAPI application that consolidates multiple automation services for image processing, masking, workflows, renaming, and prompt generation.

## 🏗️ Architecture

This project consolidates four previously separate APIs into one unified application:

- **Image Masking API** - ComfyUI-based image masking
- **Workflow Processing API** - Background change workflows
- **Image Renaming API** - Face detection and renaming
- **Prompt Generation API** - Fashion image analysis and prompts

## 📁 Project Structure

```
Automation Dashboard API/
├── main.py                    # 🎯 Unified FastAPI application
├── routes/                    # 🛣️ API route handlers
│   ├── __init__.py
│   ├── health.py             # Health check endpoints
│   ├── mask.py               # Image masking endpoints
│   ├── workflow.py           # Workflow processing endpoints
│   ├── rename.py             # Image renaming endpoints
│   └── promptmap.py          # Prompt generation endpoints
├── services/                  # ⚙️ Business logic services
│   ├── __init__.py
│   ├── mask_service.py       # Mask processing logic
│   ├── workflow_service.py   # Workflow processing logic
│   ├── rename_service.py     # Face detection logic
│   └── promptmap_service.py  # OpenAI integration logic
├── database/                  # 🗄️ Database layer (ready for future use)
│   └── __init__.py
├── requirements.txt           # 📦 Unified dependencies
├── README.md                  # 📖 This file
└── [Original API folders]     # 📂 Supporting files and configurations
    ├── Mask n8n Working/
    ├── Final Workflow n8n Working/
    ├── Rename n8n Working/
    └── PromptMap n8n Working/
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Environment Variables

Create a `.env` file in the root directory:

```env
# OpenAI API Key (for PromptMap service)
OPENAI_API_KEY=your-actual-api-key-here

# Mask API Configuration
WORKFLOW_JSON=Mask n8n Working/JSON.json
INPUT_NODE_ID=54
OUTPUT_NODE_ID=455
```

### 3. Run the Unified API

```bash
python3 main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Access the API

- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health
- **Root Info**: http://localhost:8000/

## 🎯 API Endpoints

### Health Check
- `GET /api/health/health` - Service health status

### Image Masking
- `GET /api/mask/health` - Mask service health
- `POST /api/mask/mask` - Process image masking

### Workflow Processing
- `GET /api/workflow/health` - Workflow service health
- `POST /api/workflow/process_images` - Process workflow images
- `GET /api/workflow/status/{task_id}` - Check task status
- `GET /api/workflow/download/{task_id}` - Download results

### Image Renaming
- `GET /api/rename/health` - Rename service health
- `POST /api/rename/process` - Process image renaming

### Prompt Generation
- `GET /api/promptmap/` - PromptMap service info
- `GET /api/promptmap/health` - PromptMap service health
- `POST /api/promptmap/process-images` - Generate prompts from images

## 🔧 Configuration

### Service-Specific Configuration

Each service maintains its original configuration files in their respective folders:

- **Mask API**: `Mask n8n Working/JSON.json`
- **Workflow API**: `Final Workflow n8n Working/Comfi_workflow.json`
- **PromptMap API**: `PromptMap n8n Working/promptlib.json`

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key for prompt generation | Required |
| `WORKFLOW_JSON` | Path to mask workflow JSON | `Mask n8n Working/JSON.json` |
| `INPUT_NODE_ID` | ComfyUI input node ID | `54` |
| `OUTPUT_NODE_ID` | ComfyUI output node ID | `455` |

## 🧪 Testing

### Test Individual Services

```bash
# Test route imports
python3 -c "from routes import mask, health, workflow, rename, promptmap; print('All routes imported successfully')"

# Test main application
python3 -c "import main; print('Main app imported successfully')"
```

### Test API Endpoints

1. Start the server: `python3 main.py`
2. Open http://localhost:8000/docs
3. Test endpoints using the interactive Swagger UI

## 🔄 Migration from Separate APIs

If you were previously using the separate API projects:

### Old Structure (Separate APIs)
```bash
# Old way - separate servers
cd "Mask n8n Working"
uvicorn main:app --reload --port 8000

cd "Final Workflow n8n Working"  
uvicorn main:app --reload --port 8001

cd "Rename n8n Working"
uvicorn main:app --reload --port 8002

cd "PromptMap n8n Working"
uvicorn main:app --reload --port 8003
```

### New Structure (Unified API)
```bash
# New way - single server
cd "Automation Dashboard API"
python3 main.py
# All services accessible through different route prefixes
```

## 🌟 Benefits of Unified API

1. **Single Server**: One process to manage and deploy
2. **Unified Documentation**: All endpoints in one Swagger UI
3. **Shared Middleware**: CORS, logging, and error handling
4. **Easier Deployment**: Single application to containerize
5. **Resource Efficiency**: Shared dependencies and configurations
6. **Consistent Interface**: Standardized API patterns across services

## 🚨 Important Notes

- **File Paths**: All service configurations reference their original folder locations
- **Dependencies**: Unified requirements.txt includes all necessary packages
- **Port**: Single port (8000) serves all services
- **CORS**: Configured for n8n integration
- **Logging**: Each service maintains its own logging configuration

## 🔮 Future Enhancements

- [ ] Add database layer for persistent storage
- [ ] Implement authentication middleware
- [ ] Add rate limiting
- [ ] Create monitoring and metrics endpoints
- [ ] Add automated testing suite
- [ ] Implement service health monitoring

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📄 License

This project maintains the same license as the original APIs.

---

**🎉 Welcome to the unified Automation Dashboard API!** 

All your automation services are now accessible through one powerful, unified interface. 