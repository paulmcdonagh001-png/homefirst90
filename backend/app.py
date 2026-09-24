import os, json, hmac, hashlib, time, secrets, sqlite3
from datetime import datetime, timezone
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
    "purchase_confirmed","complete_open","complete_access_restored"
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
