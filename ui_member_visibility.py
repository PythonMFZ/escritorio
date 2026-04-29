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

# Script de visibilidade com IDs reais do dashboard
_VIS_SCRIPT = """
<script>
(function(){
  // Só aplica para clientes — admin e equipe sempre veem tudo
  fetch('/api/member/visibility')
    .then(r => r.json())
    .then(v => {
      function hide(id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
      }
      function hideAll(sel) {
        document.querySelectorAll(sel).forEach(function(el){ el.style.display='none'; });
      }
      if (!v.ver_augur) hide('augurCard');
      if (!v.ver_score) hide('vis-score-block');
      if (!v.ver_diagnostico) {
        // Oculta abas e seções de diagnóstico
        hideAll('[href*="diagnostico"], [href*="perfil/avaliacao"]');
      }
      if (!v.ver_dre) {
        hide('dre-summary');
        hideAll('[id^="dre-"]');
      }
    })
    .catch(function(){});
})();
</script>"""

_dash = TEMPLATES.get("dashboard.html", "")
if _dash and "member/visibility" not in _dash:
    if "{% endblock %}" in _dash:
        _dash = _dash.replace("{% endblock %}", _VIS_SCRIPT + "\n{% endblock %}", 1)
    else:
        _dash += _VIS_SCRIPT
    TEMPLATES["dashboard.html"] = _dash

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES
