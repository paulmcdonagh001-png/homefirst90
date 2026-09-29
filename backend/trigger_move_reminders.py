import os, urllib.request
url=os.getenv("REMINDER_ENDPOINT","https://homefirst90-api.onrender.com/api/internal/run-move-reminders")
req=urllib.request.Request(url,data=b"{}",method="POST",headers={"Content-Type":"application/json"})
with urllib.request.urlopen(req,timeout=60) as r:
    print(r.read().decode("utf-8"),flush=True)
