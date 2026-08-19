"""헬스체크 테스트.

/health 는 Dockerfile 의 HEALTHCHECK 가 호출한다. DB 가 끊겼을 때
503 을 내려야 컨테이너가 unhealthy 로 넘어가므로 두 경우를 모두 확인한다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


client = TestClient(app)


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["data"] == {"status": "up", "db": "up"}


def test_health_503_when_db_down():
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("select 1", {}, Exception("connection refused"))

    def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["message"] == "데이터베이스에 연결할 수 없습니다."
