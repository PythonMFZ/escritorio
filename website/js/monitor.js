(function () {
  const container = document.getElementById('monitor-cards');
  if (!container) return;

  const base = document.querySelector('base')?.href || '';
  const jsonPath = base
    ? new URL('data/noticias.json', base).href
    : 'data/noticias.json';

  function formatDate(iso) {
    const [y, m, d] = iso.split('-');
    const months = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
    return `${parseInt(d)} ${months[parseInt(m) - 1]} ${y}`;
  }

  function buildCard(item) {
    const tagPais = `<span class="mn-tag mn-tag--destaque">${item.pais}</span>`;
    const tagTipo = `<span class="mn-tag">${item.tipo}</span>`;

    return `
      <a href="${item.arquivo}" target="_blank" rel="noopener" class="mn-card">
        <div class="mn-card-top">
          <div class="mn-tags">${tagPais}${tagTipo}</div>
          <span class="mn-data">${formatDate(item.data)}</span>
        </div>
        <div class="mn-empresa">${item.empresa}</div>
        <div class="mn-manchete">${item.manchete}</div>
        <div class="mn-resumo">${item.resumo}</div>
        <div class="mn-rodape">
          <span class="mn-passivo">${item.passivo}</span>
          <span class="mn-cta">Ver análise →</span>
        </div>
      </a>`;
  }

  fetch(jsonPath)
    .then(r => r.json())
    .then(data => {
      const items = (data.monitor || []).slice(0, 4);
      container.innerHTML = items.map(buildCard).join('');
    })
    .catch(() => {
      container.style.display = 'none';
    });
})();
