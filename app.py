"""Pulseboard - Hospital Patient Data Analysis System (Flask + MySQL).

Educational operational analytics on synthetic, de-identified data.
Run:  python app.py
"""
import io
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urlencode

import pandas as pd
from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import analytics as an
import charts
from config import Config
from db import (close_db, ensure_database, get_db, init_schema, log_action,
                now_str)
from seed import (AGE_BANDS, GENDERS, VISIT_TYPES, ensure_default_users,
                  ensure_departments, seed_synthetic)

RANGES = {90: "3 months", 180: "6 months", 365: "12 months", 0: "All data"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_attempts = {}          # login throttle: key -> [timestamps]
ATTEMPT_LIMIT, ATTEMPT_WINDOW = 5, 600


def _json_default(o):
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, (datetime, date, pd.Timestamp)):
        return o.isoformat()
    raise TypeError(f"Not serializable: {type(o)}")


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.json.default = _json_default
    app.teardown_appcontext(close_db)

    boot = {"done": False, "lock": threading.Lock()}

    # ------------------------------------------------------------ bootstrap
    def bootstrap():
        ensure_database(app.config)
        db = get_db()
        init_schema(db, app.config)
        ensure_departments(db)
        ensure_default_users(db, app.config)
        if db.scalar("SELECT COUNT(*) FROM visits", default=0) == 0:
            seed_synthetic(db)
            an.invalidate()

    @app.before_request
    def prepare():
        if request.endpoint == "static":
            return None
        if not boot["done"]:
            with boot["lock"]:
                if not boot["done"]:
                    try:
                        bootstrap()
                        boot["done"] = True
                    except Exception as exc:  # database not reachable etc.
                        app.logger.error("Bootstrap failed: %s", exc)
                        return render_template(
                            "error.html", code=503, title="Database unavailable",
                            message="The app could not reach its database (%s). Check that MySQL is "
                                    "running and that the values in your .env file are correct."
                                    % type(exc).__name__), 503

        # CSRF protection for every state-changing request
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
            real = session.get("csrf", "")
            if not real or not secrets.compare_digest(sent, real):
                return render_template("error.html", code=400, title="Session expired",
                                       message="That form is no longer valid. Go back, reload the page and try again."), 400

        g.user = None
        uid = session.get("uid")
        if uid:
            user = get_db().one(
                "SELECT user_id, full_name, email, role, is_active FROM users WHERE user_id = %s", (uid,))
            if user and user["is_active"]:
                g.user = user
            else:
                session.clear()
        return None

    @app.after_request
    def secure_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.context_processor
    def inject():
        return {"current_user": g.get("user"), "disclaimer": app.config["DISCLAIMER"],
                "ranges": RANGES, "year": date.today().year}

    @app.template_filter("pcode")
    def pcode(pid):
        return f"PT-{int(pid):06d}"

    @app.template_filter("num")
    def num(v):
        try:
            return f"{int(v):,}"
        except (TypeError, ValueError):
            return v

    @app.template_filter("dstr")
    def dstr(v):
        return str(v)[:10] if v else ""

    @app.template_filter("tstr")
    def tstr(v):
        return str(v)[:16] if v else "-"

    # ------------------------------------------------------------ guards
    def login_required(view):
        @wraps(view)
        def wrapped(*a, **kw):
            if not g.user:
                return redirect(url_for("login", next=request.full_path.rstrip("?")))
            return view(*a, **kw)
        return wrapped

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if g.user["role"] != "admin":
                log_action("access_denied", request.path)
                abort(403)
            return view(*a, **kw)
        return wrapped

    def home_for(user):
        return url_for("admin_dashboard") if user["role"] == "admin" else url_for("dashboard")

    def safe_next(target):
        if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
            return target
        return None

    def throttled(key):
        now = time.time()
        _attempts[key] = [t for t in _attempts.get(key, []) if now - t < ATTEMPT_WINDOW]
        return len(_attempts[key]) >= ATTEMPT_LIMIT

    def parse_date(text):
        try:
            return pd.Timestamp(date.fromisoformat((text or "").strip()))
        except ValueError:
            return None

    # ------------------------------------------------------------ auth
    @app.route("/")
    def index():
        return redirect(home_for(g.user) if g.user else url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(home_for(g.user))
        email = ""
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            key = f"{request.remote_addr}|{email}"
            if throttled(key):
                flash("Too many failed attempts. Wait a few minutes before trying again.", "error")
                return render_template("login.html", email=email), 429
            db = get_db()
            user = db.one("SELECT * FROM users WHERE email = %s", (email,))
            if user and check_password_hash(user["password_hash"], password):
                if not user["is_active"]:
                    flash("This account is disabled. Ask an administrator to re-enable it.", "error")
                    return render_template("login.html", email=email), 403
                _attempts.pop(key, None)
                session.clear()
                session["uid"] = user["user_id"]
                session.permanent = True
                db.execute("UPDATE users SET last_login = %s WHERE user_id = %s", (now_str(), user["user_id"]))
                log_action("login", user_id=user["user_id"])
                target = safe_next(request.args.get("next") or request.form.get("next"))
                return redirect(target or home_for(user))
            _attempts.setdefault(key, []).append(time.time())
            log_action("login_failed", email[:100])
            flash("Email or password is incorrect.", "error")
            return render_template("login.html", email=email), 401
        return render_template("login.html", email=email)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if g.user:
            return redirect(home_for(g.user))
        form, errors = {"name": "", "email": ""}, {}
        if request.method == "POST":
            name = " ".join(request.form.get("name", "").split())
            email = request.form.get("email", "").strip().lower()
            pw, pw2 = request.form.get("password", ""), request.form.get("confirm", "")
            form = {"name": name, "email": email}
            if not 2 <= len(name) <= 60:
                errors["name"] = "Enter your name (2 to 60 characters)."
            if not EMAIL_RE.match(email) or len(email) > 190:
                errors["email"] = "Enter a valid email address."
            if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
                errors["password"] = "Use at least 8 characters with a letter and a number."
            if pw != pw2:
                errors["confirm"] = "The two passwords do not match."
            if not request.form.get("ack"):
                errors["ack"] = "Confirm that you understand this system uses synthetic data only."
            db = get_db()
            if not errors and db.one("SELECT user_id FROM users WHERE email = %s", (email,)):
                errors["email"] = "An account with this email already exists. Sign in instead."
            if not errors:
                uid = db.execute(
                    "INSERT INTO users (full_name, email, password_hash, role, is_active, created_at) "
                    "VALUES (%s, %s, %s, 'user', 1, %s)",
                    (name, email, generate_password_hash(pw), now_str()))
                log_action("register", email, user_id=uid)
                flash("Account created. Sign in to open your dashboard.", "success")
                return redirect(url_for("login"))
            return render_template("register.html", form=form, errors=errors), 400
        return render_template("register.html", form=form, errors=errors)

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        log_action("logout")
        session.clear()
        flash("You have been signed out.", "info")
        return redirect(url_for("login"))

    # ------------------------------------------------------------ user pages
    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", active="dashboard")

    def report_filters():
        db = get_db()
        df_all = an.load_visits(db)
        today = pd.Timestamp.today().normalize()
        dmin = df_all["visit_date"].min() if not df_all.empty else today
        dmax = df_all["visit_date"].max() if not df_all.empty else today
        raw_range = request.args.get("range", "")
        if raw_range.isdigit() and int(raw_range) in RANGES:
            start, end = an.window(df_all, int(raw_range))
        else:
            start = parse_date(request.args.get("start")) or max(dmin, dmax - pd.Timedelta(days=364))
            end = parse_date(request.args.get("end")) or dmax
        if start > end:
            start, end = end, start
        departments = [r["department_name"] for r in
                       db.all("SELECT department_name FROM departments ORDER BY department_name")]
        dept = request.args.get("department", "")
        dept = dept if dept in departments else ""
        vtype = request.args.get("visit_type", "")
        vtype = vtype if vtype in VISIT_TYPES else ""
        df = an.apply_filters(df_all, start, end, dept or None, vtype or None)
        return {"df": df, "start": start, "end": end, "department": dept, "visit_type": vtype,
                "dmin": dmin, "dmax": dmax, "departments": departments}

    def filter_qs(f):
        return urlencode({"start": f["start"].date().isoformat(), "end": f["end"].date().isoformat(),
                          "department": f["department"], "visit_type": f["visit_type"]})

    @app.route("/reports")
    @login_required
    def reports():
        f = report_filters()
        df, start, end = f["df"], f["start"], f["end"]
        daily = an.daily_series(df, start, end)
        xt = an.age_by_department(df)
        xtab = [{"department": d, "cells": [an.mask_small(v) for v in row], "total": int(row.sum())}
                for d, row in xt.iterrows()]
        log_action("view_report", filter_qs(f))
        return render_template(
            "reports.html", active="reports", f=f, qs=filter_qs(f), total=len(df),
            dept=an.department_report(df, start, end).to_dict("records"),
            monthly=an.monthly_report(df, start, end).to_dict("records"),
            ages=an.age_band_report(df).to_dict("records"),
            types=an.visit_type_report(df).to_dict("records"),
            xtab=xtab, age_order=an.AGE_ORDER, stats=an.summary_stats(daily.values),
            visit_types=VISIT_TYPES)

    @app.route("/chart/<name>.png")
    @login_required
    def chart(name):
        f = report_filters()
        try:
            png = charts.render(name, f["df"], f["start"], f["end"])
        except KeyError:
            abort(404)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.route("/export/<kind>")
    @login_required
    def export(kind):
        f = report_filters()
        df, start, end = f["df"], f["start"], f["end"]
        label = "# Operational statistics (synthetic data) - not clinical advice\n"
        tables = {
            "departments.csv": lambda: an.department_report(df, start, end),
            "monthly.csv": lambda: an.monthly_report(df, start, end).drop(columns=["Partial month"]),
            "age_bands.csv": lambda: an.age_band_report(df).assign(
                Visits=lambda t: t["Visits"].map(lambda v: "<5" if pd.isna(v) else int(v))),
        }
        if kind in tables:
            body = label + tables[kind]().to_csv(index=False)
            log_action("export", kind)
            return Response(body, mimetype="text/csv", headers={
                "Content-Disposition": f"attachment; filename=pulseboard_{kind}"})
        if kind == "report.xlsx":
            buf = io.BytesIO()
            stats = an.summary_stats(an.daily_series(df, start, end).values)
            summary = pd.DataFrame({
                "Item": ["Period", "Department filter", "Visit type filter", "Total visits",
                         "Mean visits per day", "Median visits per day", "90th percentile per day", "Note"],
                "Value": [f"{start:%d %b %Y} to {end:%d %b %Y}", f["department"] or "All", f["visit_type"] or "All",
                          len(df), stats["mean"], stats["median"], stats["p90"],
                          app.config["DISCLAIMER"]]})
            ages = an.age_band_report(df)
            ages["Visits"] = ages["Visits"].map(lambda v: "<5" if pd.isna(v) else int(v))
            with pd.ExcelWriter(buf, engine="openpyxl") as xw:
                summary.to_excel(xw, "Summary", index=False)
                an.department_report(df, start, end).to_excel(xw, "Departments", index=False)
                an.monthly_report(df, start, end).drop(columns=["Partial month"]).to_excel(xw, "Monthly", index=False)
                ages.to_excel(xw, "Age bands", index=False)
                an.visit_type_report(df).to_excel(xw, "Visit types", index=False)
                for ws in xw.book.worksheets:
                    for col in ws.columns:
                        ws.column_dimensions[col[0].column_letter].width = min(
                            max(len(str(c.value or "")) for c in col) + 3, 70)
            log_action("export", kind)
            return Response(buf.getvalue(),
                            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": "attachment; filename=pulseboard_report.xlsx"})
        abort(404)

    @app.route("/api/dashboard")
    @login_required
    def api_dashboard():
        raw = request.args.get("range", "365")
        days = int(raw) if raw.isdigit() and int(raw) in RANGES else 365
        want_admin = request.args.get("scope") == "admin"
        if want_admin and g.user["role"] != "admin":
            abort(403)
        df = an.load_visits(get_db())
        return jsonify(an.dashboard_payload(df, days, admin=want_admin))

    # ------------------------------------------------------------ admin
    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        db = get_db()
        day_ago = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        system = {
            "users": db.scalar("SELECT COUNT(*) FROM users", default=0),
            "admins": db.scalar("SELECT COUNT(*) FROM users WHERE role = 'admin'", default=0),
            "disabled": db.scalar("SELECT COUNT(*) FROM users WHERE is_active = 0", default=0),
            "patients": db.scalar("SELECT COUNT(*) FROM patients", default=0),
            "visits": db.scalar("SELECT COUNT(*) FROM visits", default=0),
            "departments": db.scalar("SELECT COUNT(*) FROM departments", default=0),
            "events_24h": db.scalar("SELECT COUNT(*) FROM audit_log WHERE created_at >= %s", (day_ago,), default=0),
            "failed_24h": db.scalar(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'login_failed' AND created_at >= %s", (day_ago,), default=0),
        }
        recent = db.all(
            "SELECT a.action, a.detail, a.created_at, u.email FROM audit_log a "
            "LEFT JOIN users u ON u.user_id = a.user_id ORDER BY a.log_id DESC LIMIT 6")
        return render_template("admin_dashboard.html", active="admin", system=system, recent=recent)

    @app.route("/admin/records")
    @admin_required
    def admin_records():
        db = get_db()
        where, params = [], []
        dept_id = request.args.get("department_id", "")
        vtype = request.args.get("visit_type", "")
        start, end = parse_date(request.args.get("start")), parse_date(request.args.get("end"))
        pid = re.sub(r"\D", "", request.args.get("patient", ""))
        if dept_id.isdigit():
            where.append("v.department_id = %s"); params.append(int(dept_id))
        if vtype in VISIT_TYPES:
            where.append("v.visit_type = %s"); params.append(vtype)
        if start is not None:
            where.append("v.visit_date >= %s"); params.append(start.date().isoformat())
        if end is not None:
            where.append("v.visit_date <= %s"); params.append(end.date().isoformat())
        if pid:
            where.append("v.patient_id = %s"); params.append(int(pid))
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        per = 25
        total = db.scalar("SELECT COUNT(*) FROM visits v" + clause, params, default=0)
        pages = max((total + per - 1) // per, 1)
        page = min(max(int(request.args.get("page", 1)) if request.args.get("page", "1").isdigit() else 1, 1), pages)
        rows = db.all(
            "SELECT v.visit_id, v.patient_id, v.visit_date, v.visit_type, d.department_name, p.age_band, p.gender "
            "FROM visits v JOIN departments d ON d.department_id = v.department_id "
            "JOIN patients p ON p.patient_id = v.patient_id" + clause +
            " ORDER BY v.visit_date DESC, v.visit_id DESC LIMIT %s OFFSET %s", params + [per, (page - 1) * per])
        departments = db.all("SELECT department_id, department_name FROM departments ORDER BY department_name")
        log_action("view_records", f"page {page}, {total} matches")
        keep = {k: request.args.get(k, "") for k in ("department_id", "visit_type", "start", "end", "patient")}
        return render_template("admin_records.html", active="records", rows=rows, total=total, page=page,
                               pages=pages, departments=departments, visit_types=VISIT_TYPES,
                               keep=keep, keep_qs=urlencode({k: v for k, v in keep.items() if v}),
                               today=date.today().isoformat())

    @app.route("/admin/records/add", methods=["POST"])
    @admin_required
    def add_visit():
        db = get_db()
        pid = request.form.get("patient_id", "").strip()
        did = request.form.get("department_id", "").strip()
        vdate = parse_date(request.form.get("visit_date"))
        vtype = request.form.get("visit_type", "")
        pid = int(re.sub(r"\D", "", pid) or 0)
        if not (pid and db.scalar("SELECT COUNT(*) FROM patients WHERE patient_id = %s", (pid,))):
            flash("That patient code does not exist. Add the synthetic patient first.", "error")
        elif not (did.isdigit() and db.scalar("SELECT COUNT(*) FROM departments WHERE department_id = %s", (int(did),))):
            flash("Choose a department from the list.", "error")
        elif vdate is None or vdate.date() > date.today():
            flash("Enter a visit date that is today or earlier.", "error")
        elif vtype not in VISIT_TYPES:
            flash("Choose a visit type from the list.", "error")
        else:
            vid = db.execute(
                "INSERT INTO visits (patient_id, department_id, visit_date, visit_type) VALUES (%s, %s, %s, %s)",
                (pid, int(did), vdate.date().isoformat(), vtype))
            an.invalidate()
            log_action("add_visit", f"visit {vid}")
            flash(f"Visit {vid} added.", "success")
        return redirect(url_for("admin_records"))

    @app.route("/admin/records/<int:visit_id>/delete", methods=["POST"])
    @admin_required
    def delete_visit(visit_id):
        get_db().execute("DELETE FROM visits WHERE visit_id = %s", (visit_id,))
        an.invalidate()
        log_action("delete_visit", f"visit {visit_id}")
        flash(f"Visit {visit_id} deleted.", "success")
        return redirect(request.referrer or url_for("admin_records"))

    @app.route("/admin/users")
    @admin_required
    def admin_users():
        users = get_db().all(
            "SELECT user_id, full_name, email, role, is_active, created_at, last_login FROM users ORDER BY user_id")
        return render_template("admin_users.html", active="users", users=users)

    @app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
    @admin_required
    def toggle_user(user_id):
        db = get_db()
        target = db.one("SELECT user_id, email, is_active FROM users WHERE user_id = %s", (user_id,))
        if not target:
            abort(404)
        if target["user_id"] == g.user["user_id"]:
            flash("You cannot disable your own account.", "error")
        else:
            new = 0 if target["is_active"] else 1
            db.execute("UPDATE users SET is_active = %s WHERE user_id = %s", (new, user_id))
            log_action("user_enabled" if new else "user_disabled", target["email"])
            flash(f"{target['email']} is now {'active' if new else 'disabled'}.", "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/users/<int:user_id>/role", methods=["POST"])
    @admin_required
    def set_role(user_id):
        db = get_db()
        role = request.form.get("role")
        target = db.one("SELECT user_id, email FROM users WHERE user_id = %s", (user_id,))
        if not target or role not in ("user", "admin"):
            abort(400)
        if target["user_id"] == g.user["user_id"]:
            flash("You cannot change your own role.", "error")
        else:
            db.execute("UPDATE users SET role = %s WHERE user_id = %s", (role, user_id))
            log_action("role_changed", f"{target['email']} -> {role}")
            flash(f"{target['email']} is now {role}.", "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/data")
    @admin_required
    def admin_data():
        db = get_db()
        depts = db.all(
            "SELECT d.department_id, d.department_name, COUNT(v.visit_id) AS visits "
            "FROM departments d LEFT JOIN visits v ON v.department_id = d.department_id "
            "GROUP BY d.department_id, d.department_name ORDER BY d.department_name")
        counts = {
            "patients": db.scalar("SELECT COUNT(*) FROM patients", default=0),
            "visits": db.scalar("SELECT COUNT(*) FROM visits", default=0),
            "first": db.scalar("SELECT MIN(visit_date) FROM visits"),
            "last": db.scalar("SELECT MAX(visit_date) FROM visits"),
        }
        return render_template("admin_data.html", active="data", depts=depts, counts=counts,
                               age_bands=AGE_BANDS, genders=GENDERS)

    @app.route("/admin/data/department", methods=["POST"])
    @admin_required
    def add_department():
        db = get_db()
        name = " ".join(request.form.get("name", "").split())
        if not 2 <= len(name) <= 100:
            flash("Enter a department name (2 to 100 characters).", "error")
        elif db.one("SELECT department_id FROM departments WHERE department_name = %s", (name,)):
            flash(f"{name} already exists.", "error")
        else:
            db.execute("INSERT INTO departments (department_name) VALUES (%s)", (name,))
            log_action("add_department", name)
            flash(f"Department {name} added.", "success")
        return redirect(url_for("admin_data"))

    @app.route("/admin/data/patient", methods=["POST"])
    @admin_required
    def add_patient():
        band = request.form.get("age_band")
        gender = request.form.get("gender") or None
        if band not in AGE_BANDS or (gender and gender not in GENDERS):
            flash("Choose an age band (and optionally a gender) from the lists.", "error")
        else:
            pid = get_db().execute("INSERT INTO patients (age_band, gender) VALUES (%s, %s)", (band, gender))
            log_action("add_patient", f"patient {pid}")
            flash(f"Synthetic patient {pcode(pid)} added. Use this code when adding a visit.", "success")
        return redirect(url_for("admin_data"))

    @app.route("/admin/data/regenerate", methods=["POST"])
    @admin_required
    def regenerate():
        months = request.form.get("months", "18")
        if request.form.get("confirm", "").strip() != "RESET" or months not in ("6", "12", "18", "24"):
            flash("Type RESET and choose a period to regenerate the synthetic data.", "error")
            return redirect(url_for("admin_data"))
        p, v = seed_synthetic(get_db(), months=int(months), replace=True)
        an.invalidate()
        log_action("regenerate_data", f"{p} patients, {v} visits, {months} months")
        flash(f"Synthetic data regenerated: {p:,} patients and {v:,} visits.", "success")
        return redirect(url_for("admin_data"))

    @app.route("/admin/audit")
    @admin_required
    def admin_audit():
        rows = get_db().all(
            "SELECT a.log_id, a.action, a.detail, a.ip_address, a.created_at, u.email "
            "FROM audit_log a LEFT JOIN users u ON u.user_id = a.user_id ORDER BY a.log_id DESC LIMIT 150")
        return render_template("admin_audit.html", active="audit", rows=rows)

    # ------------------------------------------------------------ errors
    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, title="Admins only",
                               message="Your account does not have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, title="Page not found",
                               message="That page does not exist or has moved."), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", code=500, title="Something went wrong",
                               message="The server hit an error. Try again, and check the terminal for details."), 500

    return app


app = create_app()

if __name__ == "__main__":
    print("\n  Pulseboard is starting at http://127.0.0.1:5000")
    print("  First run creates the tables and generates synthetic data (takes a few seconds).\n")
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
