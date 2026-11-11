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
#frec-btn.frec-tem-pendente::after {
  content: ""; position: absolute; top: 2px; right: 2px; width: 12px; height: 12px;
  border-radius: 50%; background: #f59e0b; border: 2px solid #fff;
}
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

  <div id="frec-pendentes" style="display:none;gap:6px;"></div>

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
  // Gravador resistente a queda: cada pedaço do áudio vai para o IndexedDB deste navegador enquanto grava.
  // O envio é repetido sozinho se o servidor estiver fora (ex.: deploy) e só apaga a cópia local depois
  // que o servidor confirma. O que não foi enviado aparece em "Gravações não enviadas" (Reenviar/Baixar).
  var _mr = null, _chunks = [], _timer = null, _secs = 0, _stream = null, _seq = 0;
  var _panelOpen = false, _rec = null, _enviando = false, _memoria = {};
  var DB = 'mc_gravacoes';

  function idb() {
    return new Promise(function(res, rej) {
      try {
        var r = indexedDB.open(DB, 1);
        r.onupgradeneeded = function() {
          var d = r.result;
          if (!d.objectStoreNames.contains('pedacos')) d.createObjectStore('pedacos', { autoIncrement: true }).createIndex('rec', 'rec');
          if (!d.objectStoreNames.contains('gravacoes')) d.createObjectStore('gravacoes', { keyPath: 'id' });
        };
        r.onsuccess = function() { res(r.result); };
        r.onerror = function() { rej(r.error); };
      } catch (e) { rej(e); }
    });
  }
  function op(stores, modo, fn) {
    return idb().then(function(d) {
      return new Promise(function(res, rej) {
        var t = d.transaction(stores, modo), out = {};
        fn(t, out);
        t.oncomplete = function() { res(out.v); };
        t.onerror = function() { rej(t.error); };
        t.onabort = function() { rej(t.error); };
      });
    });
  }
  function salvarMeta(m) { return op(['gravacoes'], 'readwrite', function(t) { t.objectStore('gravacoes').put(m); }).catch(function(){}); }
  function salvarPedaco(rec, seq, blob) {
    return op(['pedacos'], 'readwrite', function(t) { t.objectStore('pedacos').add({ rec: rec, seq: seq, blob: blob }); }).catch(function(){});
  }
  function lerPedacos(rec) {
    return op(['pedacos'], 'readonly', function(t, out) {
      var q = t.objectStore('pedacos').index('rec').getAll(rec);
      q.onsuccess = function() { out.v = (q.result || []).sort(function(a, b) { return a.seq - b.seq; }).map(function(x) { return x.blob; }); };
    }).catch(function() { return []; });
  }
  function listarGravacoes() {
    return op(['gravacoes'], 'readonly', function(t, out) {
      var q = t.objectStore('gravacoes').getAll();
      q.onsuccess = function() { out.v = q.result || []; };
    }).catch(function() { return []; });
  }
  function apagar(rec) {
    delete _memoria[rec];
    return op(['pedacos', 'gravacoes'], 'readwrite', function(t) {
      t.objectStore('gravacoes').delete(rec);
      var c = t.objectStore('pedacos').index('rec').openCursor(IDBKeyRange.only(rec));
      c.onsuccess = function() { var cur = c.result; if (cur) { cur.delete(); cur.continue(); } };
    }).catch(function(){});
  }
  async function blobDe(rec, mime) {
    var partes = await lerPedacos(rec);
    if (!partes || !partes.length) partes = _memoria[rec] || [];
    return new Blob(partes, { type: mime || 'audio/webm' });
  }

  function frecTogglePanel() {
    _panelOpen = !_panelOpen;
    document.getElementById('frec-panel').classList.toggle('open', _panelOpen);
    if (_panelOpen) { frecCarregarReunioes(); atualizarPendentes(); }
  }
  window.frecTogglePanel = frecTogglePanel;

  async function frecCarregarReunioes() {
    var sel = document.getElementById('frec-meeting-sel');
    if (_mr && _mr.state !== 'inactive') return;
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
    var sel = document.getElementById('frec-meeting-sel');
    var mid = sel.value;
    if (!mid) { frecSetFeedback('Selecione uma reunião primeiro.'); return; }
    try {
      _stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch(e) {
      frecSetFeedback('Sem acesso ao microfone: ' + e.message); return;
    }
    _chunks = []; _secs = 0; _seq = 0;
    var mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
    var rec = 'g' + Date.now();
    _rec = rec;
    _memoria[rec] = _chunks;
    var meta = { id: rec, mid: mid, titulo: (sel.options[sel.selectedIndex] || {}).text || ('Reunião #' + mid), mime: mime,
                 inicio: Date.now(), atualizado: Date.now(), segundos: 0, status: 'gravando' };
    salvarMeta(meta);
    _mr = new MediaRecorder(_stream, { mimeType: mime });
    _mr.ondataavailable = function(e) {
      if (e.data.size > 0) {
        _chunks.push(e.data);
        salvarPedaco(rec, _seq++, e.data);
        meta.atualizado = Date.now(); meta.segundos = _secs;
        salvarMeta(meta);
      }
    };
    _mr.onstop = function() {
      meta.status = 'parada'; meta.segundos = _secs; meta.atualizado = Date.now();
      salvarMeta(meta).then(function() { frecEnviar(rec, 0); });
    };
    _mr.start(5000);

    document.getElementById('frec-start-btn').style.display = 'none';
    document.getElementById('frec-stop-btn').style.display = '';
    document.getElementById('frec-select-wrap').style.display = 'none';
    document.getElementById('frec-timer-bar').classList.add('active');
    document.getElementById('frec-btn').classList.add('recording');
    document.getElementById('frec-btn').textContent = '⏹';
    frecSetFeedback('A gravação fica salva neste navegador enquanto grava. Não feche nem recarregue esta aba.');

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

  var ESPERAS = [5, 10, 20, 30, 60, 60, 60, 60, 120, 120];

  function liberarInicio() {
    document.getElementById('frec-start-btn').style.display = '';
    document.getElementById('frec-select-wrap').style.display = '';
  }

  async function frecEnviar(rec, tentativa) {
    var lista = await listarGravacoes();
    var meta = lista.filter(function(m) { return m.id === rec; })[0];
    if (!meta) { meta = { id: rec, mid: document.getElementById('frec-meeting-sel').value, mime: 'audio/webm' }; }
    _enviando = true;
    var blob = await blobDe(rec, meta.mime);
    if (!blob.size) {
      _enviando = false; liberarInicio();
      frecSetFeedback('❌ A gravação ficou vazia (o microfone não captou áudio).');
      apagar(rec); atualizarPendentes();
      return;
    }
    var ext = (meta.mime || '').indexOf('ogg') >= 0 ? 'ogg' : 'webm';
    var fd = new FormData();
    fd.append('audio', blob, 'gravacao.' + ext);
    var d = null, status = 0;
    try {
      var r = await fetch('/reunioes/' + meta.mid + '/upload-audio', { method: 'POST', body: fd });
      status = r.status;
      try { d = await r.json(); } catch (e2) { d = null; }
      if (r.ok && d && d.ok) {
        await apagar(rec);
        _enviando = false; liberarInicio();
        frecSetFeedback('✅ ' + (d.msg || 'Enviado! Transcrevendo…'));
        atualizarPendentes();
        return;
      }
      if (d && d.erro && status < 500 && status !== 429) {
        _enviando = false; liberarInicio();
        frecSetFeedback('❌ ' + d.erro + ' A gravação continua guardada neste navegador.');
        atualizarPendentes();
        return;
      }
      throw new Error(status ? 'servidor respondeu ' + status : 'sem resposta');
    } catch (e) {
      if (tentativa < ESPERAS.length) {
        var espera = ESPERAS[tentativa];
        frecSetFeedback('Servidor indisponível (' + e.message + '). A gravação está salva. Nova tentativa em ' + espera +
                        ' s (' + (tentativa + 1) + '/' + ESPERAS.length + ')… Não feche esta aba.');
        setTimeout(function() { frecEnviar(rec, tentativa + 1); }, espera * 1000);
      } else {
        _enviando = false; liberarInicio();
        frecSetFeedback('❌ Não foi possível enviar agora. A gravação ficou guardada neste navegador: use Reenviar abaixo.');
        atualizarPendentes();
      }
    }
  }

  function fmtDur(s) { s = s || 0; return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }

  async function atualizarPendentes() {
    var box = document.getElementById('frec-pendentes');
    if (!box) return;
    var agora = Date.now();
    var lista = (await listarGravacoes()).filter(function(m) {
      if (m.id === _rec && (_enviando || (_mr && _mr.state !== 'inactive'))) return false;
      return !(m.status === 'gravando' && agora - (m.atualizado || 0) < 30000);  // gravando em outra aba
    });
    var btn = document.getElementById('frec-btn');
    btn.classList.toggle('frec-tem-pendente', lista.length > 0);
    box.innerHTML = '';
    box.style.display = lista.length ? 'grid' : 'none';
    if (!lista.length) return;
    var h = document.createElement('div');
    h.style.cssText = 'font-weight:600;font-size:.8rem;color:#b45309;';
    h.textContent = 'Gravações não enviadas (' + lista.length + ')';
    box.appendChild(h);
    lista.sort(function(a, b) { return b.inicio - a.inicio; }).forEach(function(m) {
      var item = document.createElement('div');
      item.style.cssText = 'border:1px solid #fde68a;background:#fffbeb;border-radius:8px;padding:6px 8px;display:grid;gap:4px;';
      var dt = new Date(m.inicio || Date.now());
      var t = document.createElement('div');
      t.style.fontSize = '.78rem';
      t.textContent = (m.titulo || ('Reunião #' + m.mid)) + ' · ' + dt.toLocaleDateString('pt-BR') + ' ' +
                      dt.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) + ' · ' + fmtDur(m.segundos) +
                      (m.status === 'gravando' ? ' (interrompida)' : '');
      item.appendChild(t);
      var acoes = document.createElement('div');
      acoes.className = 'd-flex gap-1';
      function botao(rot, cls, fn) {
        var b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-sm ' + cls; b.textContent = rot;
        b.addEventListener('click', fn); acoes.appendChild(b); return b;
      }
      botao('Reenviar', 'btn-primary', function() {
        if (_enviando) { frecSetFeedback('Aguarde o envio em andamento terminar.'); return; }
        m.status = 'parada'; salvarMeta(m).then(function() { frecSetFeedback('Enviando…'); frecEnviar(m.id, 0); atualizarPendentes(); });
      });
      botao('Baixar', 'btn-outline-secondary', async function() {
        var blob = await blobDe(m.id, m.mime);
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'gravacao-reuniao-' + m.mid + '-' + dt.toISOString().slice(0, 16).replace(/[:T]/g, '-') + '.webm';
        document.body.appendChild(a); a.click(); a.remove();
      });
      var desc = botao('Descartar', 'btn-outline-danger', function() {
        if (desc.dataset.confirma !== '1') { desc.dataset.confirma = '1'; desc.textContent = 'Confirmar descarte'; return; }
        apagar(m.id).then(atualizarPendentes);
      });
      item.appendChild(acoes);
      box.appendChild(item);
    });
  }

  window.addEventListener('beforeunload', function(e) {
    if ((_mr && _mr.state !== 'inactive') || _enviando) { e.preventDefault(); e.returnValue = ''; }
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', atualizarPendentes);
  else atualizarPendentes();

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
