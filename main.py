from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import mask, health, workflow, rename, promptmap
import uvicorn

# Create unified FastAPI app instance
app = FastAPI(
    title="Automation Dashboard API",
    description="Unified API for image processing, masking, workflows, renaming, and prompt generation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware for n8n integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this based on your n8n setup
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all API routers with appropriate prefixes
app.include_router(health.router, prefix="/api/health", tags=["health"])
app.include_router(mask.router, prefix="/api/mask", tags=["masking"])
app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(rename.router, prefix="/api/rename", tags=["rename"])
app.include_router(promptmap.router, prefix="/api/promptmap", tags=["promptmap"])

@app.get("/")
async def root():
    """Root endpoint with unified API information"""
    return {
        "message": "Automation Dashboard API",
        "version": "1.0.0",
        "description": "Unified API for all automation services",
        "endpoints": {
            "/": "API information",
            "/docs": "Interactive API documentation",
            "/api/health": "Health check endpoints",
            "/api/mask": "Image masking endpoints",
            "/api/workflow": "Workflow processing endpoints", 
            "/api/rename": "Image renaming endpoints",
            "/api/promptmap": "Prompt generation endpoints"
        },
        "services": [
            "Image Masking with ComfyUI",
            "Background Change Workflows",
            "Face Detection & Renaming",
            "Fashion Image Analysis & Prompts"
        ]
    }

@app.get("/health")
async def unified_health_check():
    """Unified health check endpoint"""
    return {
        "status": "healthy",
        "message": "All automation services are running",
        "services": {
            "mask": "Image masking service",
            "workflow": "Workflow processing service", 
            "rename": "Image renaming service",
            "promptmap": "Prompt generation service"
        }
    }

if __name__ == "__main__":
    print("🚀 Starting Automation Dashboard API...")
    print("📚 API Documentation available at: http://localhost:8000/docs")
    print("🔍 Health check available at: http://localhost:8000/health")
    print("🎯 All services accessible through unified API")
    
    try:
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
    except Exception as e:
        print(f"❌ Failed to start API: {e}")
        import sys
        sys.exit(1) 