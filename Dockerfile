# ReMory 백엔드 컨테이너 이미지.
# 빌드 스테이지에서 의존성만 설치해 옮기므로, 최종 이미지에 pip 캐시가 남지 않는다.

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg2-binary·webauthn 모두 wheel 로 설치되므로 컴파일러가 필요 없다.
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

# root 로 돌리지 않는다.
RUN useradd --create-home --uid 1000 remory

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY app ./app

# 업로드 파일 저장 위치. 컨테이너가 내려가면 사라지므로
# 운영에서는 볼륨을 붙이거나 S3 등 외부 스토리지로 옮겨야 한다.
RUN mkdir -p uploads/voices && chown -R remory:remory /app

USER remory

EXPOSE 8000

VOLUME ["/app/uploads"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health').read()"

# PORT 를 런타임에 주입받아야 해서 sh 를 거치지만, exec 로 uvicorn 이 PID 1 을 넘겨받는다.
# (그래야 ECS 등이 보내는 SIGTERM 을 uvicorn 이 직접 받아 graceful shutdown 한다)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
