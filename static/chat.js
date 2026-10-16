const $ = selector => document.querySelector(selector);
const joinForm = $('#join-form');
const form = $('#chat-form');
const input = $('#text');
let me = null;
let peers = [];
let history = [];
let selected = null;
let loading = false;
let sending = false;
let rendered = '';
const readThrough = new Map();
const drafts = new Map();

function initials(name) {
  return Array.from(name.trim()).slice(0, 2).join('').toUpperCase();
}

async function api(path, body) {
  const response = await fetch(`/api/${path}`, {
    cache: 'no-store',
    ...(body ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      me = null;
      selected = null;
      history = [];
      drafts.clear();
      readThrough.clear();
      $('#app').hidden = true;
      $('#welcome').hidden = false;
      $('#join-status').textContent = 'Your session ended. Enter your name to join again.';
    }
    throw new Error(data.error || 'Something went wrong. Please try again.');
  }
  return data;
}

function conversation() {
  return history.filter(m => m.sender_id === selected || m.recipient_id === selected);
}

function renderPeople() {
  const others = peers.filter(p => p.id !== me);
  $('#online-count').textContent = `${others.filter(p => p.online).length} online`;
  const buttons = others.sort((a, b) => Number(b.online) - Number(a.online) || a.name.localeCompare(b.name)).map(person => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `person${person.id === selected ? ' selected' : ''}`;
    button.setAttribute('aria-pressed', String(person.id === selected));
    const avatar = document.createElement('span');
    avatar.className = 'avatar';
    avatar.textContent = initials(person.name);
    const info = document.createElement('span');
    info.className = 'person-info';
    const name = document.createElement('strong');
    name.textContent = person.name;
    const presence = document.createElement('small');
    const dot = document.createElement('i');
    dot.className = `dot${person.online ? '' : ' offline'}`;
    presence.append(dot, person.online ? 'Online now' : 'Offline');
    info.append(name, presence);
    button.append(avatar, info);
    const unread = history.filter(m => m.sender_id === person.id && m.id > (readThrough.get(person.id) || 0)).length;
    if (unread && selected !== person.id) {
      const badge = document.createElement('span');
      badge.className = 'badge';
      badge.textContent = unread;
      badge.setAttribute('aria-label', `${unread} unread messages`);
      button.append(badge);
    }
    button.addEventListener('click', () => {
      if (selected) drafts.set(selected, input.value);
      selected = person.id;
      input.value = drafts.get(selected) || '';
      rendered = '';
      renderConversation();
      renderPeople();
      input.focus();
    });
    return button;
  });
  const focusedId = $('#people').contains(document.activeElement)
    ? document.activeElement.dataset.personId : null;
  buttons.forEach((button, index) => { button.dataset.personId = others[index].id; });
  $('#people').replaceChildren(...buttons);
  if (!buttons.length) {
    const hint = document.createElement('p');
    hint.className = 'sidebar-hint';
    hint.textContent = 'Just you for now. Invite someone to join.';
    $('#people').append(hint);
  }
  if (focusedId) buttons.find(b => b.dataset.personId === focusedId)?.focus();
}

function renderConversation() {
  const peer = peers.find(p => p.id === selected);
  if (!peer) return;
  $('#peer-name').textContent = peer.name;
  $('#peer-avatar').textContent = initials(peer.name);
  $('#peer-status').textContent = peer.online ? 'Online now · Say hello' : 'Offline · They can read your messages when they return';
  $('#empty').hidden = true;
  $('#messages').hidden = false;
  input.disabled = false;
  $('#send').disabled = sending;
  input.placeholder = `Message ${peer.name}…`;
  const items = conversation();
  readThrough.set(selected, items.at(-1)?.id || 0);
  const version = `${selected}:${items.at(-1)?.id || 0}`;
  if (rendered === version) return;
  const list = $('#messages');
  const atBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 60;
  const switched = !rendered;
  const nodes = items.map(message => {
    const item = document.createElement('li');
    item.className = `message${message.sender_id === me ? ' mine' : ''}`;
    const bubble = document.createElement('p');
    bubble.className = 'bubble';
    bubble.textContent = message.text;
    const time = document.createElement('time');
    time.dateTime = message.created_at;
    time.textContent = new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    item.append(bubble, time);
    return item;
  });
  list.replaceChildren(...nodes);
  if (!nodes.length) {
    const hint = document.createElement('li');
    hint.className = 'sidebar-hint';
    hint.textContent = `This is the start of your conversation with ${peer.name}. Say hello!`;
    list.append(hint);
  }
  if (switched || atBottom) list.scrollTop = list.scrollHeight;
  rendered = version;
}

async function refresh() {
  if (!me || loading) return;
  loading = true;
  try {
    const people = await api('users');
    const messages = await api('messages');
    me = people.me;
    peers = people.users;
    history = messages;
    const self = peers.find(p => p.id === me);
    $('#my-name').textContent = self.name;
    $('#my-avatar').textContent = initials(self.name);
    renderConversation();
    renderPeople();
    $('#status').textContent = 'Messages stay here until the server restarts.';
  } catch (error) {
    $('#status').textContent = `${error.message} Retrying automatically.`;
  } finally {
    loading = false;
  }
}

joinForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = joinForm.querySelector('button');
  button.disabled = true;
  try {
    const user = await api('join', { name: joinForm.elements.name.value });
    me = user.id;
    $('#welcome').hidden = true;
    $('#app').hidden = false;
    $('#join-status').textContent = '';
    await refresh();
  } catch (error) {
    $('#join-status').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (!selected || sending || !input.value.trim()) return;
  const recipient = selected;
  const text = input.value;
  sending = true;
  $('#send').disabled = true;
  try {
    await api('messages', { recipient_id: recipient, text });
    drafts.delete(recipient);
    if (selected === recipient && input.value === text) input.value = '';
    await refresh();
    if (selected === recipient) $('#messages').scrollTop = $('#messages').scrollHeight;
  } catch (error) {
    $('#status').textContent = error.message;
  } finally {
    sending = false;
    $('#send').disabled = !selected;
  }
});

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

// The signed HttpOnly cookie restores this browser's temporary identity.
(async () => {
  try {
    const data = await api('users');
    me = data.me;
    $('#welcome').hidden = true;
    $('#app').hidden = false;
    await refresh();
  } catch {
    // New visitors enter a name first; network failures can be retried by joining.
  }
})();
setInterval(refresh, 2000);
