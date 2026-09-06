-- 시연용 데일리·주간 리포트를 한 주치 넣는다.
--
-- 배치(generate_daily_reports.py·generate_weekly_reports.py)는 실제 대화·감정
-- 기록이 쌓여 있어야 숫자가 나온다. 시연 자리에서는 그 기록이 없어 화면이
-- '리포트가 아직 없습니다' 로만 뜬다. 그때 배치가 썼을 법한 행을 직접 넣는다.
--
--   psql "$DATABASE_URL" -v uid=1 -f scripts/seed_demo_reports.sql
--
-- uid 는 대상 어르신(users.id). 확인은:
--   psql "$DATABASE_URL" -c 'SELECT id, name FROM users ORDER BY id'
--
-- 이번 주(한국 시간 월요일부터 오늘까지)를 넣는다. 언제 돌려도 그 주가 잡히니
-- 날짜를 고칠 필요가 없다. 아직 오지 않은 날은 만들지 않는다 — 앱이 미래
-- 날짜 리포트를 보여주면 시연에서 바로 티가 난다.
--
-- 같은 주를 다시 돌려도 안전하다. (user_id, report_date)·(user_id, week_start)
-- 유니크에 걸려 값만 새로 덮어쓴다.

BEGIN;

-- 감정 라벨과 점수. 배치가 쓰는 여섯 가지 그대로다
-- (EMOTION_LABELS·EMOTION_SCORES). 앱 그래프가 아는 말과 어긋나면 감정 칸이
-- 비고, 점수 기준이 다르면 주간 점수와 앱 그래프가 따로 논다.
CREATE TEMP TABLE _emo (label text PRIMARY KEY, score int, phrase text) ON COMMIT DROP;
INSERT INTO _emo VALUES
    ('기뻐요',   85, '기분 좋게 지내셨어요'),
    ('평온해요', 65, '평온하게 지내셨어요'),
    ('외로워요', 40, '외로워하신 때가 있었어요'),
    ('불안해요', 32, '불안해하신 때가 있었어요'),
    ('슬퍼요',   25, '조금 가라앉아 계셨어요'),
    ('화나요',   20, '화가 나신 때가 있었어요');

-- 한국 시간 기준 이번 주 월요일과 오늘.
CREATE TEMP TABLE _wk ON COMMIT DROP AS
SELECT d - (EXTRACT(ISODOW FROM d)::int - 1) AS monday, d AS today
FROM (SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS d) s;

-- 한 주치 하루하루. 배치가 만든 것처럼 날마다 조금씩 다르게 둔다.
CREATE TEMP TABLE _days ON COMMIT DROP AS
SELECT * FROM (VALUES
    (0, 4, 1, '평온해요', '오후에 짧게 통화 한 번 어떠세요.'),
    (1, 6, 2, '기뻐요',   '좋아하시는 옛날 노래 이야기를 꺼내 보세요.'),
    (2, 3, 0, '외로워요', '이틀째 가족 소통이 없었어요. 안부 전화를 권해요.'),
    (3, 5, 1, '기뻐요',   '산책 다녀오신 이야기를 물어봐 주세요.'),
    (4, 7, 2, '기뻐요',   '이번 주 대화가 가장 많았던 날이에요.'),
    (5, 2, 1, '불안해요', '잠자리가 불편하신지 여쭤봐 주세요.'),
    (6, 5, 3, '평온해요', '주말 가족 소통이 많았어요. 다음 주도 이어가 보세요.')
) AS v(offset_days, conversations, family, emotion, suggestion);

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
    -- 배치의 build_summary 와 같은 문장 틀.
    u.name || '님은 인형과 ' || d.conversations || '번 이야기'
        || CASE WHEN d.family > 0 THEN ', 가족과 ' || d.family || '번 소통' ELSE '' END
        || '하셨어요. 감정은 대체로 ' || e.phrase || '.',
    d.suggestion,
    -- 리포트 조회는 created_at 내림차순이라(app/routers/reports.py) 같은 값으로
    -- 넣으면 앱의 < > 순서가 뒤죽박죽이 된다. 배치가 도는 다음 날 00:10 KST
    -- (= 15:10 UTC) 로 하루씩 벌려 둔다.
    ((w.monday + d.offset_days)::timestamp + INTERVAL '15 hours 10 minutes') AT TIME ZONE 'UTC'
FROM _wk w
JOIN _days d ON w.monday + d.offset_days <= w.today   -- 미래 날짜는 건너뛴다
JOIN _emo e ON e.label = d.emotion
CROSS JOIN (SELECT name FROM users WHERE id = :uid) u
ON CONFLICT (user_id, report_date) DO UPDATE SET
    conversation_count       = EXCLUDED.conversation_count,
    family_interaction_count = EXCLUDED.family_interaction_count,
    emotion_summary          = EXCLUDED.emotion_summary,
    summary                  = EXCLUDED.summary,
    suggestion               = EXCLUDED.suggestion;

-- 주간은 방금 넣은 데일리를 그대로 더한다. 배치와 같은 계산이라 앱의 두
-- 화면이 다른 숫자를 말하지 않는다.
CREATE TEMP TABLE _agg ON COMMIT DROP AS
SELECT
    w.monday,
    SUM(r.conversation_count)::int       AS conversations,
    SUM(r.family_interaction_count)::int AS family,
    ROUND(AVG(e.score))::int             AS avg_score,
    -- 그 주 가장 잦았던 감정. 횟수가 같으면 점수가 높은 쪽을 골라, 며칠치만
    -- 넣은 주에도 결과가 흔들리지 않게 한다.
    (SELECT r2.emotion_summary
       FROM daily_reports r2
       JOIN _emo e2 ON e2.label = r2.emotion_summary
      WHERE r2.user_id = :uid
        AND r2.report_date BETWEEN w.monday AND w.monday + 6
      GROUP BY r2.emotion_summary
      ORDER BY COUNT(*) DESC, MAX(e2.score) DESC
      LIMIT 1)                           AS dominant
FROM _wk w
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
    now()
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
