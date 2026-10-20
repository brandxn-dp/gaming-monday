import os
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from hmac import compare_digest

from flask import Flask, g, jsonify, request, send_from_directory

DB_PATH = os.environ.get("DB_PATH", "/data/checkins.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
APP_TITLE = os.environ.get("APP_TITLE", "Gaming Monday")

app = Flask(__name__, static_folder="static", static_url_path="/static")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
            day TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (person_id, day)
        );
        CREATE INDEX IF NOT EXISTS idx_checkins_day ON checkins(day);
        """
    )
    db.commit()
    db.close()


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get("X-Admin-Password", "")
        if not compare_digest(supplied.encode(), ADMIN_PASSWORD.encode()):
            return jsonify(error="Invalid admin password"), 401
        return fn(*args, **kwargs)

    return wrapper


def parse_day(value):
    """Days come from the browser so check-ins follow the user's local date."""
    if not value:
        return date.today().isoformat()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


# ---------- pages ----------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/config")
def config():
    return jsonify(title=APP_TITLE)


# ---------- public API ----------

@app.route("/api/people")
def list_people():
    day = parse_day(request.args.get("day"))
    if day is None:
        return jsonify(error="Bad day"), 400
    rows = get_db().execute(
        """
        SELECT p.id, p.name,
               EXISTS(SELECT 1 FROM checkins c WHERE c.person_id = p.id AND c.day = ?) AS checked_in,
               (SELECT created_at FROM checkins c WHERE c.person_id = p.id AND c.day = ?) AS checked_in_at
        FROM people p
        WHERE p.active = 1
        ORDER BY p.sort_order, p.name COLLATE NOCASE
        """,
        (day, day),
    ).fetchall()
    return jsonify([dict(r, checked_in=bool(r["checked_in"])) for r in rows])


@app.route("/api/checkin", methods=["POST"])
def checkin():
    body = request.get_json(silent=True) or {}
    day = parse_day(body.get("day"))
    person_id = body.get("person_id")
    if day is None or not isinstance(person_id, int):
        return jsonify(error="person_id and day required"), 400
    db = get_db()
    person = db.execute("SELECT id FROM people WHERE id = ? AND active = 1", (person_id,)).fetchone()
    if not person:
        return jsonify(error="Unknown person"), 404
    db.execute("INSERT OR IGNORE INTO checkins (person_id, day) VALUES (?, ?)", (person_id, day))
    db.commit()
    return jsonify(ok=True)


@app.route("/api/checkin", methods=["DELETE"])
def undo_checkin():
    body = request.get_json(silent=True) or {}
    day = parse_day(body.get("day"))
    person_id = body.get("person_id")
    if day is None or not isinstance(person_id, int):
        return jsonify(error="person_id and day required"), 400
    db = get_db()
    db.execute("DELETE FROM checkins WHERE person_id = ? AND day = ?", (person_id, day))
    db.commit()
    return jsonify(ok=True)


@app.route("/api/stats")
def stats():
    """All check-ins for the last N days plus per-person summaries."""
    end = parse_day(request.args.get("end")) or date.today().isoformat()
    days = min(max(int(request.args.get("days", 371)), 7), 3660)
    start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
    db = get_db()

    people = [dict(r) for r in db.execute(
        "SELECT id, name, active FROM people ORDER BY sort_order, name COLLATE NOCASE"
    ).fetchall()]

    rows = db.execute(
        "SELECT person_id, day FROM checkins WHERE day BETWEEN ? AND ? ORDER BY day",
        (start, end),
    ).fetchall()
    by_day = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r["person_id"])

    totals = {
        r["person_id"]: {"total": r["total"], "first": r["first"], "last": r["last"]}
        for r in db.execute(
            "SELECT person_id, COUNT(*) AS total, MIN(day) AS first, MAX(day) AS last "
            "FROM checkins GROUP BY person_id"
        ).fetchall()
    }
    all_days = sorted({r["day"] for r in db.execute("SELECT DISTINCT day FROM checkins").fetchall()})
    days_by_person = {}
    for r in db.execute("SELECT person_id, day FROM checkins ORDER BY day").fetchall():
        days_by_person.setdefault(r["person_id"], []).append(r["day"])

    for p in people:
        t = totals.get(p["id"], {"total": 0, "first": None, "last": None})
        p.update(t)
        p["days"] = days_by_person.get(p["id"], [])
        # Attendance rate = share of session days (days anyone checked in)
        # since this person's first check-in.
        if t["first"]:
            sessions = [d for d in all_days if d >= t["first"]]
            p["rate"] = round(t["total"] / len(sessions), 3) if sessions else 0
        else:
            p["rate"] = 0
        p["streak"] = session_streak(set(p["days"]), all_days)

    return jsonify(start=start, end=end, by_day=by_day, people=people, session_days=len(all_days))


def session_streak(person_days, all_days):
    """Consecutive most-recent session days (days anyone checked in) this person attended."""
    streak = 0
    for d in reversed(all_days):
        if d in person_days:
            streak += 1
        else:
            break
    return streak


# ---------- admin API ----------

@app.route("/api/admin/login", methods=["POST"])
@require_admin
def admin_login():
    return jsonify(ok=True)


@app.route("/api/admin/people")
@require_admin
def admin_people():
    rows = get_db().execute(
        """
        SELECT p.id, p.name, p.active, p.sort_order,
               (SELECT COUNT(*) FROM checkins c WHERE c.person_id = p.id) AS total
        FROM people p ORDER BY p.sort_order, p.name COLLATE NOCASE
        """
    ).fetchall()
    return jsonify([dict(r, active=bool(r["active"])) for r in rows])


@app.route("/api/admin/people", methods=["POST"])
@require_admin
def admin_add_person():
    name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
    if not name or len(name) > 60:
        return jsonify(error="Name must be 1-60 characters"), 400
    db = get_db()
    next_order = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM people").fetchone()[0]
    try:
        db.execute("INSERT INTO people (name, sort_order) VALUES (?, ?)", (name, next_order))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(error=f"'{name}' already exists"), 409
    return jsonify(ok=True), 201


@app.route("/api/admin/people/<int:person_id>", methods=["PATCH"])
@require_admin
def admin_update_person(person_id):
    body = request.get_json(silent=True) or {}
    db = get_db()
    if "name" in body:
        name = (body["name"] or "").strip()
        if not name or len(name) > 60:
            return jsonify(error="Name must be 1-60 characters"), 400
        try:
            db.execute("UPDATE people SET name = ? WHERE id = ?", (name, person_id))
        except sqlite3.IntegrityError:
            return jsonify(error=f"'{name}' already exists"), 409
    if "active" in body:
        db.execute("UPDATE people SET active = ? WHERE id = ?", (1 if body["active"] else 0, person_id))
    if "move" in body and body["move"] in ("up", "down"):
        move_person(db, person_id, body["move"])
    db.commit()
    return jsonify(ok=True)


def move_person(db, person_id, direction):
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM people ORDER BY sort_order, name COLLATE NOCASE"
    ).fetchall()]
    if person_id not in ids:
        return
    i = ids.index(person_id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    for order, pid in enumerate(ids):
        db.execute("UPDATE people SET sort_order = ? WHERE id = ?", (order, pid))


@app.route("/api/admin/people/<int:person_id>", methods=["DELETE"])
@require_admin
def admin_delete_person(person_id):
    db = get_db()
    db.execute("DELETE FROM people WHERE id = ?", (person_id,))
    db.commit()
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
