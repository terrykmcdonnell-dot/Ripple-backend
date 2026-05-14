import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import alarm, alarm_history, revenuecat_webhook

load_dotenv()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.REVENUECAT_WEBHOOK_PUBLIC_URL:
        logger.info(
            "RevenueCat webhook URL (set this in RevenueCat dashboard): %s",
            settings.REVENUECAT_WEBHOOK_PUBLIC_URL.strip(),
        )
    yield


app = FastAPI(title="Ripple API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Mobile apps + Expo Web hit many origins; alarm routes do not rely on browser cookies.
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(alarm.router)
app.include_router(alarm_history.router)
app.include_router(revenuecat_webhook.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
