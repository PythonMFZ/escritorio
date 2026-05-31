# ui_augur_float.py — Botão flutuante do Augur em todas as páginas
# Exec'd no namespace do app.py — injeta widget no base.html via string replacement.
#
# Aparece como botão redondo fixo (bottom-right) em qualquer tela.
# Oculto automaticamente nas páginas que já têm o widget Augur completo.
# Captura screenshot no momento do Enviar — Claude vê exatamente o que o usuário vê.

_AUGUR_FLOAT_HTML = r"""
{% if current_user %}
<div id="augurFloatWrap" style="position:fixed;bottom:1.5rem;right:1.5rem;z-index:9990;display:flex;flex-direction:column;align-items:flex-end;gap:.5rem;">

  <div id="augurFloatPanel" style="display:none;width:360px;background:#fff;border-radius:16px;
    box-shadow:0 8px 32px rgba(0,0,0,.22);overflow:hidden;flex-direction:column;">

    <div style="background:#E07020;color:#fff;padding:.6rem 1rem;display:flex;align-items:center;gap:.5rem;">
      <img src="/static/augur_logo_v3.png" style="width:18px;height:18px;object-fit:contain;"
           onerror="this.style.display='none'">
      <strong style="flex:1;font-size:.88rem;">Augur</strong>
      <button onclick="augurFloatClose()"
        style="background:none;border:none;color:#fff;cursor:pointer;font-size:1rem;line-height:1;padding:0;">✕</button>
    </div>

    <div id="augurFloatMsgs" style="padding:.75rem;min-height:180px;max-height:300px;overflow-y:auto;
      display:flex;flex-direction:column;gap:.5rem;font-size:.83rem;background:#fafafa;">
      <div id="augurFloatPlaceholder" style="color:#aaa;text-align:center;margin:auto;font-size:.8rem;padding:1rem 0;">
        Me pergunte sobre o que você está vendo na tela.
      </div>
    </div>

    <div style="padding:.6rem .75rem;border-top:1px solid #eee;background:#fff;display:flex;gap:.5rem;align-items:flex-end;">
      <textarea id="augurFloatInput" rows="2" placeholder="Pergunte sobre esta tela…"
        style="flex:1;font-size:.8rem;resize:none;border:1px solid #ddd;border-radius:10px;
               padding:.4rem .6rem;outline:none;font-family:inherit;"
        onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();augurFloatSend();}"></textarea>
      <button id="augurFloatSendBtn" onclick="augurFloatSend()"
        style="background:#E07020;color:#fff;border:none;border-radius:10px;padding:.45rem .8rem;
               cursor:pointer;font-size:.8rem;font-weight:600;white-space:nowrap;">Enviar</button>
    </div>
  </div>

  <button id="augurFloatBtn" onclick="augurFloatToggle()"
    style="width:52px;height:52px;border-radius:50%;border:none;background:#E07020;
           box-shadow:0 4px 16px rgba(224,112,32,.45);cursor:pointer;display:flex;
           align-items:center;justify-content:center;transition:transform .15s;"
    title="Perguntar ao Augur"
    onmouseenter="this.style.transform='scale(1.08)'"
    onmouseleave="this.style.transform=''">
    <img src="/static/augur_logo_v3.png" style="width:28px;height:28px;object-fit:contain;"
         onerror="this.style.display='none';this.insertAdjacentText('afterend','🔮')">
  </button>

</div>

<script>
(function(){
  // Esconde nas páginas que já têm o Augur completo (augurCard)
  function _ckHide(){
    if (document.getElementById('augurCard')) {
      var w = document.getElementById('augurFloatWrap');
      if (w) w.style.display = 'none';
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _ckHide);
  } else { _ckHide(); }

  var _open = false;

  window.augurFloatToggle = function() {
    _open = !_open;
    var p = document.getElementById('augurFloatPanel');
    p.style.display = _open ? 'flex' : 'none';
    if (_open) p.style.flexDirection = 'column';
    if (_open) setTimeout(function(){ document.getElementById('augurFloatInput').focus(); }, 50);
  };
  window.augurFloatClose = function() {
    _open = false;
    document.getElementById('augurFloatPanel').style.display = 'none';
  };

  window.augurFloatSend = async function() {
    var input = document.getElementById('augurFloatInput');
    var q = (input.value || '').trim();
    if (!q) return;

    var btn = document.getElementById('augurFloatSendBtn');
    btn.disabled = true;
    btn.textContent = '📸';

    // Screenshot — oculta o widget para não capturá-lo
    var _ss = null;
    var wrap = document.getElementById('augurFloatWrap');
    try {
      if (!window.html2canvas) {
        await new Promise(function(res, rej) {
          var s = document.createElement('script');
          s.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
          s.onload = res; s.onerror = rej;
          document.head.appendChild(s);
        });
      }
      if (wrap) wrap.style.visibility = 'hidden';
      var canvas = await html2canvas(document.body, {
        scale: 0.5, useCORS: true, logging: false, allowTaint: true,
      });
      if (wrap) wrap.style.visibility = '';
      var b64 = canvas.toDataURL('image/jpeg', 0.6).split(',')[1];
      if (b64 && b64.length < 2000000) _ss = {type:'image/jpeg', data:b64, name:'tela.jpg'};
    } catch(_e) {
      if (wrap) wrap.style.visibility = '';
    }

    btn.textContent = '...';
    input.value = '';

    var ph = document.getElementById('augurFloatPlaceholder');
    if (ph) ph.remove();

    var msgs = document.getElementById('augurFloatMsgs');

    var ub = document.createElement('div');
    ub.style.cssText = 'background:#E07020;color:#fff;padding:.35rem .65rem;border-radius:12px 12px 3px 12px;align-self:flex-end;max-width:85%;word-break:break-word;';
    ub.textContent = q + (_ss ? ' [🖥️]' : '');
    msgs.appendChild(ub);

    var tp = document.createElement('div');
    tp.id = '_augurFT';
    tp.style.cssText = 'color:#aaa;font-size:.76rem;';
    tp.textContent = 'Augur está analisando…';
    msgs.appendChild(tp);
    msgs.scrollTop = msgs.scrollHeight;

    try {
      var payload = {question: q};
      if (_ss) payload.attachments = [_ss];
      var r = await fetch('/api/ai/ask', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
      var d = await r.json();
      var t = document.getElementById('_augurFT'); if (t) t.remove();

      var ab = document.createElement('div');
      ab.style.cssText = 'background:#f0f0f0;padding:.35rem .65rem;border-radius:12px 12px 12px 3px;max-width:92%;white-space:pre-wrap;word-break:break-word;';
      ab.textContent = d.response || d.error || 'Erro ao processar.';
      msgs.appendChild(ab);
    } catch(_e) {
      var t2 = document.getElementById('_augurFT'); if (t2) t2.remove();
      var eb = document.createElement('div');
      eb.style.cssText = 'color:#dc2626;font-size:.78rem;';
      eb.textContent = '⚠️ Erro de conexão.';
      msgs.appendChild(eb);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Enviar';
      msgs.scrollTop = msgs.scrollHeight;
      input.focus();
    }
  };
})();
</script>
{% endif %}
</body>
</html>
"""

# Injeta no base.html substituindo </body>\n</html>
try:
    _tpl = TEMPLATES.get("base.html", "")
    if "</body>" in _tpl and _AUGUR_FLOAT_HTML.strip()[:20] not in _tpl:
        TEMPLATES["base.html"] = _tpl.replace("  </body>\n</html>", _AUGUR_FLOAT_HTML)
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping = TEMPLATES
        print("[augur_float] Botão flutuante injetado no base.html.")
    else:
        print("[augur_float] base.html já contém o widget ou </body> não encontrado.")
except Exception as _e_af:
    print(f"[augur_float] Erro ao injetar: {_e_af}")
