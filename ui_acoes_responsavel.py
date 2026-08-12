# ui_acoes_responsavel.py
# Adiciona atribuição de responsável nas ações (MeetingAcao e BSCAction)
# via dropdown de membros da empresa. Injeta coluna clicável na tabela.

from fastapi import Request as _Req_ar, Depends as _Dep_ar, Form as _Form_ar
from fastapi.responses import HTMLResponse as _HTML_ar, JSONResponse as _JSON_ar, RedirectResponse as _RR_ar
from sqlmodel import Session as _Sess_ar, select as _sel_ar

# ── Endpoint: lista membros da empresa para o dropdown ────────────────────────
try:
    @app.get("/admin/acoes/membros", response_class=_JSON_ar)  # type: ignore[name-defined]
    @require_login  # type: ignore[name-defined]
    async def ar_listar_membros(request: _Req_ar, session: _Sess_ar = _Dep_ar(get_session)):  # type: ignore[name-defined]
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        if not ctx:
            return _JSON_ar([])
        membros = session.exec(
            _sel_ar(User).join(Membership,  # type: ignore[name-defined]
                User.id == Membership.user_id  # type: ignore[name-defined]
            ).where(
                Membership.company_id == ctx.company.id,  # type: ignore[name-defined]
                Membership.is_active == True,  # type: ignore[name-defined]
            )
        ).all()
        return _JSON_ar([{"id": m.id, "name": m.name} for m in membros])
    print("[acoes_resp] ✅ GET /admin/acoes/membros registrado")
except Exception as _e1:
    print(f"[acoes_resp] membros: {_e1}")


# ── Endpoint: atualiza responsável de MeetingAcao ─────────────────────────────
try:
    @app.post("/admin/acoes/{acao_id}/responsavel")  # type: ignore[name-defined]
    @require_login  # type: ignore[name-defined]
    async def ar_set_responsavel(
        request: _Req_ar,
        session: _Sess_ar = _Dep_ar(get_session),  # type: ignore[name-defined]
        acao_id: int = 0,
        responsavel: str = _Form_ar(""),
        responsavel_user_id: str = _Form_ar(""),
    ):
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        if not ctx:
            return _RR_ar("/login", status_code=303)

        a = session.get(MeetingAcao, acao_id)  # type: ignore[name-defined]
        if a and a.company_id == ctx.company.id:
            a.responsavel = responsavel
            a.responsavel_user_id = int(responsavel_user_id) if responsavel_user_id.strip().isdigit() else None
            session.add(a)
            session.commit()

        return _RR_ar(str(request.headers.get("referer", "/admin/acoes")), status_code=303)
    print("[acoes_resp] ✅ POST /admin/acoes/{id}/responsavel registrado")
except Exception as _e2:
    print(f"[acoes_resp] set_responsavel: {_e2}")


# ── Endpoint: atualiza responsável de BSCAction ───────────────────────────────
try:
    from ui_ferramenta_bsc import BSCAction as _BSCAction_ar

    @app.post("/admin/acoes/bsc/{acao_id}/responsavel")  # type: ignore[name-defined]
    @require_login  # type: ignore[name-defined]
    async def ar_set_responsavel_bsc(
        request: _Req_ar,
        session: _Sess_ar = _Dep_ar(get_session),  # type: ignore[name-defined]
        acao_id: int = 0,
        responsavel: str = _Form_ar(""),
    ):
        ctx = get_tenant_context(request, session)  # type: ignore[name-defined]
        if not ctx:
            return _RR_ar("/login", status_code=303)

        a = session.get(_BSCAction_ar, acao_id)
        if a and a.company_id == ctx.company.id:
            a.responsible = responsavel
            session.add(a)
            session.commit()

        return _RR_ar(str(request.headers.get("referer", "/admin/acoes")), status_code=303)
    print("[acoes_resp] ✅ POST /admin/acoes/bsc/{id}/responsavel registrado")
except Exception as _e3:
    print(f"[acoes_resp] set_responsavel_bsc: {_e3}")


# ── Injeta JS + modal de atribuição na página admin_acoes ────────────────────
_RESP_SCRIPT = r"""
<style>
.resp-btn {
  background: none; border: 1px dashed #ccc; border-radius: 6px;
  padding: 2px 8px; cursor: pointer; font-size: .8rem; color: #888;
  white-space: nowrap;
}
.resp-btn:hover { border-color: #E07020; color: #E07020; }
[data-bs-theme="dark"] .resp-btn { border-color: #4a6375; color: #7aafd4; }
[data-bs-theme="dark"] .resp-btn:hover { border-color: #E07020; color: #E07020; }
</style>

<div class="modal fade" id="modalResp" tabindex="-1">
  <div class="modal-dialog modal-sm">
    <div class="modal-content">
      <div class="modal-header py-2">
        <h6 class="modal-title mb-0">Atribuir responsável</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <form id="formResp" method="POST">
        <div class="modal-body py-3">
          <select name="responsavel" id="selectResp" class="form-select form-select-sm">
            <option value="">— sem responsável —</option>
          </select>
          <input type="hidden" name="responsavel_user_id" id="hiddenUserId">
        </div>
        <div class="modal-footer py-2">
          <button type="submit" class="btn btn-primary btn-sm">Salvar</button>
        </div>
      </form>
    </div>
  </div>
</div>

<script>
(function(){
  var membros = [];
  fetch('/admin/acoes/membros').then(r=>r.json()).then(function(data){
    membros = data;
  });

  document.addEventListener('click', function(e){
    var btn = e.target.closest('.resp-btn');
    if(!btn) return;
    var acaoId   = btn.dataset.id;
    var tipo     = btn.dataset.tipo; // "reuniao" ou "bsc"
    var current  = btn.dataset.current || '';

    var sel = document.getElementById('selectResp');
    sel.innerHTML = '<option value="">— sem responsável —</option>';
    membros.forEach(function(m){
      var opt = document.createElement('option');
      opt.value = m.name;
      opt.dataset.uid = m.id;
      opt.textContent = m.name;
      if(m.name === current) opt.selected = true;
      sel.appendChild(opt);
    });

    sel.onchange = function(){
      var opt = sel.options[sel.selectedIndex];
      document.getElementById('hiddenUserId').value = opt.dataset.uid || '';
    };

    var url = tipo === 'bsc'
      ? '/admin/acoes/bsc/' + acaoId + '/responsavel'
      : '/admin/acoes/' + acaoId + '/responsavel';
    document.getElementById('formResp').action = url;

    new bootstrap.Modal(document.getElementById('modalResp')).show();
  });
})();
</script>
"""

try:
    _tpl_ar = TEMPLATES.get("admin_acoes.html", "")  # type: ignore[name-defined]
    print(f"[acoes_resp] admin_acoes.html len={len(_tpl_ar)}, modalResp={'modalResp' in _tpl_ar}, a.responsavel={'{{ a.responsavel }}' in _tpl_ar}")
    if _tpl_ar and "modalResp" not in _tpl_ar:
        # Substitui o display do responsável por botão clicável
        # Template usa {{ a.responsavel }} (variável 'a', não 'item')
        _tpl_ar = _tpl_ar.replace(
            "{{ a.responsavel }}",
            """<button class="resp-btn"
                 data-id="{{ a._acao_id or a.id }}"
                 data-tipo="{{ a.tipo or 'bsc' }}"
                 data-current="{{ a.responsavel or '' }}"
                 title="Clique para atribuir responsável">
                 {{ a.responsavel or '+ atribuir' }}
               </button>""",
        )
        # Injeta modal e script antes de </body>
        _tpl_ar = _tpl_ar.replace("</body>", _RESP_SCRIPT + "\n</body>", 1)
        TEMPLATES["admin_acoes.html"] = _tpl_ar  # type: ignore[name-defined]
        if hasattr(templates_env.loader, "mapping"):  # type: ignore[name-defined]
            templates_env.loader.mapping = TEMPLATES  # type: ignore[name-defined]
        print("[acoes_resp] ✅ Dropdown de responsável injetado na tabela de ações")
except Exception as _e4:
    print(f"[acoes_resp] inject: {_e4}")
