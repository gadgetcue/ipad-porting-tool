let notes = [];
let current = 0;
const list = document.getElementById('list');
const editor = document.getElementById('editor');

function render() {
  list.innerHTML = '';
  notes.forEach((n, i) => {
    const el = document.createElement('div');
    el.textContent = (n.split('\n')[0] || 'Untitled').slice(0, 40);
    el.className = i === current ? 'active' : '';
    el.onclick = () => { current = i; render(); };
    list.appendChild(el);
  });
  editor.value = notes[current] || '';
}

editor.addEventListener('input', () => { notes[current] = editor.value; window.notesApi.save(notes); render(); });
document.getElementById('add').onclick = () => { notes.unshift(''); current = 0; render(); editor.focus(); };
document.getElementById('export').onclick = async () => {
  const saved = await window.notesApi.exportText(notes.join('\n\n---\n\n'));
  if (saved) alert('Exported to ' + saved);
};
document.getElementById('help').onclick = () => window.notesApi.openHelp();

window.notesApi.load().then((loaded) => { notes = loaded.length ? loaded : ['Welcome to Notes']; render(); });
