# ============================================================================
# PATCH — Fix JS Augur v4: sessões não desaparecem
# ============================================================================
# Problema: augurCarregarSessoes() após envio de mensagem substituía
# o chat atual pela primeira sessão da lista (race condition).
# Solução: separar "atualizar lista" de "carregar sessão".
# DEPLOY: adicione ao final do app.py (após ui_augur_sessoes_base.py)
# ============================================================================

_AUGUR_JS_FIX = r"""
<script>
// Fix Augur v4 — corrige sessões desaparecendo
(function(){
  // Aguarda o widget carregar
  function _fixAugur() {
    if (typeof augurNovaConversa === 'undefined') {
      setTimeout(_fixAugur, 200);
      return;
    }

    // Sobrescreve augurSend para não recarregar sessão ativa
    const _origSend = window.augurSend;
    window.augurSend = async function() {
      const input = document.getElementById('augurInput');
      const q = (input.value || '').trim();
      if (!q && !window._augurAnexoGlobal) return;

      const btn = document.getElementById('augurBtn');
      btn.disabled = true;
      btn.textContent = '...';
      input.value = '';
      document.getElementById('augurSuggestions').style.display = 'none';

      const hora = new Date().toTimeString().slice(0,5);
      window._augurRenderMsgGlobal('user', q, null, hora, true);
      window._augurShowTypingGlobal();

      // Pega sessao atual do DOM
      const sessaoAtiva = document.querySelector('.aug-sessao-item.ativa');
      const sessaoId = sessaoAtiva ? parseInt(sessaoAtiva.dataset.id) : 0;

      const payload = { question: q || '(Analise o arquivo)', session_id: sessaoId || 0 };

      try {
        const r = await fetch('/api/ai/ask', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload),
        });
        const d = await r.json();
        window._augurHideTypingGlobal();

        // Atualiza sidebar SEM substituir o chat atual
        if (d.session_id) {
          _atualizarSidebarSessao(d.session_id, d.session_titulo || 'Nova conversa');
        }

        if (d.precisa_creditos) {
          window._augurRenderMsgGlobal('assistant', '💳 Saldo insuficiente.', null, hora, true);
        } else if (d.error || !d.response) {
          window._augurRenderMsgGlobal('assistant', '⚠️ ' + (d.error || 'Erro.'), null, hora, true);
        } else {
          window._augurRenderMsgGlobal('assistant', d.response, d.msg_id, hora, true);
        }
      } catch(e) {
        window._augurHideTypingGlobal();
        window._augurRenderMsgGlobal('assistant', '⚠️ Erro de conexão.', null, null, true);
      } finally {
        btn.disabled = false;
        btn.textContent = 'Enviar';
        input.focus();
      }
    };

    // Função para atualizar/adicionar sessão na sidebar sem recarregar tudo
    function _atualizarSidebarSessao(id, titulo) {
      const lista = document.getElementById('augurSessaoLista');
      if (!lista) return;

      // Remove mensagem "Nenhuma conversa"
      const vazio = lista.querySelector('[data-vazio]');
      if (vazio) vazio.remove();

      // Verifica se já existe na lista
      let el = lista.querySelector(`[data-id="${id}"]`);
      if (!el) {
        // Cria novo item e adiciona no topo
        el = document.createElement('div');
        el.className = 'aug-sessao-item';
        el.dataset.id = id;
        el.onclick = () => _carregarSessaoSafe(id, titulo);
        el.ondblclick = () => _renomearSessaoSafe(id, titulo, el);
        lista.insertBefore(el, lista.firstChild);
      }

      // Atualiza conteúdo
      const hoje = new Date().toISOString().slice(0,10);
      el.innerHTML = `<div style="font-weight:500;">${_escHtml(titulo)}</div><div style="font-size:.65rem;opacity:.7;">${hoje}</div>`;

      // Marca como ativa
      lista.querySelectorAll('.aug-sessao-item').forEach(x => x.classList.remove('ativa'));
      el.classList.add('ativa');

      // Atualiza título no header
      const tituloEl = document.getElementById('augurSessaoTitulo');
      if (tituloEl) tituloEl.textContent = titulo;
    }

    function _carregarSessaoSafe(id, titulo) {
      // Marca como ativa
      document.querySelectorAll('.aug-sessao-item').forEach(x => x.classList.remove('ativa'));
      const el = document.querySelector(`.aug-sessao-item[data-id="${id}"]`);
      if (el) el.classList.add('ativa');

      const tituloEl = document.getElementById('augurSessaoTitulo');
      if (tituloEl) tituloEl.textContent = titulo;

      // Carrega mensagens
      const area = document.getElementById('augurChatArea');
      area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);padding:1rem;"><div class="spinner-border spinner-border-sm"></div></div>';

      fetch('/api/ai/sessoes/' + id + '/mensagens')
        .then(r => r.json())
        .then(d => {
          area.innerHTML = '';
          if (!d.mensagens || d.mensagens.length === 0) {
            area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem;">Nenhuma mensagem.</div>';
            return;
          }
          document.getElementById('augurSuggestions').style.display = 'none';
          d.mensagens.forEach(m => window._augurRenderMsgGlobal(m.role, m.content, m.id, m.hora, false));
          area.scrollTop = area.scrollHeight;
        })
        .catch(() => {
          area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);padding:2rem;">Erro ao carregar.</div>';
        });
    }

    async function _renomearSessaoSafe(id, tituloAtual, el) {
      const novo = prompt('Renomear conversa:', tituloAtual);
      if (!novo || novo.trim() === tituloAtual) return;
      try {
        const r = await fetch('/api/ai/sessoes/' + id + '/renomear', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({titulo: novo.trim()}),
        });
        const d = await r.json();
        if (d.ok) {
          el.querySelector('div').textContent = d.titulo;
          const tituloEl = document.getElementById('augurSessaoTitulo');
          const elAtivo = document.querySelector('.aug-sessao-item.ativa');
          if (tituloEl && elAtivo && parseInt(elAtivo.dataset.id) === id) {
            tituloEl.textContent = d.titulo;
          }
        }
      } catch(e) {}
    }

    function _escHtml(t) { return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    // Expõe funções necessárias globalmente
    window._augurRenderMsgGlobal = window._augurRenderMsgGlobal || function(role, content, msgId, hora, animate) {
      const area = document.getElementById('augurChatArea');
      if (!area) return;
      const placeholder = area.querySelector('[data-placeholder]');
      if (placeholder) placeholder.remove();
      const wrap = document.createElement('div');
      wrap.className = 'aug-msg ' + role;
      const avatarHtml = role === 'user'
        ? '<div class="aug-avatar user">EU</div>'
        : '<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div>';
      const feedbackHtml = role === 'assistant' && msgId ? `
        <div class="aug-feedback">
          <button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;" onclick="augurFeedback(${msgId},true,this)">👍</button>
          <button class="btn btn-xs btn-outline-secondary" style="padding:.1rem .4rem;font-size:.7rem;" onclick="augurFeedback(${msgId},false,this)">👎</button>
        </div>` : '';
      wrap.innerHTML = avatarHtml + `<div><div class="aug-bubble ${role}">${_escHtml(content)}</div>${hora ? `<div class="aug-meta">${hora}</div>` : ''}${feedbackHtml}</div>`;
      if (animate) wrap.style.opacity = '0';
      area.appendChild(wrap);
      if (animate) setTimeout(() => { wrap.style.transition='opacity .3s'; wrap.style.opacity='1'; }, 10);
      area.scrollTop = area.scrollHeight;
    };

    window._augurShowTypingGlobal = window._augurShowTypingGlobal || function() {
      const area = document.getElementById('augurChatArea');
      if (!area) return;
      const el = document.createElement('div');
      el.className = 'aug-msg assistant'; el.id = 'aug-typing';
      el.innerHTML = '<div class="aug-avatar assistant"><img src="/static/augur_logo_v3.png" style="width:20px;height:20px;object-fit:contain;"></div><div class="aug-bubble assistant"><div class="aug-typing"><span></span><span></span><span></span></div></div>';
      area.appendChild(el);
      area.scrollTop = area.scrollHeight;
    };

    window._augurHideTypingGlobal = window._augurHideTypingGlobal || function() {
      const el = document.getElementById('aug-typing');
      if (el) el.remove();
    };

    // Sobrescreve Nova Conversa para preservar sessões na sidebar
    window.augurNovaConversa = function() {
      // Remove destaque ativo mas mantém lista
      document.querySelectorAll('.aug-sessao-item').forEach(x => x.classList.remove('ativa'));
      const tituloEl = document.getElementById('augurSessaoTitulo');
      if (tituloEl) tituloEl.textContent = '';
      const area = document.getElementById('augurChatArea');
      if (area) area.innerHTML = '<div style="text-align:center;color:var(--mc-muted);font-size:.82rem;padding:2rem 0;">Nova conversa iniciada.</div>';
      const sugg = document.getElementById('augurSuggestions');
      if (sugg) sugg.style.display = 'flex';
      const inputEl = document.getElementById('augurInput');
      if (inputEl) { inputEl.value = ''; inputEl.focus(); }
    };

    console.log('[augur_fix] JS de sessões corrigido');
  }

  // Inicia após DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _fixAugur);
  } else {
    setTimeout(_fixAugur, 300);
  }
})();
</script>
"""

# Injeta no dashboard
_dash_fix = TEMPLATES.get("dashboard.html", "")
if _dash_fix and "augur_fix" not in _dash_fix:
    if "{% endblock %}" in _dash_fix:
        _dash_fix = _dash_fix.replace("{% endblock %}", _AUGUR_JS_FIX + "\n{% endblock %}", 1)
        TEMPLATES["dashboard.html"] = _dash_fix
        print("[fix_augur_sessoes_js] ✅ Fix JS injetado no dashboard")

if hasattr(templates_env.loader, "mapping"):
    templates_env.loader.mapping = TEMPLATES

print("[fix_augur_sessoes_js] ✅ Patch completo")
