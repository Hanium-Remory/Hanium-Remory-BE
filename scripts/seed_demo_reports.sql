-- 시연용 데일리·주간 리포트 + 시각별 감정·일과를 두 주치 넣는다.
--
-- 배치(generate_daily_reports.py·generate_weekly_reports.py)는 실제 대화·감정
-- 기록이 쌓여 있어야 숫자가 나온다. 시연 자리에서는 그 기록이 없어 화면이
-- 비어 있다. 그때 배치가 썼을 법한 행을 직접 넣는다.
--
--   psql "$DATABASE_URL" -v uid=11 -f scripts/seed_demo_reports.sql
--
-- uid 는 대상 어르신(users.id). 확인은:
--   psql "$DATABASE_URL" -c 'SELECT id, name FROM users ORDER BY id'
--
-- 넣는 범위: 지난주 월요일부터 오늘까지 두 주(한국 시간). 오늘이 일요일이면
-- 8/24 ~ 9/6 이 잡히고, 두 주 모두 7일이 차서 주간 리포트가 두 건 생긴다.
-- 언제 돌려도 '지난주 + 이번 주'가 잡히니 날짜를 고칠 필요가 없다. 아직
-- 오지 않은 날·시각은 넣지 않는다 — 그래프에 미래가 찍히면 시연에서 티가 난다.
--
-- 다시 돌려도 안전하다. 요약(daily·weekly)은 유니크에 걸려 덮어쓰고, 감정·일과
-- 는 그 주에 기록이 있으면 통째로 건너뛴다(중복도 안 쌓고 기존 것도 안 지운다).

BEGIN;

-- 넣을 두 주. week_idx 0=이번 주, 1=지난주. monday 는 각 주의 월요일(한국 시간).
CREATE TEMP TABLE _weeks ON COMMIT DROP AS
SELECT g.week_idx,
       (base.this_monday - g.week_idx * 7) AS monday,
       base.today
FROM (
    SELECT d AS today, d - (EXTRACT(ISODOW FROM d)::int - 1) AS this_monday
    FROM (SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS d) s
) base
CROSS JOIN (SELECT generate_series(0, 1) AS week_idx) g;

-- 감정 라벨·점수. 배치가 쓰는 여섯 가지 그대로다(EMOTION_LABELS·EMOTION_SCORES).
CREATE TEMP TABLE _emo (label text PRIMARY KEY, score int, phrase text) ON COMMIT DROP;
INSERT INTO _emo VALUES
    ('기뻐요',   85, '기분 좋게 지내셨어요'),
    ('평온해요', 65, '평온하게 지내셨어요'),
    ('외로워요', 40, '외로워하신 때가 있었어요'),
    ('불안해요', 32, '불안해하신 때가 있었어요'),
    ('슬퍼요',   25, '조금 가라앉아 계셨어요'),
    ('화나요',   20, '화가 나신 때가 있었어요');

-- 두 주치 하루하루. 날마다·주마다 다르게 둔다(다양하게). topic 은 그날 무슨
-- 이야기를 나눴는지 — 리포트의 '오늘의 요약' 에 대화 요약처럼 들어간다. 대화
-- 원문(utterances)은 앱에 내보내지 않고 배치가 요약만 남기므로(7일 뒤 삭제),
-- 보호자가 보는 것은 이 요약이다.
CREATE TEMP TABLE _days ON COMMIT DROP AS
SELECT * FROM (VALUES
    -- 이번 주 (week_idx 0)
    (0, 0, 4, 1, '평온해요', '손주 안부를 도란도란 물으셨고,',        '오후에 짧게 통화 한 번 어떠세요.'),
    (0, 1, 6, 2, '기뻐요',   '젊을 적 좋아하던 노래로 흥이 나셨고,',  '좋아하시는 옛날 노래 이야기를 꺼내 보세요.'),
    (0, 2, 3, 0, '외로워요', '가족이 보고 싶다는 말씀을 자주 하셨고,','이틀째 가족 소통이 없었어요. 안부 전화를 권해요.'),
    (0, 3, 5, 1, '기뻐요',   '산책길에 본 꽃 이야기를 즐겁게 하셨고,','산책 다녀오신 이야기를 물어봐 주세요.'),
    (0, 4, 7, 2, '기뻐요',   '옛 직장 동료들과의 추억을 오래 나누셨고,','이번 주 대화가 가장 많았던 날이에요.'),
    (0, 5, 2, 1, '불안해요', '잠이 안 온다는 걱정을 털어놓으셨고,',   '잠자리가 불편하신지 여쭤봐 주세요.'),
    (0, 6, 5, 3, '평온해요', '주말에 찾아온 가족 이야기로 흐뭇해하셨고,','주말 가족 소통이 많았어요. 다음 주도 이어가 보세요.'),
    -- 지난주 (week_idx 1)
    (1, 0, 3, 0, '슬퍼요',   '영감님 생각이 난다며 가라앉으셨고,',   '기운이 없어 보이셨어요. 안부 전화를 권해요.'),
    (1, 1, 5, 1, '평온해요', '점심 반찬 이야기를 소소하게 나누셨고,', '점심 드시고 짧게 통화 어떠세요.'),
    (1, 2, 2, 0, '외로워요', '말벗이 없어 하루 종일 적적해하셨고,',   '이틀째 대화가 뜸했어요. 먼저 연락드려 보세요.'),
    (1, 3, 6, 2, '기뻐요',   '오랜만에 친구분과 통화해 밝아지셨고,', '오랜만에 많이 웃으셨어요.'),
    (1, 4, 4, 1, '평온해요', '텃밭 채소가 잘 자란다며 뿌듯해하셨고,', '차분히 하루를 보내셨어요.'),
    (1, 5, 8, 3, '기뻐요',   '손주가 그린 그림 자랑을 한참 하셨고,', '이번 주 대화가 가장 많았던 날이에요.'),
    (1, 6, 3, 1, '불안해요', '밤에 자꾸 깬다는 이야기를 하셨고,',     '밤에 잠을 설치신 듯해요. 살펴봐 주세요.')
) AS v(week_idx, offset_days, conversations, family, emotion, topic, suggestion);

-- 하루 안의 감정 흐름(9·12·15·18·21시, 한국 시간). 홈의 '감정 추이'와 리포트의
-- '그날 감정 흐름'은 요약이 아니라 emotion_records 를 시각순으로 그린다
-- (home.py·emotions.py). 코드는 앱이 아는 영문 여섯 가지(_emotionHeights).
-- 그날 최빈 코드가 daily_reports.emotion_summary 와 같도록 맞춘다.
CREATE TEMP TABLE _emotimeline ON COMMIT DROP AS
SELECT * FROM (VALUES
    -- 이번 주
    (0, 0,  9, 'calm'),   (0, 0, 12, 'happy'),  (0, 0, 15, 'calm'),    (0, 0, 18, 'calm'),    (0, 0, 21, 'calm'),
    (0, 1,  9, 'calm'),   (0, 1, 12, 'happy'),  (0, 1, 15, 'happy'),   (0, 1, 18, 'happy'),   (0, 1, 21, 'calm'),
    (0, 2,  9, 'lonely'), (0, 2, 12, 'sad'),    (0, 2, 15, 'lonely'),  (0, 2, 18, 'lonely'),  (0, 2, 21, 'anxious'),
    (0, 3,  9, 'calm'),   (0, 3, 12, 'happy'),  (0, 3, 15, 'happy'),   (0, 3, 18, 'calm'),    (0, 3, 21, 'happy'),
    (0, 4,  9, 'happy'),  (0, 4, 12, 'happy'),  (0, 4, 15, 'calm'),    (0, 4, 18, 'happy'),   (0, 4, 21, 'happy'),
    (0, 5,  9, 'calm'),   (0, 5, 12, 'anxious'),(0, 5, 15, 'anxious'), (0, 5, 18, 'sad'),     (0, 5, 21, 'anxious'),
    (0, 6,  9, 'calm'),   (0, 6, 12, 'calm'),   (0, 6, 15, 'happy'),   (0, 6, 18, 'calm'),    (0, 6, 21, 'calm'),
    -- 지난주
    (1, 0,  9, 'sad'),    (1, 0, 12, 'calm'),   (1, 0, 15, 'sad'),     (1, 0, 18, 'sad'),     (1, 0, 21, 'lonely'),
    (1, 1,  9, 'calm'),   (1, 1, 12, 'calm'),   (1, 1, 15, 'happy'),   (1, 1, 18, 'calm'),    (1, 1, 21, 'anxious'),
    (1, 2,  9, 'lonely'), (1, 2, 12, 'lonely'), (1, 2, 15, 'sad'),     (1, 2, 18, 'lonely'),  (1, 2, 21, 'anxious'),
    (1, 3,  9, 'happy'),  (1, 3, 12, 'happy'),  (1, 3, 15, 'calm'),    (1, 3, 18, 'happy'),   (1, 3, 21, 'calm'),
    (1, 4,  9, 'calm'),   (1, 4, 12, 'happy'),  (1, 4, 15, 'calm'),    (1, 4, 18, 'calm'),    (1, 4, 21, 'happy'),
    (1, 5,  9, 'happy'),  (1, 5, 12, 'happy'),  (1, 5, 15, 'happy'),   (1, 5, 18, 'calm'),    (1, 5, 21, 'happy'),
    (1, 6,  9, 'anxious'),(1, 6, 12, 'calm'),   (1, 6, 15, 'anxious'), (1, 6, 18, 'anxious'), (1, 6, 21, 'sad')
) AS v(week_idx, offset_days, hour_kst, code);

-- 하루 일과. 홈 타임라인과 리포트의 '그날 일과'는 activity_logs 를 시각순으로
-- 그린다(home.py·activities.py). 앱이 제목을 붙일 줄 아는 코드는 셋뿐이다
-- (activityTitleOf): DAILY_CONVERSATION·MEDICATION·VOICE_PLAY. content 는 부제.
CREATE TEMP TABLE _acttimeline ON COMMIT DROP AS
SELECT * FROM (VALUES
    -- 이번 주
    (0, 0,  9,  5, 'DAILY_CONVERSATION', '아침 안부를 나눴어요'),
    (0, 0, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 0, 16, 10, 'DAILY_CONVERSATION', '오후에 도란도란 이야기하셨어요'),
    (0, 0, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (0, 1,  9, 20, 'DAILY_CONVERSATION', '옛날 노래 이야기를 하셨어요'),
    (0, 1, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 1, 15, 40, 'VOICE_PLAY',         '따님 목소리를 들으셨어요'),
    (0, 1, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (0, 2, 10,  0, 'DAILY_CONVERSATION', '아침에 잠깐 이야기하셨어요'),
    (0, 2, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 2, 18, 30, 'VOICE_PLAY',         '가족 목소리를 들으셨어요'),
    (0, 2, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (0, 3,  9, 15, 'DAILY_CONVERSATION', '산책 다녀온 이야기를 하셨어요'),
    (0, 3, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 3, 16,  0, 'DAILY_CONVERSATION', '기분 좋게 대화하셨어요'),
    (0, 3, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (0, 4,  9, 10, 'DAILY_CONVERSATION', '아침부터 밝게 이야기하셨어요'),
    (0, 4, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 4, 15, 30, 'DAILY_CONVERSATION', '이야기가 길게 이어졌어요'),
    (0, 4, 19, 50, 'MEDICATION',         '저녁 약을 드셨어요'),
    (0, 5,  9, 30, 'DAILY_CONVERSATION', '아침에 짧게 이야기하셨어요'),
    (0, 5, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 5, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (0, 5, 21,  0, 'VOICE_PLAY',         '잠자리 전 가족 목소리를 들으셨어요'),
    (0, 6,  9,  5, 'DAILY_CONVERSATION', '주말 아침 인사를 나눴어요'),
    (0, 6, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (0, 6, 17,  0, 'DAILY_CONVERSATION', '가족과 함께한 이야기를 하셨어요'),
    (0, 6, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    -- 지난주
    (1, 0,  9, 40, 'DAILY_CONVERSATION', '기운 없이 짧게 이야기하셨어요'),
    (1, 0, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 0, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 1,  9, 10, 'DAILY_CONVERSATION', '아침 안부를 나눴어요'),
    (1, 1, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 1, 17, 20, 'VOICE_PLAY',         '아드님 목소리를 들으셨어요'),
    (1, 1, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 2, 10, 30, 'DAILY_CONVERSATION', '아침에 잠깐 이야기하셨어요'),
    (1, 2, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 2, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 3,  9, 15, 'DAILY_CONVERSATION', '오랜만에 밝게 웃으셨어요'),
    (1, 3, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 3, 16, 10, 'DAILY_CONVERSATION', '이야기가 길게 이어졌어요'),
    (1, 3, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 4,  9, 20, 'DAILY_CONVERSATION', '차분히 아침을 여셨어요'),
    (1, 4, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 4, 18, 40, 'VOICE_PLAY',         '가족 목소리를 들으셨어요'),
    (1, 4, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 5,  9,  5, 'DAILY_CONVERSATION', '아침부터 이야기가 많으셨어요'),
    (1, 5, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 5, 15, 30, 'DAILY_CONVERSATION', '한참 대화하셨어요'),
    (1, 5, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 6,  9, 30, 'DAILY_CONVERSATION', '아침에 짧게 이야기하셨어요'),
    (1, 6, 12, 30, 'MEDICATION',         '점심 약을 드셨어요'),
    (1, 6, 20,  0, 'MEDICATION',         '저녁 약을 드셨어요'),
    (1, 6, 22,  0, 'DAILY_CONVERSATION', '잠 못 드시고 늦게까지 이야기하셨어요')
) AS v(week_idx, offset_days, hour_kst, min_kst, atype, content);

-- ── 데일리 리포트 ────────────────────────────────────
INSERT INTO daily_reports (
    user_id, report_date, conversation_count, family_interaction_count,
    emotion_summary, summary, suggestion, created_at
)
SELECT
    :uid,
    w.monday + d.offset_days,
    d.conversations,
    d.family,
    d.emotion,
    -- 그날 대화 요약. 무슨 이야기를 나눴는지(topic) + 대화 횟수.
    u.name || '님은 ' || d.topic || ' 인형과 ' || d.conversations || '번'
        || CASE WHEN d.family > 0 THEN ', 가족과 ' || d.family || '번' ELSE '' END
        || ' 이야기 나누셨어요.',
    d.suggestion,
    -- 조회가 created_at 내림차순이라 같은 값이면 앱의 < > 순서가 뒤섞인다.
    -- 하루씩 벌려 둔다(그 날 다음 00:10 KST = 15:10 UTC).
    ((w.monday + d.offset_days)::timestamp + INTERVAL '15 hours 10 minutes') AT TIME ZONE 'UTC'
FROM _weeks w
JOIN _days d ON d.week_idx = w.week_idx AND w.monday + d.offset_days <= w.today
CROSS JOIN (SELECT name FROM users WHERE id = :uid) u
ON CONFLICT (user_id, report_date) DO UPDATE SET
    conversation_count       = EXCLUDED.conversation_count,
    family_interaction_count = EXCLUDED.family_interaction_count,
    emotion_summary          = EXCLUDED.emotion_summary,
    summary                  = EXCLUDED.summary,
    suggestion               = EXCLUDED.suggestion;

-- ── 시각별 감정 ──────────────────────────────────────
-- emotion_records 에는 유니크 제약이 없다. 이미 있는 실제 인형 기록은 그대로
-- 두고 시드 점만 더한다. 시드가 쓰는 시각은 정각(9·12·15·18·21시)이라 실제
-- 기록(초 단위까지 박힌)과 겹치지 않고, 이 정각에 이미 점이 있으면(=앞선
-- 실행) 건너뛰어 다시 돌려도 중복이 안 쌓인다. 아직 오지 않은 시각은 넣지 않는다.
INSERT INTO emotion_records (user_id, emotion, created_at)
SELECT :uid, t.code, ts.created_at
FROM _weeks w
JOIN _emotimeline t
  ON t.week_idx = w.week_idx AND w.monday + t.offset_days <= w.today
CROSS JOIN LATERAL (
    SELECT ((w.monday + t.offset_days)::timestamp + make_interval(hours => t.hour_kst))
               AT TIME ZONE 'Asia/Seoul' AS created_at
) ts
WHERE ts.created_at <= now()
  AND NOT EXISTS (
    SELECT 1 FROM emotion_records er
    WHERE er.user_id = :uid AND er.created_at = ts.created_at
  );

-- ── 시각별 일과 ──────────────────────────────────────
-- 감정과 같다. 실제 기록은 두고 시드만 더하며, 같은 시각에 이미 있으면 건너뛴다.
INSERT INTO activity_logs (user_id, activity_type, content, created_at)
SELECT :uid, a.atype, a.content, ts.created_at
FROM _weeks w
JOIN _acttimeline a
  ON a.week_idx = w.week_idx AND w.monday + a.offset_days <= w.today
CROSS JOIN LATERAL (
    SELECT ((w.monday + a.offset_days)::timestamp + make_interval(hours => a.hour_kst, mins => a.min_kst))
               AT TIME ZONE 'Asia/Seoul' AS created_at
) ts
WHERE ts.created_at <= now()
  AND NOT EXISTS (
    SELECT 1 FROM activity_logs al
    WHERE al.user_id = :uid AND al.created_at = ts.created_at
  );

-- ── 주간 리포트 ──────────────────────────────────────
-- 방금 넣은 데일리를 주별로 더한다. 배치와 같은 계산이라 앱의 두 화면이 다른
-- 숫자를 말하지 않는다. 두 주가 다 차 있으면 주간 리포트가 두 건 나온다.
CREATE TEMP TABLE _agg ON COMMIT DROP AS
SELECT
    w.monday,
    SUM(r.conversation_count)::int       AS conversations,
    SUM(r.family_interaction_count)::int AS family,
    ROUND(AVG(e.score))::int             AS avg_score,
    (SELECT r2.emotion_summary
       FROM daily_reports r2
       JOIN _emo e2 ON e2.label = r2.emotion_summary
      WHERE r2.user_id = :uid
        AND r2.report_date BETWEEN w.monday AND w.monday + 6
      GROUP BY r2.emotion_summary
      ORDER BY COUNT(*) DESC, MAX(e2.score) DESC
      LIMIT 1)                           AS dominant
FROM _weeks w
JOIN daily_reports r
  ON r.user_id = :uid
 AND r.report_date BETWEEN w.monday AND w.monday + 6
JOIN _emo e ON e.label = r.emotion_summary
GROUP BY w.monday;

INSERT INTO weekly_reports (
    user_id, week_start, total_conversation_count, family_interaction_count,
    avg_emotion_score, dominant_emotion, emergency_alert_count,
    weekly_summary, created_at
)
SELECT
    :uid, a.monday, a.conversations, a.family, a.avg_score, a.dominant, 0,
    u.name || '님은 이번 주 인형과 ' || a.conversations || '번 이야기, 가족과 '
        || a.family || '번 소통하셨어요. 감정은 ''' || a.dominant || ''' 가 가장 잦았어요.',
    -- 조회가 created_at 내림차순이라, 주도 한 주씩 벌려 최신 주가 먼저 오게 한다.
    (a.monday::timestamp + INTERVAL '15 hours 30 minutes') AT TIME ZONE 'UTC'
FROM _agg a
CROSS JOIN (SELECT name FROM users WHERE id = :uid) u
ON CONFLICT (user_id, week_start) DO UPDATE SET
    total_conversation_count = EXCLUDED.total_conversation_count,
    family_interaction_count = EXCLUDED.family_interaction_count,
    avg_emotion_score        = EXCLUDED.avg_emotion_score,
    dominant_emotion         = EXCLUDED.dominant_emotion,
    emergency_alert_count    = EXCLUDED.emergency_alert_count,
    weekly_summary           = EXCLUDED.weekly_summary;

COMMIT;

-- 넣은 결과를 그대로 보여 준다.
SELECT report_date, conversation_count AS 대화, family_interaction_count AS 가족,
       emotion_summary AS 감정
FROM daily_reports WHERE user_id = :uid ORDER BY report_date;

SELECT week_start, total_conversation_count AS 대화, family_interaction_count AS 가족,
       avg_emotion_score AS 점수, dominant_emotion AS 감정, weekly_summary
FROM weekly_reports WHERE user_id = :uid ORDER BY week_start;

-- 시각별 감정 점(최근 40개). 홈·리포트 그래프가 이걸 시간순으로 그린다.
SELECT to_char(created_at AT TIME ZONE 'Asia/Seoul', 'MM-DD(Dy) HH24:MI') AS "시각(KST)",
       emotion AS 감정
FROM emotion_records WHERE user_id = :uid ORDER BY created_at DESC LIMIT 40;

-- 시각별 일과(최근 40개). 홈 타임라인과 리포트의 '그날 일과'가 이걸 쓴다.
SELECT to_char(created_at AT TIME ZONE 'Asia/Seoul', 'MM-DD(Dy) HH24:MI') AS "시각(KST)",
       activity_type AS 활동, content AS 내용
FROM activity_logs WHERE user_id = :uid ORDER BY created_at DESC LIMIT 40;
