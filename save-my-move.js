(()=>{
  const API="https://homefirst90-api.onrender.com";
  const host=document.currentScript?.dataset?.host||"";
  function savedMoveDate(){
    try{
      const p=JSON.parse(localStorage.getItem("homefirst90-move-profile")||"null");
      return p&&p.date?p.date:"";
    }catch(e){return""}
  }
  function card(){
    const wrap=document.createElement("section");
    wrap.id="hf90-save-move";
    wrap.style.cssText="max-width:1080px;margin:20px auto;padding:0 20px";
    wrap.innerHTML=`
      <div style="background:#edf4f0;border:2px solid #153f33;border-radius:20px;padding:20px">
        <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;font-weight:900;color:#153f33">SAVE MY MOVE</div>
        <h2 style="margin:6px 0 6px;font-size:28px;line-height:1.1">Don’t lose your plan when moving day gets closer.</h2>
        <p style="margin:0 0 14px;color:#55645e">Save your moving date and email. We’ll send three useful reminders around your move — 14 days before, 3 days before and on moving day. No newsletter.</p>
        <form id="hf90-move-form" style="display:grid;grid-template-columns:1fr 180px auto;gap:10px;align-items:end">
          <label style="font-size:13px;font-weight:800">Email<input name="email" type="email" required autocomplete="email" style="display:block;width:100%;margin-top:5px;padding:11px;border:1px solid #bdc9c3;border-radius:10px"></label>
          <label style="font-size:13px;font-weight:800">Moving date<input name="move_date" type="date" required value="${savedMoveDate()}" style="display:block;width:100%;margin-top:5px;padding:10px;border:1px solid #bdc9c3;border-radius:10px"></label>
          <button type="submit" style="border:0;background:#153f33;color:white;border-radius:10px;padding:12px 15px;font-weight:900;cursor:pointer">Save my move</button>
          <input name="website" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-10000px;width:1px;height:1px">
          <label style="grid-column:1/-1;font-size:12px;color:#61706a"><input name="consent" type="checkbox" required style="margin-right:6px">Email me three move-date reminders with practical moving tips and relevant HomeFirst90 product information. I can unsubscribe at any time.</label>
          <div id="hf90-move-msg" style="grid-column:1/-1;font-size:13px;font-weight:700"></div>
        </form>
      </div>`;
    const main=document.querySelector("main");
    if(main) main.appendChild(wrap); else document.body.appendChild(wrap);
    const form=wrap.querySelector("#hf90-move-form"),msg=wrap.querySelector("#hf90-move-msg");
    const dateInput=form.elements.move_date;
    const today=new Date(); today.setHours(0,0,0,0);
    dateInput.min=today.toISOString().slice(0,10);
    const max=new Date(today); max.setFullYear(max.getFullYear()+2);
    dateInput.max=max.toISOString().slice(0,10);
    form.addEventListener("submit",async e=>{
      e.preventDefault();
      msg.textContent="Saving…";
      const body={
        email:form.elements.email.value.trim(),
        move_date:dateInput.value,
        consent:form.elements.consent.checked,
        website:form.elements.website.value,
        source_path:location.pathname,
        session:window.hf90SessionId||""
      };
      try{
        const r=await fetch(API+"/api/save-move",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
        const d=await r.json();
        if(!r.ok) throw new Error(d.error||"Could not save your move.");
        localStorage.setItem("homefirst90-saved-move",JSON.stringify({email:body.email,move_date:body.move_date}));
        msg.style.color="#153f33";
        msg.textContent="Saved ✓ We’ll email you around your moving date.";
        form.querySelector("button").disabled=true;
        form.querySelector("button").textContent="Saved ✓";
      }catch(err){
        msg.style.color="#8a2d1f";
        msg.textContent=err.message||"Could not save your move. Please try again.";
      }
    });
    const existing=localStorage.getItem("homefirst90-saved-move");
    if(existing){
      try{
        const x=JSON.parse(existing);
        if(x.email)form.elements.email.value=x.email;
        if(x.move_date)dateInput.value=x.move_date;
      }catch(e){}
    }
  }
  async function autoMount(){
    if(host==="preview"){card();return}
    try{
      const r=await fetch(API+"/api/move/status",{cache:"no-store"});
      const d=await r.json();
      if(d&&d.enabled)card();
    }catch(e){}
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",autoMount);else autoMount();
  window.HomeFirst90SaveMove={mount:card};
})();