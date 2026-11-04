"""目录扫描、缩略图，以及 Trash 的物理整理 / 恢复。"""

import os
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps

from . import db

TRASH_DIR = "_trash"
THUMB_MAX_EDGE = 512
SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def image_size(path: Path):
    """只读文件头取尺寸；坏图返回 (None, None)。"""
    try:
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return None, None


def _walk(root: Path, skip_dir: Path):
    """产出 (rel_path, abs_path)，跳过隐藏目录、_trash 与 data 目录。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if not d.startswith(".") and d != TRASH_DIR and (Path(dirpath) / d).resolve() != skip_dir
        )
        for name in sorted(filenames):
            if Path(name).suffix.lower() not in SUPPORTED_EXT:
                continue
            abs_path = Path(dirpath) / name
            yield abs_path.relative_to(root).as_posix(), abs_path


def scan(root: Path, db_path: Path, update) -> None:
    """后台扫描线程主体。update(dict) 用来把进度合并进状态字典。"""
    conn = db.connect(db_path)
    started = time.time()
    counts = {"added": 0, "updated": 0, "missing": 0, "errors": 0, "done": 0}
    try:
        files = list(_walk(root, db_path.parent.resolve()))
        update({"total": len(files), **counts, "started_at": started})
        seen = []
        for i, (rel, abs_path) in enumerate(files, 1):
            try:
                st = abs_path.stat()
                row = conn.execute(
                    "SELECT id, size, mtime, missing FROM images WHERE rel_path = ?",
                    (rel,),
                ).fetchone()
                if row is None:
                    width, height = image_size(abs_path)
                    conn.execute(
                        "INSERT INTO images (rel_path, filename, size, mtime, width, height, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (rel, abs_path.name, st.st_size, st.st_mtime, width, height, time.time()),
                    )
                    counts["added"] += 1
                elif row["size"] != st.st_size or row["mtime"] != st.st_mtime or row["missing"]:
                    width, height = image_size(abs_path)
                    conn.execute(
                        "UPDATE images SET filename = ?, size = ?, mtime = ?, width = ?, "
                        "height = ?, missing = 0 WHERE id = ?",
                        (abs_path.name, st.st_size, st.st_mtime, width, height, row["id"]),
                    )
                    counts["updated"] += 1
                conn.commit()
                seen.append(row["id"] if row else conn.execute(
                    "SELECT id FROM images WHERE rel_path = ?", (rel,)
                ).fetchone()["id"])
            except OSError:
                counts["errors"] += 1
            counts["done"] = i
            if i % 25 == 0 or i == len(files):
                update({**counts})
        conn.execute("DROP TABLE IF EXISTS temp.seen")
        conn.execute("CREATE TEMP TABLE seen (id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO seen (id) VALUES (?)", [(x,) for x in seen])
        cur = conn.execute(
            "UPDATE images SET missing = 1 WHERE missing = 0 "
            "AND rel_path NOT LIKE '_trash/%' AND id NOT IN (SELECT id FROM seen)"
        )
        counts["missing"] = cur.rowcount
        conn.commit()
        update({**counts, "ended_at": time.time()})
    except Exception as exc:  # 扫描失败要留在状态里给前端看
        conn.rollback()
        update({"error": f"{type(exc).__name__}: {exc}", "ended_at": time.time()})
    finally:
        conn.close()


def thumb_path(data_dir: Path, image_id: int, mtime: float) -> Path:
    return data_dir / "thumbs" / f"{image_id}-{int(mtime)}.webp"


def make_thumbnail(src: Path, out: Path) -> None:
    with Image.open(src) as im:
        if getattr(im, "is_animated", False):
            im.seek(0)
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB")
        im.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE), Image.LANCZOS)
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, "WEBP", quality=82, method=4)


def _unique_dest(conn, root: Path, folder: Path, filename: str) -> Path:
    """在 folder 里取一个和磁盘、数据库都不冲突的文件名。"""
    stem, ext = os.path.splitext(filename)
    candidate = folder / filename
    n = 0
    while candidate.exists() or conn.execute(
        "SELECT 1 FROM images WHERE rel_path = ?", (candidate.relative_to(root).as_posix(),)
    ).fetchone():
        n += 1
        candidate = folder / f"{stem}_{n}{ext}"
    return candidate


def organize(conn, root: Path, image_ids) -> tuple[int, list]:
    """把 Trash 中的图移到 <root>/_trash/。只动文件位置，不删任何东西。"""
    moved, failed = 0, []
    trash_dir = root / TRASH_DIR
    for iid in image_ids:
        row = db.get_image(conn, iid)
        if row is None:
            failed.append({"id": iid, "reason": "图片不存在"})
        elif not row["trashed"]:
            failed.append({"id": iid, "reason": "不在 Trash 中"})
        elif row["missing"]:
            failed.append({"id": iid, "reason": "文件已缺失"})
        elif row["rel_path"].startswith(f"{TRASH_DIR}/"):
            failed.append({"id": iid, "reason": "已整理"})
        else:
            src = root / row["rel_path"]
            if not src.is_file():
                failed.append({"id": iid, "reason": "文件不存在"})
                continue
            try:
                dest = _unique_dest(conn, root, trash_dir, src.name)
                trash_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                conn.execute(
                    "UPDATE images SET rel_path = ?, filename = ?, orig_rel_path = ? "
                    "WHERE id = ?",
                    (dest.relative_to(root).as_posix(), dest.name, row["rel_path"], iid),
                )
                conn.commit()
                moved += 1
            except OSError as exc:
                conn.rollback()
                failed.append({"id": iid, "reason": f"移动失败：{exc}"})
    return moved, failed


def restore(conn, root: Path, image_ids) -> tuple[int, list]:
    """把 _trash/ 里的图移回原路径，并取消 Trash 标记。"""
    moved, failed = 0, []
    for iid in image_ids:
        row = db.get_image(conn, iid)
        if row is None:
            failed.append({"id": iid, "reason": "图片不存在"})
        elif not row["rel_path"].startswith(f"{TRASH_DIR}/"):
            failed.append({"id": iid, "reason": "不在 _trash 中"})
        elif not row["orig_rel_path"]:
            failed.append({"id": iid, "reason": "缺少原路径记录"})
        else:
            src = root / row["rel_path"]
            dest = root / row["orig_rel_path"]
            conflict = conn.execute(
                "SELECT 1 FROM images WHERE rel_path = ? AND id != ?",
                (row["orig_rel_path"], iid),
            ).fetchone()
            if not src.is_file():
                failed.append({"id": iid, "reason": "文件不存在"})
            elif dest.exists() or conflict:
                failed.append({"id": iid, "reason": "原位置已被占用"})
            else:
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dest))
                    conn.execute(
                        "UPDATE images SET rel_path = ?, filename = ?, orig_rel_path = NULL, "
                        "trashed = 0, missing = 0 WHERE id = ?",
                        (row["orig_rel_path"], dest.name, iid),
                    )
                    conn.commit()
                    moved += 1
                except OSError as exc:
                    conn.rollback()
                    failed.append({"id": iid, "reason": f"移动失败：{exc}"})
    return moved, failed
