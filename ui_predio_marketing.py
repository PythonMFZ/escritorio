# ============================================================================
# ui_predio_marketing.py — 1º andar do prédio: Marketing
# ============================================================================
# Exec'd no namespace do app.py, DEPOIS de ui_predio.py (usa os helpers _pr_*).
#
# AGENTES
#   inteligencia_mercado — indicadores do BC, notícias e pesquisa na web
#   conteudo             — textos de posts, artigos e newsletter
#   agencia_redes        — calendário bimestral (3 posts/semana) em Excel, envio à
#                          agência e análise do desempenho das redes
#   editor_site          — Monitor de Insolvência e Notícias do site, todo mês
#
# PUBLICAÇÃO NO SITE
#   O site é estático (pasta website/ deste repositório, publicada pelo Render).
#   Na aprovação, a plataforma faz um commit pela API do GitHub e o Render
#   publica sozinho. Variáveis: SITE_GITHUB_TOKEN (obrigatória para publicar),
#   SITE_GITHUB_REPO (padrão PythonMFZ/escritorio), SITE_GITHUB_BRANCH (main).
#
# ROTAS (admin)
#   GET  /predio/acoes/{id}/previa     — prévia da página que será publicada
#   POST /predio/marketing/config      — agência e atualização mensal
#   POST /predio/marketing/site-agora  — roda a atualização do site agora
# ============================================================================

import base64 as _b64_mk
import html as _html_mk
import io as _io_mk
import os as _os_mk
import re as _re_mk
import unicodedata as _ud_mk
import xml.etree.ElementTree as _ET_mk

_MK_SITE_URL = "https://maffezzollicapital.com.br"
_MK_PREFIXO = "website/"
_MK_MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
_MK_MESES_LONGOS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
                    "outubro", "novembro", "dezembro"]


def _mk_repo() -> str:
    return _os_mk.environ.get("SITE_GITHUB_REPO", "PythonMFZ/escritorio")


def _mk_branch() -> str:
    return _os_mk.environ.get("SITE_GITHUB_BRANCH", "main")


def _mk_token() -> str:
    return _os_mk.environ.get("SITE_GITHUB_TOKEN") or _os_mk.environ.get("GITHUB_TOKEN") or ""


# ── Texto seguro para HTML ────────────────────────────────────────────────────

def _mk_esc(texto) -> str:
    return _html_mk.escape(str(texto or "").strip(), quote=True)


def _mk_negrito(texto) -> str:
    """Escapa o texto e converte **trecho** em <strong>trecho</strong> (único markdown aceito)."""
    return _re_mk.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", _mk_esc(texto))


def _mk_slug(texto: str, limite: int = 40) -> str:
    t = _ud_mk.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = _re_mk.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return (t[:limite].rstrip("-")) or "item"


def _mk_mes_ano(d) -> str:
    return f"{_MK_MESES[d.month - 1]} {d.year}"


# ── GitHub: leitura e commit dos arquivos do site ─────────────────────────────

def _mk_gh(metodo: str, caminho: str, **kw):
    import httpx as _httpx_mk
    token = _mk_token()
    if not token:
        raise _PrErro("Publicação no site não configurada: cadastre SITE_GITHUB_TOKEN no Render "
                      "(token do GitHub com permissão de escrita no repositório do site).")
    r = _httpx_mk.request(metodo, f"https://api.github.com/repos/{_mk_repo()}{caminho}", timeout=30,
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                   "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    if r.status_code == 404 and metodo == "GET":
        return None
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = r.text[:200]
        raise _PrErro(f"GitHub respondeu {r.status_code}: {msg}")
    return r.json()


def _mk_ler(rel: str):
    """Conteúdo atual de website/<rel>: do GitHub quando há token, senão da cópia local."""
    if _mk_token():
        dado = _mk_gh("GET", f"/contents/{_MK_PREFIXO}{rel}", params={"ref": _mk_branch()})
        if dado is None:
            return None
        return _b64_mk.b64decode(dado.get("content") or "").decode("utf-8")
    caminho = _os_mk.path.join(_os_mk.path.dirname(_os_mk.path.abspath("app.py")), "website", rel)
    if not _os_mk.path.exists(caminho):
        return None
    with open(caminho, encoding="utf-8") as f:
        return f.read()


def _mk_commit(arquivos: dict, mensagem: str) -> str:
    """Grava vários arquivos de website/ num único commit. Devolve o link do commit."""
    branch = _mk_branch()
    ref = _mk_gh("GET", f"/git/ref/heads/{branch}")
    if not ref:
        raise _PrErro(f"Branch {branch} não encontrada no repositório do site.")
    base = ref["object"]["sha"]
    arvore_base = _mk_gh("GET", f"/git/commits/{base}")["tree"]["sha"]
    itens = []
    for rel, conteudo in arquivos.items():
        blob = _mk_gh("POST", "/git/blobs", json={"content": conteudo, "encoding": "utf-8"})
        itens.append({"path": _MK_PREFIXO + rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    arvore = _mk_gh("POST", "/git/trees", json={"base_tree": arvore_base, "tree": itens})
    commit = _mk_gh("POST", "/git/commits", json={"message": mensagem, "tree": arvore["sha"], "parents": [base]})
    _mk_gh("PATCH", f"/git/refs/heads/{branch}", json={"sha": commit["sha"], "force": False})
    return commit.get("html_url", "")


def _mk_publicar(montar, mensagem: str) -> str:
    """montar() lê o estado atual e devolve {arquivo: conteúdo}. Se outro commit entrar no meio,
    lê de novo e tenta outra vez (nunca sobrescreve o que mudou)."""
    ultimo = None
    for _ in range(3):
        arquivos = montar()
        try:
            return _mk_commit(arquivos, mensagem)
        except _PrErro as e:
            if "422" not in str(e):
                raise
            ultimo = e
    raise ultimo


# ── Monitor de Insolvência ────────────────────────────────────────────────────

_MK_MONITOR_CSS = """  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Poppins:wght@300;400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap');
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #1a1a1a; display: flex; flex-direction: column; justify-content: center; align-items: flex-start; min-height: 100vh; padding: 40px 20px; font-family: 'Poppins', sans-serif; }
  .card { width: 1080px; background: #0D0D0D; position: relative; overflow: hidden; }
  .card-topbar { width: 100%; height: 5px; background: #C0392B; }
  .card-header { padding: 48px 64px 36px; display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 1px solid rgba(192,57,43,0.15); }
  .header-serie { display: flex; flex-direction: column; gap: 6px; }
  .serie-label { font-family: 'DM Mono', monospace; font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase; color: #C0392B; }
  .serie-title { font-family: 'Syne', sans-serif; font-size: 22px; font-weight: 800; color: #FAF7F2; letter-spacing: -0.01em; }
  .header-meta { text-align: right; display: flex; flex-direction: column; gap: 4px; }
  .meta-edicao { font-family: 'DM Mono', monospace; font-size: 11px; color: rgba(192,57,43,0.7); letter-spacing: 0.12em; }
  .meta-data { font-family: 'DM Mono', monospace; font-size: 11px; color: #666; letter-spacing: 0.08em; }
  .case-origin { padding: 28px 64px 0; display: flex; align-items: center; gap: 12px; }
  .tag-pais { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #0D0D0D; background: #C0392B; padding: 4px 12px; font-weight: 500; }
  .tag-tipo { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: #C0392B; border: 1px solid rgba(192,57,43,0.4); padding: 4px 12px; }
  .card-headline { padding: 32px 64px 28px; }
  .headline-text { font-family: 'Poppins', sans-serif; font-size: 40px; font-weight: 700; color: #FAF7F2; line-height: 1.15; letter-spacing: -0.01em; }
  .headline-text em { color: #C0392B; font-style: normal; }
  .headline-sub { margin-top: 14px; font-size: 15px; font-weight: 300; color: #8B8B8B; line-height: 1.6; max-width: 780px; }
  .card-logos { padding: 0 64px 32px; display: flex; align-items: center; gap: 20px; }
  .logo-box { border: 1px solid rgba(192,57,43,0.2); padding: 14px 28px; display: flex; flex-direction: column; gap: 4px; min-width: 200px; }
  .logo-box span { font-family: 'Poppins', sans-serif; font-size: 15px; font-weight: 700; color: #FAF7F2; }
  .logo-box small { font-family: 'DM Mono', monospace; font-size: 10px; color: #555; letter-spacing: 0.06em; }
  .logo-detail { font-family: 'DM Mono', monospace; font-size: 11px; color: #555; margin-left: 8px; line-height: 1.6; }
  .card-body { padding: 36px 64px 40px; border-top: 1px solid rgba(192,57,43,0.08); }
  .body-text { font-size: 15px; font-weight: 300; color: #C8C4BE; line-height: 1.8; margin-bottom: 16px; }
  .body-text strong { color: #FAF7F2; font-weight: 500; }
  .body-text em { color: #C0392B; font-style: normal; }
  .card-analise { margin: 0 64px 36px; padding: 24px 28px; border-left: 3px solid #C0392B; background: rgba(192,57,43,0.05); }
  .analise-label { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.2em; text-transform: uppercase; color: #C0392B; margin-bottom: 10px; }
  .analise-text { font-size: 14px; font-weight: 300; color: #C8C4BE; line-height: 1.75; }
  .analise-text strong { color: #FAF7F2; font-weight: 500; }
  .card-numeros { display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid rgba(192,57,43,0.15); }
  .num-item { padding: 36px 40px; border-right: 1px solid rgba(192,57,43,0.1); display: flex; flex-direction: column; gap: 10px; }
  .num-item:last-child { border-right: none; }
  .num-icon { width: 36px; height: 36px; border: 1px solid rgba(192,57,43,0.3); display: flex; align-items: center; justify-content: center; font-family: 'DM Mono', monospace; font-size: 14px; color: #C0392B; margin-bottom: 4px; }
  .num-valor { font-family: 'Poppins', sans-serif; font-size: 26px; font-weight: 700; color: #FAF7F2; line-height: 1.1; letter-spacing: -0.01em; }
  .num-label { font-family: 'DM Mono', monospace; font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #666; line-height: 1.5; }
  .card-footer { padding: 24px 64px; border-top: 1px solid rgba(192,57,43,0.1); display: flex; justify-content: space-between; align-items: center; }
  .footer-fonte { display: flex; flex-direction: column; gap: 3px; }
  .fonte-label { font-family: 'DM Mono', monospace; font-size: 9px; letter-spacing: 0.16em; text-transform: uppercase; color: #444; }
  .fonte-text { font-family: 'DM Mono', monospace; font-size: 10px; color: #666; }
  .footer-brand { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
  .brand-name { font-family: 'Syne', sans-serif; font-size: 14px; font-weight: 800; color: #C0392B; letter-spacing: 0.02em; }
  .brand-sub { font-family: 'DM Mono', monospace; font-size: 9px; color: #444; letter-spacing: 0.1em; text-transform: uppercase; }
  .card-bottombar { width: 100%; height: 3px; background: linear-gradient(to right, #C0392B, rgba(192,57,43,0.2)); }
  .preview-controls { margin-top: 32px; text-align: center; color: #888; font-family: 'Poppins', sans-serif; font-size: 13px; }
  .preview-controls kbd { background: #222; border: 1px solid #444; padding: 2px 8px; border-radius: 3px; color: #ccc; font-size: 12px; }
"""

_MK_TIPOS_CASO = ["Recuperação Judicial", "Recuperação Extrajudicial", "Falência", "Chapter 11", "Chapter 7",
                  "Insolvência", "Reestruturação de Dívida"]


def _mk_monitor_dados() -> dict:
    bruto = _mk_ler("data/noticias.json")
    if not bruto:
        return {"monitor": []}
    try:
        dados = _json_pr.loads(bruto)
    except ValueError:
        raise _PrErro("O arquivo data/noticias.json do site está inválido.")
    dados.setdefault("monitor", [])
    return dados


def _mk_proximo_post(dados: dict) -> int:
    nums = [int(m.group(1)) for it in dados["monitor"]
            for m in [_re_mk.search(r"post-(\d+)", it.get("arquivo", ""))] if m]
    return (max(nums) if nums else 0) + 1


def _mk_html_monitor(c: dict, numero: int, arquivo: str) -> str:
    d = _pr_data(c["data"])
    manchete = _mk_esc(c["manchete"])
    destaque = _mk_esc(c.get("destaque", ""))
    if destaque and destaque in manchete:
        manchete = manchete.replace(destaque, f"<em>{destaque}</em>", 1)
    titulo = f"Monitor de Insolvência · Ed. {numero:02d} · {c['empresa']}"
    url = f"{_MK_SITE_URL}/monitor-insolvencia/{arquivo}"
    numeros = "".join(
        f'<div class="num-item"><div class="num-icon">{_mk_esc(n.get("icone") or "#")[:3]}</div>'
        f'<div class="num-valor">{_mk_esc(n["valor"])}</div><div class="num-label">{_mk_esc(n["rotulo"])}</div></div>'
        for n in c["numeros"][:3])
    paragrafos = "\n".join(f'<p class="body-text">{_mk_negrito(p)}</p>' for p in c["paragrafos"] if p.strip())
    pais = _mk_esc(c["pais"])
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=G-34F5BVJVQJ"></script>
  <script>
    window.dataLayer = window.dataLayer || [];
    function gtag(){{dataLayer.push(arguments);}}
    gtag("js", new Date());
    gtag("config", "G-34F5BVJVQJ");
  </script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_mk_esc(titulo)}</title>
<meta name="description" content="{_mk_esc(c['resumo'])}">
<meta property="og:title" content="{_mk_esc(titulo)}">
<meta property="og:description" content="{_mk_esc(c['manchete'])}">
<meta property="og:image" content="{_MK_SITE_URL}/img/logo.png">
<meta property="og:url" content="{url}">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{_mk_esc(titulo)}">
<meta name="twitter:description" content="{_mk_esc(c['manchete'])}">
<link rel="canonical" href="{url}">
<style>
{_MK_MONITOR_CSS}</style>
</head>
<body>
<div style="display: flex; flex-direction: column; align-items: center;">
<div class="card">
  <div class="card-topbar"></div>
  <div class="card-header">
    <div class="header-serie">
      <span class="serie-label">Maffezzolli Capital · Reestruturação &amp; Insolvência</span>
      <span class="serie-title">Monitor de Insolvência</span>
    </div>
    <div class="header-meta">
      <span class="meta-edicao">Edição {numero:02d} · {pais}</span>
      <span class="meta-data">{_mk_mes_ano(d)}</span>
    </div>
  </div>
  <div class="case-origin">
    <span class="tag-pais">{pais.upper()}</span>
    <span class="tag-tipo">{_mk_esc(c['tipo'])}</span>
    <span class="tag-tipo">{_mk_esc(c['setor'])}</span>
  </div>
  <div class="card-headline">
    <div class="headline-text">{manchete}</div>
    <div class="headline-sub">{_mk_esc(c['subtitulo'])}</div>
  </div>
  <div class="card-logos">
    <div class="logo-box">
      <span>{_mk_esc(c['empresa'])}</span>
      <small>{_mk_esc(c['local_setor'])}</small>
    </div>
    <span class="logo-detail">Marcas: {_mk_esc(c['marcas'])}<br>{_mk_esc(c['detalhe'])}</span>
  </div>
  <div class="card-body">
{paragrafos}
  </div>
  <div class="card-analise">
    <div class="analise-label">Análise Maffezzolli</div>
    <p class="analise-text">{_mk_negrito(c['analise'])}</p>
  </div>
  <div class="card-numeros">{numeros}</div>
  <div class="card-footer">
    <div class="footer-fonte">
      <span class="fonte-label">Fontes</span>
      <span class="fonte-text">{_mk_esc(c['fontes'])}</span>
    </div>
    <div class="footer-brand">
      <span class="brand-name">MAFFEZZOLLI.CAPITAL</span>
      <span class="brand-sub">Reestruturação · Mercado de Capitais</span>
    </div>
  </div>
  <div class="card-bottombar"></div>
</div>
</div>
<div class="share-bar" style="margin-top:18px; display:flex; gap:10px; align-items:center; font-family:'Poppins',sans-serif;">
  <span style="font-size:11px; color:#888; letter-spacing:.08em; text-transform:uppercase;">Compartilhar:</span>
  <button onclick="orcShare('linkedin')" style="background:#0A66C2; color:#fff; border:none; padding:8px 14px; font-size:12px; font-weight:600; cursor:pointer;">LinkedIn</button>
  <button onclick="orcShare('whatsapp')" style="background:#25D366; color:#fff; border:none; padding:8px 14px; font-size:12px; font-weight:600; cursor:pointer;">WhatsApp</button>
  <button onclick="orcShare('twitter')" style="background:#000; color:#fff; border:none; padding:8px 14px; font-size:12px; font-weight:600; cursor:pointer;">X</button>
  <button onclick="orcShare('copy')" style="background:#333; color:#fff; border:none; padding:8px 14px; font-size:12px; font-weight:600; cursor:pointer;">Copiar link</button>
</div>
<script>
function orcShare(kind) {{
  var url = encodeURIComponent(window.location.href);
  var text = encodeURIComponent(document.title);
  var dest = null;
  if (kind === 'linkedin') dest = 'https://www.linkedin.com/sharing/share-offsite/?url=' + url;
  else if (kind === 'whatsapp') dest = 'https://wa.me/?text=' + text + '%20' + url;
  else if (kind === 'twitter') dest = 'https://twitter.com/intent/tweet?url=' + url + '&text=' + text;
  else if (kind === 'copy') {{ navigator.clipboard.writeText(window.location.href).then(function(){{ alert('Link copiado!'); }}); return; }}
  if (dest) window.open(dest, '_blank', 'noopener,width=600,height=600');
}}
</script>
</body>
</html>
"""


def _mk_monitor_entrada(c: dict, numero: int, arquivo: str) -> dict:
    d = _pr_data(c["data"])
    return {"id": f"{_mk_slug(c['empresa'], 24)}-{d.strftime('%Y-%m')}", "edicao": f"Ed. {numero:02d}",
            "data": d.isoformat(), "pais": c["pais"], "tipo": c["tipo"], "empresa": c["empresa"],
            "marcas": c["marcas"], "passivo": c["passivo"], "manchete": c["manchete"], "resumo": c["resumo"],
            "arquivo": f"monitor-insolvencia/{arquivo}"}


def _mk_validar_caso(c: dict):
    obrig = ["empresa", "pais", "tipo", "setor", "data", "passivo", "manchete", "subtitulo", "resumo",
             "local_setor", "marcas", "detalhe", "analise", "fontes"]
    faltando = [k for k in obrig if not str(c.get(k) or "").strip()]
    if faltando:
        return f"Campos obrigatórios vazios: {', '.join(faltando)}."
    d = _pr_data(c["data"])
    if not d:
        return "Data inválida: use DD/MM/AAAA."
    if d > _pr_hoje():
        return "A data do pedido não pode estar no futuro."
    if len([p for p in c.get("paragrafos", []) if p.strip()]) < 2:
        return "Escreva pelo menos 2 parágrafos."
    if len(c.get("numeros", [])) != 3:
        return "Informe exatamente 3 números de destaque."
    return ""


def _mk_ja_publicado(dados: dict, empresa: str, tipo: str):
    alvo = _pr_norm(empresa)
    for it in dados["monitor"]:
        nome = _pr_norm(it.get("empresa", ""))
        if nome and (nome in alvo or alvo in nome) and it.get("tipo") == tipo:
            return it
    return None


def _mk_t_site_monitor_atual(s, cid):
    dados = _mk_monitor_dados()
    itens = sorted(dados["monitor"], key=lambda it: it.get("data", ""), reverse=True)
    pend = s.exec(_sel_pr(PredioAcao).where(PredioAcao.company_id == cid, PredioAcao.tipo == "publicar_site",
                                            PredioAcao.status == "pendente")).all()
    return {"total_publicados": len(itens), "proxima_edicao": _mk_proximo_post(dados),
            "publicados": [{"edicao": it.get("edicao"), "data": it.get("data"), "empresa": it.get("empresa"),
                            "tipo": it.get("tipo"), "pais": it.get("pais"), "passivo": it.get("passivo")}
                           for it in itens],
            "aguardando_aprovacao": [a.titulo for a in pend]}


def _mk_t_site_propor_monitor(s, cid, **caso):
    erro = _mk_validar_caso(caso)
    if erro:
        return {"ok": False, "erro": erro}
    dados = _mk_monitor_dados()
    repetido = _mk_ja_publicado(dados, caso["empresa"], caso["tipo"])
    if repetido:
        return {"ok": False, "erro": f"{caso['empresa']} ({caso['tipo']}) já está no Monitor ({repetido.get('edicao')}, "
                                     f"{repetido.get('data')}). Só proponha de novo se houver fato novo relevante, "
                                     "com outro tipo de caso."}
    for a in s.exec(_sel_pr(PredioAcao).where(PredioAcao.company_id == cid, PredioAcao.tipo == "publicar_site",
                                              PredioAcao.status == "pendente")).all():
        p = _json_pr.loads(a.payload_json or "{}")
        if p.get("modo") == "monitor" and _pr_norm(p["caso"]["empresa"]) == _pr_norm(caso["empresa"]):
            return {"ok": False, "erro": f"Já existe uma proposta para {caso['empresa']} aguardando aprovação (#{a.id})."}
    numero = _mk_proximo_post(dados)
    acao = _pr_registrar_proposta(
        s, cid, tipo="publicar_site", titulo=f"Monitor de Insolvência: {caso['empresa']} ({caso['tipo']})",
        destinatario=f"Site · Monitor de Insolvência · edição prevista {numero:02d}",
        assunto=caso["manchete"][:200], corpo=f"{caso['resumo']}\n\nPassivo: {caso['passivo']} · Fontes: {caso['fontes']}",
        payload_json=_json_pr.dumps({"modo": "monitor", "caso": caso}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação de um admin",
            "observacao": "Nada foi publicado. O número da edição é definido na publicação."}


def _mk_executar_monitor(caso: dict) -> str:
    resultado = {}

    def montar():
        dados = _mk_monitor_dados()
        if _mk_ja_publicado(dados, caso["empresa"], caso["tipo"]):
            raise _PrErro(f"{caso['empresa']} já foi publicado no Monitor enquanto a proposta aguardava.")
        numero = _mk_proximo_post(dados)
        arquivo = f"post-{numero:02d}-{_mk_slug(caso['empresa'], 20)}.html"
        dados["monitor"].append(_mk_monitor_entrada(caso, numero, arquivo))
        resultado.update(numero=numero, arquivo=arquivo)
        return {f"monitor-insolvencia/{arquivo}": _mk_html_monitor(caso, numero, arquivo),
                "data/noticias.json": _json_pr.dumps(dados, ensure_ascii=False, indent=2) + "\n"}

    link = _mk_publicar(montar, f"Monitor de Insolvência: {caso['empresa']} ({caso['tipo']})")
    return (f"Publicado como edição {resultado['numero']:02d}: {_MK_SITE_URL}/monitor-insolvencia/{resultado['arquivo']} "
            f"(o site atualiza em 1 a 3 minutos). Commit: {link}")


# ── Notícias: análises do mês ─────────────────────────────────────────────────

_MK_INI, _MK_FIM = "<!-- ANALISES:INICIO -->", "<!-- ANALISES:FIM -->"
_MK_PRESS, _MK_RODAPE = "<!-- ── PRESS SECTION ── -->", "<!-- ── FOOTER ── -->"


def _mk_artigos() -> list:
    bruto = _mk_ler("data/artigos.json")
    if not bruto:
        return []
    try:
        dados = _json_pr.loads(bruto)
        return dados.get("artigos", []) if isinstance(dados, dict) else []
    except ValueError:
        raise _PrErro("O arquivo data/artigos.json do site está inválido.")


def _mk_trocar_meta(html: str, titulo: str, descricao: str, url: str) -> str:
    t, dsc = _mk_esc(titulo), _mk_esc(descricao)
    html = _re_mk.sub(r"<title>.*?</title>", f"<title>{t} · Maffezzolli Capital</title>", html, count=1, flags=_re_mk.S)
    html = _re_mk.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{dsc}">', html, count=1)
    html = _re_mk.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{t}">', html, count=1)
    html = _re_mk.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{dsc}">', html, count=1)
    html = _re_mk.sub(r'<meta property="og:type" content="[^"]*">', '<meta property="og:type" content="article">', html, count=1)
    html = _re_mk.sub(r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{url}">', html, count=1)
    return _re_mk.sub(r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{url}">', html, count=1)


def _mk_html_artigo(shell: str, a: dict, arquivo: str) -> str:
    if _MK_PRESS not in shell or _MK_RODAPE not in shell:
        raise _PrErro("Não reconheci a estrutura de noticias.html (marcadores PRESS SECTION / FOOTER).")
    topo, resto = shell.split(_MK_PRESS, 1)
    rodape = _MK_RODAPE + resto.split(_MK_RODAPE, 1)[1]
    d = _pr_data(a["data"])
    corpo = "\n".join(f"          <p>{_mk_negrito(p)}</p>" for p in a["paragrafos"] if p.strip())
    meio = f"""{_MK_PRESS}
<div class="press-wrap">
  <header class="press-masthead">
    <div class="press-eyebrow">Maffezzolli Capital · Análises do Mês</div>
    <div class="press-title">Análise &amp; Perspectiva</div>
    <div class="press-meta">
      <span>{_MK_MESES_LONGOS[d.month - 1].capitalize()} de {d.year}</span>
      <span>Brusque, Santa Catarina</span>
      <span><a href="noticias.html">← Todas as notícias</a></span>
    </div>
  </header>
  <main class="press-edition">
    <article class="art-featured">
      <div class="art-left">
        <div class="art-cat">{_mk_esc(a['categoria'])}</div>
        <h1 class="art-h art-h-lg">{_mk_esc(a['titulo'])}</h1>
        <div class="art-deck">{_mk_esc(a['linha_fina'])}</div>
        <div class="art-byline">
          <span class="art-byline-loc">Brusque (SC)</span>
          <span>{d.strftime('%d/%m/%Y')}</span>
        </div>
      </div>
      <div class="art-right">
        <div class="art-body open">
{corpo}
          <div class="art-source">
            <strong>Fontes</strong>
            {_mk_esc(a['fontes'])}
          </div>
        </div>
      </div>
    </article>
  </main>
</div>
"""
    url = f"{_MK_SITE_URL}/{arquivo}"
    return _mk_trocar_meta(topo, a["titulo"], a["linha_fina"], url) + meio + rodape


def _mk_bloco_analises(artigos: list) -> str:
    # mais recente primeiro; no mesmo dia, o publicado por último vem antes
    recentes = [x for _, x in sorted(enumerate(artigos), key=lambda ix: (ix[1].get("data", ""), ix[0]), reverse=True)][:6]
    cards = "\n".join(
        f"""      <article class="art-secondary">
        <div class="art-cat">{_mk_esc(x.get('categoria'))}</div>
        <h2 class="art-h art-h-md"><a href="{_mk_esc(x.get('arquivo'))}">{_mk_esc(x.get('titulo'))}</a></h2>
        <div class="art-deck">{_mk_esc(x.get('linha_fina'))}</div>
        <div class="art-byline"><span class="art-byline-loc">{_mk_esc(_pr_fmt_data(_pr_data(x.get('data'))))}</span>
          <span><a href="{_mk_esc(x.get('arquivo'))}">Ler análise →</a></span></div>
      </article>""" for x in recentes)
    return (f"{_MK_INI}\n    <div class=\"press-divider\">Análises do Mês</div>\n    <div class=\"art-grid\">\n"
            f"{cards}\n    </div>\n    {_MK_FIM}")


def _mk_noticias_com_analises(pagina: str, artigos: list) -> str:
    bloco = _mk_bloco_analises(artigos)
    if _MK_INI in pagina and _MK_FIM in pagina:
        antes = pagina.split(_MK_INI, 1)[0]
        depois = pagina.split(_MK_FIM, 1)[1]
        return antes + bloco + depois
    if "</main>" not in pagina:
        raise _PrErro("Não encontrei onde inserir as análises em noticias.html.")
    # primeira vez: as análises entram logo depois do destaque principal
    if '<div class="press-divider">' in pagina:
        return pagina.replace('<div class="press-divider">', bloco + '\n\n    <div class="press-divider">', 1)
    return pagina.replace("</main>", bloco + "\n  </main>", 1)


def _mk_validar_artigo(a: dict) -> str:
    for k in ("categoria", "titulo", "linha_fina", "fontes", "data"):
        if not str(a.get(k) or "").strip():
            return f"Campo obrigatório vazio: {k}."
    if not _pr_data(a["data"]):
        return "Data inválida: use DD/MM/AAAA."
    if len([p for p in a.get("paragrafos", []) if p.strip()]) < 4:
        return "Escreva pelo menos 4 parágrafos."
    return ""


def _mk_t_site_artigos_atual(s, cid):
    arts = sorted(_mk_artigos(), key=lambda x: x.get("data", ""), reverse=True)
    return {"total": len(arts), "artigos": [{"data": x.get("data"), "titulo": x.get("titulo"),
                                             "categoria": x.get("categoria")} for x in arts[:24]]}


def _mk_t_site_propor_artigo(s, cid, categoria, titulo, linha_fina, data, paragrafos, fontes):
    art = {"categoria": categoria, "titulo": titulo, "linha_fina": linha_fina, "data": data,
           "paragrafos": paragrafos, "fontes": fontes}
    erro = _mk_validar_artigo(art)
    if erro:
        return {"ok": False, "erro": erro}
    acao = _pr_registrar_proposta(
        s, cid, tipo="publicar_site", titulo=f"Notícias do site: {titulo[:120]}",
        destinatario="Site · Notícias · Análises do Mês", assunto=titulo[:200], corpo=linha_fina,
        payload_json=_json_pr.dumps({"modo": "artigo", "artigo": art}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação de um admin",
            "observacao": "Nada foi publicado ainda."}


def _mk_arquivo_artigo(art: dict, existentes: list) -> str:
    d = _pr_data(art["data"])
    base = f"noticia-{d.strftime('%Y-%m')}-{_mk_slug(art['titulo'], 40)}"
    usados = {x.get("arquivo") for x in existentes}
    nome, n = f"{base}.html", 2
    while nome in usados:
        nome, n = f"{base}-{n}.html", n + 1
    return nome


def _mk_executar_artigo(art: dict) -> str:
    resultado = {}

    def montar():
        artigos = _mk_artigos()
        pagina = _mk_ler("noticias.html")
        if not pagina:
            raise _PrErro("Não encontrei noticias.html no site.")
        arquivo = _mk_arquivo_artigo(art, artigos)
        artigos.append({"data": _pr_data(art["data"]).isoformat(), "categoria": art["categoria"],
                        "titulo": art["titulo"], "linha_fina": art["linha_fina"], "arquivo": arquivo})
        resultado["arquivo"] = arquivo
        return {arquivo: _mk_html_artigo(pagina, art, arquivo),
                "data/artigos.json": _json_pr.dumps({"artigos": artigos}, ensure_ascii=False, indent=2) + "\n",
                "noticias.html": _mk_noticias_com_analises(pagina, artigos)}

    link = _mk_publicar(montar, f"Notícias: {art['titulo'][:80]}")
    return f"Publicado: {_MK_SITE_URL}/{resultado['arquivo']} (o site atualiza em 1 a 3 minutos). Commit: {link}"


def _mk_exec_publicar_site(s, acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    if p.get("modo") == "monitor":
        return _mk_executar_monitor(p["caso"])
    if p.get("modo") == "artigo":
        return _mk_executar_artigo(p["artigo"])
    raise _PrErro("Proposta de publicação inválida.")


def _mk_previa(acao) -> str:
    p = _json_pr.loads(acao.payload_json or "{}")
    if p.get("modo") == "monitor":
        numero = _mk_proximo_post(_mk_monitor_dados())
        html = _mk_html_monitor(p["caso"], numero, f"post-{numero:02d}-previa.html")
        base = f"{_MK_SITE_URL}/monitor-insolvencia/"
    else:
        pagina = _mk_ler("noticias.html") or ""
        html = _mk_html_artigo(pagina, p["artigo"], "previa.html")
        base = f"{_MK_SITE_URL}/"
    aviso = ('<div style="position:sticky;top:0;z-index:9999;background:#FFF3CD;color:#664D03;padding:8px 16px;'
             'font:14px Arial,sans-serif;text-align:center">Prévia — ainda não publicada no site</div>')
    html = html.replace("<head>", f'<head>\n<base href="{base}">', 1)
    return _re_mk.sub(r"(<body[^>]*>)", r"\1" + aviso, html, count=1)


# ── Indicadores e notícias de mercado ─────────────────────────────────────────

_MK_CACHE: dict = {}

_MK_SERIES_SGS = [
    (432, "Selic meta (% a.a.)", 3),
    (4389, "CDI anualizado (% a.a.)", 3),
    (433, "IPCA mensal (%)", 13),
    (13522, "IPCA acumulado 12 meses (%)", 3),
    (189, "IGP-M mensal (%)", 13),
    (1, "Dólar comercial venda (R$)", 3),
]


def _mk_cache(chave: str, horas: float, gerar):
    agora = _time_pr.time()
    item = _MK_CACHE.get(chave)
    if item and agora - item[0] < horas * 3600:
        return item[1]
    valor = gerar()
    _MK_CACHE[chave] = (agora, valor)
    return valor


def _mk_sgs(codigo: int, n: int) -> list:
    import httpx as _httpx_mk
    r = _httpx_mk.get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/{n}",
                      params={"formato": "json"}, timeout=15)
    r.raise_for_status()
    return [{"data": x.get("data"), "valor": x.get("valor")} for x in r.json()]


def _mk_t_indicadores(s, cid):
    def gerar():
        saida, falhas = {}, []
        for codigo, nome, n in _MK_SERIES_SGS:
            try:
                saida[nome] = _mk_sgs(codigo, n)
            except Exception as e:
                falhas.append(f"{nome}: {e.__class__.__name__}")
        return saida, falhas

    series, falhas = _mk_cache("sgs", 6, gerar)
    if falhas:
        _MK_CACHE.pop("sgs", None)  # não guarda resultado incompleto
    credito = []
    TaxaBC_ = globals().get("TaxaBC")
    if TaxaBC_ is not None:
        try:
            credito = [{"modalidade": t.modalidade, "taxa_am": t.taxa_am, "taxa_aa": t.taxa_aa, "mes_ref": t.mes_ref}
                       for t in s.exec(_sel_pr(TaxaBC_)).all()]
        except Exception:
            credito = []
    return {"fonte": "Banco Central do Brasil (SGS) e taxas médias de crédito do BC já registradas na plataforma",
            "series": series, "taxas_credito_media_mercado": credito,
            "indisponiveis": falhas,
            "observacao": "INCC, dados setoriais e projeções (Focus) não estão aqui: pesquise na web e cite a fonte."}


_MK_FEEDS_PADRAO = [
    {"name": "InfoMoney", "url": "https://www.infomoney.com.br/feed/"},
    {"name": "BM&C News", "url": "https://bmcnews.com.br/feed/"},
    {"name": "Money Times", "url": "https://www.moneytimes.com.br/feed/"},
    {"name": "Exame", "url": "https://exame.com/feed/"},
]


def _mk_ler_feed(feed: dict) -> list:
    import httpx as _httpx_mk
    from email.utils import parsedate_to_datetime as _pdt_mk
    r = _httpx_mk.get(feed["url"], timeout=12, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (compatible; MaffezzolliBot/1.0)"})
    r.raise_for_status()
    raiz = _ET_mk.fromstring(r.content)
    itens = []
    for it in raiz.iter("item"):
        quando = None
        try:
            quando = _pdt_mk(it.findtext("pubDate") or "").replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
        itens.append({"fonte": feed["name"], "titulo": (it.findtext("title") or "").strip(),
                      "link": (it.findtext("link") or "").strip(),
                      "data": quando.strftime("%d/%m/%Y") if quando else "", "_quando": quando})
    return itens


def _mk_t_noticias(s, cid, dias, termo):
    feeds = globals().get("_NEWS_FEEDS_NC") or _MK_FEEDS_PADRAO

    def gerar():
        todos, falhas = [], []
        for f in feeds:
            try:
                todos += _mk_ler_feed(f)
            except Exception as e:
                falhas.append(f"{f.get('name')}: {e.__class__.__name__}")
        return todos, falhas

    todos, falhas = _mk_cache("feeds", 1, gerar)
    corte = _dt_pr.utcnow() - _td_pr(days=max(1, min(int(dias or 7), 60)))
    termos = [_pr_norm(t) for t in (termo or "").split() if len(t) > 2]
    sel = []
    for it in todos:
        if it["_quando"] and it["_quando"] < corte:
            continue
        if termos and not any(t in _pr_norm(it["titulo"]) for t in termos):
            continue
        sel.append({k: v for k, v in it.items() if k != "_quando"})
    return {"noticias": sel[:60], "total": len(sel), "feeds_com_falha": falhas,
            "observacao": "Só títulos e links dos feeds. Para detalhes, leia a página com web_fetch."}


# ── Calendário de posts (Excel) e envio à agência ─────────────────────────────

_MK_COLUNAS = [("data", "Data", 12), ("dia", "Dia", 8), ("rede", "Rede", 16), ("formato", "Formato", 14),
               ("tema", "Tema", 30), ("objetivo", "Objetivo", 28), ("mensagem_principal", "Mensagem principal", 40),
               ("texto", "Texto-base / legenda", 70), ("visual", "Sugestão de visual", 45), ("cta", "Chamada (CTA)", 26),
               ("hashtags", "Hashtags", 28), ("fonte", "Fonte / case", 26)]
_MK_DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _mk_salvar_gerado(s, cid: int, nome: str, mime: str, dados: bytes) -> PredioAnexo:
    chamado_id = getattr(_PR_EXEC, "chamado_id", None)
    turno = getattr(_PR_EXEC, "turno", 0)
    a = PredioAnexo(company_id=cid, chamado_id=chamado_id or 0, turno=turno if isinstance(turno, int) else 0,
                    nome=nome, mime=mime, tamanho=len(dados), tipo="gerado", conteudo=dados)
    s.add(a)
    s.commit()
    s.refresh(a)
    return a


def _mk_t_gerar_calendario(s, cid, titulo, periodo, orientacoes, posts):
    if not posts:
        return {"ok": False, "erro": "Nenhum post informado."}
    if len(posts) > 90:
        return {"ok": False, "erro": "Máximo de 90 posts por calendário."}
    from openpyxl import Workbook as _WB_mk
    from openpyxl.styles import Alignment as _Al_mk, Font as _Fo_mk, PatternFill as _PF_mk
    linhas, invalidas = [], []
    for i, p in enumerate(posts, 1):
        d = _pr_data(p.get("data"))
        if not d:
            invalidas.append(i)
            continue
        linhas.append((d, p))
    if invalidas:
        return {"ok": False, "erro": f"Datas inválidas nos posts {invalidas}: use DD/MM/AAAA."}
    linhas.sort(key=lambda x: x[0])
    wb = _WB_mk()
    ws = wb.active
    ws.title = "Calendário"
    ws["A1"] = titulo
    ws["A1"].font = _Fo_mk(bold=True, size=14)
    ws["A2"] = f"Período: {periodo} · {len(linhas)} posts · gerado em {_pr_agora_brt().strftime('%d/%m/%Y')}"
    ws["A3"] = orientacoes or ""
    ws["A3"].alignment = _Al_mk(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=len(_MK_COLUNAS))
    ws.row_dimensions[3].height = 60 if orientacoes else 15
    cab = 5
    for j, (_, rotulo, larg) in enumerate(_MK_COLUNAS, 1):
        c = ws.cell(row=cab, column=j, value=rotulo)
        c.font = _Fo_mk(bold=True, color="FFFFFF")
        c.fill = _PF_mk("solid", fgColor="1A1816")
        c.alignment = _Al_mk(vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = larg
    for i, (d, p) in enumerate(linhas, cab + 1):
        valores = dict(p, data=d.strftime("%d/%m/%Y"), dia=_MK_DIAS[d.weekday()])
        for j, (chave, _, _) in enumerate(_MK_COLUNAS, 1):
            cel = ws.cell(row=i, column=j, value=str(valores.get(chave) or ""))
            cel.alignment = _Al_mk(wrap_text=True, vertical="top")
    ws.freeze_panes = ws.cell(row=cab + 1, column=3)
    ws.auto_filter.ref = f"A{cab}:{ws.cell(row=cab, column=len(_MK_COLUNAS)).column_letter}{cab + len(linhas)}"
    buf = _io_mk.BytesIO()
    wb.save(buf)
    nome = f"{_mk_slug(titulo, 60)}.xlsx"
    a = _mk_salvar_gerado(s, cid, nome, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          buf.getvalue())
    por_semana: dict = {}
    for d, _ in linhas:
        k = d.isocalendar()[:2]
        por_semana[k] = por_semana.get(k, 0) + 1
    return {"ok": True, "anexo_id": a.id, "arquivo": nome, "posts": len(linhas),
            "primeiro": linhas[0][0].strftime("%d/%m/%Y"), "ultimo": linhas[-1][0].strftime("%d/%m/%Y"),
            "semanas_fora_de_3_posts": [f"semana {k[1]}/{k[0]}: {v}" for k, v in sorted(por_semana.items()) if v != 3],
            "observacao": "O arquivo aparece no chamado, em 'Arquivos gerados'."}


def _mk_cfg(s, cid: int):
    return s.exec(_sel_pr(PredioConfig).where(PredioConfig.company_id == cid)).first()


def _mk_t_propor_envio_agencia(s, cid, assunto, corpo, anexo_ids):
    cfg = _mk_cfg(s, cid)
    email = (cfg.agencia_email if cfg else "") or ""
    if "@" not in email:
        return {"ok": False, "erro": "O e-mail da agência não está cadastrado. Peça a um admin para preencher em "
                                     "Prédio → Marketing. Entregue o texto e o arquivo para envio manual."}
    if not (assunto or "").strip() or len((corpo or "").strip()) < 40:
        return {"ok": False, "erro": "Assunto e corpo do e-mail são obrigatórios."}
    anexos = []
    for aid in anexo_ids or []:
        a = s.get(PredioAnexo, int(aid))
        if not a or a.company_id != cid or a.conteudo is None:
            return {"ok": False, "erro": f"Arquivo {aid} não encontrado."}
        anexos.append({"id": a.id, "nome": a.nome})
    acao = _pr_registrar_proposta(
        s, cid, tipo="email_agencia", titulo=f"E-mail para a agência{' ' + cfg.agencia_nome if cfg.agencia_nome else ''}",
        destinatario=email, assunto=assunto.strip()[:200], corpo=corpo.strip()[:20000],
        payload_json=_json_pr.dumps({"anexos": anexos}, ensure_ascii=False))
    return {"ok": True, "proposta_id": acao.id, "status": "aguardando aprovação",
            "observacao": f"Vai para {email} depois da aprovação, com {len(anexos)} arquivo(s). Nada foi enviado."}


def _mk_exec_email_agencia(s, acao) -> str:
    anexos = []
    for x in _json_pr.loads(acao.payload_json or "{}").get("anexos") or []:
        a = s.get(PredioAnexo, int(x.get("id") or 0))
        if a and a.company_id == acao.company_id and a.conteudo is not None:
            anexos.append({"filename": a.nome, "data": a.conteudo, "mimetype": a.mime or "application/octet-stream"})
    corpo_html = ("<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#1f2933\">"
                  + _html_mk.escape(acao.corpo).replace("\n", "<br>") + "</div>")
    _smtp_send_email(to_email=acao.destinatario, subject=acao.assunto, html_body=corpo_html, text_body=acao.corpo,
                     attachments=anexos or None)
    return f"E-mail enviado para {acao.destinatario}" + (f" com {len(anexos)} arquivo(s)." if anexos else ".")


# ── Registro das ferramentas ──────────────────────────────────────────────────

def _mk_obj(props: dict, desc: str = "") -> dict:
    o = _pr_schema(props)
    if desc:
        o["description"] = desc
    return o


_MK_STR = {"type": "string"}

_MK_SCHEMA_CASO = {
    "empresa": {"type": "string", "description": "Nome da empresa ou grupo (ex.: Grupo Toky)."},
    "pais": {"type": "string", "description": "País do processo (ex.: Brasil, EUA, Alemanha)."},
    "tipo": {"type": "string", "enum": _MK_TIPOS_CASO, "description": "Tipo do processo."},
    "setor": {"type": "string", "description": "Setor curto para a etiqueta (ex.: Varejo · Móveis)."},
    "data": {"type": "string", "description": "Data do pedido/decretação, DD/MM/AAAA (confirmada na fonte)."},
    "passivo": {"type": "string", "description": "Passivo no formato curto do site (ex.: R$ 1,1Bi, US$ 450M)."},
    "manchete": {"type": "string", "description": "Manchete objetiva, até ~110 caracteres."},
    "destaque": {"type": "string", "description": "Trecho EXATO da manchete para destacar em vermelho (ou vazio)."},
    "subtitulo": {"type": "string", "description": "Linha fina de 1 frase com o contexto."},
    "resumo": {"type": "string", "description": "Resumo de 1 a 2 frases para a lista do Monitor."},
    "local_setor": {"type": "string", "description": "Cidade/estado, país · setor (ex.: São Paulo, Brasil · Varejo)."},
    "marcas": {"type": "string", "description": "Marcas ou empresas do grupo, separadas por ' · '."},
    "detalhe": {"type": "string", "description": "Linha de detalhe: porte, funcionários, vara/tribunal e data."},
    "paragrafos": {"type": "array", "items": _MK_STR,
                   "description": "3 parágrafos factuais: o que aconteceu, causas, próximos passos. **negrito** permitido."},
    "analise": {"type": "string", "description": "Análise Maffezzolli: a lição para médias empresas, 3 a 5 frases."},
    "numeros": {"type": "array", "description": "Exatamente 3 números de destaque.",
                "items": _mk_obj({"icone": {"type": "string", "description": "R$, US$, %, # ou ~"},
                                  "valor": {"type": "string", "description": "Ex.: R$ 1,1Bi"},
                                  "rotulo": {"type": "string", "description": "Ex.: Passivo declarado"}})},
    "fontes": {"type": "string", "description": "Fontes consultadas (veículos, tribunal) e mês/ano."},
}

_MK_SCHEMA_POST = _mk_obj({
    "data": {"type": "string", "description": "DD/MM/AAAA"},
    "rede": {"type": "string", "enum": ["Instagram", "LinkedIn", "Instagram e LinkedIn", "YouTube", "Blog"]},
    "formato": {"type": "string", "enum": ["Carrossel", "Post único", "Reels/Vídeo", "Stories", "Artigo"]},
    "tema": _MK_STR, "objetivo": _MK_STR, "mensagem_principal": _MK_STR,
    "texto": {"type": "string", "description": "Texto-base / legenda pronta para a agência ajustar."},
    "visual": {"type": "string", "description": "Sugestão de visual, telas do carrossel ou roteiro do vídeo."},
    "cta": _MK_STR, "hashtags": _MK_STR,
    "fonte": {"type": "string", "description": "Case (anonimizado), dado ou notícia que embasa o post."},
})

_MK_FERRAMENTAS = {
    "mkt_indicadores": {
        "fn": _mk_t_indicadores, "rotulo": "Consultou os indicadores do Banco Central",
        "description": "Selic, CDI, IPCA (mensal e 12 meses), IGP-M e dólar direto do Banco Central, e as taxas "
                       "médias de crédito por modalidade já registradas na plataforma.",
        "props": {}},
    "mkt_noticias": {
        "fn": _mk_t_noticias, "rotulo": "Leu as notícias do mercado",
        "description": "Títulos e links recentes dos feeds InfoMoney, BM&C News, Money Times e Exame, com filtro "
                       "opcional por palavra.",
        "props": {"dias": {"type": "integer", "description": "Janela em dias (1 a 60)."},
                  "termo": {"type": "string", "description": "Palavras para filtrar o título (vazio = todas)."}}},
    "site_monitor_atual": {
        "fn": _mk_t_site_monitor_atual, "rotulo": "Conferiu o Monitor de Insolvência do site",
        "description": "Casos já publicados no Monitor de Insolvência do site (para não repetir), a próxima edição e "
                       "as propostas que aguardam aprovação.",
        "props": {}},
    "site_propor_monitor": {
        "fn": _mk_t_site_propor_monitor, "rotulo": "Propôs um caso para o Monitor de Insolvência",
        "description": "Cria uma PROPOSTA de novo caso no Monitor de Insolvência do site, no padrão visual das edições "
                       "anteriores. Só é publicado depois da aprovação de um admin. Todos os fatos e números devem vir "
                       "de fontes que você leu.",
        "props": _MK_SCHEMA_CASO},
    "site_artigos_atual": {
        "fn": _mk_t_site_artigos_atual, "rotulo": "Conferiu as análises publicadas no site",
        "description": "Análises do mês já publicadas na página de Notícias do site.",
        "props": {}},
    "site_propor_artigo": {
        "fn": _mk_t_site_propor_artigo, "rotulo": "Propôs uma análise para as Notícias do site",
        "description": "Cria uma PROPOSTA de análise na página de Notícias do site (seção Análises do Mês). Só é "
                       "publicada depois da aprovação de um admin.",
        "props": {"categoria": {"type": "string", "description": "Ex.: Juros & Crédito, Reestruturação, Mercado Imobiliário."},
                  "titulo": {"type": "string", "description": "Título jornalístico, até ~120 caracteres."},
                  "linha_fina": {"type": "string", "description": "Linha fina de 1 a 2 frases."},
                  "data": {"type": "string", "description": "Data da publicação, DD/MM/AAAA (normalmente hoje)."},
                  "paragrafos": {"type": "array", "items": _MK_STR,
                                 "description": "5 a 9 parágrafos. **negrito** permitido; sem citações atribuídas a pessoas."},
                  "fontes": {"type": "string", "description": "Fontes dos dados (BC, IBGE, veículos) e mês/ano."}}},
    "mkt_gerar_calendario": {
        "fn": _mk_t_gerar_calendario, "rotulo": "Gerou o calendário de posts em Excel",
        "description": "Gera a planilha Excel do calendário editorial (um post por linha, com briefing completo para a "
                       "agência) e anexa ao chamado. Devolve o anexo_id para usar no envio à agência.",
        "props": {"titulo": {"type": "string", "description": "Ex.: Calendário Jan-Fev 2027 — Maffezzolli Capital"},
                  "periodo": {"type": "string", "description": "Ex.: 05/01/2027 a 28/02/2027"},
                  "orientacoes": {"type": "string", "description": "Orientações gerais à agência (tom, identidade, prioridades)."},
                  "posts": {"type": "array", "items": _MK_SCHEMA_POST, "description": "Posts do período."}}},
    "mkt_propor_envio_agencia": {
        "fn": _mk_t_propor_envio_agencia, "rotulo": "Propôs um e-mail para a agência",
        "description": "Cria uma PROPOSTA de e-mail para a agência de redes sociais (e-mail cadastrado no Prédio), "
                       "com arquivos gerados no chamado. Nada é enviado agora: alguém da equipe aprova.",
        "props": {"assunto": _MK_STR,
                  "corpo": {"type": "string", "description": "E-mail em texto simples, cordial e objetivo, com assinatura."},
                  "anexo_ids": {"type": "array", "items": {"type": "integer"},
                                "description": "anexo_id dos arquivos a enviar (ex.: o calendário)."}}},
}

for _nome_mk, _spec_mk in _MK_FERRAMENTAS.items():
    _pr_registrar_ferramenta(_nome_mk, _spec_mk)

_PR_EXECUTORES_EXTRA["publicar_site"] = _mk_exec_publicar_site
_PR_EXECUTORES_EXTRA["email_agencia"] = _mk_exec_email_agencia


# ── Agentes ───────────────────────────────────────────────────────────────────

_MK_AGENTES = {
    "inteligencia_mercado": {
        "web": True,
        "ferramentas": ["mkt_indicadores", "mkt_noticias", "conh_buscar", "conh_ler"],
        "instrucoes": (
            "Você é a inteligência de mercado do escritório. Junte dados oficiais (mkt_indicadores), as notícias "
            "(mkt_noticias) e pesquisa na web para responder o que mudou e o que isso significa para médias empresas "
            "do Sul do Brasil, com foco em indústria, construção civil e incorporação.\n"
            "- Boletim: em cada tema (juros, inflação, crédito, câmbio, insolvências, mercado imobiliário), traga o "
            "dado com data e fonte e um parágrafo de 'e daí para os nossos clientes'.\n"
            "- Cite a fonte e a data de todo número. Prefira fontes primárias (BC, IBGE, FGV, tribunais) e veículos "
            "reconhecidos. Se não achar um dado, diga que não achou.\n"
            "- Seu material serve de base para o Conteúdo, a Agência e Redes e o Editor do Site.")},
    "conteudo": {
        "web": True,
        "ferramentas": ["conh_buscar", "conh_ler", "mkt_indicadores", "mkt_noticias", "mkt_gerar_calendario",
                        "mkt_propor_envio_agencia"],
        "instrucoes": (
            "Você escreve o conteúdo da Maffezzolli Capital: posts, artigos, newsletter e respostas a pedidos da "
            "agência. Tom: técnico e acessível, para empresários e diretores financeiros; frases curtas, exemplos "
            "concretos, sem jargão vazio nem promessas de resultado.\n"
            "- Use cases da base de conhecimento (conh_buscar) SEMPRE anonimizados: nunca o nome do cliente, de "
            "sócios, CNPJ, cidade pequena ou valores exatos que permitam identificar. Arredonde (\"cerca de R$ 20 "
            "milhões\") e descreva pelo setor e porte.\n"
            "- Não invente números de mercado: use mkt_indicadores ou pesquisa com fonte.\n"
            "- Não atribua frases a pessoas reais (sócios, clientes) que elas não disseram. Se uma citação ajudar, "
            "marque como [sugestão de citação para aprovação].\n"
            "- Entregue os textos prontos no chamado. Para pedidos da agência, você pode gerar a planilha e propor o "
            "envio.")},
    "agencia_redes": {
        "web": True,
        "ferramentas": ["conh_buscar", "conh_ler", "conh_propor_registro", "mkt_indicadores", "mkt_noticias",
                        "mkt_gerar_calendario", "mkt_propor_envio_agencia"],
        "instrucoes": (
            "Você faz a ponte entre o marketing do escritório e a agência que programa e publica as redes sociais. "
            "A agência programa por BIMESTRE e publica em média 3 posts por semana (Instagram e LinkedIn).\n"
            "Calendário do bimestre:\n"
            "- 3 posts por semana (normalmente segunda, quarta e sexta), cobrindo as 8 a 9 semanas do bimestre.\n"
            "- Equilibre os pilares: ~40% educação financeira para empresários (caixa, capital de giro, dívida, "
            "crédito), ~25% mercado e conjuntura (juros, crédito, insolvências — Monitor de Insolvência), ~20% cases "
            "anonimizados e bastidores da boutique, ~15% institucional (Augur, serviços, equipe, eventos).\n"
            "- Considere datas relevantes do período (Copom, divulgação do IPCA, datas comemorativas do setor).\n"
            "- Cada post com briefing completo para a agência: tema, objetivo, mensagem principal, texto-base, "
            "sugestão de visual (telas do carrossel ou roteiro do vídeo), CTA, hashtags e fonte. Gere a planilha com "
            "mkt_gerar_calendario e confira 'semanas_fora_de_3_posts'.\n"
            "- Para enviar à agência, proponha o e-mail com mkt_propor_envio_agencia anexando a planilha.\n"
            "Desempenho das redes: quando receberem o relatório da agência (PDF, planilha ou prints), analise alcance, "
            "engajamento, seguidores e os melhores e piores posts; compare com meses anteriores (busque com "
            "conh_buscar 'Desempenho redes') e diga o que repetir e o que mudar no próximo calendário. Ao final, "
            "proponha registrar o resumo com conh_propor_registro, título 'Desempenho redes — MM/AAAA', tipo 'licao', "
            "cliente vazio.\n"
            "Cases sempre anonimizados; nunca invente métricas que não estejam no relatório.")},
    "editor_site": {
        "web": True,
        "ferramentas": ["site_monitor_atual", "site_propor_monitor", "site_artigos_atual", "site_propor_artigo",
                        "mkt_indicadores", "mkt_noticias"],
        "instrucoes": (
            "Você mantém duas seções do site maffezzollicapital.com.br:\n"
            "1. Monitor de Insolvência: casos de recuperação judicial, extrajudicial e falência. Antes de propor, "
            "confira site_monitor_atual para não repetir. Priorize Brasil (especialmente o Sul) e grandes casos "
            "internacionais com lição útil para médias empresas. Para cada caso, pesquise e leia pelo menos duas "
            "fontes; data, passivo, vara e números têm de estar nas fontes lidas — se não confirmar um dado, deixe-o "
            "de fora. A 'Análise Maffezzolli' explica a causa da crise e a lição para gestores, sem julgar pessoas.\n"
            "2. Notícias (Análises do Mês): um artigo jornalístico por mês sobre a conjuntura que importa para médias "
            "empresas: juros, crédito, inflação, insolvências e o que fazer a respeito. Use mkt_indicadores para os "
            "números oficiais.\n"
            "Regras: textos factuais e sóbrios; nenhum dado de cliente do escritório; nada de citações atribuídas a "
            "pessoas; tudo vira proposta para um admin aprovar — nunca diga que foi publicado. Ao terminar, liste o "
            "que propôs com as fontes.")},
}

for _key_mk, _cfg_ag_mk in _MK_AGENTES.items():
    _ag_mk = _PREDIO_AGENTES.get(_key_mk)
    if not _ag_mk:
        continue
    _ag_mk["ferramentas"] = list(_cfg_ag_mk["ferramentas"])
    _ag_mk["web"] = _cfg_ag_mk["web"]
    _ag_mk["ativo"] = True
    _PR_INSTRUCOES[_key_mk] = _cfg_ag_mk["instrucoes"]


# ── Atualização mensal do site ────────────────────────────────────────────────

def _mk_pedido_mensal() -> str:
    hoje = _pr_hoje()
    anterior = (hoje.replace(day=1) - _td_pr(days=1))
    mes = f"{_MK_MESES_LONGOS[anterior.month - 1]} de {anterior.year}"
    return (
        f"Atualização mensal do site — referência: {mes}.\n\n"
        "1. Monitor de Insolvência: veja o que já está publicado (site_monitor_atual) e pesquise na web os pedidos "
        f"de recuperação judicial, extrajudicial e falências relevantes de {mes} e das últimas semanas. Escolha de 3 a "
        "5 casos ainda não publicados e proponha cada um com site_propor_monitor.\n"
        f"2. Notícias: escreva a análise do mês sobre a conjuntura de {mes} (juros, crédito, inflação, insolvências e o "
        "que isso muda para médias empresas) e proponha com site_propor_artigo, com data de hoje.\n\n"
        "No fim, resuma o que foi proposto, com as fontes de cada item."
    )


def _mk_criar_chamado_site(s, company_id: int, user_id: int, roteamento: str) -> PredioChamado:
    ch = PredioChamado(
        company_id=company_id, created_by_user_id=user_id, papel_solicitante="admin",
        titulo=f"Atualização do site — {_pr_agora_brt().strftime('%m/%Y')}", pedido=_mk_pedido_mensal(),
        agente_key="editor_site", roteamento=roteamento,
        motivo_roteamento="Atualização mensal do site." if roteamento == "agenda" else "")
    s.add(ch)
    s.commit()
    s.refresh(ch)
    return ch


def _mk_rotina_mensal() -> None:
    agora = _pr_agora_brt()
    if agora.hour < 9:
        return
    inicio_mes_utc = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + _td_pr(hours=3)
    with _Sess_pr(engine) as s:
        for cfg in s.exec(_sel_pr(PredioConfig).where(PredioConfig.site_mensal == True)).all():  # noqa: E712
            # só um worker do gunicorn consegue reivindicar a atualização do mês
            res = s.connection().execute(_sqltext_pr(
                "UPDATE predio_config SET ultimo_site_em = :agora "
                "WHERE id = :id AND (ultimo_site_em IS NULL OR ultimo_site_em < :inicio)"
            ), {"agora": _dt_pr.utcnow(), "id": cfg.id, "inicio": inicio_mes_utc})
            s.commit()
            if res.rowcount != 1:
                continue
            admin = s.exec(_sel_pr(Membership).where(Membership.company_id == cfg.company_id,
                                                     Membership.role == "admin")).first()
            if admin:
                _pr_disparar(_mk_criar_chamado_site(s, cfg.company_id, admin.user_id, "agenda").id)


def _mk_agendador() -> None:
    _time_pr.sleep(120)
    while True:
        try:
            _mk_rotina_mensal()
        except Exception as e:
            print(f"[predio_marketing] agendador: {e}")
        _time_pr.sleep(900)


_thr_pr.Thread(target=_mk_agendador, daemon=True, name="predio-marketing").start()


# ── Rotas ─────────────────────────────────────────────────────────────────────

def _mk_config_view(cfg) -> dict:
    return {"agencia_nome": (cfg.agencia_nome if cfg else "") or "", "agencia_email": (cfg.agencia_email if cfg else "") or "",
            "site_mensal": bool(cfg and cfg.site_mensal), "github_ok": bool(_mk_token())}


@app.post("/predio/marketing/config")
@require_login
async def predio_marketing_config(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    form = await request.form()
    cfg = _mk_cfg(session, ctx.company.id) or PredioConfig(company_id=ctx.company.id)
    if form.get("campo") == "site_mensal":
        cfg.site_mensal = form.get("site_mensal") == "1"
    elif form.get("campo") == "agencia":
        cfg.agencia_nome = str(form.get("agencia_nome") or "").strip()[:120]
        email = str(form.get("agencia_email") or "").strip()[:200]
        cfg.agencia_email = email if _re_mk.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else ""
    session.add(cfg)
    session.commit()
    return RedirectResponse("/predio#marketing", status_code=303)


@app.post("/predio/marketing/site-agora")
@require_login
async def predio_marketing_site_agora(request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx or ctx.membership.role != "admin":
        return RedirectResponse("/predio", status_code=303)
    ch = _mk_criar_chamado_site(session, ctx.company.id, ctx.user.id, "manual")
    _pr_disparar(ch.id)
    return RedirectResponse(f"/predio/chamados/{ch.id}", status_code=303)


@app.get("/predio/acoes/{acao_id}/previa", response_class=HTMLResponse)
@require_login
async def predio_previa_acao(acao_id: int, request: Request, session: Session = Depends(get_session)):
    ctx = _pr_ctx(request, session)
    if not ctx:
        return RedirectResponse("/", status_code=303)
    acao = session.get(PredioAcao, acao_id)
    if not acao or acao.company_id != ctx.company.id or acao.tipo != "publicar_site":
        return RedirectResponse("/predio", status_code=303)
    from starlette.concurrency import run_in_threadpool as _rtp_mk
    try:
        html = await _rtp_mk(_mk_previa, acao)
    except Exception as e:
        return HTMLResponse(f"<p style='font-family:Arial'>Não foi possível montar a prévia: {_mk_esc(e)}</p>",
                            status_code=200)
    return HTMLResponse(html, headers={"X-Robots-Tag": "noindex"})


print("[predio_marketing] Andar de Marketing carregado.")
