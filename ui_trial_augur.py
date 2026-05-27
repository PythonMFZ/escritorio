# ============================================================================
# Augur PME — Trial / Freemium   (v2)
# ============================================================================
# Fluxo:
#   1. /cadastro               → formulário (nome, email, empresa, CNPJ, WhatsApp)
#   2. POST /api/trial/cadastro → cria TrialLead + card no CRM, retorna token
#   3. /trial?token=UUID        → Augur standalone, 5 msgs grátis
#   4. POST /api/trial/ask      → chat com limite + CTA progressivo
#   5. GET  /api/trial/status   → créditos restantes
#   6. GET  /api/trial/checkout → Stripe subscription checkout (R$299/mês)
# ============================================================================

import uuid as _uuid_tr
import re   as _re_tr
import os   as _os_tr
from datetime import datetime as _dt_tr, timedelta as _td_tr
from typing   import Optional as _Opt_tr
from sqlmodel import Field as _F_tr, SQLModel as _SM_tr, select as _sel_tr, Session as _Sess_tr
from fastapi  import Request as _Req_tr
from fastapi.responses import JSONResponse as _JSON_tr, HTMLResponse as _HTML_tr, RedirectResponse as _RR_tr

_TRIAL_MSGS_FREE  = 5   # mensagens gratuitas
_TRIAL_CTA_AT     = 3   # mostra banner a partir desta mensagem
_STRIPE_PRICE_PME = "price_1TSj9eDqHWO7wr"   # R$299/mês Augur PME
_ADMIN_EMAIL      = "maffezzolli.eng@gmail.com"


# ── Modelo ────────────────────────────────────────────────────────────────────

class TrialLead(_SM_tr, table=True):
    __tablename__  = "triallead"
    __table_args__ = {"extend_existing": True}
    id:             _Opt_tr[int] = _F_tr(default=None, primary_key=True)
    nome:           str          = _F_tr(default="")
    email:          str          = _F_tr(default="", index=True)
    empresa:        str          = _F_tr(default="")
    cnpj:           str          = _F_tr(default="", index=True)
    whatsapp:       str          = _F_tr(default="", index=True)
    access_token:   str          = _F_tr(default="", index=True)
    messages_used:  int          = _F_tr(default=0)
    messages_limit: int          = _F_tr(default=_TRIAL_MSGS_FREE)
    crm_deal_id:    _Opt_tr[int] = _F_tr(default=None)  # BusinessDeal.id
    created_at:     str          = _F_tr(default="")
    expires_at:     str          = _F_tr(default="")
    converted:      bool         = _F_tr(default=False)


try:
    _SM_tr.metadata.create_all(engine, tables=[TrialLead.__table__])
    print("[trial_augur] ✅ Tabela triallead OK")
except Exception as _e_tr:
    print(f"[trial_augur] Tabela: {_e_tr}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _limpar_cnpj(v: str) -> str:
    return _re_tr.sub(r"\D", "", v or "")

def _limpar_whatsapp(v: str) -> str:
    return _re_tr.sub(r"\D", "", v or "")

def _agora() -> str:
    return _dt_tr.now().strftime("%Y-%m-%d %H:%M:%S")

def _expira() -> str:
    return (_dt_tr.now() + _td_tr(days=30)).strftime("%Y-%m-%d %H:%M:%S")

def _trial_valido(lead: TrialLead) -> tuple[bool, str]:
    if lead.messages_used >= lead.messages_limit:
        return False, "credits"
    try:
        exp = _dt_tr.strptime(lead.expires_at, "%Y-%m-%d %H:%M:%S")
        if _dt_tr.now() > exp:
            return False, "expired"
    except Exception:
        pass
    return True, ""


def _criar_crm_lead(session, lead: TrialLead) -> _Opt_tr[int]:
    """Cria um BusinessDeal no CRM para rastrear o lead. Retorna deal_id ou None."""
    try:
        # Encontra admin e sua empresa
        admin_user = session.exec(_sel_tr(User).where(User.email == _ADMIN_EMAIL)).first()
        if not admin_user:
            return None
        membership = session.exec(
            _sel_tr(Membership).where(
                Membership.user_id == admin_user.id,
                Membership.role.in_(["admin", "owner"]),
            )
        ).first()
        if not membership:
            return None
        company_id = membership.company_id

        # Encontra ou cria cliente-placeholder "Leads Augur PME"
        placeholder = session.exec(
            _sel_tr(Client).where(
                Client.company_id == company_id,
                Client.name == "Leads Augur PME",
            )
        ).first()
        if not placeholder:
            placeholder = Client(
                company_id=company_id,
                name="Leads Augur PME",
                cnpj="00000000000000",
                notes="Cliente placeholder para leads do trial Augur PME",
            )
            session.add(placeholder)
            session.flush()

        deal = BusinessDeal(
            company_id         = company_id,
            client_id          = placeholder.id,
            created_by_user_id = admin_user.id,
            owner_user_id      = admin_user.id,
            title              = f"[Trial PME] {lead.empresa}",
            demand             = (
                f"Nome: {lead.nome}\n"
                f"Empresa: {lead.empresa}\n"
                f"CNPJ: {lead.cnpj}\n"
                f"WhatsApp: {lead.whatsapp}\n"
                f"E-mail: {lead.email}"
            ),
            stage   = "qualificacao",
            source  = "augur_trial",
            notes   = f"Trial iniciado em {_agora()}. Limite: {lead.messages_limit} msgs.",
        )
        session.add(deal)
        session.flush()
        return deal.id
    except Exception as _e_crm:
        print(f"[trial_crm] Erro ao criar deal: {_e_crm}")
        return None


# ── Página de cadastro ────────────────────────────────────────────────────────

_CADASTRO_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Diagnóstico Gratuito · Augur PME</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{--bg:#0A0A0A;--card:#141414;--border:#2a2a2a;--gold:#C9963A;--gold2:#E0A84B;--text:#F5F0E8;--muted:#888;}
    body{background:var(--bg);color:var(--text);font-family:'Poppins',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem 1rem;}
    .card{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:2.5rem 2rem;width:100%;max-width:480px;}
    .logo{text-align:center;margin-bottom:2rem;}
    .logo-text{font-family:'Syne',sans-serif;font-size:1.6rem;font-weight:800;color:var(--gold);letter-spacing:.05em;}
    .logo-sub{font-size:.75rem;color:var(--muted);margin-top:.2rem;}
    h1{font-family:'Syne',sans-serif;font-size:1.4rem;font-weight:700;margin-bottom:.5rem;text-align:center;}
    .sub{font-size:.85rem;color:var(--muted);text-align:center;margin-bottom:2rem;line-height:1.6;}
    .badge{display:inline-block;background:rgba(201,150,58,.12);border:1px solid rgba(201,150,58,.3);color:var(--gold);font-size:.72rem;font-weight:600;padding:.25rem .75rem;border-radius:999px;text-align:center;margin-bottom:1.25rem;}
    label{display:block;font-size:.78rem;font-weight:600;color:var(--muted);margin-bottom:.35rem;text-transform:uppercase;letter-spacing:.04em;}
    input{width:100%;background:#1a1a1a;border:1px solid var(--border);border-radius:10px;padding:.7rem 1rem;font-size:.9rem;color:var(--text);font-family:'Poppins',sans-serif;outline:none;transition:border .2s;}
    input:focus{border-color:var(--gold);}
    .field{margin-bottom:1.1rem;}
    .btn{width:100%;background:var(--gold);color:#0A0A0A;font-family:'Syne',sans-serif;font-weight:700;font-size:1rem;padding:.9rem;border:none;border-radius:12px;cursor:pointer;transition:background .2s;margin-top:.5rem;}
    .btn:hover{background:var(--gold2);}
    .btn:disabled{opacity:.6;cursor:not-allowed;}
    .note{font-size:.72rem;color:var(--muted);text-align:center;margin-top:1rem;line-height:1.5;}
    .err{color:#f87171;font-size:.8rem;margin-top:.4rem;display:none;}
    .spinner{display:none;margin:0 auto;width:22px;height:22px;border:3px solid rgba(255,255,255,.2);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;}
    @keyframes spin{to{transform:rotate(360deg)}}
  </style>
</head>
<body>
<div class="card">
  <div class="logo">
    <div class="logo-text">Augur</div>
    <div class="logo-sub">by Maffezzolli Capital</div>
  </div>
  <div style="text-align:center;margin-bottom:1.5rem;">
    <div class="badge">🎁 5 diagnósticos gratuitos · sem cartão</div>
  </div>
  <h1>Diagnóstico gratuito da sua empresa</h1>
  <p class="sub">Preencha os dados abaixo e acesse o Augur imediatamente.<br>Sem cartão de crédito. Sem compromisso.</p>

  <form id="form" onsubmit="enviar(event)">
    <div class="field">
      <label>Seu nome</label>
      <input type="text" id="nome" placeholder="João Silva" required autocomplete="name">
    </div>
    <div class="field">
      <label>E-mail</label>
      <input type="email" id="email" placeholder="joao@empresa.com.br" required autocomplete="email">
    </div>
    <div class="field">
      <label>Nome da empresa</label>
      <input type="text" id="empresa" placeholder="Construtora ABC Ltda" required>
    </div>
    <div class="field">
      <label>CNPJ</label>
      <input type="text" id="cnpj" placeholder="00.000.000/0001-00" required maxlength="18" oninput="mascaraCNPJ(this)">
      <div class="err" id="errCnpj">CNPJ inválido ou já cadastrado.</div>
    </div>
    <div class="field">
      <label>WhatsApp</label>
      <input type="tel" id="whatsapp" placeholder="(47) 99999-0000" required oninput="mascaraFone(this)">
    </div>
    <div class="err" id="errGeral">Ocorreu um erro. Tente novamente.</div>
    <button type="submit" class="btn" id="btn">Acessar diagnóstico grátis</button>
    <div class="spinner" id="spin"></div>
  </form>
  <p class="note">Ao continuar, você concorda que a Maffezzolli Capital pode entrar em contato sobre seus serviços.</p>
</div>
<script>
function mascaraCNPJ(el){
  let v=el.value.replace(/\D/g,'').slice(0,14);
  if(v.length>12) v=v.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d)/,'$1.$2.$3/$4-$5');
  else if(v.length>8) v=v.replace(/^(\d{2})(\d{3})(\d{3})(\d)/,'$1.$2.$3/$4');
  else if(v.length>5) v=v.replace(/^(\d{2})(\d{3})(\d)/,'$1.$2.$3');
  else if(v.length>2) v=v.replace(/^(\d{2})(\d)/,'$1.$2');
  el.value=v;
}
function mascaraFone(el){
  let v=el.value.replace(/\D/g,'').slice(0,11);
  if(v.length>10) v=v.replace(/^(\d{2})(\d{5})(\d{4})$/,'($1) $2-$3');
  else if(v.length>6) v=v.replace(/^(\d{2})(\d{4})(\d)/,'($1) $2-$3');
  else if(v.length>2) v=v.replace(/^(\d{2})(\d)/,'($1) $2');
  el.value=v;
}
async function enviar(e){
  e.preventDefault();
  document.querySelectorAll('.err').forEach(el=>el.style.display='none');
  const btn=document.getElementById('btn');
  const spin=document.getElementById('spin');
  btn.style.display='none'; spin.style.display='block';
  const payload={
    nome:document.getElementById('nome').value.trim(),
    email:document.getElementById('email').value.trim(),
    empresa:document.getElementById('empresa').value.trim(),
    cnpj:document.getElementById('cnpj').value,
    whatsapp:document.getElementById('whatsapp').value,
  };
  try{
    const r=await fetch('/api/trial/cadastro',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.ok){
      window.location.href='/trial?token='+d.token;
    } else if(d.erro==='cnpj_duplicado'){
      document.getElementById('errCnpj').style.display='block';
      btn.style.display='block'; spin.style.display='none';
    } else {
      document.getElementById('errGeral').textContent=d.erro||'Erro inesperado.';
      document.getElementById('errGeral').style.display='block';
      btn.style.display='block'; spin.style.display='none';
    }
  }catch(err){
    document.getElementById('errGeral').style.display='block';
    btn.style.display='block'; spin.style.display='none';
  }
}
</script>
</body>
</html>"""


@app.get("/cadastro")
async def trial_cadastro_page():
    return _HTML_tr(_CADASTRO_HTML)


# ── Rota admin: acesso direto ao trial para testes ───────────────────────────

@app.get("/trial/demo")
async def trial_demo(request: _Req_tr):
    if not request.session.get("user_id"):
        return _HTML_tr("<script>location.href='/login'</script>")

    token = "demo-" + str(_uuid_tr.uuid4())
    with _Sess_tr(engine) as _s:
        _s.add(TrialLead(
            nome           = request.session.get("user_name", "Admin"),
            email          = _ADMIN_EMAIL,
            empresa        = "Demo Interno",
            cnpj           = "DEMO" + token[:8],
            whatsapp       = "00000000000",
            access_token   = token,
            messages_used  = 0,
            messages_limit = 999,
            created_at     = _agora(),
            expires_at     = (_dt_tr.now() + _td_tr(days=365)).strftime("%Y-%m-%d %H:%M:%S"),
        ))
        _s.commit()

    return _RR_tr(f"/trial?token={token}", status_code=303)


# ── API: criar trial ──────────────────────────────────────────────────────────

@app.post("/api/trial/cadastro")
async def trial_cadastro(request: _Req_tr):
    try:
        body = await request.json()
    except Exception:
        return _JSON_tr({"ok": False, "erro": "Dados inválidos."})

    nome     = (body.get("nome") or "").strip()
    email    = (body.get("email") or "").strip().lower()
    empresa  = (body.get("empresa") or "").strip()
    cnpj_raw = _limpar_cnpj(body.get("cnpj") or "")
    wpp_raw  = _limpar_whatsapp(body.get("whatsapp") or "")

    if not nome or not empresa or len(cnpj_raw) < 14 or len(wpp_raw) < 10:
        return _JSON_tr({"ok": False, "erro": "Preencha todos os campos corretamente."})

    with _Sess_tr(engine) as session:
        existente = session.exec(
            _sel_tr(TrialLead).where(TrialLead.cnpj == cnpj_raw)
        ).first()
        if existente:
            return _JSON_tr({"ok": False, "erro": "cnpj_duplicado"})

        token = str(_uuid_tr.uuid4())
        lead  = TrialLead(
            nome           = nome,
            email          = email,
            empresa        = empresa,
            cnpj           = cnpj_raw,
            whatsapp       = wpp_raw,
            access_token   = token,
            messages_used  = 0,
            messages_limit = _TRIAL_MSGS_FREE,
            created_at     = _agora(),
            expires_at     = _expira(),
        )
        session.add(lead)
        session.flush()

        # Cria card no CRM automaticamente
        deal_id = _criar_crm_lead(session, lead)
        if deal_id:
            lead.crm_deal_id = deal_id
            session.add(lead)

        session.commit()
        print(f"[trial] Novo lead: {empresa} / {cnpj_raw} / wpp={wpp_raw[-4:]} / crm_deal={deal_id}")

    return _JSON_tr({"ok": True, "token": token})


# ── Página trial (Augur standalone) ──────────────────────────────────────────

_TRIAL_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Augur · Diagnóstico Financeiro</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Poppins:wght@300;400;500;600&display=swap" rel="stylesheet">
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    :root{--bg:#F7F8FA;--card:#fff;--border:#E5E7EB;--gold:#C9963A;--primary:#1a1a2e;--text:#1a1a2e;--muted:#6B7280;}
    body{background:var(--bg);color:var(--text);font-family:'Poppins',sans-serif;min-height:100vh;display:flex;flex-direction:column;}
    nav{background:#0A0A0A;padding:.75rem 1.5rem;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
    .nav-brand{font-family:'Syne',sans-serif;font-weight:800;font-size:1.2rem;color:#C9963A;}
    .nav-info{font-size:.72rem;color:#888;}
    .credit-bar{background:#fff;border-bottom:1px solid var(--border);padding:.6rem 1.5rem;display:flex;align-items:center;gap:1rem;flex-shrink:0;}
    .credit-label{font-size:.75rem;color:var(--muted);font-weight:500;}
    .credit-track{flex:1;max-width:200px;height:6px;background:#E5E7EB;border-radius:999px;overflow:hidden;}
    .credit-fill{height:100%;background:#C9963A;border-radius:999px;transition:width .4s;}
    .credit-count{font-size:.75rem;font-weight:600;color:var(--text);}
    .trial-badge{font-size:.68rem;background:rgba(201,150,58,.1);color:#C9963A;border:1px solid rgba(201,150,58,.3);border-radius:999px;padding:.15rem .6rem;font-weight:600;}
    /* CTA banner */
    .cta-banner{display:none;background:linear-gradient(135deg,#1a1a2e,#0A0A0A);color:#fff;padding:.9rem 1.5rem;border-bottom:1px solid #2a2a2a;flex-shrink:0;}
    .cta-banner.show{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;}
    .cta-banner-text{font-size:.8rem;line-height:1.4;}
    .cta-banner-text strong{color:#C9963A;}
    .cta-banner-btn{background:#C9963A;color:#0A0A0A;border:none;border-radius:8px;padding:.45rem 1.1rem;font-weight:700;font-size:.78rem;cursor:pointer;white-space:nowrap;font-family:'Syne',sans-serif;}
    .cta-banner-btn:hover{background:#E0A84B;}
    .chat-wrap{flex:1;display:flex;flex-direction:column;max-width:760px;width:100%;margin:0 auto;padding:1rem;gap:.75rem;overflow-y:auto;}
    .msg{display:flex;gap:.5rem;max-width:100%;}
    .msg.user{flex-direction:row-reverse;}
    .bubble{max-width:82%;padding:.65rem .95rem;border-radius:14px;font-size:.87rem;line-height:1.6;white-space:pre-wrap;word-break:break-word;}
    .bubble.user{background:#0A0A0A;color:#fff;border-radius:14px 14px 4px 14px;}
    .bubble.assistant{background:#fff;border:1px solid var(--border);border-radius:14px 14px 14px 4px;color:var(--text);}
    .av{width:30px;height:30px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;align-self:flex-end;}
    .av.user{background:#0A0A0A;color:#fff;}
    .av.assistant{background:#0A0A0A;overflow:hidden;}
    .av.assistant img{width:20px;height:20px;object-fit:contain;}
    .meta{font-size:.65rem;color:var(--muted);margin-top:.2rem;}
    .typing-wrap{display:flex;gap:4px;align-items:center;padding:.4rem .8rem;}
    .typing-wrap span{width:7px;height:7px;border-radius:50%;background:var(--muted);animation:bounce 1.2s infinite;}
    .typing-wrap span:nth-child(2){animation-delay:.2s;}.typing-wrap span:nth-child(3){animation-delay:.4s;}
    @keyframes bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
    .input-area{background:#fff;border-top:1px solid var(--border);padding:.75rem 1rem;display:flex;gap:.6rem;align-items:flex-end;flex-shrink:0;}
    .input-area textarea{flex:1;border:1px solid var(--border);border-radius:10px;padding:.6rem .9rem;font-size:.87rem;font-family:'Poppins',sans-serif;resize:none;outline:none;max-height:120px;}
    .input-area textarea:focus{border-color:#C9963A;}
    .send-btn{background:#0A0A0A;color:#fff;border:none;border-radius:10px;padding:.6rem 1.1rem;font-size:.82rem;font-weight:600;cursor:pointer;align-self:flex-end;min-width:80px;}
    .send-btn:disabled{opacity:.5;cursor:not-allowed;}
    .sugg{display:flex;gap:.5rem;flex-wrap:wrap;padding:.5rem 1rem;background:#fff;border-top:1px solid var(--border);}
    .sugg button{background:#F7F8FA;border:1px solid var(--border);border-radius:999px;padding:.3rem .8rem;font-size:.73rem;cursor:pointer;font-family:'Poppins',sans-serif;color:var(--text);}
    .sugg button:hover{border-color:#C9963A;color:#C9963A;}
    /* Paywall */
    .paywall{display:none;position:fixed;inset:0;background:rgba(10,10,10,.9);z-index:100;align-items:center;justify-content:center;padding:1rem;}
    .paywall.show{display:flex;}
    .paywall-card{background:#fff;border-radius:20px;padding:2.5rem 2rem;max-width:440px;width:100%;text-align:center;}
    .paywall-icon{font-size:2.5rem;margin-bottom:1rem;}
    .paywall h2{font-family:'Syne',sans-serif;font-size:1.3rem;margin-bottom:.75rem;}
    .paywall p{font-size:.85rem;color:var(--muted);line-height:1.6;margin-bottom:.5rem;}
    .paywall-price{font-family:'Syne',sans-serif;font-size:1.6rem;font-weight:800;color:#1a1a2e;margin:.75rem 0 1.5rem;}
    .paywall-price span{font-size:.9rem;font-weight:400;color:var(--muted);}
    .paywall-btns{display:flex;flex-direction:column;gap:.75rem;}
    .paywall .btn-gold{background:#C9963A;color:#fff;border:none;border-radius:12px;padding:.9rem;font-weight:700;font-size:.95rem;cursor:pointer;font-family:'Syne',sans-serif;text-decoration:none;display:block;}
    .paywall .btn-gold:hover{background:#E0A84B;}
    .paywall .btn-outline{background:transparent;color:#1a1a2e;border:1px solid #E5E7EB;border-radius:12px;padding:.9rem;font-weight:600;font-size:.9rem;cursor:pointer;display:block;text-decoration:none;}
    .paywall-features{text-align:left;margin:.75rem 0 1.5rem;font-size:.8rem;color:var(--muted);list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:.4rem;}
    .paywall-features li::before{content:'✓ ';color:#C9963A;font-weight:700;}
  </style>
</head>
<body>

<nav>
  <div class="nav-brand">Augur</div>
  <div class="nav-info">Diagnóstico gratuito · by Maffezzolli Capital</div>
</nav>

<div class="credit-bar">
  <span class="credit-label">Diagnósticos gratuitos</span>
  <div class="credit-track"><div class="credit-fill" id="creditFill" style="width:100%"></div></div>
  <span class="credit-count" id="creditCount">5 / 5</span>
  <span class="trial-badge">Trial gratuito</span>
</div>

<!-- Banner CTA progressivo -->
<div class="cta-banner" id="ctaBanner">
  <div class="cta-banner-text">
    <strong>Está gostando do Augur?</strong> Você tem <strong id="ctaRestantes">X</strong> mensagens restantes no trial.
    Assine e tenha acesso ilimitado ao diagnóstico financeiro da sua empresa.
  </div>
  <button class="cta-banner-btn" onclick="abrirStripeCheckout()">Assinar R$299/mês →</button>
</div>

<div class="chat-wrap" id="chatArea">
  <div class="msg assistant">
    <div class="av assistant"><img src="/static/augur_logo_v3.png" alt="Augur"></div>
    <div>
      <div class="bubble assistant">Olá! Sou o Augur, seu consultor financeiro inteligente. 👋

Vou fazer um diagnóstico rápido da sua empresa — leva cerca de 10 minutos e você sai daqui sabendo exatamente onde estão os pontos críticos do seu negócio.

Para começar: **qual é o principal desafio financeiro da sua empresa hoje?** Pode ser fluxo de caixa, dívidas, margem, crescimento — fique à vontade para descrever.</div>
      <div class="meta">agora</div>
    </div>
  </div>
</div>

<div class="sugg" id="sugg">
  <button onclick="setQ('Fluxo de caixa apertado')">💸 Fluxo de caixa apertado</button>
  <button onclick="setQ('Dívidas e renegociação')">📋 Dívidas e renegociação</button>
  <button onclick="setQ('Quero crescer mas falta capital')">🚀 Falta capital para crescer</button>
  <button onclick="setQ('Margem baixa e não sei o porquê')">📉 Margem baixa</button>
</div>

<div class="input-area">
  <textarea id="inp" rows="2" placeholder="Descreva sua situação..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();enviar();}"></textarea>
  <button class="send-btn" id="sendBtn" onclick="enviar()">Enviar</button>
</div>

<!-- Paywall -->
<div class="paywall" id="paywall">
  <div class="paywall-card">
    <div class="paywall-icon">🔐</div>
    <h2 id="paywallTitle">Você usou seu diagnóstico gratuito</h2>
    <p id="paywallDesc">Gostou do Augur? Com a assinatura você tem acesso ilimitado, histórico completo e alertas financeiros automáticos.</p>
    <div class="paywall-price">R$299<span>/mês</span></div>
    <ul class="paywall-features">
      <li>Augur ilimitado</li>
      <li>Histórico completo</li>
      <li>Alertas automáticos</li>
      <li>Suporte dedicado</li>
      <li>Relatórios PDF</li>
      <li>Score financeiro</li>
    </ul>
    <div class="paywall-btns">
      <a id="stripeBtn" href="#" class="btn-gold" onclick="abrirStripeCheckout();return false;">
        Assinar agora — R$299/mês
      </a>
      <a href="https://wa.me/5547991359091?text=Quero+assinar+o+Augur+PME" target="_blank" class="btn-outline">
        Falar com um consultor
      </a>
    </div>
  </div>
</div>

<script>
(function(){
  const TOKEN = new URLSearchParams(location.search).get('token') || '';
  if(!TOKEN){ location.href='/cadastro'; return; }

  let limitTotal = __LIMIT__;
  let limitUsed  = 0;
  let _history   = [];

  fetch('/api/trial/status?token='+TOKEN)
    .then(r=>r.json())
    .then(d=>{
      if(!d.ok){ location.href='/cadastro'; return; }
      limitTotal = d.limit;
      limitUsed  = d.used;
      atualizarCreditos();
      if(!d.pode_usar) mostrarPaywall(d.motivo);
      else if(d.used >= __CTA_AT__) mostrarCtaBanner(d.limit - d.used);
    })
    .catch(()=>{ location.href='/cadastro'; });

  function atualizarCreditos(){
    const restantes = Math.max(0, limitTotal - limitUsed);
    const pct = limitTotal > 0 ? (restantes / limitTotal * 100) : 0;
    document.getElementById('creditFill').style.width = pct+'%';
    document.getElementById('creditCount').textContent = restantes+' / '+limitTotal;
    if(pct <= 40) document.getElementById('creditFill').style.background = '#f59e0b';
    if(pct <= 20) document.getElementById('creditFill').style.background = '#ef4444';
  }

  function mostrarCtaBanner(restantes){
    const banner = document.getElementById('ctaBanner');
    document.getElementById('ctaRestantes').textContent = restantes;
    banner.classList.add('show');
  }

  function mostrarPaywall(motivo){
    const pw = document.getElementById('paywall');
    if(motivo === 'expired'){
      document.getElementById('paywallTitle').textContent = 'Seu período gratuito encerrou';
      document.getElementById('paywallDesc').textContent  = 'Seus 30 dias de teste chegaram ao fim. Assine para continuar usando o Augur sem limites.';
    }
    pw.classList.add('show');
    document.getElementById('sendBtn').disabled = true;
    document.getElementById('inp').disabled = true;
  }

  window.abrirStripeCheckout = function(){
    const btn = document.getElementById('stripeBtn');
    btn.textContent = 'Aguarde...';
    fetch('/api/trial/checkout?token='+TOKEN)
      .then(r=>r.json())
      .then(d=>{
        if(d.url) window.location.href = d.url;
        else { btn.textContent='Erro — tente novamente'; }
      })
      .catch(()=>{ btn.textContent='Erro — tente novamente'; });
  };

  function _esc(t){ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function addMsg(role, text, animate){
    const area = document.getElementById('chatArea');
    const wrap = document.createElement('div');
    wrap.className = 'msg '+role;
    const hora = new Date().toTimeString().slice(0,5);
    const av = role==='user'
      ? '<div class="av user">EU</div>'
      : '<div class="av assistant"><img src="/static/augur_logo_v3.png" alt="Augur"></div>';
    wrap.innerHTML = av+'<div><div class="bubble '+role+'" style="white-space:pre-wrap">'+_esc(text)+'</div><div class="meta">'+hora+'</div></div>';
    if(animate){ wrap.style.opacity='0'; area.appendChild(wrap); setTimeout(()=>{wrap.style.transition='opacity .3s';wrap.style.opacity='1';},10); }
    else area.appendChild(wrap);
    area.scrollTop = area.scrollHeight;
  }

  function showTyping(){
    const area = document.getElementById('chatArea');
    const el = document.createElement('div');
    el.className='msg assistant'; el.id='typing';
    el.innerHTML='<div class="av assistant"><img src="/static/augur_logo_v3.png" alt="Augur"></div><div class="bubble assistant"><div class="typing-wrap"><span></span><span></span><span></span></div></div>';
    area.appendChild(el); area.scrollTop=area.scrollHeight;
  }
  function hideTyping(){ const el=document.getElementById('typing'); if(el) el.remove(); }

  window.setQ = function(q){ document.getElementById('inp').value=q; document.getElementById('inp').focus(); };

  window.enviar = async function(){
    const inp = document.getElementById('inp');
    const q = (inp.value||'').trim();
    if(!q) return;
    if(limitUsed >= limitTotal){ mostrarPaywall('credits'); return; }

    const btn = document.getElementById('sendBtn');
    btn.disabled=true; inp.value='';
    document.getElementById('sugg').style.display='none';

    _history.push({role:'user', content:q});
    addMsg('user', q, true);
    showTyping();

    try{
      const r = await fetch('/api/trial/ask',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({token:TOKEN, question:q, history:_history.slice(-20)})
      });
      const d = await r.json();
      hideTyping();

      if(d.paywall){
        addMsg('assistant','Você atingiu o limite do seu diagnóstico gratuito. Veja como continuar abaixo!', true);
        setTimeout(()=>mostrarPaywall(d.motivo||'credits'), 1200);
        return;
      }
      if(d.error){ addMsg('assistant','⚠️ '+(d.error||'Erro.'), true); return; }

      _history.push({role:'assistant', content:d.response});
      addMsg('assistant', d.response, true);
      limitUsed = d.used || (limitUsed+1);
      atualizarCreditos();

      // Mostra banner CTA quando chega em __CTA_AT__ mensagens usadas
      if(limitUsed >= __CTA_AT__ && !document.getElementById('ctaBanner').classList.contains('show')){
        mostrarCtaBanner(Math.max(0, limitTotal - limitUsed));
      } else if(document.getElementById('ctaBanner').classList.contains('show')){
        document.getElementById('ctaRestantes').textContent = Math.max(0, limitTotal - limitUsed);
      }

      if(!d.pode_usar) setTimeout(()=>mostrarPaywall('credits'), 1200);

    }catch(e){
      hideTyping();
      addMsg('assistant','⚠️ Erro de conexão. Tente novamente.', true);
    }finally{
      btn.disabled=false; inp.focus();
    }
  };
})();
</script>
</body>
</html>"""

# Substitui placeholders de configuração no HTML
_TRIAL_HTML = _TRIAL_HTML.replace("__LIMIT__", str(_TRIAL_MSGS_FREE)).replace("__CTA_AT__", str(_TRIAL_CTA_AT))


@app.get("/trial")
async def trial_page(token: str = ""):
    if not token:
        return _HTML_tr("<script>location.href='/cadastro'</script>")
    with _Sess_tr(engine) as session:
        lead = session.exec(_sel_tr(TrialLead).where(TrialLead.access_token == token)).first()
        if not lead:
            return _HTML_tr("<script>location.href='/cadastro'</script>")
    return _HTML_tr(_TRIAL_HTML)


# ── API: status ───────────────────────────────────────────────────────────────

@app.get("/api/trial/status")
async def trial_status(token: str = ""):
    if not token:
        return _JSON_tr({"ok": False})
    with _Sess_tr(engine) as session:
        lead = session.exec(_sel_tr(TrialLead).where(TrialLead.access_token == token)).first()
        if not lead:
            return _JSON_tr({"ok": False})
        ok, motivo = _trial_valido(lead)
        return _JSON_tr({
            "ok": True,
            "pode_usar": ok,
            "motivo": motivo,
            "used": lead.messages_used,
            "limit": lead.messages_limit,
            "empresa": lead.empresa,
            "expires_at": lead.expires_at,
        })


# ── API: Stripe checkout (subscription R$299/mês) ─────────────────────────────

@app.get("/api/trial/checkout")
async def trial_checkout(request: _Req_tr, token: str = ""):
    if not token:
        return _JSON_tr({"error": "Token inválido."})

    with _Sess_tr(engine) as session:
        lead = session.exec(_sel_tr(TrialLead).where(TrialLead.access_token == token)).first()
        if not lead:
            return _JSON_tr({"error": "Acesso inválido."})

    try:
        import stripe as _stripe_tr  # type: ignore
        _stripe_tr.api_key = _os_tr.environ.get("STRIPE_SECRET_KEY", "")
        if not _stripe_tr.api_key:
            raise ValueError("STRIPE_SECRET_KEY não configurado")

        base = str(request.base_url).rstrip("/")
        checkout = _stripe_tr.checkout.Session.create(
            mode="subscription",
            success_url=base + f"/trial/assinado?token={token}",
            cancel_url=base + f"/trial?token={token}",
            customer_email=lead.email or None,
            line_items=[{"price": _STRIPE_PRICE_PME, "quantity": 1}],
            metadata={
                "trial_token": token,
                "lead_id": str(lead.id),
                "tipo": "augur_pme",
            },
        )
        return _JSON_tr({"url": checkout.url})
    except Exception as _e_stripe:
        print(f"[trial_checkout] Stripe erro: {_e_stripe}")
        return _JSON_tr({"error": "Erro ao criar checkout. Tente novamente."})


# ── Página de sucesso pós-assinatura ─────────────────────────────────────────

@app.get("/trial/assinado")
async def trial_assinado(token: str = ""):
    _html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
<title>Obrigado · Augur PME</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Poppins:wght@400;600&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0A0A0A;color:#F5F0E8;font-family:'Poppins',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem;}}
.card{{background:#141414;border:1px solid #2a2a2a;border-radius:20px;padding:3rem 2rem;max-width:480px;width:100%;text-align:center;}}
.icon{{font-size:3rem;margin-bottom:1.5rem;}}
h1{{font-family:'Syne',sans-serif;font-size:1.5rem;color:#C9963A;margin-bottom:.75rem;}}
p{{font-size:.9rem;color:#888;line-height:1.7;margin-bottom:1.5rem;}}
.btn{{display:inline-block;background:#C9963A;color:#0A0A0A;padding:.9rem 2rem;border-radius:12px;font-family:'Syne',sans-serif;font-weight:700;font-size:.95rem;text-decoration:none;}}
</style></head><body>
<div class="card">
  <div class="icon">🎉</div>
  <h1>Assinatura confirmada!</h1>
  <p>Bem-vindo ao Augur PME. Nossa equipe entrará em contato em breve para criar seu acesso completo à plataforma.</p>
  <p style="margin-bottom:2rem;">Qualquer dúvida, fale conosco pelo WhatsApp:</p>
  <a href="https://wa.me/5547991359091?text=Acabei+de+assinar+o+Augur+PME" class="btn">Falar com a equipe →</a>
</div></body></html>"""
    return _HTML_tr(_html)


# ── API: chat trial ───────────────────────────────────────────────────────────

_TRIAL_SYSTEM = """Você é o Augur, assistente financeiro inteligente da Maffezzolli Capital.

O usuário está no diagnóstico gratuito (trial PME). Seu objetivo é:
1. Entender a situação financeira da empresa em até 15 perguntas objetivas
2. Identificar os principais problemas: caixa, margem, dívida, capital de giro, inadimplência
3. Ao final, apresentar um Score de Saúde Financeira (0–100) com justificativa e top 3 ações prioritárias

Estilo:
- Perguntas curtas e diretas, uma por vez
- Linguagem acessível (evite jargão técnico)
- Empático mas objetivo — você está aqui para ajudar, não para impressionar
- Quando tiver dados suficientes, consolide em um diagnóstico claro com score e plano de ação

Ao final do diagnóstico, mencione naturalmente que com o Augur completo o empresário teria acesso contínuo a esse nível de análise, histórico e alertas automáticos."""


@app.post("/api/trial/ask")
async def trial_ask(request: _Req_tr):
    try:
        body = await request.json()
    except Exception:
        return _JSON_tr({"error": "Dados inválidos."})

    token    = (body.get("token") or "").strip()
    question = (body.get("question") or "").strip()
    history  = body.get("history") or []

    if not token or not question:
        return _JSON_tr({"error": "Dados incompletos."})

    with _Sess_tr(engine) as session:
        lead = session.exec(_sel_tr(TrialLead).where(TrialLead.access_token == token)).first()
        if not lead:
            return _JSON_tr({"error": "Acesso inválido.", "paywall": True})

        ok, motivo = _trial_valido(lead)
        if not ok:
            return _JSON_tr({"paywall": True, "motivo": motivo})

        try:
            from ai_assistant.assistant import ask as _ask_tr

            conv_history = []
            for h in history[-18:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    conv_history.append({"role": h["role"], "content": h["content"]})

            client_data_trial = {
                "nome":    lead.nome,
                "empresa": lead.empresa,
                "cnpj":    lead.cnpj if not lead.cnpj.startswith("DEMO") else "",
                "segment": "pme",
                "_trial_system_override": _TRIAL_SYSTEM,
            }

            result = _ask_tr(
                question=question,
                client_data=client_data_trial,
                conversation_history=conv_history if conv_history else None,
            )
            answer = result.get("response") or "Não consegui processar sua pergunta."
            if result.get("error"):
                return _JSON_tr({"error": answer})
        except ImportError:
            return _JSON_tr({"error": "Assistente não disponível. Tente novamente."})
        except Exception as _e_ai:
            print(f"[trial_ask] Claude erro: {_e_ai}")
            return _JSON_tr({"error": "Erro ao processar. Tente novamente."})

        lead.messages_used += 1
        session.add(lead)
        session.commit()

        pode_ainda, _ = _trial_valido(lead)
        restantes = lead.messages_limit - lead.messages_used
        print(f"[trial_ask] {lead.empresa}: {lead.messages_used}/{lead.messages_limit} msgs")

        return _JSON_tr({
            "response": answer,
            "used":     lead.messages_used,
            "limit":    lead.messages_limit,
            "restantes": restantes,
            "pode_usar": pode_ainda,
        })


print("[trial_augur] ✅ Augur PME Trial v2 carregado")
