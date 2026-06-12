import sqlite3
from datetime import date
from json import dumps

from flask import flash, redirect, render_template, request, url_for

from .auth import role_required
from .config import CATEGORIES
from .db import get_db, int_from_form


def equipment_form_data():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    status = request.form.get("status", "正常").strip()
    remark = request.form.get("remark", "").strip()
    try:
        total_stock = int_from_form("total_stock")
        available_stock = int_from_form("available_stock")
    except ValueError:
        return None, "库存必须是整数。"

    if not name:
        return None, "用品名称不能为空。"
    if category not in CATEGORIES:
        return None, "请选择正确的用品分类。"
    if total_stock < 0 or available_stock < 0:
        return None, "库存不能小于 0。"
    if available_stock > total_stock:
        return None, "可借数量不能大于总库存。"
    if status not in ("正常", "停用"):
        return None, "请选择正确的状态。"
    return (name, category, total_stock, available_stock, status, remark), None


@role_required("admin")
def admin_equipment():
    keyword = request.args.get("keyword", "").strip()
    category = request.args.get("category", "").strip()
    sql = "SELECT * FROM equipment WHERE 1 = 1"
    params = []

    if keyword:
        sql += " AND name LIKE ?"
        params.append(f"%{keyword}%")
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY id DESC"

    equipment = get_db().execute(sql, params).fetchall()
    return render_template("admin_equipment.html", equipment=equipment, keyword=keyword, category=category)


@role_required("admin")
def admin_equipment_new():
    if request.method == "POST":
        equipment_data, error = equipment_form_data()
        if error:
            flash(error, "danger")
        else:
            get_db().execute(
                """
                INSERT INTO equipment (name, category, total_stock, available_stock, status, remark)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                equipment_data,
            )
            get_db().commit()
            flash("用品添加成功。", "success")
            return redirect(url_for("admin_equipment"))

    return render_template("equipment_form.html", equipment=None)


@role_required("admin")
def admin_equipment_edit(equipment_id):
    equipment = get_db().execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
    if equipment is None:
        flash("用品不存在。", "danger")
        return redirect(url_for("admin_equipment"))

    if request.method == "POST":
        equipment_data, error = equipment_form_data()
        if error:
            flash(error, "danger")
        else:
            get_db().execute(
                """
                UPDATE equipment
                SET name = ?, category = ?, total_stock = ?, available_stock = ?, status = ?, remark = ?
                WHERE id = ?
                """,
                (*equipment_data, equipment_id),
            )
            get_db().commit()
            flash("用品信息已更新。", "success")
            return redirect(url_for("admin_equipment"))

    return render_template("equipment_form.html", equipment=equipment)


@role_required("admin")
def admin_equipment_delete(equipment_id):
    try:
        get_db().execute("DELETE FROM equipment WHERE id = ?", (equipment_id,))
        get_db().commit()
        flash("用品已删除。", "success")
    except sqlite3.IntegrityError:
        flash("该用品已有借用记录，不能直接删除。", "danger")
    return redirect(url_for("admin_equipment"))


@role_required("admin")
def admin_borrow_review():
    records = get_db().execute(
        """
        SELECT br.*, u.real_name, u.username, u.credit_score, u.violation_count,
            e.name AS equipment_name, e.category, e.available_stock
        FROM borrow_records br
        JOIN users u ON u.id = br.user_id
        JOIN equipment e ON e.id = br.equipment_id
        WHERE br.status = 'pending'
        ORDER BY br.apply_time ASC
        """
    ).fetchall()
    return render_template("admin_borrow_review.html", records=records)


@role_required("admin")
def admin_review_action(record_id, action):
    db = get_db()
    record = db.execute(
        """
        SELECT br.*, u.credit_score, e.available_stock
        FROM borrow_records br
        JOIN users u ON u.id = br.user_id
        JOIN equipment e ON e.id = br.equipment_id
        WHERE br.id = ? AND br.status = 'pending'
        """,
        (record_id,),
    ).fetchone()

    if record is None:
        flash("待审核记录不存在。", "danger")
        return redirect(url_for("admin_borrow_review"))

    if action == "approve":
        can_deduct_now = record["borrow_date"] <= date.today().isoformat()
        should_deduct_now = can_deduct_now and record["quantity"] <= record["available_stock"]
        if can_deduct_now and record["quantity"] > record["available_stock"]:
            flash("当前库存不足，暂时不能通过该申请。", "danger")
        else:
            if should_deduct_now:
                db.execute(
                    "UPDATE equipment SET available_stock = available_stock - ? WHERE id = ?",
                    (record["quantity"], record["equipment_id"]),
                )
            db.execute(
                """
                UPDATE borrow_records
                SET status = 'approved',
                    review_time = CURRENT_TIMESTAMP,
                    stock_deducted = ?,
                    stock_notice = CASE
                        WHEN ? = 1 THEN stock_notice
                        WHEN is_reservation = 1 THEN '预约申请已通过，到借用日期后归还时再核对库存。'
                        ELSE stock_notice
                    END
                WHERE id = ?
                """,
                (1 if should_deduct_now else 0, 1 if should_deduct_now else 0, record_id),
            )
            db.commit()
            if should_deduct_now:
                flash("申请已通过，库存已扣减。", "success")
            else:
                flash("预约申请已通过，暂不扣减当前库存。", "success")
    elif action == "reject":
        reject_reason = request.form.get("reject_reason", "").strip()
        db.execute(
            """
            UPDATE borrow_records
            SET status = 'rejected', reject_reason = ?, review_time = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (reject_reason, record_id),
        )
        db.commit()
        flash("申请已驳回。", "success")
    else:
        flash("未知审核操作。", "danger")

    return redirect(url_for("admin_borrow_review"))


@role_required("admin")
def admin_returns():
    records = get_db().execute(
        """
        SELECT br.*, u.real_name, u.username, u.credit_score,
            e.name AS equipment_name, e.category
        FROM borrow_records br
        JOIN users u ON u.id = br.user_id
        JOIN equipment e ON e.id = br.equipment_id
        WHERE br.status IN ('approved', 'overdue')
        ORDER BY br.expected_return_date ASC
        """
    ).fetchall()
    return render_template("admin_returns.html", records=records, today=date.today().isoformat())


@role_required("admin")
def admin_return_action(record_id):
    db = get_db()
    record = db.execute(
        "SELECT * FROM borrow_records WHERE id = ? AND status IN ('approved', 'overdue')",
        (record_id,),
    ).fetchone()

    if record is None:
        flash("待归还记录不存在。", "danger")
        return redirect(url_for("admin_returns"))

    return_condition = request.form.get("return_condition", "正常").strip()
    damage_note = request.form.get("damage_note", "").strip()
    if return_condition not in ("正常", "损坏"):
        return_condition = "正常"

    db.execute(
        """
        UPDATE borrow_records
        SET status = 'returned',
            actual_return_date = ?,
            return_condition = ?,
            damage_note = ?
        WHERE id = ?
        """,
        (date.today().isoformat(), return_condition, damage_note, record_id),
    )
    if record["stock_deducted"]:
        db.execute(
            """
            UPDATE equipment
            SET available_stock = MIN(total_stock, available_stock + ?)
            WHERE id = ?
            """,
            (record["quantity"], record["equipment_id"]),
        )
    if return_condition == "损坏":
        db.execute(
            """
            UPDATE users
            SET credit_score = MAX(0, credit_score - 15),
                violation_count = violation_count + 1
            WHERE id = ?
            """,
            (record["user_id"],),
        )
    db.commit()
    if return_condition == "损坏":
        flash("归还已确认，损坏记录已扣除 15 分信用分。", "warning")
    else:
        flash("归还已确认，库存已恢复。", "success")
    return redirect(url_for("admin_returns"))


@role_required("admin")
def admin_records():
    student = request.args.get("student", "").strip()
    equipment_name = request.args.get("equipment_name", "").strip()
    status = request.args.get("status", "").strip()

    sql = """
        SELECT br.*, u.real_name, u.username, u.credit_score,
            e.name AS equipment_name, e.category
        FROM borrow_records br
        JOIN users u ON u.id = br.user_id
        JOIN equipment e ON e.id = br.equipment_id
        WHERE 1 = 1
    """
    params = []
    if student:
        sql += " AND (u.real_name LIKE ? OR u.username LIKE ?)"
        params.extend([f"%{student}%", f"%{student}%"])
    if equipment_name:
        sql += " AND e.name LIKE ?"
        params.append(f"%{equipment_name}%")
    if status:
        sql += " AND br.status = ?"
        params.append(status)
    sql += " ORDER BY br.apply_time DESC"

    records = get_db().execute(sql, params).fetchall()
    return render_template(
        "admin_records.html",
        records=records,
        student=student,
        equipment_name=equipment_name,
        status=status,
    )


@role_required("admin")
def admin_statistics():
    db = get_db()
    stock_by_category = db.execute(
        """
        SELECT category AS name, SUM(total_stock) AS total_stock, SUM(available_stock) AS available_stock
        FROM equipment
        GROUP BY category
        ORDER BY total_stock DESC
        """
    ).fetchall()
    hot_equipment = db.execute(
        """
        SELECT e.name, COALESCE(SUM(br.quantity), 0) AS borrow_count
        FROM equipment e
        LEFT JOIN borrow_records br ON br.equipment_id = e.id
        GROUP BY e.id, e.name
        ORDER BY borrow_count DESC, e.id ASC
        LIMIT 8
        """
    ).fetchall()
    daily_applications = db.execute(
        """
        SELECT substr(apply_time, 1, 10) AS label, COUNT(*) AS total
        FROM borrow_records
        GROUP BY label
        ORDER BY label ASC
        LIMIT 14
        """
    ).fetchall()
    weekly_applications = db.execute(
        """
        SELECT strftime('%Y-W%W', apply_time) AS label, COUNT(*) AS total
        FROM borrow_records
        GROUP BY label
        ORDER BY label ASC
        LIMIT 8
        """
    ).fetchall()
    overdue_stats = db.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) AS current_overdue,
            SUM(CASE WHEN overdue_penalized = 1 THEN 1 ELSE 0 END) AS penalized_overdue,
            SUM(CASE WHEN expected_return_date < ? AND status != 'returned' THEN 1 ELSE 0 END) AS pending_overdue
        FROM borrow_records
        """,
        (date.today().isoformat(),),
    ).fetchone()

    chart_data = {
        "stockByCategory": [
            {
                "name": item["name"],
                "value": item["total_stock"] or 0,
                "available": item["available_stock"] or 0,
            }
            for item in stock_by_category
        ],
        "hotEquipment": {
            "names": [item["name"] for item in reversed(hot_equipment)],
            "values": [item["borrow_count"] or 0 for item in reversed(hot_equipment)],
        },
        "dailyApplications": {
            "labels": [item["label"] for item in daily_applications],
            "values": [item["total"] for item in daily_applications],
        },
        "weeklyApplications": {
            "labels": [item["label"] for item in weekly_applications],
            "values": [item["total"] for item in weekly_applications],
        },
        "overdueStats": [
            {"name": "当前逾期", "value": overdue_stats["current_overdue"] or 0},
            {"name": "已扣分逾期", "value": overdue_stats["penalized_overdue"] or 0},
            {"name": "待处理逾期", "value": overdue_stats["pending_overdue"] or 0},
        ],
    }
    summary = {
        "equipment_total": db.execute("SELECT COUNT(*) AS total FROM equipment").fetchone()["total"],
        "borrow_total": db.execute("SELECT COUNT(*) AS total FROM borrow_records").fetchone()["total"],
        "pending_total": db.execute("SELECT COUNT(*) AS total FROM borrow_records WHERE status = 'pending'").fetchone()["total"],
        "overdue_total": overdue_stats["current_overdue"] or 0,
    }
    return render_template("admin_statistics.html", chart_data=dumps(chart_data, ensure_ascii=False), summary=summary)


def register_admin_routes(app):
    app.add_url_rule("/admin/equipment", endpoint="admin_equipment", view_func=admin_equipment)
    app.add_url_rule(
        "/admin/equipment/new",
        endpoint="admin_equipment_new",
        view_func=admin_equipment_new,
        methods=("GET", "POST"),
    )
    app.add_url_rule(
        "/admin/equipment/<int:equipment_id>/edit",
        endpoint="admin_equipment_edit",
        view_func=admin_equipment_edit,
        methods=("GET", "POST"),
    )
    app.add_url_rule(
        "/admin/equipment/<int:equipment_id>/delete",
        endpoint="admin_equipment_delete",
        view_func=admin_equipment_delete,
        methods=("POST",),
    )
    app.add_url_rule("/admin/borrow-review", endpoint="admin_borrow_review", view_func=admin_borrow_review)
    app.add_url_rule(
        "/admin/borrow-review/<int:record_id>/<action>",
        endpoint="admin_review_action",
        view_func=admin_review_action,
        methods=("POST",),
    )
    app.add_url_rule("/admin/returns", endpoint="admin_returns", view_func=admin_returns)
    app.add_url_rule(
        "/admin/returns/<int:record_id>",
        endpoint="admin_return_action",
        view_func=admin_return_action,
        methods=("POST",),
    )
    app.add_url_rule("/admin/records", endpoint="admin_records", view_func=admin_records)
    app.add_url_rule("/admin/statistics", endpoint="admin_statistics", view_func=admin_statistics)
