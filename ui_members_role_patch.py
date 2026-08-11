# ============================================================================
# ui_members_role_patch.py — Adiciona seletor de papel (gestor/usuario)
#                            diretamente na página /admin/members
# ============================================================================
# Injeta no members.html um <select> inline para membros com role="cliente"
# que permite mudar o ClienteRole sem sair da tela de membros.
# Um endpoint /api/cliente-role/{cid}/{uid} fornece o valor atual via fetch.
# ============================================================================

from fastapi.responses import JSONResponse as _JSON_mrp, HTMLResponse as _HTML_mrp
from fastapi import Request as _Req_mrp, Depends as _Dep_mrp
from sqlmodel import Session as _Sess_mrp, select as _sel_mrp

# ── Endpoint: papel atual do usuário num cliente ───────────────────────────

@app.get("/api/cliente-role/{client_id}/{user_id}")
@require_login
async def api_get_cliente_role(
    request: _Req_mrp,
    session: _Sess_mrp = _Dep_mrp(get_session),
    client_id: int = 0,
    user_id: int = 0,
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _JSON_mrp({"role": "usuario"})
    try:
        cr = session.exec(
            _sel_mrp(ClienteRole).where(
                ClienteRole.company_id == ctx.company.id,
                ClienteRole.client_id == client_id,
                ClienteRole.user_id == user_id,
            )
        ).first()
        return _JSON_mrp({"role": cr.role if cr else "usuario"})
    except Exception:
        return _JSON_mrp({"role": "usuario"})


# ── Patch no members.html ─────────────────────────────────────────────────

_ROLE_SELECTOR_SNIPPET = r"""
                {% if row.membership.role == "cliente" and row.membership.client_id %}
                <div class="mt-2 d-flex align-items-center gap-2 flex-wrap">
                  <span class="muted" style="font-size:.78rem;">Papel no cliente:</span>
                  <select class="form-select form-select-sm mt-role-sel"
                          style="width:auto; font-size:.78rem;"
                          data-cid="{{ row.membership.client_id }}"
                          data-uid="{{ row.user.id }}"
                          onchange="mtRoleChange(this)">
                    <option value="usuario">👤 Usuário</option>
                    <option value="gestor">🔑 Gestor</option>
                  </select>
                  <span class="mt-role-ok" style="display:none;color:#22c55e;font-size:.75rem;">✓ salvo</span>
                </div>
                {% endif %}"""

_ROLE_JS = r"""
<script>
(function(){
  // Carrega papel atual para cada select
  document.querySelectorAll('.mt-role-sel').forEach(function(sel){
    var cid = sel.dataset.cid, uid = sel.dataset.uid;
    fetch('/api/cliente-role/' + cid + '/' + uid, {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){
        sel.value = d.role || 'usuario';
      })
      .catch(function(){});
  });
})();

function mtRoleChange(sel) {
  var cid = sel.dataset.cid, uid = sel.dataset.uid, role = sel.value;
  var ok = sel.parentElement.querySelector('.mt-role-ok');
  var fd = new FormData();
  fd.append('role', role);
  fetch('/admin/clientes/' + cid + '/usuarios/' + uid + '/role', {
    method: 'POST', credentials: 'same-origin', body: fd,
    // Evita redirecionamento — captura a resposta e ignora
    redirect: 'manual',
  })
  .then(function(){
    if(ok){ ok.style.display='inline'; setTimeout(function(){ ok.style.display='none'; }, 2000); }
  })
  .catch(function(e){ console.warn('mtRoleChange error', e); });
}
</script>
"""

try:
    _tpl = TEMPLATES.get("members.html", "")

    # Injeta o seletor após a linha de WhatsApp do usuário (Augur)
    _MARKER = "· WhatsApp: <b>{{ row.user.whatsapp_phone or \"—\" }}</b>"

    if _MARKER in _tpl and "mt-role-sel" not in _tpl:
        _tpl = _tpl.replace(
            _MARKER,
            _MARKER + "\n" + _ROLE_SELECTOR_SNIPPET,
            1,
        )
        # Injeta JS antes do </div> que fecha o list-group-item do primeiro row,
        # ou simplesmente antes de {% endfor %} no loop de rows
        _tpl = _tpl.replace(
            "{% endfor %}\n      </div>\n    </div>",
            "{% endfor %}\n      </div>\n    </div>\n" + _ROLE_JS,
            1,
        )

        TEMPLATES["members.html"] = _tpl
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["members.html"] = _tpl
        print("[members_role_patch] ✅ Seletor de papel injetado em members.html.")
    elif "mt-role-sel" in _tpl:
        print("[members_role_patch] ℹ️ Seletor já presente.")
    else:
        print(f"[members_role_patch] ⚠️ Marcador não encontrado em members.html.")

except Exception as _e_mrp:
    print(f"[members_role_patch] ⚠️ Erro: {_e_mrp}")

print("[members_role_patch] ✅ Módulo carregado.")
