"""SQLite 数据层：建表、查询、序列化。"""

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
  id            INTEGER PRIMARY KEY,
  rel_path      TEXT NOT NULL UNIQUE,
  filename      TEXT NOT NULL,
  size          INTEGER NOT NULL DEFAULT 0,
  mtime         REAL NOT NULL DEFAULT 0,
  width         INTEGER,
  height        INTEGER,
  score         INTEGER,
  loved         INTEGER NOT NULL DEFAULT 0,
  trashed       INTEGER NOT NULL DEFAULT 0,
  missing       INTEGER NOT NULL DEFAULT 0,
  orig_rel_path TEXT,
  rated_at      REAL,
  created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_score ON images(score);
CREATE INDEX IF NOT EXISTS idx_images_trashed ON images(trashed);
CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime);
CREATE TABLE IF NOT EXISTS collections (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL UNIQUE,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_images (
  collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  image_id      INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
  PRIMARY KEY (collection_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_ci_image ON collection_images(image_id);
CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

SORTS = {
    "newest": "mtime DESC, id DESC",
    "oldest": "mtime ASC, id ASC",
    "score_high": "score IS NULL, score DESC, mtime DESC",
    "score_low": "score IS NULL, score ASC, mtime ASC",
    "random": "RANDOM()",
}

VIEWS = ("all", "unrated", "score", "loved", "trash", "collection")


def connect(db_path) -> sqlite3.Connection:
    # FastAPI 的 yield 依赖、同步端点分别在 threadpool 的不同线程里执行，
    # 连接只被单个请求顺序使用，因此允许跨线程；并发写入靠 WAL + busy timeout 兜住。
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(db_path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def to_item(row, memberships=None) -> dict:
    """行 → 前端 JSON 对象。memberships: {image_id: [{"id","name"}]}"""
    rel = row["rel_path"]
    mtime = int(row["mtime"])
    return {
        "id": row["id"],
        "filename": row["filename"],
        "rel_path": rel,
        "size": row["size"],
        "mtime": row["mtime"],
        "width": row["width"],
        "height": row["height"],
        "score": row["score"],
        "loved": bool(row["loved"]),
        "trashed": bool(row["trashed"]),
        "organized": rel.startswith("_trash/"),
        "missing": bool(row["missing"]),
        "orig_rel_path": row["orig_rel_path"],
        "rated_at": row["rated_at"],
        "collections": (memberships or {}).get(row["id"], []),
        "thumb_url": f"/api/img/thumb/{row['id']}?v={mtime}",
        "full_url": f"/api/img/full/{row['id']}?v={mtime}",
    }


def memberships(conn, image_ids) -> dict:
    """批量取图片所属 collection，避免 N+1。"""
    ids = list(image_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT ci.image_id, c.id, c.name FROM collection_images ci "
        f"JOIN collections c ON c.id = ci.collection_id "
        f"WHERE ci.image_id IN ({marks}) ORDER BY c.created_at, c.id",
        ids,
    ).fetchall()
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r["image_id"], []).append({"id": r["id"], "name": r["name"]})
    return out


def get_image(conn, image_id: int):
    return conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()


def item_of(conn, image_id: int) -> dict | None:
    row = get_image(conn, image_id)
    if not row:
        return None
    return to_item(row, memberships(conn, [image_id]))


def _where(view, score, collection, keyword):
    """返回 (where 子句, 参数列表)。"""
    clauses = ["missing = 0"]
    params: list = []
    if view == "unrated":
        clauses.append("score IS NULL AND trashed = 0")
    elif view == "score":
        if score is None:
            raise ValueError("view=score 需要 score 参数")
        clauses.append("score = ? AND trashed = 0")
        params.append(score)
    elif view == "loved":
        clauses.append("loved = 1")
    elif view == "trash":
        clauses.append("trashed = 1")
    elif view == "collection":
        if collection is None:
            raise ValueError("view=collection 需要 collection 参数")
        clauses.append(
            "id IN (SELECT image_id FROM collection_images WHERE collection_id = ?)"
        )
        params.append(collection)
    elif view != "all":
        raise ValueError(f"未知 view: {view}")
    if keyword:
        clauses.append("lower(filename) LIKE ?")
        params.append(f"%{keyword.lower()}%")
    return " AND ".join(clauses), params


def query_images(conn, view="all", score=None, collection=None, keyword="",
                 sort="newest", page=1, per_page=60):
    if sort not in SORTS:
        raise ValueError(f"未知 sort: {sort}")
    where, params = _where(view, score, collection, keyword)
    total = conn.execute(f"SELECT COUNT(*) AS n FROM images WHERE {where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT * FROM images WHERE {where} ORDER BY {SORTS[sort]} LIMIT ? OFFSET ?",
        [*params, per_page, (page - 1) * per_page],
    ).fetchall()
    cols = memberships(conn, [r["id"] for r in rows])
    return [to_item(r, cols) for r in rows], total


def stats(conn) -> dict:
    row = conn.execute(
        "SELECT "
        "COALESCE(SUM(missing = 0), 0) AS total, "
        "COALESCE(SUM(missing = 0 AND score IS NULL AND trashed = 0), 0) AS unrated, "
        "COALESCE(SUM(missing = 0 AND loved = 1), 0) AS loved, "
        "COALESCE(SUM(missing = 0 AND trashed = 1), 0) AS trash "
        "FROM images"
    ).fetchone()
    scores = {str(i): 0 for i in range(6)}
    for r in conn.execute(
        "SELECT score, COUNT(*) AS n FROM images "
        "WHERE missing = 0 AND trashed = 0 AND score IS NOT NULL GROUP BY score"
    ):
        scores[str(r["score"])] = r["n"]
    return {
        "total": row["total"],
        "unrated": row["unrated"],
        "loved": row["loved"],
        "trash": row["trash"],
        "scores": scores,
    }


def collections(conn) -> list:
    rows = conn.execute(
        "SELECT c.id, c.name, c.created_at, "
        "  (SELECT COUNT(*) FROM collection_images ci "
        "     JOIN images i ON i.id = ci.image_id "
        "    WHERE ci.collection_id = c.id AND i.missing = 0) AS count "
        "FROM collections c ORDER BY c.created_at, c.id"
    ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "count": r["count"], "created_at": r["created_at"]}
        for r in rows
    ]


def collection_count(conn, collection_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM collection_images ci "
        "JOIN images i ON i.id = ci.image_id "
        "WHERE ci.collection_id = ? AND i.missing = 0",
        (collection_id,),
    ).fetchone()
    return row["n"]


def rated_score_fields(score) -> dict:
    """把「用户想设的分数」翻译成数据库字段（含 Trash 联动规则）。"""
    now = time.time()
    if score is None:
        return {"score": None}
    if score == 0:
        return {"score": 0, "trashed": 1, "rated_at": now}
    return {"score": score, "trashed": 0, "rated_at": now}
