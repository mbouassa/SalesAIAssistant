"""
AI Demo Agent - FastAPI Application Entry Point.

This application provides an AI-powered demo agent that can
conduct product demonstrations via video calls.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.v1 import rooms, agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    settings = get_settings()
    print(f"🚀 Starting {settings.app_name}")
    print(f"📹 Daily.co API configured: {'✓' if settings.daily_api_key else '✗'}")
    print(f"🎤 Deepgram API configured: {'✓' if settings.deepgram_api_key else '✗'}")
    print(f"🤖 OpenAI API configured: {'✓' if settings.openai_api_key else '✗'}")
    
    yield
    
    # Shutdown
    print("👋 Shutting down...")


def create_app() -> FastAPI:
    """Application factory for creating the FastAPI app."""
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered demo agent for automated product demonstrations",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # CORS middleware - allow Vercel deployments via regex
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routers
    app.include_router(rooms.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    
    # Root endpoint (for Railway healthcheck)
    @app.get("/", tags=["health"])
    async def root():
        """Root endpoint for healthcheck."""
        return {"status": "ok"}
    
    # Health check endpoint
    @app.get("/health", tags=["health"])
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "service": settings.app_name}
    
    return app


# Create the app instance
app = create_app()

