# ============================================================================
# PATCH — Rebuild completo do dashboard
# ============================================================================
# Substitui o dashboard.html inteiro por uma versão limpa
# que inclui o Augur sem condições problemáticas
# DEPLOY: adicione ao final do app.py
# ============================================================================

_DASHBOARD_CLEAN = r"""
{% extends "base.html" %}
{% block content %}

{# ── Augur ── #}
<div class="row g-3 mb-3">
  <div class="col-12">
    <div class="card" id="augurCard">
      <div class="card-body p-0">
        <div class="d-flex align-items-center gap-2 p-3" style="border-bottom:1px solid var(--mc-border);">
          <div style="width:34px;height:34px;border-radius:10px;background:#1a1a1a;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden;">
            <img src="/static/augur_logo_v3.png" alt="Augur" style="width:24px;height:24px;object-fit:contain;">
          </div>
          <div style="flex:1;">
            <div class="fw-bold" style="font-size:.92rem;">Augur <span id="augurSessaoTitulo" style="font-weight:400;font-size:.78rem;color:var(--mc-muted);margin-left:.5rem;"></span></div>
            <div class="muted" style="font-size:.7rem;">Consultor financeiro inteligente · Vê reuniões, diagnósticos, obras e viabilidades</div>
          </div>
          <button class="btn btn-sm btn-outline-secondary" onclick="augurNovaConversa()" style="font-size:.75rem;">✏️ Nova conversa</button>
        </div>
        <div style="display:flex;height:500px;">
          <div id="augurSidebar" style="width:240px;border-right:1px solid var(--mc-border);overflow-y:auto;padding:.5rem;background:#f8f9fa;flex-shrink:0;">
            <div style="font-size:.68rem;font-weight:700;color:var(--mc-muted);padding:.25rem .5rem;margin-bottom:.25rem;letter-spacing:.06em;">CONVERSAS</div>
            <div id="augurSessaoLista"><div class="muted small" style="padding:.5rem;font-size:.72rem;">Carregando...</div></div>
          </div>
          <div style="flex:1;display:flex;flex-direction:column;min-width:0;">
            <div id="augurChatArea" style="flex:1;overflow-y:auto;padding:1rem 1.25rem;display:flex;flex-direction:column;gap:.75rem;background:#fafafa;">
              <div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;" data-placeholder>Carregando...</div>
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
                <input type="file" id="augurFileInput" style="display:none;" accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,.csv,.xlsx,.xls" onchange="selecionarAnexo(this)">
                <button class="btn btn-outline-secondary" style="border-radius:10px;padding:.45rem .65rem;font-size:.8rem;" onclick="document.getElementById('augurFileInput').click()" title="Anexar">📎</button>
              </div>
              <textarea id="augurInput" class="form-control" rows="2" placeholder="Pergunte ao Augur..." style="font-size:.86rem;resize:none;border-radius:10px;" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurSend();}"></textarea>
              <button class="btn btn-primary" onclick="augurSend()" id="augurBtn" style="border-radius:10px;align-self:flex-end;min-width:80px;font-size:.8rem;padding:.45rem .8rem;">Enviar</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    {# Base de Conhecimento #}
    <div class="card mt-3" id="baseConhecimentoCard">
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
              <label class="form-label small fw-semibold">Arquivo</label>
              <input type="file" id="baseArquivo" class="form-control form-control-sm" accept=".pdf,.csv,.xlsx,.xls,.txt,.png,.jpg,.jpeg">
            </div>
            <div class="col-12 d-flex gap-2">
              <button class="btn btn-primary btn-sm" onclick="baseSalvar()">Salvar</button>
              <button class="btn btn-outline-secondary btn-sm" onclick="baseToggleForm()">Cancelar</button>
            </div>
            <div id="baseFeedback" class="col-12" style="display:none;"></div>
          </div>
        </div>
        <div id="baseDocLista" style="padding:.75rem 1rem;max-height:200px;overflow-y:auto;">
          <div class="muted small">Carregando...</div>
        </div>
      </div>
    </div>
  </div>
</div>

{# ── Painel / conteúdo original ── #}
<div class="row g-3">
  <div class="col-12">
    <div class="card p-4">
      <h4 class="mb-1">Painel de Saúde Financeira</h4>
      <div class="muted">
        {% if role in ["admin","equipe"] %}
          Escritório: <b>{{ current_company.name }}</b>.
          {% if current_client %} Cliente selecionado: <b>{{ current_client.name }}</b>.{% endif %}
        {% else %}
          Bem-vindo(a)! Você vê apenas seus dados e arquivos.
        {% endif %}
      </div>
      {% if role in ["admin","equipe"] %}
      <div class="mt-3 d-flex gap-2">
        <a class="btn btn-outline-primary btn-sm" href="/admin/members">Gerenciar membros</a>
        <a class="btn btn-outline-secondary btn-sm" href="/client/switch">Trocar cliente</a>
      </div>
      {% endif %}
    </div>
  </div>
</div>

<style>
  .aug-msg{display:flex;gap:.5rem;max-width:100%;}
  .aug-msg.user{flex-direction:row-reverse;}
  .aug-bubble{max-width:75%;padding:.6rem .9rem;border-radius:14px;font-size:.84rem;line-height:1.55;white-space:pre-wrap;word-break:break-word;}
  .aug-bubble.user{background:var(--mc-primary);color:#fff;border-radius:14px 14px 4px 14px;}
  .aug-bubble.assistant{background:#fff;border:1px solid var(--mc-border);border-radius:14px 14px 14px 4px;color:var(--mc-text);}
  .aug-avatar{width:28px;height:28px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;align-self:flex-end;}
  .aug-avatar.user{background:var(--mc-primary);color:#fff;}
  .aug-avatar.assistant{background:#1a1a1a;overflow:hidden;}
  .aug-meta{font-size:.68rem;color:var(--mc-muted);margin-top:.25rem;}
  .aug-feedback{display:flex;gap:.3rem;margin-top:.35rem;}
  .aug-typing{display:flex;gap:4px;align-items:center;padding:.5rem .8rem;}
  .aug-typing span{width:7px;height:7px;border-radius:50%;background:var(--mc-muted);animation:augBounce 1.2s infinite;}
  .aug-typing span:nth-child(2){animation-delay:.2s;}
  .aug-typing span:nth-child(3){animation-delay:.4s;}
  @keyframes augBounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}
  .aug-sessao-item{padding:.4rem .6rem;border-radius:8px;cursor:pointer;font-size:.75rem;color:var(--mc-text);margin-bottom:.2rem;line-height:1.3;word-break:break-word;transition:background .15s;}
  .aug-sessao-item:hover{background:rgba(0,0,0,.06);}
  .aug-sessao-item.ativa{background:var(--mc-primary);color:#fff;}
</style>

<script>
(function(){
  const _esc=t=>String(t||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  let _sid=null, _anx=null;

  async function _carregarSessoes(){
    try{
      const r=await fetch('/api/ai/sessoes');
      const d=await r.json();
      const lista=document.getElementById('augurSessaoLista');
      lista.innerHTML='';
      if(!d.sessoes||!d.sessoes.length){
        lista.innerHTML='<div style="font-size:.72rem;color:var(--mc-muted);padding:.5rem;">Nenhuma conversa ainda</div>';
        _novaConversa();
        return;
      }
      d.sessoes.forEach(s=>{
        const el=document.createElement('div');
        el.className='aug-sessao-item'+(_sid===s.id?' ativa':'');
        el.dataset.id=s.id;
        el.innerHTML=`<div style="font-weight:600;">${_esc(s.titulo)}</div><div style="font-size:.65rem;opacity:.6;">${s.updated_at||''}</div>`;
        el.onclick=()=>_abrirSessao(s.id,s.titulo);
        el.ondblclick=()=>_renomear(s.id,s.titulo,el);
        lista.appendChild(el);
      });
      if(!_sid&&d.sessoes.length) _abrirSessao(d.sessoes[0].id,d.sessoes[0].titulo);
    }catch(e){_novaConversa();}
  }

  async function _abrirSessao(id,titulo){
    _sid=id;
    document.getElementById('augurSessaoTitulo').textContent=titulo||'';
    document.querySelectorAll('.aug-sessao-item').forEach(x=>x.classList.toggle('ativa',parseInt(x.dataset.id)===id));
    const area=document.getElementById('augurChatArea');
    area.innerHTML='<div style="text-align:center;padding:1rem;"><div class="spinner-border spinner-border-sm"></div></div>';
    try{
      const r=await fetch('/api/ai/sessoes/'+id+'/mensagens');
      const d=await r.json();
      area.innerHTML='';
      if(!d.mensagens||!d.mensagens.length){area.innerHTML='<div style="text-align:center;color:var(--mc-muted);padding:2rem;">Nenhuma mensagem.</div>';document.getElementById('augurSuggestions').style.display='flex';return;}
      document.getElementById('augurSuggestions').style.display='none';
      d.mensagens.forEach(m=>_renderMsg(m.role,m.content,m.id,m.hora,false));
      _scrollBottom();
    }catch(e){area.innerHTML='<div style="text-align:center;color:var(--mc-muted);padding:2rem;">Erro.</div>';}
  }

  function _novaConversa(){
    _sid=null;
    document.getElementById('augurSessaoTitulo').textContent='';
    document.getElementById('augurChatArea').innerHTML='<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nova conversa iniciada.</div>';
    document.getElementById('augurSuggestions').style.display='flex';
    document.getElementById('augurInput').value='';
    document.getElementById('augurInput').focus();
    _anx=null;
    document.getElementById('augurAnexoPreview').style.display='none';
    document.querySelectorAll('.aug-sessao-item').forEach(x=>x.classList.remove('ativa'));
  }
  window.augurNovaConversa=_novaConversa;

  async function _renomear(id,titulo,el){
    const novo=prompt('Renomear:',titulo);
    if(!novo||novo.trim()===titulo)return;
    const r=await fetch('/api/ai/sessoes/'+id+'/renomear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:novo.trim()})});
    const d=await r.json();
    if(d.ok){el.querySelector('div').textContent=d.titulo;if(_sid===id)document.getElementById('augurSessaoTitulo').textContent=d.titulo;}
  }

  function _adicionarSessao(id,titulo){
    const lista=document.getElementById('augurSessaoLista');
    lista.querySelectorAll('div:not([data-id])').forEach(x=>{if(x.textContent.includes('Nenhuma'))x.remove();});
    if(lista.querySelector('[data-id="'+id+'"]'))return;
    const el=document.createElement('div');
    el.className='aug-sessao-item ativa';
    el.dataset.id=id;
    el.innerHTML='<div style="font-weight:600;">'+_esc(titulo)+'</div><div style="font-size:.65rem;opacity:.6;">'+new Date().toISOString().slice(0,10)+'</div>';
    el.onclick=()=>_abrirSessao(id,titulo);
    el.ondblclick=()=>_renomear(id,titulo,el);
    lista.insertBefore(el,lista.firstChild);
    lista.querySelectorAll('.aug-sessao-item').forEach(x=>x.classList.toggle('ativa',parseInt(x.dataset.id)===id));
  }

  window.augurSend=async function(){
    const input=document.getElementById('augurInput');
    const q=(input.value||'').trim();
    if(!q&&!_anx)return;
    const btn=document.getElementById('augurBtn');
    btn.disabled=true;btn.textContent='...';
    input.value='';
    document.getElementById('augurSuggestions').style.display='none';
    const hora=new Date().toTimeString().slice(0,5);
    _renderMsg('user',q+(_anx?' [📎 '+_anx.name+']':''),null,hora,true);
    _showTyping();
    const payload={question:q||'(Analise o arquivo)',session_id:_sid||0};
    if(_anx)payload.attachments=[_anx];
    _anx=null;document.getElementById('augurAnexoPreview').style.display='none';
    try{
      const r=await fetch('/api/ai/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const d=await r.json();
      _hideTyping();
      if(d.session_id&&!_sid){_sid=d.session_id;document.getElementById('augurSessaoTitulo').textContent=d.session_titulo||'';_adicionarSessao(d.session_id,d.session_titulo||'Nova conversa');}
      if(d.precisa_creditos)_renderMsg('assistant','💳 Saldo insuficiente.',null,hora,true);
      else if(d.error||!d.response)_renderMsg('assistant','⚠️ '+(d.error||'Erro.'),null,hora,true);
      else _renderMsg('assistant',d.response,d.msg_id,hora,true);
    }catch(e){_hideTyping();_renderMsg('assistant','⚠️ Erro de conexão.',null,null,true);}
    finally{btn.disabled=false;btn.textContent='Enviar';input.focus();}
  };

  function _renderMsg(role,content,msgId,hora,animate){
    const area=document.getElementById('augurChatArea');
    area.querySelectorAll('[data-placeholder]').forEach(x=>x.remove());
    const wrap=document.createElement('div');wrap.className='aug-msg '+role;
    const av=role==='user'?'<div class="aug-avatar user">EU</div>':'<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div>';
    const fb=role==='assistant'&&msgId?'<div class="aug-feedback"><button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;" onclick="augurFeedback('+msgId+',true,this)">👍</button><button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;" onclick="augurFeedback('+msgId+',false,this)">👎</button></div>':'';
    wrap.innerHTML=av+'<div><div class="aug-bubble '+role+'">'+_esc(content)+'</div>'+(hora?'<div class="aug-meta">'+hora+'</div>':'')+fb+'</div>';
    if(animate)wrap.style.opacity='0';
    area.appendChild(wrap);
    if(animate)setTimeout(()=>{wrap.style.transition='opacity .3s';wrap.style.opacity='1';},10);
    _scrollBottom();
  }
  function _showTyping(){const area=document.getElementById('augurChatArea');const el=document.createElement('div');el.className='aug-msg assistant';el.id='aug-typing';el.innerHTML='<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div><div class="aug-bubble assistant"><div class="aug-typing"><span></span><span></span><span></span></div></div>';area.appendChild(el);_scrollBottom();}
  function _hideTyping(){const el=document.getElementById('aug-typing');if(el)el.remove();}
  function _scrollBottom(){const a=document.getElementById('augurChatArea');a.scrollTop=a.scrollHeight;}
  window.augurSetQ=function(q){document.getElementById('augurInput').value=q;document.getElementById('augurInput').focus();};
  window.selecionarAnexo=async function(input){
    const file=input.files[0];if(!file)return;
    if(file.size>10*1024*1024){alert('Máximo 10MB.');return;}
    const ext=file.name.split('.').pop().toLowerCase();
    if(['csv','xlsx','xls','txt'].includes(ext)){const txt=await file.text();_anx={type:'csv',data:txt.slice(0,50000),name:file.name};}
    else{const reader=new FileReader();const tipo=ext==='pdf'?'pdf':['png','jpg','jpeg','gif','webp'].includes(ext)?'image/'+(ext==='jpg'?'jpeg':ext):null;if(!tipo){alert('Tipo não suportado.');return;}reader.onload=e=>{_anx={type:tipo,data:e.target.result.split(',')[1],name:file.name};};reader.readAsDataURL(file);}
    document.getElementById('augurAnexoNome').textContent='📎 '+file.name;
    document.getElementById('augurAnexoPreview').style.display='block';
    input.value='';
  };
  window.removerAnexo=function(){_anx=null;document.getElementById('augurAnexoPreview').style.display='none';document.getElementById('augurFileInput').value='';};
  window.augurFeedback=async function(msgId,positive,btn){try{await fetch('/api/ai/feedback/'+msgId,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({positive})});const wrap=btn.closest('.aug-feedback');if(wrap)wrap.innerHTML=positive?'<span style="font-size:.75rem;color:#16a34a;">✅ Obrigado!</span>':'<span style="font-size:.75rem;color:#dc2626;">Vamos melhorar!</span>';}catch(e){}};

  // Base de Conhecimento
  async function _baseCarregar(){
    try{const r=await fetch('/api/base-conhecimento');const d=await r.json();const lista=document.getElementById('baseDocLista');
    if(!d.docs||!d.docs.length){lista.innerHTML='<div class="muted small">Nenhum documento ainda.</div>';return;}
    lista.innerHTML=d.docs.map(doc=>'<div class="d-flex align-items-center gap-2 py-2" style="border-bottom:1px solid var(--mc-border);"><div style="flex:1;"><div class="fw-semibold" style="font-size:.83rem;">'+_esc(doc.nome)+'</div>'+(doc.descricao?'<div class="muted" style="font-size:.72rem;">'+_esc(doc.descricao)+'</div>':'')+'<div class="muted" style="font-size:.68rem;">'+doc.tipo+' · '+doc.created_at+'</div></div><button class="btn btn-sm btn-outline-danger" style="padding:.1rem .4rem;font-size:.7rem;" onclick="baseDeletar('+doc.id+',this)">🗑️</button></div>').join('');
    }catch(e){document.getElementById('baseDocLista').innerHTML='<div class="muted small">Erro.</div>';}}
  window.baseToggleForm=function(){const f=document.getElementById('baseForm');f.style.display=f.style.display==='none'?'block':'none';};
  window.baseSalvar=async function(){
    const nome=document.getElementById('baseNome').value.trim();
    const descricao=document.getElementById('baseDescricao').value.trim();
    const arquivo=document.getElementById('baseArquivo').files[0];
    const fb=document.getElementById('baseFeedback');
    if(!nome||!arquivo){fb.style.display='block';fb.innerHTML='<div class="alert alert-warning py-1 mb-0">Nome e arquivo são obrigatórios.</div>';return;}
    fb.style.display='block';fb.innerHTML='<div class="alert alert-info py-1 mb-0">Processando...</div>';
    try{
      let conteudo='',tipo=arquivo.name.split('.').pop().toLowerCase();
      if(['csv','txt'].includes(tipo)){conteudo=await arquivo.text();}
      else if(['xlsx','xls'].includes(tipo)){conteudo=await arquivo.text();tipo='excel';}
      else{const reader=new FileReader();conteudo=await new Promise(res=>{reader.onload=e=>res(e.target.result.split(',')[1]);reader.readAsDataURL(arquivo);});tipo=tipo==='pdf'?'pdf_base64':'imagem_base64';}
      const r=await fetch('/api/base-conhecimento/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nome,descricao,tipo,conteudo})});
      const d=await r.json();
      if(d.ok){fb.innerHTML='<div class="alert alert-success py-1 mb-0">✅ Documento salvo!</div>';document.getElementById('baseNome').value='';document.getElementById('baseDescricao').value='';document.getElementById('baseArquivo').value='';_baseCarregar();setTimeout(()=>{baseToggleForm();fb.style.display='none';},1500);}
      else{fb.innerHTML='<div class="alert alert-danger py-1 mb-0">'+(d.erro||'Erro.')+'</div>';}
    }catch(e){fb.innerHTML='<div class="alert alert-danger py-1 mb-0">Erro ao processar.</div>';}
  };
  window.baseDeletar=async function(id,btn){if(!confirm('Remover?'))return;try{await fetch('/api/base-conhecimento/'+id,{method:'DELETE'});_baseCarregar();}catch(e){}};

  _carregarSessoes();
  _baseCarregar();
})();
</script>

{% endblock %}
"""

TEMPLATES["dashboard.html"] = _DASHBOARD_CLEAN
if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[dashboard_rebuild] ✅ Dashboard reconstruído com Augur limpo e funcional")
