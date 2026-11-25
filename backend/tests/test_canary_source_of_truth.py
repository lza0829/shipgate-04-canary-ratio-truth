"""比例真源夹具（物化臂）。

真源 = releases.canary_ratio。覆盖：
1. 先改比例再放行
2. 先放行再改比例
3. 改比例与放行并发双写（库层串行，只许一种真源长期成立）
4. 半截脏比例（无审计支撑的事件损坏，可纠偏且只纠附件）
另含：冻结拒写、校验、总览/健康/对账/审计各面同源对读、0/100 边界。
"""
from __future__ import annotations
import threading

from conftest import admit_flow, create_release, first_release_id, raw_sql


# ---------- 夹具一：先改比例再放行 ----------

def test_change_ratio_then_promote(client):
    rid = first_release_id(client)  # 种子单：已入闸、测、10%
    # 改比例 10 -> 30，同事务落字段+审计
    res = client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": 30})
    assert res.status_code == 200
    assert res.json()["金丝雀比例"] == 30

    # 放行到预：事件快照必须是放行当下的 30
    res = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    assert res.status_code == 200, res.text

    event = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM promote_events WHERE release_id=? ORDER BY id DESC LIMIT 1", (rid,)
    ).fetchone())
    assert event["canary_ratio"] == 30

    # 总览分布格读真源 = 30
    ov = client.get("/api/总览").json()
    row = next(x for x in ov["金丝雀分布"] if x["编号"] == rid)
    assert row["金丝雀比例"] == 30 and row["流量暗示"] == "金丝雀 30%"

    # 对账：真源 30、回放 30、差额 0、一致
    rec = client.get("/api/对账").json()
    cr = next(x for x in rec["金丝雀对账"] if x["编号"] == rid)
    assert (cr["真源比例"], cr["回放比例"], cr["差额"], cr["对账结论"]) == (30, 30, 0, "一致")

    # 健康页实例流量暗示同源
    inst = [x for x in client.get("/api/实例").json() if x["发版单编号"] == rid]
    assert all(x["金丝雀比例"] == 30 and x["流量暗示"] == "金丝雀 30%" for x in inst)

    # 审计有改比例记录
    audits = client.get("/api/审计").json()
    assert any(a["类别"] == "金丝雀" and "30%" in a["备注"] and "10%" in a["备注"] for a in audits)


# ---------- 夹具二：先放行再改比例 ----------

def test_promote_then_change_ratio(client):
    rid = first_release_id(client)  # 10%
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    event_ratio = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM promote_events WHERE release_id=? ORDER BY id DESC LIMIT 1", (rid,)
    ).fetchone())["canary_ratio"]
    assert event_ratio == 10  # 事件附件冻结在 10

    # 放行后（仍在途，状态=晋升中）允许改比例到 50
    res = client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": 50})
    assert res.status_code == 200 and res.json()["金丝雀比例"] == 50

    # 真源 50，事件回放仍是 10：结论必须是"待下次快照"，不是脏比例
    rec = client.get("/api/对账").json()
    cr = next(x for x in rec["金丝雀对账"] if x["编号"] == rid)
    assert cr["真源比例"] == 50 and cr["回放比例"] == 10 and cr["差额"] == 40
    assert cr["对账结论"] == "待下次快照"
    assert rec["金丝雀对账汇总"]["待下次快照"] >= 1

    # 待下次快照禁止纠偏（没有脏数，两套数各有合法身份）
    rep = client.post("/api/对账/金丝雀纠偏", json={"发版单编号": rid})
    assert rep.status_code == 400

    # 再放行一次到产：新事件快照 50，重新对齐；状态落已放行并冻结
    res = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "产"})
    assert res.status_code == 200 and res.json()["状态"] == "已放行"
    rec = client.get("/api/对账").json()
    cr = next(x for x in rec["金丝雀对账"] if x["编号"] == rid)
    assert cr["真源比例"] == 50 and cr["回放比例"] == 50 and cr["对账结论"] == "一致"

    # 冻结后改比例被拒，真源与历史事件都不动
    blocked = client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": 80})
    assert blocked.status_code == 400 and "冻结" in blocked.json()["detail"]
    again = next(x for x in client.get("/api/对账").json()["金丝雀对账"] if x["编号"] == rid)
    assert again["真源比例"] == 50 and again["回放比例"] == 50
    first_event = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM promote_events WHERE release_id=? ORDER BY id ASC LIMIT 1", (rid,)
    ).fetchone())
    assert first_event["canary_ratio"] == 10  # 旧事件附件保持历史快照，不被回改


# ---------- 夹具三：并发双写（改比例撞放行） ----------

def test_concurrent_ratio_change_and_promote(client):
    rid = first_release_id(client)
    errors = []

    def change():
        try:
            r = client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": 45})
            errors.append(("ratio", r.status_code))
        except Exception as e:  # 序列化失败时请求方应收到明确错误而非脏写
            errors.append(("ratio-exc", str(e)))

    def promote():
        try:
            r = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
            errors.append(("promote", r.status_code))
        except Exception as e:
            errors.append(("promote-exc", str(e)))

    t1 = threading.Thread(target=change)
    t2 = threading.Thread(target=promote)
    t1.start(); t2.start(); t1.join(); t2.join()

    # 两笔写在库层 BEGIN IMMEDIATE 串行：成功的写各自完整提交，无半截
    statuses = dict(errors)
    assert statuses.get("ratio") in (200, None)
    assert statuses.get("promote") in (200, None)

    materialized = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio, status FROM releases WHERE id=?", (rid,)
    ).fetchone())
    events = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM promote_events WHERE release_id=? ORDER BY id", (rid,)
    ).fetchall())

    # 只许一种真源长期成立。两种合法交错：
    # A 改比例先提交 -> 真源45，放行事件快照45（全一致）
    # B 放行先提交   -> 事件快照10，真源随后变45（待下次快照，有审计支撑）
    rec = next(x for x in client.get("/api/对账").json()["金丝雀对账"] if x["编号"] == rid)
    if materialized["canary_ratio"] == 45 and events and events[-1]["canary_ratio"] == 45:
        assert rec["对账结论"] == "一致" and rec["差额"] == 0
    else:
        assert events[-1]["canary_ratio"] == 10
        assert materialized["canary_ratio"] == 45
        assert rec["对账结论"] == "待下次快照"
    # 任何交错下都不允许出现无来源脏比例
    assert rec["对账结论"] != "脏比例"


def test_concurrent_two_ratio_writes_single_winner(client):
    rid = first_release_id(client)
    results = []

    def write(v):
        r = client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": v})
        results.append((v, r.status_code))

    t1 = threading.Thread(target=write, args=(20,))
    t2 = threading.Thread(target=write, args=(80,))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert all(code == 200 for _, code in results)
    final = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM releases WHERE id=?", (rid,)
    ).fetchone())["canary_ratio"]
    # 后提交者覆盖，字段只有一个值；两条审计都在，历史可追溯
    assert final in (20, 80)
    notes = raw_sql(lambda c: c.execute(
        "SELECT note FROM audit_events WHERE ref_id=? AND kind='金丝雀'", (rid,)
    ).fetchall())
    assert len(notes) == 2


# ---------- 夹具四：半截脏比例 ----------

def test_dirty_ratio_detected_and_repairable(client):
    rid = first_release_id(client)
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})  # 事件快照 10
    # 模拟半截脏写：事件附件被外部改坏，且没有改比例审计支撑
    raw_sql(lambda c: c.execute(
        "UPDATE promote_events SET canary_ratio=99 WHERE release_id=?", (rid,)
    ))

    rec = client.get("/api/对账").json()
    cr = next(x for x in rec["金丝雀对账"] if x["编号"] == rid)
    assert cr["真源比例"] == 10 and cr["回放比例"] == 99 and cr["差额"] == -89
    assert cr["对账结论"] == "脏比例"
    assert rec["金丝雀对账汇总"]["脏比例"] >= 1

    # 纠偏：只改事件附件，真源字段不动
    rep = client.post("/api/对账/金丝雀纠偏", json={"发版单编号": rid})
    assert rep.status_code == 200 and rep.json()["纠偏后比例"] == 10

    rec2 = client.get("/api/对账").json()
    cr2 = next(x for x in rec2["金丝雀对账"] if x["编号"] == rid)
    assert (cr2["真源比例"], cr2["回放比例"], cr2["对账结论"]) == (10, 10, "一致")
    assert rec2["金丝雀对账汇总"]["脏比例"] == 0

    # 纠偏本身进审计
    audits = client.get("/api/审计").json()
    assert any(a["动作"] == "脏比例纠偏" and "真源未改" in a["备注"] for a in audits)


def test_repair_never_touches_source_field(client):
    rid = first_release_id(client)
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    raw_sql(lambda c: c.execute(
        "UPDATE promote_events SET canary_ratio=77 WHERE release_id=?", (rid,)
    ))
    before = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM releases WHERE id=?", (rid,)
    ).fetchone())["canary_ratio"]
    client.post("/api/对账/金丝雀纠偏", json={"发版单编号": rid})
    after = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM releases WHERE id=?", (rid,)
    ).fetchone())["canary_ratio"]
    assert before == after == 10


def test_audit_before_event_cannot_justify_dirty_after(client):
    """事件之前的改比例审计已被该事件快照吸收，不得为事件之后的脏写背书。"""
    rid = first_release_id(client)
    # 放行前改到 30，再放行：事件快照 30，审计在事件之前
    client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": 30})
    client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    # 事件附件被外部改坏成 7；真源仍是 30，且事件之后没有任何改比例审计
    raw_sql(lambda c: c.execute(
        "UPDATE promote_events SET canary_ratio=7 WHERE release_id=? ORDER BY id DESC LIMIT 1",
        (rid,),
    ))
    rec = client.get("/api/对账").json()
    cr = next(x for x in rec["金丝雀对账"] if x["编号"] == rid)
    assert cr["真源比例"] == 30 and cr["回放比例"] == 7
    assert cr["对账结论"] == "脏比例"  # 不得误判成待下次快照
    rep = client.post("/api/对账/金丝雀纠偏", json={"发版单编号": rid})
    assert rep.status_code == 200
    fixed = next(x for x in client.get("/api/对账").json()["金丝雀对账"] if x["编号"] == rid)
    assert fixed["对账结论"] == "一致" and fixed["回放比例"] == 30


# ---------- 边界与同源对读 ----------

def test_ratio_validation_and_boundaries(client):
    bad = client.post("/api/发版单", json={
        "应用编号": client.get("/api/应用").json()[0]["编号"],
        "目标版本": "x", "金丝雀比例": 101,
    })
    assert bad.status_code == 400
    rid0 = create_release(client, ratio=0)
    rid100 = create_release(client, ratio=100)
    assert client.get(f"/api/发版单/{rid0}").json()["金丝雀比例"] == 0
    assert client.get(f"/api/发版单/{rid100}").json()["金丝雀比例"] == 100

    # 总览流量暗示三态
    admit_flow(client, rid100)
    ov = client.get("/api/总览").json()
    h100 = next(x for x in ov["金丝雀分布"] if x["编号"] == rid100)
    assert h100["流量暗示"] == "全量"


def test_all_faces_read_same_source_after_edits(client):
    rid = create_release(client, ratio=15)
    admit_flow(client, rid)
    client.post(f"/api/发版单/{rid}/金丝雀比例", json={"金丝雀比例": 60})
    # 入闸即落在测，逐级晋升到预
    r = client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
    assert r.status_code == 200

    # 五个面同读 60
    assert client.get(f"/api/发版单/{rid}").json()["金丝雀比例"] == 60
    ov = next(x for x in client.get("/api/总览").json()["金丝雀分布"] if x["编号"] == rid)
    assert ov["金丝雀比例"] == 60
    cr = next(x for x in client.get("/api/对账").json()["金丝雀对账"] if x["编号"] == rid)
    assert cr["真源比例"] == 60 and cr["回放比例"] == 60
    inst = [x for x in client.get("/api/实例").json() if x["发版单编号"] == rid]
    assert inst and all(x["金丝雀比例"] == 60 for x in inst)
    ev = raw_sql(lambda c: c.execute(
        "SELECT canary_ratio FROM promote_events WHERE release_id=?", (rid,)
    ).fetchone())
    assert ev["canary_ratio"] == 60
