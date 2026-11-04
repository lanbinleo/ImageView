"""FastAPI 应用：路由、鉴权、静态文件。契约见 docs/API.md。"""

import math
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__, auth, db
from . import scan as scan_mod
from .settings import load_config, web_dir

SCAN_IDLE = {
    "running": False, "total": 0, "done": 0, "added": 0, "updated": 0,
    "missing": 0, "errors": 0, "started_at": None, "ended_at": None, "error": None,
}
NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}
STATIC_FILES = {
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "theme.js": "text/javascript; charset=utf-8",
}


class PasswordBody(BaseModel):
    password: str = ""


class RateBody(BaseModel):
    score: int | None = None


class LovedBody(BaseModel):
    loved: bool = False


class TrashBody(BaseModel):
    trashed: bool = False


class StatePatch(BaseModel):
    """撤回用的精确状态回填：只更新显式给出的字段（null 也算显式）。"""

    id: int
    score: int | None = None
    trashed: bool | None = None
    loved: bool | None = None
    rated_at: float | None = None


class BatchBody(BaseModel):
    ids: list[int] = []
    op: str
    score: int | None = None
    loved: bool | None = None
    trashed: bool | None = None
    items: list[StatePatch] = []


class CollectionBody(BaseModel):
    name: str = ""


class CollectionImagesBody(BaseModel):
    ids: list[int] = []
    action: str = "add"


class IdsBody(BaseModel):
    ids: list[int] = []


class SettingsBody(BaseModel):
    root: str | None = None
    current_password: str | None = None
    new_password: str | None = None


def create_app(data_dir: str | None = None) -> FastAPI:
    cfg = load_config()
    data_path = Path(data_dir) if data_dir else Path(cfg["data_dir"])
    data_path.mkdir(parents=True, exist_ok=True)
    db_path = data_path / "rating.db"
    db.init_db(db_path)

    conn = db.connect(db_path)
    try:
        if not db.get_setting(conn, "secret"):
            db.set_setting(conn, "secret", secrets.token_hex(32))
        secret = db.get_setting(conn, "secret")
    finally:
        conn.close()

    app = FastAPI(title="ImageRating", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg = cfg
    app.state.data_dir = data_path
    app.state.db_path = db_path
    app.state.secret = secret
    app.state.scan = dict(SCAN_IDLE)
    app.state.scan_lock = threading.Lock()

    # ---------- 依赖 ----------

    def get_db(request: Request):
        conn = db.connect(request.app.state.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def require_auth(request: Request):
        if not auth.check_session(request.app.state.secret, request.cookies.get(auth.COOKIE_NAME)):
            raise HTTPException(401, "未登录")

    def root_of(conn) -> Path:
        root = db.get_setting(conn, "root")
        if not root:
            raise HTTPException(400, "尚未设置图片目录")
        return Path(root)

    def set_session(response: Response, request: Request) -> None:
        response.set_cookie(
            auth.COOKIE_NAME, auth.make_session(request.app.state.secret),
            max_age=auth.SESSION_TTL, httponly=True, samesite="lax", path="/",
        )

    def start_scan(request: Request, conn) -> bool:
        """启动后台扫描线程；已在跑就返回 False。"""
        root = root_of(conn)
        if not root.is_dir():
            raise HTTPException(400, f"图片目录不存在：{root}")
        with request.app.state.scan_lock:
            if request.app.state.scan["running"]:
                return False
            request.app.state.scan = {**SCAN_IDLE, "running": True, "total": 0}
            state = request.app.state.scan

            def update(patch: dict) -> None:
                state.update(patch)

            def worker() -> None:
                try:
                    scan_mod.scan(root, request.app.state.db_path, update)
                finally:
                    state["running"] = False
                    if not state.get("ended_at"):
                        state["ended_at"] = time.time()

            threading.Thread(target=worker, name="scan", daemon=True).start()
            return True

    # ---------- 认证 ----------

    @app.get("/api/session")
    def session(request: Request, conn=Depends(get_db)):
        authed = auth.check_session(request.app.state.secret, request.cookies.get(auth.COOKIE_NAME))
        return {"authed": authed, "needs_setup": db.get_setting(conn, "password_hash") is None}

    @app.post("/api/setup")
    def setup(body: PasswordBody, request: Request, response: Response, conn=Depends(get_db)):
        if db.get_setting(conn, "password_hash") is not None:
            raise HTTPException(409, "密码已设置，请直接登录")
        if len(body.password) < 4:
            raise HTTPException(400, "密码至少 4 个字符")
        db.set_setting(conn, "password_hash", auth.hash_password(body.password))
        set_session(response, request)
        return {"ok": True}

    @app.post("/api/login")
    def login(body: PasswordBody, request: Request, response: Response, conn=Depends(get_db)):
        stored = db.get_setting(conn, "password_hash")
        if stored is None:
            raise HTTPException(400, "尚未设置密码")
        if not auth.verify_password(body.password, stored):
            raise HTTPException(401, "密码错误")
        set_session(response, request)
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return {"ok": True}

    # ---------- 图片列表与操作 ----------

    @app.get("/api/images", dependencies=[Depends(require_auth)])
    def list_images(
        view: str = "all", score: int | None = None, collection: int | None = None,
        q: str = "", sort: str = "newest", page: int = 1, per_page: int = 60,
        conn=Depends(get_db),
    ):
        page = max(1, page)
        per_page = min(200, max(1, per_page))
        try:
            items, total = db.query_images(
                conn, view=view, score=score, collection=collection, keyword=q.strip(),
                sort=sort, page=page, per_page=per_page,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {
            "items": items,
            "total": total,
            "page": page,
            "last_page": max(1, math.ceil(total / per_page)),
            "stats": db.stats(conn),
            "collections": db.collections(conn),
        }

    @app.get("/api/images/{image_id}", dependencies=[Depends(require_auth)])
    def get_one(image_id: int, conn=Depends(get_db)):
        item = db.item_of(conn, image_id)
        if item is None:
            raise HTTPException(404, "图片不存在")
        return item

    @app.post("/api/images/{image_id}/rate", dependencies=[Depends(require_auth)])
    def rate(image_id: int, body: RateBody, conn=Depends(get_db)):
        if body.score is not None and not 0 <= body.score <= 5:
            raise HTTPException(400, "分数必须是 0–5 或 null")
        if db.get_image(conn, image_id) is None:
            raise HTTPException(404, "图片不存在")
        fields = db.rated_score_fields(body.score)
        conn.execute(
            f"UPDATE images SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            [*fields.values(), image_id],
        )
        conn.commit()
        return {"item": db.item_of(conn, image_id)}

    @app.post("/api/images/{image_id}/loved", dependencies=[Depends(require_auth)])
    def loved(image_id: int, body: LovedBody, conn=Depends(get_db)):
        cur = conn.execute(
            "UPDATE images SET loved = ? WHERE id = ?", (int(body.loved), image_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "图片不存在")
        return {"item": db.item_of(conn, image_id)}

    @app.post("/api/images/{image_id}/trash", dependencies=[Depends(require_auth)])
    def trash(image_id: int, body: TrashBody, conn=Depends(get_db)):
        cur = conn.execute(
            "UPDATE images SET trashed = ? WHERE id = ?", (int(body.trashed), image_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "图片不存在")
        return {"item": db.item_of(conn, image_id)}

    @app.post("/api/images/batch", dependencies=[Depends(require_auth)])
    def batch(body: BatchBody, conn=Depends(get_db)):
        if body.op == "state":
            # 前端 Ctrl+Z 撤回：按提交的字段精确回填，不走 rate 的 Trash 联动规则。
            updated = 0
            for patch in body.items:
                fields = patch.model_dump(exclude_unset=True)
                image_id = fields.pop("id", None)
                if image_id is None or not fields:
                    continue
                if fields.get("score") is not None and not 0 <= fields["score"] <= 5:
                    raise HTTPException(400, "分数必须是 0–5 或 null")
                sql = f"UPDATE images SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?"
                updated += conn.execute(sql, [*fields.values(), image_id]).rowcount
            conn.commit()
            return {"updated": updated}
        ids = [int(i) for i in body.ids]
        if not ids:
            return {"updated": 0}
        marks = ",".join("?" * len(ids))
        if body.op == "rate":
            if body.score is not None and not 0 <= body.score <= 5:
                raise HTTPException(400, "分数必须是 0–5 或 null")
            fields = db.rated_score_fields(body.score)
            sql = f"UPDATE images SET {', '.join(f'{k} = ?' for k in fields)} WHERE id IN ({marks})"
            cur = conn.execute(sql, [*fields.values(), *ids])
        elif body.op == "loved":
            cur = conn.execute(
                f"UPDATE images SET loved = ? WHERE id IN ({marks})",
                [int(bool(body.loved)), *ids],
            )
        elif body.op == "trash":
            cur = conn.execute(
                f"UPDATE images SET trashed = ? WHERE id IN ({marks})",
                [int(bool(body.trashed)), *ids],
            )
        else:
            raise HTTPException(400, f"未知操作：{body.op}")
        conn.commit()
        return {"updated": cur.rowcount}

    # ---------- Collections ----------

    @app.get("/api/collections", dependencies=[Depends(require_auth)])
    def list_collections(conn=Depends(get_db)):
        return db.collections(conn)

    @app.post("/api/collections", dependencies=[Depends(require_auth)])
    def create_collection(body: CollectionBody, conn=Depends(get_db)):
        name = body.name.strip()
        if not 1 <= len(name) <= 50:
            raise HTTPException(400, "名称长度需为 1–50 个字符")
        try:
            cur = conn.execute(
                "INSERT INTO collections (name, created_at) VALUES (?, ?)", (name, time.time())
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "已有同名 Collection")
        cid = cur.lastrowid
        return {"id": cid, "name": name, "count": 0, "created_at": time.time()}

    @app.patch("/api/collections/{collection_id}", dependencies=[Depends(require_auth)])
    def rename_collection(collection_id: int, body: CollectionBody, conn=Depends(get_db)):
        name = body.name.strip()
        if not 1 <= len(name) <= 50:
            raise HTTPException(400, "名称长度需为 1–50 个字符")
        if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
            raise HTTPException(404, "Collection 不存在")
        try:
            conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "已有同名 Collection")
        return next(c for c in db.collections(conn) if c["id"] == collection_id)

    @app.delete("/api/collections/{collection_id}", dependencies=[Depends(require_auth)])
    def delete_collection(collection_id: int, conn=Depends(get_db)):
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
        return {"ok": True}

    @app.post("/api/collections/{collection_id}/images", dependencies=[Depends(require_auth)])
    def collection_images(collection_id: int, body: CollectionImagesBody, conn=Depends(get_db)):
        if conn.execute("SELECT 1 FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
            raise HTTPException(404, "Collection 不存在")
        ids = [int(i) for i in body.ids]
        if body.action == "add":
            conn.executemany(
                "INSERT OR IGNORE INTO collection_images (collection_id, image_id) VALUES (?, ?)",
                [(collection_id, i) for i in ids],
            )
        elif body.action == "remove":
            conn.executemany(
                "DELETE FROM collection_images WHERE collection_id = ? AND image_id = ?",
                [(collection_id, i) for i in ids],
            )
        else:
            raise HTTPException(400, f"未知操作：{body.action}")
        conn.commit()
        return {"count": db.collection_count(conn, collection_id)}

    # ---------- 扫描 ----------

    @app.post("/api/scan", dependencies=[Depends(require_auth)])
    def trigger_scan(request: Request, conn=Depends(get_db)):
        start_scan(request, conn)
        return {"running": True, "status": request.app.state.scan}

    @app.get("/api/scan/status", dependencies=[Depends(require_auth)])
    def scan_status(request: Request):
        return request.app.state.scan

    # ---------- 物理整理 / 恢复 ----------

    @app.post("/api/organize", dependencies=[Depends(require_auth)])
    def organize(body: IdsBody, conn=Depends(get_db)):
        moved, failed = scan_mod.organize(conn, root_of(conn), body.ids)
        return {"moved": moved, "failed": failed}

    @app.post("/api/restore", dependencies=[Depends(require_auth)])
    def restore(body: IdsBody, conn=Depends(get_db)):
        moved, failed = scan_mod.restore(conn, root_of(conn), body.ids)
        return {"moved": moved, "failed": failed}

    # ---------- 图片内容 ----------

    @app.get("/api/img/thumb/{image_id}", dependencies=[Depends(require_auth)])
    def thumb(image_id: int, request: Request, conn=Depends(get_db)):
        row = db.get_image(conn, image_id)
        if row is None:
            raise HTTPException(404, "图片不存在")
        src = root_of(conn) / row["rel_path"]
        if not src.is_file():
            raise HTTPException(404, "文件不存在")
        out = scan_mod.thumb_path(request.app.state.data_dir, image_id, row["mtime"])
        if not out.is_file():
            try:
                scan_mod.make_thumbnail(src, out)
            except Exception:
                raise HTTPException(404, "文件不是可读取的图片")
        return FileResponse(out, media_type="image/webp", headers=IMMUTABLE)

    @app.get("/api/img/full/{image_id}", dependencies=[Depends(require_auth)])
    def full(image_id: int, conn=Depends(get_db)):
        row = db.get_image(conn, image_id)
        if row is None:
            raise HTTPException(404, "图片不存在")
        src = root_of(conn) / row["rel_path"]
        if not src.is_file():
            raise HTTPException(404, "文件不存在")
        mime = scan_mod.MIME_TYPES.get(
            Path(row["filename"]).suffix.lower(), "application/octet-stream"
        )
        return FileResponse(src, media_type=mime, headers=IMMUTABLE)

    # ---------- 设置 ----------

    @app.get("/api/settings", dependencies=[Depends(require_auth)])
    def read_settings(request: Request, conn=Depends(get_db)):
        cfg = request.app.state.cfg
        return {
            "version": __version__,
            "root": db.get_setting(conn, "root") or "",
            "host": cfg["host"],
            "port": cfg["port"],
            "data_dir": str(request.app.state.data_dir),
        }

    @app.put("/api/settings", dependencies=[Depends(require_auth)])
    def write_settings(body: SettingsBody, request: Request, conn=Depends(get_db)):
        scan_started = False
        if body.root is not None:
            root = Path(body.root.strip())
            if not root.is_dir():
                raise HTTPException(400, f"目录不存在：{body.root}")
            db.set_setting(conn, "root", str(root))
            scan_started = start_scan(request, conn)
        if body.new_password:
            stored = db.get_setting(conn, "password_hash")
            if not auth.verify_password(body.current_password or "", stored):
                # 用 400 而不是 401：401 会被前端当成会话失效而踢回登录页。
                raise HTTPException(400, "当前密码不正确")
            if len(body.new_password) < 4:
                raise HTTPException(400, "新密码至少 4 个字符")
            db.set_setting(conn, "password_hash", auth.hash_password(body.new_password))
        return {"ok": True, "scan_started": scan_started}

    # ---------- 静态文件 ----------

    @app.get("/", include_in_schema=False)
    def index():
        path = web_dir() / "index.html"
        if not path.is_file():
            raise HTTPException(404, "前端文件缺失")
        return FileResponse(path, media_type="text/html; charset=utf-8", headers=NO_CACHE)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    def static_route(name: str, mime: str):
        def handler():
            path = web_dir() / name
            if not path.is_file():
                raise HTTPException(404, "文件不存在")
            return FileResponse(path, media_type=mime, headers=NO_CACHE)
        return handler

    for _name, _mime in STATIC_FILES.items():
        app.add_api_route(f"/{_name}", static_route(_name, _mime), include_in_schema=False)

    return app
