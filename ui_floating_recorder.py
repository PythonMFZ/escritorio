# ============================================================================
# ui_floating_recorder.py — Gravador flutuante persistente em todas as páginas
# ============================================================================
# Injeta no base.html um botão de microfone fixo (bottom-right) que:
#   1. Persiste em qualquer página do app (não precisa ficar na aba da reunião)
#   2. Ao clicar: seleciona a reunião e inicia gravação
#   3. Mostra timer enquanto grava (● 02:34)
#   4. Ao parar: envia o áudio para a reunião selecionada e notifica
#   5. Sem integração Notion — apenas upload para /reunioes/{id}/upload-audio
# ============================================================================

_FLOAT_REC_HTML = r"""
<!-- ── Gravador Flutuante ────────────────────────────────────────────────── -->
<style>
#frec-btn {
  position: fixed; bottom: 20px; left: 20px; z-index: 9999;
  width: 52px; height: 52px; border-radius: 50%;
  background: #E07020; border: none; cursor: pointer;
  box-shadow: 0 4px 16px rgba(0,0,0,.25);
  display: flex; align-items: center; justify-content: center;
  transition: background .2s, transform .15s, left .22s cubic-bezier(.4,0,.2,1);
  color: #fff; font-size: 22px;
}
#frec-btn:hover { background: #C85F1B; transform: scale(1.07); }
#frec-btn.recording { background: #dc2626; animation: frec-pulse 1.2s infinite; }
@keyframes frec-pulse {
  0%,100% { box-shadow: 0 0 0 0 rgba(220,38,38,.5); }
  50%      { box-shadow: 0 0 0 10px rgba(220,38,38,0); }
}
/* Desloca para fora da sidebar em desktop */
@media (min-width: 992px) {
  #frec-btn { left: calc(var(--sb-w, 220px) + 16px); }
  body.sb-is-collapsed #frec-btn { left: calc(var(--sb-w-col, 56px) + 16px); }
}

#frec-panel {
  position: fixed; bottom: 84px; left: 16px; z-index: 9999;
  width: 300px; background: #fff; border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0,0,0,.18); padding: 16px;
  display: none; flex-direction: column; gap: 10px;
  font-size: .85rem;
}
#frec-panel.open { display: flex; }
#frec-timer-bar {
  display: none; align-items: center; gap: 8px;
  background: #fef2f2; border-radius: 8px; padding: 8px 12px;
  color: #dc2626; font-weight: 600;
}
#frec-timer-bar.active { display: flex; }
#frec-dot { font-size: 12px; animation: frec-blink 1s infinite; }
@keyframes frec-blink { 0%,100%{opacity:1} 50%{opacity:0} }
#frec-feedback { font-size: .78rem; color: #6b7280; }
</style>

<button id="frec-btn" title="Gravador de reunião" onclick="frecTogglePanel()">
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
    <!-- Forma de onda de áudio -->
    <line x1="2"  y1="12" x2="2"  y2="12"/>
    <line x1="5"  y1="9"  x2="5"  y2="15"/>
    <line x1="8"  y1="6"  x2="8"  y2="18"/>
    <line x1="11" y1="4"  x2="11" y2="20"/>
    <line x1="14" y1="7"  x2="14" y2="17"/>
    <line x1="17" y1="10" x2="17" y2="14"/>
    <line x1="20" y1="11" x2="20" y2="13"/>
  </svg>
</button>

<div id="frec-panel">
  <div style="font-weight:600; font-size:.9rem;">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:-2px;margin-right:4px;">
      <line x1="5" y1="9" x2="5" y2="15"/><line x1="8" y1="6" x2="8" y2="18"/>
      <line x1="11" y1="4" x2="11" y2="20"/><line x1="14" y1="7" x2="14" y2="17"/>
      <line x1="17" y1="10" x2="17" y2="14"/>
    </svg>
    Gravar Reunião
  </div>

  <div id="frec-select-wrap">
    <label style="font-size:.75rem;color:#6b7280;">Reunião</label>
    <select id="frec-meeting-sel" class="form-select form-select-sm mt-1">
      <option value="">Carregando…</option>
    </select>
  </div>

  <div id="frec-timer-bar">
    <span id="frec-dot">●</span>
    <span>Gravando</span>
    <span id="frec-timer" style="margin-left:auto;">00:00</span>
  </div>

  <div id="frec-feedback"></div>

  <div class="d-flex gap-2">
    <button id="frec-start-btn" class="btn btn-danger btn-sm flex-grow-1" onclick="frecIniciar()">
      ● Iniciar
    </button>
    <button id="frec-stop-btn" class="btn btn-warning btn-sm flex-grow-1" style="display:none" onclick="frecParar()">
      ■ Parar e Enviar
    </button>
    <button class="btn btn-outline-secondary btn-sm" onclick="frecTogglePanel()" title="Fechar">✕</button>
  </div>
</div>

<script>
(function(){
  var _mr = null, _chunks = [], _timer = null, _secs = 0, _stream = null;
  var _panelOpen = false;

  function frecTogglePanel() {
    _panelOpen = !_panelOpen;
    document.getElementById('frec-panel').classList.toggle('open', _panelOpen);
    if (_panelOpen) frecCarregarReunioes();
  }
  window.frecTogglePanel = frecTogglePanel;

  async function frecCarregarReunioes() {
    var sel = document.getElementById('frec-meeting-sel');
    try {
      var r = await fetch('/api/reunioes/recentes');
      if (!r.ok) throw new Error('status ' + r.status);
      var data = await r.json();
      sel.innerHTML = '<option value="">Selecione a reunião…</option>';
      (data.reunioes || []).forEach(function(m) {
        var opt = document.createElement('option');
        opt.value = m.id;
        opt.textContent = (m.meeting_date ? m.meeting_date + ' — ' : '') + (m.title || 'Reunião #' + m.id);
        sel.appendChild(opt);
      });
    } catch(e) {
      sel.innerHTML = '<option value="">Erro ao carregar reuniões</option>';
    }
  }

  async function frecIniciar() {
    var mid = document.getElementById('frec-meeting-sel').value;
    if (!mid) { frecSetFeedback('Selecione uma reunião primeiro.'); return; }
    try {
      _stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch(e) {
      frecSetFeedback('Sem acesso ao microfone: ' + e.message); return;
    }
    _chunks = []; _secs = 0;
    var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';
    _mr = new MediaRecorder(_stream, { mimeType: mime });
    _mr.ondataavailable = function(e){ if(e.data.size>0) _chunks.push(e.data); };
    _mr.onstop = function(){ frecEnviar(mid, mime); };
    _mr.start(1000);

    document.getElementById('frec-start-btn').style.display = 'none';
    document.getElementById('frec-stop-btn').style.display = '';
    document.getElementById('frec-select-wrap').style.display = 'none';
    document.getElementById('frec-timer-bar').classList.add('active');
    document.getElementById('frec-btn').classList.add('recording');
    document.getElementById('frec-btn').textContent = '⏹';
    frecSetFeedback('');

    _timer = setInterval(function(){
      _secs++;
      var m = String(Math.floor(_secs/60)).padStart(2,'0');
      var s = String(_secs%60).padStart(2,'0');
      document.getElementById('frec-timer').textContent = m+':'+s;
    }, 1000);
  }
  window.frecIniciar = frecIniciar;

  function frecParar() {
    if (_mr && _mr.state !== 'inactive') _mr.stop();
    if (_stream) { _stream.getTracks().forEach(function(t){ t.stop(); }); _stream = null; }
    clearInterval(_timer);
    document.getElementById('frec-stop-btn').style.display = 'none';
    document.getElementById('frec-timer-bar').classList.remove('active');
    document.getElementById('frec-btn').classList.remove('recording');
    document.getElementById('frec-btn').textContent = '🎙';
    frecSetFeedback('Enviando…');
  }
  window.frecParar = frecParar;

  async function frecEnviar(mid, mime) {
    var ext = mime.includes('ogg') ? 'ogg' : 'webm';
    var blob = new Blob(_chunks, { type: mime });
    var fd = new FormData();
    fd.append('audio', blob, 'gravacao.' + ext);
    try {
      var r = await fetch('/reunioes/' + mid + '/upload-audio', { method: 'POST', body: fd });
      var d = await r.json();
      if (d.ok) {
        frecSetFeedback('✅ ' + (d.msg || 'Enviado! Transcrevendo…'));
        document.getElementById('frec-start-btn').style.display = '';
        document.getElementById('frec-select-wrap').style.display = '';
      } else {
        frecSetFeedback('❌ ' + (d.erro || 'Erro ao enviar.'));
        document.getElementById('frec-start-btn').style.display = '';
        document.getElementById('frec-select-wrap').style.display = '';
      }
    } catch(e) {
      frecSetFeedback('❌ Erro de conexão.');
      document.getElementById('frec-start-btn').style.display = '';
      document.getElementById('frec-select-wrap').style.display = '';
    }
  }

  function frecSetFeedback(msg) {
    document.getElementById('frec-feedback').textContent = msg;
  }
})();
</script>
<!-- ── /Gravador Flutuante ───────────────────────────────────────────────── -->
"""

# ── Rota API: listar reuniões recentes para o dropdown ───────────────────────

from fastapi.responses import JSONResponse as _FRJSON

@app.get("/api/reunioes/recentes")
@require_login
async def frec_reunioes_recentes(request: Request, session: Session = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "equipe"):
        return _FRJSON({"reunioes": []})
    reunioes = session.exec(
        __import__('sqlmodel').select(Meeting)
        .where(Meeting.company_id == ctx.company.id)
        .order_by(Meeting.created_at.desc())
        .limit(30)
    ).all()
    data = [
        {"id": m.id, "title": m.title or "", "meeting_date": m.meeting_date or ""}
        for m in reunioes
    ]
    return _FRJSON({"reunioes": data})


# ── Injetar widget no base.html ───────────────────────────────────────────────

try:
    _base = TEMPLATES.get("base.html", "")
    _marker = "</body>"
    if _marker in _base and "frec-btn" not in _base:
        _base = _base.replace(
            _marker,
            "{% if role in ['admin','equipe'] %}\n" + _FLOAT_REC_HTML + "\n{% endif %}\n" + _marker,
            1,
        )
        TEMPLATES["base.html"] = _base
        if hasattr(templates_env.loader, "mapping"):
            templates_env.loader.mapping["base.html"] = _base
        print("[floating_recorder] ✅ Gravador flutuante injetado no base.html.")
    else:
        print("[floating_recorder] ℹ️ Gravador já presente ou base.html não encontrado.")
except Exception as _e_fr:
    print(f"[floating_recorder] ⚠️ Erro ao injetar gravador: {_e_fr}")

print("[floating_recorder] ✅ Módulo de gravador flutuante carregado.")
