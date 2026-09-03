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

alembic upgrade head        # 표 생성·변경은 여기서 한다
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger 문서: http://localhost:8000/docs
- 헬스체크: `GET /health`

### 스키마 마이그레이션 (Alembic)

```bash
alembic upgrade head                      # 최신 스키마로
alembic revision --autogenerate -m "설명"  # 모델을 고친 뒤 리비전 생성
alembic downgrade -1                      # 한 단계 되돌리기
alembic current                           # 지금 적용된 리비전
```

접속 문자열은 `migrations/env.py` 가 `app.config.settings` 에서 가져온다.
`alembic.ini` 에 적지 않는다(운영 비밀번호가 저장소에 들어간다).

**모델을 고쳤으면 리비전을 같이 만들어야 한다.** 예전에는 기동할 때
`create_all` 로 표를 만들었는데, 그 방식은 기존 표의 컬럼 변경을 반영하지
못한다. 실제로 `EmotionRecord.score` 를 지운 뒤에도 운영 DB 에는 남아 있었다.

컨테이너는 기동할 때 `alembic upgrade head` 를 먼저 실행한다. 실패하면 그대로
멈춘다 — 어긋난 스키마로 뜨는 것보다 낫다.

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

## 설정 API 명세

아래는 모두 `Authorization: Bearer <accessToken>` 이 필요하다(`GET /service/info` 제외).
내가 가족으로 연결되지 않은 어르신·인형·약은 **404**로 응답한다(존재 여부를 숨김).

### 9. 내 프로필 조회 · 수정
`GET /protectors/me` → 보호자 본인 정보 + 내가 받는 알림 설정 + 연결된 어르신 목록
```json
{
  "protectorId": 1, "name": "김지영", "phoneNumber": "01011112222",
  "relation": "딸", "profileImageUrl": null, "onboardingCompleted": false,
  "users": [{ "userId": 1, "name": "박순자", "deviceId": 1, "isPrimary": true }],
  "notificationSettings": { "urgent": true, "dailyReport": true, "chat": true, "marketing": false, "...": "..." }
}
```
> 앱은 여기서 얻은 `userId` / `deviceId` 로 나머지 설정 API를 호출한다.

`PUT /protectors/me` — `{ "name", "relation", "profileImageUrl" }` (보낸 필드만 수정)
- `relation`: 딸/아들/며느리/사위/손주/손녀/기타
- **전화번호는 여기서 바꿀 수 없다.** 현재 번호와 다른 값을 보내면 400 (SMS 재인증 필요).

### 10. 알림 수신 설정 수정
`PATCH /protectors/me/notification-settings` — 보낸 항목만 부분 수정.

| 그룹 | 필드 |
|---|---|
| 상위(프로필 화면) | `urgent`, `dailyReport`, `chat`, `marketing` |
| 긴급 | `emotionChange`, `deviceDisconnected`, `medicationMissed` |
| 일상 | `voiceRequest`, `messageDelivered`, `voiceTrainingCompleted` |
| 리포트·기타 | `weeklyReport`, `appUpdate` |

### 11. 회원 탈퇴
`DELETE /protectors/me` → 패스키·토큰·가족 연결까지 삭제.
- 내가 **마지막 가족**이던 어르신은 인형·약·목소리까지 함께 삭제되고 `deletedUserIds`로 알려준다.
- 다른 가족이 남았는데 내가 주보호자였다면 가장 오래된 멤버가 주보호자를 이어받는다.

### 12. 어르신 정보 조회 · 수정
`GET /users/{userId}` → `{ userId, name, gender, birthDate, age, photoUrl, note, deviceId }`
`PUT /users/{userId}` — `{ "name", "gender", "birthDate", "photoUrl", "note" }`
- `gender`는 `female|male`. `"여성"/"남성"`도 받아서 정규화한다.
- `age`는 `birthDate`로 계산한 만 나이.

### 13. 가족 멤버 목록 · 제거
`GET /users/{userId}/family-members`
```json
{
  "stats": { "familyCount": 2, "voiceCount": 1, "inviteCodeCount": 0 },
  "members": [{ "protectorId": 1, "name": "김지영", "relation": "딸", "isPrimary": true, "isMe": true }]
}
```
`DELETE /family-members/{protectorId}` — **주보호자만** 가능. 본인(400)·주보호자(400)는 제거 불가.
제거된 가족이 등록한 인형 목소리도 함께 지운다.

### 14. 인형 상태 · 설정
`GET /devices/{deviceId}/settings`
```json
{
  "deviceId": 1, "name": "모리", "connected": false, "batteryLevel": 78,
  "batteryHoursLeft": 14, "lastHeartbeatAt": null, "volume": 80,
  "medicationCheck": true, "defaultVoiceId": 1,
  "voices": [{ "voiceId": 1, "name": "김지영", "status": "ready", "progress": 100, "isDefault": true }]
}
```
- `connected`: 마지막 heartbeat가 `DEVICE_OFFLINE_AFTER_SEC`(기본 600초) 이내인지.
- `voices[].status`: `ready | training | failed`.

`PUT /devices/{deviceId}/settings` — `{ "name", "volume"(0~100), "defaultVoiceId", "medicationCheck" }`
`PATCH /devices/{deviceId}/settings/voice` — `{ "voiceId": 1 }` (학습 중인 목소리는 400)

#### 기기 토큰 발급 (인형에 넣어 줄 값)
`POST /devices/{deviceId}/token` → `201`
```json
{ "deviceId": 1, "deviceToken": "0Yb...43자" }
```
- 인형은 이 값을 `X-Device-Token` 헤더에 담아 heartbeat·감정·활동을 올린다(아래 "인형이 호출하는 API").
- **응답으로만 볼 수 있다.** 조회 API 어디에도 토큰은 실리지 않으니(가족 전원이 보는 화면이라서) 받는 즉시 인형에 넣어야 한다.
- 다시 호출하면 새 토큰이 나오고 **이전 토큰은 즉시 무효**가 된다. 유출됐을 때 회전 수단이다.
- 해당 어르신의 가족이 아니면 404.

#### 인형이 호출하는 API (보호자 JWT 아님, `X-Device-Token`)
`PATCH /devices/{deviceId}/heartbeat` → `{ deviceId, connected }` (`connected` 판정의 근거가 되는 시각 갱신)
`POST /devices/{deviceId}/emotions` — `{ "emotion": "..." }` → `201`
`POST /devices/{deviceId}/activities` — `{ "activityType": "...", "content": "..." }` → `201`
- 토큰이 가리키는 기기와 URL 의 `deviceId` 가 다르면 403.
- `GET /devices/{deviceId}/settings|dnd|medications` 는 보호자 JWT·기기 토큰 둘 다 받는다.

### 15. 방해 금지 시간
`GET /devices/{deviceId}/dnd` → 설정한 적 없으면 기본값(23시~7시)을 만들어 반환.
`PUT /devices/{deviceId}/dnd` — `{ "enabled", "startHour", "endHour", "allowUrgentAlert", "allowWakeWord" }`
- 시작·종료 시각이 같으면 400.

### 16. 약 복용 시간
`GET /devices/{deviceId}/medications` → `{ deviceId, medicationCheck, medications: [...] }`
`POST /devices/{deviceId}/medications` → `201` — `{ "name", "time": "08:00", "timing": "식후", "enabled": true }`
`PUT /medications/{id}` · `DELETE /medications/{id}`
- `time`은 `HH:MM`(24시간), `timing`은 식전/식후/공복/아무때나. 형식이 틀리면 422.

### 17. 서비스 정보
`GET /service/info` (인증 불필요) → `{ appName, version, minSupportedVersion, termsUrl, privacyUrl, supportEmail, supportPhone }`
- 값은 `.env`(`SERVICE_VERSION`, `TERMS_URL`, …)로 관리한다.

### (개발 전용) 샘플 데이터
`POST /dev/seed` — 현재 보호자에게 어르신·인형·목소리·약 샘플을 연결한다(`DEBUG=true`일 때만).
어르신·인형을 만드는 정식 경로(첫 등록/초대 코드 플로우)가 붙기 전까지 설정 화면 테스트용.

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
│   ├── models.py          # 인증(Protector/Credential/...) + 설정(User/FamilyMember/Device/Voice/DndSetting/Medication/NotificationSetting/InviteCode)
│   ├── schemas.py         # 요청 스키마(camelCase)
│   ├── security.py        # JWT 발급/검증
│   ├── deps.py            # 인증 의존성
│   ├── errors.py          # 응답 봉투 + 예외 핸들러
│   ├── routers/           # phone / passkey / token / protectors / users / family_members / devices / medications / service / dev
│   └── services/          # sms(mock·aligo·ncp) / webauthn_service / access(소유권 검사·직렬화)
└── tests/                 # test_auth.py / test_settings.py
```

## 다음 단계(권장)

- **Alembic** 도입으로 스키마 마이그레이션 관리(테이블이 늘어날 예정이라면 필수).
- SMS provider 실연동(키/발신번호 등록) 후 `SMS_PROVIDER` 전환.
- rate limit(번호별 발송 제한)·로깅/모니터링 추가.
