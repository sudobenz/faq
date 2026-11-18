(() => {
  const grid = document.getElementById('library-grid');
  const search = document.getElementById('library-search');
  const sort = document.getElementById('library-sort');
  if (!grid || !search || !sort) return;
  const cards = [...grid.querySelectorAll('.library-card')];
  const count = document.getElementById('library-result-count');
  const empty = document.getElementById('library-empty-filtered');
  let activeFilter = 'all';

  function applyFilters() {
    const term = search.value.trim().toLocaleLowerCase('fr');
    let visible = 0;
    cards.forEach((card) => {
      const matchTerm = !term || (card.dataset.search || '').includes(term);
      const matchStatus = activeFilter === 'all' || card.dataset.status === activeFilter;
      const show = matchTerm && matchStatus;
      card.hidden = !show;
      if (show) visible += 1;
    });
    if (count) count.textContent = `${visible} contenu(s)`;
    if (empty) empty.hidden = visible !== 0 || cards.length === 0;
    const ordered = [...cards].sort((a, b) => {
      if (sort.value === 'title') return (a.dataset.title || '').localeCompare(b.dataset.title || '', 'fr');
      if (sort.value === 'created') return Number(a.dataset.created || 0) - Number(b.dataset.created || 0);
      if (sort.value === 'views') return Number(b.dataset.views || 0) - Number(a.dataset.views || 0);
      return Number(b.dataset.updated || 0) - Number(a.dataset.updated || 0);
    });
    ordered.forEach((card) => grid.appendChild(card));
  }
  search.addEventListener('input', applyFilters);
  sort.addEventListener('change', applyFilters);
  document.querySelectorAll('.library-filters [data-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.filter;
      document.querySelectorAll('.library-filters [data-filter]').forEach((item) => item.classList.toggle('active', item === button));
      applyFilters();
    });
  });
  document.getElementById('clear-library-filters')?.addEventListener('click', () => {
    search.value = ''; activeFilter = 'all'; sort.value = 'updated';
    document.querySelectorAll('.library-filters [data-filter]').forEach((item) => item.classList.toggle('active', item.dataset.filter === 'all'));
    applyFilters();
  });
  applyFilters();
})();
