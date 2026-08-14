import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .errors import envelope, register_exception_handlers
from .routers import (
    activities,
    chat,
    dev,
    devices,
    emotions,
    family_members,
    files,
    home,
    medications,
    memories,
    notifications,
    passkey,
    phone,
    protectors,
    reports,
    service,
    token,
    users,
    voices,
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

# 로컬 저장소일 때만 업로드된 사진·음성을 /uploads/파일명 으로 서빙한다.
# S3 를 쓰면 파일이 서버에 없고 URL 도 S3 주소라 마운트할 필요가 없다.
if settings.storage_backend != "s3":
    os.makedirs("uploads/voices", exist_ok=True)
    app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

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

# 홈·콘텐츠 기능 (기능 백엔드에서 합침)
app.include_router(home.router)
app.include_router(files.router)
app.include_router(memories.router)
app.include_router(chat.router)
app.include_router(emotions.router)
app.include_router(activities.router)
app.include_router(notifications.router)
app.include_router(reports.router)
app.include_router(voices.router)


@app.get("/health")
def health():
    return envelope({"status": "up"}, "OK", 200)
