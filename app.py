from __future__ import annotations

import os
import secrets
import sqlite3
import sys
from functools import wraps
from pathlib import Path
from datetime import datetime

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("PULSELINK_DB", BASE_DIR / "pulselink.db"))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("PULSELINK_SECRET_KEY", "dev-only-change-this-key"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

BLOOD_GROUPS = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]
URGENCY_LEVELS = ["Normal", "Urgent", "Critical"]
REQUEST_STATUSES = ["Open", "In Progress", "Fulfilled", "Closed"]
# Which donor groups can donate red blood cells to each recipient group.
COMPATIBLE_DONORS = {
    "O-": ["O-"],
    "O+": ["O-", "O+"],
    "A-": ["O-", "A-"],
    "A+": ["O-", "O+", "A-", "A+"],
    "B-": ["O-", "B-"],
    "B+": ["O-", "O+", "B-", "B+"],
    "AB-": ["O-", "A-", "B-", "AB-"],
    "AB+": BLOOD_GROUPS[:],
}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        phone TEXT NOT NULL,
        city TEXT NOT NULL,
        blood_group TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Both',
        password_hash TEXT NOT NULL,
        is_available INTEGER NOT NULL DEFAULT 1,
        last_donation_date TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS blood_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creator_id INTEGER NOT NULL,
        patient_name TEXT NOT NULL,
        blood_group TEXT NOT NULL,
        units INTEGER NOT NULL DEFAULT 1,
        urgency TEXT NOT NULL DEFAULT 'Normal',
        city TEXT NOT NULL,
        hospital TEXT DEFAULT '',
        contact_number TEXT NOT NULL,
        notes TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Open',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (creator_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id INTEGER NOT NULL,
        donor_id INTEGER NOT NULL,
        message TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Interested',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(request_id, donor_id),
        FOREIGN KEY (request_id) REFERENCES blood_requests(id) ON DELETE CASCADE,
        FOREIGN KEY (donor_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_users_blood_city ON users(blood_group, city);
    CREATE INDEX IF NOT EXISTS idx_requests_status_created ON blood_requests(status, created_at);
    """)
    db.commit()
    db.close()


def seed_demo():
    init_db()
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    demo_users = [
        ("Demo Donor A", "donor.a@pulselink.demo", "9000000001", "Mumbai", "O+", "Donor", "Demo@123", 1),
        ("Demo Donor B", "donor.b@pulselink.demo", "9000000002", "Mumbai", "A+", "Donor", "Demo@123", 1),
        ("Demo Donor C", "donor.c@pulselink.demo", "9000000003", "Pune", "B+", "Both", "Demo@123", 1),
        ("Demo Recipient", "recipient@pulselink.demo", "9000000004", "Mumbai", "AB+", "Recipient", "Demo@123", 0),
    ]
    for name, email, phone, city, group, role, password, available in demo_users:
        db.execute("""INSERT OR IGNORE INTO users
          (full_name,email,phone,city,blood_group,role,password_hash,is_available)
          VALUES (?,?,?,?,?,?,?,?)""",
          (name, email, phone, city, group, role, generate_password_hash(password), available))
    user = db.execute("SELECT id FROM users WHERE email=?", ("recipient@pulselink.demo",)).fetchone()
    if user:
        exists = db.execute("SELECT id FROM blood_requests WHERE creator_id=?", (user["id"],)).fetchone()
        if not exists:
            db.execute("""INSERT INTO blood_requests
                (creator_id,patient_name,blood_group,units,urgency,city,hospital,contact_number,notes,status)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user["id"], "Demo Patient", "O+", 2, "Urgent", "Mumbai", "City Care Hospital", "9000000004", "Demo data for project presentation.", "Open"))
    db.commit()
    db.close()


@app.before_request
def protect_post_forms():
    if request.method == "POST":
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not submitted or not secrets.compare_digest(submitted, expected):
            abort(400, description="The form security token is missing or expired. Refresh the page and try again.")


@app.context_processor
def inject_globals():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {
        "current_user": get_current_user(),
        "csrf_token": session["csrf_token"],
        "blood_groups": BLOOD_GROUPS,
        "urgency_levels": URGENCY_LEVELS,
        "request_statuses": REQUEST_STATUSES,
        "current_year": datetime.now().year,
    }


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def clean(value: str | None) -> str:
    return (value or "").strip()


def valid_phone(phone: str) -> bool:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return 7 <= len(digits) <= 15


@app.route("/")
def index():
    db = get_db()
    donor_count = db.execute("SELECT COUNT(*) FROM users WHERE is_available=1 AND role IN ('Donor','Both')").fetchone()[0]
    open_count = db.execute("SELECT COUNT(*) FROM blood_requests WHERE status IN ('Open','In Progress')").fetchone()[0]
    city_count = db.execute("SELECT COUNT(DISTINCT city) FROM users WHERE is_available=1 AND role IN ('Donor','Both')").fetchone()[0]
    return render_template("index.html", donor_count=donor_count, open_count=open_count, city_count=city_count)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = clean(request.form.get("full_name"))
        email = clean(request.form.get("email")).lower()
        phone = clean(request.form.get("phone"))
        city = clean(request.form.get("city"))
        group = clean(request.form.get("blood_group"))
        role = clean(request.form.get("role"))
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        errors = []
        if len(name) < 2: errors.append("Enter your full name.")
        if "@" not in email or "." not in email.split("@")[-1]: errors.append("Enter a valid email address.")
        if not valid_phone(phone): errors.append("Enter a valid contact number.")
        if not city: errors.append("Enter your city.")
        if group not in BLOOD_GROUPS: errors.append("Select a valid blood group.")
        if role not in ("Donor", "Recipient", "Both"): errors.append("Select an account type.")
        if len(password) < 8: errors.append("Password must contain at least 8 characters.")
        if password != confirm: errors.append("Passwords do not match.")
        db = get_db()
        if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone(): errors.append("An account with this email already exists.")
        if errors:
            for error in errors: flash(error, "error")
            return render_template("register.html")
        db.execute("""INSERT INTO users(full_name,email,phone,city,blood_group,role,password_hash,is_available)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (name, email, phone, city, group, role, generate_password_hash(password), 1 if role in ("Donor", "Both") else 0))
        db.commit()
        user = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        session.clear()
        session["user_id"] = user["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        flash("Your account has been created. Welcome to PulseLink!", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = clean(request.form.get("email")).lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
            return render_template("login.html")
        session.clear()
        session["user_id"] = user["id"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        flash("Welcome back!", "success")
        next_url = request.args.get("next", "")
        if next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = session["user_id"]
    user = get_current_user()
    my_requests = db.execute("""SELECT r.*, (SELECT COUNT(*) FROM responses x WHERE x.request_id=r.id) AS response_count
                              FROM blood_requests r WHERE r.creator_id=? ORDER BY r.created_at DESC LIMIT 5""", (user_id,)).fetchall()
    my_responses = db.execute("""SELECT x.*, r.patient_name, r.blood_group, r.city, r.urgency, r.status AS request_status
                               FROM responses x JOIN blood_requests r ON r.id=x.request_id
                               WHERE x.donor_id=? ORDER BY x.created_at DESC LIMIT 5""", (user_id,)).fetchall()
    metrics = {
        "my_requests": db.execute("SELECT COUNT(*) FROM blood_requests WHERE creator_id=?", (user_id,)).fetchone()[0],
        "responses": db.execute("SELECT COUNT(*) FROM responses WHERE donor_id=?", (user_id,)).fetchone()[0],
        "available": "Yes" if user["is_available"] else "No",
    }
    recent = db.execute("""SELECT r.*, u.city AS creator_city FROM blood_requests r JOIN users u ON u.id=r.creator_id
                           WHERE r.status IN ('Open','In Progress') ORDER BY CASE r.urgency WHEN 'Critical' THEN 1 WHEN 'Urgent' THEN 2 ELSE 3 END,
                           r.created_at DESC LIMIT 4""").fetchall()
    return render_template("dashboard.html", user=user, my_requests=my_requests, my_responses=my_responses, metrics=metrics, recent=recent)


@app.route("/donors")
def donors():
    db = get_db()
    group = clean(request.args.get("blood_group"))
    city = clean(request.args.get("city"))
    compatible_only = request.args.get("compatible", "1") == "1"
    conditions = ["is_available=1", "role IN ('Donor','Both')"]
    params: list = []
    if group in BLOOD_GROUPS:
        if compatible_only:
            allowed = COMPATIBLE_DONORS[group]
            conditions.append("blood_group IN (" + ",".join("?" for _ in allowed) + ")")
            params.extend(allowed)
        else:
            conditions.append("blood_group=?")
            params.append(group)
    if city:
        conditions.append("city LIKE ?")
        params.append(f"%{city}%")
    sql = "SELECT id,full_name,city,blood_group,role,is_available,last_donation_date FROM users WHERE " + " AND ".join(conditions) + " ORDER BY city, full_name LIMIT 100"
    rows = db.execute(sql, params).fetchall()
    return render_template("donors.html", donors=rows, selected_group=group, selected_city=city, compatible_only=compatible_only)


@app.route("/requests")
def blood_requests():
    db = get_db()
    group = clean(request.args.get("blood_group"))
    city = clean(request.args.get("city"))
    urgency = clean(request.args.get("urgency"))
    status = clean(request.args.get("status", "Open"))
    conditions = ["1=1"]
    params: list = []
    if group in BLOOD_GROUPS:
        conditions.append("r.blood_group=?"); params.append(group)
    if city:
        conditions.append("r.city LIKE ?"); params.append(f"%{city}%")
    if urgency in URGENCY_LEVELS:
        conditions.append("r.urgency=?"); params.append(urgency)
    if status in REQUEST_STATUSES:
        conditions.append("r.status=?"); params.append(status)
    elif status == "Active":
        conditions.append("r.status IN ('Open','In Progress')")
    rows = db.execute("""SELECT r.*, u.full_name AS creator_name,
                         (SELECT COUNT(*) FROM responses x WHERE x.request_id=r.id) AS response_count
                         FROM blood_requests r JOIN users u ON u.id=r.creator_id WHERE """ + " AND ".join(conditions) +
                       " ORDER BY CASE r.urgency WHEN 'Critical' THEN 1 WHEN 'Urgent' THEN 2 ELSE 3 END, r.created_at DESC LIMIT 100", params).fetchall()
    return render_template("requests.html", requests=rows, selected_group=group, selected_city=city, selected_urgency=urgency, selected_status=status)


@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def create_request():
    if request.method == "POST":
        patient = clean(request.form.get("patient_name"))
        group = clean(request.form.get("blood_group"))
        units_raw = clean(request.form.get("units"))
        urgency = clean(request.form.get("urgency"))
        city = clean(request.form.get("city"))
        hospital = clean(request.form.get("hospital"))
        contact = clean(request.form.get("contact_number"))
        notes = clean(request.form.get("notes"))
        errors = []
        try:
            units = int(units_raw)
            if not 1 <= units <= 20: errors.append("Units must be between 1 and 20.")
        except ValueError:
            units = 0; errors.append("Enter the number of units required.")
        if not patient: errors.append("Enter the patient name.")
        if group not in BLOOD_GROUPS: errors.append("Select a valid blood group.")
        if urgency not in URGENCY_LEVELS: errors.append("Select an urgency level.")
        if not city: errors.append("Enter the city.")
        if not valid_phone(contact): errors.append("Enter a valid contact number.")
        if errors:
            for error in errors: flash(error, "error")
            return render_template("create_request.html")
        db = get_db()
        cur = db.execute("""INSERT INTO blood_requests(creator_id,patient_name,blood_group,units,urgency,city,hospital,contact_number,notes)
                            VALUES(?,?,?,?,?,?,?,?,?)""",
                         (session["user_id"], patient, group, units, urgency, city, hospital, contact, notes))
        db.commit()
        flash("Blood request published successfully.", "success")
        return redirect(url_for("request_detail", request_id=cur.lastrowid))
    user = get_current_user()
    return render_template("create_request.html", user=user)


@app.route("/requests/<int:request_id>")
def request_detail(request_id):
    db = get_db()
    req = db.execute("""SELECT r.*, u.full_name AS creator_name, u.email AS creator_email
                        FROM blood_requests r JOIN users u ON u.id=r.creator_id WHERE r.id=?""", (request_id,)).fetchone()
    if not req: abort(404)
    responses = db.execute("""SELECT x.*, u.full_name AS donor_name, u.city AS donor_city, u.blood_group AS donor_blood_group
                             FROM responses x JOIN users u ON u.id=x.donor_id WHERE x.request_id=? ORDER BY x.created_at DESC""", (request_id,)).fetchall() if session.get("user_id") == req["creator_id"] else []
    already_responded = False
    if session.get("user_id"):
        already_responded = bool(db.execute("SELECT id FROM responses WHERE request_id=? AND donor_id=?", (request_id, session["user_id"])).fetchone())
    return render_template("request_detail.html", req=req, responses=responses, already_responded=already_responded)


@app.post("/requests/<int:request_id>/respond")
@login_required
def respond_request(request_id):
    db = get_db()
    req = db.execute("SELECT * FROM blood_requests WHERE id=?", (request_id,)).fetchone()
    if not req: abort(404)
    if req["creator_id"] == session["user_id"]:
        flash("You cannot respond to your own request.", "error")
        return redirect(url_for("request_detail", request_id=request_id))
    if req["status"] not in ("Open", "In Progress"):
        flash("This request is no longer accepting responses.", "error")
        return redirect(url_for("request_detail", request_id=request_id))
    message = clean(request.form.get("message"))[:500]
    try:
        db.execute("INSERT INTO responses(request_id,donor_id,message) VALUES(?,?,?)", (request_id, session["user_id"], message))
        db.execute("UPDATE blood_requests SET status='In Progress' WHERE id=? AND status='Open'", (request_id,))
        db.commit()
        flash("Your response has been sent to the request creator.", "success")
    except sqlite3.IntegrityError:
        flash("You have already responded to this request.", "info")
    return redirect(url_for("request_detail", request_id=request_id))


@app.post("/requests/<int:request_id>/status")
@login_required
def update_request_status(request_id):
    status = clean(request.form.get("status"))
    if status not in REQUEST_STATUSES:
        flash("Choose a valid request status.", "error")
        return redirect(url_for("request_detail", request_id=request_id))
    db = get_db()
    req = db.execute("SELECT creator_id FROM blood_requests WHERE id=?", (request_id,)).fetchone()
    if not req: abort(404)
    if req["creator_id"] != session["user_id"]:
        abort(403)
    db.execute("UPDATE blood_requests SET status=? WHERE id=?", (status, request_id))
    db.commit()
    flash("Request status updated.", "success")
    return redirect(url_for("request_detail", request_id=request_id))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    db = get_db()
    user_id = session["user_id"]
    user = get_current_user()
    if request.method == "POST":
        name = clean(request.form.get("full_name"))
        phone = clean(request.form.get("phone"))
        city = clean(request.form.get("city"))
        group = clean(request.form.get("blood_group"))
        role = clean(request.form.get("role"))
        last_date = clean(request.form.get("last_donation_date"))
        available = 1 if request.form.get("is_available") == "on" else 0
        errors=[]
        if len(name) < 2: errors.append("Enter your full name.")
        if not valid_phone(phone): errors.append("Enter a valid contact number.")
        if not city: errors.append("Enter your city.")
        if group not in BLOOD_GROUPS: errors.append("Select a valid blood group.")
        if role not in ("Donor", "Recipient", "Both"): errors.append("Select a valid account type.")
        if last_date:
            try: datetime.strptime(last_date, "%Y-%m-%d")
            except ValueError: errors.append("Enter a valid last donation date.")
        if role == "Recipient": available = 0
        if errors:
            for error in errors: flash(error, "error")
            return render_template("profile.html", user=user)
        db.execute("""UPDATE users SET full_name=?,phone=?,city=?,blood_group=?,role=?,last_donation_date=?,is_available=? WHERE id=?""",
                   (name, phone, city, group, role, last_date, available, user_id))
        db.commit()
        flash("Profile saved successfully.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=getattr(error, "description", "Bad request.")), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="You do not have permission to perform this action."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="The page or record you requested could not be found."), 404


if __name__ == "__main__":
    init_db()
    if "--seed-demo" in sys.argv:
        seed_demo()
        print("Demo data added. Demo password: Demo@123")
        raise SystemExit(0)
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "5000")))
