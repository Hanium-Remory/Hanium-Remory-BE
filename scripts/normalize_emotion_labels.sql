-- 원본 한글 감정 라벨을 앱이 아는 영문 코드로 정규화한다.
--
-- 인형이 초기(정규화 로직 전)에 보낸 기록은 emotion_records 에 '기쁨·중립·
-- 불쾌·알수없음' 같은 원본 라벨로 남아 있다. 앱 그래프는 영문 코드
-- (happy/calm/sad/angry/anxious/lonely)만 알아서, 이 라벨들은 평평하게 뜬다.
-- 지금 저장 경로는 app/routers/devices.py 가 normalize_emotion 으로 맞춰
-- 넣지만, 그 전에 쌓인 것은 남아 있으므로 한 번 손봐 준다.
--
--   psql "$DATABASE_URL" -v uid=11 -f scripts/normalize_emotion_labels.sql
--
-- 매핑은 app/services/emotion_codes.py 의 _ALIASES 와 같다. 감정이 아닌 값
-- ('알수없음' 등, normalize 가 None 을 주는 것)은 그래프에서 빼야 맞으므로
-- (앱도 None 은 그래프에 안 섞는다) 지운다. 이미 영문 코드인 행은 건드리지
-- 않으니, 시드로 넣은 점은 그대로다. 다시 돌려도 안전하다.

BEGIN;

-- 바꾸기 전 분포(무엇이 얼마나 있는지 눈으로 확인).
SELECT '바꾸기 전' AS 시점, emotion, count(*)
FROM emotion_records WHERE user_id = :uid
GROUP BY emotion ORDER BY count(*) DESC;

-- 1) 알아볼 수 있는 한글 라벨 → 영문 코드.
UPDATE emotion_records e
SET emotion = m.code
FROM (VALUES
    ('기쁨', 'happy'),
    ('중립', 'calm'),
    ('평온', 'calm'),
    ('슬픔', 'sad'),
    ('분노', 'angry'),
    ('못마땅함', 'angry'),
    ('불쾌', 'angry'),
    ('두려움', 'anxious'),
    ('불안', 'anxious'),
    ('놀람', 'anxious'),
    ('외로움', 'lonely')
) AS m(label, code)
WHERE e.user_id = :uid AND e.emotion = m.label;

-- 2) 그래도 영문 코드가 아닌 값('알수없음' 등, 감정이 아닌 것)은 지운다.
--    앱이 그래프에서 빼는 값이라, 남겨 두면 선만 평평하게 흐트러진다.
DELETE FROM emotion_records
WHERE user_id = :uid
  AND emotion NOT IN ('happy', 'calm', 'sad', 'angry', 'anxious', 'lonely');

COMMIT;

-- 바꾼 뒤 분포. 이제 여섯 코드만 남아야 한다.
SELECT '바꾼 후' AS 시점, emotion, count(*)
FROM emotion_records WHERE user_id = :uid
GROUP BY emotion ORDER BY count(*) DESC;
