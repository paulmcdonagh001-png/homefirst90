(()=>{
  const API="https://homefirst90-api.onrender.com";
  let sid=sessionStorage.getItem("hf90-session");
  if(!sid){
    sid=(self.crypto&&crypto.randomUUID)?crypto.randomUUID():"s_"+Date.now()+"_"+Math.random().toString(36).slice(2);
    sessionStorage.setItem("hf90-session",sid);
  }
  window.hf90SessionId=sid;

  const toolName=()=>{
    const p=location.pathname;
    if(p==="/"||p==="/index.html")return "setup_cost";
    if(p.includes("moving-out-budget"))return "moving_out_budget";
    if(p.includes("household-bills"))return "household_bills";
    if(p.includes("what-to-buy-first"))return "buy_first";
    if(p.includes("first-90-days-planner"))return "pre_move_plan";
    return "";
  };
  const cleanTag=v=>String(v||"").trim().toLowerCase().replace(/[^a-z0-9_-]/g,"").slice(0,60);
  const deriveSource=()=>{
    try{
      const q=new URLSearchParams(location.search);
      const tagged=cleanTag(q.get("src")||q.get("utm_source"));
      if(tagged)return tagged;
      if(!document.referrer)return "direct";
      const r=new URL(document.referrer);
      if(r.hostname===location.hostname)return "internal";
      if(/google\.|bing\.|duckduckgo\.|yahoo\./i.test(r.hostname))return "search";
      return "external";
    }catch(e){return "unknown"}
  };
  const q=new URLSearchParams(location.search);
  const querySource=cleanTag(q.get("src")||q.get("utm_source"));
  const queryCampaign=cleanTag(q.get("campaign")||q.get("utm_campaign"));
  let attributedSource=sessionStorage.getItem("hf90-source")||"";
  let attributedCampaign=sessionStorage.getItem("hf90-campaign")||"";
  if(querySource){attributedSource=querySource;sessionStorage.setItem("hf90-source",attributedSource)}
  if(queryCampaign){attributedCampaign=queryCampaign;sessionStorage.setItem("hf90-campaign",attributedCampaign)}
  if(!attributedSource){attributedSource=deriveSource();sessionStorage.setItem("hf90-source",attributedSource)}
  function track(event,metadata={}){
    const enriched={source:attributedSource||"unknown",campaign:attributedCampaign||"",...metadata};
    fetch(API+"/api/event",{
      method:"POST",
      mode:"cors",
      keepalive:true,
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({event,path:location.pathname,session:sid,metadata:enriched})
    }).catch(()=>{});
  }
  window.hf90Track=track;

  track("page_view");
  if(location.pathname.includes("checkout-success"))track("checkout_return",{stage:"payment_return"});
  if(location.pathname.includes("complete-home"))track("complete_open",{stage:"dashboard"});

  // Record a completion when a free tool actually saves a result, not merely when the user clicks.
  const completionKeys={
    "homefirst90-home":"setup_cost",
    "homefirst90-moving":"moving_out_budget",
    "homefirst90-bills":"household_bills",
    "homefirst90-move-profile":"pre_move_plan"
  };
  const originalSetItem=Storage.prototype.setItem;
  Storage.prototype.setItem=function(key,value){
    const out=originalSetItem.apply(this,arguments);
    try{
      if(this===localStorage&&completionKeys[key]){
        const tool=completionKeys[key];
        track("tool_complete",{tool,stage:"complete"});
        if(key==="homefirst90-home")track("home_saved",{stage:"home_profile"});
      }
    }catch(e){}
    return out;
  };

  let lastTool=0;
  function toolRun(){
    const now=Date.now(); if(now-lastTool<800)return; lastTool=now;
    const t=toolName(); if(t)track("tool_run",{tool:t,stage:"start"});
  }

  document.addEventListener("submit",toolRun,true);
  document.addEventListener("click",e=>{
    const a=e.target.closest&&e.target.closest("a");
    if(a&&/buy\.stripe\.com/i.test(a.href||""))track("complete_checkout_click",{stage:"checkout"});

    const b=e.target.closest&&e.target.closest("button");
    if(b&&(b.id==="run"||b.id==="build"))toolRun();

    // The shopping-order tool renders without writing a separate result to localStorage,
    // so a successful click is its completion signal.
    if(b&&b.id==="run"&&toolName()==="buy_first"){
      setTimeout(()=>track("tool_complete",{tool:"buy_first",stage:"complete"}),0);
    }
  },true);
})();