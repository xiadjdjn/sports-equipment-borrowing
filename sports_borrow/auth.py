import sqlite3
from functools import wraps

from flask import flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            flash("请先登录。", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(role):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if g.user is None:
                flash("请先登录。", "warning")
                return redirect(url_for("login"))
            if g.user["role"] != role:
                flash("当前账号没有访问该页面的权限。", "danger")
                return redirect(url_for("index"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        real_name = request.form.get("real_name", "").strip()
        password = request.form.get("password", "")

        if not username or not real_name or not password:
            flash("用户名、姓名和密码都不能为空。", "danger")
        else:
            try:
                get_db().execute(
                    """
                    INSERT INTO users (username, password_hash, real_name, role)
                    VALUES (?, ?, ?, 'student')
                    """,
                    (username, generate_password_hash(password), real_name),
                )
                get_db().commit()
                flash("注册成功，请登录。", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("用户名已存在，请更换后再试。", "danger")

    return render_template("register.html")


def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("用户名或密码错误。", "danger")
        else:
            session.clear()
            session["user_id"] = user["id"]
            flash("登录成功。", "success")
            return redirect(url_for("index"))

    return render_template("login.html")


def logout():
    session.clear()
    flash("已退出登录。", "success")
    return redirect(url_for("index"))


def register_auth_routes(app):
    app.add_url_rule("/register", endpoint="register", view_func=register, methods=("GET", "POST"))
    app.add_url_rule("/login", endpoint="login", view_func=login, methods=("GET", "POST"))
    app.add_url_rule("/logout", endpoint="logout", view_func=logout)
