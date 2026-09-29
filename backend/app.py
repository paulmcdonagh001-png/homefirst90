import os, json, hmac, hashlib, time, secrets, sqlite3, re
from datetime import datetime, timezone, date, timedelta
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
TESTER_INVITE_CODE = os.getenv("TESTER_INVITE_CODE", "")
TESTER_LIMIT = int(os.getenv("TESTER_LIMIT", "20") or "20")
FEEDBACK_REVIEW_KEY = os.getenv("FEEDBACK_REVIEW_KEY", "")
GROWTH_REVIEW_KEY = os.getenv("GROWTH_REVIEW_KEY", "")

COMPLETE_PLAN = [
    {"name":"Moving day + first 48 hours","end":2,"tasks":[
        ("meters","Take meter readings and photograph them","all"),
        ("controls","Find the stopcock, fuse box / consumer unit and main controls","all"),
        ("alarms","Check smoke and carbon-monoxide alarms","all"),
        ("secure","Secure doors/windows and identify every key","all"),
        ("essentials","Get sleeping, bathroom and basic kitchen essentials usable","scratch"),
        ("inventory","Photograph condition and inventory issues","rent"),
        ("petid","Update pet ID / microchip contact details","pets"),
    ]},
    {"name":"Week 1","end":7,"tasks":[
        ("counciltax","Register / confirm council tax responsibility","all"),
        ("utilities","Set up or confirm energy and water accounts","all"),
        ("broadband","Get broadband working and test real speeds","all"),
        ("gp","Register with a local GP if needed","all"),
        ("wfh","Test home-working setup in real conditions","wfh"),
        ("billsplit","Agree who pays which recurring bills","multi"),
        ("repairs","Report tenancy repairs or inventory discrepancies in writing","rent"),
    ]},
    {"name":"Days 8–30","end":30,"tasks":[
        ("realbills","Replace estimated bills with the first real household bills","all"),
        ("nextbuy","Buy the next priority items without blowing the setup budget","scratch"),
        ("bins","Check bins, recycling days and local collection rules","all"),
        ("routine","Build a simple cleaning and maintenance routine","all"),
        ("garden","Check garden boundaries, drainage and immediate maintenance","garden"),
        ("subs","Review subscriptions and direct debits after the move","all"),
    ]},
    {"name":"Days 31–60","end":60,"tasks":[
        ("rooms","Review rooms that still do not work properly before buying decoration","all"),
        ("storage","Finish storage only where clutter is actually causing a problem","all"),
        ("fund","Create a small home emergency / repair fund","all"),
        ("serials","Record appliance model/serial details and keep key receipts","all"),
        ("costs","Review commute, school and home-working costs","all"),
    ]},
    {"name":"Days 61–90","end":90,"tasks":[
        ("budgetreview","Compare total setup spend with the original budget","all"),
        ("declutter","Sell, donate or recycle duplicate items and moving clutter","all"),
        ("maintenance","Set an ongoing annual home-maintenance allowance","own"),
        ("landlord","List non-urgent landlord repairs to follow up","rent"),
        ("energyreview","Check whether broadband/energy choices still suit actual usage","all"),
        ("checkin","Do a final 90-day household check-in","multi"),
    ]},
]

def complete_relevant(tag, profile):
    if tag == "all":
        return True
    if tag == "rent":
        return profile.get("tenure") == "rent"
    if tag == "own":
        return profile.get("tenure") == "own"
    if tag == "pets":
        return str(profile.get("pets")) == "1"
    if tag == "wfh":
        return str(profile.get("wfh")) == "1"
    if tag == "garden":
        return str(profile.get("garden")) == "1"
    if tag == "scratch":
        return str(profile.get("scratch")) == "1"
    if tag == "multi":
        try:
            return int(profile.get("adults") or 0) > 1
        except Exception:
            return False
    return False


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
        CREATE TABLE IF NOT EXISTS hf90_tester_applications (
            id BIGSERIAL PRIMARY KEY,
            name TEXT,
            email TEXT UNIQUE NOT NULL,
            mover_stage TEXT,
            move_date DATE,
            consent BOOLEAN NOT NULL DEFAULT TRUE,
            entitlement_session_id TEXT,
            feedback_reminder_sent BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
        cur.execute("ALTER TABLE hf90_tester_applications ADD COLUMN IF NOT EXISTS source TEXT")
        cur.execute("ALTER TABLE hf90_tester_applications ADD COLUMN IF NOT EXISTS feedback_reminder_sent BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_growth_drafts (
            id BIGSERIAL PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'draft',
            topic TEXT NOT NULL,
            hook TEXT NOT NULL,
            destination_path TEXT NOT NULL,
            channels_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            copy_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            visual_brief TEXT,
            rationale TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at TIMESTAMPTZ
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_feedback (
            id BIGSERIAL PRIMARY KEY,
            name TEXT,
            email TEXT,
            mover_stage TEXT,
            rating INTEGER,
            useful_text TEXT,
            confusing_text TEXT,
            would_pay TEXT,
            quote_text TEXT,
            permission_to_quote BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
        CREATE TABLE IF NOT EXISTS hf90_tester_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE NOT NULL,
            mover_stage TEXT,
            move_date TEXT,
            consent INTEGER NOT NULL DEFAULT 1,
            entitlement_session_id TEXT,
            feedback_reminder_sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """)
        try:
            cur.execute("ALTER TABLE hf90_tester_applications ADD COLUMN source TEXT")
        except Exception:
            pass
        try:
            cur.execute("ALTER TABLE hf90_tester_applications ADD COLUMN feedback_reminder_sent INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_growth_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'draft',
            topic TEXT NOT NULL,
            hook TEXT NOT NULL,
            destination_path TEXT NOT NULL,
            channels_json TEXT NOT NULL DEFAULT '[]',
            copy_json TEXT NOT NULL DEFAULT '{}',
            visual_brief TEXT,
            rationale TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS hf90_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            mover_stage TEXT,
            rating INTEGER,
            useful_text TEXT,
            confusing_text TEXT,
            would_pay TEXT,
            quote_text TEXT,
            permission_to_quote INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
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


HF90_GROWTH_SEEDS = [
    {
        "topic":"Moving-out cash",
        "hook":"Moving into your first place? Your deposit and first month's rent aren't the full number.",
        "destination":"/moving-out-budget-calculator.html",
        "channels":["facebook","instagram","pinterest","youtube"],
        "copy":{
            "facebook":"Moving into your first place? The deposit and first month's rent are only part of the number. There’s moving costs, setup essentials, first bills and the cash you need left afterwards. HomeFirst90 has a free moving-out budget calculator that puts the lot in one place.",
            "instagram":"Deposit sorted? Good. Now count the rest: moving costs, setup essentials, first bills and emergency cash. The free HomeFirst90 moving-out calculator helps you see the full number before the keys arrive.",
            "pinterest":"How much money do you really need to move out? Use the free HomeFirst90 moving-out budget calculator to include upfront housing, moving costs, setup essentials, first bills and emergency cash.",
            "youtube":"Your deposit isn't your moving budget. Before you move out, add the moving costs, setup essentials, first household bills and some emergency cash. HomeFirst90 has a free calculator that works through the whole number."
        },
        "visual":"Five stacked cost buckets: upfront housing, moving costs, setup essentials, first bills, emergency cash. Clean HomeFirst90 branding.",
        "rationale":"High-intent first-home problem with a direct calculator answer."
    },
    {
        "topic":"£2,000 setup budget",
        "hook":"Got £2,000 to set up a new home? Don't spend it room by room in the order you walk through the door.",
        "destination":"/what-to-buy-first.html",
        "channels":["facebook","instagram","pinterest"],
        "copy":{
            "facebook":"Got a fixed budget to set up a new home? Start with what makes the place function, keep some emergency cash back, then push the lower-priority furniture and decor down the list. The free HomeFirst90 What To Buy First tool builds the order around your budget.",
            "instagram":"A setup budget disappears quickly if everything feels urgent. Split it into Need now / Buy soon / Can wait, and keep emergency cash back. HomeFirst90's free What To Buy First tool does the sorting for you.",
            "pinterest":"New-home shopping order: Need now, Buy soon, Can wait. Use HomeFirst90's free tool to prioritise your setup budget before filling the basket."
        },
        "visual":"Three columns: Need now / Buy soon / Can wait, plus a small emergency-cash reserve.",
        "rationale":"Strong visual format and naturally leads into the prioritisation tool."
    },
    {
        "topic":"Real monthly home cost",
        "hook":"Rent is the headline number. The monthly total is the number that actually matters.",
        "destination":"/household-bills-estimator.html",
        "channels":["facebook","pinterest","youtube"],
        "copy":{
            "facebook":"Rent is only the headline number. Council tax, energy, water, broadband and the smaller recurring costs all sit beside it. HomeFirst90's free household-bills estimator helps you work out the monthly total before you commit.",
            "pinterest":"First-flat monthly bills checklist: council tax, energy, water, broadband and recurring household costs. Estimate the full monthly total free with HomeFirst90.",
            "youtube":"Before you decide whether a flat is affordable, don't stop at the rent. Add council tax, energy, water, broadband and the smaller household costs. HomeFirst90 has a free bills estimator that puts the monthly total together."
        },
        "visual":"Large rent figure beside a second stack labelled Real monthly home cost with the additional bills underneath.",
        "rationale":"Common budgeting mistake with a strong calculator destination."
    },
    {
        "topic":"First night essentials",
        "hook":"First night in the new place? You need far less than a fully furnished home — but a few missing things are incredibly annoying.",
        "destination":"/first-night-new-home-essentials.html",
        "channels":["instagram","pinterest","facebook","youtube"],
        "copy":{
            "instagram":"First night in the new place? Forget making every room perfect. Sort sleep, bathroom basics, food/drink, charging, lighting, cleaning and the important keys/safety bits first.",
            "pinterest":"First-night new-home essentials: sleep, bathroom, food/drink, charging, lighting, cleaning and keys. Save the full HomeFirst90 checklist for moving day.",
            "facebook":"You do not need a finished home on night one. You do need somewhere to sleep, bathroom basics, something to eat and drink, chargers, light, cleaning bits and working keys. HomeFirst90 has the first-night list in one place.",
            "youtube":"Your first night in a new home doesn't need a sofa, artwork and matching mugs. It does need a bed, bathroom basics, food and drink, chargers, light, cleaning bits and working keys. HomeFirst90 has the full first-night checklist."
        },
        "visual":"A simple labelled 'First-night box' with seven essentials.",
        "rationale":"Highly saveable/shareable content and a natural bridge toward post-move Complete."
    },
    {
        "topic":"Four weeks to moving day",
        "hook":"Four weeks until moving day? This is when a bit of admin starts saving you grief later.",
        "destination":"/first-90-days-planner.html",
        "channels":["facebook","instagram","pinterest"],
        "copy":{
            "facebook":"Four weeks out is a good time to stop keeping the move in your head. Start the address/admin jobs, check what needs booking, work out what you're buying and give each week a short list. HomeFirst90's free planner builds the timeline around your move.",
            "instagram":"4 weeks → 2 weeks → 1 week → day before. Moving gets much easier when the jobs have somewhere to live other than your head. Build a free personalised plan with HomeFirst90.",
            "pinterest":"Moving-house timeline: 4 weeks, 2 weeks, 1 week, day before. Build your personalised free HomeFirst90 pre-move plan."
        },
        "visual":"Simple four-stage timeline: 4 weeks / 2 weeks / 1 week / day before.",
        "rationale":"Good planning intent and naturally demonstrates the personalised planner."
    }
]

def seed_growth_drafts():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM hf90_growth_drafts")
    if int(cur.fetchone()[0]) == 0:
        for item in HF90_GROWTH_SEEDS:
            channels = json.dumps(item["channels"])
            copies = json.dumps(item["copy"])
            if is_postgres():
                cur.execute("""
                    INSERT INTO hf90_growth_drafts
                      (status,topic,hook,destination_path,channels_json,copy_json,visual_brief,rationale,created_at)
                    VALUES ('draft',%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,NOW())
                """, (item["topic"],item["hook"],item["destination"],channels,copies,item["visual"],item["rationale"]))
            else:
                cur.execute("""
                    INSERT INTO hf90_growth_drafts
                      (status,topic,hook,destination_path,channels_json,copy_json,visual_brief,rationale,created_at)
                    VALUES ('draft',?,?,?,?,?,?,?,?)
                """, (item["topic"],item["hook"],item["destination"],channels,copies,item["visual"],item["rationale"],datetime.now(timezone.utc).isoformat()))
        conn.commit()
    conn.close()

# Initialise persistent storage when the service boots.
init_db()
seed_growth_drafts()
print("HomeFirst90 storage ready:", "postgres" if is_postgres() else "temporary-sqlite", flush=True)

def cors(resp):
    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Feedback-Key, X-Growth-Key"
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
    "page_view","tool_run","tool_complete","home_saved",
    "complete_checkout_click","checkout_return",
    "purchase_confirmed","complete_open","complete_access_restored","move_saved",
    "feedback_submitted","tester_access_granted","tester_application"
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


@app.route("/api/funnel")
def funnel_summary():
    try:
        days = int(request.args.get("days", "30"))
    except Exception:
        days = 30
    days = max(1, min(days, 365))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("""
            SELECT event_type,path,session_key,metadata_json,created_at
            FROM hf90_events
            WHERE created_at >= %s
            ORDER BY created_at ASC
        """, (cutoff,))
    else:
        cur.execute("""
            SELECT event_type,path,session_key,metadata_json,created_at
            FROM hf90_events
            WHERE created_at >= ?
            ORDER BY created_at ASC
        """, (cutoff.isoformat(),))
    rows = cur.fetchall()
    conn.close()

    counts = {
        "visitors": 0,
        "tool_starts": 0,
        "tool_completions": 0,
        "homes_saved": 0,
        "emails_captured": 0,
        "complete_views": 0,
        "checkout_starts": 0,
        "purchases": 0,
    }
    visitor_sessions = set()
    first_source = {}

    for row in rows:
        event_type, path, session_key, metadata = row[0], row[1] or "", row[2] or "", row[3]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

        if event_type == "page_view" and session_key and session_key != "startup-test":
            visitor_sessions.add(session_key)
            if session_key not in first_source:
                first_source[session_key] = str(metadata.get("source") or "unknown")
        if event_type == "tool_run":
            counts["tool_starts"] += 1
        elif event_type == "tool_complete":
            counts["tool_completions"] += 1
        elif event_type == "home_saved":
            counts["homes_saved"] += 1
        elif event_type == "move_saved":
            counts["emails_captured"] += 1
        elif event_type == "page_view" and path in ("/complete.html", "/complete"):
            counts["complete_views"] += 1
        elif event_type == "complete_checkout_click":
            counts["checkout_starts"] += 1
        elif event_type == "purchase_confirmed":
            counts["purchases"] += 1

    counts["visitors"] = len(visitor_sessions)
    source_counts = {}
    for src in first_source.values():
        source_counts[src] = source_counts.get(src, 0) + 1

    order = ["visitors","tool_starts","tool_completions","homes_saved","emails_captured","complete_views","checkout_starts","purchases"]
    stages = []
    previous = None
    for key in order:
        value = counts[key]
        stages.append({
            "key": key,
            "count": value,
            "from_previous_pct": None if previous in (None, 0) else round(value / previous * 100, 1),
            "from_visitors_pct": None if counts["visitors"] == 0 else round(value / counts["visitors"] * 100, 1),
        })
        previous = value

    return jsonify({
        "days": days,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stages": stages,
        "sources": [{"source": k, "visitors": v} for k, v in sorted(source_counts.items(), key=lambda x: (-x[1], x[0]))],
    })


def _growth_authorised():
    key = request.headers.get("X-Growth-Key", "")
    return bool(GROWTH_REVIEW_KEY and hmac.compare_digest(key, GROWTH_REVIEW_KEY))

@app.route("/api/growth-agent/queue")
def growth_agent_queue():
    if not _growth_authorised():
        return jsonify({"ok": False, "error": "unauthorised"}), 401
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id,status,topic,hook,destination_path,channels_json,copy_json,
               visual_brief,rationale,created_at,reviewed_at
        FROM hf90_growth_drafts
        ORDER BY CASE status WHEN 'draft' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, id DESC
        LIMIT 100
    """)
    rows = cur.fetchall()
    conn.close()
    items=[]
    for r in rows:
        channels=r[5]
        copies=r[6]
        if isinstance(channels,str):
            try: channels=json.loads(channels)
            except Exception: channels=[]
        if isinstance(copies,str):
            try: copies=json.loads(copies)
            except Exception: copies={}
        items.append({
            "id":r[0],"status":r[1],"topic":r[2],"hook":r[3],"destination_path":r[4],
            "channels":channels if isinstance(channels,list) else [],
            "copy":copies if isinstance(copies,dict) else {},
            "visual_brief":r[7] or "","rationale":r[8] or "",
            "created_at":str(r[9]),"reviewed_at":str(r[10] or "")
        })
    return jsonify({"ok": True, "items": items})

@app.route("/api/growth-agent/action", methods=["POST","OPTIONS"])
def growth_agent_action():
    if request.method == "OPTIONS":
        return ("",204)
    if not _growth_authorised():
        return jsonify({"ok": False, "error": "unauthorised"}), 401
    data=request.get_json(silent=True) or {}
    try:
        draft_id=int(data.get("id"))
    except Exception:
        return jsonify({"ok":False,"error":"invalid id"}),400
    action=str(data.get("action") or "")
    if action not in ("approve","reject","save"):
        return jsonify({"ok":False,"error":"invalid action"}),400
    conn=db()
    cur=conn.cursor()
    if action=="save":
        hook=str(data.get("hook") or "")[:500]
        visual=str(data.get("visual_brief") or "")[:2000]
        copies=data.get("copy") if isinstance(data.get("copy"),dict) else {}
        safe_copies={str(k)[:40]:str(v)[:4000] for k,v in copies.items()}
        raw=json.dumps(safe_copies)
        if is_postgres():
            cur.execute("UPDATE hf90_growth_drafts SET hook=%s,visual_brief=%s,copy_json=%s::jsonb WHERE id=%s",(hook,visual,raw,draft_id))
        else:
            cur.execute("UPDATE hf90_growth_drafts SET hook=?,visual_brief=?,copy_json=? WHERE id=?",(hook,visual,raw,draft_id))
    else:
        status="approved" if action=="approve" else "rejected"
        if is_postgres():
            cur.execute("UPDATE hf90_growth_drafts SET status=%s,reviewed_at=NOW() WHERE id=%s",(status,draft_id))
        else:
            cur.execute("UPDATE hf90_growth_drafts SET status=?,reviewed_at=? WHERE id=?",(status,datetime.now(timezone.utc).isoformat(),draft_id))
    conn.commit()
    conn.close()
    return jsonify({"ok":True,"id":draft_id,"action":action})



@app.route("/api/tester-status")
def tester_status():
    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("SELECT COUNT(*) FROM hf90_entitlements WHERE customer_id=%s", ("tester",))
    else:
        cur.execute("SELECT COUNT(*) FROM hf90_entitlements WHERE customer_id=?", ("tester",))
    used = int(cur.fetchone()[0])
    if is_postgres():
        cur.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN permission_to_quote THEN 1 ELSE 0 END),0) FROM hf90_feedback")
    else:
        cur.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN permission_to_quote=1 THEN 1 ELSE 0 END),0) FROM hf90_feedback")
    fb = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM hf90_tester_applications")
    applications = int(cur.fetchone()[0])
    conn.close()
    return jsonify({
        "enabled": True,
        "limit": TESTER_LIMIT,
        "used": used,
        "remaining": max(0, TESTER_LIMIT - used),
        "applications": applications,
        "feedback_received": int(fb[0]),
        "quotable_feedback": int(fb[1]),
    })


@app.route("/api/feedback-review")
def feedback_review():
    key = request.headers.get("X-Feedback-Key", "")
    if not FEEDBACK_REVIEW_KEY or not hmac.compare_digest(key, FEEDBACK_REVIEW_KEY):
        return jsonify({"ok": False, "error": "unauthorised"}), 401
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id,name,email,mover_stage,rating,useful_text,confusing_text,
               would_pay,quote_text,permission_to_quote,created_at
        FROM hf90_feedback
        ORDER BY created_at DESC
        LIMIT 200
    """)
    rows = cur.fetchall()
    items = []
    for row in rows:
        items.append({
            "id": row[0],
            "name": row[1] or "",
            "email": row[2] or "",
            "mover_stage": row[3] or "",
            "rating": row[4] or 0,
            "useful_text": row[5] or "",
            "confusing_text": row[6] or "",
            "would_pay": row[7] or "",
            "quote_text": row[8] or "",
            "permission_to_quote": bool(row[9]),
            "created_at": str(row[10]),
        })
    if is_postgres():
        cur.execute("""
            SELECT name,email,mover_stage,move_date,source,created_at
            FROM hf90_tester_applications
            ORDER BY created_at DESC
            LIMIT 200
        """)
    else:
        cur.execute("""
            SELECT name,email,mover_stage,move_date,created_at
            FROM hf90_tester_applications
            ORDER BY created_at DESC
            LIMIT 200
        """)
    app_rows = cur.fetchall()
    conn.close()
    applications = [{
        "name": r[0] or "",
        "email": r[1] or "",
        "mover_stage": r[2] or "",
        "move_date": str(r[3] or ""),
        "source": r[4] or "direct",
        "created_at": str(r[5]),
    } for r in app_rows]
    return jsonify({"ok": True, "count": len(items), "applications": applications, "items": items})


@app.route("/api/tester-apply", methods=["POST", "OPTIONS"])
def tester_apply():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    if str(data.get("website") or "").strip():
        return jsonify({"ok": True}), 200

    name = str(data.get("name") or "").strip()[:100]
    email = str(data.get("email") or "").strip().lower()[:254]
    mover_stage = str(data.get("mover_stage") or "").strip()[:40]
    move_date_raw = str(data.get("move_date") or "").strip()
    consent = data.get("consent") is True
    source = re.sub(r"[^a-zA-Z0-9_\-]", "", str(data.get("source") or ""))[:60] or "direct"

    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400
    if mover_stage not in ("moving_soon","planning","just_moved"):
        return jsonify({"ok": False, "error": "Please choose where you are in your move."}), 400
    if not consent:
        return jsonify({"ok": False, "error": "Please confirm the tester terms."}), 400

    move_date = None
    if move_date_raw:
        try:
            move_date = date.fromisoformat(move_date_raw)
        except Exception:
            return jsonify({"ok": False, "error": "Please enter a valid moving date."}), 400

    conn = db()
    cur = conn.cursor()

    # Returning applicant: restore the same tester access if it already exists.
    if is_postgres():
        cur.execute("SELECT entitlement_session_id FROM hf90_tester_applications WHERE email=%s LIMIT 1", (email,))
    else:
        cur.execute("SELECT entitlement_session_id FROM hf90_tester_applications WHERE email=? LIMIT 1", (email,))
    existing_app = cur.fetchone()
    if existing_app and existing_app[0]:
        sid = existing_app[0]
        if is_postgres():
            cur.execute("SELECT access_key,active FROM hf90_entitlements WHERE session_id=%s LIMIT 1", (sid,))
        else:
            cur.execute("SELECT access_key,active FROM hf90_entitlements WHERE session_id=? LIMIT 1", (sid,))
        ent = cur.fetchone()
        if ent:
            if not bool(ent[1]):
                if is_postgres():
                    cur.execute("UPDATE hf90_entitlements SET active=TRUE,updated_at=NOW() WHERE session_id=%s", (sid,))
                else:
                    cur.execute("UPDATE hf90_entitlements SET active=1,updated_at=? WHERE session_id=?", (datetime.now(timezone.utc).isoformat(), sid))
                conn.commit()
            conn.close()
            return jsonify({"ok": True, "access_key": ent[0], "existing": True})

    if is_postgres():
        cur.execute("LOCK TABLE hf90_entitlements IN EXCLUSIVE MODE")
        cur.execute("SELECT COUNT(*) FROM hf90_entitlements WHERE customer_id=%s", ("tester",))
    else:
        cur.execute("SELECT COUNT(*) FROM hf90_entitlements WHERE customer_id=?", ("tester",))
    used = int(cur.fetchone()[0])
    if used >= TESTER_LIMIT:
        conn.close()
        return jsonify({"ok": False, "error": "The Founding Tester places are now full."}), 409

    session_id = "tester_" + hashlib.sha256(email.encode()).hexdigest()[:24]
    access_key = "hf90_" + secrets.token_urlsafe(28)
    now = datetime.now(timezone.utc).isoformat()

    if is_postgres():
        cur.execute("""
            INSERT INTO hf90_entitlements
              (session_id,email,customer_id,payment_intent_id,access_key,active,home_json,created_at,updated_at)
            VALUES (%s,%s,%s,NULL,%s,TRUE,'{}'::jsonb,NOW(),NOW())
            ON CONFLICT (session_id) DO UPDATE SET active=TRUE,updated_at=NOW()
            RETURNING access_key
        """, (session_id,email,"tester",access_key))
        access_key = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO hf90_tester_applications
              (name,email,mover_stage,move_date,consent,entitlement_session_id,source,created_at)
            VALUES (%s,%s,%s,%s,TRUE,%s,%s,NOW())
            ON CONFLICT (email) DO UPDATE SET
              name=EXCLUDED.name,mover_stage=EXCLUDED.mover_stage,move_date=EXCLUDED.move_date,
              consent=TRUE,entitlement_session_id=EXCLUDED.entitlement_session_id,source=EXCLUDED.source
        """, (name,email,mover_stage,move_date,session_id,source))
    else:
        cur.execute("""
            INSERT OR IGNORE INTO hf90_entitlements
              (session_id,email,customer_id,payment_intent_id,access_key,active,home_json,created_at,updated_at)
            VALUES (?,?,?,NULL,?,1,'{}',?,?)
        """, (session_id,email,"tester",access_key,now,now))
        cur.execute("SELECT access_key FROM hf90_entitlements WHERE session_id=?", (session_id,))
        access_key = cur.fetchone()[0]
        cur.execute("""
            INSERT INTO hf90_tester_applications
              (name,email,mover_stage,move_date,consent,entitlement_session_id,source,created_at)
            VALUES (?,?,?,?,1,?,?,?)
            ON CONFLICT(email) DO UPDATE SET
              name=excluded.name,mover_stage=excluded.mover_stage,move_date=excluded.move_date,
              consent=1,entitlement_session_id=excluded.entitlement_session_id,source=excluded.source
        """, (name,email,mover_stage,move_date_raw or None,session_id,source,now))

    conn.commit()
    conn.close()
    try:
        record_event("tester_application", "/founding-testers.html", "", {"stage":"tester"})
        record_event("tester_access_granted", "/founding-testers.html", "", {"stage":"tester"})
    except Exception:
        pass
    return jsonify({"ok": True, "access_key": access_key, "existing": False})


@app.route("/api/tester-access", methods=["POST", "OPTIONS"])
def tester_access():
    if request.method == "OPTIONS":
        return ("", 204)
    if not TESTER_INVITE_CODE:
        return jsonify({"ok": False, "error": "Tester access is not enabled."}), 503
    data = request.get_json(silent=True) or {}
    if str(data.get("website") or "").strip():
        return jsonify({"ok": True}), 200
    email = str(data.get("email") or "").strip().lower()
    code = str(data.get("code") or "").strip()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400
    if not hmac.compare_digest(code, TESTER_INVITE_CODE):
        return jsonify({"ok": False, "error": "That tester code is not valid."}), 403

    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("SELECT session_id,access_key,active FROM hf90_entitlements WHERE email=%s AND customer_id=%s LIMIT 1", (email, "tester"))
    else:
        cur.execute("SELECT session_id,access_key,active FROM hf90_entitlements WHERE email=? AND customer_id=? LIMIT 1", (email, "tester"))
    existing = cur.fetchone()
    if existing:
        key = existing[1]
        active = bool(existing[2])
        if not active:
            if is_postgres():
                cur.execute("UPDATE hf90_entitlements SET active=TRUE,updated_at=NOW() WHERE session_id=%s", (existing[0],))
            else:
                cur.execute("UPDATE hf90_entitlements SET active=1,updated_at=? WHERE session_id=?", (datetime.now(timezone.utc).isoformat(), existing[0]))
            conn.commit()
        conn.close()
        return jsonify({"ok": True, "access_key": key, "existing": True})

    if is_postgres():
        cur.execute("SELECT COUNT(*) FROM hf90_entitlements WHERE customer_id=%s", ("tester",))
    else:
        cur.execute("SELECT COUNT(*) FROM hf90_entitlements WHERE customer_id=?", ("tester",))
    count = int(cur.fetchone()[0])
    if count >= TESTER_LIMIT:
        conn.close()
        return jsonify({"ok": False, "error": "The Founding Tester places are full."}), 409

    session_id = "tester_" + hashlib.sha256(email.encode()).hexdigest()[:24]
    access_key = "hf90_" + secrets.token_urlsafe(28)
    now = datetime.now(timezone.utc).isoformat()
    if is_postgres():
        cur.execute("""
            INSERT INTO hf90_entitlements
              (session_id,email,customer_id,payment_intent_id,access_key,active,home_json,created_at,updated_at)
            VALUES (%s,%s,%s,NULL,%s,TRUE,'{}'::jsonb,NOW(),NOW())
            ON CONFLICT (session_id) DO NOTHING
        """, (session_id, email, "tester", access_key))
    else:
        cur.execute("""
            INSERT OR IGNORE INTO hf90_entitlements
              (session_id,email,customer_id,payment_intent_id,access_key,active,home_json,created_at,updated_at)
            VALUES (?,?,?,NULL,?,1,'{}',?,?)
        """, (session_id, email, "tester", access_key, now, now))
    conn.commit()
    conn.close()
    try:
        record_event("tester_access_granted", "/tester.html", "", {"stage":"tester"})
    except Exception:
        pass
    return jsonify({"ok": True, "access_key": access_key, "existing": False})


@app.route("/api/feedback", methods=["POST", "OPTIONS"])
def feedback():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(silent=True) or {}
    if str(data.get("website") or "").strip():
        return jsonify({"ok": True}), 200

    name = str(data.get("name") or "").strip()[:100]
    email = str(data.get("email") or "").strip().lower()[:254]
    mover_stage = str(data.get("mover_stage") or "").strip()[:80]
    useful_text = str(data.get("useful_text") or "").strip()[:4000]
    confusing_text = str(data.get("confusing_text") or "").strip()[:4000]
    would_pay = str(data.get("would_pay") or "").strip()[:20]
    quote_text = str(data.get("quote_text") or "").strip()[:1000]
    permission = data.get("permission_to_quote") is True
    try:
        rating = int(data.get("rating") or 0)
    except Exception:
        rating = 0
    if rating < 1 or rating > 5:
        return jsonify({"ok": False, "error": "Please choose a rating from 1 to 5."}), 400
    if len(useful_text) < 5:
        return jsonify({"ok": False, "error": "Please tell us what was useful."}), 400
    if email and not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Please enter a valid email address or leave it blank."}), 400

    conn = db()
    cur = conn.cursor()
    if is_postgres():
        cur.execute("""
            INSERT INTO hf90_feedback
              (name,email,mover_stage,rating,useful_text,confusing_text,would_pay,quote_text,permission_to_quote,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (name,email,mover_stage,rating,useful_text,confusing_text,would_pay,quote_text,permission))
    else:
        cur.execute("""
            INSERT INTO hf90_feedback
              (name,email,mover_stage,rating,useful_text,confusing_text,would_pay,quote_text,permission_to_quote,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (name,email,mover_stage,rating,useful_text,confusing_text,would_pay,quote_text,1 if permission else 0,datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    try:
        record_event("feedback_submitted", "/feedback.html", "", {"stage":"tester_feedback"})
    except Exception:
        pass
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
    session_key = str(data.get("session") or "")[:80]

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
        record_event("move_saved", source_path, session_key, {"stage":"lead_capture"})
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

@app.route("/api/complete/plan")
def complete_plan():
    init_db()
    key = bearer_key()
    row = row_for_key(key)
    if not row:
        return jsonify({"error": "unauthorised"}), 401
    raw = val(row, "home_json", 5)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    profile = raw.get("homefirst90-move-profile") or {}
    phases = []
    total = 0
    for phase in COMPLETE_PLAN:
        tasks = [
            {"id": task_id, "text": text}
            for task_id, text, tag in phase["tasks"]
            if complete_relevant(tag, profile)
        ]
        total += len(tasks)
        phases.append({"name": phase["name"], "end": phase["end"], "tasks": tasks})
    return jsonify({"phases": phases, "total": total})

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
