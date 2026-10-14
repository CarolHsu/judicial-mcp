PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS judgments (
    id               INTEGER PRIMARY KEY,          -- docdata.aspx id
    case_no          TEXT NOT NULL UNIQUE,         -- 111年憲判字第6號
    case_name        TEXT,
    year             INTEGER,
    number           INTEGER,
    original_case_no TEXT,
    decision_date    TEXT,                         -- ISO date
    petitioner       TEXT,
    cause            TEXT,
    author_note      TEXT,
    source_url       TEXT NOT NULL,
    crawled_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paragraphs (
    judgment_id INTEGER NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
    section     TEXT NOT NULL,                     -- 主文 | 理由
    para_no     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    PRIMARY KEY (judgment_id, section, para_no)
);

CREATE TABLE IF NOT EXISTS statutes (
    judgment_id INTEGER NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    text        TEXT NOT NULL,
    url         TEXT,
    PRIMARY KEY (judgment_id, ord)
);

CREATE TABLE IF NOT EXISTS related_cases (
    judgment_id INTEGER NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    case_no     TEXT NOT NULL,
    url         TEXT,
    PRIMARY KEY (judgment_id, ord)
);

CREATE TABLE IF NOT EXISTS documents (
    id             INTEGER PRIMARY KEY,            -- download.aspx id
    judgment_id    INTEGER NOT NULL REFERENCES judgments(id) ON DELETE CASCADE,
    ord            INTEGER NOT NULL,
    section        TEXT NOT NULL,
    grp            TEXT,
    title          TEXT NOT NULL,
    base_title     TEXT NOT NULL,
    ext            TEXT NOT NULL,
    doc_type       TEXT NOT NULL,
    is_ocr_variant INTEGER NOT NULL DEFAULT 0,
    twin_id        INTEGER,                        -- for originals: id of the _OCR sibling used for text
    party          TEXT,
    justice        TEXT,
    opinion_type   TEXT,
    filed_date     TEXT,
    source_url     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending', -- pending|downloaded|extracted|skipped|failed
    skip_reason    TEXT,
    error          TEXT,
    file_path      TEXT,
    sha256         TEXT,
    bytes          INTEGER,
    page_count     INTEGER
);
CREATE INDEX IF NOT EXISTS documents_judgment ON documents(judgment_id);
CREATE INDEX IF NOT EXISTS documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS pages (
    doc_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no    INTEGER NOT NULL,
    text       TEXT NOT NULL,
    method     TEXT NOT NULL,                      -- native|site_ocr|ocr|pending_ocr
    confidence REAL,
    PRIMARY KEY (doc_id, page_no)
);
CREATE INDEX IF NOT EXISTS pages_method ON pages(method);

CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts USING fts5(
    text, judgment_id UNINDEXED, section UNINDEXED, para_no UNINDEXED, tokenize = 'trigram'
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text, doc_id UNINDEXED, page_no UNINDEXED, tokenize = 'trigram'
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
