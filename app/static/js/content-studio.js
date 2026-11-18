(() => {
  const root = document.getElementById('content-studio');
  const form = document.getElementById('content-studio-form');
  const editorNode = document.getElementById('cms-editor');
  if (!root || !form || !editorNode || typeof Quill === 'undefined') return;

  const type = root.dataset.contentType;
  const autosaveUrl = root.dataset.autosaveUrl;
  const titleInput = document.getElementById('content-title');
  const slugInput = document.getElementById('content-slug');
  const summaryInput = document.getElementById('content-summary');
  const contentIdInput = document.getElementById('content-id');
  const statusSelect = document.getElementById('content-status');
  const saveState = document.getElementById('save-state');
  const outline = document.getElementById('content-outline');
  const historyList = document.getElementById('revision-list');
  const csrf = document.querySelector('input[name="csrf"]')?.value || '';
  const localKey = `faq-cms-draft:${type}:${contentIdInput.value || location.pathname}`;
  let slugWasEdited = Boolean(slugInput.value.trim());
  let debounceTimer = null;
  let lastSavedFingerprint = '';
  let lastSelection = { index: 0, length: 0 };
  let saving = false;
  let pendingSave = false;

  // Séparateur natif Quill : il reste un bloc éditable et non une image externe.
  const BlockEmbed = Quill.import('blots/block/embed');
  class DividerBlot extends BlockEmbed {
    static blotName = 'divider';
    static tagName = 'hr';
    static className = 'content-divider';
  }
  Quill.register(DividerBlot, true);

  const quill = new Quill('#cms-editor', {
    theme: 'snow',
    placeholder: 'Commencez à rédiger… Utilisez les titres pour structurer votre contenu.',
    modules: {
      toolbar: {
        container: '#cms-toolbar',
        handlers: { image: chooseImage }
      },
      history: { delay: 900, maxStack: 100, userOnly: true }
    }
  });

  function setSaveState(text, state = 'idle') {
    if (!saveState) return;
    saveState.className = `studio-save-state is-${state}`;
    const label = saveState.querySelector('span');
    if (label) label.textContent = text;
  }

  function slugify(value) {
    return (value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 230);
  }

  function currentMetadata() {
    if (type === 'article') {
      return {
        category: document.getElementById('content-category')?.value || 'Général',
        tags: document.getElementById('content-tags')?.value || '',
        featured: Boolean(document.getElementById('content-featured')?.checked),
        cover_image: document.getElementById('cover-image-url')?.value || ''
      };
    }
    return { show_in_footer: Boolean(document.getElementById('content-footer')?.checked) };
  }

  function payload() {
    return {
      type,
      id: Number(contentIdInput.value || 0),
      title: titleInput.value.trim(),
      slug: slugInput.value.trim() || slugify(titleInput.value),
      summary: summaryInput.value.trim(),
      content_html: quill.root.innerHTML,
      metadata: currentMetadata()
    };
  }

  function fingerprint(data) {
    return JSON.stringify(data);
  }

  function cacheLocal(data) {
    try {
      localStorage.setItem(localKey, JSON.stringify({ ...data, cached_at: new Date().toISOString() }));
    } catch (_) { /* Le stockage local peut être désactivé par le navigateur. */ }
  }

  function clearLocalCache() {
    try { localStorage.removeItem(localKey); } catch (_) { /* noop */ }
  }

  function refreshMetrics() {
    const text = quill.getText().trim();
    const words = text ? text.split(/\s+/).filter(Boolean).length : 0;
    const count = document.getElementById('word-count');
    const time = document.getElementById('reading-time');
    if (count) count.textContent = words.toLocaleString('fr-FR');
    if (time) time.textContent = Math.max(1, Math.ceil(words / 200));
  }

  function refreshSeoPreview() {
    const title = titleInput.value.trim() || 'Titre de votre contenu';
    const slug = slugInput.value.trim() || slugify(title) || 'mon-contenu';
    const summary = summaryInput.value.trim() || 'Le résumé de votre contenu apparaîtra ici.';
    document.getElementById('seo-title').textContent = title;
    document.getElementById('seo-summary').textContent = summary;
    document.getElementById('seo-url').textContent = `${type === 'page' ? '/contenu/' : '/faq/'}${slug}`;
  }

  function refreshOutline() {
    const headings = editorNode.querySelectorAll('h2, h3, h4');
    if (!headings.length) {
      outline.className = 'studio-outline-empty';
      outline.textContent = 'Ajoutez des titres H2 ou H3 pour générer le plan automatiquement.';
      return;
    }
    outline.className = 'studio-outline-list';
    outline.replaceChildren();
    headings.forEach((heading, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `outline-item outline-${heading.tagName.toLowerCase()}`;
      button.textContent = heading.textContent.trim() || `Section ${index + 1}`;
      button.addEventListener('click', () => {
        heading.scrollIntoView({ behavior: 'smooth', block: 'center' });
        quill.focus();
      });
      outline.appendChild(button);
    });
  }

  async function uploadFile(file, insertAt = null) {
    if (!file || !/^image\/(png|jpeg|webp|gif)$/i.test(file.type)) {
      setSaveState('Format image non accepté', 'error');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setSaveState('Image supérieure à 5 Mo', 'error');
      return;
    }
    setSaveState('Envoi de l’image…', 'saving');
    const data = new FormData();
    data.append('file', file);
    try {
      const response = await fetch('/admin/upload-image', {
        method: 'POST', body: data, credentials: 'same-origin',
        headers: { 'X-CSRF-Token': csrf }
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `Erreur ${response.status}`);
      const range = quill.getSelection(true) || lastSelection;
      const index = Number.isInteger(insertAt) ? insertAt : (range?.index ?? quill.getLength());
      quill.insertEmbed(index, 'image', result.url, 'user');
      quill.setSelection(index + 1, 0, 'silent');
      quill.insertText(index + 1, '\n', 'user');
      quill.setSelection(index + 2, 0, 'silent');
      setSaveState('Image insérée', 'success');
    } catch (error) {
      setSaveState(error.message || 'Échec du téléversement', 'error');
    }
  }

  function chooseImage() {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/png,image/jpeg,image/webp,image/gif';
    picker.addEventListener('change', () => uploadFile(picker.files?.[0]));
    picker.click();
  }

  async function saveAutomatically() {
    if (saving) { pendingSave = true; return; }
    const data = payload();
    if (!data.title) {
      setSaveState('Ajoutez un titre pour démarrer la sauvegarde', 'idle');
      return false;
    }
    const currentFingerprint = fingerprint(data);
    if (currentFingerprint === lastSavedFingerprint) return true;
    saving = true;
    pendingSave = false;
    setSaveState('Sauvegarde en cours…', 'saving');
    cacheLocal(data);
    try {
      const response = await fetch(autosaveUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(data)
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `Erreur ${response.status}`);
      if (Number(contentIdInput.value || 0) !== result.id) {
        contentIdInput.value = result.id;
        root.dataset.contentId = result.id;
        root.dataset.revisionsUrl = `/admin/content/${type}/${result.id}/revisions`;
      }
      if (result.slug && data.slug === slugInput.value && result.slug !== slugInput.value) slugInput.value = result.slug;
      lastSavedFingerprint = fingerprint(payload());
      clearLocalCache();
      const savedDate = result.saved_at ? new Date(result.saved_at) : new Date();
      setSaveState(`Enregistré automatiquement à ${savedDate.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`, 'success');
      loadHistory();
      return true;
    } catch (error) {
      setSaveState('Sauvegarde serveur indisponible — copie locale conservée', 'error');
      cacheLocal(data);
      return false;
    } finally {
      saving = false;
      if (pendingSave) saveAutomatically();
    }
  }

  function scheduleAutosave() {
    setSaveState('Modifications non enregistrées', 'dirty');
    cacheLocal(payload());
    window.clearTimeout(debounceTimer);
    debounceTimer = window.setTimeout(saveAutomatically, 1700);
  }

  async function loadHistory() {
    const id = Number(contentIdInput.value || 0);
    if (!id) return;
    try {
      const response = await fetch(root.dataset.revisionsUrl, { credentials: 'same-origin' });
      if (!response.ok) throw new Error('Historique indisponible');
      const result = await response.json();
      historyList.replaceChildren();
      if (!result.items?.length) {
        const empty = document.createElement('p'); empty.className = 'revision-empty'; empty.textContent = 'Aucune version enregistrée.'; historyList.appendChild(empty); return;
      }
      result.items.forEach((revision) => {
        const card = document.createElement('div'); card.className = 'revision-item';
        const info = document.createElement('div');
        const title = document.createElement('b'); title.textContent = revision.title || 'Sans titre';
        const date = document.createElement('small');
        const when = revision.created_at ? new Date(revision.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '';
        date.textContent = `${revision.type === 'auto' ? 'Sauvegarde automatique' : 'Version enregistrée'} · ${when}`;
        info.append(title, date);
        const restore = document.createElement('button'); restore.type = 'button'; restore.textContent = 'Restaurer';
        restore.addEventListener('click', () => restoreRevision(revision));
        card.append(info, restore); historyList.appendChild(card);
      });
    } catch (_) {
      historyList.innerHTML = '<p class="revision-empty">Impossible de charger l’historique pour le moment.</p>';
    }
  }

  function restoreRevision(revision) {
    if (!window.confirm('Restaurer cette version dans l’éditeur ? La version actuellement affichée sera conservée dans l’historique.')) return;
    titleInput.value = revision.title || '';
    slugInput.value = revision.slug || '';
    slugWasEdited = true;
    summaryInput.value = revision.summary || '';
    quill.setText('');
    quill.clipboard.dangerouslyPasteHTML(0, revision.content_html || '', 'silent');
    const meta = revision.metadata || {};
    if (type === 'article') {
      if (document.getElementById('content-category')) document.getElementById('content-category').value = meta.category || 'Général';
      if (document.getElementById('content-tags')) document.getElementById('content-tags').value = meta.tags || '';
      if (document.getElementById('content-featured')) document.getElementById('content-featured').checked = Boolean(meta.featured);
      if (document.getElementById('cover-image-url')) document.getElementById('cover-image-url').value = meta.cover_image || document.getElementById('cover-image-url').value;
    } else if (document.getElementById('content-footer')) {
      document.getElementById('content-footer').checked = Boolean(meta.show_in_footer);
    }
    refreshMetrics(); refreshSeoPreview(); refreshOutline(); scheduleAutosave();
  }

  function openPreview() {
    const dialog = document.getElementById('studio-preview-dialog');
    const frame = document.getElementById('studio-preview-frame');
    const safeTitle = titleInput.value.trim() || 'Sans titre';
    const safeSummary = summaryInput.value.trim();
    const html = quill.root.innerHTML;
    const previewDoc = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
      *{box-sizing:border-box}body{margin:0;background:#f7f8fb;color:#202a3a;font-family:Inter,'Segoe UI',Arial,sans-serif;line-height:1.75}.preview-wrap{max-width:850px;margin:36px auto;padding:0 28px 70px}.eyebrow{font-size:11px;letter-spacing:1.5px;color:#477cbd;font-weight:800}.preview-wrap h1{font-size:clamp(30px,4vw,43px);line-height:1.16;letter-spacing:-1.3px;margin:10px 0 13px}.summary{font-size:17px;color:#637187;line-height:1.55;padding-bottom:25px;border-bottom:1px solid #e1e6ee}.body{margin-top:30px;font-size:16px}.body h2{font-size:26px;margin-top:1.7em}.body h3{font-size:21px;margin-top:1.5em}.body img{max-width:100%;height:auto;border-radius:12px}.body blockquote{margin:22px 0;padding:16px 19px;background:#eef4fc;border-left:4px solid #477cbd;border-radius:0 9px 9px 0}.body pre{padding:15px;background:#172337;color:#fff;border-radius:9px;overflow:auto}.body table{border-collapse:collapse;width:100%}.body td,.body th{border:1px solid #dbe2ec;padding:9px;text-align:left}.body a{color:#3157a4}.body hr{border:0;border-top:1px solid #dce2ea;margin:28px 0}
      </style></head><body><main class="preview-wrap"><span class="eyebrow">${type === 'page' ? 'INFORMATIONS' : 'FICHE PRATIQUE'}</span><h1 id="preview-title"></h1><p class="summary" id="preview-summary"></p><article class="body" id="preview-body"></article></main></body></html>`;
    // Écrire le document après l'ouverture de la fenêtre évite la course entre srcdoc et l'événement load.
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', 'open');
    const doc = frame.contentDocument;
    doc.open(); doc.write(previewDoc); doc.close();
    doc.getElementById('preview-title').textContent = safeTitle;
    doc.getElementById('preview-summary').textContent = safeSummary;
    if (!safeSummary) doc.getElementById('preview-summary').style.display = 'none';
    doc.getElementById('preview-body').innerHTML = html;
  }

  // Titre, URL et aperçu SEO.
  titleInput.addEventListener('input', () => {
    if (!slugWasEdited) slugInput.value = slugify(titleInput.value);
    refreshSeoPreview(); scheduleAutosave();
  });
  slugInput.addEventListener('input', () => { slugWasEdited = true; refreshSeoPreview(); scheduleAutosave(); });
  summaryInput.addEventListener('input', () => { refreshSeoPreview(); scheduleAutosave(); });
  form.querySelectorAll('input, select, textarea').forEach((field) => {
    if (!['content-title', 'content-slug', 'content-summary', 'content-html', 'content-id'].includes(field.id)) {
      field.addEventListener('input', scheduleAutosave);
      field.addEventListener('change', scheduleAutosave);
    }
  });
  quill.on('selection-change', (range) => { if (range) lastSelection = range; });
  quill.on('text-change', () => { refreshMetrics(); refreshOutline(); scheduleAutosave(); });

  // Blocs éditoriaux rapides.
  document.querySelectorAll('[data-editor-action]').forEach((button) => {
    button.addEventListener('click', () => {
      quill.focus();
      const range = quill.getSelection(true) || lastSelection;
      if (button.dataset.editorAction === 'callout') {
        quill.format('blockquote', true, 'user');
        if (!quill.getText(range.index, 1).trim()) quill.insertText(range.index, 'À retenir : ', 'user');
      } else if (button.dataset.editorAction === 'checklist') {
        quill.format('list', 'checked', 'user');
        if (!quill.getText(range.index, 1).trim()) quill.insertText(range.index, 'Nouvelle étape', 'user');
      } else if (button.dataset.editorAction === 'divider') {
        quill.insertEmbed(range.index, 'divider', true, 'user');
        quill.insertText(range.index + 1, '\n', 'user');
        quill.setSelection(range.index + 2, 0, 'silent');
      }
    });
  });

  // Dépôt et collage d’images directement dans la zone de rédaction.
  editorNode.addEventListener('dragover', (event) => {
    if ([...(event.dataTransfer?.items || [])].some((item) => item.type.startsWith('image/'))) {
      event.preventDefault(); editorNode.classList.add('is-dragging');
    }
  });
  editorNode.addEventListener('dragleave', () => editorNode.classList.remove('is-dragging'));
  editorNode.addEventListener('drop', (event) => {
    editorNode.classList.remove('is-dragging');
    const file = [...(event.dataTransfer?.files || [])].find((item) => item.type.startsWith('image/'));
    if (file) { event.preventDefault(); uploadFile(file); }
  });
  editorNode.addEventListener('paste', (event) => {
    const file = [...(event.clipboardData?.items || [])].map((item) => item.getAsFile?.()).find((item) => item && item.type.startsWith('image/'));
    if (file) { event.preventDefault(); uploadFile(file); }
  });

  // Image de couverture propre à la tuile FAQ.
  const coverPicker = document.getElementById('cover-image-file');
  const coverUrl = document.getElementById('cover-image-url');
  const coverPreview = document.getElementById('cover-image-preview');
  coverPicker?.addEventListener('change', async () => {
    const file = coverPicker.files?.[0]; if (!file) return;
    if (!/^image\/(png|jpeg|webp|gif)$/i.test(file.type) || file.size > 5 * 1024 * 1024) {
      setSaveState('Image invalide : PNG, JPEG, WEBP ou GIF, 5 Mo maximum', 'error'); coverPicker.value = ''; return;
    }
    const data = new FormData(); data.append('file', file);
    setSaveState('Téléversement de l’image de tuile…', 'saving');
    try {
      const response = await fetch('/admin/upload-image', {method:'POST', body:data, credentials:'same-origin', headers:{'X-CSRF-Token':csrf}});
      const result = await response.json(); if (!response.ok) throw new Error(result.detail || `Erreur ${response.status}`);
      coverUrl.value = result.url; coverPreview.hidden = false; coverPreview.replaceChildren();
      const img = document.createElement('img'); img.src = result.url; img.alt = 'Aperçu de l’image de tuile';
      const remove = document.createElement('button'); remove.type='button'; remove.id='cover-image-remove'; remove.textContent='Retirer l’image';
      coverPreview.append(img, remove); remove.addEventListener('click', clearCoverImage);
      scheduleAutosave(); setSaveState('Image de tuile chargée — sauvegardez la fiche', 'success');
    } catch (error) { setSaveState(error.message || 'Échec du téléversement', 'error'); }
  });
  function clearCoverImage() { if (coverUrl) coverUrl.value=''; if (coverPreview) { coverPreview.hidden=true; coverPreview.replaceChildren(); } if (coverPicker) coverPicker.value=''; scheduleAutosave(); }
  document.getElementById('cover-image-remove')?.addEventListener('click', clearCoverImage);

  // Barre d’actions et prévisualisation.
  document.getElementById('preview-button')?.addEventListener('click', openPreview);
  document.querySelectorAll('[data-close-preview]').forEach((button) => button.addEventListener('click', () => document.getElementById('studio-preview-dialog').close()));
  document.getElementById('save-button')?.addEventListener('click', async () => {
    const originalStatus = root.dataset.originalStatus || 'draft';
    const pdfInput = document.getElementById('pdf-file');
    if (pdfInput?.files?.length) {
      if (originalStatus === 'published' && statusSelect.value === 'published' &&
          !window.confirm('Le PDF sera associé à la fiche et la version enregistrée sera mise à jour. Continuer ?')) return;
      document.getElementById('content-html').value = quill.root.innerHTML;
      form.requestSubmit();
      return;
    }
    if (originalStatus === 'published' && statusSelect.value === 'draft') {
      if (!window.confirm('Cette action dépubliera immédiatement la version actuellement en ligne. Continuer ?')) {
        statusSelect.value = 'published';
        document.getElementById('visibility-label').textContent = 'Visible par tous';
        return;
      }
      document.getElementById('content-html').value = quill.root.innerHTML;
      form.requestSubmit();
      return;
    }
    if (statusSelect.value === 'published') {
      const saved = await saveAutomatically();
      if (saved) setSaveState('Brouillon sauvegardé — la version publique reste inchangée. Cliquez sur « Publier » pour appliquer.', 'success');
      return;
    }
    if (originalStatus === 'draft') {
      document.getElementById('content-html').value = quill.root.innerHTML;
      form.requestSubmit();
      return;
    }
    await saveAutomatically();
  });
  document.getElementById('publish-button')?.addEventListener('click', () => {
    statusSelect.value = 'published';
    form.requestSubmit();
  });
  statusSelect?.addEventListener('change', () => {
    document.getElementById('visibility-label').textContent = statusSelect.value === 'published' ? 'Visible par tous' : 'Administrateurs uniquement';
    scheduleAutosave();
  });
  form.addEventListener('submit', (event) => {
    if (!titleInput.value.trim()) { event.preventDefault(); titleInput.focus(); setSaveState('Le titre est obligatoire', 'error'); return; }
    document.getElementById('content-html').value = quill.root.innerHTML;
    clearLocalCache();
    setSaveState('Enregistrement…', 'saving');
  });
  document.getElementById('refresh-history')?.addEventListener('click', loadHistory);
  document.getElementById('dismiss-recovery')?.addEventListener('click', () => document.querySelector('.studio-recovery-banner')?.remove());

  // Récupération d’une copie locale si le réseau était indisponible.
  try {
    const cachedRaw = localStorage.getItem(localKey);
    if (cachedRaw) {
      const cached = JSON.parse(cachedRaw);
      if (cached.title && window.confirm('Une copie locale non synchronisée a été trouvée. Voulez-vous la récupérer ?')) {
        titleInput.value = cached.title;
        slugInput.value = cached.slug || '';
        summaryInput.value = cached.summary || '';
        slugWasEdited = true;
        quill.clipboard.dangerouslyPasteHTML(0, cached.content_html || '', 'silent');
        const meta = cached.metadata || {};
        if (type === 'article') {
          if (document.getElementById('content-category')) document.getElementById('content-category').value = meta.category || 'Général';
          if (document.getElementById('content-tags')) document.getElementById('content-tags').value = meta.tags || '';
          if (document.getElementById('content-featured')) document.getElementById('content-featured').checked = Boolean(meta.featured);
      if (document.getElementById('cover-image-url')) document.getElementById('cover-image-url').value = meta.cover_image || document.getElementById('cover-image-url').value;
        } else if (document.getElementById('content-footer')) document.getElementById('content-footer').checked = Boolean(meta.show_in_footer);
      }
    }
  } catch (_) { /* Ignore une sauvegarde locale endommagée. */ }

  // Navigation par onglets des paramètres : évite une colonne latérale interminable.
  const inspectorTabs = [...document.querySelectorAll('[data-inspector-tab]')];
  const inspectorPanels = [...document.querySelectorAll('[data-inspector-panel]')];
  function activateInspectorTab(index) {
    inspectorTabs.forEach((button) => button.classList.toggle('active', Number(button.dataset.inspectorTab) === index));
    inspectorPanels.forEach((panel) => { panel.hidden = Number(panel.dataset.inspectorPanel) !== index; });
    sessionStorage.setItem(`faq-inspector-${type}`, String(index));
  }
  inspectorTabs.forEach((button) => button.addEventListener('click', () => activateInspectorTab(Number(button.dataset.inspectorTab))));
  if (inspectorTabs.length) {
    const savedTab = Number(sessionStorage.getItem(`faq-inspector-${type}`) || 0);
    activateInspectorTab(inspectorTabs.some((button) => Number(button.dataset.inspectorTab) === savedTab) ? savedTab : 0);
  }

  refreshMetrics(); refreshOutline(); refreshSeoPreview(); loadHistory();
  if (contentIdInput.value) setSaveState('Contenu chargé', 'success');
  else setSaveState('Brouillon prêt — sauvegarde automatique activée', 'idle');

  // Raccourcis clavier : Ctrl/Cmd+S pour enregistrer, Ctrl/Cmd+Shift+P pour l’aperçu.
  document.addEventListener('keydown', (event) => {
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key.toLowerCase() === 's') { event.preventDefault(); form.requestSubmit(); }
    if (modifier && event.shiftKey && event.key.toLowerCase() === 'p') { event.preventDefault(); openPreview(); }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && debounceTimer) {
      window.clearTimeout(debounceTimer); saveAutomatically();
    }
  });
})();
