import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .errors import envelope, register_exception_handlers
from .routers import (
    dev,
    devices,
    family_members,
    medications,
    passkey,
    phone,
    protectors,
    service,
    token,
    users,
    wellknown,
)

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 개발 편의: 시작 시 테이블 생성. 운영은 Alembic 권장.
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Flutter 앱은 CORS와 무관하지만, 웹 디버깅/관리 도구를 위해 허용.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(phone.router)
app.include_router(passkey.router)
app.include_router(token.router)
app.include_router(wellknown.router)

# 설정 화면
app.include_router(protectors.router)
app.include_router(users.router)
app.include_router(family_members.router)
app.include_router(devices.router)
app.include_router(medications.router)
app.include_router(service.router)
app.include_router(dev.router)


@app.get("/health")
def health():
    return envelope({"status": "up"}, "OK", 200)
