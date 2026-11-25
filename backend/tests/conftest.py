from __future__ import annotations
import os
import tempfile
from pathlib import Path

import pytest

# 在导入应用前指向隔离库，每个测试函数独立一份
_tmp = tempfile.mkdtemp(prefix="shipgate-test-")
os.environ["SHIPGATE_DB"] = str(Path(_tmp) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import db as db_ctx  # noqa: E402


@pytest.fixture()
def client():
    # 每函数重建库：删掉文件后重新播种
    from app import config
    Path(config.DB_PATH).unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
    from app.seed import seed_if_empty
    seed_if_empty()
    with TestClient(app) as c:
        yield c


def first_release_id(client) -> int:
    rows = client.get("/api/发版单").json()
    return rows[0]["编号"]


def admit_flow(client, rid: int) -> None:
    """流水线绿 -> 入闸，种子单已入闸时跳过。"""
    r = client.get(f"/api/发版单/{rid}").json()
    if r["状态"] == "待入闸":
        client.post(f"/api/发版单/{rid}/流水线", json={"流水线": "绿"})
        res = client.post(f"/api/发版单/{rid}/入闸", json={})
        assert res.status_code == 200, res.text


def create_release(client, ratio=None) -> int:
    apps = client.get("/api/应用").json()
    # 用第二个应用：种子在途单挂在第一个应用上，避免并行入闸限制
    app = apps[1] if len(apps) > 1 else apps[0]
    payload = {"应用编号": app["编号"], "目标版本": "9.9.9", "制品摘要": "sha256:t"}
    if ratio is not None:
        payload["金丝雀比例"] = ratio
    res = client.post("/api/发版单", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["编号"]


def raw_sql(fn):
    """绕过 API 直接操作库，模拟半截脏写/外部改坏事件。"""
    with db_ctx() as conn:
        return fn(conn)
