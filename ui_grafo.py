# ui_grafo.py — Segundo Cérebro: grafo de conhecimento operacional
# Exec'd no namespace do app.py
#
# Rota:  GET /admin/grafo          — visualização interativa (vis.js)
# Rota:  GET /api/grafo/data       — JSON com nodes + edges para o frontend
#
# Nós:
#   client    🟢  verde-água
#   meeting   🔵  azul
#   acao      🟠  laranja / vermelho (alta prioridade)
#   budget    🟣  roxo
#   user      🟡  amarelo
#   desvio    🔴  vermelho
#
# Filtros: ?client_id=X  restringe ao universo de um cliente

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
        nodes.append({
            "id": id_, "label": label, "group": group,
            "title": title, "url": url, "size": size,
        })

    def add_edge(src, dst, label=""):
        key = f"{src}|{dst}"
        if key not in seen_edges:
            seen_edges.add(key)
            edges.append({"from": src, "to": dst, "label": label})

    # ── Clientes ─────────────────────────────────────────────────────────────
    try:
        clientes = session.exec(
            select(Client).where(Client.company_id == cid)
        ).all()
        if filter_client_id:
            clientes = [c for c in clientes if c.id == filter_client_id]

        client_ids = {c.id for c in clientes}
        for c in clientes:
            add_node(
                f"client_{c.id}",
                c.name or f"Cliente #{c.id}",
                "client",
                title=f"Cliente: {c.name}",
                url=f"/client/switch?client_id={c.id}",
                size=28,
            )
    except Exception:
        clientes = []
        client_ids = set()

    # ── Usuários / membros ────────────────────────────────────────────────────
    user_ids_seen = set()
    try:
        membros = session.exec(
            select(Membership).where(Membership.company_id == cid)
        ).all()
        for m in membros:
            u = session.get(User, m.user_id)
            if not u or m.user_id in user_ids_seen:
                continue
            user_ids_seen.add(m.user_id)
            add_node(
                f"user_{m.user_id}",
                (u.name or u.email or f"User #{m.user_id}")[:20],
                "user",
                title=f"{u.name or ''} ({m.role})\n{u.email or ''}",
                url=f"/admin/members",
            )
    except Exception:
        pass

    # ── Reuniões ──────────────────────────────────────────────────────────────
    try:
        q_meet = select(Meeting).where(Meeting.company_id == cid)
        if filter_client_id:
            q_meet = q_meet.where(Meeting.client_id == filter_client_id)
        meetings = session.exec(q_meet).all()

        for mt in meetings:
            if mt.client_id not in client_ids and not filter_client_id:
                continue
            label = (mt.title or "Reunião")[:22]
            add_node(
                f"meet_{mt.id}", label, "meeting",
                title=f"Reunião: {mt.title}\nData: {mt.meeting_date or '—'}",
                url=f"/reunioes/{mt.id}",
            )
            add_edge(f"client_{mt.client_id}", f"meet_{mt.id}", "reunião")
            if mt.created_by_user_id in user_ids_seen:
                add_edge(f"user_{mt.created_by_user_id}", f"meet_{mt.id}", "criou")
    except Exception:
        meetings = []

    # ── Ações corretivas (MeetingAcao) ────────────────────────────────────────
    try:
        q_ac = select(MeetingAcao).where(MeetingAcao.company_id == cid)
        if filter_client_id:
            q_ac = q_ac.where(MeetingAcao.client_id == filter_client_id)
        acoes = session.exec(q_ac).all()

        for a in acoes:
            grp = "acao_alta" if a.prioridade == "alta" else "acao"
            short = (a.titulo or "Ação")[:22]
            prazo_txt = f"\nPrazo: {a.prazo}" if a.prazo else ""
            resp_txt = f"\nResp: {a.responsavel}" if a.responsavel else ""
            add_node(
                f"acao_{a.id}", short, grp,
                title=f"[{a.prioridade.upper()}] {a.titulo}\nStatus: {a.status}{prazo_txt}{resp_txt}",
                url=f"/reunioes/{a.meeting_id}/acoes",
            )
            add_edge(f"meet_{a.meeting_id}", f"acao_{a.id}", a.status)
            if a.responsavel_user_id and a.responsavel_user_id in user_ids_seen:
                add_edge(f"user_{a.responsavel_user_id}", f"acao_{a.id}", "responsável")
            if a.client_id in client_ids:
                add_edge(f"client_{a.client_id}", f"acao_{a.id}", "ação")
    except Exception:
        pass

    # ── Planos orçamentários ──────────────────────────────────────────────────
    try:
        q_bp = select(BudgetPlan).where(BudgetPlan.company_id == cid, BudgetPlan.is_active == True)
        if filter_client_id:
            q_bp = q_bp.where(BudgetPlan.client_id == filter_client_id)
        plans = session.exec(q_bp).all()

        for p in plans:
            if p.client_id and p.client_id not in client_ids:
                continue
            add_node(
                f"budget_{p.id}",
                f"Orç. {p.year}",
                "budget",
                title=f"Orçamento: {p.name}\nAno: {p.year}",
                url=f"/ferramentas/orcamento/{p.id}",
                size=22,
            )
            if p.client_id:
                add_edge(f"client_{p.client_id}", f"budget_{p.id}", "orçamento")
    except Exception:
        pass

    # ── Desvios orçamentários (BudgetAlert = contas com alerta configurado) ──
    try:
        from sqlmodel import col as _col_grafo
        alerts = session.exec(
            select(BudgetAlert).where(BudgetAlert.company_id == cid)
        ).all()
        for al in alerts:
            acc = session.get(BudgetAccount, al.account_id)
            if not acc:
                continue
            # Só inclui se conta pertence a um cliente filtrado (ou sem filtro)
            if filter_client_id and acc.client_id != filter_client_id:
                continue
            node_id = f"desvio_{al.id}"
            add_node(
                node_id,
                f"⚠ {acc.name[:18]}",
                "desvio",
                title=f"Alerta: {acc.name}\nTol: {al.tolerance_pct}% | Crit: {al.critical_pct}%",
                url=f"/ferramentas/orcamento/{acc.client_id or 0}/dashboard" if acc.client_id else "#",
            )
            # Conecta ao plano do cliente
            if acc.client_id:
                plan_client = session.exec(
                    select(BudgetPlan).where(
                        BudgetPlan.company_id == cid,
                        BudgetPlan.client_id == acc.client_id,
                        BudgetPlan.is_active == True,
                    )
                ).first()
                if plan_client:
                    add_edge(f"budget_{plan_client.id}", node_id, "desvio")
    except Exception:
        pass

    return _JR_grafo({"nodes": nodes, "edges": edges})


# ── Página do grafo ───────────────────────────────────────────────────────────

@app.get("/admin/grafo", response_class=HTMLResponse)
@require_login
async def admin_grafo_page(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/", status_code=303)

    clientes = []
    try:
        clientes = session.exec(
            select(Client).where(Client.company_id == ctx.company.id)
        ).all()
    except Exception:
        pass

    cc = get_client_or_none(session, ctx.company.id, get_active_client_id(request, session, ctx))
    return render("admin_grafo.html", request=request, context={
        "current_user": ctx.user,
        "current_company": ctx.company,
        "role": ctx.membership.role,
        "current_client": cc,
        "clientes": clientes,
    })


# ── Template ──────────────────────────────────────────────────────────────────

TEMPLATES["admin_grafo.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  #grafo-container {
    width: 100%;
    height: calc(100vh - 200px);
    min-height: 500px;
    background: #0d1117;
    border-radius: 12px;
    position: relative;
    overflow: hidden;
  }
  #grafo-canvas { width: 100%; height: 100%; }
  #grafo-legend {
    position: absolute; top: 12px; left: 12px;
    background: rgba(0,0,0,.7); border-radius: 8px;
    padding: 10px 14px; color: #eee; font-size: .75rem;
    backdrop-filter: blur(4px);
  }
  #grafo-legend span { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; }
  #grafo-tooltip {
    position: fixed; pointer-events: none;
    background: rgba(0,0,0,.85); color: #fff;
    border-radius: 8px; padding: 8px 12px;
    font-size: .78rem; max-width: 240px;
    line-height: 1.5; z-index: 9999;
    display: none; white-space: pre-wrap;
    box-shadow: 0 4px 20px rgba(0,0,0,.4);
  }
  .grafo-controls {
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
  }
  #grafo-stats { color: var(--mc-muted); font-size:.8rem; }
</style>

<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
  <div>
    <h4 class="mb-0">🧠 Segundo Cérebro</h4>
    <div class="muted small">Grafo de conhecimento operacional — todos os nós e conexões da empresa</div>
  </div>
  <div class="grafo-controls">
    <select id="filtro-cliente" class="form-select form-select-sm" style="max-width:220px;">
      <option value="">Todos os clientes</option>
      {% for c in clientes %}
        <option value="{{ c.id }}">{{ c.name }}</option>
      {% endfor %}
    </select>
    <button class="btn btn-sm btn-outline-secondary" onclick="grafoFitAll()">⊡ Centralizar</button>
    <span id="grafo-stats">—</span>
  </div>
</div>

<div id="grafo-container">
  <canvas id="grafo-canvas"></canvas>
  <div id="grafo-legend">
    <div class="mb-1 fw-semibold" style="font-size:.8rem;">Legenda</div>
    <div><span style="background:#4ade80"></span> Cliente</div>
    <div><span style="background:#60a5fa"></span> Reunião</div>
    <div><span style="background:#fb923c"></span> Ação</div>
    <div><span style="background:#f87171"></span> Ação alta prioridade</div>
    <div><span style="background:#a78bfa"></span> Orçamento</div>
    <div><span style="background:#fbbf24"></span> Pessoa</div>
    <div><span style="background:#f43f5e"></span> Desvio</div>
  </div>
</div>
<div id="grafo-tooltip"></div>

<script>
// ── Configuração de cores ──────────────────────────────────────────────────
const COLORS = {
  client:    { fill: "#4ade80", stroke: "#16a34a", text: "#052e16" },
  meeting:   { fill: "#60a5fa", stroke: "#2563eb", text: "#1e3a5f" },
  acao:      { fill: "#fb923c", stroke: "#ea580c", text: "#431407" },
  acao_alta: { fill: "#f87171", stroke: "#dc2626", text: "#450a0a" },
  budget:    { fill: "#a78bfa", stroke: "#7c3aed", text: "#2e1065" },
  user:      { fill: "#fbbf24", stroke: "#d97706", text: "#451a03" },
  desvio:    { fill: "#f43f5e", stroke: "#be123c", text: "#fff" },
};

// ── Estado ────────────────────────────────────────────────────────────────
let nodes = [], edges = [];
let transform = { x: 0, y: 0, scale: 1 };
let dragging = null, dragStart = null, panStart = null;
let hoveredNode = null;
const canvas = document.getElementById("grafo-canvas");
const ctx2d = canvas.getContext("2d");
const tooltip = document.getElementById("grafo-tooltip");

// ── Física (force-directed) ───────────────────────────────────────────────
const SPRING_LEN = 120, SPRING_K = 0.04;
const REPULSION = 3500, DAMPING = 0.82, GRAVITY = 0.015;

function applyForces() {
  // Repulsão
  for (let i = 0; i < nodes.length; i++) {
    nodes[i].fx = 0; nodes[i].fy = 0;
    for (let j = 0; j < nodes.length; j++) {
      if (i === j) continue;
      const dx = nodes[i].x - nodes[j].x;
      const dy = nodes[i].y - nodes[j].y;
      const dist = Math.sqrt(dx*dx + dy*dy) || 1;
      const force = REPULSION / (dist * dist);
      nodes[i].fx += (dx / dist) * force;
      nodes[i].fy += (dy / dist) * force;
    }
  }
  // Molas (arestas)
  edges.forEach(e => {
    const a = nodeMap[e.from], b = nodeMap[e.to];
    if (!a || !b) return;
    const dx = b.x - a.x, dy = b.y - a.y;
    const dist = Math.sqrt(dx*dx + dy*dy) || 1;
    const force = (dist - SPRING_LEN) * SPRING_K;
    const fx = (dx / dist) * force, fy = (dy / dist) * force;
    a.fx += fx; a.fy += fy;
    b.fx -= fx; b.fy -= fy;
  });
  // Gravidade ao centro
  nodes.forEach(n => {
    n.fx -= n.x * GRAVITY;
    n.fy -= n.y * GRAVITY;
  });
  // Integração
  nodes.forEach(n => {
    if (n === dragging) return;
    n.vx = (n.vx + n.fx) * DAMPING;
    n.vy = (n.vy + n.fy) * DAMPING;
    n.x += n.vx;
    n.y += n.vy;
  });
}

// ── Render ────────────────────────────────────────────────────────────────
let nodeMap = {};

function resize() {
  canvas.width = canvas.offsetWidth;
  canvas.height = canvas.offsetHeight;
}

function draw() {
  resize();
  ctx2d.clearRect(0, 0, canvas.width, canvas.height);
  ctx2d.save();
  ctx2d.translate(transform.x + canvas.width/2, transform.y + canvas.height/2);
  ctx2d.scale(transform.scale, transform.scale);

  // Arestas
  ctx2d.lineWidth = 1;
  edges.forEach(e => {
    const a = nodeMap[e.from], b = nodeMap[e.to];
    if (!a || !b) return;
    ctx2d.beginPath();
    ctx2d.strokeStyle = "rgba(150,150,170,0.35)";
    ctx2d.moveTo(a.x, a.y);
    ctx2d.lineTo(b.x, b.y);
    ctx2d.stroke();
    // Label da aresta
    if (e.label && transform.scale > 0.6) {
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      ctx2d.fillStyle = "rgba(180,180,200,0.7)";
      ctx2d.font = "9px sans-serif";
      ctx2d.textAlign = "center";
      ctx2d.fillText(e.label, mx, my);
    }
  });

  // Nós
  nodes.forEach(n => {
    const c = COLORS[n.group] || COLORS.user;
    const r = (n.size || 18) * (n === hoveredNode ? 1.25 : 1);
    // Halo no hover
    if (n === hoveredNode) {
      ctx2d.beginPath();
      ctx2d.arc(n.x, n.y, r + 6, 0, Math.PI*2);
      ctx2d.fillStyle = c.fill + "44";
      ctx2d.fill();
    }
    // Círculo
    ctx2d.beginPath();
    ctx2d.arc(n.x, n.y, r, 0, Math.PI*2);
    ctx2d.fillStyle = c.fill;
    ctx2d.fill();
    ctx2d.strokeStyle = c.stroke;
    ctx2d.lineWidth = 1.5;
    ctx2d.stroke();
    // Label
    if (transform.scale > 0.4) {
      ctx2d.fillStyle = c.text;
      ctx2d.font = `bold ${Math.max(9, 11 * transform.scale)}px sans-serif`;
      ctx2d.textAlign = "center";
      ctx2d.textBaseline = "middle";
      ctx2d.fillText(n.label, n.x, n.y + r + 11);
    }
  });

  ctx2d.restore();
}

// ── Loop de animação ──────────────────────────────────────────────────────
let running = true;
function loop() {
  if (!running) return;
  applyForces();
  draw();
  requestAnimationFrame(loop);
}

// ── Coordenadas ───────────────────────────────────────────────────────────
function canvasToWorld(cx, cy) {
  return {
    x: (cx - canvas.width/2 - transform.x) / transform.scale,
    y: (cy - canvas.height/2 - transform.y) / transform.scale,
  };
}

function hitTest(wx, wy) {
  let best = null, bestD = Infinity;
  nodes.forEach(n => {
    const r = n.size || 18;
    const d = Math.hypot(wx - n.x, wy - n.y);
    if (d < r + 4 && d < bestD) { bestD = d; best = n; }
  });
  return best;
}

// ── Eventos mouse ─────────────────────────────────────────────────────────
canvas.addEventListener("mousedown", e => {
  const rect = canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
  const w = canvasToWorld(cx, cy);
  const hit = hitTest(w.x, w.y);
  if (hit) {
    dragging = hit;
    dragStart = { mx: cx, my: cy, nx: hit.x, ny: hit.y };
  } else {
    panStart = { mx: cx, my: cy, tx: transform.x, ty: transform.y };
  }
});

canvas.addEventListener("mousemove", e => {
  const rect = canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
  if (dragging && dragStart) {
    const w = canvasToWorld(cx, cy);
    dragging.x = w.x; dragging.y = w.y;
    dragging.vx = 0; dragging.vy = 0;
  } else if (panStart) {
    transform.x = panStart.tx + (cx - panStart.mx);
    transform.y = panStart.ty + (cy - panStart.my);
  }
  // Hover
  const w2 = canvasToWorld(cx, cy);
  const hit = hitTest(w2.x, w2.y);
  hoveredNode = hit;
  if (hit) {
    canvas.style.cursor = "pointer";
    tooltip.style.display = "block";
    tooltip.style.left = (e.clientX + 14) + "px";
    tooltip.style.top  = (e.clientY - 10) + "px";
    tooltip.textContent = hit.title || hit.label;
  } else {
    canvas.style.cursor = panStart ? "grabbing" : "grab";
    tooltip.style.display = "none";
  }
});

canvas.addEventListener("mouseup", e => {
  if (dragging && dragStart) {
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const dx = Math.abs(cx - dragStart.mx), dy = Math.abs(cy - dragStart.my);
    if (dx < 5 && dy < 5 && dragging.url && dragging.url !== "#") {
      window.location.href = dragging.url;
    }
  }
  dragging = null; dragStart = null; panStart = null;
  canvas.style.cursor = "grab";
});

canvas.addEventListener("wheel", e => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.12 : 0.88;
  const rect = canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left - canvas.width/2 - transform.x;
  const cy = e.clientY - rect.top  - canvas.height/2 - transform.y;
  transform.x -= cx * (factor - 1);
  transform.y -= cy * (factor - 1);
  transform.scale = Math.max(0.1, Math.min(5, transform.scale * factor));
}, { passive: false });

// ── Touch ─────────────────────────────────────────────────────────────────
let lastPinchDist = null;
canvas.addEventListener("touchstart", e => {
  if (e.touches.length === 1) {
    const t = e.touches[0];
    const rect = canvas.getBoundingClientRect();
    const cx = t.clientX - rect.left, cy = t.clientY - rect.top;
    const w = canvasToWorld(cx, cy);
    const hit = hitTest(w.x, w.y);
    if (hit) { dragging = hit; dragStart = { mx: cx, my: cy }; }
    else panStart = { mx: cx, my: cy, tx: transform.x, ty: transform.y };
  }
}, { passive: true });
canvas.addEventListener("touchmove", e => {
  if (e.touches.length === 2) {
    const d = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    if (lastPinchDist) transform.scale = Math.max(0.1, Math.min(5, transform.scale * (d / lastPinchDist)));
    lastPinchDist = d;
  } else if (e.touches.length === 1) {
    const t = e.touches[0];
    const rect = canvas.getBoundingClientRect();
    const cx = t.clientX - rect.left, cy = t.clientY - rect.top;
    if (dragging && dragStart) {
      const w = canvasToWorld(cx, cy);
      dragging.x = w.x; dragging.y = w.y; dragging.vx = 0; dragging.vy = 0;
    } else if (panStart) {
      transform.x = panStart.tx + (cx - panStart.mx);
      transform.y = panStart.ty + (cy - panStart.my);
    }
  }
  e.preventDefault();
}, { passive: false });
canvas.addEventListener("touchend", () => {
  dragging = null; dragStart = null; panStart = null; lastPinchDist = null;
});

// ── Centralizar ───────────────────────────────────────────────────────────
function grafoFitAll() {
  if (!nodes.length) return;
  transform.x = 0; transform.y = 0; transform.scale = 1;
}

// ── Carregar dados ────────────────────────────────────────────────────────
function loadGrafo(clientId) {
  const url = "/api/grafo/data" + (clientId ? `?client_id=${clientId}` : "");
  fetch(url).then(r => r.json()).then(data => {
    nodes = data.nodes.map(n => ({
      ...n,
      x: (Math.random() - 0.5) * 600,
      y: (Math.random() - 0.5) * 600,
      vx: 0, vy: 0, fx: 0, fy: 0,
    }));
    edges = data.edges;
    nodeMap = {};
    nodes.forEach(n => nodeMap[n.id] = n);
    document.getElementById("grafo-stats").textContent =
      `${nodes.length} nós · ${edges.length} conexões`;
    grafoFitAll();
  });
}

document.getElementById("filtro-cliente").addEventListener("change", function() {
  loadGrafo(this.value);
});

canvas.style.cursor = "grab";
loadGrafo("");
loop();
</script>
{% endblock %}
"""

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping["admin_grafo.html"] = TEMPLATES["admin_grafo.html"]

# Garante feature visível no menu para admin/equipe
try:
    ROLE_DEFAULT_FEATURES.setdefault("admin", set()).add("grafo")
    ROLE_DEFAULT_FEATURES.setdefault("equipe", set()).add("grafo")
    FEATURE_VISIBLE_ROLES.setdefault("grafo", {"admin", "equipe"})
except Exception:
    pass

print("[grafo] ✅ Segundo Cérebro — rota /admin/grafo carregada.")
