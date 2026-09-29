import os, json, urllib.request, urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo
import psycopg

DATABASE_URL=os.getenv("DATABASE_URL","")
RESEND_API_KEY=os.getenv("RESEND_API_KEY","")
API_BASE=os.getenv("PUBLIC_API_BASE","https://homefirst90-api.onrender.com")
SITE_BASE="https://homefirst90.com"
FROM="HomeFirst90 <move@homefirst90.com>"

TEMPLATES={
    "14":{"id":"17e99ced-be10-4d41-b6b9-0b460d591172","subject":"Two weeks to go — get the important bits sorted","flag":"sent_14"},
    "3":{"id":"3b589b53-7f17-4c68-b8e2-ef729b15e8b9","subject":"Three days to go — your final move check","flag":"sent_3"},
    "0":{"id":"9d260cf8-b789-421d-b1f5-fa9c65027360","subject":"Moving day — start with these five things","flag":"sent_0"},
}

def fmt_date(d):
    return f"{d.day} {d.strftime('%B %Y')}"

def choose_milestone(days_left, row):
    if days_left == 0 and not row["sent_0"]:
        return "0"
    if days_left == 3 and not row["sent_3"]:
        return "3"
    if days_left == 14 and not row["sent_14"]:
        return "14"
    return None

def send_email(row, milestone):
    cfg=TEMPLATES[milestone]
    unsub=f"{SITE_BASE}/unsubscribe.html?token={row['unsubscribe_token']}"
    one_click=f"{API_BASE}/api/move/unsubscribe/{row['unsubscribe_token']}"
    payload={
        "from":FROM,
        "to":[row["email"]],
        "subject":cfg["subject"],
        "reply_to":["support@homefirst90.com"],
        "template":{
            "id":cfg["id"],
            "variables":{
                "MOVE_DATE":fmt_date(row["move_date"]),
                "UNSUBSCRIBE_URL":unsub
            }
        },
        "headers":{
            "List-Unsubscribe":f"<{one_click}>",
            "List-Unsubscribe-Post":"List-Unsubscribe=One-Click"
        },
        "tags":[
            {"name":"product","value":"homefirst90"},
            {"name":"sequence","value":"save-my-move"},
            {"name":"milestone","value":milestone}
        ]
    }
    data=json.dumps(payload).encode("utf-8")
    req=urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        method="POST",
        headers={
            "Authorization":f"Bearer {RESEND_API_KEY}",
            "Content-Type":"application/json",
            "Idempotency-Key":f"hf90-move-{row['id']}-{milestone}-{row['move_date'].isoformat()}"
        }
    )
    try:
        with urllib.request.urlopen(req,timeout=20) as resp:
            body=json.loads(resp.read().decode("utf-8") or "{}")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Resend status {resp.status}")
            return body.get("id","sent")
    except urllib.error.HTTPError as e:
        detail=e.read().decode("utf-8","replace")[:500]
        raise RuntimeError(f"Resend HTTP {e.code}: {detail}")

def run_reminders(database_url, resend_api_key):
    global DATABASE_URL, RESEND_API_KEY
    DATABASE_URL=database_url
    RESEND_API_KEY=resend_api_key
    if not DATABASE_URL or not RESEND_API_KEY:
        raise RuntimeError("DATABASE_URL and RESEND_API_KEY are required")
    today=datetime.now(ZoneInfo("Europe/London")).date()
    conn=psycopg.connect(DATABASE_URL,row_factory=psycopg.rows.dict_row)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id,email,move_date,unsubscribe_token,sent_14,sent_3,sent_0
                FROM hf90_move_leads
                WHERE active=TRUE
                  AND move_date >= %s
                  AND move_date <= %s + INTERVAL '14 days'
                ORDER BY move_date,id
            """,(today,today))
            rows=cur.fetchall()
        sent=0
        for row in rows:
            days_left=(row["move_date"]-today).days
            milestone=choose_milestone(days_left,row)
            if not milestone:
                continue
            try:
                email_id=send_email(row,milestone)
                flag=TEMPLATES[milestone]["flag"]
                with conn.cursor() as cur:
                    cur.execute(f"UPDATE hf90_move_leads SET {flag}=TRUE,updated_at=NOW() WHERE id=%s",(row["id"],))
                conn.commit()
                sent+=1
                print("HF90_REMINDER_SENT",row["id"],milestone,email_id,flush=True)
            except Exception as e:
                conn.rollback()
                print("HF90_REMINDER_ERROR",row["id"],milestone,type(e).__name__,str(e)[:300],flush=True)
        # Minimise retained lead data after the move sequence has finished.
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE hf90_move_leads
                SET active=FALSE,updated_at=NOW()
                WHERE active=TRUE AND move_date < %s - INTERVAL '30 days'
            """,(today,))
        conn.commit()
        print("HF90_REMINDER_RUN",today.isoformat(),"sent",sent,flush=True)
        return {"date":today.isoformat(),"sent":sent}
    finally:
        conn.close()

def main():
    run_reminders(DATABASE_URL, RESEND_API_KEY)

if __name__=="__main__":
    main()
