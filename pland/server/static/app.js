const $ = (id) => document.getElementById(id);
const status = $('status');
const chats = $('chats');
let profile = 'default';
let session;
let timer;

async function api(method, path, body) {
  const response = await fetch(path, {
    method,
    ...(body === undefined ? {} : {
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || response.statusText);
  return data;
}

function route(suffix = '') {
  return `/api/profiles/${encodeURIComponent(profile)}/sessions${suffix}`;
}

function report(error) {
  status.textContent = String(error.message || error);
  $('send').disabled = false;
}

function switchChat(next) {
  session = next;
  $('send').disabled = !session;
  status.textContent = '';
  $('messages').replaceChildren();
  clearTimeout(timer);
  if (session) refresh().catch(report);
}

async function refresh() {
  const path = route(`/${encodeURIComponent(session)}/messages`);
  const data = await api('GET', path);
  if (!session || path !== route(`/${encodeURIComponent(session)}/messages`)) return;
  const nodes = data.items.map((item) => {
    const row = document.createElement('li');
    const label = document.createElement('strong');
    const text = document.createElement('p');
    label.textContent = item.role;
    text.textContent = item.content || (item.tool_calls || []).map((call) => call.name).join(', ');
    row.append(label, text);
    return row;
  });
  $('messages').replaceChildren(...nodes);
  status.textContent = data.busy ? 'Agent is working…' : '';
  $('send').disabled = data.busy;
  clearTimeout(timer);
  if (data.busy) timer = setTimeout(() => refresh().catch(report), 400);
}

async function loadChats(preferred) {
  const listingPath = route();
  const rows = await api('GET', listingPath);
  if (route() !== listingPath) return;
  chats.replaceChildren(...rows.map(({id, title}) => new Option(title || 'Untitled', id)));
  if (preferred && rows.some(({id}) => id === preferred)) chats.value = preferred;
  switchChat(chats.value);
}

chats.addEventListener('change', () => switchChat(chats.value));
$('new-chat').addEventListener('click', async () => {
  try {
    const path = route();
    const row = await api('POST', path, {title: ''});
    if (path === route()) await loadChats(row.id);
  } catch (error) { report(error); }
});
$('composer').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = $('input').value.trim();
  if (!text || !session) return;
  try {
    $('send').disabled = true;
    await api('POST', route(`/${encodeURIComponent(session)}/messages`), {text});
    $('input').value = '';
    if (session) await refresh();
  } catch (error) { report(error); }
});

loadChats().catch(report);
