"""ImageRating HTTP API 测试。

按 ``docs/API.md``（唯一契约）断言，不按后端实现猜。
运行：``python -m unittest discover -s tests -v``

每个用例用独立的临时目录作为 ``data_dir`` 与图片根目录，绝不读写仓库里的 ``data/``。
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import create_app  # noqa: E402

try:  # 作为包（discover）导入，或直接 python tests/test_api.py 运行
    from tests import make_samples  # noqa: E402
except ImportError:  # pragma: no cover
    import make_samples  # noqa: E402


PASSWORD = "test1234"
NEW_PASSWORD = "newpass99"
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
CACHE_DIRECTIVES = {"private", "max-age=31536000", "immutable"}


def count_supported_files(root: Path) -> int:
    """磁盘上会被扫描入库的文件数（跳过隐藏目录与 _trash）。"""
    root = Path(root)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "_trash"]
        count += sum(1 for name in filenames if Path(name).suffix.lower() in SUPPORTED_EXTS)
    return count


class ApiTestCase(unittest.TestCase):
    """公共夹具：临时 data_dir + 临时图片根目录 + 已登录 client + 已就绪的扫描。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(prefix="ir-tests-")
        self.tmp = Path(self._tmpdir.name)
        self.data_dir = self.tmp / "data"
        self.img_root = self.tmp / "images"
        self.data_dir.mkdir()
        self.img_root.mkdir()

        self.client = TestClient(create_app(data_dir=str(self.data_dir)))
        self.assert_ok(self.client.post("/api/setup", json={"password": PASSWORD}))
        self.set_root(self.img_root)

    def tearDown(self):
        try:
            self.client.close()
        finally:
            self._tmpdir.cleanup()

    # ---------------- 请求 / 断言助手 ----------------

    def assert_ok(self, response):
        self.assertGreaterEqual(response.status_code, 200, response.text)
        self.assertLess(response.status_code, 300, response.text)
        return response.json()

    def get_json(self, path, **kwargs):
        return self.assert_ok(self.client.get(path, **kwargs))

    def post_json(self, path, payload=None):
        return self.assert_ok(self.client.post(path, json=payload))

    def put_json(self, path, payload):
        return self.assert_ok(self.client.put(path, json=payload))

    def fresh_client(self, name="fresh"):
        """另一个未设置密码的全新应用（隔离 data_dir），用于首次设置/登录测试。"""
        data_dir = self.tmp / name
        data_dir.mkdir()
        client = TestClient(create_app(data_dir=str(data_dir)))
        self.addCleanup(client.close)
        return client

    # ---------------- 扫描助手 ----------------

    def set_root(self, root, timeout=20.0):
        since = time.time()
        data = self.put_json("/api/settings", {"root": str(root)})
        self.assertTrue(data["scan_started"], f"改变 root 应自动触发扫描: {data}")
        self.wait_scan(timeout, since=since)
        return data

    def scan(self, timeout=20.0):
        since = time.time()
        self.assert_ok(self.client.post("/api/scan"))
        return self.wait_scan(timeout, since=since)

    def wait_scan(self, timeout=20.0, since=None):
        deadline = time.monotonic() + timeout
        status = None
        while time.monotonic() < deadline:
            status = self.get_json("/api/scan/status")
            if not status["running"]:
                started = status.get("started_at")
                if since is None or (started is not None and started >= since - 0.001):
                    return status
            time.sleep(0.02)
        self.fail(f"扫描超时（>{timeout}s），最后状态: {status}")

    # ---------------- 数据助手 ----------------

    def images(self, view="all", per_page=200, **params):
        query = {"view": view, "per_page": per_page}
        query.update({k: v for k, v in params.items() if v is not None})
        return self.get_json("/api/images", params=query)

    def items(self, view="all", **params):
        return self.images(view=view, **params)["items"]

    def ids(self, view="all", **params):
        return {item["id"] for item in self.items(view=view, **params)}

    def get_image(self, image_id):
        return self.get_json(f"/api/images/{image_id}")

    def find(self, filename):
        for item in self.items():
            if item["filename"] == filename:
                return item
        return None

    def add_samples(self, count=6, flawed=0):
        """生成样图并扫描，返回 ``{filename: Image}``（文件名在样图里唯一）。"""
        paths = make_samples.generate(self.img_root, count=count, flawed=flawed)
        self.scan()
        items = self.items()
        by_name = {}
        for path in paths:
            matches = [item for item in items if item["filename"] == path.name]
            self.assertEqual(
                len(matches), 1,
                f"磁盘文件 {path.name} 未唯一入库；当前列表={[i['filename'] for i in items]}",
            )
            by_name[path.name] = matches[0]
        return by_name

    def rate(self, image_id, score):
        return self.post_json(f"/api/images/{image_id}/rate", {"score": score})["item"]

    def set_loved(self, image_id, value):
        return self.post_json(f"/api/images/{image_id}/loved", {"loved": value})["item"]

    def set_trash(self, image_id, value):
        return self.post_json(f"/api/images/{image_id}/trash", {"trashed": value})["item"]

    def batch(self, ids, op, **payload):
        body = {"ids": list(ids), "op": op}
        body.update(payload)
        return self.post_json("/api/images/batch", body)

    def create_collection(self, name):
        return self.post_json("/api/collections", {"name": name})

    def collection_images(self, collection_id, ids, action="add"):
        return self.post_json(
            f"/api/collections/{collection_id}/images", {"ids": list(ids), "action": action}
        )

    def assert_cache_control(self, response):
        directives = {
            part.strip().lower() for part in response.headers.get("cache-control", "").split(",")
        }
        self.assertEqual(
            directives, CACHE_DIRECTIVES,
            f"Cache-Control 不符合契约: {response.headers.get('cache-control')!r}",
        )


# =====================================================================
# 1. 鉴权
# =====================================================================


class TestAuth(ApiTestCase):
    def test_unauthenticated_requests_return_401(self):
        client = self.fresh_client()
        for path in (
            "/api/images",
            "/api/images/1",
            "/api/collections",
            "/api/img/thumb/1",
            "/api/img/full/1",
            "/api/settings",
            "/api/scan/status",
        ):
            with self.subTest(method="GET", path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 401, f"GET {path}: {response.text}")
                self.assertIn("detail", response.json())

        for path, payload in (
            ("/api/scan", None),
            ("/api/organize", {"ids": []}),
            ("/api/restore", {"ids": []}),
            ("/api/images/batch", {"ids": [], "op": "rate", "score": 1}),
        ):
            with self.subTest(method="POST", path=path):
                response = client.post(path, json=payload)
                self.assertEqual(response.status_code, 401, f"POST {path}: {response.text}")

        response = client.put("/api/settings", json={"root": str(self.img_root)})
        self.assertEqual(response.status_code, 401, response.text)

    def test_session_needs_setup_flag(self):
        client = self.fresh_client()
        session = client.get("/api/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertFalse(session.json()["authed"])
        self.assertTrue(session.json()["needs_setup"])

        self.assert_ok(client.post("/api/setup", json={"password": PASSWORD}))
        session = client.get("/api/session").json()
        self.assertTrue(session["authed"], "setup 成功即视为登录")
        self.assertFalse(session["needs_setup"])
        self.assert_ok(client.get("/api/images"))

    def test_setup_rules(self):
        client = self.fresh_client()
        response = client.post("/api/setup", json={"password": "123"})
        self.assertEqual(response.status_code, 400, "密码 < 4 字符应 400")
        self.assertTrue(client.get("/api/session").json()["needs_setup"], "失败的 setup 不应设置密码")

        self.assert_ok(client.post("/api/setup", json={"password": "abcd"}))
        response = client.post("/api/setup", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 409, "重复 setup 应 409")
        self.assertTrue(client.get("/api/session").json()["authed"])

    def test_login_rules(self):
        client = self.fresh_client()
        response = client.post("/api/login", json={"password": PASSWORD})
        self.assertEqual(response.status_code, 400, "尚未设置密码时登录应 400")

        self.assert_ok(client.post("/api/setup", json={"password": PASSWORD}))
        self.assert_ok(client.post("/api/logout"))
        self.assertEqual(client.get("/api/images").status_code, 401, "登出后应 401")

        response = client.post("/api/login", json={"password": "wrong-password"})
        self.assertEqual(response.status_code, 401, "错误密码应 401")
        self.assertEqual(client.get("/api/images").status_code, 401)

        self.assert_ok(client.post("/api/login", json={"password": PASSWORD}))
        self.assert_ok(client.get("/api/images"))

    def test_logout(self):
        self.get_json("/api/images")
        self.assert_ok(self.client.post("/api/logout"))
        self.assertEqual(self.client.get("/api/images").status_code, 401)
        self.assert_ok(self.client.post("/api/login", json={"password": PASSWORD}))
        self.get_json("/api/images")


# =====================================================================
# 2. 扫描
# =====================================================================


class TestScan(ApiTestCase):
    def test_scan_imports_files_recursively(self):
        paths = make_samples.generate(self.img_root, count=6)
        status = self.scan()
        self.assertFalse(status["running"])
        self.assertEqual(status["added"], 6, f"扫描状态: {status}")
        self.assertEqual(status["errors"], 0, f"扫描状态: {status}")
        self.assertEqual(status["total"], 6, f"扫描状态: {status}")
        self.assertEqual(status["done"], 6, f"扫描状态: {status}")

        disk_count = count_supported_files(self.img_root)
        self.assertEqual(disk_count, len(paths))
        data = self.images()
        self.assertEqual(data["total"], 6)
        self.assertEqual(len(data["items"]), disk_count, "列表数量应与磁盘文件数一致")

        rel_paths = {item["rel_path"] for item in data["items"]}
        self.assertEqual(len(rel_paths), 6)
        self.assertTrue(any("/" in rel for rel in rel_paths), f"子目录未记入 rel_path: {rel_paths}")

        for item in data["items"]:
            path = self.img_root / item["rel_path"]
            self.assertTrue(path.is_file(), item["rel_path"])
            self.assertEqual(item["size"], path.stat().st_size)
            self.assertAlmostEqual(item["mtime"], path.stat().st_mtime, delta=1.0)
            with Image.open(path) as image:
                self.assertEqual((item["width"], item["height"]), image.size)
            # 新入库默认值
            self.assertIsNone(item["score"])
            self.assertFalse(item["loved"])
            self.assertFalse(item["trashed"])
            self.assertFalse(item["organized"])
            self.assertFalse(item["missing"])
            self.assertIsNone(item["orig_rel_path"])
            self.assertIsNone(item["rated_at"])
            self.assertEqual(item["collections"], [])
            self.assertIn(f"/api/img/thumb/{item['id']}", item["thumb_url"])
            self.assertIn(f"/api/img/full/{item['id']}", item["full_url"])

    def test_rescan_is_incremental(self):
        make_samples.generate(self.img_root, count=4)
        self.scan()
        status = self.scan()
        self.assertEqual(status["added"], 0, f"重复扫描 added 应为 0: {status}")
        self.assertEqual(status["updated"], 0, f"未变化的文件不应更新: {status}")
        self.assertEqual(status["missing"], 0, f"扫描状态: {status}")
        self.assertEqual(self.images()["total"], 4)

    def test_rescan_detects_new_file(self):
        make_samples.generate(self.img_root, count=3)
        self.scan()
        make_samples.make_image(
            self.img_root / "batch" / "extra_frame.png", size=512, kind="grid", seed=31
        )
        status = self.scan()
        self.assertEqual(status["added"], 1, f"新增 1 个文件应 added=1: {status}")
        data = self.images()
        self.assertEqual(data["total"], 4)
        self.assertIsNotNone(self.find("extra_frame.png"))
        self.assertEqual(data["items"][0]["filename"], "extra_frame.png", "默认按 newest 排序")

    def test_deleted_file_becomes_missing(self):
        paths = make_samples.generate(self.img_root, count=3)
        self.scan()
        victim = paths[0]
        victim.unlink()
        status = self.scan()
        self.assertGreaterEqual(status["missing"], 1, f"删除磁盘文件后应标记 missing: {status}")

        data = self.images()
        self.assertEqual(data["total"], 2, "missing 默认从列表排除")
        self.assertIsNone(self.find(victim.name), "missing 的图不应出现在默认列表")
        self.assertEqual(data["stats"]["total"], 2, "stats 不计 missing")

        # 文件重新出现后 missing 恢复
        make_samples.make_image(victim, size=768, kind="gradient", seed=52)
        status = self.scan()
        self.assertEqual(status["added"], 0, "行已存在，重新出现不算 added")
        self.assertEqual(self.images()["total"], 3)
        self.assertIsNotNone(self.find(victim.name))


# =====================================================================
# 3. 评分联动
# =====================================================================


class TestRating(ApiTestCase):
    def test_stars_set_score_and_keep_loved(self):
        images = self.add_samples(count=2)
        target = next(iter(images.values()))
        payload = self.set_loved(target["id"], True)
        self.assertTrue(payload["loved"])

        for score in range(1, 6):
            with self.subTest(score=score):
                item = self.rate(target["id"], score)
                self.assertEqual(item["score"], score)
                self.assertFalse(item["trashed"], f"打 {score} 星不应在 Trash 里")
                self.assertTrue(item["loved"], "评分不应改变 loved")
                self.assertIsNotNone(item["rated_at"], "rated_at 应被设置")
                self.assertGreater(item["rated_at"], 0)
                self.assertLessEqual(item["rated_at"], time.time() + 60)
                self.assertIn(target["id"], self.ids("score", score=score))
        self.assertNotIn(target["id"], self.ids("trash"))

    def test_zero_score_enters_trash(self):
        images = self.add_samples(count=2)
        target = next(iter(images.values()))
        total_before = self.images()["total"]

        item = self.rate(target["id"], 0)
        self.assertEqual(item["score"], 0)
        self.assertTrue(item["trashed"], "score=0 应自动进 Trash")
        self.assertIn(target["id"], self.ids("trash"))
        # view=all 只排除 missing，Trash 中的图仍在 all 里
        self.assertEqual(self.images()["total"], total_before)
        self.assertIn(target["id"], self.ids())
        # view=score 排除 trashed：0 分图只在 trash 视图看
        self.assertNotIn(target["id"], self.ids("score", score=0))
        self.assertEqual(self.images()["stats"]["trash"], 1)

    def test_rating_trashed_image_restores_it(self):
        images = self.add_samples(count=2)
        target = next(iter(images.values()))
        self.rate(target["id"], 0)
        self.assertIn(target["id"], self.ids("trash"))

        item = self.rate(target["id"], 4)
        self.assertEqual(item["score"], 4)
        self.assertFalse(item["trashed"], "对 Trash 中的图打 4 分应移出 Trash")
        self.assertIn(target["id"], self.ids("score", score=4))
        self.assertNotIn(target["id"], self.ids("trash"))
        self.assertEqual(self.images()["stats"]["trash"], 0)

    def test_null_score_clears_score_only(self):
        images = self.add_samples(count=3)
        first, second, _ = list(images.values())

        self.rate(first["id"], 5)
        item = self.rate(first["id"], None)
        self.assertIsNone(item["score"])
        self.assertFalse(item["trashed"], "清空分数不应把图放进 Trash")
        self.assertIn(first["id"], self.ids("unrated"))

        self.rate(second["id"], 0)
        self.assertIn(second["id"], self.ids("trash"))
        item = self.rate(second["id"], None)
        self.assertIsNone(item["score"])
        self.assertTrue(item["trashed"], "清空分数不应改变 trashed")
        self.assertIn(second["id"], self.ids("trash"))
        self.assertNotIn(second["id"], self.ids("unrated"), "trashed 的图不算 unrated")

    def test_invalid_score_rejected(self):
        images = self.add_samples(count=1)
        target = next(iter(images.values()))
        for bad in (6, -1, 99):
            with self.subTest(score=bad):
                response = self.client.post(
                    f"/api/images/{target['id']}/rate", json={"score": bad}
                )
                self.assertIn(
                    response.status_code, (400, 422),
                    f"非法分数 {bad} 应被拒绝，实际 {response.status_code}: {response.text}",
                )
                self.assertIsNone(self.get_image(target["id"])["score"])


# =====================================================================
# 4. loved
# =====================================================================


class TestLoved(ApiTestCase):
    def test_loved_toggle_and_filter(self):
        images = self.add_samples(count=3)
        target = next(iter(images.values()))

        item = self.set_loved(target["id"], True)
        self.assertTrue(item["loved"])
        loved = self.images("loved")
        self.assertEqual(loved["total"], 1)
        self.assertEqual({i["id"] for i in loved["items"]}, {target["id"]})
        self.assertEqual(self.images()["stats"]["loved"], 1)

        item = self.set_loved(target["id"], False)
        self.assertFalse(item["loved"])
        self.assertEqual(self.images("loved")["total"], 0)
        self.assertEqual(self.images()["stats"]["loved"], 0)

    def test_loved_crosses_score_filter(self):
        images = self.add_samples(count=3)
        a, b, c = list(images.values())
        self.rate(a["id"], 4)
        self.set_loved(a["id"], True)
        self.rate(b["id"], 5)
        self.set_loved(c["id"], True)  # 未评分但收藏

        self.assertEqual(self.ids("loved"), {a["id"], c["id"]})
        self.assertEqual(self.ids("score", score=4), {a["id"]})
        self.assertEqual(self.ids("score", score=5), {b["id"]})
        self.assertEqual(self.images()["stats"]["loved"], 2)

        item = self.get_image(a["id"])
        self.assertTrue(item["loved"], "同一张图可同时有分数与 loved")
        self.assertEqual(item["score"], 4)


# =====================================================================
# 5. Collections
# =====================================================================


class TestCollections(ApiTestCase):
    def test_create_and_list(self):
        collection = self.create_collection(" 精选 ")
        self.assertEqual(collection["name"], "精选", "名称首尾空白应去掉")
        self.assertIsInstance(collection["id"], int)
        self.assertEqual(collection["count"], 0)
        self.assertIsInstance(collection["created_at"], (int, float))

        second = self.create_collection("待定")
        listed = self.get_json("/api/collections")
        self.assertEqual([c["id"] for c in listed], [collection["id"], second["id"]], "按创建时间排序")
        self.assertEqual(listed[0]["name"], "精选")

    def test_duplicate_and_invalid_names(self):
        cid = self.create_collection("精选")["id"]
        self.assertEqual(self.client.post("/api/collections", json={"name": "精选"}).status_code, 409)
        self.assertEqual(
            self.client.post("/api/collections", json={"name": "  精选  "}).status_code, 409,
            "去空白后重名也应 409",
        )
        for bad in ("", "   ", "x" * 51):
            with self.subTest(name=bad):
                response = self.client.post("/api/collections", json={"name": bad})
                self.assertEqual(response.status_code, 400, f"非法名称 {bad!r}: {response.text}")
        self.assertEqual(len(self.get_json("/api/collections")), 1, f"非法名称不应入库（{cid}）")

    def test_add_remove_members_and_count(self):
        images = self.add_samples(count=6)
        all_ids = [item["id"] for item in images.values()]
        five = all_ids[:5]
        cid = self.create_collection("五张")["id"]

        self.assertEqual(self.collection_images(cid, five)["count"], 5)
        view = self.images("collection", collection=cid)
        self.assertEqual(view["total"], 5)
        self.assertEqual({item["id"] for item in view["items"]}, set(five))

        listed = {c["id"]: c for c in self.get_json("/api/collections")}
        self.assertEqual(listed[cid]["count"], 5)
        for image_id in five:
            self.assertEqual([c["id"] for c in self.get_image(image_id)["collections"]], [cid])

        # 重复加入不重复计数
        self.assertEqual(self.collection_images(cid, five)["count"], 5)

        # 移除两张
        self.assertEqual(self.collection_images(cid, five[:2], action="remove")["count"], 3)
        view = self.images("collection", collection=cid)
        self.assertEqual(view["total"], 3)
        self.assertEqual({item["id"] for item in view["items"]}, set(five[2:]))
        self.assertEqual(self.get_image(five[0])["collections"], [])

    def test_image_can_belong_to_two_collections(self):
        images = self.add_samples(count=3)
        target, other, _ = list(images.values())
        first = self.create_collection("甲")["id"]
        second = self.create_collection("乙")["id"]
        self.collection_images(first, [target["id"]])
        self.collection_images(second, [target["id"], other["id"]])

        item = self.get_image(target["id"])
        self.assertEqual(sorted(c["name"] for c in item["collections"]), ["乙", "甲"])
        listed = {c["id"]: c for c in self.get_json("/api/collections")}
        self.assertEqual(listed[first]["count"], 1)
        self.assertEqual(listed[second]["count"], 2)
        self.assertEqual(self.ids("collection", collection=first), {target["id"]})
        self.assertEqual(self.ids("collection", collection=second), {target["id"], other["id"]})

    def test_delete_collection_keeps_images(self):
        images = self.add_samples(count=3)
        ids = [item["id"] for item in images.values()]
        cid = self.create_collection("临时")["id"]
        self.collection_images(cid, ids)
        total_before = self.images()["total"]

        response = self.client.delete(f"/api/collections/{cid}")
        self.assertTrue(self.assert_ok(response)["ok"])
        self.assertNotIn(cid, [c["id"] for c in self.get_json("/api/collections")])
        self.assertEqual(self.images()["total"], total_before, "删除 Collection 不应动图片")
        for image_id in ids:
            self.assertEqual(self.get_image(image_id)["collections"], [])

    def test_rename_collection(self):
        images = self.add_samples(count=2)
        target = next(iter(images.values()))
        cid = self.create_collection("旧名")["id"]
        self.collection_images(cid, [target["id"]])

        renamed = self.assert_ok(
            self.client.patch(f"/api/collections/{cid}", json={"name": " 新名 "})
        )
        self.assertEqual(renamed["name"], "新名")
        self.assertEqual(renamed["count"], 1)
        self.assertEqual(
            {c["id"]: c for c in self.get_json("/api/collections")}[cid]["name"], "新名"
        )
        self.assertEqual([c["name"] for c in self.get_image(target["id"])["collections"]], ["新名"])

        other = self.create_collection("另一个")["id"]
        response = self.client.patch(f"/api/collections/{other}", json={"name": "新名"})
        self.assertEqual(response.status_code, 409, "改名撞重名应 409")


# =====================================================================
# 6. 批量操作
# =====================================================================


class TestBatch(ApiTestCase):
    def test_batch_rate(self):
        images = self.add_samples(count=4)
        all_ids = [item["id"] for item in images.values()]
        ids = all_ids[:3]
        self.assertEqual(self.batch(ids, "rate", score=3)["updated"], 3)
        for image_id in ids:
            item = self.get_image(image_id)
            self.assertEqual(item["score"], 3)
            self.assertFalse(item["trashed"])
            self.assertIsNotNone(item["rated_at"])
        self.assertIsNone(self.get_image(all_ids[3])["score"], "未传入的图不应被修改")

    def test_batch_loved(self):
        images = self.add_samples(count=3)
        ids = [item["id"] for item in list(images.values())[:2]]
        self.assertEqual(self.batch(ids, "loved", loved=True)["updated"], 2)
        for image_id in ids:
            self.assertTrue(self.get_image(image_id)["loved"])
        self.assertEqual(self.ids("loved"), set(ids))
        self.assertEqual(self.batch(ids, "loved", loved=False)["updated"], 2)
        self.assertEqual(self.ids("loved"), set())

    def test_batch_trash(self):
        images = self.add_samples(count=3)
        ids = [item["id"] for item in list(images.values())[:2]]
        self.assertEqual(self.batch(ids, "trash", trashed=True)["updated"], 2)
        for image_id in ids:
            item = self.get_image(image_id)
            self.assertTrue(item["trashed"])
        self.assertEqual(self.ids("trash"), set(ids))
        self.assertEqual(self.images()["stats"]["trash"], 2)

    def test_batch_rate_untrashes_from_trash(self):
        images = self.add_samples(count=3)
        ids = [item["id"] for item in images.values()]
        self.batch(ids, "rate", score=0)
        self.assertEqual(self.ids("trash"), set(ids))

        self.assertEqual(self.batch(ids, "rate", score=5)["updated"], 3)
        for image_id in ids:
            item = self.get_image(image_id)
            self.assertEqual(item["score"], 5)
            self.assertFalse(item["trashed"], "批量打 5 星应移出 Trash")
        self.assertEqual(self.ids("trash"), set())

    def test_batch_ignores_unknown_ids(self):
        images = self.add_samples(count=2)
        ids = [item["id"] for item in images.values()]
        result = self.batch([*ids, 999999], "rate", score=2)
        self.assertEqual(result["updated"], 2, "不存在的 id 应静默忽略")
        for image_id in ids:
            self.assertEqual(self.get_image(image_id)["score"], 2)

    # ---------------- 撤回用的精确状态回填 ----------------

    def test_batch_state_restores_exact_meta(self):
        images = self.add_samples(count=2)
        ids = [item["id"] for item in images.values()]
        self.batch(ids, "rate", score=4)
        self.batch(ids, "loved", loved=True)

        data = self.post_json("/api/images/batch", {
            "op": "state",
            "items": [{"id": image_id, "score": None, "trashed": False, "loved": False} for image_id in ids],
        })
        self.assertEqual(data["updated"], 2)
        for image_id in ids:
            item = self.get_image(image_id)
            self.assertIsNone(item["score"])
            self.assertFalse(item["trashed"])
            self.assertFalse(item["loved"])
        self.assertEqual(self.ids("loved"), set())

    def test_batch_state_only_touches_given_fields(self):
        image_id = next(iter(self.add_samples(count=1).values()))["id"]
        self.batch([image_id], "rate", score=0)  # 0 分 → 进 Trash

        # 只回填 score，trashed 保持不变（不套 rate 的联动规则）
        self.post_json("/api/images/batch", {"op": "state", "items": [{"id": image_id, "score": 5}]})
        item = self.get_image(image_id)
        self.assertEqual(item["score"], 5)
        self.assertTrue(item["trashed"])

    def test_batch_state_rejects_bad_score(self):
        image_id = next(iter(self.add_samples(count=1).values()))["id"]
        response = self.client.post(
            "/api/images/batch", json={"op": "state", "items": [{"id": image_id, "score": 9}]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.get_image(image_id)["score"])

    def test_batch_state_ignores_unknown_id(self):
        image_id = next(iter(self.add_samples(count=1).values()))["id"]
        data = self.post_json("/api/images/batch", {
            "op": "state",
            "items": [{"id": 999999, "score": 3}, {"id": image_id, "loved": True}],
        })
        self.assertEqual(data["updated"], 1)
        self.assertTrue(self.get_image(image_id)["loved"])


# =====================================================================
# 7. stats 计数
# =====================================================================


class TestStats(ApiTestCase):
    def test_stats_counts(self):
        images = self.add_samples(count=8)
        a, b, c, d, e, f, g, h = list(images.values())

        self.rate(a["id"], 5)
        self.rate(b["id"], 4)
        self.rate(c["id"], 1)
        self.rate(d["id"], 0)  # score 0 → Trash
        self.rate(e["id"], 0)  # score 0 → Trash
        self.set_loved(a["id"], True)
        self.set_loved(b["id"], True)
        self.set_trash(g["id"], True)  # 未评分但手动 Trash
        # f 保持未评分；h 从磁盘删除 → missing（不计入任何统计）
        (self.img_root / h["rel_path"]).unlink()
        self.scan()

        stats = self.images()["stats"]
        self.assertEqual(stats["total"], 7, f"missing 不计入 total: {stats}")
        self.assertEqual(stats["unrated"], 1, f"unrated = 未评分且未进 Trash: {stats}")
        self.assertEqual(stats["loved"], 2, f"{stats}")
        self.assertEqual(stats["trash"], 3, f"{stats}")
        self.assertEqual(
            stats["scores"],
            {"0": 0, "1": 1, "2": 0, "3": 0, "4": 1, "5": 1},
            f"scores 只统计未进 Trash 的图，scores['0'] 恒为 0: {stats}",
        )

        # 与筛选视图交叉校验
        self.assertEqual(self.images("unrated")["total"], stats["unrated"])
        self.assertEqual(self.images("trash")["total"], stats["trash"])
        self.assertEqual(self.images("loved")["total"], stats["loved"])
        self.assertEqual(self.images("score", score=5)["total"], 1)
        self.assertEqual(self.images("score", score=4)["total"], 1)
        self.assertEqual(self.images("score", score=0)["total"], 0, "0 分图都在 Trash 里")


# =====================================================================
# 8. 物理整理 / 恢复
# =====================================================================


class TestOrganize(ApiTestCase):
    def test_organize_then_restore(self):
        images = self.add_samples(count=2)
        target, other = list(images.values())
        before = self.get_image(target["id"])
        orig_rel = before["rel_path"]
        orig_path = self.img_root / orig_rel
        self.assertTrue(orig_path.is_file())
        self.rate(target["id"], 0)

        result = self.post_json("/api/organize", {"ids": [target["id"], other["id"]]})
        self.assertEqual(result["moved"], 1, f"{result}")
        failed_ids = [entry["id"] for entry in result["failed"]]
        self.assertIn(other["id"], failed_ids, "非 Trash 的 id 应进 failed")
        self.assertNotIn(target["id"], failed_ids)
        for entry in result["failed"]:
            self.assertIn("reason", entry)

        self.assertTrue((self.img_root / "_trash").is_dir(), "应创建 <root>/_trash/")
        item = self.get_image(target["id"])
        self.assertTrue(item["organized"])
        self.assertTrue(item["trashed"])
        self.assertTrue(item["rel_path"].startswith("_trash/"), item["rel_path"])
        self.assertEqual(item["orig_rel_path"], orig_rel)
        moved_path = self.img_root / item["rel_path"]
        self.assertTrue(moved_path.is_file(), "文件应真的在 _trash/ 下")
        self.assertFalse(orig_path.exists(), "原路径应消失")
        self.assertEqual(item["size"], before["size"], "整理不应改变 size")
        self.assertAlmostEqual(item["mtime"], before["mtime"], delta=1e-6, msg="整理不应改变 mtime")

        # restore
        result = self.post_json("/api/restore", {"ids": [target["id"]]})
        self.assertEqual(result["moved"], 1, f"{result}")
        item = self.get_image(target["id"])
        self.assertFalse(item["organized"])
        self.assertFalse(item["trashed"], "恢复后应移出 Trash")
        self.assertIsNone(item["orig_rel_path"])
        self.assertEqual(item["rel_path"], orig_rel)
        self.assertTrue(orig_path.is_file(), "文件应回到原路径")
        self.assertFalse(moved_path.exists())
        self.assertEqual(item["size"], before["size"])

    def test_organize_name_conflict_gets_suffix(self):
        make_samples.make_image(self.img_root / "set_a" / "same.png", size=512, kind="grid", seed=11)
        make_samples.make_image(self.img_root / "set_b" / "same.png", size=512, kind="noise", seed=12)
        self.scan()
        by_rel = {item["rel_path"]: item for item in self.items()}
        self.assertIn("set_a/same.png", by_rel)
        self.assertIn("set_b/same.png", by_rel)
        ids = [by_rel["set_a/same.png"]["id"], by_rel["set_b/same.png"]["id"]]
        for image_id in ids:
            self.rate(image_id, 0)

        result = self.post_json("/api/organize", {"ids": ids})
        self.assertEqual(result["moved"], 2, f"{result}")
        rel_paths = [self.get_image(image_id)["rel_path"] for image_id in ids]
        self.assertEqual(len(set(rel_paths)), 2, f"重名文件不能互相覆盖: {rel_paths}")
        for rel in rel_paths:
            self.assertTrue(rel.startswith("_trash/"), rel)
            self.assertTrue((self.img_root / rel).is_file(), rel)
        names = sorted(Path(rel).name for rel in rel_paths)
        self.assertEqual(names, ["same.png", "same_1.png"], f"重名应加 _1 后缀: {rel_paths}")

    def test_scan_does_not_mark_organized_as_missing(self):
        images = self.add_samples(count=2)
        target = next(iter(images.values()))
        self.rate(target["id"], 0)
        self.post_json("/api/organize", {"ids": [target["id"]]})

        status = self.scan()
        self.assertEqual(status["missing"], 0, f"_trash/ 里的图不应被标记 missing: {status}")
        item = self.get_image(target["id"])
        self.assertFalse(item["missing"])
        self.assertIn(target["id"], self.ids("trash"))
        self.assertEqual(count_supported_files(self.img_root), 1, "_trash 目录不应被扫描")

    def test_restore_fails_when_original_path_occupied(self):
        images = self.add_samples(count=1)
        target = next(iter(images.values()))
        before = self.get_image(target["id"])
        orig_path = self.img_root / before["rel_path"]
        self.rate(target["id"], 0)
        self.post_json("/api/organize", {"ids": [target["id"]]})

        # 原路径被新文件占用
        make_samples.make_image(orig_path, size=256, kind="grid", seed=99)
        result = self.post_json("/api/restore", {"ids": [target["id"]]})
        self.assertEqual(result["moved"], 0, f"{result}")
        self.assertIn(target["id"], [entry["id"] for entry in result["failed"]], f"{result}")

        item = self.get_image(target["id"])
        self.assertTrue(item["organized"], "恢复失败不应改变状态")
        self.assertTrue(item["trashed"])
        self.assertTrue((self.img_root / item["rel_path"]).is_file(), "文件应仍在 _trash/")


# =====================================================================
# 9. 图片内容
# =====================================================================


class TestImageContent(ApiTestCase):
    def test_thumb_is_webp_within_512(self):
        make_samples.make_image(self.img_root / "big.png", size=1024, kind="gradient", seed=61)
        self.scan()
        target = self.find("big.png")
        self.assertIsNotNone(target)

        response = self.client.get(target["thumb_url"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"].split(";")[0].strip(), "image/webp")
        self.assert_cache_control(response)
        with Image.open(io.BytesIO(response.content)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertLessEqual(max(image.size), 512, f"缩略图最长边应 ≤512: {image.size}")
            self.assertEqual(image.size[0], image.size[1], "正方形原图缩略图仍应为正方形")

    def test_full_returns_original_bytes(self):
        make_samples.make_image(self.img_root / "origin.png", size=768, kind="shapes", seed=62)
        self.scan()
        target = self.find("origin.png")
        source = self.img_root / target["rel_path"]

        response = self.client.get(target["full_url"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"].split(";")[0].strip(), "image/png")
        self.assert_cache_control(response)
        self.assertEqual(response.content, source.read_bytes(), "full 应返回原图字节")

    def test_full_content_type_follows_extension(self):
        make_samples.make_image(self.img_root / "one.jpg", size=512, kind="grid", seed=63)
        make_samples.make_image(self.img_root / "one.webp", size=512, kind="shapes", seed=64)
        self.scan()
        for filename, expected in (
            ("one.jpg", "image/jpeg"),
            ("one.webp", "image/webp"),
        ):
            with self.subTest(filename=filename):
                item = self.find(filename)
                self.assertIsNotNone(item)
                response = self.client.get(item["full_url"])
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    response.headers["content-type"].split(";")[0].strip(), expected
                )

    def test_image_endpoints_require_auth(self):
        client = self.fresh_client()
        for path in ("/api/img/thumb/1", "/api/img/full/1"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 401)

    def test_unknown_id_returns_404(self):
        for path in ("/api/img/thumb/999999", "/api/img/full/999999"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404, response.text)

    def test_missing_file_returns_404(self):
        images = self.add_samples(count=1)
        target = next(iter(images.values()))
        (self.img_root / target["rel_path"]).unlink()

        for url in (target["thumb_url"], target["full_url"]):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(response.json()["detail"], "文件不存在")


# =====================================================================
# 10. 设置
# =====================================================================


class TestSettings(ApiTestCase):
    def test_get_settings(self):
        data = self.get_json("/api/settings")
        self.assertEqual(Path(data["root"]).resolve(), self.img_root.resolve())
        for key in ("host", "port", "data_dir", "version"):
            self.assertIn(key, data)
        self.assertEqual(Path(data["data_dir"]).resolve(), self.data_dir.resolve())

    def test_invalid_root_rejected(self):
        missing = self.tmp / "does_not_exist"
        response = self.client.put("/api/settings", json={"root": str(missing)})
        self.assertEqual(response.status_code, 400, "不存在的目录应 400")

        as_file = self.tmp / "not_a_dir.txt"
        as_file.write_text("x", encoding="utf-8")
        response = self.client.put("/api/settings", json={"root": str(as_file)})
        self.assertEqual(response.status_code, 400, "文件不是目录，应 400")

        current = self.get_json("/api/settings")
        self.assertEqual(Path(current["root"]).resolve(), self.img_root.resolve(), "root 不应被改动")

    def test_change_password(self):
        self.assert_ok(
            self.client.put(
                "/api/settings",
                json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
            )
        )
        self.get_json("/api/images")  # 改密码后当前会话仍应有效

        self.assert_ok(self.client.post("/api/logout"))
        self.assertEqual(
            self.client.post("/api/login", json={"password": PASSWORD}).status_code, 401,
            "旧密码应失效",
        )
        self.assert_ok(self.client.post("/api/login", json={"password": NEW_PASSWORD}))
        self.get_json("/api/images")

    def test_change_password_requires_current(self):
        response = self.client.put("/api/settings", json={"new_password": NEW_PASSWORD})
        self.assertEqual(response.status_code, 400, f"缺少 current_password: {response.text}")

        response = self.client.put(
            "/api/settings",
            json={"current_password": "wrong-password", "new_password": NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 400, f"当前密码错误应 400: {response.text}")

        # 密码没有被改动
        self.assert_ok(self.client.post("/api/logout"))
        self.assert_ok(self.client.post("/api/login", json={"password": PASSWORD}))

    def test_change_root_triggers_scan(self):
        new_root = self.tmp / "newroot"
        new_root.mkdir()
        make_samples.generate(new_root, count=3)

        data = self.set_root(new_root)
        self.assertTrue(data["scan_started"])
        self.assertEqual(Path(self.get_json("/api/settings")["root"]).resolve(), new_root.resolve())

        images = self.images()
        self.assertEqual(images["total"], 3, "改 root 后应自动扫描新目录")
        self.assertIsNotNone(self.find("ComfyUI_00001_.png"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
