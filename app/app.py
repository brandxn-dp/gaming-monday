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
    if date.fromisoformat(day).weekday() != 0:
        return jsonify(error="Check-ins are only for Mondays"), 400
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


MONDAY_SQL = "strftime('%w', day) = '1'"  # SQLite: 0 = Sunday, 1 = Monday


@app.route("/api/stats")
def stats():
    """Monday check-ins for the last N weeks plus per-person summaries.

    Only Mondays count. A "session" is a Monday where at least one person
    checked in, so a skipped week never breaks anyone's streak.
    """
    end = parse_day(request.args.get("end")) or date.today().isoformat()
    weeks = min(max(int(request.args.get("weeks", 52)), 1), 520)
    end_d = date.fromisoformat(end)
    last_monday = end_d - timedelta(days=end_d.weekday())
    start = (last_monday - timedelta(weeks=weeks - 1)).isoformat()
    db = get_db()

    people = [dict(r) for r in db.execute(
        "SELECT id, name, active FROM people ORDER BY sort_order, name COLLATE NOCASE"
    ).fetchall()]

    monday_rows = db.execute(
        f"SELECT person_id, day FROM checkins WHERE {MONDAY_SQL} AND day <= ? ORDER BY day", (end,)
    ).fetchall()

    by_day = {}
    days_by_person = {}
    for r in monday_rows:
        if r["day"] >= start:
            by_day.setdefault(r["day"], []).append(r["person_id"])
        days_by_person.setdefault(r["person_id"], []).append(r["day"])
    sessions = sorted({r["day"] for r in monday_rows})

    for p in people:
        days = days_by_person.get(p["id"], [])
        p["days"] = days
        p["total"] = len(days)
        p["first"] = days[0] if days else None
        p["last"] = days[-1] if days else None
        # Attendance = share of sessions since this person's first check-in
        # (tonight only counts once they've checked in, same as the streak).
        since = [d for d in sessions if days and d >= days[0] and (d != end or d in days)]
        p["rate"] = round(len(days) / len(since), 3) if since else 0
        p["streak"] = monday_streak(set(days), sessions, end)

    return jsonify(start=start, end=last_monday.isoformat(), by_day=by_day, people=people,
                   session_days=len([d for d in sessions if d >= start]))


def monday_streak(person_days, sessions, today):
    """Consecutive most-recent sessions this person attended.

    Tonight's session doesn't break a streak until it's over, so someone who
    hasn't checked in yet today keeps last week's streak.
    """
    streak = 0
    for d in reversed(sessions):
        if d in person_days:
            streak += 1
        elif d == today:
            continue
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
               (SELECT COUNT(*) FROM checkins c WHERE c.person_id = p.id AND strftime('%w', c.day) = '1') AS total
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
