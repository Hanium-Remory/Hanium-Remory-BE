import logging

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .services.storage import resolve_urls


logger = logging.getLogger("remory.errors")


class APIError(Exception):
    """도메인 에러. {status, message, data:null} 형태로 응답."""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def envelope(data=None, message: str = "OK", status: int = 200) -> dict:
    # 저장소 URL 은 여기서 한 번만 조회 가능한 형태(presigned)로 바꾼다.
    # 라우터마다 챙기면 새로 만드는 API 에서 빠뜨리기 쉽다.
    return {"status": status, "message": message, "data": resolve_urls(data)}


def register_exception_handlers(app) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError):
        return JSONResponse(
            status_code=exc.status,
            content=envelope(None, exc.message, exc.status),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope(None, str(exc.detail), exc.status_code),
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        """예상 못 한 예외도 같은 봉투로 돌려준다.

        기본 핸들러는 순수 텍스트 "Internal Server Error" 를 내보내는데, 앱이
        그걸 JSON 으로 읽으려다 실패해 사용자에게는 '서버 응답을 읽을 수
        없습니다' 라고만 보인다. 무엇이 잘못됐는지도, 다시 시도하면 되는지도
        알 수 없다. 사유는 로그에만 남기고 사용자에게는 담담한 문구를 준다.
        """
        logger.exception("처리하지 못한 예외: %s: %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=500,
            content={
                "status": 500,
                "message": "잠시 문제가 생겼어요. 조금 뒤에 다시 시도해 주세요.",
                "data": None,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=envelope(jsonable_encoder(exc.errors()), "요청 형식이 올바르지 않습니다.", 422),
        )
