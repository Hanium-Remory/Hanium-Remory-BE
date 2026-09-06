"""응답을 만들다 나는 문제가 화면 전체를 막지 않아야 한다."""

import pytest
from fastapi import FastAPI

from app.errors import APIError, envelope, register_exception_handlers
from app.services import storage as storage_module


# ── 저장소 URL 서명 실패 ─────────────────────────────
def test_signing_failure_keeps_the_rest_of_the_response(monkeypatch):
    """사진 한 장이 안 뜨는 것과 화면이 안 열리는 것은 무게가 다르다.

    EC2 의 S3 권한이 빠져 있으면 presigned URL 생성이 NoCredentialsError 로
    터진다. 예전에는 그 예외가 그대로 올라가 대화방 조회 전체가 500 이었다.
    """
    class Boom:
        signs_urls = True

        def public_url(self, value):
            raise RuntimeError("Unable to locate credentials")

    monkeypatch.setattr(storage_module, "storage", Boom())

    data = [
        {"messageId": 1, "content": "안녕하세요", "imageUrl": None},
        {"messageId": 2, "content": None, "imageUrl": "https://b.s3.amazonaws.com/a.jpg"},
    ]
    out = storage_module.resolve_urls(data)

    assert out[0]["content"] == "안녕하세요"
    # 서명은 못 했어도 값은 남는다(표준 URL). 화면은 열린다.
    assert out[1]["imageUrl"] == "https://b.s3.amazonaws.com/a.jpg"


def test_signing_still_applies_when_it_works(monkeypatch):
    class Fine:
        signs_urls = True

        def public_url(self, value):
            return value + "?signed"

    monkeypatch.setattr(storage_module, "storage", Fine())
    assert storage_module.resolve_urls({"imageUrl": "a.jpg"}) == {"imageUrl": "a.jpg?signed"}


# ── 예상 못 한 예외 ──────────────────────────────────
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("무언가 잘못됨")

    @app.get("/known")
    def known():
        raise APIError(404, "없는 어르신입니다.")

    @app.get("/fine")
    def fine():
        return envelope({"ok": True}, "OK", 200)

    return TestClient(app, raise_server_exceptions=False)


def test_unexpected_error_still_speaks_json(client):
    """앱이 JSON 을 못 읽으면 '서버 응답을 읽을 수 없습니다' 만 보인다.

    무엇이 잘못됐는지도, 다시 시도하면 되는지도 알 수 없다.
    """
    r = client.get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == 500
    assert body["data"] is None
    assert body["message"]
    # 예외 내용이 사용자에게 새지 않는다
    assert "무언가 잘못됨" not in body["message"]
    assert "RuntimeError" not in body["message"]


def test_known_errors_keep_their_message(client):
    r = client.get("/known")
    assert r.status_code == 404
    assert r.json()["message"] == "없는 어르신입니다."


def test_normal_response_is_untouched(client):
    r = client.get("/fine")
    assert r.status_code == 200
    assert r.json()["data"] == {"ok": True}
