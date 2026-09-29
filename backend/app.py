import os, json, hmac, hashlib, time, secrets, sqlite3, re
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify

app = Flask(__name__)

ALLOWED_ORIGINS = {
    "https://homefirst90.com",
    "https://www.homefirst90.com",
    "https://homefirst90.onrender.com",
}
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
SQLITE_PATH = os.getenv("SQLITE_PATH", "/tmp/homefirst90.db")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
MOVE_REMINDERS_ENABLED = os.getenv("MOVE_REMINDERS_ENABLED", "false").lower() == "true"

def is_postgres():
    return DATABASE_URL.startswith("postgres")

def db():
    if is_postgres():
        import psycopg
        return psycopg.connect(DATABASE_URL)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_entitlements (
            session_id TEXT PRIMARY KEY,
            email TEXT,
            customer_id TEXT,
            payment_intent_id TEXT,
            access_key TEXT UNIQUE NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            home_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
        cur.execute("ALTER TABLE hf90_entitlements ADD COLUMN IF NOT EXISTS payment_intent_id TEXT")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_events (
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            path TEXT,
            session_key TEXT,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_job_runs (
            job_name TEXT NOT NULL,
            run_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(job_name,run_date)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_move_leads (
            id BIGSERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            move_date DATE NOT NULL,
            consent BOOLEAN NOT NULL DEFAULT TRUE,
            consent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source_path TEXT,
            unsubscribe_token TEXT UNIQUE NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            sent_14 BOOLEAN NOT NULL DEFAULT FALSE,
            sent_3 BOOLEAN NOT NULL DEFAULT FALSE,
            sent_0 BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    else:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_entitlements (
            session_id TEXT PRIMARY KEY,
            email TEXT,
            customer_id TEXT,
            access_key TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            home_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
        try:
            cur.execute("ALTER TABLE hf90_entitlements ADD COLUMN payment_intent_id TEXT")
        except Exception:
            pass
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            path TEXT,
            session_key TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_job_runs (
            job_name TEXT NOT NULL,
            run_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(job_name,run_date)
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_move_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            move_date TEXT NOT NULL,
            consent INTEGER NOT NULL DEFAULT 1,
            consent_at TEXT NOT NULL,
            source_path TEXT,
            unsubscribe_token TEXT UNIQUE NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sent_14 INTEGER NOT NULL DEFAULT 0,
            sent_3 INTEGER NOT NULL DEFAULT 0,
            sent_0 INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)
    conn.commit()
    conn.close()

# Initialise persistent storage when the service boots.
init_db()
print("HomeFirst90 storage ready:", "postgres" if is_postgres() else "temporary-sqlite", flush=True)

def cors(resp):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, PUT, POST, OPTIONS"
    return resp

@app.after_request
def after(resp):
    return cors(resp)

@app.route("/health")
def health():
    try:
        init_db()
        return jsonify({"ok": True, "storage": "postgres" if is_postgres() else "temporary-sqlite"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def verify_stripe_signature(payload: bytes, sig_header: str):
    if not WEBHOOK_SECRET or not sig_header:
        return False
    parts = {}
    for piece in sig_header.split(","):
        if "=" in piece:
            k, v = piece.split("=", 1)
            parts.setdefault(k, []).append(v)
    if "t" not in parts or "v1" not in parts:
        return False
    try:
        ts = int(parts["t"][0])
    except Exception:
        return False
    if abs(time.time() - ts) > 300:
        return False
    signed = f"{ts}.".encode() + payload
    expected = hmac.new(WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in parts["v1"])

def save_entitlement(session):
    session_id = session.get("id")
    if not session_id:
        return
    payment_status = session.get("payment_status")
    if payment_status not in ("paid", "no_payment_required"):
        return
    email = ((session.get("customer_details") or {}).get("email")
             or session.get("customer_email"))
    customer_id = session.get("customer")
    payment_intent_id = session.get("payment_intent")
    now = datetime.now(timezone.utc).isoformat()
    access_key = "hf90_" + secrets.token_urlsafe(28)
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("""
            INSERT INTO hf90_entitlements
              (session_id,email,customer_id,payment_intent_id,access_key,active,home_json,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,TRUE,'{}'::jsonb,NOW(),NOW())
            ON CONFLICT (session_id) DO UPDATE SET
              email=EXCLUDED.email,
              customer_id=EXCLUDED.customer_id,
              payment_intent_id=EXCLUDED.payment_intent_id,
              active=TRUE,
              updated_at=NOW()
        """, (session_id, email, customer_id, payment_intent_id, access_key))
    else:
        cur.execute("""
            INSERT INTO hf90_entitlements
              (session_id,email,customer_id,payment_intent_id,access_key,active,home_json,created_at,updated_at)
            VALUES (?,?,?,?,?,1,'{}',?,?)
            ON CONFLICT(session_id) DO UPDATE SET
              email=excluded.email,
              customer_id=excluded.customer_id,
              payment_intent_id=excluded.payment_intent_id,
              active=1,
              updated_at=excluded.updated_at
        """, (session_id, email, customer_id, payment_intent_id, access_key, now, now))
    conn.commit()
    conn.close()


ALLOWED_EVENTS = {
    "page_view","tool_run","complete_checkout_click","checkout_return",
    "purchase_confirmed","complete_open","complete_access_restored","move_saved"
}

def record_event(event_type, path="", session_key="", metadata=None):
    metadata = metadata if isinstance(metadata, dict) else {}
    safe_meta = {}
    for k, v in metadata.items():
        if k in ("source","tool","stage","referrer_kind") and isinstance(v, (str, int, float, bool)):
            safe_meta[k] = v
    raw = json.dumps(safe_meta)
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute(
            "INSERT INTO hf90_events(event_type,path,session_key,metadata_json,created_at) VALUES (%s,%s,%s,%s::jsonb,NOW())",
            (event_type, path[:200], session_key[:80], raw)
        )
    else:
        cur.execute(
            "INSERT INTO hf90_events(event_type,path,session_key,metadata_json,created_at) VALUES (?,?,?,?,?)",
            (event_type, path[:200], session_key[:80], raw, datetime.now(timezone.utc).isoformat())
        )
    conn.commit()
    conn.close()
    print("HF90_EVENT", event_type, path[:120], flush=True)

@app.route("/api/event", methods=["POST", "OPTIONS"])
def analytics_event():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    event_type = str(data.get("event") or "")
    if event_type not in ALLOWED_EVENTS:
        return jsonify({"ok": False, "error": "invalid event"}), 400
    path = str(data.get("path") or "")[:200]
    session_key = str(data.get("session") or "")[:80]
    metadata = data.get("metadata") or {}
    try:
        record_event(event_type, path, session_key, metadata)
    except Exception as e:
        print("HF90_EVENT_ERROR", type(e).__name__, flush=True)
        return jsonify({"ok": False}), 500
    return jsonify({"ok": True})


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

@app.route("/api/move/status")
def move_status():
    return jsonify({"enabled": bool(MOVE_REMINDERS_ENABLED and RESEND_API_KEY)})

@app.route("/api/save-move", methods=["POST", "OPTIONS"])
def save_move():
    if request.method == "OPTIONS":
        return ("", 204)
    if not MOVE_REMINDERS_ENABLED or not RESEND_API_KEY:
        return jsonify({"ok": False, "error": "Move reminders are not available yet."}), 503
    data = request.get_json(silent=True) or {}
    # Honeypot field: normal users never fill this.
    if str(data.get("website") or "").strip():
        return jsonify({"ok": True}), 200

    email = str(data.get("email") or "").strip().lower()
    move_date_raw = str(data.get("move_date") or "").strip()
    consent = data.get("consent") is True
    source_path = str(data.get("source_path") or "")[:200]

    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400
    if not consent:
        return jsonify({"ok": False, "error": "Please confirm that you want the move-date emails."}), 400
    try:
        move_date_value = date.fromisoformat(move_date_raw)
    except Exception:
        return jsonify({"ok": False, "error": "Please enter a valid moving date."}), 400

    days_away = (move_date_value - date.today()).days
    if days_away < 0 or days_away > 730:
        return jsonify({"ok": False, "error": "Moving date must be between today and two years from now."}), 400

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("""
            INSERT INTO hf90_move_leads
              (email,move_date,consent,consent_at,source_path,unsubscribe_token,active,sent_14,sent_3,sent_0,created_at,updated_at)
            VALUES (%s,%s,TRUE,NOW(),%s,%s,TRUE,FALSE,FALSE,FALSE,NOW(),NOW())
            ON CONFLICT (email) DO UPDATE SET
              move_date=EXCLUDED.move_date,
              consent=TRUE,
              consent_at=NOW(),
              source_path=EXCLUDED.source_path,
              unsubscribe_token=EXCLUDED.unsubscribe_token,
              active=TRUE,
              sent_14=FALSE,
              sent_3=FALSE,
              sent_0=FALSE,
              updated_at=NOW()
        """, (email, move_date_value, source_path, token))
    else:
        cur.execute("""
            INSERT INTO hf90_move_leads
              (email,move_date,consent,consent_at,source_path,unsubscribe_token,active,sent_14,sent_3,sent_0,created_at,updated_at)
            VALUES (?,?,1,?,?,?,1,0,0,0,?,?)
            ON CONFLICT(email) DO UPDATE SET
              move_date=excluded.move_date,
              consent=1,
              consent_at=excluded.consent_at,
              source_path=excluded.source_path,
              unsubscribe_token=excluded.unsubscribe_token,
              active=1,
              sent_14=0,
              sent_3=0,
              sent_0=0,
              updated_at=excluded.updated_at
        """, (email, move_date_raw, now, source_path, token, now, now))
    conn.commit()
    conn.close()
    try:
        record_event("move_saved", source_path, "", {"stage":"lead_capture"})
    except Exception:
        pass
    return jsonify({"ok": True, "move_date": move_date_raw})

@app.route("/api/move/unsubscribe/<token>", methods=["GET","POST"])
def move_unsubscribe(token):
    if not token or len(token) > 128:
        return ("Invalid unsubscribe link.", 400)
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("UPDATE hf90_move_leads SET active=FALSE,updated_at=NOW() WHERE unsubscribe_token=%s", (token,))
    else:
        cur.execute("UPDATE hf90_move_leads SET active=0,updated_at=? WHERE unsubscribe_token=?", (datetime.now(timezone.utc).isoformat(), token))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    if not changed:
        return ("This unsubscribe link is no longer valid.", 404)
    return ("You have been unsubscribed from HomeFirst90 move-date emails. You can close this page.", 200, {"Content-Type":"text/plain; charset=utf-8"})

@app.route("/api/internal/run-move-reminders", methods=["POST"])
def run_move_reminders():
    if not MOVE_REMINDERS_ENABLED or not RESEND_API_KEY:
        return jsonify({"ok": False, "error": "email sending not configured"}), 503

    now_uk = datetime.now(ZoneInfo("Europe/London"))
    if now_uk.hour < 7 or now_uk.hour > 11:
        return jsonify({"ok": False, "error": "outside send window"}), 403

    today = now_uk.date()
    conn = db()
    cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute("""
                INSERT INTO hf90_job_runs(job_name,run_date,created_at)
                VALUES (%s,%s,NOW())
                ON CONFLICT (job_name,run_date) DO NOTHING
            """, ("move-reminders", today))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO hf90_job_runs(job_name,run_date,created_at)
                VALUES (?,?,?)
            """, ("move-reminders", today.isoformat(), datetime.now(timezone.utc).isoformat()))
        inserted = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    if not inserted:
        return jsonify({"ok": True, "already_ran": True, "date": today.isoformat(), "sent": 0})

    try:
        from send_move_reminders import run_reminders
        result = run_reminders(DATABASE_URL, RESEND_API_KEY)
        return jsonify({"ok": True, **result})
    except Exception as e:
        conn = db()
        cur = conn.cursor()
        if is_postgres():
            cur.execute("DELETE FROM hf90_job_runs WHERE job_name=%s AND run_date=%s", ("move-reminders", today))
        else:
            cur.execute("DELETE FROM hf90_job_runs WHERE job_name=? AND run_date=?", ("move-reminders", today.isoformat()))
        conn.commit()
        conn.close()
        print("HF90_REMINDER_RUN_ERROR", type(e).__name__, str(e)[:300], flush=True)
        return jsonify({"ok": False, "error": "reminder run failed"}), 500

@app.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    if not verify_stripe_signature(payload, request.headers.get("Stripe-Signature", "")):
        return jsonify({"ok": False, "error": "invalid signature"}), 400
    event = json.loads(payload.decode("utf-8"))
    if event.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session_obj = (event.get("data") or {}).get("object") or {}
        save_entitlement(session_obj)
        if session_obj.get("id") != "cs_hf90_startup_test":
            try:
                record_event("purchase_confirmed", "/stripe/purchase-confirmed", "", {"stage":"purchase_confirmed"})
            except Exception:
                pass
    elif event.get("type") == "charge.refunded":
        charge = (event.get("data") or {}).get("object") or {}
        if charge.get("refunded") and charge.get("payment_intent"):
            conn = db()
            cur = conn.cursor()
            if is_postgres():
                cur.execute("UPDATE hf90_entitlements SET active=FALSE,updated_at=NOW() WHERE payment_intent_id=%s", (charge.get("payment_intent"),))
            else:
                cur.execute("UPDATE hf90_entitlements SET active=0,updated_at=? WHERE payment_intent_id=?", (datetime.now(timezone.utc).isoformat(), charge.get("payment_intent")))
            conn.commit()
            conn.close()
    return jsonify({"received": True})

def row_for_session(session_id):
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("SELECT session_id,email,customer_id,access_key,active,home_json FROM hf90_entitlements WHERE session_id=%s", (session_id,))
    else:
        cur.execute("SELECT session_id,email,customer_id,access_key,active,home_json FROM hf90_entitlements WHERE session_id=?", (session_id,))
    row = cur.fetchone()
    conn.close()
    return row

def row_for_key(key):
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("SELECT session_id,email,customer_id,access_key,active,home_json FROM hf90_entitlements WHERE access_key=%s AND active=TRUE", (key,))
    else:
        cur.execute("SELECT session_id,email,customer_id,access_key,active,home_json FROM hf90_entitlements WHERE access_key=? AND active=1", (key,))
    row = cur.fetchone()
    conn.close()
    return row

def val(row, key, idx):
    if row is None: return None
    try:
        return row[key]
    except Exception:
        return row[idx]

@app.route("/api/checkout/verify")
def checkout_verify():
    init_db()
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id.startswith("cs_"):
        return jsonify({"paid": False, "error": "invalid session"}), 400
    row = row_for_session(session_id)
    if not row:
        return jsonify({"paid": False, "pending": True}), 202
    return jsonify({
        "paid": True,
        "access_key": val(row, "access_key", 3),
        "email": val(row, "email", 1)
    })

def bearer_key():
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth.startswith("Bearer ") else ""

@app.route("/api/access/verify", methods=["POST", "OPTIONS"])
def access_verify():
    if request.method == "OPTIONS":
        return ("", 204)
    init_db()
    key = bearer_key() or ((request.get_json(silent=True) or {}).get("access_key") or "")
    row = row_for_key(key)
    if not row:
        return jsonify({"active": False}), 401
    return jsonify({"active": True, "email": val(row, "email", 1)})

@app.route("/api/home", methods=["GET", "PUT", "OPTIONS"])
def home():
    if request.method == "OPTIONS":
        return ("", 204)
    init_db()
    key = bearer_key()
    row = row_for_key(key)
    if not row:
        return jsonify({"error": "unauthorised"}), 401
    if request.method == "GET":
        raw = val(row, "home_json", 5)
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except Exception: raw = {}
        return jsonify({"home": raw or {}, "email": val(row, "email", 1)})
    payload = request.get_json(silent=True) or {}
    current = val(row, "home_json", 5)
    if isinstance(current, str):
        try: current = json.loads(current)
        except Exception: current = {}
    if not isinstance(current, dict):
        current = {}
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid payload"}), 400
    current.update(payload)
    raw = json.dumps(current)
    if len(raw) > 250000:
        return jsonify({"error": "payload too large"}), 413
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("UPDATE hf90_entitlements SET home_json=%s::jsonb,updated_at=NOW() WHERE access_key=%s", (raw, key))
    else:
        cur.execute("UPDATE hf90_entitlements SET home_json=?,updated_at=? WHERE access_key=?", (raw, datetime.now(timezone.utc).isoformat(), key))
    conn.commit()
    conn.close()
    return jsonify({"saved": True})

def startup_self_test():
    if not WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is missing")
    payload = json.dumps({"type":"checkout.session.completed","data":{"object":{"id":"cs_hf90_startup_test","payment_status":"paid","customer":"cus_hf90_test","payment_intent":"pi_hf90_test","customer_details":{"email":"startup-test@homefirst90.invalid"}}}}, separators=(",",":")).encode()
    ts = int(time.time())
    sig = hmac.new(WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not verify_stripe_signature(payload, f"t={ts},v1={sig}"):
        raise RuntimeError("Stripe signature self-test failed")
    event = json.loads(payload.decode("utf-8"))
    save_entitlement(event["data"]["object"])
    row = row_for_session("cs_hf90_startup_test")
    if not row or not val(row, "access_key", 3):
        raise RuntimeError("Entitlement storage self-test failed")
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("DELETE FROM hf90_entitlements WHERE session_id=%s", ("cs_hf90_startup_test",))
    else:
        cur.execute("DELETE FROM hf90_entitlements WHERE session_id=?", ("cs_hf90_startup_test",))
    conn.commit()
    conn.close()
    record_event("page_view", "/__analytics_startup_test__", "startup-test", {"source":"internal"})
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("DELETE FROM hf90_events WHERE path=%s AND session_key=%s", ("/__analytics_startup_test__", "startup-test"))
    else:
        cur.execute("DELETE FROM hf90_events WHERE path=? AND session_key=?", ("/__analytics_startup_test__", "startup-test"))
    conn.commit()
    conn.close()
    print("HomeFirst90 secure entitlement self-test: passed", flush=True)
    print("HomeFirst90 launch analytics self-test: passed", flush=True)

startup_self_test()

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
