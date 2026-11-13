"""用真实浏览器投递官网联系表单（通用版）。

为什么必须用浏览器：
- 多数建站平台（Wix / Squarespace / Webflow / Framer / Mailchimp）对非浏览器 UA
  直接 403（Python 探测结果里 6 家平台方全是 unreachable，但浏览器能开）。
- 表单字段名、必填项、隐藏 token、CSRF 都由前端决定。

流程：
1. 打开联系页，列出可见表单字段
2. 填入询盘（按 field name / type / placeholder 启发式匹配）
3. 提交，抓网络 POST 响应 + 页面成功提示
4. 落盘 evidence/<公司>.json

失败会明确记录卡在哪一步，不静默吞掉。
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from browser_form import Page, new_tab, save_evidence  # noqa: E402

BASE = r"<project>"

# 询盘正文
def build_message(email, name="Kai Zhang", company="Linforge Studio"):
    return f"""Hi {name.replace(' ', '')} team,

I'm Kai, an AI video producer running a local pipeline for 9:16 vertical micro-drama: consistent character bibles (three-view character sheets), voice cloning, pose and wardrobe reference, shot generation, TTS voice-over, and burned-in subtitles placed in the platform safe area.

I work as a production partner, not a tool rental: you get finished episodes, not raw clips. Typical deliverables:
- Paid look test: 6-8s, 9:16, 1 character, 1 line - $99
- Single finished episode (45-90s): $250-$450
- Series (10+ episodes): from $200/episode
- Character bible per character: $60-$150

Character consistency across episodes and a repeatable production flow are the part I specialise in, which is usually what breaks when AI drama is scaled up.

Reply to this message and I will send two finished vertical samples (17.6s each, 1104x1968, English voice-over, burned-in subtitles) plus a storyboard for a topic of your choice. If those are not what you need, the $99 look test is the cheapest way to check the output on your own subject before you commit to a full episode.

Best,
{name}
{company}
{email}

This AI-generated content was produced with human creative direction, script, editing and supervision."""


FIELD_HINT = [
    # (正则匹配 name/id/placeholder, 提供的值来源)
    (r"name|fullname|full_name|first|your.?name|contact.?name|^fname$|given",
     "NAME", "text"),
    (r"email|e-mail|mail", "EMAIL", "email"),
    (r"company|organi[sz]ation|brand|studio|agency|outfit", "COMPANY", "text"),
    (r"phone|tel|mobile", "PHONE", "tel"),
    (r"message|enquir|detail|comment|note|body|content|project|brief|tell", "MSG", "textarea"),
    (r"budget|rate|price", "BUDGET", "text"),
    (r"subject|topic", "SUBJECT", "text"),
    (r"url|website|site|portfolio", "WEBSITE", "url"),
]


def classify(fields):
    """给每个可见字段分配填什么值。返回 {字段序号: 类型}。"""
    out = {}
    used = set()
    for f in fields:
        hay = " ".join([f.get("name") or "", f.get("id") or "", f.get("ph") or "",
                         f.get("aria") or "", f.get("label") or ""]).lower()
        ftype = f.get("type") or "text"
        if ftype in ("hidden", "checkbox", "radio", "submit", "button", "file"):
            continue
        pick = None
        for pat, kind, _t in FIELD_HINT:
            if kind in used:
                continue
            if re.search(pat, hay):
                pick = kind
                break
        if pick is None:
            if ftype == "email":
                pick = "EMAIL"
            elif ftype == "textarea" or f.get("tag") == "TEXTAREA":
                pick = "MSG"
            else:
                pick = "TEXT"
        out[f["idx"]] = pick
        used.add(pick)
    return out


VALUES = {
    "NAME": ("Kai Zhang", "Kai Zhang"),
    "EMAIL": ("zycbb287673751@163.com", "zycbb287673751@163.com"),
    "COMPANY": ("Linforge Studio", "Linforge Studio"),
    "PHONE": ("", ""),
    "MSG": ("", ""),
    "BUDGET": ("$250-$450 per episode", ""),
    "SUBJECT": ("AI vertical micro-drama production - paid test offer", ""),
    "WEBSITE": ("", ""),
    "TEXT": ("", ""),
}


def collect_fields(page):
    """收集可见表单字段。

    关键：必须排除 honeypot。Framer 等站会渲染十几个 width=0 的隐藏输入
    （website/company/message/subject...），那是反 spam 陷阱，填了就等于
    被判定为机器人而静默丢弃。判据用 getBoundingClientRect 的实际宽高，
    而不是 offsetParent（hidden 类型的可见性判断在部分站会误判）。
    """
    return page.js(r"""
(()=>{
 const out=[];
 let idx=0;
 document.querySelectorAll('input, textarea, select').forEach(el=>{
   const r=el.getBoundingClientRect();
   const t=(el.type||'').toLowerCase();
   if(t==='hidden'||t==='checkbox'||t==='radio'||t==='submit'||t==='button'||t==='file'||t==='reset') return;
   if(r.width<8||r.height<8) return;                       // honeypot 排除
   if(getComputedStyle(el).visibility==='hidden') return;
   if(getComputedStyle(el).display==='none') return;
   let label='';
   if(el.id){ const l=document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if(l) label=(l.textContent||'').trim(); }
   if(!label && el.closest('label')) label=(el.closest('label').textContent||'').trim();
   out.push({idx: idx++,
            tag: el.tagName, type: el.type||'', name: el.name||'', id: el.id||'',
            ph: el.placeholder||'', aria: el.getAttribute('aria-label')||'', label: label.slice(0,80),
            required: !!el.required});
 });
 const forms=[...document.querySelectorAll('form')].map(f=>({
   action:f.action||'', method:(f.method||'get').toLowerCase(),
   id:f.id||'', cls:(f.className||'').toString().slice(0,60),
   visible: !!f.offsetParent,
   nfields: f.querySelectorAll('input,textarea,select').length}));
 const btns=[...document.querySelectorAll('button, input[type=submit], [role=button]')]
   .filter(b=>b.offsetParent).map(b=>({t:(b.textContent||b.value||'').trim().slice(0,40), tag:b.tagName, type:b.type||''}));
 return JSON.stringify({fields:out, forms, btns:btns.slice(0,25)});
})()
""")


def fill_by_name(page, name, value):
    """按 name 属性定位并填值。

    比 idx 稳：页面结构一变 idx 就错位，而 name 是表单契约的一部分。
    找不到时返回 NO_EL（不静默跳过）。
    """
    r = page.js(r"""
(()=>{
 const el=[...document.querySelectorAll('input,textarea,select')]
   .find(e=>e.getAttribute('name')===%s);
 if(!el) return 'NO_EL';
 const t=(el.type||'').toLowerCase();
 if(['hidden','checkbox','radio','submit','button','file','reset'].includes(t)){
   // 隐藏字段也要能填（如 Webflow 的 route-to），但 checkbox/radio 需单独处理
   if(['hidden'].includes(t)){
     const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
     Object.getOwnPropertyDescriptor(proto,'value').set.call(el,%s);
     el.dispatchEvent(new Event('input',{bubbles:true}));
     el.dispatchEvent(new Event('change',{bubbles:true}));
     return 'OK:'+(el.value||'').length;
   }
   return 'SKIP:'+t;
 }
 el.scrollIntoView({block:'center'});
 const q=el.getBoundingClientRect();
 try{ el.focus({preventScroll:true}); if(el.select) el.select(); }catch(e){}
 return JSON.stringify({x:q.x+q.width/2,y:q.y+q.height/2,tag:el.tagName});
})()
""" % (json.dumps(name), json.dumps(value)))
    if r == "NO_EL":
        return "NO_EL"
    if isinstance(r, str) and r.startswith("OK:"):
        return r
    if isinstance(r, str) and r.startswith("SKIP:"):
        return r
    if not isinstance(r, str):
        return "NO_EL"
    pos = json.loads(r)
    if pos.get("tag") == "SELECT":
        return page.js(r"""
(()=>{const el=[...document.querySelectorAll('input,textarea,select')]
  .find(e=>e.getAttribute('name')===%s);
 if(!el) return 'NO_EL';
 Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(el,%s);
 el.dispatchEvent(new Event('input',{bubbles:true}));
 el.dispatchEvent(new Event('change',{bubbles:true}));
 return 'OK:'+(el.value||'');})()
""" % (json.dumps(name), json.dumps(value)))
    try:
        for ev, btn, clicks in (("mouseMoved", 0, 0), ("mousePressed", 1, 1), ("mouseReleased", 0, 1)):
            d = {"type": ev, "x": pos["x"], "y": pos["y"], "button": "left",
                 "buttons": btn, "clickCount": clicks}
            if ev == "mouseMoved":
                d["buttons"] = 0
            page.send("Input.dispatchMouseEvent", d)
            time.sleep(0.12)
        # 真实点击可能被页面重排/横幅遮挡带走焦点：校验 activeElement，
        # 不对则用 JS focus 兜底（insertText 只发给当前焦点元素）。
        act = page.js(r"""
(()=>{const a=document.activeElement;
 return a?(a.getAttribute('name')||a.tagName):'NONE';})()
""")
        if act != name:
            page.js(r"""
(()=>{const el=[...document.querySelectorAll('input,textarea,select')]
  .find(e=>e.getAttribute('name')===%s);
 if(el){el.scrollIntoView({block:'center'});el.focus({preventScroll:true});
   if(el.select&&el.tagName!=='SELECT')el.select();}
 return 'FOCUSED';})()
""" % json.dumps(name))
            time.sleep(0.15)
        page.send("Input.insertText", {"text": value})
        time.sleep(0.05)
        for ev in ("keyDown", "keyUp"):
            page.send("Input.dispatchKeyEvent",
                      {"type": ev, "key": "End", "code": "End", "windowsVirtualKeyCode": 35})
        time.sleep(0.25)
    except Exception as e:
        return "CDP_ERR:" + str(e)[:80]
    got = page.js(r"""
(()=>{const el=[...document.querySelectorAll('input,textarea,select')]
  .find(e=>e.getAttribute('name')===%s);
 if(!el) return 'NO_EL';
 return 'OK:'+(el.value||'').length;})()
""" % json.dumps(name))
    # 长度校验：值没进去必须报错，不能静默通过
    if isinstance(got, str) and got.startswith("OK:"):
        n = int(got[3:] or 0)
        if n < len(value) * 0.9:
            return "SHORT:%d/%d" % (n, len(value))
    return got


def fill(page, key, value):
    """按收集时的序号定位元素。

    优先用 CDP 真实键盘（Input.insertText）：React 受控组件只认真实输入事件，
    纯 JS setter + dispatchEvent 在 Framer/Next 等站不会更新 state，
    结果是表单看着填好了却永远不提交。
    """
    # 1) 真实点击聚焦（同时用 JS focus + select 兜底，防止 20px 高的输入框点击落空）
    r = page.js(r"""
(()=>{const list=[...document.querySelectorAll('input, textarea, select')].filter(el=>{
   const t=(el.type||'').toLowerCase();
   if(['hidden','checkbox','radio','submit','button','file','reset'].includes(t)) return false;
   const r=el.getBoundingClientRect(); if(r.width<8||r.height<8) return false;
   if(getComputedStyle(el).visibility==='hidden'||getComputedStyle(el).display==='none') return false;
   return true;});
 const el=list[%d]; if(!el) return 'NO_EL';
 el.scrollIntoView({block:'center'});
 const q=el.getBoundingClientRect();
 try{ el.focus({preventScroll:true}); if(el.select) el.select(); }catch(e){}
 return JSON.stringify({x:q.x+q.width/2, y:q.y+q.height/2, tag:el.tagName, focused: document.activeElement===el});})()
""" % key)
    if r == "NO_EL":
        return "NO_EL"
    pos = json.loads(r)
    # SELECT：键盘输入无效，直接设值 + 触发 change
    if pos.get("tag") == "SELECT":
        return page.js(r"""
(()=>{const list=[...document.querySelectorAll('input:not([type=hidden]), textarea, select')].filter(el=>{
   if(!el.offsetParent && el.tagName!=='SELECT') return false;
   const r=el.getBoundingClientRect(); return !(r.width<2||r.height<2);});
 const el=list[%d]; if(!el) return 'NO_EL';
 const proto=HTMLSelectElement.prototype;
 Object.getOwnPropertyDescriptor(proto,'value').set.call(el, %s);
 el.dispatchEvent(new Event('input',{bubbles:true}));
 el.dispatchEvent(new Event('change',{bubbles:true}));
 return 'OK:'+(el.value||'');})()
""" % (key, json.dumps(value)))
    try:
        page.send("Input.dispatchMouseEvent",
                  {"type": "mouseMoved", "x": pos["x"], "y": pos["y"], "buttons": 0})
        time.sleep(0.25)
        page.send("Input.dispatchMouseEvent",
                  {"type": "mousePressed", "x": pos["x"], "y": pos["y"],
                   "button": "left", "buttons": 1, "clickCount": 1})
        time.sleep(0.12)
        page.send("Input.dispatchMouseEvent",
                  {"type": "mouseReleased", "x": pos["x"], "y": pos["y"],
                   "button": "left", "buttons": 0, "clickCount": 1})
        time.sleep(0.2)
        if pos["tag"] == "SELECT":
            page.send("Input.insertText", {"text": value})
        else:
            # Input.insertText 不产生 keydown/keyup，而 Duda / WordPress 等表单
            # 用 jQuery 监听 keyup 同步值，校验会认为字段为空而静默拒绝。
            # 折中：insertText 填值（快）后补发一次真实 keyup，触发该 handler。
            page.send("Input.insertText", {"text": value})
            time.sleep(0.05)
            for ev in ("keyDown", "keyUp"):
                page.send("Input.dispatchKeyEvent",
                          {"type": ev, "key": "End", "code": "End",
                           "windowsVirtualKeyCode": 35})
        time.sleep(0.35)
        page.send("Input.dispatchKeyEvent",
                  {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
        page.send("Input.dispatchKeyEvent",
                  {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
        time.sleep(0.2)
    except Exception as e:
        return "CDP_ERR:" + str(e)[:80]
    # 2) 读回长度校验（值真的进去了吗）
    return page.js(r"""
(()=>{const list=[...document.querySelectorAll('input, textarea, select')].filter(el=>{
   const t=(el.type||'').toLowerCase();
   if(['hidden','checkbox','radio','submit','button','file','reset'].includes(t)) return false;
   const r=el.getBoundingClientRect(); if(r.width<8||r.height<8) return false;
   if(getComputedStyle(el).visibility==='hidden'||getComputedStyle(el).display==='none') return false;
   return true;});
 const el=list[%d]; if(!el) return 'NO_EL';
 return 'OK:'+(el.value||'').length;})()
""" % key)


def submit_and_read(page, timeout=22):
    """点击最像提交按钮的按钮，然后收集结果。

    判据纪律：GA / 埋点 / analytics 的 POST 不算表单提交。
    只认业务端点（含 form/contact/apply/enquiry/subscribe/inquiry/mail 等语义）
    或页面出现成功文案。否则会出现「看起来提交了其实没发」的假绿。
    """
    page.events.clear()
    btn = page.js(r"""
(()=>{
 const cands=[...document.querySelectorAll('button, input[type=submit], [role=button]')].filter(b=>b.offsetParent);
 const score=b=>{
   const t=((b.textContent||b.value||'')+' '+b.className+' '+(b.getAttribute('type')||'')).toLowerCase();
   let s=0;
   if(/submit|send|enquir|contact|message|apply|inquir|go|book/.test(t)) s+=10;
   if(/type=.submit|type=submit/.test(t)) s+=6;
   if(/cancel|close|dismiss|cookie|accept|reject|privacy|menu|nav|back|next|skip|read more|learn more/.test(t)) s-=8;
   return s;};
 const best=cands.sort((a,b)=>score(b)-score(a))[0];
 if(!best) return 'NO_BTN';
 best.scrollIntoView({block:'center'});
 const q=best.getBoundingClientRect();
 return JSON.stringify({x:q.x+q.width/2, y:q.y+q.height/2, t:(best.textContent||best.value||'').trim().slice(0,40), score:score(best)});
})()
""")
    if not btn or btn == "NO_BTN":
        return {"clicked": False, "reason": "no button"}
    info = json.loads(btn)
    page.click(info["x"], info["y"])
    time.sleep(timeout)
    # 网络证据：只保留业务端点 POST
    ANALYTICS = ("google-analytics.com", "doubleclick.net", "googletagmanager",
                 "events.framer.com", "facebook.net", "clarity.ms", "hotjar",
                 "segment.io", "mixpanel", "sentry.io", "posthog")
    posts, analytics = [], []
    for e in page.events:
        m = e.get("method")
        if m == "Network.requestWillBeSent":
            rq = e["params"]["request"]
            if rq.get("method") == "POST":
                u = rq["url"]
                item = {"url": u, "post": (rq.get("postData") or "")[:400]}
                (analytics if any(a in u for a in ANALYTICS) else posts).append(item)
        elif m == "Network.responseReceived":
            rs = e["params"]["response"]
            u = rs.get("url", "")
            if rs.get("status", 0) >= 400 and not any(a in u for a in ANALYTICS):
                posts.append({"err_status": rs["status"], "url": u})
    # 页面提示
    state = page.js(r"""
(()=>{
 const txt=(document.body.innerText||'').replace(/\s+/g,' ');
 const hints=[...document.querySelectorAll('[class*=success],[class*=thank],[role=status],[role=alert],[class*=toast],[class*=error],[class*=invalid]')]
   .map(e=>(e.textContent||'').trim()).filter(t=>t&&t.length>4&&t.length<220).slice(0,6);
 const btnTxt=[...document.querySelectorAll('button')].map(b=>(b.textContent||'').trim()).filter(Boolean).slice(0,8);
 return JSON.stringify({
   hints, btn_texts: btnTxt,
   body_head: txt.slice(0,400),
   has_form: !!document.querySelector('form'),
   still_empty: [...document.querySelectorAll('input:not([type=hidden]),textarea')]
     .filter(e=>{const r=e.getBoundingClientRect();return r.width>8&&r.height>8;})
     .map(e=>(e.name||e.type)+':'+((e.value||'').length)).join('|')
 });
})()
""")
    return {"clicked": True, "button": info, "posts": posts[:8],
            "analytics_posts": len(analytics), "page": json.loads(state)}
