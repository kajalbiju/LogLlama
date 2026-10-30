from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import SessionLocal, engine
from .routes import accounts, admin, data, sdk
from .services.bootstrap import seed_default_keys, verify_schema_revision


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema changes happen only through `alembic upgrade head`. Startup verifies the revision and seeds keys.
    await verify_schema_revision(engine)
    async with SessionLocal() as session:
        await seed_default_keys(session)
    yield
    await engine.dispose()


app = FastAPI(title="LogLlama API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds {settings.max_request_bytes} bytes."},
        )
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(accounts.router)
app.include_router(data.router)
app.include_router(admin.router)
app.include_router(sdk.router)
