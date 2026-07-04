import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Load environment variables from .env file
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
load_dotenv(dotenv_path=env_path)

from app.backend.auth.utils import (  # noqa: E402
    get_cors_origins,
    resolve_admin_bootstrap_password,
    should_auto_init_admin,
)
from app.backend.database.connection import engine, SessionLocal  # noqa: E402
from app.backend.database.models import Base  # noqa: E402
from app.backend.models.user import (  # noqa: E402, F401 — register auth models with Base
    InvitationCode,
    User,
)
from app.backend.routes import (  # noqa: E402 — after load_dotenv so imported modules read env
    api_router,
)
from app.backend.services.ollama_service import ollama_service  # noqa: E402

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Auto-initialize admin user if not exists
def _auto_init_admin():
    """Create admin user on first startup if it doesn't exist."""
    if not should_auto_init_admin():
        logger.info("Skipping admin auto-initialization because AUTH_AUTO_INIT_ADMIN is disabled")
        return

    default_password = resolve_admin_bootstrap_password()
    if not default_password:
        logger.warning("Skipping admin auto-initialization because no bootstrap admin password is configured")
        return

    db = None
    try:
        from app.backend.auth.constants import ADMIN_USERNAME
        from app.backend.auth.utils import hash_password

        db = SessionLocal()
        existing = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if not existing:
            admin = User(username=ADMIN_USERNAME, password_hash=hash_password(default_password), role="admin", is_active=True)
            db.add(admin)
            db.commit()
            logger.info(f"Admin user '{ADMIN_USERNAME}' auto-created (change default password via CLI)")
    except Exception as e:
        logger.warning(f"Could not auto-init admin: {e}")
    finally:
        if db:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # --- Startup ---
    Base.metadata.create_all(bind=engine)
    _auto_init_admin()

    try:
        logger.info("Checking Ollama availability...")
        status = await ollama_service.check_ollama_status()

        if status["installed"]:
            if status["running"]:
                logger.info(f"Ollama is installed and running at {status['server_url']}")
                if status["available_models"]:
                    logger.info(f"Available models: {', '.join(status['available_models'])}")
                else:
                    logger.info("No models are currently downloaded")
            else:
                logger.info("Ollama is installed but not running")
                logger.info("You can start it from the Settings page or manually with 'ollama serve'")
        else:
            logger.info("Ollama is not installed. Install it to use local models.")
            logger.info("Visit https://ollama.com to download and install Ollama")

    except Exception as e:
        logger.warning(f"Could not check Ollama status: {e}")
        logger.info("Ollama integration is available if you install it later")

    yield  # Application is running

    # --- Shutdown ---
    pass


app = FastAPI(title="AI Hedge Fund API", description="Backend API for AI Hedge Fund", version="0.1.0", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Include all routes
app.include_router(api_router)
