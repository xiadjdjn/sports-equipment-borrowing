from datetime import date

from flask import flash, g, redirect, render_template, request, url_for

from .auth import login_required, role_required
from .config import CATEGORIES, EQUIPMENT_IMAGE_BY_CATEGORY, EQUIPMENT_IMAGE_BY_NAME
from .db import get_db, int_from_form

LOW_CREDIT_SCORE = 60


def equipment_image(item, category=None):
    if not isinstance(item, str):
        keys = item.keys()
        name = item["name"] if "name" in keys else item["equipment_name"] if "equipment_name" in keys else ""
        if category is None and "category" in keys:
            category = item["category"]
    else:
        name = item

    for keyword, image in EQUIPMENT_IMAGE_BY_NAME.items():
        if keyword in name:
            return image
    return EQUIPMENT_IMAGE_BY_CATEGORY.get(category, "images/split/item-cone.png")


def predicted_available_stock(equipment_id, borrow_date):
    row = get_db().execute(
        """
        SELECT e.available_stock
            + COALESCE(SUM(
                CASE
                    WHEN br.expected_return_date < ?
                        AND br.status IN ('approved', 'overdue')
                    THEN br.quantity
                    ELSE 0
                END
            ), 0)
            - COALESCE(SUM(
                CASE
                    WHEN br.borrow_date <= ?
                        AND br.status = 'approved'
                        AND br.stock_deducted = 0
                    THEN br.quantity
                    ELSE 0
                END
            ), 0) AS predicted_stock
        FROM equipment e
        LEFT JOIN borrow_records br ON br.equipment_id = e.id
        WHERE e.id = ?
        GROUP BY e.id
        """,
        (borrow_date, borrow_date, equipment_id),
    ).fetchone()
    return max(0, row["predicted_stock"]) if row else 0


def recommended_equipment(user_id):
    db = get_db()
    favorite_categories = db.execute(
        """
        SELECT e.category, COUNT(*) AS use_count
        FROM borrow_records br
        JOIN equipment e ON e.id = br.equipment_id
        WHERE br.user_id = ?
            AND br.status IN ('approved', 'returned', 'overdue')
        GROUP BY e.category
        ORDER BY use_count DESC
        LIMIT 2
        """,
        (user_id,),
    ).fetchall()
    categories = [item["category"] for item in favorite_categories]

    params = []
    category_score = "0"
    if categories:
        placeholders = ",".join("?" for _ in categories)
        category_score = f"CASE WHEN e.category IN ({placeholders}) THEN 20 ELSE 0 END"
        params.extend(categories)

    params.append(user_id)
    return db.execute(
        f"""
        SELECT e.*,
            COALESCE(SUM(br.quantity), 0) AS borrow_count,
            ({category_score})
                + COALESCE(SUM(br.quantity), 0) * 2
                + MIN(e.available_stock, 10) AS recommend_score
        FROM equipment e
        LEFT JOIN borrow_records br
            ON br.equipment_id = e.id
            AND br.status IN ('approved', 'returned', 'overdue')
        WHERE e.status = '正常'
            AND e.available_stock > 0
            AND e.id NOT IN (
                SELECT equipment_id
                FROM borrow_records
                WHERE user_id = ?
                    AND status IN ('pending', 'approved', 'overdue')
            )
        GROUP BY e.id
        ORDER BY recommend_score DESC, e.available_stock DESC, e.name ASC
        LIMIT 3
        """,
        params,
    ).fetchall()


def dashboard_data():
    db = get_db()
    stats = {
        "total_stock": db.execute("SELECT COALESCE(SUM(total_stock), 0) AS n FROM equipment").fetchone()["n"],
        "available_stock": db.execute("SELECT COALESCE(SUM(available_stock), 0) AS n FROM equipment").fetchone()["n"],
        "pending_count": db.execute("SELECT COUNT(*) AS n FROM borrow_records WHERE status = 'pending'").fetchone()["n"],
        "unreturned_count": db.execute(
            "SELECT COUNT(*) AS n FROM borrow_records WHERE status IN ('approved', 'overdue')"
        ).fetchone()["n"],
    }
    hot_items = db.execute(
        """
        SELECT e.name, e.category, e.available_stock, COALESCE(SUM(br.quantity), 0) AS borrow_count
        FROM equipment e
        LEFT JOIN borrow_records br
            ON br.equipment_id = e.id
            AND br.status IN ('approved', 'returned', 'overdue')
        GROUP BY e.id
        HAVING borrow_count > 0
        ORDER BY borrow_count DESC, e.name ASC
        LIMIT 5
        """
    ).fetchall()
    category_rows = db.execute(
        """
        SELECT category, COALESCE(SUM(available_stock), 0) AS available_stock
        FROM equipment
        WHERE status = '正常'
        GROUP BY category
        """
    ).fetchall()
    category_counts = {item["category"]: item["available_stock"] for item in category_rows}
    recommendations = []
    if g.get("user") and g.user["role"] == "student":
        recommendations = recommended_equipment(g.user["id"])
    return stats, hot_items, recommendations, category_counts


def index():
    stats, hot_items, recommendations, category_counts = dashboard_data()
    equipment = get_db().execute(
        """
        SELECT *
        FROM equipment
        WHERE status = '正常'
        ORDER BY available_stock DESC, name ASC
        LIMIT 6
        """
    ).fetchall()
    return render_template(
        "index.html",
        stats=stats,
        hot_items=hot_items,
        equipment=equipment,
        recommendations=recommendations,
        category_counts=category_counts,
    )


@login_required
def equipment_list():
    keyword = request.args.get("keyword", "").strip()
    category = request.args.get("category", "").strip()
    sql = "SELECT * FROM equipment WHERE status = '正常'"
    params = []

    if keyword:
        sql += " AND name LIKE ?"
        params.append(f"%{keyword}%")
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY category ASC, name ASC"

    equipment = get_db().execute(sql, params).fetchall()
    return render_template("equipment_list.html", equipment=equipment, keyword=keyword, category=category)


@role_required("student")
def borrow(equipment_id):
    equipment = get_db().execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
    if equipment is None:
        flash("用品不存在。", "danger")
        return redirect(url_for("equipment_list"))

    if request.method == "POST":
        try:
            quantity = int_from_form("quantity")
        except ValueError:
            quantity = 0
        borrow_date = request.form.get("borrow_date", "").strip()
        expected_return_date = request.form.get("expected_return_date", "").strip()
        purpose = request.form.get("purpose", "").strip()
        is_future_borrow = borrow_date > date.today().isoformat()
        future_stock = predicted_available_stock(equipment_id, borrow_date) if borrow_date else equipment["available_stock"]
        is_low_credit = g.user["credit_score"] < LOW_CREDIT_SCORE
        is_reservation = 0
        stock_notice = ""

        if quantity <= 0:
            flash("借用数量必须大于 0。", "danger")
        elif is_low_credit and quantity > 1:
            flash("信用分低于 60 分时，单次最多借用 1 件用品。", "danger")
        elif not borrow_date or not expected_return_date:
            flash("借用日期和预计归还日期不能为空。", "danger")
        elif expected_return_date < borrow_date:
            flash("预计归还日期不能早于借用日期。", "danger")
        elif is_future_borrow and quantity > future_stock:
            flash("预约日期前预计可用库存不足，不能提交该预约申请。", "danger")
        elif quantity > equipment["available_stock"] and not (is_future_borrow and quantity <= future_stock):
            flash("当前库存不足，且预约日期前预计可用库存仍不足。", "danger")
        else:
            if quantity > equipment["available_stock"]:
                is_reservation = 1
                stock_notice = f"当前库存不足，系统按 {borrow_date} 预计可用 {future_stock} 件处理为预约申请。"
            elif is_future_borrow:
                is_reservation = 1
                stock_notice = "未来日期借用申请，已按预约借用处理。"
            if is_low_credit:
                stock_notice = (stock_notice + " " if stock_notice else "") + "信用分较低，请等待管理员人工审核。"
            get_db().execute(
                """
                INSERT INTO borrow_records (
                    user_id, equipment_id, quantity, borrow_date, expected_return_date,
                    is_reservation, stock_notice, purpose
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    g.user["id"],
                    equipment_id,
                    quantity,
                    borrow_date,
                    expected_return_date,
                    is_reservation,
                    stock_notice,
                    purpose,
                ),
            )
            get_db().commit()
            if is_reservation:
                flash("预约借用申请已提交，等待管理员审核。", "success")
            else:
                flash("借用申请已提交，等待管理员审核。", "success")
            return redirect(url_for("my_records"))

    return render_template(
        "borrow_form.html",
        equipment=equipment,
        today=date.today().isoformat(),
        low_credit_score=LOW_CREDIT_SCORE,
    )


@role_required("student")
def my_records():
    records = get_db().execute(
        """
        SELECT br.*, e.name AS equipment_name, e.category
        FROM borrow_records br
        JOIN equipment e ON e.id = br.equipment_id
        WHERE br.user_id = ?
        ORDER BY br.apply_time DESC
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("my_records.html", records=records)


def health():
    return {"status": "ok"}


def register_borrow_routes(app):
    app.add_url_rule("/", endpoint="index", view_func=index)
    app.add_url_rule("/equipment", endpoint="equipment_list", view_func=equipment_list)
    app.add_url_rule("/borrow/<int:equipment_id>", endpoint="borrow", view_func=borrow, methods=("GET", "POST"))
    app.add_url_rule("/my-records", endpoint="my_records", view_func=my_records)
    app.add_url_rule("/health", endpoint="health", view_func=health)
