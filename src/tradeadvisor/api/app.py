from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tradeadvisor import __version__
from tradeadvisor.api.routes import router
from tradeadvisor.config import Settings, get_settings
from tradeadvisor.data.service import MarketDataService
from tradeadvisor.runtime import build_service
from tradeadvisor.signals.engine import SignalEngine

WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def create_app(
    settings: Settings | None = None,
    service: MarketDataService | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Trade Advisor", version=__version__)
    app.state.settings = settings
    app.state.service = service or build_service(settings)
    app.state.engine = SignalEngine()
    app.include_router(router)
    if WEB_DIR.is_dir():
        # mounted last so /api/* and /health win; same-origin, so no CORS needed
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
