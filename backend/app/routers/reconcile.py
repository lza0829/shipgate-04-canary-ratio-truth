from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db import db, rows_to_list
from app.services.common import RATIO_AUDIT_KIND, audit, now_str, traffic_hint

router = APIRouter(tags=["对账"])

# 比例真源（物化臂）口径声明：
#   真源 = releases.canary_ratio（放行当下物化、在途可改、落定冻结）
#   附件 = promote_events.canary_ratio（放行事件里的比例快照）
# 对账按事件重放出"回放比例"，与真源字段对读：
#   一致        —— 两套数吻合
#   待下次快照  —— 差额由放行后的合法改比例产生（有改比例审计），下一次放行事件会重新对齐
#   脏比例      —— 无改比例审计支撑的差额（事件被外部改坏等半截脏写），纠偏把事件附件改回真源
# 纠偏永远只改事件附件，绝不改真源字段；真源长期唯一。


class RepairIn(BaseModel):
    发版单编号: int


def _ratio_audit_after_event(conn, release_id: int, event_id: int) -> list[dict]:
    """最新放行事件之后发生的改比例审计。

    时间戳只到秒、同秒多笔会丢比较，故按同库单调的自增 id 定序：
    该放行事件的晋升审计行 id 作为分界，之后的改比例审计才能解释
    '回放值 != 真源值'；事件之前的审计已被事件快照吸收，拿来当证据
    会把脏写误判成合法差额。
    """
    boundary = conn.execute(
        "SELECT MAX(id) AS bid FROM audit_events WHERE kind='晋升' AND ref_id=? AND note LIKE ?",
        (release_id, f"事件{event_id}%"),
    ).fetchone()["bid"]
    if boundary is None:  # 旧数据没有事件锚点时退化为不采信，按脏比例处理更安全
        return []
    return conn.execute(
        """
        SELECT note FROM audit_events
        WHERE kind=? AND ref_id=? AND action='修改金丝雀比例' AND id > ?
        ORDER BY id
        """,
        (RATIO_AUDIT_KIND, release_id, boundary),
    ).fetchall()


def _canary_replay(conn) -> list[dict]:
    releases = conn.execute(
        """
        SELECT r.id, r.serial, a.name AS app_name, r.status,
               r.canary_ratio AS materialized,
               (SELECT e.code FROM environments e WHERE e.id = r.current_env_id) AS env_code
        FROM releases r JOIN apps a ON a.id = r.app_id
        ORDER BY r.id
        """
    ).fetchall()
    result = []
    for r in releases:
        latest_event = conn.execute(
            """
            SELECT id, canary_ratio, created_at FROM promote_events
            WHERE release_id=? ORDER BY id DESC LIMIT 1
            """,
            (r["id"],),
        ).fetchone()
        replayed = latest_event["canary_ratio"] if latest_event else None
        materialized = r["materialized"]
        diff = None if replayed is None else materialized - replayed
        if latest_event is None:
            state = "未放行"
        elif diff == 0:
            state = "一致"
        else:
            # 差额是否合法：最新放行事件之后必须有改比例审计，
            # 且审计链的终点就是当前真源值。否则是无来源的脏比例。
            later_audits = _ratio_audit_after_event(conn, r["id"], latest_event["id"])
            legit = bool(later_audits) and any(
                a["note"].endswith(f"-> {materialized}%") for a in later_audits
            )
            state = "待下次快照" if legit else "脏比例"
        result.append(
            {
                "编号": r["id"],
                "发版单号": r["serial"],
                "应用": r["app_name"],
                "状态": r["status"],
                "当前环境": r["env_code"],
                "真源比例": materialized,
                "回放比例": replayed,
                "差额": diff,
                "对账结论": state,
                "流量暗示": traffic_hint(materialized),
                "最新事件编号": latest_event["id"] if latest_event else None,
            }
        )
    return result


@router.get("/对账")
def reconcile():
    with db() as conn:
        release_stats = {
            "申请数": conn.execute("SELECT COUNT(*) AS c FROM releases").fetchone()["c"],
            "已放行": conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status='已放行'"
            ).fetchone()["c"],
            "已回滚": conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status='已回滚'"
            ).fetchone()["c"],
            "在途": conn.execute(
                """
                SELECT COUNT(*) AS c FROM releases
                WHERE status IN ('已入闸','晋升中','已放行','回滚中')
                """
            ).fetchone()["c"],
        }
        version_vs_instance = rows_to_list(
            conn.execute(
                """
                SELECT a.name AS 应用, e.code AS 环境,
                       v.version AS 名册版本,
                       GROUP_CONCAT(i.version, ',') AS 实例版本们,
                       SUM(CASE WHEN i.health='探针红' THEN 1 ELSE 0 END) AS 红灯数
                FROM app_env_versions v
                JOIN apps a ON a.id = v.app_id
                JOIN environments e ON e.id = v.env_id
                LEFT JOIN instances i ON i.app_id = v.app_id AND i.env_id = v.env_id
                GROUP BY v.app_id, v.env_id
                ORDER BY a.id, e.sort_order
                """
            ).fetchall()
        )
        promote_count = conn.execute("SELECT COUNT(*) AS c FROM promote_events").fetchone()["c"]
        canary_rows = _canary_replay(conn)
        canary_summary = {
            "一致": sum(1 for x in canary_rows if x["对账结论"] == "一致"),
            "待下次快照": sum(1 for x in canary_rows if x["对账结论"] == "待下次快照"),
            "脏比例": sum(1 for x in canary_rows if x["对账结论"] == "脏比例"),
            "未放行": sum(1 for x in canary_rows if x["对账结论"] == "未放行"),
        }
        return {
            "发版统计": release_stats,
            "晋升事件数": promote_count,
            "名册与实例": version_vs_instance,
            "比例真源": "releases.canary_ratio（物化字段）",
            "金丝雀对账": canary_rows,
            "金丝雀对账汇总": canary_summary,
        }


@router.post("/对账/金丝雀纠偏")
def repair_canary(body: RepairIn):
    """脏比例纠偏：只把最新放行事件的附件比例改回真源字段，真源不动。

    合法的'待下次快照'不允许纠（那是正常在途状态，没有脏数）。
    """
    with db() as conn:
        r = conn.execute(
            "SELECT id, canary_ratio FROM releases WHERE id=?", (body.发版单编号,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        latest_event = conn.execute(
            "SELECT id, canary_ratio FROM promote_events WHERE release_id=? ORDER BY id DESC LIMIT 1",
            (body.发版单编号,),
        ).fetchone()
        if not latest_event:
            raise HTTPException(400, "无放行事件，无需纠偏")
        if latest_event["canary_ratio"] == r["canary_ratio"]:
            raise HTTPException(400, "事件附件与真源一致，无需纠偏")
        later_audits = _ratio_audit_after_event(conn, body.发版单编号, latest_event["id"])
        legit = bool(later_audits) and any(
            a["note"].endswith(f"-> {r['canary_ratio']}%") for a in later_audits
        )
        if legit:
            raise HTTPException(400, "差额有事件后的改比例审计支撑，属待下次快照，禁止纠偏")
        conn.execute(
            "UPDATE promote_events SET canary_ratio=? WHERE id=?",
            (r["canary_ratio"], latest_event["id"]),
        )
        audit(
            conn,
            "金丝雀",
            body.发版单编号,
            "脏比例纠偏",
            f"事件{latest_event['id']}附件 {latest_event['canary_ratio']}% -> {r['canary_ratio']}%（真源未改）",
        )
        return {"编号": body.发版单编号, "纠偏后比例": r["canary_ratio"], "时间": now_str()}
