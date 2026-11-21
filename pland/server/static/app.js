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
  $('stop').disabled = true;
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
  $('stop').disabled = !data.busy;
  refreshModelStatus().catch(() => {});
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

const bots = $('bots');
const profilePath = () => `/api/profiles/${encodeURIComponent(profile)}`;

async function loadBots(preferred = profile) {
  const rows = await api('GET', '/api/profiles');
  bots.replaceChildren(...rows.map(({name, title}) => new Option(title, name)));
  if (rows.some(({name}) => name === preferred)) bots.value = preferred;
  profile = bots.value;
  $('remove-bot').disabled = profile === 'default';
  switchChat(undefined);
  await loadChats();
}

async function refreshModelStatus() {
  const [config, usage] = await Promise.all([api('GET', '/api/status'), api('GET', '/api/usage')]);
  $('provider').textContent = [config.provider, config.model, config.api_key_set ? 'Key set' : 'Key missing',
    `${usage.calls ?? 0} model calls`].filter(Boolean).join(' · ');
}

function on(id, action) {
  $(id).addEventListener('click', () => action().catch(report));
}

bots.addEventListener('change', () => loadBots(bots.value).catch(report));
on('new-bot', async () => {
  const title = window.prompt('Bot title')?.trim();
  if (!title) return;
  const bot = await api('POST', '/api/profiles', {title});
  await loadBots(bot.name);
});
on('rename-bot', async () => {
  const title = window.prompt('Bot title', bots.selectedOptions[0].text)?.trim();
  if (!title) return;
  await api('PATCH', profilePath(), {title});
  await loadBots();
});
on('remove-bot', async () => {
  if (!window.confirm('Remove this bot and its saved state?')) return;
  await api('DELETE', profilePath());
  await loadBots('default');
});
on('bot-chat', async () => {
  const path = profilePath();
  const data = await api('GET', `${path}/bot-chat`);
  if (profilePath() !== path) return;
  if (![...chats.options].some(({value}) => value === data.session_id)) {
    chats.add(new Option('Bot Chat', data.session_id));
  }
  chats.value = data.session_id;
  switchChat(data.session_id);
});
on('stop', async () => {
  if (session) await api('POST', route(`/${encodeURIComponent(session)}/stop`));
});
loadBots().catch(report);
refreshModelStatus().catch(report);
