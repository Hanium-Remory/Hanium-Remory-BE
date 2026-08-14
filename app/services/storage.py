"""업로드 파일 저장소.

로컬 디스크(개발)와 S3(운영)를 같은 인터페이스로 다룬다.
컨테이너는 재시작하면 디스크가 사라지므로 운영에서는 반드시 S3 를 쓴다.

DB 에는 저장 경로가 아니라 '공개 URL' 을 그대로 넣는다.
로컬이면 "/uploads/xxx.jpg", S3 면 "https://버킷.../xxx.jpg" 가 된다.
그래서 저장소를 바꿔도 기존 레코드의 URL 은 계속 유효하다.
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
    ):
        if not bucket:
            raise RuntimeError("S3 저장소를 쓰려면 S3_BUCKET 을 설정해야 합니다.")
        self.bucket = bucket
        self.region = region
        self.key_prefix = key_prefix.strip("/")
        # CloudFront 나 커스텀 도메인을 쓸 경우를 위해 열어둔다.
        self.public_base_url = (
            public_base_url.rstrip("/")
            or f"https://{bucket}.s3.{region}.amazonaws.com"
        )
        self._client = None

    @property
    def client(self):
        # boto3 는 클라이언트 생성이 느려서 실제 업로드가 있을 때 한 번만 만든다.
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.key_prefix}/{key}" if self.key_prefix else key

    def save(self, content: bytes, ext: str, prefix: str = "") -> str:
        key = self._full_key(_new_key(ext, prefix))
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=_content_type(ext),
        )
        return f"{self.public_base_url}/{key}"

    def delete(self, url: str) -> None:
        prefix = f"{self.public_base_url}/"
        if not url.startswith(prefix):
            return  # 저장소를 옮기기 전에 만들어진 URL 은 건드리지 않는다.
        self.client.delete_object(Bucket=self.bucket, Key=url[len(prefix) :])


def _build_storage():
    if settings.storage_backend == "s3":
        return S3Storage(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            key_prefix=settings.s3_key_prefix,
            public_base_url=settings.s3_public_base_url,
        )
    return LocalStorage()


storage = _build_storage()
