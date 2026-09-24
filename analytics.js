(()=>{
  const API="https://homefirst90-api.onrender.com";
  let sid=sessionStorage.getItem("hf90-session");
  if(!sid){
    sid=(self.crypto&&crypto.randomUUID)?crypto.randomUUID():"s_"+Date.now()+"_"+Math.random().toString(36).slice(2);
    sessionStorage.setItem("hf90-session",sid);
  }
  const toolName=()=>{
    const p=location.pathname;
    if(p==="/"||p==="/index.html")return "setup_cost";
    if(p.includes("moving-out-budget"))return "moving_out_budget";
    if(p.includes("household-bills"))return "household_bills";
    if(p.includes("what-to-buy-first"))return "buy_first";
    if(p.includes("first-90-days-planner"))return "pre_move_plan";
    return "";
  };
  const source=()=>{
    try{
      if(!document.referrer)return "direct";
      const r=new URL(document.referrer);
      if(r.hostname===location.hostname)return "internal";
      if(/google\.|bing\.|duckduckgo\.|yahoo\./i.test(r.hostname))return "search";
      return "external";
    }catch(e){return "unknown"}
  };
  function track(event,metadata={}){
    fetch(API+"/api/event",{
      method:"POST",
      mode:"cors",
      keepalive:true,
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({event,path:location.pathname,session:sid,metadata})
    }).catch(()=>{});
  }
  window.hf90Track=track;
  track("page_view",{source:source()});
  if(location.pathname.includes("checkout-success"))track("checkout_return",{stage:"payment_return"});
  if(location.pathname.includes("complete-home"))track("complete_open",{stage:"dashboard"});
  let lastTool=0;
  function toolRun(){
    const now=Date.now(); if(now-lastTool<800)return; lastTool=now;
    const t=toolName(); if(t)track("tool_run",{tool:t});
  }
  document.addEventListener("submit",toolRun,true);
  document.addEventListener("click",e=>{
    const a=e.target.closest&&e.target.closest("a");
    if(a&&/buy\.stripe\.com/i.test(a.href||""))track("complete_checkout_click",{stage:"checkout"});
    const b=e.target.closest&&e.target.closest("button");
    if(b&&(b.id==="run"||b.id==="build"))toolRun();
  },true);
})();