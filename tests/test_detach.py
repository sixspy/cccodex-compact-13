import threading

import pytest

from app.db import get_db
from app.services import files, plans, reconcile, rewrite
from app.services.errors import ServiceError


def _make_plan(db, code="CP-D1", table="dw_payments"):
    p = plans.create_plan(code, "拆项计划", table, db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    return p


def _plan_row(db, plan_id):
    return [
        p for p in plans.list_plans(db_path=db) if p["id"] == plan_id
    ][0]


def test_detach_shrinks_bytes_and_returns_file(db):
    p = _make_plan(db)
    before = _plan_row(db, p["id"])
    detail = plans.plan_detail(p["id"], db_path=db)
    target = detail["items"][0]

    out = plans.detach_plan_item(p["id"], target["id"], operator="admin", db_path=db)

    after = _plan_row(db, p["id"])
    assert after["plan_bytes"] == before["plan_bytes"] - target["size_bytes"]
    assert after["item_count"] == before["item_count"] - 1
    assert out["plan_bytes"] == after["plan_bytes"]
    # 碎件回写碎文件态
    f = [x for x in files.list_files(db_path=db) if x["id"] == target["id"]][0]
    assert f["status"] == "碎文件"
    # 库表可核凭证行
    with get_db(db) as conn:
        v = conn.execute(
            "SELECT * FROM detach_vouchers WHERE plan_id=? AND file_id=?",
            (p["id"], target["id"]),
        ).fetchone()
    assert v is not None
    assert v["size_bytes"] == target["size_bytes"]
    assert v["operator"] == "admin"
    # 详情带退挂记录
    detail2 = plans.plan_detail(p["id"], db_path=db)
    assert [d["file_id"] for d in detail2["detaches"]] == [target["id"]]
    assert target["id"] not in [i["id"] for i in detail2["items"]]


def test_detached_item_not_merged_and_reconcile_ok(db):
    p = _make_plan(db)
    detail = plans.plan_detail(p["id"], db_path=db)
    target = detail["items"][0]
    plans.detach_plan_item(p["id"], target["id"], db_path=db)
    plans.publish_plan(p["id"], db_path=db)

    job = rewrite.start_rewrite(p["id"], db_path=db)
    assert job["status"] == "成功"
    merged_ids = {
        f["id"]
        for f in files.list_files(db_path=db)
        if f["status"] == "已合并"
    }
    assert target["id"] not in merged_ids
    # 拆项后再核对体积才收：前后一致
    report = reconcile.run_reconcile(p["id"], db_path=db)
    assert report["before_bytes"] == report["after_bytes"]


def test_double_detach_rejected(db):
    p = _make_plan(db)
    fid = plans.plan_detail(p["id"], db_path=db)["items"][0]["id"]
    plans.detach_plan_item(p["id"], fid, db_path=db)
    with pytest.raises(ServiceError) as exc:
        plans.detach_plan_item(p["id"], fid, db_path=db)
    assert exc.value.status_code in (404, 409)
    with get_db(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM detach_vouchers WHERE plan_id=? AND file_id=?",
            (p["id"], fid),
        ).fetchone()["c"]
    assert n == 1


def test_concurrent_detach_only_one_wins(db):
    p = _make_plan(db)
    fid = plans.plan_detail(p["id"], db_path=db)["items"][0]["id"]
    results, errors = [], []

    def worker():
        try:
            results.append(plans.detach_plan_item(p["id"], fid, db_path=db))
        except ServiceError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1
    assert len(errors) == 1
    with get_db(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM detach_vouchers WHERE plan_id=? AND file_id=?",
            (p["id"], fid),
        ).fetchone()["c"]
    assert n == 1
    f = [x for x in files.list_files(db_path=db) if x["id"] == fid][0]
    assert f["status"] == "碎文件"


def test_detached_item_not_reattached(db):
    p = _make_plan(db)
    fid = plans.plan_detail(p["id"], db_path=db)["items"][0]["id"]
    plans.detach_plan_item(p["id"], fid, db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    detail = plans.plan_detail(p["id"], db_path=db)
    assert fid not in [i["id"] for i in detail["items"]]


def test_detach_guards(db):
    p = _make_plan(db)
    with pytest.raises(ServiceError) as exc:
        plans.detach_plan_item(p["id"], 999999, db_path=db)
    assert exc.value.status_code == 404
    with pytest.raises(ServiceError) as exc:
        plans.detach_plan_item(999999, 1, db_path=db)
    assert exc.value.status_code == 404
    # 已完成计划不可拆项
    plans.publish_plan(p["id"], db_path=db)
    rewrite.start_rewrite(p["id"], db_path=db)
    with pytest.raises(ServiceError) as exc:
        plans.detach_plan_item(p["id"], 1, db_path=db)
    assert exc.value.status_code == 409


def test_misaligned_item_blocks_merge(db):
    p = _make_plan(db)
    plans.publish_plan(p["id"], db_path=db)
    fid = plans.plan_detail(p["id"], db_path=db)["items"][0]["id"]
    # 人为制造偏态：挂载行还在，碎件态却被改写
    with get_db(db) as conn:
        conn.execute(
            "UPDATE lake_files SET status='碎文件' WHERE id=?", (fid,)
        )
    with pytest.raises(ServiceError) as exc:
        rewrite.start_rewrite(p["id"], db_path=db)
    assert exc.value.status_code == 409
    assert "未对齐" in exc.value.message
