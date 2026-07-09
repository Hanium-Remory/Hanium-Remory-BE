# ReMory Auth Backend

ReMory 앱(보호자용)의 **회원가입·로그인 백엔드**. 패스키(WebAuthn) 기반 가입/로그인과 전화번호 인증(SMS OTP)을 제공한다. Flutter 프론트엔드가 이 API를 호출한다.

- **Framework**: FastAPI (Python)
- **DB**: PostgreSQL (SQLAlchemy ORM)
- **인증**: WebAuthn 패스키 + JWT(access/refresh)
- **SMS**: mock / 알리고(Aligo) / NCP SENS 교체형

## 빠른 시작

```bash
cd remory-backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # 값 채우기 (개발은 기본값으로 바로 실행 가능)

# PostgreSQL 준비 (예: 로컬)
#   createdb remory && psql -c "create user remory with password 'remory'" \
#     && psql -c "grant all privileges on database remory to remory"
# 개발 중 DB 없이 흐름만 보려면 DATABASE_URL 을 sqlite 로 바꿔도 됨:
#   DATABASE_URL=sqlite:///./dev.db

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 서버 시작 시 테이블이 자동 생성된다(`init_db`, 개발 편의). 운영에서는 Alembic 마이그레이션 권장.
- Swagger 문서: http://localhost:8000/docs
- 헬스체크: `GET /health`

### 테스트

```bash
pip install pytest
pytest        # SQLite + WebAuthn 검증 목킹으로 전체 플로우 검증
```

## 공통 응답 형식

모든 응답은 아래 봉투(envelope)로 감싼다.

```json
{ "status": 200, "message": "OK", "data": { ... } }
```

에러도 동일 형식(`data: null`)이며 HTTP status와 `status` 필드가 일치한다.

인증이 필요한 요청은 `Authorization: Bearer <token>` 헤더를 쓴다.

## 인증 플로우

```
[가입]  전화번호 입력
  → POST /auth/phone/verification-code      (SMS 6자리 발송)
  → POST /auth/phone/verify                 (검증 → registrationToken 발급)
  → POST /auth/passkey/registration/options (registrationToken 필요, challenge 발급)
  → 기기에서 패스키 생성(navigator.credentials.create)
  → POST /auth/passkey/registration         (attestation 검증·저장 → access/refresh 발급)

[로그인]
  → POST /auth/passkey/authentication/options (challenge 발급)
  → 기기에서 서명(navigator.credentials.get)
  → POST /auth/passkey/authentication         (서명 검증 → access/refresh 발급)

[세션]
  → POST /auth/token/refresh   (access 재발급 + refresh 로테이션)
  → POST /auth/logout          (refresh 회수, access 토큰 필요)
```

## API 명세

### 1. 전화번호 인증번호 발송
`POST /auth/phone/verification-code`
```json
{ "phoneNumber": "010-1234-5678" }
```
→ `200 { "expiresInSec": 180 }`
> mock provider일 때 인증번호는 서버 로그(`📱 [MOCK SMS] ... code=xxxxxx`)에 찍힌다.

### 2. 전화번호 인증번호 확인
`POST /auth/phone/verify`
```json
{ "phoneNumber": "010-1234-5678", "code": "123456" }
```
→ `200 { "registrationToken": "<임시토큰>", "alreadyRegistered": false }`
- `registrationToken`은 패스키 등록 단계에서 `Authorization: Bearer`로 사용(기본 10분 유효).
- `alreadyRegistered`가 true면 이미 가입된 번호(로그인으로 유도).

### 3. 패스키 등록 옵션 요청
`POST /auth/passkey/registration/options`  ·  헤더: `Authorization: Bearer <registrationToken>`
```json
{ "displayName": "보호자" }
```
→ `200`
```json
{
  "rp": { "id": "remory.app", "name": "ReMory" },
  "user": { "id": "dXNlci0x", "name": "01012345678", "displayName": "보호자" },
  "challenge": "c2FtcGxlLWNoYWxsZW5nZQ",
  "pubKeyCredParams": [{ "type": "public-key", "alg": -7 }, { "type": "public-key", "alg": -257 }],
  "timeout": 60000,
  "authenticatorSelection": { "userVerification": "required", "residentKey": "preferred" }
}
```

### 4. 패스키 등록(검증·저장)
`POST /auth/passkey/registration`  ·  헤더: `Authorization: Bearer <registrationToken>`
```json
{
  "credentialId": "AaBbCc123...",
  "clientDataJSON": "<base64url>",
  "attestationObject": "<base64url>"
}
```
→ `201`
```json
{
  "protectorId": 1,
  "accessToken": "eyJhbGciOi...",
  "refreshToken": "eyJhbGciOi...",
  "onboardingCompleted": false
}
```

### 5. 패스키 로그인 옵션 요청
`POST /auth/passkey/authentication/options`
```json
{ "phoneNumber": "010-1234-5678" }
```
- `phoneNumber` 생략 가능(discoverable credential 로그인 시 `allowCredentials`가 빈 배열).

→ `200`
```json
{
  "challenge": "bG9naW4tY2hhbGxlbmdl",
  "rpId": "remory.app",
  "allowCredentials": [{ "type": "public-key", "id": "AaBbCc123..." }],
  "userVerification": "required",
  "timeout": 60000
}
```

### 6. 패스키 로그인(서명 검증)
`POST /auth/passkey/authentication`
```json
{
  "credentialId": "AaBbCc123...",
  "clientDataJSON": "<base64url>",
  "authenticatorData": "<base64url>",
  "signature": "<base64url>",
  "userHandle": "<base64url, optional>"
}
```
→ `200` (등록과 동일한 `protectorId/accessToken/refreshToken/onboardingCompleted`)
- 서명 검증 후 `sign_count`를 갱신한다.

### 7. 토큰 재발급
`POST /auth/token/refresh`
```json
{ "refreshToken": "eyJhbGciOi..." }
```
→ `200 { "accessToken": "...", "refreshToken": "..." }`
- refresh 토큰은 **로테이션**된다(이전 토큰은 즉시 무효). 재사용 시 401.

### 8. 로그아웃
`POST /auth/logout`  ·  헤더: `Authorization: Bearer <accessToken>`
```json
{ "refreshToken": "eyJhbGciOi..." }
```
→ `200` (해당 refresh 토큰 회수)

## 백엔드에서 자동 처리되는 부분 (명세 보완)

명세에 없었지만 서버에서 처리하는 것들:

- **공통 응답 봉투** `{status, message, data}` 및 통일된 에러 형식.
- **registrationToken**: 전화번호 인증과 패스키 등록을 잇는 단기 토큰(인증 안 한 번호의 등록 차단).
- **challenge 저장/만료/1회성**: 등록·로그인 challenge를 서버가 저장하고 `clientDataJSON` 안의 challenge로 대조 후 폐기(재사용 공격 방지).
- **sign_count 검증·갱신**: 로그인 때 인증기 카운터를 저장값과 비교해 복제 감지.
- **refresh 토큰 로테이션/회수**: 재발급 시 이전 토큰 무효, 로그아웃 시 회수.
- **OTP 만료(기본 180초)·시도 횟수 제한(기본 5회)**.
- **중복 가입 방지**: 이미 가입된 전화번호는 409.
- **전화번호 정규화**: `-`/공백 제거 후 저장·조회.

## WebAuthn 설정 메모 (프론트와 맞출 값)

- `RP_ID` = `remory.app` (앱의 associated domain / 도메인과 일치해야 함).
- `WEBAUTHN_ORIGINS`: 검증 시 허용할 origin 목록.
  - iOS: associated domain → `https://remory.app`
  - Android: `android:apk-key-hash:<앱 서명 해시>` (Flutter 앱 서명키로 산출)
  - 웹 디버깅: `http://localhost`
  - 프론트 담당자와 실제 값을 확정해 `.env`에 넣어야 실기기 검증이 통과한다.

## 프로젝트 구조

```
remory-backend/
├── app/
│   ├── main.py            # FastAPI 앱 + 라우터 등록
│   ├── config.py          # 환경설정(.env)
│   ├── database.py        # 엔진/세션/Base/init_db
│   ├── models.py          # Protector/Credential/PhoneVerification/WebAuthnChallenge/RefreshToken
│   ├── schemas.py         # 요청 스키마(camelCase)
│   ├── security.py        # JWT 발급/검증
│   ├── deps.py            # 인증 의존성
│   ├── errors.py          # 응답 봉투 + 예외 핸들러
│   ├── routers/           # phone / passkey / token
│   └── services/          # sms(mock·aligo·ncp) / webauthn_service
└── tests/test_auth.py
```

## 다음 단계(권장)

- **Alembic** 도입으로 스키마 마이그레이션 관리(테이블이 늘어날 예정이라면 필수).
- SMS provider 실연동(키/발신번호 등록) 후 `SMS_PROVIDER` 전환.
- rate limit(번호별 발송 제한)·로깅/모니터링 추가.
