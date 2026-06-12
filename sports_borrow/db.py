from datetime import date
import sqlite3

from flask import g, request
from werkzeug.security import generate_password_hash

from .config import DB_PATH


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            real_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student', 'admin')),
            credit_score INTEGER NOT NULL DEFAULT 100,
            violation_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            total_stock INTEGER NOT NULL CHECK(total_stock >= 0),
            available_stock INTEGER NOT NULL CHECK(available_stock >= 0),
            status TEXT NOT NULL DEFAULT '正常',
            remark TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS borrow_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            borrow_date TEXT NOT NULL,
            expected_return_date TEXT NOT NULL,
            is_reservation INTEGER NOT NULL DEFAULT 0,
            stock_deducted INTEGER NOT NULL DEFAULT 0,
            overdue_penalized INTEGER NOT NULL DEFAULT 0,
            stock_notice TEXT DEFAULT '',
            purpose TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'approved', 'rejected', 'returned', 'overdue')),
            reject_reason TEXT DEFAULT '',
            return_condition TEXT DEFAULT '',
            damage_note TEXT DEFAULT '',
            apply_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            review_time TEXT,
            actual_return_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(equipment_id) REFERENCES equipment(id)
        );
        """
    )

    ensure_column(db, "users", "credit_score", "INTEGER NOT NULL DEFAULT 100")
    ensure_column(db, "users", "violation_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "borrow_records", "is_reservation", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "borrow_records", "stock_deducted", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "borrow_records", "overdue_penalized", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(db, "borrow_records", "stock_notice", "TEXT DEFAULT ''")
    db.execute(
        """
        UPDATE borrow_records
        SET stock_deducted = 1
        WHERE status IN ('approved', 'overdue') AND stock_deducted = 0
        """
    )

    admin = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if admin is None:
        db.execute(
            "INSERT INTO users (username, password_hash, real_name, role) VALUES (?, ?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "管理员", "admin"),
        )

    count = db.execute("SELECT COUNT(*) AS total FROM equipment").fetchone()["total"]
    if count == 0:
        samples = [
            ("篮球", "球类", 20, 20, "正常", "室内外通用篮球"),
            ("足球", "球类", 16, 16, "正常", "标准 5 号足球"),
            ("羽毛球拍", "球拍类", 30, 30, "正常", "按支借用"),
            ("乒乓球拍", "球拍类", 24, 24, "正常", "含常用训练球拍"),
            ("跳绳", "健身类", 40, 40, "正常", "普通计数跳绳"),
            ("排球", "球类", 12, 12, "正常", "标准训练排球"),
        ]
        db.executemany(
            """
            INSERT INTO equipment (name, category, total_stock, available_stock, status, remark)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            samples,
        )
    db.commit()


def ensure_column(db, table_name, column_name, definition):
    columns = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    if column_name not in {column["name"] for column in columns}:
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def refresh_overdue_records():
    today = date.today().isoformat()
    db = get_db()
    overdue_records = db.execute(
        """
        SELECT id, user_id
        FROM borrow_records
        WHERE status = 'approved'
            AND stock_deducted = 1
            AND expected_return_date < ?
            AND overdue_penalized = 0
        """,
        (today,),
    ).fetchall()

    for record in overdue_records:
        db.execute(
            """
            UPDATE users
            SET credit_score = MAX(0, credit_score - 10),
                violation_count = violation_count + 1
            WHERE id = ?
            """,
            (record["user_id"],),
        )
        db.execute(
            """
            UPDATE borrow_records
            SET overdue_penalized = 1,
                stock_notice = '逾期未归还，已扣除 10 分信用分。'
            WHERE id = ?
            """,
            (record["id"],),
        )

    db.execute(
        """
        UPDATE borrow_records
        SET status = 'overdue'
        WHERE status = 'approved' AND stock_deducted = 1 AND expected_return_date < ?
        """,
        (today,),
    )
    db.commit()


def activate_due_reservations():
    today = date.today().isoformat()
    db = get_db()
    due_records = db.execute(
        """
        SELECT br.id, br.quantity, br.equipment_id
        FROM borrow_records br
        WHERE br.status = 'approved'
            AND br.is_reservation = 1
            AND br.stock_deducted = 0
            AND br.borrow_date <= ?
        ORDER BY br.borrow_date ASC, br.apply_time ASC
        """,
        (today,),
    ).fetchall()

    for record in due_records:
        equipment = db.execute(
            "SELECT available_stock FROM equipment WHERE id = ?",
            (record["equipment_id"],),
        ).fetchone()
        if equipment and equipment["available_stock"] >= record["quantity"]:
            db.execute(
                "UPDATE equipment SET available_stock = available_stock - ? WHERE id = ?",
                (record["quantity"], record["equipment_id"]),
            )
            db.execute(
                """
                UPDATE borrow_records
                SET stock_deducted = 1,
                    stock_notice = '预约已生效，库存已按借用日期自动预留。'
                WHERE id = ?
                """,
                (record["id"],),
            )
        else:
            db.execute(
                """
                UPDATE borrow_records
                SET stock_notice = '预约已到借用日，正在等待库存释放。'
                WHERE id = ?
                """,
                (record["id"],),
            )
    db.commit()


def int_from_form(name, default=0):
    value = request.form.get(name, "").strip()
    if value == "":
        return default
    return int(value)
