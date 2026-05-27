# ============================================================================
# Survey system — NPS Consultoria + App MVP feedback
# ============================================================================
# Salve como ui_pesquisas.py e adicione ao final do app.py:
#   exec(open('ui_pesquisas.py').read())
# ============================================================================

import json as _json_pq
from datetime import datetime as _dt_pq
from typing import Optional as _OptPq
from sqlmodel import (
    Field as _FPq,
    SQLModel as _SMPq,
    Session as _SessPq,
    select as _selPq,
)


# ── Model ─────────────────────────────────────────────────────────────────────

class PesquisaResposta(_SMPq, table=True):
    __tablename__ = "pesquisaresposta"
    __table_args__ = {"extend_existing": True}
    id: _OptPq[int] = _FPq(default=None, primary_key=True)
    pesquisa: str = _FPq(default="", index=True)   # "nps" or "app"
    respostas_json: str = _FPq(default="{}")
    nps_score: int = _FPq(default=-1)              # -1 if not applicable
    ip: str = _FPq(default="")
    created_at: str = _FPq(default="")


try:
    _SMPq.metadata.create_all(engine, tables=[PesquisaResposta.__table__])
except Exception:
    pass


# ── CORS preflight ────────────────────────────────────────────────────────────

@app.options("/api/pesquisa/submit")
async def pesquisa_submit_options(request: Request):
    resp = Response(status_code=200)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ── POST /api/pesquisa/submit ─────────────────────────────────────────────────

@app.post("/api/pesquisa/submit")
async def pesquisa_submit(request: Request):
    try:
        body = await request.json()
    except Exception:
        resp = JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    pesquisa_type = str(body.get("pesquisa", ""))
    nps_score = int(body.get("nps", body.get("nps_app", -1)) or -1)
    ip_addr = request.headers.get("X-Forwarded-For", request.client.host if request.client else "")

    row = PesquisaResposta(
        pesquisa=pesquisa_type,
        respostas_json=_json_pq.dumps(body, ensure_ascii=False),
        nps_score=nps_score,
        ip=ip_addr[:128],
        created_at=_dt_pq.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )

    with _SessPq(engine) as _sess:
        _sess.add(row)
        _sess.commit()

    resp = JSONResponse({"ok": True})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# ── GET /admin/pesquisas ──────────────────────────────────────────────────────

@app.get("/admin/pesquisas")
@require_login
async def admin_pesquisas(request: Request):
    # Simple auth: any logged-in user with session
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    tab = request.query_params.get("tab", "nps")  # "nps" or "app"

    with _SessPq(engine) as _sess:
        all_rows = _sess.exec(_selPq(PesquisaResposta).order_by(PesquisaResposta.id.desc())).all()

    nps_rows = [r for r in all_rows if r.pesquisa == "nps"]
    app_rows = [r for r in all_rows if r.pesquisa == "app"]

    def _parse(r):
        try:
            return _json_pq.loads(r.respostas_json)
        except Exception:
            return {}

    # ── NPS stats ──────────────────────────────────────────────────────────────
    nps_scores = [r.nps_score for r in nps_rows if r.nps_score >= 0]
    n_total = len(nps_scores)
    n_promoters = sum(1 for s in nps_scores if s >= 9)
    n_passivos  = sum(1 for s in nps_scores if 7 <= s <= 8)
    n_detratores = sum(1 for s in nps_scores if s <= 6)
    nps_index = round(((n_promoters - n_detratores) / n_total * 100)) if n_total else 0

    # ── App stats ──────────────────────────────────────────────────────────────
    app_scores = [r.nps_score for r in app_rows if r.nps_score >= 0]
    na_total = len(app_scores)
    na_promoters  = sum(1 for s in app_scores if s >= 9)
    na_passivos   = sum(1 for s in app_scores if 7 <= s <= 8)
    na_detratores = sum(1 for s in app_scores if s <= 6)
    nps_app_index = round(((na_promoters - na_detratores) / na_total * 100)) if na_total else 0

    # Feature usage from app survey q1
    _feature_count: dict = {}
    _payment_count: dict = {}
    for r in app_rows:
        d = _parse(r)
        for feat in (d.get("q1") or []):
            _feature_count[feat] = _feature_count.get(feat, 0) + 1
        pay = d.get("q8", "")
        if pay:
            _payment_count[pay] = _payment_count.get(pay, 0) + 1

    max_feat = max(_feature_count.values(), default=1)

    _pay_labels = {
        "sim_100": "Pagaria até R$100/mês",
        "sim_299": "Pagaria até R$299/mês",
        "talvez":  "Talvez — depende",
        "nao":     "Não pagaria",
    }

    # ── Build NPS rows HTML ────────────────────────────────────────────────────
    def _nps_score_badge(score):
        if score >= 9:
            color = "#16a34a"
        elif score >= 7:
            color = "#ca8a04"
        elif score >= 0:
            color = "#dc2626"
        else:
            return '<span style="color:#666">—</span>'
        return f'<span style="background:{color}20;color:{color};padding:2px 10px;border-radius:99px;font-weight:600;font-size:.8rem;">{score}</span>'

    def _rows_table(rows, type_tag):
        if not rows:
            return '<p style="color:#888;font-size:.88rem;padding:16px 0;">Nenhuma resposta ainda.</p>'
        html_parts = ['<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:.85rem;">',
                      '<thead><tr style="border-bottom:1px solid #222;">',
                      '<th style="padding:10px 12px;text-align:left;color:#888;font-weight:500;">Data</th>',
                      '<th style="padding:10px 12px;text-align:left;color:#888;font-weight:500;">NPS</th>',
                      '<th style="padding:10px 12px;text-align:left;color:#888;font-weight:500;">Prévia</th>',
                      '<th style="padding:10px 12px;text-align:left;color:#888;font-weight:500;"></th>',
                      '</tr></thead><tbody>']

        for r in rows:
            d = _parse(r)
            preview_key = "q2" if type_tag == "nps" else "q2"
            preview = str(d.get(preview_key, "")).strip()[:90]
            if len(str(d.get(preview_key, ""))) > 90:
                preview += "…"
            if not preview:
                preview = '<span style="color:#555;font-style:italic;">sem texto</span>'

            modal_id = f"modal_{r.id}"
            html_parts.append(f'''
            <tr style="border-bottom:1px solid #1a1a1a;" class="hover-row" data-id="{r.id}">
              <td style="padding:10px 12px;color:#aaa;white-space:nowrap;">{r.created_at[:10] if r.created_at else "—"}</td>
              <td style="padding:10px 12px;">{_nps_score_badge(r.nps_score)}</td>
              <td style="padding:10px 12px;color:#ccc;max-width:340px;">{preview}</td>
              <td style="padding:10px 12px;">
                <button onclick="openModal('{modal_id}')"
                  style="background:transparent;border:1px solid #333;color:#C9963A;padding:4px 12px;border-radius:6px;cursor:pointer;font-size:.78rem;transition:all .2s;"
                  onmouseover="this.style.borderColor='#C9963A'" onmouseout="this.style.borderColor='#333'">
                  Ver completo
                </button>
              </td>
            </tr>
            ''')
        html_parts.append('</tbody></table></div>')
        return "".join(html_parts)

    # ── Build modals HTML ──────────────────────────────────────────────────────
    def _all_modals(rows, type_tag):
        parts = []
        _q_labels_nps = {
            "nps":  "Nota NPS",
            "q2":   "Comentário da nota",
            "q3":   "Resultado mais concreto",
            "q4":   "Maior preocupação financeira",
            "q5":   "Usa o app?",
            "q6":   "Por que não usa?",
        }
        _q_labels_app = {
            "q1":     "Ferramentas usadas",
            "q2":     "O que o app resolve?",
            "q3":     "O que não consegue?",
            "q4":     "O que sentiria falta?",
            "nps_app": "NPS do app",
            "q6":     "O que faria nota maior?",
            "q7":     "Funcionalidade desejada",
            "q8":     "Pagaria pelo app?",
        }
        labels = _q_labels_nps if type_tag == "nps" else _q_labels_app

        for r in rows:
            d = _parse(r)
            modal_id = f"modal_{r.id}"
            rows_html = []
            for key, label in labels.items():
                val = d.get(key, "")
                if val is None or val == "" or val == [] or val == -1:
                    continue
                if isinstance(val, list):
                    val_str = ", ".join(str(v) for v in val)
                else:
                    val_str = str(val)
                val_esc = val_str.replace("<", "&lt;").replace(">", "&gt;")
                rows_html.append(f'''
                <div style="margin-bottom:18px;">
                  <div style="font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:#C9963A;margin-bottom:6px;">{label}</div>
                  <div style="background:#181818;border:1px solid #222;border-radius:8px;padding:12px 14px;color:#F5F0E8;font-size:.88rem;line-height:1.65;">{val_esc}</div>
                </div>
                ''')

            parts.append(f'''
            <div id="{modal_id}" class="pq-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:9999;overflow-y:auto;padding:32px 16px;">
              <div style="max-width:560px;margin:0 auto;background:#111;border:1px solid rgba(201,150,58,.22);border-radius:14px;padding:36px 32px 28px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;">
                  <div>
                    <div style="font-size:.65rem;letter-spacing:.18em;text-transform:uppercase;color:#C9963A;margin-bottom:4px;">Resposta #{r.id}</div>
                    <div style="font-size:.82rem;color:#888;">{r.created_at[:16] if r.created_at else "—"} · IP: {r.ip[:20] if r.ip else "—"}</div>
                  </div>
                  <button onclick="closeModal('{modal_id}')"
                    style="background:transparent;border:1px solid #333;color:#888;width:32px;height:32px;border-radius:8px;cursor:pointer;font-size:1.1rem;display:flex;align-items:center;justify-content:center;transition:all .2s;"
                    onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#888'">×</button>
                </div>
                {"".join(rows_html) if rows_html else '<p style="color:#666;font-size:.85rem;">Sem dados.</p>'}
              </div>
            </div>
            ''')
        return "".join(parts)

    # ── Open-text answers block ────────────────────────────────────────────────
    def _open_text_section(rows, questions: list, type_tag: str):
        parts = []
        for (qkey, qlabel) in questions:
            answers = []
            for r in rows:
                d = _parse(r)
                val = d.get(qkey, "")
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                val = str(val).strip()
                if val and val not in ("-1", ""):
                    answers.append((r.created_at[:10] if r.created_at else "—", val))

            if not answers:
                continue

            items_html = "".join(
                f'<div style="border-left:2px solid rgba(201,150,58,.3);padding:10px 16px;margin-bottom:10px;background:#0f0f0f;border-radius:0 8px 8px 0;">'
                f'<div style="font-size:.7rem;color:#666;margin-bottom:4px;">{dt}</div>'
                f'<div style="color:#ddd;font-size:.88rem;line-height:1.6;">{txt.replace(chr(10), "<br>").replace("<", "&lt;").replace(">", "&gt;").replace("&lt;br&gt;", "<br>")}</div>'
                f'</div>'
                for dt, txt in answers
            )

            parts.append(f'''
            <div style="margin-bottom:32px;">
              <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#C9963A;margin-bottom:14px;">{qlabel}</div>
              <div style="max-height:300px;overflow-y:auto;padding-right:4px;">{items_html}</div>
            </div>
            ''')
        return "".join(parts) if parts else '<p style="color:#666;font-size:.85rem;">Nenhuma resposta aberta ainda.</p>'

    # ── NPS doughnut-style stat cards ─────────────────────────────────────────
    def _stat_card(label, count, total, color):
        pct = round(count / total * 100) if total else 0
        return f'''
        <div style="flex:1;min-width:140px;background:#111;border:1px solid #222;border-radius:12px;padding:20px 18px;text-align:center;">
          <div style="font-size:1.8rem;font-weight:700;color:{color};font-family:'Syne',sans-serif;">{count}</div>
          <div style="font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:#666;margin:4px 0 6px;">{label}</div>
          <div style="font-size:1rem;color:{color};font-weight:500;">{pct}%</div>
        </div>
        '''

    def _feature_bars(fcount, fmax):
        if not fcount:
            return '<p style="color:#666;font-size:.85rem;">Nenhum dado ainda.</p>'
        sorted_feats = sorted(fcount.items(), key=lambda x: -x[1])
        rows_html = []
        for feat, cnt in sorted_feats:
            pct = round(cnt / fmax * 100)
            rows_html.append(f'''
            <div style="margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                <span style="font-size:.84rem;color:#ccc;">{feat}</span>
                <span style="font-size:.78rem;color:#C9963A;font-weight:600;">{cnt}</span>
              </div>
              <div style="height:6px;background:#1a1a1a;border-radius:99px;overflow:hidden;">
                <div style="height:100%;width:{pct}%;background:linear-gradient(90deg,#C9963A,#e8b855);border-radius:99px;transition:width .4s;"></div>
              </div>
            </div>
            ''')
        return "".join(rows_html)

    def _payment_pills(pcount):
        if not pcount:
            return '<p style="color:#666;font-size:.85rem;">Nenhum dado ainda.</p>'
        total_p = sum(pcount.values())
        color_map = {
            "sim_100": "#16a34a",
            "sim_299": "#15803d",
            "talvez":  "#ca8a04",
            "nao":     "#dc2626",
        }
        parts = []
        for key, label in _pay_labels.items():
            cnt = pcount.get(key, 0)
            if cnt == 0:
                continue
            pct = round(cnt / total_p * 100)
            color = color_map.get(key, "#888")
            parts.append(f'''
            <div style="display:flex;align-items:center;gap:12px;padding:10px 14px;background:#111;border:1px solid #1e1e1e;border-radius:10px;margin-bottom:8px;">
              <div style="width:10px;height:10px;border-radius:50%;background:{color};flex-shrink:0;"></div>
              <div style="flex:1;font-size:.86rem;color:#ccc;">{label}</div>
              <div style="font-size:.85rem;color:{color};font-weight:600;">{cnt} <span style="color:#666;font-weight:400;">({pct}%)</span></div>
            </div>
            ''')
        return "".join(parts)

    # ── Build per-tab HTML blocks ──────────────────────────────────────────────
    nps_open_qs = [
        ("q2", "Comentário da nota"),
        ("q3", "Resultado mais concreto"),
        ("q4", "Maior preocupação financeira"),
        ("q6", "Por que não usa o app?"),
    ]

    app_open_qs = [
        ("q2", "O que o app resolve?"),
        ("q3", "O que não consegue?"),
        ("q4", "O que sentiria falta?"),
        ("q6", "O que faria nota maior?"),
        ("q7", "Funcionalidade desejada"),
    ]

    nps_tab_content = f'''
    <!-- NPS Index -->
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;">
      <div style="flex:1;min-width:200px;background:#111;border:1px solid rgba(201,150,58,.25);border-radius:12px;padding:24px;text-align:center;">
        <div style="font-size:3rem;font-weight:800;color:#C9963A;font-family:'Syne',sans-serif;line-height:1;">{nps_index:+d}</div>
        <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#888;margin-top:8px;">NPS Score</div>
        <div style="font-size:.78rem;color:#555;margin-top:4px;">% promotores - % detratores</div>
      </div>
      {_stat_card("Promotores (9-10)", n_promoters, n_total, "#16a34a")}
      {_stat_card("Passivos (7-8)", n_passivos, n_total, "#ca8a04")}
      {_stat_card("Detratores (0-6)", n_detratores, n_total, "#dc2626")}
    </div>

    <!-- Open text answers -->
    <div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:12px;padding:24px 24px 12px;margin-bottom:28px;">
      <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#666;margin-bottom:20px;">Respostas abertas</div>
      {_open_text_section(nps_rows, nps_open_qs, "nps")}
    </div>

    <!-- Responses table -->
    <div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:12px;padding:24px;margin-bottom:16px;">
      <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#666;margin-bottom:18px;">
        Todas as respostas — {len(nps_rows)} total
      </div>
      {_rows_table(nps_rows, "nps")}
    </div>
    {_all_modals(nps_rows, "nps")}
    '''

    app_tab_content = f'''
    <!-- NPS do app -->
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px;">
      <div style="flex:1;min-width:200px;background:#111;border:1px solid rgba(201,150,58,.25);border-radius:12px;padding:24px;text-align:center;">
        <div style="font-size:3rem;font-weight:800;color:#C9963A;font-family:'Syne',sans-serif;line-height:1;">{nps_app_index:+d}</div>
        <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#888;margin-top:8px;">NPS App</div>
        <div style="font-size:.78rem;color:#555;margin-top:4px;">% promotores - % detratores</div>
      </div>
      {_stat_card("Promotores (9-10)", na_promoters, na_total, "#16a34a")}
      {_stat_card("Passivos (7-8)", na_passivos, na_total, "#ca8a04")}
      {_stat_card("Detratores (0-6)", na_detratores, na_total, "#dc2626")}
    </div>

    <!-- Feature usage + payment side by side -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px;">
      <div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:12px;padding:22px;">
        <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#666;margin-bottom:18px;">Ferramentas usadas</div>
        {_feature_bars(_feature_count, max_feat)}
      </div>
      <div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:12px;padding:22px;">
        <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#666;margin-bottom:18px;">Disposição de pagar</div>
        {_payment_pills(_payment_count)}
      </div>
    </div>

    <!-- Open text answers -->
    <div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:12px;padding:24px 24px 12px;margin-bottom:28px;">
      <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#666;margin-bottom:20px;">Respostas abertas</div>
      {_open_text_section(app_rows, app_open_qs, "app")}
    </div>

    <!-- Responses table -->
    <div style="background:#0e0e0e;border:1px solid #1a1a1a;border-radius:12px;padding:24px;margin-bottom:16px;">
      <div style="font-size:.7rem;letter-spacing:.18em;text-transform:uppercase;color:#666;margin-bottom:18px;">
        Todas as respostas — {len(app_rows)} total
      </div>
      {_rows_table(app_rows, "app")}
    </div>
    {_all_modals(app_rows, "app")}
    '''

    tab_nps_active  = 'style="background:#C9963A;color:#0A0A0A;"'  if tab == "nps" else 'style="background:transparent;color:#aaa;border:1px solid #333;"'
    tab_app_active  = 'style="background:#C9963A;color:#0A0A0A;"'  if tab == "app" else 'style="background:transparent;color:#aaa;border:1px solid #333;"'
    tab_body = nps_tab_content if tab == "nps" else app_tab_content

    html_page = f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pesquisas — Admin · Maffezzolli Capital</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800&family=Poppins:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg:   #0A0A0A;
      --bg2:  #111111;
      --gold: #C9963A;
    }}
    body {{
      background: var(--bg);
      color: #F5F0E8;
      font-family: 'Poppins', sans-serif;
      font-weight: 300;
      min-height: 100vh;
    }}
    .admin-header {{
      border-bottom: 1px solid #1a1a1a;
      padding: 20px 32px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}
    .brand {{
      font-family: 'Syne', sans-serif;
      font-size: 1rem;
      font-weight: 700;
      letter-spacing: .1em;
      text-transform: uppercase;
      color: var(--gold);
    }}
    .admin-nav {{
      font-size: .78rem;
      color: #666;
    }}
    .admin-nav a {{ color: #888; text-decoration: none; margin: 0 8px; }}
    .admin-nav a:hover {{ color: #C9963A; }}
    .page-body {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 36px 24px 64px;
    }}
    .page-title {{
      font-family: 'Syne', sans-serif;
      font-size: 1.5rem;
      font-weight: 700;
      color: #F5F0E8;
      margin-bottom: 6px;
    }}
    .page-sub {{
      font-size: .82rem;
      color: #666;
      margin-bottom: 28px;
    }}
    .tab-btn {{
      padding: 9px 22px;
      font-family: 'Syne', sans-serif;
      font-size: .78rem;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      text-decoration: none;
      display: inline-block;
      transition: all .2s;
    }}
    .hover-row:hover {{ background: rgba(201,150,58,.04) !important; }}
    /* scrollbar styling */
    ::-webkit-scrollbar {{ width: 5px; height: 5px; }}
    ::-webkit-scrollbar-track {{ background: #111; }}
    ::-webkit-scrollbar-thumb {{ background: #333; border-radius: 99px; }}
    @media (max-width: 700px) {{
      .admin-header {{ padding: 16px; }}
      .page-body {{ padding: 20px 12px 48px; }}
    }}
  </style>
</head>
<body>

<div class="admin-header">
  <div class="brand">Maffezzolli Capital</div>
  <nav class="admin-nav">
    <a href="/admin">← Admin</a>
    <a href="/logout">Sair</a>
  </nav>
</div>

<div class="page-body">

  <div class="page-title">Pesquisas</div>
  <div class="page-sub">NPS Consultoria &amp; Feedback do App</div>

  <!-- Tab switcher -->
  <div style="display:flex;gap:10px;margin-bottom:28px;flex-wrap:wrap;">
    <a href="/admin/pesquisas?tab=nps" class="tab-btn" {tab_nps_active}>
      NPS Consultoria
      <span style="margin-left:8px;background:rgba(255,255,255,.12);padding:1px 8px;border-radius:99px;font-size:.72rem;">{len(nps_rows)}</span>
    </a>
    <a href="/admin/pesquisas?tab=app" class="tab-btn" {tab_app_active}>
      App MVP
      <span style="margin-left:8px;background:rgba(255,255,255,.12);padding:1px 8px;border-radius:99px;font-size:.72rem;">{len(app_rows)}</span>
    </a>
  </div>

  <!-- Tab body -->
  {tab_body}

</div>

<script>
  function openModal(id) {{
    document.getElementById(id).style.display = 'block';
    document.body.style.overflow = 'hidden';
  }}
  function closeModal(id) {{
    document.getElementById(id).style.display = 'none';
    document.body.style.overflow = '';
  }}
  // Close on backdrop click
  document.addEventListener('click', function(e) {{
    if (e.target.classList.contains('pq-modal')) {{
      e.target.style.display = 'none';
      document.body.style.overflow = '';
    }}
  }});
  // Close on Escape
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
      document.querySelectorAll('.pq-modal').forEach(m => {{
        m.style.display = 'none';
      }});
      document.body.style.overflow = '';
    }}
  }});
</script>

</body>
</html>'''

    return HTMLResponse(html_page)
