from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .services.storage import resolve_urls


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

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=envelope(jsonable_encoder(exc.errors()), "요청 형식이 올바르지 않습니다.", 422),
        )
