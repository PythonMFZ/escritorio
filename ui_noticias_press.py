# ============================================================================
# Sala de Imprensa — Rota pública /noticias
# ============================================================================

from fastapi import Request
from fastapi.responses import HTMLResponse as _HTMLResponse_press

_NOTICIAS_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sala de Imprensa · Maffezzolli Capital</title>
<meta name="description" content="Análise e perspectiva sobre finanças corporativas, tecnologia financeira e o mercado de médias empresas no Sul do Brasil.">
<style>
/* ── Tokens ── */
:root {
  --bg:       #F0EDE6;
  --surface:  #FFFFFF;
  --border:   #CFC8BC;
  --rule:     #1A1816;
  --ink:      #1A1816;
  --ink-2:    #4A453E;
  --ink-3:    #8A837A;
  --gold:     #8B6914;
  --gold-hi:  #A07C20;
  --gold-dim: #D4B86A;
  --col-rule: #CFC8BC;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:       #0D0F14;
    --surface:  #141820;
    --border:   #252C3A;
    --rule:     #C9A84C;
    --ink:      #D8D4CC;
    --ink-2:    #9A96A0;
    --ink-3:    #4A5068;
    --gold:     #C9A84C;
    --gold-hi:  #DFB85C;
    --gold-dim: #5A4812;
    --col-rule: #252C3A;
  }
}
:root[data-theme="dark"] {
  --bg:       #0D0F14;
  --surface:  #141820;
  --border:   #252C3A;
  --rule:     #C9A84C;
  --ink:      #D8D4CC;
  --ink-2:    #9A96A0;
  --ink-3:    #4A5068;
  --gold:     #C9A84C;
  --gold-hi:  #DFB85C;
  --gold-dim: #5A4812;
  --col-rule: #252C3A;
}
:root[data-theme="light"] {
  --bg:       #F0EDE6;
  --surface:  #FFFFFF;
  --border:   #CFC8BC;
  --rule:     #1A1816;
  --ink:      #1A1816;
  --ink-2:    #4A453E;
  --ink-3:    #8A837A;
  --gold:     #8B6914;
  --gold-hi:  #A07C20;
  --gold-dim: #D4B86A;
  --col-rule: #CFC8BC;
}

/* ── Reset ── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 16px; }
body {
  background: var(--bg);
  color: var(--ink);
  font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
  line-height: 1.6;
  padding: 0 0 4rem;
}

/* ── Top nav bar ── */
.press-nav {
  background: var(--bg);
  border-bottom: 1px solid var(--border);
  padding: .6rem 1.5rem;
  max-width: 1060px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: .5rem;
  font-family: 'Courier New', Courier, monospace;
  font-size: .62rem;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.press-nav a {
  color: var(--gold);
  text-decoration: none;
}
.press-nav a:hover { color: var(--gold-hi); }
.press-nav span { color: var(--border); }

/* ── Masthead ── */
.masthead {
  border-bottom: 2px solid var(--rule);
  padding: 2rem 1.5rem 1rem;
  max-width: 1060px;
  margin: 0 auto;
}
.masthead-eyebrow {
  font-family: 'Courier New', Courier, monospace;
  font-size: .68rem;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: .5rem;
}
.masthead-title {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  font-weight: 700;
  letter-spacing: -.02em;
  line-height: 1;
  color: var(--ink);
  text-wrap: balance;
}
.masthead-meta {
  display: flex;
  gap: 2rem;
  margin-top: .75rem;
  font-family: 'Courier New', Courier, monospace;
  font-size: .65rem;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--ink-3);
  flex-wrap: wrap;
}
.masthead-meta span::before {
  content: '— ';
  color: var(--gold);
}

/* ── Wrapper ── */
.edition {
  max-width: 1060px;
  margin: 0 auto;
  padding: 0 1.5rem;
}

/* ── Featured article ── */
.article-featured {
  border-bottom: 1px solid var(--border);
  padding: 2.5rem 0 2rem;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3rem;
  align-items: start;
}
@media (max-width: 700px) {
  .article-featured { grid-template-columns: 1fr; gap: 1.5rem; }
}
.article-featured .art-left {
  border-left: 3px solid var(--gold);
  padding-left: 1.25rem;
}
.article-featured .art-right { padding-top: .25rem; }

/* ── Secondary grid ── */
.article-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border-bottom: 1px solid var(--border);
}
@media (max-width: 640px) {
  .article-grid { grid-template-columns: 1fr; }
}
.article-secondary {
  padding: 2rem 0;
  border-left: 3px solid var(--border);
  padding-left: 1.25rem;
}
.article-secondary:first-child {
  border-left: 3px solid var(--gold);
  padding-right: 2.5rem;
}
.article-secondary:last-child {
  padding-left: 2.5rem;
  border-left: 1px solid var(--border);
}
@media (max-width: 640px) {
  .article-secondary:first-child { padding-right: 0; border-left: 3px solid var(--gold); }
  .article-secondary:last-child  { padding-left: 1.25rem; border-left: 3px solid var(--border); border-top: 1px solid var(--border); }
}

/* ── Article typography ── */
.art-category {
  font-family: 'Courier New', Courier, monospace;
  font-size: .62rem;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: var(--gold);
  margin-bottom: .6rem;
}
.art-headline {
  font-family: Georgia, 'Times New Roman', serif;
  font-weight: 700;
  line-height: 1.2;
  color: var(--ink);
  text-wrap: balance;
  margin-bottom: .75rem;
}
.art-headline-lg { font-size: clamp(1.35rem, 2.5vw, 1.85rem); }
.art-headline-md { font-size: clamp(1.1rem, 2vw, 1.35rem); }
.art-deck {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: .97rem;
  font-style: italic;
  color: var(--ink-2);
  line-height: 1.55;
  margin-bottom: 1rem;
}
.art-byline {
  font-family: 'Courier New', Courier, monospace;
  font-size: .62rem;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--ink-3);
  margin-bottom: 1.1rem;
  display: flex;
  gap: 1rem;
  flex-wrap: wrap;
}
.art-byline-loc { color: var(--gold); }
.art-body {
  font-size: .92rem;
  color: var(--ink-2);
  line-height: 1.75;
  display: none;
}
.art-body.open { display: block; }
.art-body p + p { margin-top: .9rem; }

/* Newspaper columns on expanded featured */
.art-body-cols.open {
  column-count: 2;
  column-gap: 2rem;
  column-rule: 1px solid var(--col-rule);
  text-align: justify;
  hyphens: auto;
}
@media (max-width: 700px) {
  .art-body-cols.open { column-count: 1; text-align: left; }
}
.art-body blockquote {
  border-left: 2px solid var(--gold);
  padding: .5rem 0 .5rem 1rem;
  margin: 1rem 0;
  font-family: Georgia, 'Times New Roman', serif;
  font-style: italic;
  font-size: .95rem;
  color: var(--ink);
  line-height: 1.6;
  break-inside: avoid;
}
.art-body .art-source {
  margin-top: 1.25rem;
  padding-top: .75rem;
  border-top: 1px solid var(--border);
  font-size: .78rem;
  color: var(--ink-3);
  font-family: 'Courier New', Courier, monospace;
  letter-spacing: .05em;
  break-inside: avoid;
}
.art-body .art-source strong {
  color: var(--ink-2);
  display: block;
  margin-bottom: .2rem;
  letter-spacing: .08em;
  text-transform: uppercase;
  font-size: .65rem;
}

/* ── Read more button ── */
.read-more {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  font-family: 'Courier New', Courier, monospace;
  font-size: .65rem;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--gold);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  margin-top: .25rem;
  transition: color .2s;
}
.read-more:hover { color: var(--gold-hi); }
.read-more:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
.read-more svg { transition: transform .25s; flex-shrink: 0; }
.read-more.open svg { transform: rotate(180deg); }

/* ── Divider tag ── */
.section-divider {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1.75rem 0 0;
  border-top: 1px solid var(--border);
  font-family: 'Courier New', Courier, monospace;
  font-size: .62rem;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.section-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border);
}
</style>
</head>
<body>

<!-- Breadcrumb nav -->
<nav class="press-nav" aria-label="Navegação">
  <a href="/">Maffezzolli Capital</a>
  <span>/</span>
  <span>Sala de Imprensa</span>
</nav>

<!-- Masthead -->
<header class="masthead">
  <div class="masthead-eyebrow">Maffezzolli Capital · Sala de Imprensa</div>
  <div class="masthead-title">Análise &amp; Perspectiva</div>
  <div class="masthead-meta">
    <span>Edição 2026</span>
    <span>Brusque, Santa Catarina</span>
    <span>Finanças Corporativas · Sul do Brasil</span>
  </div>
</header>

<main class="edition">

  <!-- ── Artigo 1 — Featured ── -->
  <article class="article-featured">
    <div class="art-left">
      <div class="art-category">Tecnologia &amp; Inovação</div>
      <h1 class="art-headline art-headline-lg">Boutique financeira do Sul do Brasil desenvolve IA própria para monitorar a saúde financeira de médias empresas</h1>
      <div class="art-deck">Augur, plataforma da Maffezzolli Capital, une diagnóstico financeiro, análise de viabilidade e inteligência artificial em um só ambiente</div>
      <div class="art-byline">
        <span class="art-byline-loc">Brusque (SC)</span>
        <span>Maffezzolli Capital</span>
      </div>
    </div>
    <div class="art-right">
      <button class="read-more" onclick="toggle(this,'body-1')" aria-expanded="false">
        Continuar lendo
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2 3.5L5 6.5L8 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="art-body art-body-cols" id="body-1">
        <p>Enquanto grande parte do mercado financeiro discute inteligência artificial em termos genéricos, a boutique catarinense Maffezzolli Capital decidiu construir a própria ferramenta. Batizada de Augur, a plataforma proprietária integra diagnóstico financeiro, análise de viabilidade de projetos, controle orçamentário e um assistente de inteligência artificial em um único ambiente, pensado especificamente para médias empresas do Sul do Brasil — um segmento que a empresa considera mal atendido pelas soluções bancárias tradicionais.</p>
        <p>O módulo de diagnóstico financeiro processa indicadores como liquidez, DRE, necessidade de capital de giro (NCG) e ciclo financeiro, gerando um raio-x da empresa em minutos, com interpretação automática e alertas de risco. Já a frente de viabilidade foi construída para avaliar projetos e investimentos em diferentes setores — da indústria ao agronegócio, passando pela construção civil —, calculando indicadores como VGV, TIR, payback e exposição máxima de caixa com parâmetros do mercado regional.</p>
        <p>O módulo de controle orçamentário acompanha, em tempo real, a execução física e financeira de projetos ao longo de sua implementação. O quarto módulo, batizado Augur IA, funciona como um consultor digital: interpreta os indicadores do cliente, responde perguntas sobre o negócio e mantém a empresa orientada entre uma reunião e outra com a equipe da boutique.</p>
        <blockquote>"O Augur não nasceu para substituir o julgamento humano, e sim para ampliar a capacidade da nossa equipe de entender o cliente e propor soluções com mais velocidade e precisão. É o que nos permite entregar a médias empresas o mesmo nível de sofisticação analítica que só as grandes corporações costumam acessar."<br><br>— Rafael Maffezzolli, sócio-fundador e diretor executivo</blockquote>
        <p>O acesso à plataforma é exclusivo para clientes da boutique, que atende empresas com faturamento entre R$ 10 milhões e R$ 150 milhões em Santa Catarina, Paraná e Rio Grande do Sul.</p>
        <div class="art-source">
          <strong>Sobre a Maffezzolli Capital</strong>
          A Maffezzolli Capital é uma boutique financeira independente fundada em Brusque (SC), com atuação em reestruturação financeira, gestão estratégica, captação via mercado de capitais, investment banking e special situations/recuperação judicial para médias empresas do Sul do Brasil.
        </div>
      </div>
    </div>
  </article>

  <!-- ── Seção secundária ── -->
  <div class="section-divider">Mais da Redação</div>

  <div class="article-grid">

    <!-- Artigo 2 -->
    <article class="article-secondary">
      <div class="art-category">Posicionamento de Mercado</div>
      <h2 class="art-headline art-headline-md">No Sul do Brasil, uma boutique financeira aposta na lacuna entre os grandes bancos e as consultorias generalistas</h2>
      <div class="art-deck">Maffezzolli Capital atende empresas de R$&nbsp;10 milhões a R$&nbsp;150 milhões de faturamento — o público que, segundo a empresa, "é grande demais para os pequenos e pequeno demais para os grandes bancos"</div>
      <div class="art-byline">
        <span class="art-byline-loc">Brusque (SC)</span>
        <span>Estratégia Corporativa</span>
      </div>
      <button class="read-more" onclick="toggle(this,'body-2')" aria-expanded="false">
        Continuar lendo
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2 3.5L5 6.5L8 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="art-body" id="body-2">
        <p>Médias empresas do Sul do Brasil costumam enfrentar um dilema recorrente: problemas financeiros complexos demais para uma consultoria generalista resolver, mas pequenos demais para chamar a atenção dos grandes bancos de investimento. É nesse espaço que a Maffezzolli Capital, boutique financeira fundada em Brusque, Santa Catarina, decidiu atuar.</p>
        <p>A empresa se define como independente — sem vínculo com bancos ou fundos — e trabalha com cinco frentes principais: reestruturação financeira, gestão financeira estratégica (atuando como um CFO externo), captação via mercado de capitais (CRI, CRA, debêntures e outros instrumentos de crédito estruturado), investment banking (fusões, aquisições, entrada de sócios e sucessão familiar) e special situations, incluindo assessoria financeira em processos de recuperação judicial.</p>
        <p>Entre os cases da boutique está a reestruturação de uma indústria têxtil do Sul do Brasil, com receita de R$&nbsp;136 milhões, que reduziu sua despesa financeira anual de R$&nbsp;21,5 milhões para uma faixa de R$&nbsp;6 a 8 milhões após uma operação estruturada — tornando-se lucrativa sem crescer a receita. Outro case é o suporte financeiro prestado ao administrador judicial do Grupo Forest, em Ponta Grossa (PR), em uma recuperação judicial com passivo superior a R$&nbsp;150 milhões sob análise técnica.</p>
        <blockquote>"Nossa única lealdade é com o resultado do cliente. Isso muda completamente a natureza da recomendação: não é sobre o que é mais conveniente para um banco ou fundo, é sobre o que é certo para a empresa."<br><br>— Rafael Maffezzolli</blockquote>
        <div class="art-source">
          <strong>Sobre a Maffezzolli Capital</strong>
          Boutique financeira independente fundada em Brusque (SC), com atuação em Santa Catarina, Paraná e Rio Grande do Sul. A empresa desenvolveu a plataforma proprietária Augur, que combina diagnóstico financeiro e inteligência artificial.
        </div>
      </div>
    </article>

    <!-- Artigo 3 -->
    <article class="article-secondary">
      <div class="art-category">Perfil</div>
      <h2 class="art-headline art-headline-md">Da engenharia de produção às salas de recuperação judicial: a trajetória de Rafael Maffezzolli</h2>
      <div class="art-deck">Sócio-fundador e diretor executivo da Maffezzolli Capital construiu reputação regional em turnaround management antes de estruturar uma boutique financeira própria para médias empresas do Sul do Brasil</div>
      <div class="art-byline">
        <span class="art-byline-loc">Brusque (SC)</span>
        <span>Perfil Executivo</span>
      </div>
      <button class="read-more" onclick="toggle(this,'body-3')" aria-expanded="false">
        Continuar lendo
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2 3.5L5 6.5L8 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      <div class="art-body" id="body-3">
        <p>Antes de fundar a Maffezzolli Capital, Rafael Maffezzolli seguiu um caminho pouco convencional para o mercado financeiro: formou-se engenheiro de produção e se especializou em controladoria, finanças corporativas, investment banking e direito empresarial e tributário. Foi a partir do turnaround management — a reestruturação de empresas em crise — que construiu sua reputação como referência regional em reestruturação financeira para médias empresas do Sul do Brasil.</p>
        <p>É coautor do livro "Turnaround — 100 Segredos" e hoje lidera a assessoria em investment banking, captação via mercado de capitais, recuperação judicial e gestão financeira estratégica da boutique, com foco especial em incorporadoras e empresas industriais.</p>
        <p>Maffezzolli fundou a boutique a partir de uma tese específica: médias empresas — aquelas com faturamento entre R$&nbsp;10 milhões e R$&nbsp;150 milhões — merecem o mesmo nível de sofisticação financeira que as grandes corporações acessam, mas sem os conflitos de interesse dos grandes bancos nem a superficialidade das consultorias generalistas.</p>
        <blockquote>"Nascemos da convicção de que existe um público inteiro sendo mal atendido: grande demais para os pequenos, pequeno demais para os grandes bancos. É esse o espaço que ocupamos."<br><br>— Rafael Maffezzolli</blockquote>
        <p>Hoje a boutique atua em cinco frentes — reestruturação financeira, gestão estratégica, mercado de capitais, investment banking e special situations — e desenvolveu internamente a Augur, plataforma proprietária de inteligência financeira com módulo de inteligência artificial.</p>
        <div class="art-source">
          <strong>Sobre a Maffezzolli Capital</strong>
          Boutique financeira independente fundada em Brusque (SC), especializada em reestruturação, investment banking e captação via mercado de capitais para médias empresas de Santa Catarina, Paraná e Rio Grande do Sul.
        </div>
      </div>
    </article>

  </div><!-- /article-grid -->
</main>

<script>
function toggle(btn, id) {
  const body = document.getElementById(id);
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  btn.classList.toggle('open', !isOpen);
  btn.setAttribute('aria-expanded', String(!isOpen));
  btn.childNodes[0].textContent = isOpen ? 'Continuar lendo ' : 'Recolher ';
}
</script>
</body>
</html>"""


@app.get("/noticias", response_class=_HTMLResponse_press)
async def noticias_press(request: Request) -> _HTMLResponse_press:
    return _HTMLResponse_press(_NOTICIAS_HTML)
