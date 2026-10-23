// DOM/API contract smoke check. This does not replace an interactive browser test.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync('templates/index.html', 'utf8');
const source = fs.readFileSync('static/chat.js', 'utf8');
class Element {
  constructor() {
    this.value = ''; this.hidden = false; this.disabled = false;
    this.dataset = {}; this.handlers = {}; this.attrs = {}; this.children = [];
    this.classList = { toggle() {} }; this.maxLength = 1000;
    this.selectionStart = 0; this.selectionEnd = 0; this.scrollHeight = 100;
    this.textContent = '';
  }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(k, v) { this.handlers[k] = v; }
  append(...elements) { this.children.push(...elements); }
  replaceChildren(...elements) { this.children = elements; this.value = ''; this.textContent = ''; }
  add(element) { this.children.push(element); }
  focus() {}
  querySelector() { return this.children[0] || new Element(); }
  setRangeText(text, start, end) { this.value = this.value.slice(0, start) + text + this.value.slice(end); }
  async fire(type, extra = {}) { return this.handlers[type]?.({ preventDefault() {}, currentTarget: this, ...extra }); }
  requestSubmit() { this.submission = this.fire('submit'); }
}
const ids = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
const elements = new Map(ids.map(id => [id, new Element()]));
assert.equal(elements.size, ids.length, 'unique HTML ids');
for (const match of source.matchAll(/\$\('#([^']+)'\)/g)) {
  if (match[1] !== 'emoji-picker button') assert(elements.has(match[1]), `DOM reference ${match[1]}`);
}
for (const match of html.matchAll(/(?:for|aria-controls|aria-labelledby|aria-describedby)="([^"]+)"/g)) {
  for (const id of match[1].split(' ')) assert(elements.has(id), `label/ARIA reference ${id}`);
}
const nav = ['chats', 'friends', 'groups'].map(name => {
  const item = new Element(); item.dataset.panel = name; return item;
});
const document = {
  hidden: false,
  querySelector(s) { return s === '#emoji-picker button' ? elements.get('emoji-picker').children[0] : elements.get(s.slice(1)); },
  querySelectorAll() { return nav; }, createElement() { return new Element(); }, addEventListener() {},
};
const person = { id: 'bob', username: '<img src=x onerror=alert(1)>' };
let signedIn = false, requestSent = false, incoming = true, accepted = false, groupCreated = false, sent = false, invited = false;
const calls = [];
let polling;
const respond = (status, data) => ({ ok: status < 400, status, json: async () => data });
const fetch = async (path, options) => {
  calls.push({ path, options });
  const body = options.body && JSON.parse(options.body);
  if (path === '/api/me') return respond(401, { error: 'Login required.' });
  if (path === '/api/register') { signedIn = true; return respond(201, { id: 'alice', username: 'Alice' }); }
  if (path === '/api/logout') { signedIn = false; return respond(200, { message: 'Logged out' }); }
  assert(signedIn, 'social request requires signed-in client');
  if (path === '/api/friends') return respond(200, { friends: accepted ? [person] : [] });
  if (path === '/api/friend-requests' && body) { assert.equal(body.user_id, 'bob'); requestSent = true; return respond(201, { id: 1 }); }
  if (path === '/api/friend-requests') return respond(200, { requests: incoming ? [{ id: 2, username: 'Bob', incoming: true }] : [] });
  if (path.startsWith('/api/users/search?')) return respond(200, { users: [person] });
  if (path === '/api/friend-requests/2/accept') { incoming = false; accepted = true; return respond(200, { status: 'accepted' }); }
  if (path === '/api/conversations/direct') { assert(accepted); return respond(201, { id: 10 }); }
  if (path === '/api/conversations') return respond(200, { conversations: [
    ...(accepted ? [{ id: 10, name: 'Bob', type: 'direct' }] : []),
    ...(groupCreated ? [{ id: 11, name: 'Friends', type: 'group', created_by: 'alice' }] : []),
  ] });
  if (path === '/api/group-invitations') return respond(200, { invitations: [] });
  if (path === '/api/conversations/10/members') return respond(200, { members: [{ username: 'Alice' }, person] });
  if (path === '/api/conversations/10/messages' && body) { assert.equal(body.text, 'Hello 👋'); sent = true; return respond(201, { id: 1 }); }
  if (path.startsWith('/api/conversations/10/messages?')) return respond(200, { messages: sent ? [{ id: 1, sender_id: 'bob', username: 'Bob', text: person.username, created_at: '2026-10-23T00:00:00Z' }] : [] });
  if (path === '/api/conversations/groups') { assert.equal(body.name, 'Friends'); groupCreated = true; return respond(201, { id: 11 }); }
  if (path === '/api/conversations/11/invitations') { assert.equal(body.user_id, 'bob'); invited = true; return respond(201, { id: 2 }); }
  throw Error(`Unexpected API request: ${path}`);
};
vm.runInNewContext(source, {
  document, fetch, Error, Array, Object, String, JSON, Date, encodeURIComponent,
  Option: function(text, value) { this.text = text; this.value = value; },
  setInterval(callback) { polling = callback; },
});
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  await tick();
  assert.equal(elements.get('auth-submit').disabled, false);
  await elements.get('register-mode').fire('click');
  assert.equal(elements.get('password').minLength, 10);
  elements.get('username').value = 'Alice'; elements.get('password').value = 'test-password';
  await elements.get('auth-form').fire('submit'); await tick();
  assert.equal(elements.get('app').hidden, false);
  await nav[1].fire('click'); assert.equal(elements.get('friends-panel').hidden, false);
  elements.get('friend-username').value = 'Bob';
  await elements.get('friend-search').fire('submit');
  const search = elements.get('search-results').children[0];
  assert.equal(search.children[0].textContent, person.username);
  await search.children[1].fire('click'); assert(requestSent);
  await elements.get('friend-requests').children[0].children[1].fire('click'); assert(accepted);
  await elements.get('friends-list').children[0].fire('click');
  assert.equal(elements.get('send').disabled, false);
  elements.get('text').value = 'Hello 👋';
  await elements.get('text').fire('keydown', { key: 'Enter' });
  await elements.get('chat-form').submission; assert(sent);
  assert.equal(elements.get('messages').children[0].children[0].textContent, person.username);
  assert.equal(elements.get('text').value, '');
  const first = elements.get('messages').children[0];
  assert.equal(first.children[1].hidden, false);
  const second = new Element(); second.dataset.sender = 'bob'; second.append(new Element(), new Element());
  elements.get('messages').append(second);
  await first.children[0].fire('click');
  assert.equal(first.children[1].hidden, false, 'click reveals an earlier timestamp');
  await first.children[0].fire('click');
  assert.equal(first.children[1].hidden, true, 'only the last consecutive timestamp remains');
  elements.get('messages').children.pop();
  elements.get('text').value = 'new line';
  await elements.get('text').fire('keydown', { key: 'Enter', shiftKey: true });
  assert.equal(elements.get('text').value, 'new line', 'Shift+Enter preserves the draft');

  elements.get('group-name').value = 'Friends'; await elements.get('create-group').fire('submit');
  assert(groupCreated);
  elements.get('group-select').value = '11'; elements.get('group-friend').value = 'bob';
  await elements.get('invite-friend').fire('submit'); assert(invited);
  await polling(); await tick();
  assert.equal(elements.get('messages').children.length, 1, 'polling does not duplicate messages');
  await elements.get('logout').fire('click');
  assert.equal(elements.get('app').hidden, true);
  assert.equal(elements.get('messages').children.length, 0);
  assert.equal(elements.get('friends-list').children.length, 0);
  assert(calls.every(call => call.options.credentials === 'same-origin'));
  assert(!/innerHTML|api\('join'/.test(source));
  console.log('PASS: DOM/ARIA contracts, signup, search, send/accept friend request, private chat, message rendering, polling, groups, invitations, logout cleanup, safe text rendering.');
})().catch(error => { console.error(error); process.exitCode = 1; });
