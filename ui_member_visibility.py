# ============================================================================
# PATCH — Visibilidade do Dashboard por Membro
# ============================================================================

from typing import Optional as _OptV
from sqlmodel import Field as _FV, SQLModel as _SMV


class MembershipVisibility(_SMV, table=True):
    __tablename__  = "membershipvisibility"
    __table_args__ = {"extend_existing": True}
    id:              _OptV[int] = _FV(default=None, primary_key=True)
    membership_id:   int        = _FV(unique=True, index=True)
    ver_score:       bool       = _FV(default=True)
    ver_diagnostico: bool       = _FV(default=True)
    ver_dre:         bool       = _FV(default=True)
    ver_augur:       bool       = _FV(default=True)

try:
    _SMV.metadata.create_all(engine, tables=[MembershipVisibility.__table__])
except Exception:
    pass


def get_member_visibility(session, membership_id: int) -> dict:
    mv = session.exec(
        select(MembershipVisibility)
        .where(MembershipVisibility.membership_id == membership_id)
    ).first()
    if mv:
        return {"ver_score": mv.ver_score, "ver_diagnostico": mv.ver_diagnostico,
                "ver_dre": mv.ver_dre, "ver_augur": mv.ver_augur}
    return {"ver_score": True, "ver_diagnostico": True, "ver_dre": True, "ver_augur": True}


@app.post("/admin/members/{membership_id}/visibility")
@require_login
async def member_visibility_post(
    membership_id: int, request: Request, session: Session = Depends(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return RedirectResponse("/admin/members", status_code=303)
    membership = session.get(Membership, membership_id)
    if not membership or membership.company_id != ctx.company.id:
        return RedirectResponse("/admin/members", status_code=303)
    form = await request.form()
    mv = session.exec(
        select(MembershipVisibility)
        .where(MembershipVisibility.membership_id == membership_id)
    ).first()
    if not mv:
        mv = MembershipVisibility(membership_id=membership_id)
    mv.ver_score       = "ver_score"       in form
    mv.ver_diagnostico = "ver_diagnostico" in form
    mv.ver_dre         = "ver_dre"         in form
    mv.ver_augur       = "ver_augur"       in form
    session.add(mv)
    session.commit()
    return RedirectResponse("/admin/members", status_code=303)


@app.get("/api/member/visibility")
@require_login
async def api_member_visibility(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ver_score": True, "ver_diagnostico": True,
                             "ver_dre": True, "ver_augur": True})
    vis = get_member_visibility(session, ctx.membership.id)
    return JSONResponse(vis)


# Registra helper como global Jinja2
if hasattr(templates_env, 'globals'):
    templates_env.globals['get_member_visibility'] = get_member_visibility


# Injeta guards no dashboard usando allowed_features (server-side)
# O dashboard já passa allowed_features no contexto
# Vamos wrappear o bloco do Painel de Saúde com o guard correto

_dash = TEMPLATES.get("dashboard.html", "")

# Guard para o Painel de Saúde (score)
if _dash and "vis-score-block" not in _dash:
    _dash = _dash.replace(
        '<div class="col-12" id="vis-score-block">',
        '{% if not allowed_features or "perfil" in allowed_features %}<div class="col-12" id="vis-score-block">',
    )
    # Fecha o guard — encontra o fechamento do bloco
    # Usa o bloco do Augur como referência para fechar antes
    if "augurCard" in _dash:
        _dash = _dash.replace(
            '{# ── AUGUR WIDGET',
            '{% endif %}{# fecha guard perfil #}\n{# ── AUGUR WIDGET',
        )

# Guard para o Augur
if _dash and "ver_augur" not in _dash and "augurCard" in _dash:
    _dash = _dash.replace(
        '{% if current_client %}\n<div class="card mb-3" id="augurCard"',
        '{% if current_client and (not allowed_features or "perfil" in allowed_features) %}\n<div class="card mb-3" id="augurCard"',
    )

TEMPLATES["dashboard.html"] = _dash

# Script JS apenas para ocultar Augur (mais simples e confiável)
_VIS_SCRIPT = """
<script>
(function(){
  fetch('/api/member/visibility')
    .then(function(r){return r.json();})
    .then(function(v){
      if(!v.ver_augur){
        var a=document.getElementById('augurCard');
        if(a)a.style.display='none';
      }
      if(!v.ver_score){
        var s=document.getElementById('vis-score-block');
        if(s)s.style.display='none';
      }
    })
    .catch(function(){});
})();
</script>"""

_dash2 = TEMPLATES.get("dashboard.html", "")
if _dash2 and "member/visibility" not in _dash2:
    if "{% endblock %}" in _dash2:
        _dash2 = _dash2.replace("{% endblock %}", _VIS_SCRIPT + "\n{% endblock %}", 1)
    TEMPLATES["dashboard.html"] = _dash2

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES
