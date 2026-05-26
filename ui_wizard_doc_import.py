# ui_wizard_doc_import.py
# Adds "Preencher com documento" (Excel/PDF → auto-fill) to the diagnostic wizard.
# Exec'd in app.py namespace after ui_wizard_v3.py.

import json as _json_wdi
import os as _os_wdi
import re as _re_wdi

import httpx as _httpx_wdi
from fastapi import UploadFile as _Up_wdi, File as _Fi_wdi, Depends as _Dep_wdi
from sqlmodel import Session as _Sess_wdi


_WDI_PROMPT = """Você é especialista em documentos financeiros empresariais.
Analise o texto abaixo e extraia os valores numéricos para EXATAMENTE estes campos.
Retorne APENAS um JSON válido (sem markdown, sem explicação).
Use null para campos não encontrados. Valores em reais, numéricos (sem R$, sem pontos de milhar).

Campos:
- faturamento_bruto_mensal: faturamento/receita bruta mensal (média)
- faturamento_medio_12m: faturamento médio dos últimos 12 meses
- caixa_disponivel: caixa + bancos + aplicações financeiras (ativo circulante)
- ac_cr_30d: recebíveis a vencer em até 30 dias
- ac_cr_60d: recebíveis de 31 a 60 dias
- ac_cr_90d: recebíveis de 61 a 90 dias
- ac_cr_360d: recebíveis de 91 dias a 1 ano
- anc_cr_361d: recebíveis acima de 1 ano (longo prazo)
- ac_est_acab: estoque total (matéria-prima + em processo + acabado)
- anc_imoveis: imóveis da empresa
- anc_veiculos: veículos e maquinário
- pc_forn_360d: total de fornecedores / contas a pagar (curto prazo)
- pc_trab_360d: passivo trabalhista total (salários, FGTS, férias)
- pc_trib_360d: impostos e tributos a pagar
- pc_emp_360d: empréstimos e financiamentos de curto prazo (até 1 ano)
- pnc_emp: empréstimos e financiamentos de longo prazo (acima de 1 ano)
- patrimonio_liquido: patrimônio líquido / PL

Texto do documento:
{content}

JSON:"""


def _wdi_extract_fields(content_text: str) -> dict:
    key = _os_wdi.getenv("ANTHROPIC_API_KEY", "")
    if not key or not content_text:
        return {}
    try:
        prompt = _WDI_PROMPT.format(content=content_text[:10000])
        r = _httpx_wdi.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        raw = r.json()["content"][0]["text"].strip()
        m = _re_wdi.search(r"\{[\s\S]+\}", raw)
        return _json_wdi.loads(m.group()) if m else {}
    except Exception as _e:
        print(f"[wdi] extract erro: {_e}")
        return {}


def _wdi_extract_file(file_bytes: bytes, filename: str, mime: str) -> str:
    """Extract text from uploaded file for wizard pre-fill."""
    fname = filename.lower()
    if fname.endswith((".xlsx", ".xls")) or "spreadsheet" in mime or "excel" in mime:
        return _bc_extract_excel(file_bytes, fname)
    elif fname.endswith(".pdf") or mime == "application/pdf":
        # Try local first
        local = _bc_extract_pdf_local(file_bytes)
        if local:
            return local
        return _bc_extract_claude(file_bytes, "application/pdf")
    elif fname.endswith(".csv") or "csv" in mime:
        return file_bytes.decode("utf-8", errors="replace")
    elif fname.endswith((".doc", ".docx")) or "word" in mime:
        try:
            import docx as _dx, io as _io2
            _doc = _dx.Document(_io2.BytesIO(file_bytes))
            return "\n".join(p.text for p in _doc.paragraphs if p.text.strip())
        except Exception:
            return ""
    try:
        return file_bytes.decode("utf-8", errors="replace")
    except Exception:
        return ""


@app.post("/api/wizard/extract-doc")
@require_login
async def wizard_extract_doc(
    request: Request,
    session: Session = Depends(get_session),
    arquivo: UploadFile = File(...),
):
    ctx = get_tenant_context(request, session)
    if not ctx:
        return JSONResponse({"ok": False, "erro": "Não autenticado."}, status_code=401)

    file_bytes = await arquivo.read()
    if not file_bytes:
        return JSONResponse({"ok": False, "erro": "Arquivo vazio."})

    fname = arquivo.filename or ""
    mime  = arquivo.content_type or ""

    content_text = _wdi_extract_file(file_bytes, fname, mime)
    if not content_text:
        return JSONResponse({
            "ok": False,
            "erro": "Não consegui extrair o conteúdo. Verifique se o arquivo não está protegido por senha.",
        })

    fields = _wdi_extract_fields(content_text)
    if not fields or all(v is None for v in fields.values()):
        return JSONResponse({
            "ok": False,
            "erro": "Nenhum dado financeiro identificado no documento. Tente um extrato, DRE ou balanço patrimonial.",
        })

    # Filter nulls, format numbers
    result = {}
    for k, v in fields.items():
        if v is not None:
            try:
                result[k] = float(v)
            except (TypeError, ValueError):
                pass

    return JSONResponse({"ok": True, "fields": result, "chars": len(content_text)})


# ── Patch wizard template to add the upload button + modal ────────────────────

_WDI_BTN_HTML = """
<div id="wdi-bar" style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:.6rem 1rem;margin-bottom:1rem;display:flex;align-items:center;justify-content:space-between;gap:.75rem;flex-wrap:wrap;">
  <span style="font-size:.82rem;color:#1e40af;font-weight:600;">📎 Tem uma planilha ou PDF com os dados financeiros?</span>
  <button type="button" class="btn btn-sm" style="background:#1e40af;color:#fff;border-radius:8px;" onclick="document.getElementById('wdi-modal').style.display='flex'">
    Preencher com documento
  </button>
</div>

<div id="wdi-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:14px;padding:1.75rem;max-width:440px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,.18);">
    <h5 style="margin-bottom:.75rem;">📄 Preencher com documento</h5>
    <p style="font-size:.82rem;color:#6b7280;margin-bottom:1rem;">
      Envie uma planilha (Excel), PDF de balanço, DRE ou extrato de recebíveis/pagar.
      O sistema vai extrair os dados e pré-preencher os campos automaticamente.
    </p>
    <input type="file" id="wdi-file" accept=".xlsx,.xls,.pdf,.csv,.doc,.docx"
           style="display:block;width:100%;margin-bottom:.75rem;font-size:.82rem;">
    <div id="wdi-status" style="font-size:.78rem;color:#6b7280;margin-bottom:.75rem;min-height:1.2rem;"></div>
    <div style="display:flex;gap:.5rem;justify-content:flex-end;">
      <button type="button" class="btn btn-outline-secondary btn-sm"
              onclick="document.getElementById('wdi-modal').style.display='none'">Cancelar</button>
      <button type="button" class="btn btn-sm" id="wdi-send-btn"
              style="background:#f97316;color:#fff;border-radius:8px;"
              onclick="wdiUpload()">Extrair dados</button>
    </div>
  </div>
</div>

<script>
function wdiUpload() {
  const f = document.getElementById('wdi-file').files[0];
  if (!f) { alert('Selecione um arquivo primeiro.'); return; }
  const st = document.getElementById('wdi-status');
  const btn = document.getElementById('wdi-send-btn');
  st.textContent = '⏳ Extraindo dados, aguarde...';
  btn.disabled = true;

  const fd = new FormData();
  fd.append('arquivo', f);

  fetch('/api/wizard/extract-doc', { method: 'POST', body: fd })
    .then(r => r.json())
    .then(data => {
      btn.disabled = false;
      if (!data.ok) {
        st.style.color = '#dc2626';
        st.textContent = '❌ ' + data.erro;
        return;
      }
      const fields = data.fields;
      let filled = 0;
      for (const [key, val] of Object.entries(fields)) {
        const el = document.querySelector('[name="' + key + '"]');
        if (el && val != null) {
          // Format as pt-BR currency
          const num = parseFloat(val);
          el.value = num.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
          el.style.background = '#fef9c3';
          filled++;
        }
      }
      document.getElementById('wdi-modal').style.display = 'none';
      if (filled > 0) {
        st.style.color = '#166534';
        st.textContent = '✅ ' + filled + ' campo(s) preenchido(s).';
        // Show a visible banner on the page
        const bar = document.getElementById('wdi-bar');
        if (bar) {
          bar.style.background = '#f0fdf4';
          bar.style.borderColor = '#86efac';
          bar.querySelector('span').textContent = '✅ ' + filled + ' campos preenchidos com os dados do documento. Confira e ajuste se necessário.';
          bar.querySelector('button').style.display = 'none';
        }
      } else {
        alert('Nenhum campo correspondente encontrado nesta etapa. Tente uma etapa diferente ou verifique o documento.');
      }
    })
    .catch(err => {
      btn.disabled = false;
      st.style.color = '#dc2626';
      st.textContent = '❌ Erro de comunicação: ' + err;
    });
}
</script>
"""

try:
    _wiz_tpl = TEMPLATES.get("wizard_diagnostico.html", "")
    if _wiz_tpl and "wdi-bar" not in _wiz_tpl:
        _wiz_tpl = _wiz_tpl.replace(
            '<input type="hidden" name="etapa" value="{{ etapa }}">',
            '<input type="hidden" name="etapa" value="{{ etapa }}">\n'
            '{% if etapa in [2,3,4] %}\n' + _WDI_BTN_HTML + '\n{% endif %}',
            1,
        )
        TEMPLATES["wizard_diagnostico.html"] = _wiz_tpl
    if hasattr(templates_env.loader, "mapping"):
        templates_env.loader.mapping = TEMPLATES
    print("[wdi] template wizard atualizado com botão de upload de documento")
except Exception as _e_wdi:
    print(f"[wdi] erro ao atualizar template (não fatal): {_e_wdi}")
