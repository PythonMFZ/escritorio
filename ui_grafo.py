# ui_grafo.py — Segundo Cérebro: grafo de conhecimento operacional
# Exec'd no namespace do app.py
#
# Rota:  GET /admin/grafo        — visualização interativa (canvas nativo)
# Rota:  GET /api/grafo/data     — JSON nodes + edges

from fastapi.responses import JSONResponse as _JR_grafo

# ── API de dados ──────────────────────────────────────────────────────────────

@app.get("/api/grafo/data")
@require_login
async def api_grafo_data(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _JR_grafo({"erro": "sem permissão"}, status_code=403)

    cid = ctx.company.id
    filter_client = request.query_params.get("client_id")
    filter_client_id = int(filter_client) if filter_client and filter_client.isdigit() else None

    nodes = []
    edges = []
    seen_edges = set()

    def add_node(id_, label, group, title="", url="", size=18):
        nodes.append({"id": id_, "label": label, "group": group,
                      "title": title, "url": url, "size": size})

    def add_edge(src, dst, label=""):
        key = f"{src}|{dst}"
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"from": src, "to": dst, "label": label})

    # Clientes
    try:
        clientes = session.exec(select(Client).where(Client.company_id == cid)).all()
        if filter_client_id:
            clientes = [c for c in clientes if c.id == filter_client_id]
        client_ids = {c.id for c in clientes}
        for c in clientes:
            add_node(f"client_{c.id}", (c.name or f"#{c.id}")[:20], "client",
                     title=f"Cliente: {c.name}", url=f"/client/switch?client_id={c.id}", size=26)
    except Exception:
        clientes = []; client_ids = set()

    # Membros
    user_ids_seen = set()
    try:
        for m in session.exec(select(Membership).where(Membership.company_id == cid)).all():
            u = session.get(User, m.user_id)
            if not u or m.user_id in user_ids_seen:
                continue
            user_ids_seen.add(m.user_id)
            add_node(f"user_{m.user_id}", (u.name or u.email or f"#{m.user_id}")[:18], "user",
                     title=f"{u.name or ''} ({m.role})\n{u.email or ''}", url="/admin/members")
    except Exception:
        pass

    # Reuniões
    try:
        q = select(Meeting).where(Meeting.company_id == cid)
        if filter_client_id:
            q = q.where(Meeting.client_id == filter_client_id)
        for mt in session.exec(q).all():
            if mt.client_id not in client_ids:
                continue
            add_node(f"meet_{mt.id}", (mt.title or "Reunião")[:20], "meeting",
                     title=f"Reunião: {mt.title}\nData: {mt.meeting_date or '—'}",
                     url=f"/reunioes/{mt.id}")
            add_edge(f"client_{mt.client_id}", f"meet_{mt.id}")
            if mt.created_by_user_id in user_ids_seen:
                add_edge(f"user_{mt.created_by_user_id}", f"meet_{mt.id}", "criou")
    except Exception:
        pass

    # Ações corretivas
    try:
        q = select(MeetingAcao).where(MeetingAcao.company_id == cid)
        if filter_client_id:
            q = q.where(MeetingAcao.client_id == filter_client_id)
        for a in session.exec(q).all():
            grp = "acao_alta" if a.prioridade == "alta" else "acao"
            prazo = f"\nPrazo: {a.prazo}" if a.prazo else ""
            resp = f"\nResp: {a.responsavel}" if a.responsavel else ""
            add_node(f"acao_{a.id}", (a.titulo or "Ação")[:20], grp,
                     title=f"[{a.prioridade.upper()}] {a.titulo}\n{a.status}{prazo}{resp}",
                     url=f"/reunioes/{a.meeting_id}/acoes", size=14)
            add_edge(f"meet_{a.meeting_id}", f"acao_{a.id}", a.status)
            if a.responsavel_user_id and a.responsavel_user_id in user_ids_seen:
                add_edge(f"user_{a.responsavel_user_id}", f"acao_{a.id}", "resp.")
    except Exception:
        pass

    # Planos orçamentários
    try:
        q = select(BudgetPlan).where(BudgetPlan.company_id == cid, BudgetPlan.is_active == True)
        if filter_client_id:
            q = q.where(BudgetPlan.client_id == filter_client_id)
        for p in session.exec(q).all():
            if p.client_id and p.client_id not in client_ids:
                continue
            add_node(f"budget_{p.id}", f"Orç.{p.year}", "budget",
                     title=f"Orçamento: {p.name}\nAno: {p.year}",
                     url=f"/ferramentas/orcamento/{p.id}", size=20)
            if p.client_id:
                add_edge(f"client_{p.client_id}", f"budget_{p.id}", "orçamento")
    except Exception:
        pass

    # Desvios
    try:
        for al in session.exec(select(BudgetAlert).where(BudgetAlert.company_id == cid)).all():
            acc = session.get(BudgetAccount, al.account_id)
            if not acc:
                continue
            if filter_client_id and acc.client_id != filter_client_id:
                continue
            add_node(f"desvio_{al.id}", f"⚠ {acc.name[:16]}", "desvio",
                     title=f"Alerta: {acc.name}\nTol:{al.tolerance_pct}% Crit:{al.critical_pct}%",
                     url="#", size=14)
            if acc.client_id:
                pl = session.exec(select(BudgetPlan).where(
                    BudgetPlan.company_id == cid,
                    BudgetPlan.client_id == acc.client_id,
                    BudgetPlan.is_active == True,
                )).first()
                if pl:
                    add_edge(f"budget_{pl.id}", f"desvio_{al.id}", "desvio")
    except Exception:
        pass

    return _JR_grafo({"nodes": nodes, "edges": edges})


# ── Página ────────────────────────────────────────────────────────────────────

@app.get("/admin/grafo", response_class=HTMLResponse)
@require_login
async def admin_grafo_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)
    clientes = []
    try:
        clientes = session.exec(select(Client).where(Client.company_id == ctx.company.id)).all()
    except Exception:
        pass
    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("admin_grafo.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc, "clientes": clientes,
    })


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATES["admin_grafo.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  #grafo-wrap {
    width:100%; height:calc(100vh - 195px); min-height:480px;
    background:#0d1117; border-radius:12px; position:relative; overflow:hidden;
  }
  #gc { width:100%; height:100%; display:block; cursor:grab; }
  #gc:active { cursor:grabbing; }
  #grafo-legend {
    position:absolute; top:12px; left:12px;
    background:rgba(0,0,0,.75); border-radius:8px;
    padding:10px 14px; color:#ddd; font-size:.73rem; line-height:1.8;
    backdrop-filter:blur(6px); user-select:none;
  }
  #grafo-legend b { display:block; margin-bottom:2px; color:#fff; font-size:.8rem; }
  #grafo-legend i { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; vertical-align:middle; }
  #tip {
    position:fixed; pointer-events:none; display:none;
    background:rgba(10,10,20,.9); color:#eee;
    border-radius:8px; padding:8px 12px; font-size:.77rem;
    max-width:220px; white-space:pre-wrap; z-index:9999;
    box-shadow:0 4px 20px rgba(0,0,0,.5); line-height:1.5;
  }
  .grafo-bar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:10px; }
  #grafo-stats { color:#888; font-size:.78rem; }
</style>

<div class="grafo-bar">
  <h4 class="mb-0">🧠 Segundo Cérebro</h4>
  <select id="sel-client" class="form-select form-select-sm" style="max-width:220px;">
    <option value="">Todos os clientes</option>
    {% for c in clientes %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}
  </select>
  <button class="btn btn-sm btn-outline-secondary" onclick="fitAll()">⊡ Centralizar</button>
  <button class="btn btn-sm btn-outline-secondary" id="btn-pause">⏸ Pausar</button>
  <span id="grafo-stats">carregando…</span>
</div>

<div id="grafo-wrap">
  <canvas id="gc"></canvas>
  <div id="grafo-legend">
    <b>Legenda</b>
    <div><i style="background:#4ade80"></i>Cliente</div>
    <div><i style="background:#60a5fa"></i>Reunião</div>
    <div><i style="background:#fb923c"></i>Ação</div>
    <div><i style="background:#f87171"></i>Ação alta prior.</div>
    <div><i style="background:#a78bfa"></i>Orçamento</div>
    <div><i style="background:#fbbf24"></i>Pessoa</div>
    <div><i style="background:#f43f5e"></i>Desvio</div>
    <div><i style="background:#22d3ee"></i>Integração API</div>
    <div><i style="background:#d1d5db"></i>Arquivo Drive</div>
  </div>
</div>
<div id="tip"></div>

<script>
const PALETTE = {
  client:    {f:"#4ade80",s:"#16a34a",t:"#052e16"},
  meeting:   {f:"#60a5fa",s:"#2563eb",t:"#1e3a5f"},
  acao:      {f:"#fb923c",s:"#ea580c",t:"#3b0a00"},
  acao_alta: {f:"#f87171",s:"#dc2626",t:"#450a0a"},
  budget:    {f:"#a78bfa",s:"#7c3aed",t:"#2e1065"},
  user:      {f:"#fbbf24",s:"#d97706",t:"#451a03"},
  desvio:    {f:"#f43f5e",s:"#be123c",t:"#fff"},
  api_integ: {f:"#22d3ee",s:"#0891b2",t:"#083344"},
  drive_file:{f:"#d1d5db",s:"#6b7280",t:"#111827"},
};

const cv = document.getElementById("gc");
const cx = cv.getContext("2d");
const tip = document.getElementById("tip");

let nodes=[], edges=[], nmap={};
let tx=0, ty=0, sc=1;
let drag=null, pan=null, hov=null;
let paused=false, ticks=0, ambient=false;
const MAX_TICKS=600; // ticks para estabilização inicial; depois entra em modo deriva

// ── Resize ────────────────────────────────────────────────────────────────
function resize(){
  cv.width=cv.offsetWidth; cv.height=cv.offsetHeight;
}
window.addEventListener("resize", resize);

// ── Coordenadas ───────────────────────────────────────────────────────────
function w2s(wx,wy){ return {x: wx*sc+tx+cv.width/2, y: wy*sc+ty+cv.height/2}; }
function s2w(sx,sy){ return {x:(sx-cv.width/2-tx)/sc, y:(sy-cv.height/2-ty)/sc}; }
function hit(wx,wy){
  let best=null,bd=Infinity;
  nodes.forEach(n=>{
    const r=(n.size||16)+6; // world-space radius — correto para qualquer zoom
    const d=Math.hypot(wx-n.x,wy-n.y);
    if(d<r && d<bd){bd=d;best=n;}
  });
  return best;
}

// ── Física ────────────────────────────────────────────────────────────────
// Fase 1 (ticks < MAX_TICKS): estabilização com força total
// Fase 2 (ambient): deriva suave perpétua — forças reduzidas + ruído Browniano
let _ambientSeed = 0;
function _rand(i){ // pseudo-aleatório determinístico por nó (sem Math.random no loop crítico)
  _ambientSeed = (_ambientSeed*1664525 + 1013904223) & 0xffffffff;
  return (_ambientSeed>>>0)/4294967296 - 0.5;
}

function physics(){
  const N=nodes.length;
  if(!N) return;

  if(ambient){
    // ── Modo deriva: molas suaves + ruído Browniano ──────────────────────────
    const SPR_K=0.008, SPR_L=120, DAMP=0.98, GRAV=0.003;
    const NOISE=0.12, MAX_V=1.2;
    nodes.forEach(n=>{ n.fx=0; n.fy=0; });
    // Molas (sem repulsão pra poupar CPU e evitar explosão)
    edges.forEach(e=>{
      const a=nmap[e.from], b=nmap[e.to];
      if(!a||!b) return;
      const dx=b.x-a.x, dy=b.y-a.y;
      const d=Math.sqrt(dx*dx+dy*dy)||1;
      const f=(d-SPR_L)*SPR_K;
      const fx=dx/d*f, fy=dy/d*f;
      a.fx+=fx; a.fy+=fy;
      b.fx-=fx; b.fy-=fy;
    });
    nodes.forEach((n,i)=>{
      if(n===drag) return;
      n.fx -= n.x*GRAV;
      n.fy -= n.y*GRAV;
      // Ruído Browniano: força aleatória suave por nó
      n.fx += _rand(i)*NOISE;
      n.fy += _rand(i)*NOISE;
      n.vx = (n.vx+n.fx)*DAMP;
      n.vy = (n.vy+n.fy)*DAMP;
      const spd=Math.hypot(n.vx,n.vy);
      if(spd>MAX_V){ n.vx=n.vx/spd*MAX_V; n.vy=n.vy/spd*MAX_V; }
      n.x+=n.vx; n.y+=n.vy;
    });
    return;
  }

  // ── Fase inicial: física completa até estabilizar ──────────────────────────
  const REP = Math.min(4000, 800000/N);
  const SPR_K=0.05, SPR_L=100, DAMP=0.75, GRAV=0.02;
  const MAX_V=8;

  nodes.forEach(n=>{ n.fx=0; n.fy=0; });

  for(let i=0;i<N;i++){
    for(let j=i+1;j<N;j++){
      const a=nodes[i], b=nodes[j];
      const dx=a.x-b.x, dy=a.y-b.y;
      const d2=dx*dx+dy*dy+1;
      const f=REP/d2;
      const fx=dx/Math.sqrt(d2)*f, fy=dy/Math.sqrt(d2)*f;
      a.fx+=fx; a.fy+=fy;
      b.fx-=fx; b.fy-=fy;
    }
  }

  edges.forEach(e=>{
    const a=nmap[e.from], b=nmap[e.to];
    if(!a||!b) return;
    const dx=b.x-a.x, dy=b.y-a.y;
    const d=Math.sqrt(dx*dx+dy*dy)||1;
    const f=(d-SPR_L)*SPR_K;
    const fx=dx/d*f, fy=dy/d*f;
    a.fx+=fx; a.fy+=fy;
    b.fx-=fx; b.fy-=fy;
  });

  nodes.forEach(n=>{
    if(n===drag) return;
    n.fx -= n.x*GRAV;
    n.fy -= n.y*GRAV;
    n.vx = (n.vx+n.fx)*DAMP;
    n.vy = (n.vy+n.fy)*DAMP;
    const spd=Math.hypot(n.vx,n.vy);
    if(spd>MAX_V){ n.vx=n.vx/spd*MAX_V; n.vy=n.vy/spd*MAX_V; }
    n.x+=n.vx; n.y+=n.vy;
  });
  ticks++;
  if(ticks>MAX_TICKS){
    ambient=true; // entra em modo deriva perpétua — nunca para
    // Zera velocidades para a transição ser suave
    nodes.forEach(n=>{ n.vx*=0.1; n.vy*=0.1; });
  }
}

// ── Render ────────────────────────────────────────────────────────────────
function draw(){
  resize();
  cx.clearRect(0,0,cv.width,cv.height);
  cx.save();
  cx.translate(tx+cv.width/2, ty+cv.height/2);
  cx.scale(sc,sc);

  // Arestas
  cx.lineWidth=0.8/sc;
  edges.forEach(e=>{
    const a=nmap[e.from], b=nmap[e.to];
    if(!a||!b) return;
    cx.beginPath();
    cx.strokeStyle="rgba(120,130,160,0.28)";
    cx.moveTo(a.x,a.y); cx.lineTo(b.x,b.y);
    cx.stroke();
  });

  // Nós
  nodes.forEach(n=>{
    const p=PALETTE[n.group]||PALETTE.user;
    const r=(n.size||16)*(n===hov?1.3:1);
    if(n===hov){
      cx.beginPath(); cx.arc(n.x,n.y,r+7,0,Math.PI*2);
      cx.fillStyle=p.f+"33"; cx.fill();
    }
    cx.beginPath(); cx.arc(n.x,n.y,r,0,Math.PI*2);
    cx.fillStyle=p.f; cx.fill();
    cx.strokeStyle=p.s; cx.lineWidth=1.2/sc; cx.stroke();

    // Label (só se zoom suficiente)
    if(sc>0.35){
      const fs=Math.max(8,10);
      cx.font=`${fs}px system-ui,sans-serif`;
      cx.fillStyle="#ddd";
      cx.textAlign="center"; cx.textBaseline="top";
      cx.fillText(n.label, n.x, n.y+r+3);
    }
  });
  cx.restore();
}

function loop(){
  if(!paused) physics();
  draw();
  requestAnimationFrame(loop);
}

function _updatePauseBtn(){
  const btn=document.getElementById("btn-pause");
  if(paused) btn.textContent="▶ Retomar";
  else btn.textContent = ambient ? "⏸ Pausar deriva" : "⏸ Pausar";
}

// ── fitAll ────────────────────────────────────────────────────────────────
function fitAll(){
  if(!nodes.length) return;
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  nodes.forEach(n=>{minX=Math.min(minX,n.x);maxX=Math.max(maxX,n.x);minY=Math.min(minY,n.y);maxY=Math.max(maxY,n.y);});
  const pw=cv.width-80, ph=cv.height-80;
  const gw=maxX-minX||1, gh=maxY-minY||1;
  sc=Math.min(pw/gw, ph/gh, 2);
  tx=-((minX+maxX)/2)*sc;
  ty=-((minY+maxY)/2)*sc;
}

// ── Carregar ──────────────────────────────────────────────────────────────
function load(cid){
  fetch("/api/grafo/data"+(cid?`?client_id=${cid}`:``))
    .then(r=>r.json()).then(data=>{
      // Posição inicial em espiral para evitar sobreposição
      nodes=data.nodes.map((n,i)=>{
        const angle=i*2.399; // golden angle
        const rad=Math.sqrt(i)*28;
        return {...n, x:Math.cos(angle)*rad, y:Math.sin(angle)*rad, vx:0,vy:0,fx:0,fy:0};
      });
      edges=data.edges;
      nmap={}; nodes.forEach(n=>nmap[n.id]=n);
      ticks=0; paused=false; ambient=false;
      _updatePauseBtn();
      document.getElementById("grafo-stats").textContent=`${nodes.length} nós · ${edges.length} conexões`;
      setTimeout(fitAll, 2000); // centraliza após 2s de física
    });
}

// ── Eventos mouse ─────────────────────────────────────────────────────────
let dragStart=null; // posição de tela no mousedown, para detectar clique vs drag
cv.addEventListener("mousedown",e=>{
  const r=cv.getBoundingClientRect();
  const sx=e.clientX-r.left, sy=e.clientY-r.top;
  const w=s2w(sx,sy);
  const h=hit(w.x,w.y);
  if(h){ drag=h; dragStart={sx,sy}; }
  else { pan={mx:e.clientX,my:e.clientY,tx,ty}; }
});
cv.addEventListener("mousemove",e=>{
  const r=cv.getBoundingClientRect();
  const sx=e.clientX-r.left, sy=e.clientY-r.top;
  const w=s2w(sx,sy);
  if(drag){ drag.x=w.x; drag.y=w.y; drag.vx=0; drag.vy=0; }
  else if(pan){ tx=pan.tx+(e.clientX-pan.mx); ty=pan.ty+(e.clientY-pan.my); }
  const h=hit(w.x,w.y); hov=h;
  if(h){
    tip.style.display="block";
    tip.style.left=(e.clientX+16)+"px"; tip.style.top=(e.clientY-10)+"px";
    tip.textContent=h.title||h.label;
  } else { tip.style.display="none"; }
});
cv.addEventListener("mouseup",e=>{
  if(drag && dragStart){
    const r=cv.getBoundingClientRect();
    const sx=e.clientX-r.left, sy=e.clientY-r.top;
    // Compara deslocamento de tela (pixels) desde o mousedown — não posição do nó
    const screenDist=Math.hypot(sx-dragStart.sx, sy-dragStart.sy);
    if(screenDist<6 && drag.url && drag.url!=="#") window.location.href=drag.url;
  }
  drag=null; dragStart=null; pan=null;
});
cv.addEventListener("mouseleave",()=>{ drag=null; dragStart=null; pan=null; tip.style.display="none"; });
cv.addEventListener("wheel",e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect();
  const sx=e.clientX-r.left-cv.width/2-tx;
  const sy=e.clientY-r.top-cv.height/2-ty;
  const f=e.deltaY<0?1.1:0.91;
  sc=Math.max(0.08,Math.min(6,sc*f));
  tx-=sx*(f-1); ty-=sy*(f-1);
},{passive:false});

// ── Eventos touch ─────────────────────────────────────────────────────────
let lastPinch=null, touchDragStart=null;
function resetTouchState(){ drag=null; dragStart=null; touchDragStart=null; pan=null; lastPinch=null; }
cv.addEventListener("touchstart",e=>{
  if(e.touches.length>1){
    // Multi-touch: cancela qualquer drag/tap pendente para evitar navegação acidental
    drag=null; dragStart=null; touchDragStart=null; pan=null;
    return;
  }
  const t=e.touches[0];
  const r=cv.getBoundingClientRect();
  const sx=t.clientX-r.left, sy=t.clientY-r.top;
  const w=s2w(sx,sy);
  const h=hit(w.x,w.y);
  if(h){ drag=h; dragStart={sx,sy}; touchDragStart={sx,sy}; }
  else { pan={mx:t.clientX,my:t.clientY,tx,ty}; }
},{passive:true});
cv.addEventListener("touchmove",e=>{
  e.preventDefault();
  if(e.touches.length===2){
    // Pinch: cancela drag/tap do primeiro toque
    drag=null; dragStart=null; touchDragStart=null; pan=null;
    const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,
                       e.touches[0].clientY-e.touches[1].clientY);
    if(lastPinch) sc=Math.max(0.08,Math.min(6,sc*(d/lastPinch)));
    lastPinch=d;
  } else if(e.touches.length===1){
    const t=e.touches[0];
    const r=cv.getBoundingClientRect();
    const sx=t.clientX-r.left, sy=t.clientY-r.top;
    const w=s2w(sx,sy);
    if(drag){ drag.x=w.x; drag.y=w.y; drag.vx=0; drag.vy=0; }
    else if(pan){ tx=pan.tx+(t.clientX-pan.mx); ty=pan.ty+(t.clientY-pan.my); }
  }
},{passive:false});
cv.addEventListener("touchend",e=>{
  if(drag && touchDragStart && e.changedTouches.length){
    const t=e.changedTouches[0];
    const r=cv.getBoundingClientRect();
    const sx=t.clientX-r.left, sy=t.clientY-r.top;
    const screenDist=Math.hypot(sx-touchDragStart.sx, sy-touchDragStart.sy);
    if(screenDist<10 && drag.url && drag.url!=="#") window.location.href=drag.url;
  }
  resetTouchState();
},{passive:true});
cv.addEventListener("touchcancel", resetTouchState, {passive:true});

document.getElementById("btn-pause").addEventListener("click",()=>{
  paused=!paused;
  if(!paused && !ambient){ ticks=0; } // se retomando da pausa pré-ambient, recomeça física
  _updatePauseBtn();
});
document.getElementById("sel-client").addEventListener("change",function(){ load(this.value); });

resize(); load(""); loop();
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["admin_grafo.html"] = TEMPLATES["admin_grafo.html"]

# ── Registrar no menu lateral ─────────────────────────────────────────────────
# Precisa ser feito DEPOIS de app.py definir FEATURE_KEYS e ROLE_DEFAULT_FEATURES
try:
    FEATURE_KEYS["grafo"] = {
        "title": "🧠 Segundo Cérebro",
        "desc": "Grafo de conhecimento operacional — nós e conexões.",
        "href": "/admin/grafo",
    }
    FEATURE_VISIBLE_ROLES["grafo"] = {"admin", "equipe"}
    ROLE_DEFAULT_FEATURES.setdefault("admin", set()).add("grafo")
    ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).add("grafo")
    # Adiciona ao grupo Gestão Interna
    for _grp in FEATURE_GROUPS:
        if _grp.get("key") == "gestao_interna":
            if "grafo" not in _grp.get("features", []):
                _grp["features"].append("grafo")
            break
    print("[grafo] ✅ Feature 'grafo' registrada no menu.")
except Exception as _eg:
    print(f"[grafo] ⚠️ Erro ao registrar feature: {_eg}")

print("[grafo] ✅ Segundo Cérebro — /admin/grafo carregado.")
