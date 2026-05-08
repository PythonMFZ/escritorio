# ── Batch 6 v2: layout fix, sessões, Documentos, Base de Conhecimento ────────
import re as _re_b6


# ─────────────────────────────────────────────────────────────────────────────
# 1. Remove rota /api/ai/ask duplicada (v3 bloqueia v4 que tem sessões/BC)
# ─────────────────────────────────────────────────────────────────────────────

def _b6v2_fix_ask_route() -> None:
    routes = app.routes
    idx = [i for i, r in enumerate(routes)
           if getattr(r, "path", None) == "/api/ai/ask"
           and "POST" in (getattr(r, "methods", None) or set())]
    if len(idx) > 1:
        for i in sorted(idx[:-1], reverse=True):
            routes.pop(i)
        print(f"[fixes_batch6] ✅ /api/ai/ask: {len(idx)-1} rota(s) antiga(s) removida(s), v4 ativa")
    else:
        print(f"[fixes_batch6] /api/ai/ask: {len(idx)} rota(s) (ok)")


_b6v2_fix_ask_route()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Fix layout: retira widget do interior do <h4>, insere como col-12 próprio
# ─────────────────────────────────────────────────────────────────────────────

_WIDGET_B6V2 = r"""{% if current_client %}
<div class="card mb-3" id="augurCard" style="border:1px solid var(--mc-border);"><!-- _b6v2AugurWidget -->
  <div class="card-body p-0">
    <div class="d-flex align-items-center gap-2 p-3" style="border-bottom:1px solid var(--mc-border);">
      <div style="width:34px;height:34px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden;">
        <img src="/static/augur_logo_v3.png" alt="Augur" style="width:24px;height:24px;object-fit:contain;">
      </div>
      <div style="flex:1;">
        <div class="fw-bold" style="font-size:.92rem;">Augur <span id="augurSessaoTitulo" style="font-weight:400;font-size:.78rem;color:var(--mc-muted);margin-left:.5rem;"></span></div>
        <div class="muted" style="font-size:.7rem;">Consultor financeiro inteligente</div>
      </div>
      <button class="btn btn-sm btn-outline-secondary" onclick="augurNovaConversa()" style="font-size:.75rem;">✏️ Nova conversa</button>
    </div>
    <div style="display:flex;height:460px;overflow:hidden;">
      <div id="augurSidebar" style="display:none;width:210px;border-right:1px solid var(--mc-border);overflow-y:auto;padding:.5rem;background:#f8f9fa;flex-shrink:0;">
        <div style="font-size:.7rem;font-weight:600;color:var(--mc-muted);padding:.25rem .5rem;margin-bottom:.25rem;letter-spacing:.05em;">CONVERSAS</div>
        <div id="augurSessaoLista"></div>
      </div>
      <div style="flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden;">
        <div id="augurChatArea" style="flex:1;overflow-y:auto;padding:1rem 1.25rem;display:flex;flex-direction:column;gap:.75rem;background:#fafafa;">
          <div id="augurLoading" style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">
            <div class="spinner-border spinner-border-sm me-2" role="status"></div>Carregando...
          </div>
        </div>
        <div id="augurAnexoPreview" style="display:none;padding:.5rem 1rem;background:#f0f9ff;border-top:1px solid #bae6fd;font-size:.78rem;">
          <div class="d-flex align-items-center gap-2">
            <span id="augurAnexoNome" style="flex:1;"></span>
            <button class="btn btn-sm btn-outline-danger" style="padding:.1rem .4rem;font-size:.7rem;" onclick="removerAnexo()">✕</button>
          </div>
        </div>
        <div id="augurSuggestions" class="d-flex gap-2 flex-wrap px-3 py-2" style="border-top:1px solid var(--mc-border);background:#fff;">
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Meu caixa está apertado. O que faço?')">💸 Caixa apertado</button>
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Como posso melhorar meu score?')">📈 Melhorar score</button>
          <button class="btn btn-outline-secondary btn-sm" style="font-size:.73rem;" onclick="augurSetQ('Qual crédito faz sentido para minha situação?')">🏦 Crédito certo</button>
        </div>
        <div class="d-flex gap-2 p-3 align-items-end" style="border-top:1px solid var(--mc-border);background:#fff;">
          <div>
            <input type="file" id="augurFileInput" style="display:none;" multiple
                   accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.csv,.xlsx,.xls"
                   onchange="selecionarAnexo(this)">
            <button class="btn btn-outline-secondary" style="border-radius:10px;padding:.45rem .65rem;font-size:.8rem;"
                    onclick="document.getElementById('augurFileInput').click()" title="Anexar arquivos">📎</button>
          </div>
          <textarea id="augurInput" class="form-control" rows="2" placeholder="Pergunte ao Augur..."
            style="font-size:.86rem;resize:none;border-radius:10px;"
            onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurSend();}"></textarea>
          <button class="btn btn-primary" onclick="augurSend()" id="augurBtn"
                  style="border-radius:10px;align-self:flex-end;min-width:80px;font-size:.8rem;padding:.45rem .8rem;">Enviar</button>
        </div>
      </div>
    </div>
  </div>
</div>
<style>
  .aug-msg{display:flex;gap:.5rem;max-width:100%;}.aug-msg.user{flex-direction:row-reverse;}
  .aug-bubble{max-width:85%;padding:.6rem .9rem;border-radius:14px;font-size:.84rem;line-height:1.55;white-space:pre-wrap;word-break:break-word;}
  .aug-bubble.user{background:var(--mc-primary);color:#fff;border-radius:14px 14px 4px 14px;}
  .aug-bubble.assistant{background:#fff;border:1px solid var(--mc-border);border-radius:14px 14px 14px 4px;color:var(--mc-text);}
  .aug-avatar{width:28px;height:28px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;align-self:flex-end;}
  .aug-avatar.user{background:var(--mc-primary);color:#fff;}.aug-avatar.assistant{background:#1a1a1a;overflow:hidden;}
  .aug-meta{font-size:.68rem;color:var(--mc-muted);margin-top:.25rem;}
  .aug-feedback{display:flex;gap:.3rem;margin-top:.35rem;}
  .aug-typing{display:flex;gap:4px;align-items:center;padding:.5rem .8rem;}
  .aug-typing span{width:7px;height:7px;border-radius:50%;background:var(--mc-muted);animation:augBounce 1.2s infinite;}
  .aug-typing span:nth-child(2){animation-delay:.2s;}.aug-typing span:nth-child(3){animation-delay:.4s;}
  @keyframes augBounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
  .aug-sessao-item{padding:.35rem .5rem;border-radius:8px;cursor:pointer;font-size:.75rem;color:var(--mc-text);margin-bottom:.2rem;line-height:1.3;word-break:break-word;}
  .aug-sessao-item:hover{background:var(--mc-border);}.aug-sessao-item.ativa{background:var(--mc-primary);color:#fff;}
</style>
<script>
(function(){
  let _sessaoAtual = null;
  let _augurAnexos = [];

  function _sb(show){ const s=document.getElementById('augurSidebar'); if(s) s.style.display=show?'block':'none'; }

  async function augurCarregarSessoes() {
    try {
      const r = await fetch('/api/ai/sessoes');
      if (!r.ok) { if(!_sessaoAtual) augurNovaConversa(); return; }
      const d = await r.json();
      const lista = document.getElementById('augurSessaoLista');
      if (!lista) return;
      lista.innerHTML = '';
      if (!d.sessoes || d.sessoes.length === 0) { _sb(false); if(!_sessaoAtual) augurNovaConversa(); return; }
      _sb(true);
      d.sessoes.forEach(s => {
        const el = document.createElement('div');
        el.className = 'aug-sessao-item' + (_sessaoAtual === s.id ? ' ativa' : '');
        el.dataset.id = s.id;
        el.innerHTML = '<div style="font-weight:500;">'+_esc(s.titulo)+'</div><div style="font-size:.65rem;opacity:.7;">'+s.updated_at+'</div>';
        el.onclick = () => augurCarregarSessao(s.id, s.titulo);
        el.ondblclick = () => augurRenomearSessao(s.id, s.titulo, el);
        lista.appendChild(el);
      });
      if (!_sessaoAtual && d.sessoes.length > 0) augurCarregarSessao(d.sessoes[0].id, d.sessoes[0].titulo);
    } catch(e) { console.error('[augur]', e); if(!_sessaoAtual) augurNovaConversa(); }
  }

  async function augurCarregarSessao(id, titulo) {
    _sessaoAtual = id;
    document.getElementById('augurSessaoTitulo').textContent = titulo || '';
    document.querySelectorAll('.aug-sessao-item').forEach(el => el.classList.toggle('ativa', parseInt(el.dataset.id)===id));
    const area = document.getElementById('augurChatArea');
    area.innerHTML = '<div style="text-align:center;padding:1rem 0;"><div class="spinner-border spinner-border-sm"></div></div>';
    try {
      const r = await fetch('/api/ai/sessoes/'+id+'/mensagens');
      const d = await r.json();
      area.innerHTML = '';
      if (!d.mensagens || d.mensagens.length === 0) {
        area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nenhuma mensagem ainda.</div>';
        document.getElementById('augurSuggestions').style.display = 'flex'; return;
      }
      document.getElementById('augurSuggestions').style.display = 'none';
      d.mensagens.forEach(m => _renderMsg(m.role, m.content, m.id, m.hora, false));
      _scrollBot();
    } catch(e) { area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Erro ao carregar.</div>'; }
  }

  window.augurNovaConversa = function() {
    _sessaoAtual = null;
    document.getElementById('augurSessaoTitulo').textContent = '';
    document.getElementById('augurChatArea').innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;" data-placeholder="1">Olá! Como posso ajudar?</div>';
    document.getElementById('augurSuggestions').style.display = 'flex';
    document.getElementById('augurInput').value = '';
    document.getElementById('augurInput').focus();
    _augurAnexos = [];
    document.getElementById('augurAnexoPreview').style.display = 'none';
    document.querySelectorAll('.aug-sessao-item').forEach(el => el.classList.remove('ativa'));
  };

  async function augurRenomearSessao(id, tituloAtual, el) {
    const novo = prompt('Renomear conversa:', tituloAtual);
    if (!novo || novo.trim() === tituloAtual) return;
    try {
      const r = await fetch('/api/ai/sessoes/'+id+'/renomear', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:novo.trim()})});
      const d = await r.json();
      if (d.ok) { el.querySelector('div').textContent = d.titulo; if(_sessaoAtual===id) document.getElementById('augurSessaoTitulo').textContent=d.titulo; }
    } catch(e) {}
  }

  window.augurSend = async function() {
    const input = document.getElementById('augurInput');
    const q = (input.value||'').trim();
    if (!q && _augurAnexos.length===0) return;
    const btn = document.getElementById('augurBtn');
    btn.disabled=true; btn.textContent='...'; input.value='';
    document.getElementById('augurSuggestions').style.display='none';
    const hora = new Date().toTimeString().slice(0,5);
    const lbl = _augurAnexos.length>0 ? ' [📎 '+_augurAnexos.map(a=>a.name).join(', ')+']' : '';
    _renderMsg('user', q+lbl, null, hora, true);
    _showTyping();
    const payload = {question: q||'(Analise os arquivos anexados)', session_id: _sessaoAtual||0};
    if (_augurAnexos.length>0) payload.attachments = _augurAnexos;
    _augurAnexos=[];
    document.getElementById('augurAnexoPreview').style.display='none';
    try {
      const r = await fetch('/api/ai/ask', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const d = await r.json();
      _hideTyping();
      if (d.session_id) {
        const isNew = !_sessaoAtual;
        _sessaoAtual = d.session_id;
        if (d.session_titulo) document.getElementById('augurSessaoTitulo').textContent = d.session_titulo;
        if (isNew) augurCarregarSessoes();
        else { const el=document.querySelector('.aug-sessao-item[data-id="'+d.session_id+'"] div'); if(el&&d.session_titulo) el.textContent=d.session_titulo; }
      }
      if (d.precisa_creditos) _renderMsg('assistant','💳 Saldo insuficiente.',null,hora,true);
      else if (d.error||!d.response) _renderMsg('assistant','⚠️ '+(d.error||'Erro ao processar.'),null,hora,true);
      else _renderMsg('assistant', d.response, d.msg_id, hora, true);
    } catch(e) { _hideTyping(); _renderMsg('assistant','⚠️ Erro de conexão.',null,null,true); }
    finally { btn.disabled=false; btn.textContent='Enviar'; input.focus(); }
  };

  function _renderMsg(role, content, msgId, hora, animate) {
    const area = document.getElementById('augurChatArea');
    const ph = area.querySelector('[data-placeholder]'); if(ph) ph.remove();
    const wrap = document.createElement('div'); wrap.className='aug-msg '+role;
    const av = role==='user' ? '<div class="aug-avatar user">EU</div>' : '<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div>';
    const fb = role==='assistant'&&msgId ? '<div class="aug-feedback"><button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;" onclick="augurFeedback('+msgId+',true,this)">👍</button><button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;" onclick="augurFeedback('+msgId+',false,this)">👎</button></div>' : '';
    wrap.innerHTML = av+'<div><div class="aug-bubble '+role+'">'+_esc(content)+'</div>'+(hora?'<div class="aug-meta">'+hora+'</div>':'')+fb+'</div>';
    if(animate) wrap.style.opacity='0';
    area.appendChild(wrap);
    if(animate) setTimeout(()=>{wrap.style.transition='opacity .3s';wrap.style.opacity='1';},10);
    _scrollBot();
  }
  function _showTyping(){ const a=document.getElementById('augurChatArea'),el=document.createElement('div'); el.className='aug-msg assistant'; el.id='aug-typing'; el.innerHTML='<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div><div class="aug-bubble assistant"><div class="aug-typing"><span></span><span></span><span></span></div></div>'; a.appendChild(el); _scrollBot(); }
  function _hideTyping(){ const el=document.getElementById('aug-typing'); if(el) el.remove(); }
  function _scrollBot(){ const a=document.getElementById('augurChatArea'); if(a) a.scrollTop=a.scrollHeight; }
  function _esc(t){ return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function _atualizarPreview(){
    const p=document.getElementById('augurAnexoPreview'), n=document.getElementById('augurAnexoNome');
    if(_augurAnexos.length===0){p.style.display='none';}else{n.textContent=_augurAnexos.map(a=>'📎 '+a.name).join('  ');p.style.display='block';}
  }
  window.selecionarAnexo = async function(input) {
    for(const file of Array.from(input.files)){
      if(file.size>10*1024*1024){alert('Muito grande: '+file.name);continue;}
      const ext=file.name.split('.').pop().toLowerCase();
      if(ext==='csv'||ext==='txt'){
        const t=await file.text();
        _augurAnexos.push({type:'csv',data:t.slice(0,50000),name:file.name});
      } else if(ext==='xlsx'||ext==='xls'){
        alert('⚠️ Excel binário pode não ser lido corretamente. Recomenda-se salvar como CSV antes de enviar.\n\nVamos tentar mesmo assim...');
        const t=await file.text();
        _augurAnexos.push({type:'csv',data:t.slice(0,50000),name:file.name+'(excel-texto)'});
      } else if(ext==='pdf'){
        const b=await new Promise(r=>{const rd=new FileReader();rd.onload=e=>r(e.target.result.split(',')[1]);rd.readAsDataURL(file)});
        _augurAnexos.push({type:'pdf',data:b,name:file.name});
      } else if(['png','jpg','jpeg','gif','webp'].includes(ext)){
        const m='image/'+(ext==='jpg'?'jpeg':ext);
        const b=await new Promise(r=>{const rd=new FileReader();rd.onload=e=>r(e.target.result.split(',')[1]);rd.readAsDataURL(file)});
        _augurAnexos.push({type:m,data:b,name:file.name});
      } else alert('Tipo não suportado: '+file.name);
    }
    input.value=''; _atualizarPreview();
  };
  window.removerAnexo=function(){_augurAnexos=[];document.getElementById('augurAnexoPreview').style.display='none';document.getElementById('augurFileInput').value='';};
  window.augurSetQ=function(q){document.getElementById('augurInput').value=q;document.getElementById('augurInput').focus();};
  window.augurFeedback=async function(msgId,positive,btn){try{await fetch('/api/ai/feedback/'+msgId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({positive})});const w=btn.closest('.aug-feedback');if(w)w.innerHTML=positive?'<span style="font-size:.75rem;color:#16a34a;">✅ Obrigado!</span>':'<span style="font-size:.75rem;color:#dc2626;">Vamos melhorar!</span>';}catch(e){}};
  window.augurCarregarSessoes = augurCarregarSessoes;
  augurCarregarSessoes();
})();
</script>

<div class="card mb-3" id="baseConhecimentoCard" style="border:1px solid var(--mc-border);">
  <div class="card-body p-0">
    <div class="d-flex align-items-center gap-2 p-3" style="border-bottom:1px solid var(--mc-border);">
      <div style="font-size:1.1rem;">📚</div>
      <div style="flex:1;">
        <div class="fw-bold" style="font-size:.92rem;">Base de Conhecimento</div>
        <div class="muted" style="font-size:.7rem;">Documentos que o Augur usa para responder suas perguntas</div>
      </div>
      <button class="btn btn-sm btn-outline-primary" onclick="baseToggleForm()" style="font-size:.75rem;">+ Adicionar</button>
    </div>
    <div id="baseForm" style="display:none;padding:1rem;border-bottom:1px solid var(--mc-border);background:#f8fafc;">
      <div class="row g-2">
        <div class="col-md-6">
          <label class="form-label small fw-semibold">Nome do documento</label>
          <input type="text" id="baseNome" class="form-control form-control-sm" placeholder="Ex: Fluxo de Caixa Janeiro 2026">
        </div>
        <div class="col-md-6">
          <label class="form-label small fw-semibold">Descrição (opcional)</label>
          <input type="text" id="baseDescricao" class="form-control form-control-sm" placeholder="Ex: Planilha de entradas e saídas">
        </div>
        <div class="col-12">
          <label class="form-label small fw-semibold">Arquivo (CSV recomendado; PDF, imagem também aceitos)</label>
          <input type="file" id="baseArquivo" class="form-control form-control-sm"
                 accept=".pdf,.csv,.txt,.png,.jpg,.jpeg">
          <div class="form-text text-warning">⚠️ Arquivos Excel (.xlsx/.xls) não são suportados aqui. Exporte como CSV primeiro.</div>
        </div>
        <div class="col-12 d-flex gap-2">
          <button class="btn btn-primary btn-sm" onclick="baseSalvar()">Salvar</button>
          <button class="btn btn-outline-secondary btn-sm" onclick="baseToggleForm()">Cancelar</button>
        </div>
        <div id="baseFeedback" class="col-12" style="display:none;"></div>
      </div>
    </div>
    <div id="baseDocLista" style="padding:.75rem 1rem;max-height:180px;overflow-y:auto;">
      <div class="muted small">Carregando...</div>
    </div>
  </div>
</div>

<script>
(function(){
  async function baseCarregar() {
    try {
      const r = await fetch('/api/base-conhecimento');
      const d = await r.json();
      const lista = document.getElementById('baseDocLista');
      if (!lista) return;
      if (!d.docs || d.docs.length === 0) {
        lista.innerHTML = '<div class="muted small">Nenhum documento ainda. Adicione arquivos para o Augur usar.</div>';
        return;
      }
      lista.innerHTML = d.docs.map(doc =>
        '<div class="d-flex align-items-center gap-2 py-2" style="border-bottom:1px solid var(--mc-border);">' +
        '<div style="flex:1;"><div class="fw-semibold" style="font-size:.83rem;">' + doc.nome + '</div>' +
        (doc.descricao ? '<div class="muted" style="font-size:.72rem;">' + doc.descricao + '</div>' : '') +
        '<div class="muted" style="font-size:.68rem;">' + doc.tipo + ' · ' + doc.created_at + '</div></div>' +
        '<button class="btn btn-sm btn-outline-danger" style="padding:.1rem .4rem;font-size:.7rem;" onclick="baseDeletar(' + doc.id + ',this)">🗑️</button></div>'
      ).join('');
    } catch(e) {
      const lista = document.getElementById('baseDocLista');
      if (lista) lista.innerHTML = '<div class="muted small">Erro ao carregar.</div>';
    }
  }
  window.baseToggleForm = function() {
    const f = document.getElementById('baseForm');
    if (f) f.style.display = f.style.display === 'none' ? 'block' : 'none';
  };
  window.baseSalvar = async function() {
    const nome = (document.getElementById('baseNome').value||'').trim();
    const descricao = (document.getElementById('baseDescricao').value||'').trim();
    const arquivo = document.getElementById('baseArquivo').files[0];
    const fb = document.getElementById('baseFeedback');
    if (!nome || !arquivo) {
      fb.style.display='block';
      fb.innerHTML='<div class="alert alert-warning alert-sm py-1 mb-0">Nome e arquivo são obrigatórios.</div>';
      return;
    }
    fb.style.display='block';
    fb.innerHTML='<div class="alert alert-info py-1 mb-0">Processando...</div>';
    try {
      let conteudo='', tipo=arquivo.name.split('.').pop().toLowerCase();
      if(['csv','txt'].includes(tipo)){
        conteudo = await arquivo.text();
      } else if(tipo==='pdf'){
        conteudo = await new Promise(res=>{const rd=new FileReader();rd.onload=e=>res(e.target.result.split(',')[1]);rd.readAsDataURL(arquivo)});
        tipo='pdf_base64';
      } else {
        conteudo = await new Promise(res=>{const rd=new FileReader();rd.onload=e=>res(e.target.result.split(',')[1]);rd.readAsDataURL(arquivo)});
        tipo='imagem_base64';
      }
      const r = await fetch('/api/base-conhecimento/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nome,descricao,tipo,conteudo})});
      const d = await r.json();
      if(d.ok){
        fb.innerHTML='<div class="alert alert-success py-1 mb-0">✅ Documento salvo!</div>';
        document.getElementById('baseNome').value='';
        document.getElementById('baseDescricao').value='';
        document.getElementById('baseArquivo').value='';
        baseCarregar();
        setTimeout(()=>{baseToggleForm();fb.style.display='none';},1500);
      } else {
        fb.innerHTML='<div class="alert alert-danger py-1 mb-0">'+(d.erro||'Erro ao salvar.')+'</div>';
      }
    } catch(e){fb.innerHTML='<div class="alert alert-danger py-1 mb-0">Erro ao processar arquivo.</div>';}
  };
  window.baseDeletar = async function(id,btn){
    if(!confirm('Remover este documento?')) return;
    try{await fetch('/api/base-conhecimento/'+id,{method:'DELETE'});baseCarregar();}catch(e){}
  };
  baseCarregar();
})();
</script>
{% endif %}"""


def _b6v2_fix_augur_layout() -> None:
    _dash = TEMPLATES.get("dashboard.html", "")
    if not _dash:
        print("[fixes_batch6] dashboard.html nao encontrado")
        return
    if "_b6v2AugurWidget" in _dash:
        print("[fixes_batch6] Augur widget v2 ja aplicado")
        return

    # Passo 1: limpa qualquer widget injetado dentro do <h4 class="mb-1">
    _h4_open = '<h4 class="mb-1">'
    _painel = 'Painel de Saúde Financeira'
    _pos_h4 = _dash.find(_h4_open)
    _pos_painel = _dash.find(_painel, _pos_h4) if _pos_h4 != -1 else -1

    if _pos_h4 != -1 and _pos_painel > _pos_h4 + len(_h4_open):
        _dash = _dash[:_pos_h4 + len(_h4_open)] + _dash[_pos_painel:]
        print("[fixes_batch6] h4 limpa (widget removido do interior)")
    else:
        print("[fixes_batch6] h4 sem widget injetado (ok)")

    # Passo 2: insere widget como col-12 próprio antes do vis-score-block
    _vs_tag = '<div class="col-12" id="vis-score-block">'
    _vs_pos = _dash.find(_vs_tag)
    if _vs_pos == -1:
        print("[fixes_batch6] vis-score-block nao encontrado no dashboard")
        return

    _dash = (
        _dash[:_vs_pos]
        + '<div class="col-12 mb-3">\n'
        + _WIDGET_B6V2.strip()
        + '\n</div>\n  '
        + _dash[_vs_pos:]
    )

    if "_b6v2AugurWidget" in _dash:
        TEMPLATES["dashboard.html"] = _dash
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping = TEMPLATES
        print("[fixes_batch6] ✅ Augur widget v2 posicionado corretamente (col-12 proprio)")
    else:
        print("[fixes_batch6] ⚠️ _b6v2AugurWidget nao encontrado apos insercao")


_b6v2_fix_augur_layout()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integra Documents (aba Documentos) ao contexto do Augur
# ─────────────────────────────────────────────────────────────────────────────

def _b6v2_patch_documentos() -> None:
    global _enriquecer_client_data
    if getattr(_enriquecer_client_data, '_b6v2docs', False):
        print("[fixes_batch6] Documents: ja patcheado")
        return
    _orig_enr = _enriquecer_client_data

    def _enriquecer_com_docs(session, company_id, client_id, client, client_data):
        result = _orig_enr(session, company_id, client_id, client, client_data)
        try:
            from sqlmodel import select as _sel_d
            docs = session.exec(
                _sel_d(Document)
                .where(
                    Document.company_id == company_id,
                    Document.client_id == client_id,
                    Document.status != "rascunho",
                )
                .order_by(Document.updated_at.desc())
                .limit(5)
            ).all()
            if docs:
                result["documentos_aba"] = [
                    {
                        "titulo": d.title,
                        "conteudo": (d.content or "")[:2000],
                        "data": str(d.updated_at)[:10],
                    }
                    for d in docs if d.content
                ]
        except Exception as _e_docs:
            print(f"[fixes_batch6] Documents patch erro: {_e_docs}")
        return result

    _enriquecer_com_docs._b6v2docs = True
    _enriquecer_client_data = _enriquecer_com_docs
    print("[fixes_batch6] ✅ Documents (aba Documentos) integrados ao contexto do Augur")


_b6v2_patch_documentos()


def _b6v2_patch_format_ctx() -> None:
    try:
        import ai_assistant.assistant as _ast_b6v2
        if getattr(_ast_b6v2._format_client_context, '_b6v2ctx', False):
            print("[fixes_batch6] _format_client_context v2: ja patcheado")
            return
        _orig_fmt = _ast_b6v2._format_client_context

        def _fmt_v2(client_data: dict) -> str:
            ctx = _orig_fmt(client_data)
            docs = client_data.get("documentos_aba", [])
            if docs and "DOCUMENTOS DO CLIENTE" not in ctx:
                ctx += "\n\n=== DOCUMENTOS DO CLIENTE (aba Documentos) ==="
                ctx += "\nUse estes documentos para enriquecer suas respostas quando relevante."
                for d in docs:
                    ctx += f"\n\n--- {d['titulo']} ({d.get('data', '')}) ---\n{d['conteudo'][:2000]}"
            return ctx

        _fmt_v2._b6v2ctx = True
        _ast_b6v2._format_client_context = _fmt_v2
        print("[fixes_batch6] ✅ _format_client_context patcheada com documentos_aba")
    except Exception as _e_fmt:
        print(f"[fixes_batch6] _format_client_context v2 erro: {_e_fmt}")


_b6v2_patch_format_ctx()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Base de Conhecimento: garante que _format_client_context inclui BC
# ─────────────────────────────────────────────────────────────────────────────

def _b6_fix_base_conhecimento() -> None:
    try:
        import ai_assistant.assistant as _ast_b6
        if getattr(_ast_b6._format_client_context, '_b6kb', False):
            print("[fixes_batch6] base conhecimento: ja patcheado")
            return
        _orig = _ast_b6._format_client_context

        def _fmt_b6(client_data: dict) -> str:
            ctx = _orig(client_data)
            base = client_data.get("base_conhecimento", [])
            if base and "BASE DE CONHECIMENTO DO CLIENTE" not in ctx:
                ctx += "\n\n=== BASE DE CONHECIMENTO DO CLIENTE ==="
                ctx += "\nDocumentos fornecidos. Use o conteudo abaixo para responder perguntas sobre eles."
                for doc in base:
                    ctx += f"\n\n--- {doc.get('nome','Documento')} ({doc.get('data','')}) ---"
                    if doc.get('descricao'):
                        ctx += f"\nDescrição: {doc['descricao']}"
                    ctx += f"\n{doc.get('conteudo','')[:2500]}"
            return ctx

        _fmt_b6._b6kb = True
        _ast_b6._format_client_context = _fmt_b6
        print("[fixes_batch6] ✅ _format_client_context patcheada com base de conhecimento")
    except Exception as e:
        print(f"[fixes_batch6] base conhecimento erro: {e}")


_b6_fix_base_conhecimento()

print("[fixes_batch6] ✅ Batch 6 v2 aplicado")
