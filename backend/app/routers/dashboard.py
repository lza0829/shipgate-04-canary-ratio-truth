from __future__ import annotations
from fastapi import APIRouter
from app.db import db, rows_to_list
from app.services.common import RELEASE_SELECT, traffic_hint

router = APIRouter(tags=["总览"])


@router.get("/总览")
def overview():
    with db() as conn:
        counts = {}
        for name in ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭"):
            counts[name] = conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status=?", (name,)
            ).fetchone()["c"]
        active = rows_to_list(
            conn.execute(
                RELEASE_SELECT
                + " WHERE r.status IN ('已入闸','晋升中','已放行','回滚中') ORDER BY r.id DESC"
            ).fetchall()
        )
        # 金丝雀分布格：直接读真源物化字段，不做事件重放，不另立口径
        canary = rows_to_list(
            conn.execute(
                """
                SELECT r.id AS 编号, r.serial AS 发版单号, a.name AS 应用,
                       e.code AS 环境, r.status AS 状态,
                       r.canary_ratio AS 金丝雀比例
                FROM releases r
                JOIN apps a ON a.id = r.app_id
                LEFT JOIN environments e ON e.id = r.current_env_id
                WHERE r.status IN ('已入闸','晋升中','已放行','回滚中')
                ORDER BY r.id DESC
                """
            ).fetchall()
        )
        for row in canary:
            row["流量暗示"] = traffic_hint(row["金丝雀比例"])
        versions = rows_to_list(
            conn.execute(
                """
                SELECT a.name AS 应用, e.code AS 环境, e.name AS 环境名,
                       v.version AS 版本, v.updated_at AS 更新时间
                FROM app_env_versions v
                JOIN apps a ON a.id = v.app_id
                JOIN environments e ON e.id = v.env_id
                ORDER BY a.id, e.sort_order
                """
            ).fetchall()
        )
        health = rows_to_list(
            conn.execute(
                """
                SELECT i.id AS 编号, a.name AS 应用, e.code AS 环境, i.version AS 版本,
                       i.health AS 健康, i.release_id AS 发版单编号,
                       r.canary_ratio AS 金丝雀比例, i.updated_at AS 更新时间
                FROM instances i
                JOIN apps a ON a.id = i.app_id
                JOIN environments e ON e.id = i.env_id
                LEFT JOIN releases r ON r.id = i.release_id
                ORDER BY a.id, e.sort_order, i.id
                """
            ).fetchall()
        )
        for row in health:
            row["流量暗示"] = traffic_hint(row["金丝雀比例"])
        return {
            "分布": counts,
            "在途": active,
            "金丝雀分布": canary,
            "环境版本": versions,
            "实例": health,
        }
