"""업로드 파일 저장소.

로컬 디스크(개발)와 S3(운영)를 같은 인터페이스로 다룬다.
컨테이너는 재시작하면 디스크가 사라지므로 운영에서는 반드시 S3 를 쓴다.

DB 에는 '표준 URL' 을 넣는다. 로컬이면 "/uploads/xxx.jpg",
S3 면 "https://버킷.s3.리전.amazonaws.com/xxx.jpg" 다.

버킷을 비공개로 두면(S3_PRESIGN=true, 기본) 표준 URL 로는 파일을 받을 수 없다.
그래서 응답으로 내보내는 순간에만 presigned URL 로 바꿔 내려준다(resolve_urls).
앱이 그 presigned URL 을 그대로 되돌려 보내도 normalize() 가 서명 쿼리를 떼고
표준 URL 로 되돌리므로, DB 에는 만료되지 않는 값만 남는다.
"""

import mimetypes
import os
import uuid
from typing import Optional

from ..config import settings


def _new_key(ext: str, prefix: str) -> str:
    """충돌하지 않는 저장 이름. prefix 는 "voices" 같은 하위 폴더."""
    name = f"{uuid.uuid4().hex}{ext}"
    return f"{prefix}/{name}" if prefix else name


def _content_type(ext: str) -> str:
    return mimetypes.types_map.get(ext) or "application/octet-stream"


class LocalStorage:
    """서버 로컬 디스크에 저장하고 /uploads/... 로 서빙한다."""

    # 로컬은 URL 이 그대로 유효해서 응답을 다시 훑을 필요가 없다.
    signs_urls = False

    def __init__(self, base_dir: str = "uploads", public_prefix: str = "/uploads"):
        self.base_dir = base_dir
        self.public_prefix = public_prefix

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        key = _new_key(ext, prefix)
        path = os.path.join(self.base_dir, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return f"{self.public_prefix}/{key}"

    def delete(self, url: str) -> None:
        key = self._key_from_url(url)
        if key is None:
            return
        path = os.path.join(self.base_dir, key)
        if os.path.exists(path):
            os.remove(path)

    def public_url(self, url: str) -> str:
        return url

    def normalize(self, url: str) -> str:
        return url

    def _key_from_url(self, url: str) -> Optional[str]:
        if not url.startswith(f"{self.public_prefix}/"):
            return None
        key = url[len(self.public_prefix) + 1 :]
        # "../" 로 uploads 밖 파일을 지우지 못하게 막는다.
        if ".." in key.split("/"):
            return None
        return key


class S3Storage:
    """S3 버킷에 저장한다. 자격증명은 boto3 기본 체인(EC2 인스턴스 역할 등)을 따른다."""

    def __init__(
        self,
        bucket: str,
        region: str,
        key_prefix: str = "",
        public_base_url: str = "",
        presign: bool = True,
        presign_ttl_sec: int = 3600,
    ):
        if not bucket:
            raise RuntimeError("S3 저장소를 쓰려면 S3_BUCKET 을 설정해야 합니다.")
        if presign and public_base_url:
            # presigned 서명은 S3 엔드포인트에 대해서만 유효하다.
            # CloudFront 를 앞에 두려면 그쪽 서명 방식(signed cookie 등)을 따로 써야 한다.
            raise RuntimeError(
                "S3_PUBLIC_BASE_URL 과 S3_PRESIGN 은 같이 쓸 수 없습니다. "
                "공개 CDN 도메인으로 서빙하려면 S3_PRESIGN=false 로 두세요."
            )
        self.bucket = bucket
        self.region = region
        self.key_prefix = key_prefix.strip("/")
        self.presign = presign
        self.presign_ttl_sec = presign_ttl_sec
        self.signs_urls = presign
        # CloudFront 나 커스텀 도메인을 쓸 경우를 위해 열어둔다.
        self.base_url = (
            public_base_url.rstrip("/")
            or f"https://{bucket}.s3.{region}.amazonaws.com"
        )
        self._client = None

    @property
    def client(self):
        # boto3 는 클라이언트 생성이 느려서 실제로 필요할 때 한 번만 만든다.
        if self._client is None:
            import boto3
            from botocore.config import Config

            # 리전 엔드포인트를 명시한다. 기본값은 presigned URL 을
            # s3.amazonaws.com 호스트로 발급해서 표준 URL 과 호스트가 어긋나고,
            # 리전으로 리다이렉트되는 과정에서 서명이 깨질 수 있다.
            self._client = boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=f"https://s3.{self.region}.amazonaws.com",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "virtual"},
                ),
            )
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.key_prefix}/{key}" if self.key_prefix else key

    def _key_from_url(self, url: str) -> Optional[str]:
        """우리 버킷의 URL 이면 오브젝트 키를, 아니면 None 을 준다."""
        prefix = f"{self.base_url}/"
        if not url.startswith(prefix):
            return None  # 저장소를 옮기기 전에 만들어진 URL 은 건드리지 않는다.
        # presigned URL 이 되돌아왔을 때를 대비해 서명 쿼리를 떼어낸다.
        return url[len(prefix) :].split("?", 1)[0]

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        key = self._full_key(_new_key(ext, prefix))
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=_content_type(ext),
        )
        return f"{self.base_url}/{key}"

    def delete(self, url: str) -> None:
        key = self._key_from_url(url)
        if key is None:
            return
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def public_url(self, url: str) -> str:
        """응답에 내보낼 URL. 비공개 버킷이면 만료되는 presigned URL 을 발급한다."""
        if not self.presign:
            return url
        key = self._key_from_url(url)
        if key is None:
            return url
        # 로컬 서명이라 네트워크 호출이 없다.
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presign_ttl_sec,
        )

    def normalize(self, url: str) -> str:
        """앱이 돌려준 URL 을 DB 에 넣을 표준 형태로 되돌린다."""
        key = self._key_from_url(url)
        if key is None:
            return url
        return f"{self.base_url}/{key}"


def _build_storage():
    if settings.storage_backend == "s3":
        return S3Storage(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            key_prefix=settings.s3_key_prefix,
            public_base_url=settings.s3_public_base_url,
            presign=settings.s3_presign,
            presign_ttl_sec=settings.s3_presign_ttl_sec,
        )
    return LocalStorage()


storage = _build_storage()


def normalize_url(url: Optional[str]) -> Optional[str]:
    """요청으로 들어온 저장소 URL 을 저장 가능한 표준 형태로 만든다."""
    if not url:
        return url
    return storage.normalize(url)


def _resolve(value):
    if isinstance(value, str):
        return storage.public_url(value)
    if isinstance(value, dict):
        return {k: _resolve(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_resolve(v) for v in value)
    return value


def resolve_urls(data):
    """응답 안의 저장소 URL 을 조회 가능한 형태로 바꾼다.

    라우터마다 URL 필드를 챙기면 새 API 에서 빠뜨리기 쉬워서
    envelope() 에서 응답 전체를 한 번만 훑는다.
    presigned 를 쓰지 않는 저장소면 아무 일도 하지 않는다.
    """
    if not storage.signs_urls:
        return data
    return _resolve(data)
