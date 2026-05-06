# ============================================================================
# PATCH — Fix upload Excel na Base de Conhecimento
# ============================================================================
# Excel (.xls/.xlsx) é binário — não pode ser lido como texto.
# Fix: lê como base64 e salva como pdf_base64 para o Augur processar.
# DEPLOY: adicione ao final do app.py
# ============================================================================

_BASE_JS_FIX = """
<script>
// Fix Base de Conhecimento — Excel como base64
window.baseSalvar = async function(){
  const nome = document.getElementById('baseNome').value.trim();
  const descricao = document.getElementById('baseDescricao').value.trim();
  const arquivo = document.getElementById('baseArquivo').files[0];
  const fb = document.getElementById('baseFeedback');

  if(!nome || !arquivo){
    fb.style.display='block';
    fb.innerHTML='<div class="alert alert-warning py-1 mb-0">Nome e arquivo são obrigatórios.</div>';
    return;
  }

  fb.style.display='block';
  fb.innerHTML='<div class="alert alert-info py-1 mb-0">Processando...</div>';

  try {
    let conteudo = '', tipo = arquivo.name.split('.').pop().toLowerCase();

    if(tipo === 'csv' || tipo === 'txt') {
      // Texto puro — lê direto
      conteudo = await arquivo.text();

    } else if(tipo === 'xlsx' || tipo === 'xls') {
      // Excel — lê como base64
      const reader = new FileReader();
      conteudo = await new Promise(res => {
        reader.onload = e => res(e.target.result.split(',')[1]);
        reader.readAsDataURL(arquivo);
      });
      tipo = 'excel_base64';

    } else if(tipo === 'pdf') {
      const reader = new FileReader();
      conteudo = await new Promise(res => {
        reader.onload = e => res(e.target.result.split(',')[1]);
        reader.readAsDataURL(arquivo);
      });
      tipo = 'pdf_base64';

    } else if(['png','jpg','jpeg','gif','webp'].includes(tipo)) {
      const reader = new FileReader();
      conteudo = await new Promise(res => {
        reader.onload = e => res(e.target.result.split(',')[1]);
        reader.readAsDataURL(arquivo);
      });
      tipo = 'imagem_base64';

    } else {
      fb.innerHTML='<div class="alert alert-warning py-1 mb-0">Tipo não suportado. Use PDF, Excel, CSV ou imagem.</div>';
      return;
    }

    const r = await fetch('/api/base-conhecimento/upload', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({nome, descricao, tipo, conteudo}),
    });
    const d = await r.json();

    if(d.ok) {
      fb.innerHTML='<div class="alert alert-success py-1 mb-0">✅ Documento salvo!</div>';
      document.getElementById('baseNome').value='';
      document.getElementById('baseDescricao').value='';
      document.getElementById('baseArquivo').value='';
      if(typeof _baseCarregar === 'function') _baseCarregar();
      else if(typeof baseCarregar === 'function') baseCarregar();
      setTimeout(() => { baseToggleForm(); fb.style.display='none'; }, 1500);
    } else {
      fb.innerHTML='<div class="alert alert-danger py-1 mb-0">'+(d.erro||'Erro ao salvar.')+'</div>';
    }
  } catch(e) {
    console.error('[base] Erro:', e);
    fb.innerHTML='<div class="alert alert-danger py-1 mb-0">Erro: ' + e.message + '</div>';
  }
};
</script>
"""

# Injeta no dashboard
_dash_bfix = TEMPLATES.get("dashboard.html", "")
if _dash_bfix and "Fix Base de Conhecimento" not in _dash_bfix:
    if "{% endblock %}" in _dash_bfix:
        _dash_bfix = _dash_bfix.replace("{% endblock %}", _BASE_JS_FIX + "\n{% endblock %}", 1)
        TEMPLATES["dashboard.html"] = _dash_bfix
        print("[fix_base_excel] ✅ Fix Excel injetado no dashboard")
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES

print("[fix_base_excel] ✅ Patch completo")
