'use strict';
const $ = selector => document.querySelector(selector);
const authForm = $('#auth-form');
let mode = 'login';
let busy = false;
let sessionPending = true;
let account = null;
let conversation = null;
let messageCursor = 0;
let conversationVersion = 0;
let generation = 0;
let refreshing = false;

function authBusy(value) {
  busy = value;
  authForm.setAttribute('aria-busy', String(value));
  for (const id of ['username', 'password', 'auth-submit', 'login-mode', 'register-mode']) {
    $(`#${id}`).disabled = value;
  }
  $('#auth-submit').textContent = value ? (sessionPending ? 'Checking session…' : 'Please wait…') : mode === 'login' ? 'Log in →' : 'Create account →';
}

async function api(path, body) {
  let response;
  try {
    response = await fetch(`/api/${path}`, {
      credentials: 'same-origin', cache: 'no-store',
      ...(body !== undefined ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
  } catch {
    throw new Error('Could not connect to Gather. Check your connection and try again.');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(typeof data?.error === 'string' ? data.error : 'Gather is unavailable right now. Please try again.');
    error.status = response.status;
    throw error;
  }
  if (!data || typeof data !== 'object') throw new Error('Gather returned an unexpected response. Please try again.');
  return data;
}

function setMode(next) {
  if (busy) return;
  mode = next;
  $('#login-mode').setAttribute('aria-pressed', String(mode === 'login'));
  $('#register-mode').setAttribute('aria-pressed', String(mode === 'register'));
  $('#auth-title').textContent = mode === 'login' ? 'Welcome back to Gather.' : 'Make yourself at home.';
  $('#auth-intro').textContent = mode === 'login' ? 'Sign in and make room for a hello.' : 'Create an account to keep your place in Gather.';
  $('#password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
  $('#password').minLength = mode === 'register' ? 10 : 1;
  $('#password-help').textContent = mode === 'register' ? 'Use 10–128 characters. Keep your password private.' : 'Enter your account password.';
  $('#password').value = '';
  $('#auth-status').textContent = '';
  authBusy(false);
}

let workspaceChats = [];
function showPanel(name) {
  for (const key of ['chats', 'friends', 'groups']) $(key === 'chats' ? '#chats-list-panel' : `#${key}-panel`).hidden = key !== name;
  for (const button of document.querySelectorAll('[data-panel]')) {
    button.classList.toggle('selected', button.dataset.panel === name);
    button.setAttribute('aria-pressed', String(button.dataset.panel === name));
  }
}
function conversationButton(name, id, open, subtitle) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'person';
  button.classList.toggle('selected', String(id) === conversation);
  const info = document.createElement('span');
  info.className = 'person-info';
  const title = document.createElement('strong');
  title.textContent = name;
  const detail = document.createElement('small');
  detail.textContent = subtitle;
  info.append(title, detail);
  button.append(info);
  button.addEventListener('click', async () => {
    button.disabled = true;
    try { await open(); }
    catch (error) { note('#account-status', error.message); }
    finally { button.disabled = false; }
  });
  return button;
}
function renderConversations() {
  const render = chat => conversationButton(chat.name, chat.id, () => selectConversation(String(chat.id), chat.name), chat.type === 'group' ? 'Group conversation' : 'Private conversation');
  renderList('#conversation-list', workspaceChats, 'No conversations yet. Open Friends to start a chat.', render);
  renderList('#groups-list', workspaceChats.filter(chat => chat.type === 'group'), 'You have not joined any groups yet.', render);
}
function showAccount(user) {
  if (typeof user.id !== 'string' || typeof user.username !== 'string') throw new Error('Account details could not be loaded. Please try again.');
  $('#my-name').textContent = user.username;
  $('#my-avatar').textContent = Array.from(user.username).slice(0, 2).join('').toUpperCase();
  $('#password').value = '';
  $('#auth-status').textContent = '';
  $('#account-status').textContent = '';
  $('#welcome').hidden = true;
  $('#app').hidden = false;
  account = user;
  generation += 1;
  resetConversation();
  showPanel('chats');
  refreshWorkspace();
}

$('#login-mode').addEventListener('click', () => setMode('login'));
$('#register-mode').addEventListener('click', () => setMode('register'));
authForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const username = $('#username').value.trim();
  if (!username) {
    $('#auth-status').textContent = 'Enter a username between 1 and 40 characters.';
    $('#username').focus();
    return;
  }
  authBusy(true);
  $('#auth-status').textContent = mode === 'login' ? 'Signing in…' : 'Creating your account…';
  try {
    showAccount(await api(mode, { username, password: $('#password').value }));
    $('#retry-session').hidden = true;
  } catch (error) {
    $('#password').value = '';
    $('#auth-status').textContent = error.message;
  } finally {
    authBusy(false);
  }
});
$('#logout').addEventListener('click', async () => {
  $('#logout').disabled = true;
  $('#account-status').textContent = 'Signing out…';
  try {
    await api('logout', {});
    account = null;
    generation += 1;
    resetConversation();
    workspaceChats = [];
    for (const id of ['friend-requests', 'friends-list', 'search-results', 'group-invitations', 'conversation-list', 'groups-list']) $(`#${id}`).replaceChildren();
    $('#friend-username').value = '';
    $('#group-name').value = '';
    $('#friend-status').textContent = '';
    $('#group-status').textContent = '';
    $('#text').value = '';
    updateDraft();
    closePicker();
    $('#my-name').textContent = '';
    $('#my-avatar').textContent = '';
    $('#app').hidden = true;
    $('#welcome').hidden = false;
    setMode('login');
    $('#auth-status').textContent = 'You have been logged out.';
    $('#username').focus();
  } catch (error) {
    $('#account-status').textContent = error.message;
  } finally {
    $('#logout').disabled = false;
  }
});
for (const button of document.querySelectorAll('[data-panel]')) button.addEventListener('click', () => showPanel(button.dataset.panel));

const input = $('#text');
function updateDraft() {
  $('#draft-count').textContent = `${Array.from(input.value).length} / 1000 characters`;
}
function closePicker() {
  $('#emoji-picker').hidden = true;
  $('#emoji-toggle').setAttribute('aria-expanded', 'false');
}
for (const [emoji, label] of [['😀', 'Smile'], ['😊', 'Happy'], ['😂', 'Laugh'], ['❤️', 'Heart'], ['👋', 'Wave'], ['👍', 'Thumbs up'], ['🎉', 'Celebrate'], ['✨', 'Sparkles'], ['☕', 'Coffee'], ['🌿', 'Leaf'], ['🙌', 'Raised hands'], ['🤗', 'Hug']]) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = emoji;
  button.setAttribute('aria-label', label);
  button.addEventListener('click', () => {
    const start = input.selectionStart;
    const end = input.selectionEnd;
    if (input.value.length - (end - start) + emoji.length > input.maxLength) return;
    input.setRangeText(emoji, start, end, 'end');
    updateDraft();
    closePicker();
    input.focus();
  });
  $('#emoji-picker').append(button);
}
$('#emoji-toggle').addEventListener('click', () => {
  const opening = $('#emoji-picker').hidden;
  $('#emoji-picker').hidden = !opening;
  $('#emoji-toggle').setAttribute('aria-expanded', String(opening));
  if (opening) $('#emoji-picker button').focus();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('#emoji-picker').hidden) {
    closePicker();
    $('#emoji-toggle').focus();
  }
});
input.addEventListener('input', updateDraft);

async function restoreSession() {
  sessionPending = true;
  authBusy(true);
  $('#retry-session').hidden = true;
  $('#auth-status').textContent = 'Checking your session…';
  try {
    showAccount(await api('me'));
  } catch (error) {
    $('#auth-status').textContent = error.status === 401 ? '' : error.message;
    $('#retry-session').hidden = error.status === 401;
  } finally {
    sessionPending = false;
    authBusy(false);
  }
}
$('#retry-session').addEventListener('click', restoreSession);

function resetConversation() {
  conversationVersion += 1;
  conversation = null;
  messageCursor = 0;
  $('#messages').replaceChildren();
  $('#conversation-members').textContent = '';
  note('#panel-title', 'Your conversations start here');
  note('#panel-subtitle', 'Select a friend or group on the left.');
  $('#text').value = '';
  $('#text').disabled = true;
  $('#send').disabled = true;
  updateDraft();
}

function note(id, value) { $(id).textContent = value; }
function actionButton(label, action, status) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.addEventListener('click', async () => {
    button.disabled = true;
    const version = generation;
    try {
      await action();
      if (version === generation) {
        note(status, 'Done.');
        await refreshWorkspace();
      }
    } catch (error) {
      if (version === generation) note(status, error.message);
    } finally { button.disabled = false; }
  });
  return button;
}
function row(label) {
  const item = document.createElement('div');
  item.className = 'social-row';
  const name = document.createElement('span');
  name.textContent = label;
  item.append(name);
  return item;
}
function renderList(id, entries, empty, render) {
  const container = $(id);
  container.replaceChildren();
  if (!entries.length) container.textContent = empty;
  for (const entry of entries) container.append(render(entry));
}
function options(id, entries, placeholder, label) {
  const select = $(id);
  const selected = select.value;
  select.replaceChildren(new Option(placeholder, ''));
  for (const entry of entries) select.add(new Option(label(entry), String(entry.id)));
  if (entries.some(entry => String(entry.id) === selected)) select.value = selected;
}
async function refreshWorkspace() {
  if (!account || refreshing) return;
  refreshing = true;
  const version = generation;
  try {
    const [friends, requests, chats, invitations] = await Promise.all([
      api('friends'), api('friend-requests'), api('conversations'), api('group-invitations'),
    ]);
    if (version !== generation || !account) return;
    workspaceChats = chats.conversations;
    renderConversations();
    renderList('#friends-list', friends.friends, 'No friends yet. Search for someone below.', friend =>
      conversationButton(friend.username, '', async () => {
        const result = await api('conversations/direct', { user_id: friend.id });
        if (version !== generation) return;
        await selectConversation(String(result.id), friend.username);
        await refreshWorkspace();
      }, 'Click to message')
    );
    renderList('#friend-requests', requests.requests, 'No pending requests.', entry => {
      const item = row(`${entry.username} · ${entry.incoming ? 'Incoming request' : 'Request sent'}`);
      if (entry.incoming) for (const action of ['accept', 'reject']) {
        item.append(actionButton(action === 'accept' ? 'Accept' : 'Reject', () => api(`friend-requests/${entry.id}/${action}`, {}), '#friend-status'));
      }
      return item;
    });
    renderList('#group-invitations', invitations.invitations, 'No pending invitations.', entry => {
      const item = row(`${entry.name} · Invited by ${entry.username}`);
      for (const action of ['accept', 'reject']) item.append(actionButton(action === 'accept' ? 'Join' : 'Decline', () => api(`group-invitations/${entry.id}/${action}`, {}), '#group-status'));
      return item;
    });
    options('#group-select', chats.conversations.filter(chat => chat.type === 'group' && chat.created_by === account.id), 'Choose a group', chat => chat.name);
    options('#group-friend', friends.friends, 'Choose a friend', friend => friend.username);
    await loadMessages();
    note('#account-status', '');
  } catch (error) {
    if (version === generation) {
      note('#account-status', error.message);
      if (error.status === 401) {
        account = null;
        generation += 1;
        resetConversation();
        $('#app').hidden = true;
        $('#welcome').hidden = false;
        note('#auth-status', 'Your session expired. Please log in again.');
      }
    }
  } finally { refreshing = false; }
}

$('#friend-search').addEventListener('submit', async event => {
  event.preventDefault();
  const version = generation;
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  note('#friend-status', 'Searching…');
  try {
    const result = await api(`users/search?username=${encodeURIComponent($('#friend-username').value.trim())}`);
    if (version !== generation) return;
    renderList('#search-results', result.users, 'No matching account found.', person => {
      const item = row(person.username);
      item.append(actionButton('Send friend request', () => api('friend-requests', { user_id: person.id }), '#friend-status'));
      return item;
    });
    note('#friend-status', 'Search complete.');
  } catch (error) { if (version === generation) note('#friend-status', error.message); }
  finally { button.disabled = false; }
});

async function selectConversation(selected, name) {
  resetConversation();
  if (!selected) return;
  note('#panel-title', name);
  note('#panel-subtitle', 'Conversation');
  conversation = selected;
  renderConversations();
  const version = generation;
  const selectionVersion = conversationVersion;
  try {
    const result = await api(`conversations/${selected}/members`);
    if (version !== generation || conversation !== selected || selectionVersion !== conversationVersion) return;
    note('#conversation-members', `Members: ${result.members.map(member => member.username).join(', ')}`);
    $('#text').disabled = false;
    $('#send').disabled = false;
    note('#draft-help', 'Enter to send · Shift+Enter for a new line · Click a message for its timestamp.');
    await loadMessages();
  } catch (error) { if (version === generation) note('#account-status', error.message); }
}
let messagesLoading = false;
async function loadMessages() {
  if (!account || !conversation || messagesLoading) return;
  messagesLoading = true;
  const selected = conversation;
  const version = generation;
  const selectionVersion = conversationVersion;
  try {
    const result = await api(`conversations/${selected}/messages?after=${messageCursor}`);
    if (version !== generation || selected !== conversation || selectionVersion !== conversationVersion) return;
    for (const message of result.messages) {
      if (message.id <= messageCursor) continue;
      const item = document.createElement('li');
      item.className = `message${message.sender_id === account.id ? ' mine' : ''}`;
      item.dataset.sender = message.sender_id;
      const bubble = document.createElement('button');
      bubble.type = 'button';
      bubble.setAttribute('aria-expanded', 'false');
      bubble.className = 'bubble';
      bubble.textContent = message.text;
      const meta = document.createElement('small');
      meta.id = `message-time-${message.id}`;
      bubble.setAttribute('aria-controls', meta.id);
      bubble.setAttribute('aria-label', `${message.text}. Show timestamp`);
      bubble.addEventListener('click', () => {
        item.dataset.expanded = item.dataset.expanded === 'true' ? 'false' : 'true';
        bubble.setAttribute('aria-expanded', item.dataset.expanded);
        updateTimestamps();
      });
      meta.textContent = `${message.username} · ${new Date(message.created_at).toLocaleString()}`;
      item.append(bubble, meta);
      $('#messages').append(item);
      messageCursor = message.id;
    }
    updateTimestamps();
    if (result.messages.length) $('#messages').scrollTop = $('#messages').scrollHeight;
  } finally { messagesLoading = false; }
}
function updateTimestamps() {
  const messages = Array.from($('#messages').children);
  messages.forEach((item, index) => {
    const next = messages[index + 1];
    item.children[1].hidden = next?.dataset.sender === item.dataset.sender && item.dataset.expanded !== 'true';
  });
}
input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!$('#send').disabled) $('#chat-form').requestSubmit();
  }
});
$('#chat-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!conversation || $('#send').disabled || !input.value.trim()) return;
  const selected = conversation;
  const version = generation;
  const draft = input.value;
  $('#send').disabled = true;
  try {
    await api(`conversations/${selected}/messages`, { text: draft });
    if (version !== generation || selected !== conversation) return;
    if (input.value === draft) input.value = '';
    updateDraft();
    await loadMessages();
    note('#account-status', '');
  } catch (error) { if (version === generation) note('#account-status', error.message); }
  finally { $('#send').disabled = !conversation; }
});
for (const [formId, action, status] of [
  ['#create-group', () => api('conversations/groups', { name: $('#group-name').value.trim() }), '#group-status'],
  ['#invite-friend', () => api(`conversations/${$('#group-select').value}/invitations`, { user_id: $('#group-friend').value }), '#group-status'],
]) {
  $(formId).addEventListener('submit', async event => {
    event.preventDefault();
    const version = generation;
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    try {
      await action();
      if (version !== generation) return;
      note(status, 'Done.');
      await refreshWorkspace();
    } catch (error) { if (version === generation) note(status, error.message); }
    finally { button.disabled = false; }
  });
}
setInterval(() => { if (!document.hidden && account) refreshWorkspace(); }, 4000);

restoreSession();
