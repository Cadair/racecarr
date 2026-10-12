import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import inspect, text
from .core.config import get_settings, normalize_base_path
from .core.logging_config import configure_logging
from .core.database import Base, engine, SessionLocal
from .api.routes import router as api_router
from .services.auth import ensure_auth_row
from .services.app_config import ensure_app_config
from .services.scheduler import SchedulerService


def _ensure_downloader_priority_column() -> None:
    inspector = inspect(engine)
    if "downloader" not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns("downloader")}
    if "priority" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE downloader ADD COLUMN priority INTEGER"))


def _ensure_scheduled_search_overrides() -> None:
    inspector = inspect(engine)
    if "scheduled_search" not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns("scheduled_search")}
    alter_statements = []
    if "min_resolution" not in cols:
        alter_statements.append("ALTER TABLE scheduled_search ADD COLUMN min_resolution INTEGER")
    if "max_resolution" not in cols:
        alter_statements.append("ALTER TABLE scheduled_search ADD COLUMN max_resolution INTEGER")
    if "allow_hdr" not in cols:
        alter_statements.append("ALTER TABLE scheduled_search ADD COLUMN allow_hdr BOOLEAN")
    if "auto_download_threshold" not in cols:
        alter_statements.append("ALTER TABLE scheduled_search ADD COLUMN auto_download_threshold INTEGER")
    if not alter_statements:
        return
    with engine.begin() as conn:
        for stmt in alter_statements:
            conn.execute(text(stmt))


def _ensure_season_soft_delete() -> None:
    inspector = inspect(engine)
    if "season" not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns("season")}
    if "is_deleted" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE season ADD COLUMN is_deleted BOOLEAN DEFAULT 0"))


def _ensure_notification_targets_column() -> None:
    inspector = inspect(engine)
    if "app_config" not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns("app_config")}
    if "notification_targets" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE app_config ADD COLUMN notification_targets TEXT"))


def _ensure_app_config_columns() -> None:
    inspector = inspect(engine)
    if "app_config" not in inspector.get_table_names():
        return
    cols = {col["name"] for col in inspector.get_columns("app_config")}
    alter_statements: list[str] = []
    if "min_resolution" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN min_resolution INTEGER")
    if "max_resolution" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN max_resolution INTEGER")
    if "allow_hdr" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN allow_hdr BOOLEAN")
    if "preferred_codecs" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN preferred_codecs TEXT")
    if "preferred_groups" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN preferred_groups TEXT")
    if "auto_download_threshold" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN auto_download_threshold INTEGER")
    if "default_downloader_id" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN default_downloader_id INTEGER")
    if "event_allowlist" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN event_allowlist TEXT")
    if "notification_targets" not in cols:
        alter_statements.append("ALTER TABLE app_config ADD COLUMN notification_targets TEXT")

    if not alter_statements:
        return
    with engine.begin() as conn:
        for stmt in alter_statements:
            conn.execute(text(stmt))


def create_app() -> FastAPI:
    settings = get_settings()
    _ensure_downloader_priority_column()
    _ensure_scheduled_search_overrides()
    _ensure_season_soft_delete()
    _ensure_app_config_columns()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        ensure_auth_row(session)
        app_config = ensure_app_config(session)
    configure_logging(app_config.log_level)

    scheduler = SchedulerService(tick_seconds=settings.scheduler_tick_seconds, poll_seconds=settings.scheduler_tick_seconds)

    base = settings.base_path
    app = FastAPI(
        title=settings.app_name,
        openapi_url=f"{base}/openapi.json",
        docs_url=f"{base}/docs",
        redoc_url=f"{base}/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:8080",
            "http://127.0.0.1:8080",
        ],
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=f"{base}{settings.api_prefix}")

    app.state.scheduler = scheduler

    @app.on_event("startup")
    async def _start_scheduler() -> None:
        if settings.enable_scheduler:
            await scheduler.start()

    @app.on_event("shutdown")
    async def _stop_scheduler() -> None:
        if settings.enable_scheduler:
            await scheduler.stop()

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        index_path = static_dir / "index.html"

        def _render_index() -> HTMLResponse:
            if not index_path.exists():
                raise HTTPException(status_code=404)
            html = index_path.read_text(encoding="utf-8")
            inject = (
                "<head>\n"
                f"  <script>window.__BASE_PATH__ = {json.dumps(base)};</script>\n"
            )
            html = html.replace("<head>", inject, 1)
            return HTMLResponse(html)

        @app.get(f"{base}/", include_in_schema=False)
        async def spa_index():
            return _render_index()

        @app.get(f"{base}/{{full_path:path}}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = static_dir / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            return _render_index()
    return app


app = create_app()
