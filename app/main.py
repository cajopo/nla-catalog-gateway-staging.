from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.app_proxy import AppProxyError, verify_app_proxy
from app.catalog import CatalogFilters, CatalogRepository
from app.config import Settings, get_settings
from app.cursor import CursorCodec, CursorError
from app.database import Database
from app.models import BrowseResponse, FacetsResponse, GamesResponse, SearchResponse, SuggestResponse
from app.rate_limit import InMemoryRateLimiter

LOGGER = logging.getLogger("nla_gateway")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    if settings.auto_bootstrap and not settings.database_path.is_file():
        from app.bootstrap import bootstrap_catalog
        app.state.bootstrap_task = asyncio.create_task(asyncio.to_thread(bootstrap_catalog, settings))
    yield
    task = getattr(app.state, "bootstrap_task", None)
    if task and not task.done():
        task.cancel()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings.database_path)
    repository = CatalogRepository(
        database=database,
        cursor_codec=CursorCodec(settings.cursor_secret, settings.cursor_ttl_seconds),
        public_base_url=settings.public_base_url,
        max_page_size=settings.max_page_size,
    )
    limiter = InMemoryRateLimiter(settings.rate_limit_per_minute)

    app = FastAPI(
        title="NLA Catalog Gateway",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.repository = repository

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origin_list,
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        client = request.client.host if request.client else "unknown"
        allowed, retry_after = limiter.allow(client)
        if not allowed:
            return JSONResponse(
                {"detail": "Rate limit exceeded", "requestId": request_id},
                status_code=429,
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )

        if request.url.path.startswith("/apps/nla-catalog") and settings.require_app_proxy:
            try:
                verify_app_proxy(
                    request.url.query,
                    settings.shopify_app_secret or "",
                    settings.allowed_shop or "",
                    settings.app_proxy_max_age_seconds,
                )
            except AppProxyError as exc:
                LOGGER.warning("Rejected App Proxy request id=%s reason=%s", request_id, exc)
                return JSONResponse(
                    {"detail": "Unauthorized proxy request", "requestId": request_id},
                    status_code=401,
                    headers={"X-Request-ID": request_id},
                )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = (
            "public, max-age=30, stale-while-revalidate=120"
            if request.method == "GET" and response.status_code == 200
            else "no-store"
        )
        return response

    @app.exception_handler(CursorError)
    async def cursor_error_handler(_: Request, exc: CursorError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def ensure_ready() -> None:
        status = database.status(settings.expected_product_count)
        if not status.ready:
            raise HTTPException(status_code=503, detail="Catalog is not ready")

    def build_filters(
        set_name: str | None,
        language: str | None,
        rarity: str | None,
        availability: str | None,
    ) -> CatalogFilters:
        if availability not in {None, "available", "sold-out"}:
            raise HTTPException(status_code=422, detail="Invalid availability")
        return CatalogFilters(set_name, language, rarity, availability)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        status = database.status(settings.expected_product_count)
        return JSONResponse(
            {
                "ready": status.ready,
                "datasetVersion": status.dataset_version,
                "productCount": status.product_count,
                "sourceSha256": status.source_sha256,
                "error": status.error,
            },
            status_code=200 if status.ready else 503,
        )

    @app.get("/api/catalog/games", response_model=GamesResponse)
    @app.get("/apps/nla-catalog/games", response_model=GamesResponse)
    async def games():
        ensure_ready()
        return repository.games()

    @app.get("/api/catalog/search", response_model=SearchResponse)
    @app.get("/apps/nla-catalog/search", response_model=SearchResponse)
    async def search(
        game: str,
        q: str = Query(min_length=2, max_length=settings.max_query_length),
        limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
        cursor: str | None = Query(default=None, max_length=2048),
        set_name: str | None = Query(default=None, alias="set", max_length=160),
        language: str | None = Query(default=None, max_length=50),
        rarity: str | None = Query(default=None, max_length=50),
        availability: str | None = Query(default=None),
    ):
        ensure_ready()
        try:
            return repository.search(
                game, q, limit, cursor, build_filters(set_name, language, rarity, availability)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/catalog/browse", response_model=BrowseResponse)
    @app.get("/apps/nla-catalog/browse", response_model=BrowseResponse)
    async def browse(
        game: str,
        limit: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
        cursor: str | None = Query(default=None, max_length=2048),
        set_name: str | None = Query(default=None, alias="set", max_length=160),
        language: str | None = Query(default=None, max_length=50),
        rarity: str | None = Query(default=None, max_length=50),
        availability: str | None = Query(default=None),
    ):
        ensure_ready()
        try:
            return repository.browse(
                game, limit, cursor, build_filters(set_name, language, rarity, availability)
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/catalog/suggest", response_model=SuggestResponse)
    @app.get("/apps/nla-catalog/suggest", response_model=SuggestResponse)
    async def suggest(
        game: str,
        q: str = Query(min_length=2, max_length=settings.max_query_length),
        limit: int = Query(default=8, ge=1, le=20),
    ):
        ensure_ready()
        try:
            return repository.suggest(game, q, limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/catalog/facets", response_model=FacetsResponse)
    @app.get("/apps/nla-catalog/facets", response_model=FacetsResponse)
    async def facets_endpoint(
        game: str,
        q: str | None = Query(default=None, max_length=settings.max_query_length),
    ):
        ensure_ready()
        try:
            return repository.facets(game, q)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app


app = create_app()
