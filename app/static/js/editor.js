(() => {
  const editorNode = document.getElementById('editor');
  const form = document.getElementById('article-form');
  if (!editorNode || !form || typeof Quill === 'undefined') return;

  const toolbar = [
    [{ header: [2, 3, 4, false] }],
    ['bold', 'italic', 'underline', 'strike'],
    [{ list: 'ordered' }, { list: 'bullet' }],
    [{ indent: '-1' }, { indent: '+1' }],
    ['blockquote', 'code-block'],
    ['link', 'image'],
    [{ align: [] }],
    ['clean']
  ];

  const quill = new Quill('#editor', {
    theme: 'snow',
    placeholder: 'Rédigez votre procédure ici…',
    modules: { toolbar: { container: toolbar, handlers: { image: uploadImage } } }
  });

  async function uploadImage() {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/png,image/jpeg,image/webp,image/gif';
    picker.click();
    picker.onchange = async () => {
      const file = picker.files && picker.files[0];
      if (!file) return;
      const data = new FormData();
      data.append('file', file);
      try {
        const csrf = document.querySelector('input[name=csrf]')?.value || '';
        const response = await fetch('/admin/upload-image', { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf } });
        if (!response.ok) throw new Error('Le serveur a refusé le fichier (' + response.status + ').');
        const result = await response.json();
        const range = quill.getSelection(true);
        quill.insertEmbed(range ? range.index : quill.getLength(), 'image', result.url, 'user');
      } catch (error) {
        window.alert("Impossible d'insérer l'image : " + error.message);
      }
    };
  }

  form.addEventListener('submit', () => {
    document.getElementById('content_html').value = quill.root.innerHTML;
  });

  const title = document.getElementById('title');
  const slug = document.getElementById('slug');
  let slugEdited = Boolean(slug.value.trim());
  slug.addEventListener('input', () => { slugEdited = true; });
  title.addEventListener('input', () => {
    if (!slugEdited) {
      slug.value = title.value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    }
  });
})();
