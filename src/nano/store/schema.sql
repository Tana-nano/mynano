-- nano soul schema
-- 方針: 生ログ(events)は追記専用で絶対に消さない。
--       忘却は notes.state の遷移(active -> cold -> merged)だけで表現する。

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 1. 生ログ。魂の一次資料。
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    ts         REAL NOT NULL,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,            -- user | companion | system | world
    content    TEXT NOT NULL,
    meta_json  TEXT NOT NULL DEFAULT '{}',
    episode_id INTEGER REFERENCES episodes(id)   -- NULL = 未消化(無意識がこれから処理する)
);
CREATE INDEX IF NOT EXISTS events_session_ts ON events (session_id, ts);
CREATE INDEX IF NOT EXISTS events_pending ON events (id) WHERE episode_id IS NULL;

-- 2. エピソード。会話の塊＝要約の単位。
CREATE TABLE IF NOT EXISTS episodes (
    id         INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at   REAL NOT NULL,
    summary    TEXT NOT NULL DEFAULT '',
    salience   REAL NOT NULL DEFAULT 0.5,
    mood       TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);

-- 3. 記憶ノート。想起の主役。1ノート1事実（原子性）。
CREATE TABLE IF NOT EXISTS notes (
    id                INTEGER PRIMARY KEY,
    created_at        REAL NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'fact',   -- fact|preference|episode|reflection|self
    content           TEXT NOT NULL,
    context           TEXT NOT NULL DEFAULT '',       -- 新しい記憶が入るたび書き換わりうる
    keywords_json     TEXT NOT NULL DEFAULT '[]',
    tags_json         TEXT NOT NULL DEFAULT '[]',
    category          TEXT NOT NULL DEFAULT '',
    importance        REAL NOT NULL DEFAULT 0.5,
    half_life_days    REAL NOT NULL DEFAULT 3.0,      -- 想起のたびに伸びる
    last_accessed_at  REAL NOT NULL,
    access_count      INTEGER NOT NULL DEFAULT 0,
    state             TEXT NOT NULL DEFAULT 'active', -- active | cold | merged
    merged_into       INTEGER REFERENCES notes(id),
    pinned            INTEGER NOT NULL DEFAULT 0,     -- 1 = 決して忘れない(人格の芯など)
    source_episode_id INTEGER REFERENCES episodes(id)
);
CREATE INDEX IF NOT EXISTS notes_state ON notes (state);
CREATE INDEX IF NOT EXISTS notes_kind ON notes (kind);
CREATE INDEX IF NOT EXISTS notes_episode ON notes (source_episode_id);

-- 埋め込み。float32 のリトルエンディアン列。numpy にも array にも読める素朴な形式。
CREATE TABLE IF NOT EXISTS note_vectors (
    note_id INTEGER PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    dim     INTEGER NOT NULL,
    vec     BLOB NOT NULL
);

-- 明示検索(「〇〇覚えてる?」)用。trigram なので日本語でも部分一致が効く。
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5 (
    note_id UNINDEXED,
    text,
    tokenize = 'trigram'
);

-- 4. 記憶グラフ。連想の実体。
CREATE TABLE IF NOT EXISTS links (
    src_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    dst_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    relation   TEXT NOT NULL,   -- similar|elaborates|causes|contradicts|temporal_next|about_entity|merged_from
    weight     REAL NOT NULL DEFAULT 0.5,
    created_by TEXT NOT NULL DEFAULT 'unconscious',
    created_at REAL NOT NULL,
    PRIMARY KEY (src_id, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS links_dst ON links (dst_id);

-- 5. 固有名詞。人・場所・作品・概念。
CREATE TABLE IF NOT EXISTS entities (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS note_entities (
    note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, entity_id)
);
CREATE INDEX IF NOT EXISTS note_entities_entity ON note_entities (entity_id);

-- 6. コアメモリ。常にシステムプロンプトへ載る作業状態＝「意識の手元」。
--    無意識デーモンが静かに書き換える唯一の窓口でもある。
CREATE TABLE IF NOT EXISTS working_state (
    key        TEXT PRIMARY KEY,   -- identity | user_model | current_focus | mood | thread
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL,
    updated_by TEXT NOT NULL DEFAULT 'system'
);
-- 人格に触れる変更は必ず追跡できるようにする（勝手に別人になっていないかの監査）。
CREATE TABLE IF NOT EXISTS working_state_log (
    id         INTEGER PRIMARY KEY,
    ts         REAL NOT NULL,
    key        TEXT NOT NULL,
    old_value  TEXT NOT NULL DEFAULT '',
    new_value  TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

-- 7. 無意識のジョブキュー。
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    priority     INTEGER NOT NULL DEFAULT 10,
    run_after    REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT NOT NULL DEFAULT '',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_ready ON jobs (status, run_after, priority);
