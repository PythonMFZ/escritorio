# ============================================================================
# ui_cliente_grafo.py — 2º Cérebro por client_id
# ============================================================================
# Rotas:
#   GET /cliente/grafo          → página do grafo (gestor vê tudo, usuario só o próprio)
#   GET /api/grafo/cliente      → JSON nodes + edges filtrado por client_id e role
#
# Regras de visibilidade:
#   gestor  → todos os nós do client_id (reuniões, ações, orçamento, BSC, pessoas)
#   usuario → apenas nós onde ele é criador ou responsável
# ============================================================================

from fastapi.responses import JSONResponse as _JR_cg, HTMLResponse as _HTML_cg
from fastapi import Request as _Req_cg, Depends as _Dep_cg
from sqlmodel import Session as _Sess_cg, select as _sel_cg

# ── Helper: papel no cliente ──────────────────────────────────────────────────

def _cg_cliente_role(session, company_id, client_id, user_id):
    try:
        cr = session.exec(
            _sel_cg(ClienteRole).where(
                ClienteRole.company_id == company_id,
                ClienteRole.client_id == client_id,
                ClienteRole.user_id == user_id,
            )
        ).first()
        return cr.role if cr else "usuario"
    except Exception:
        return "usuario"


# ── API de dados do cliente ───────────────────────────────────────────────────

@app.get("/api/grafo/cliente")
@require_login
async def cg_api_data(request: _Req_cg, session: _Sess_cg = _Dep_cg(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role != "cliente":
        return _JR_cg({"erro": "sem permissão"}, status_code=403)

    client_id = ctx.membership.client_id
    if not client_id:
        return _JR_cg({"nodes": [], "edges": []})

    company_id = ctx.company.id
    user_id = ctx.user.id

    # Papel no cliente: gestor vê tudo, usuario vê só o seu
    papel = _cg_cliente_role(session, company_id, client_id, user_id)
    is_gestor = (papel == "gestor")

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

    # Nó do cliente (âncora central)
    try:
        cliente = session.get(Client, client_id)
        if cliente:
            add_node(f"client_{client_id}",
                     (cliente.name or f"#{client_id}")[:20], "client",
                     title=f"Cliente: {cliente.name}", url="#", size=30)
    except Exception:
        pass

    # Usuários conectados ao cliente (gestor vê todos, usuario vê só a si mesmo)
    user_ids_in_graph = set()
    try:
        if is_gestor:
            memberships = session.exec(
                _sel_cg(Membership).where(
                    Membership.company_id == company_id,
                    Membership.client_id == client_id,
                )
            ).all()
            for ms in memberships:
                u = session.get(User, ms.user_id)
                if not u or ms.user_id in user_ids_in_graph:
                    continue
                user_ids_in_graph.add(ms.user_id)
                add_node(f"user_{ms.user_id}", (u.name or u.email or f"#{ms.user_id}")[:18],
                         "user", title=f"{u.name or ''}\n{u.email or ''}", url="#")
        else:
            # Usuário só vê a si mesmo
            user_ids_in_graph.add(user_id)
            u = ctx.user
            add_node(f"user_{user_id}", (u.name or u.email or f"#{user_id}")[:18],
                     "user", title=f"{u.name or ''}", url="#")
    except Exception:
        pass

    # Reuniões
    meeting_ids_in_graph = set()
    try:
        all_meetings = session.exec(
            _sel_cg(Meeting).where(
                Meeting.company_id == company_id,
                Meeting.client_id == client_id,
            )
        ).all()

        if not is_gestor:
            # Usuário vê reuniões que criou OU nas quais participou
            try:
                participou_ids = {
                    p.meeting_id for p in session.exec(
                        _sel_cg(MeetingParticipante).where(
                            MeetingParticipante.user_id == user_id,
                        )
                    ).all()
                }
            except Exception:
                participou_ids = set()
            all_meetings = [
                mt for mt in all_meetings
                if mt.created_by_user_id == user_id or mt.id in participou_ids
            ]

        for mt in all_meetings:
            meeting_ids_in_graph.add(mt.id)
            add_node(f"meet_{mt.id}", (mt.title or "Reunião")[:20], "meeting",
                     title=f"Reunião: {mt.title}\nData: {mt.meeting_date or '—'}",
                     url=f"/reunioes/{mt.id}")
            add_edge(f"client_{client_id}", f"meet_{mt.id}")
            if mt.created_by_user_id in user_ids_in_graph:
                add_edge(f"user_{mt.created_by_user_id}", f"meet_{mt.id}", "criou")
    except Exception:
        pass

    # Ações corretivas
    try:
        q = _sel_cg(MeetingAcao).where(
            MeetingAcao.company_id == company_id,
            MeetingAcao.client_id == client_id,
        )
        if not is_gestor:
            # Usuário vê ações onde é responsável OU das reuniões que criou
            from sqlmodel import or_ as _or_cg
            q = q.where(
                _or_cg(
                    MeetingAcao.responsavel_user_id == user_id,
                    MeetingAcao.created_by_user_id == user_id,
                )
            )
        for a in session.exec(q).all():
            grp = "acao_alta" if a.prioridade == "alta" else "acao"
            prazo = f"\nPrazo: {a.prazo}" if a.prazo else ""
            resp = f"\nResp: {a.responsavel}" if a.responsavel else ""
            add_node(f"acao_{a.id}", (a.titulo or "Ação")[:20], grp,
                     title=f"[{(a.prioridade or '').upper()}] {a.titulo}\n{a.status}{prazo}{resp}",
                     url=f"/reunioes/{a.meeting_id}/acoes", size=14)
            # Edge da reunião mãe (se estiver no grafo)
            if a.meeting_id in meeting_ids_in_graph:
                add_edge(f"meet_{a.meeting_id}", f"acao_{a.id}", a.status)
            else:
                # Reunião não está no grafo — conecta direto ao cliente
                add_edge(f"client_{client_id}", f"acao_{a.id}", "ação")
            if a.responsavel_user_id and a.responsavel_user_id in user_ids_in_graph:
                add_edge(f"user_{a.responsavel_user_id}", f"acao_{a.id}", "resp.")
    except Exception:
        pass

    # Orçamento
    try:
        for p in session.exec(
            _sel_cg(BudgetPlan).where(
                BudgetPlan.company_id == company_id,
                BudgetPlan.client_id == client_id,
                BudgetPlan.is_active == True,
            )
        ).all():
            add_node(f"budget_{p.id}", f"Orç.{p.year}", "budget",
                     title=f"Orçamento: {p.name}\nAno: {p.year}",
                     url=f"/ferramentas/orcamento/{p.id}", size=20)
            add_edge(f"client_{client_id}", f"budget_{p.id}", "orçamento")
    except Exception:
        pass

    # BSC — Perspectivas e Indicadores
    try:
        perspectivas = session.exec(
            _sel_cg(BSCPerspectiva).where(
                BSCPerspectiva.company_id == company_id,
                BSCPerspectiva.client_id == client_id,
            )
        ).all()
        for p in perspectivas:
            add_node(f"bscp_{p.id}", (p.nome or "Perspectiva")[:18], "bsc_p",
                     title=f"BSC — {p.nome}", url="/cliente/bsc", size=22)
            add_edge(f"client_{client_id}", f"bscp_{p.id}", "BSC")

            objetivos = session.exec(
                _sel_cg(BSCObjetivo).where(BSCObjetivo.perspectiva_id == p.id)
            ).all()
            for obj in objetivos:
                indicadores = session.exec(
                    _sel_cg(BSCIndicador).where(BSCIndicador.objetivo_id == obj.id)
                ).all()
                for ind in indicadores:
                    add_node(f"bsci_{ind.id}", (ind.nome or "KPI")[:18], "bsc_i",
                             title=f"KPI: {ind.nome}\nMeta: {ind.meta_valor} {ind.unidade}",
                             url="/cliente/bsc", size=13)
                    add_edge(f"bscp_{p.id}", f"bsci_{ind.id}")
    except Exception:
        pass

    return _JR_cg({"nodes": nodes, "edges": edges, "is_gestor": is_gestor})


# ── Página /cliente/grafo ─────────────────────────────────────────────────────

@app.get("/cliente/grafo", response_class=_HTML_cg)
@require_login
async def cg_page(request: _Req_cg, session: _Sess_cg = _Dep_cg(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return __import__('fastapi').responses.RedirectResponse("/login", status_code=303)
    if ctx.membership.role != "cliente":
        return __import__('fastapi').responses.RedirectResponse("/admin/grafo", status_code=303)

    client_id = ctx.membership.client_id
    papel = _cg_cliente_role(session, ctx.company.id, client_id, ctx.user.id) if client_id else "usuario"

    cc = get_client_or_none(session, ctx.company.id, client_id)
    return render("cliente_grafo.html", request=request, context={
        "current_user": ctx.user, "current_company": ctx.company,
        "role": ctx.membership.role, "current_client": cc,
        "papel": papel,
    })


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATES["cliente_grafo.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  #grafo-wrap {
    width:100%; height:calc(100vh - 185px); min-height:460px;
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
  {% if papel == "gestor" %}
    <span class="badge bg-warning text-dark">🔑 Gestor — visão completa</span>
  {% else %}
    <span class="badge bg-secondary">👤 Suas conexões pessoais</span>
  {% endif %}
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
    <div><i style="background:#34d399"></i>BSC Perspectiva</div>
    <div><i style="background:#6ee7b7"></i>KPI / Indicador</div>
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
  bsc_p:     {f:"#34d399",s:"#059669",t:"#022c22"},
  bsc_i:     {f:"#6ee7b7",s:"#10b981",t:"#022c22"},
};

const cv = document.getElementById("gc");
const cx = cv.getContext("2d");
const tip = document.getElementById("tip");

let nodes=[], edges=[], nmap={};
let tx=0, ty=0, sc=1;
let drag=null, pan=null, hov=null;
let paused=false, ticks=0;
const MAX_TICKS=600;

function resize(){ cv.width=cv.offsetWidth; cv.height=cv.offsetHeight; }
window.addEventListener("resize", resize);

function w2s(wx,wy){ return {x: wx*sc+tx+cv.width/2, y: wy*sc+ty+cv.height/2}; }
function s2w(sx,sy){ return {x:(sx-cv.width/2-tx)/sc, y:(sy-cv.height/2-ty)/sc}; }
function hit(wx,wy){
  let best=null,bd=Infinity;
  nodes.forEach(n=>{ const r=(n.size||16)+6, d=Math.hypot(wx-n.x,wy-n.y); if(d<r&&d<bd){bd=d;best=n;} });
  return best;
}

function physics(){
  const N=nodes.length; if(!N) return;
  const REP=Math.min(4000,800000/N);
  const SPR_K=0.05,SPR_L=110,DAMP=0.75,GRAV=0.02,MAX_V=8;
  nodes.forEach(n=>{n.fx=0;n.fy=0;});
  for(let i=0;i<N;i++){
    for(let j=i+1;j<N;j++){
      const a=nodes[i],b=nodes[j],dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy+1,f=REP/d2,sq=Math.sqrt(d2);
      a.fx+=dx/sq*f;a.fy+=dy/sq*f;b.fx-=dx/sq*f;b.fy-=dy/sq*f;
    }
  }
  edges.forEach(e=>{
    const a=nmap[e.from],b=nmap[e.to]; if(!a||!b) return;
    const dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-SPR_L)*SPR_K,fx=dx/d*f,fy=dy/d*f;
    a.fx+=fx;a.fy+=fy;b.fx-=fx;b.fy-=fy;
  });
  nodes.forEach(n=>{
    if(n===drag) return;
    n.fx-=n.x*GRAV;n.fy-=n.y*GRAV;
    n.vx=(n.vx+n.fx)*DAMP;n.vy=(n.vy+n.fy)*DAMP;
    const spd=Math.hypot(n.vx,n.vy); if(spd>MAX_V){n.vx=n.vx/spd*MAX_V;n.vy=n.vy/spd*MAX_V;}
    n.x+=n.vx;n.y+=n.vy;
  });
  ticks++;
  if(ticks>MAX_TICKS){paused=true;document.getElementById("btn-pause").textContent="▶ Retomar";}
}

function draw(){
  resize();cx.clearRect(0,0,cv.width,cv.height);cx.save();
  cx.translate(tx+cv.width/2,ty+cv.height/2);cx.scale(sc,sc);
  cx.lineWidth=0.8/sc;
  edges.forEach(e=>{
    const a=nmap[e.from],b=nmap[e.to]; if(!a||!b) return;
    cx.beginPath();cx.strokeStyle="rgba(120,130,160,0.28)";cx.moveTo(a.x,a.y);cx.lineTo(b.x,b.y);cx.stroke();
    if(e.label&&sc>0.5){
      cx.font=`${Math.max(7,9/sc)}px system-ui`; cx.fillStyle="rgba(180,180,200,.6)";
      cx.textAlign="center"; cx.textBaseline="middle";
      cx.fillText(e.label,(a.x+b.x)/2,(a.y+b.y)/2);
    }
  });
  nodes.forEach(n=>{
    const p=PALETTE[n.group]||PALETTE.user,r=(n.size||16)*(n===hov?1.3:1);
    if(n===hov){cx.beginPath();cx.arc(n.x,n.y,r+7,0,Math.PI*2);cx.fillStyle=p.f+"33";cx.fill();}
    cx.beginPath();cx.arc(n.x,n.y,r,0,Math.PI*2);cx.fillStyle=p.f;cx.fill();
    cx.strokeStyle=p.s;cx.lineWidth=1.2/sc;cx.stroke();
    if(sc>0.3){
      cx.font=`${Math.max(8,10)}px system-ui`;cx.fillStyle="#ddd";
      cx.textAlign="center";cx.textBaseline="top";cx.fillText(n.label,n.x,n.y+r+3);
    }
  });
  cx.restore();
}

function loop(){ if(!paused) physics(); draw(); requestAnimationFrame(loop); }

function fitAll(){
  if(!nodes.length) return;
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  nodes.forEach(n=>{minX=Math.min(minX,n.x);maxX=Math.max(maxX,n.x);minY=Math.min(minY,n.y);maxY=Math.max(maxY,n.y);});
  const pw=cv.width-80,ph=cv.height-80,gw=maxX-minX||1,gh=maxY-minY||1;
  sc=Math.min(pw/gw,ph/gh,2);tx=-((minX+maxX)/2)*sc;ty=-((minY+maxY)/2)*sc;
}

function load(){
  fetch("/api/grafo/cliente").then(r=>r.json()).then(data=>{
    nodes=data.nodes.map((n,i)=>{
      const angle=i*2.399,rad=Math.sqrt(i)*28;
      return {...n,x:Math.cos(angle)*rad,y:Math.sin(angle)*rad,vx:0,vy:0,fx:0,fy:0};
    });
    edges=data.edges;nmap={};nodes.forEach(n=>nmap[n.id]=n);
    ticks=0;paused=false;document.getElementById("btn-pause").textContent="⏸ Pausar";
    document.getElementById("grafo-stats").textContent=`${nodes.length} nós · ${edges.length} conexões`;
    setTimeout(fitAll,2000);
  });
}

let dragStart=null;
cv.addEventListener("mousedown",e=>{
  const r=cv.getBoundingClientRect(),sx=e.clientX-r.left,sy=e.clientY-r.top,w=s2w(sx,sy),h=hit(w.x,w.y);
  if(h){drag=h;dragStart={sx,sy};}else{pan={mx:e.clientX,my:e.clientY,tx,ty};}
});
cv.addEventListener("mousemove",e=>{
  const r=cv.getBoundingClientRect(),sx=e.clientX-r.left,sy=e.clientY-r.top,w=s2w(sx,sy);
  if(drag){drag.x=w.x;drag.y=w.y;drag.vx=0;drag.vy=0;}
  else if(pan){tx=pan.tx+(e.clientX-pan.mx);ty=pan.ty+(e.clientY-pan.my);}
  hov=hit(w.x,w.y);
  if(hov){tip.style.display="block";tip.style.left=(e.clientX+16)+"px";tip.style.top=(e.clientY-10)+"px";tip.textContent=hov.title||hov.label;}
  else{tip.style.display="none";}
});
cv.addEventListener("mouseup",e=>{
  if(drag&&dragStart){
    const r=cv.getBoundingClientRect(),sx=e.clientX-r.left,sy=e.clientY-r.top;
    if(Math.hypot(sx-dragStart.sx,sy-dragStart.sy)<6&&drag.url&&drag.url!=="#") window.location.href=drag.url;
  }
  drag=null;dragStart=null;pan=null;
});
cv.addEventListener("mouseleave",()=>{drag=null;dragStart=null;pan=null;tip.style.display="none";});
cv.addEventListener("wheel",e=>{
  e.preventDefault();
  const r=cv.getBoundingClientRect(),sx=e.clientX-r.left-cv.width/2-tx,sy=e.clientY-r.top-cv.height/2-ty,f=e.deltaY<0?1.1:0.91;
  sc=Math.max(0.08,Math.min(6,sc*f));tx-=sx*(f-1);ty-=sy*(f-1);
},{passive:false});

// Touch
let lastPinch=null,touchDragStart=null;
function resetTouch(){drag=null;dragStart=null;touchDragStart=null;pan=null;lastPinch=null;}
cv.addEventListener("touchstart",e=>{
  if(e.touches.length>1){drag=null;dragStart=null;touchDragStart=null;pan=null;return;}
  const t=e.touches[0],r=cv.getBoundingClientRect(),sx=t.clientX-r.left,sy=t.clientY-r.top,w=s2w(sx,sy),h=hit(w.x,w.y);
  if(h){drag=h;dragStart={sx,sy};touchDragStart={sx,sy};}else{pan={mx:t.clientX,my:t.clientY,tx,ty};}
},{passive:true});
cv.addEventListener("touchmove",e=>{
  e.preventDefault();
  if(e.touches.length===2){
    drag=null;dragStart=null;touchDragStart=null;pan=null;
    const d=Math.hypot(e.touches[0].clientX-e.touches[1].clientX,e.touches[0].clientY-e.touches[1].clientY);
    if(lastPinch) sc=Math.max(0.08,Math.min(6,sc*(d/lastPinch)));lastPinch=d;
  } else if(e.touches.length===1){
    const t=e.touches[0],r=cv.getBoundingClientRect(),sx=t.clientX-r.left,sy=t.clientY-r.top,w=s2w(sx,sy);
    if(drag){drag.x=w.x;drag.y=w.y;drag.vx=0;drag.vy=0;}else if(pan){tx=pan.tx+(t.clientX-pan.mx);ty=pan.ty+(t.clientY-pan.my);}
  }
},{passive:false});
cv.addEventListener("touchend",e=>{
  if(drag&&touchDragStart&&e.changedTouches.length){
    const t=e.changedTouches[0],r=cv.getBoundingClientRect(),sx=t.clientX-r.left,sy=t.clientY-r.top;
    if(Math.hypot(sx-touchDragStart.sx,sy-touchDragStart.sy)<10&&drag.url&&drag.url!=="#") window.location.href=drag.url;
  }
  resetTouch();
},{passive:true});
cv.addEventListener("touchcancel",resetTouch,{passive:true});

document.getElementById("btn-pause").addEventListener("click",()=>{
  paused=!paused;ticks=paused?MAX_TICKS+1:0;
  document.getElementById("btn-pause").textContent=paused?"▶ Retomar":"⏸ Pausar";
});

resize();load();loop();
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["cliente_grafo.html"] = TEMPLATES["cliente_grafo.html"]
    print("[cg] ✅ cliente_grafo.html propagado ao loader.")


# ── Sidebar: adicionar "2º Cérebro" para role=cliente ─────────────────────────

try:
    _base_cg = TEMPLATES.get("base.html", "")
    # Injeta link após o link de Ações na seção Gestão do cliente
    _ACOES_LINK = '<a class="sb-link" href="/admin/acoes" data-sbpath="/admin/acoes" title="Ações">\n      <span class="sb-icon">⚡</span><span class="sb-label">Ações</span>\n    </a>'
    _CEREBRO_LINK = '<a class="sb-link" href="/cliente/grafo" data-sbpath="/cliente/grafo" title="2º Cérebro">\n      <span class="sb-icon">🧠</span><span class="sb-label">2º Cérebro</span>\n    </a>'
    if _ACOES_LINK in _base_cg and _CEREBRO_LINK not in _base_cg:
        _base_cg = _base_cg.replace(
            _ACOES_LINK,
            _ACOES_LINK + "\n    " + _CEREBRO_LINK,
            1,  # só a primeira ocorrência (bloco do cliente)
        )
        TEMPLATES["base.html"] = _base_cg
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["base.html"] = _base_cg
        print("[cg] ✅ Link '2º Cérebro' adicionado à sidebar do cliente.")
    elif _CEREBRO_LINK in _base_cg:
        print("[cg] ℹ️ Link já presente na sidebar.")
    else:
        print("[cg] ⚠️ Marcador de Ações não encontrado na sidebar — link não injetado.")
except Exception as _e_cg_sb:
    print(f"[cg] ⚠️ Sidebar patch: {_e_cg_sb}")

print("[cg] ✅ Módulo 2º Cérebro do cliente carregado.")
