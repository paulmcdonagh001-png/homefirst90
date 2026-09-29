import os, json, urllib.request, urllib.error

API=os.getenv("GROWTH_API_URL","https://homefirst90-api.onrender.com").rstrip("/")
KEY=os.getenv("GROWTH_REVIEW_KEY","")
if not KEY:
    raise SystemExit("GROWTH_REVIEW_KEY missing")

req=urllib.request.Request(
    API+"/api/growth-agent/generate?auto=1",
    data=b"{}",
    method="POST",
    headers={"Content-Type":"application/json","X-Growth-Key":KEY},
)
try:
    with urllib.request.urlopen(req,timeout=45) as resp:
        body=resp.read().decode("utf-8","replace")
        print("HF90_GROWTH_HEARTBEAT",resp.status,body,flush=True)
except urllib.error.HTTPError as e:
    detail=e.read().decode("utf-8","replace")[:1000]
    print("HF90_GROWTH_HEARTBEAT_ERROR",e.code,detail,flush=True)
    raise
