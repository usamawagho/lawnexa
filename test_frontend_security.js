'use strict';

// Dependency-free regression tests for DOM XSS paths in index.html.
// Run with Node.js: node test_frontend_security.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script\s*>/gi)];
assert.equal(scripts.length, 1, 'Expected one application inline script');

function makeStorage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(String(key), String(value)),
    removeItem: key => values.delete(key),
    clear: () => values.clear(),
  };
}

const elements = new Map();
function createElement() {
  return {
    value: '', innerHTML: '', scrollTop: 0, scrollHeight: 0,
    classList: { add() {}, remove() {}, contains() { return false; } },
    querySelectorAll() { return []; },
    addEventListener() {},
    insertAdjacentHTML(_where, value) { this.innerHTML += value; },
  };
}
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, createElement());
    return elements.get(id);
  },
  addEventListener() {},
};
const context = vm.createContext({
  console,
  URL,
  document,
  window: { location: { href: 'https://lawnexa.vercel.app/', protocol: 'https:' } },
  localStorage: makeStorage(),
  sessionStorage: makeStorage(),
  setTimeout: () => 1,
  clearTimeout() {},
});
vm.runInContext(scripts[0][1], context, { filename: 'index.inline.js', timeout: 5000 });

const attack = '"/><img src=x onerror=alert(1)><svg onload=alert(2)></svg>';

vm.runInContext('lawyers = ' + JSON.stringify([{
  id: 'lawyer_x', name: attack, specialty: attack, specialtyBadge: attack,
  chamber: attack, city: 'Karachi', fee: 2500, desc: attack,
  avatar: 'javascript:alert(1)', isFeatured: false,
}]), context);
vm.runInContext('renderLawyersGrid()', context);
let rendered = elements.get('lawyers-grid').innerHTML;
assert.equal(rendered.includes('<img src=x onerror='), false, 'Lawyer-card fields must not execute HTML');
assert.equal(rendered.includes('src="javascript:'), false, 'Lawyer avatar must reject javascript: URLs');
assert.equal(rendered.includes('onclick="openDirectMessage('), false, 'User names must not enter inline JavaScript handlers');

vm.runInContext('bookings = ' + JSON.stringify([{
  id: attack, lawyerName: attack, clientName: attack, clientPhone: attack,
  notes: attack, status: attack, type: 'virtual', fee: 5000,
  date: '2026-10-29', time: '12:00',
}]), context);
vm.runInContext('renderMyBookings()', context);
rendered = elements.get('bookings-list-container').innerHTML;
assert.equal(rendered.includes('<svg onload='), false, 'Booking fields must be escaped');

vm.runInContext("localStorage.setItem('user', JSON.stringify({role:'advocate'})); sessionStorage.setItem('token','test-token');", context);
vm.runInContext('bookings = ' + JSON.stringify([{ id: 1, lawyerName: attack, clientName: attack, clientPhone: attack, notes: attack, status: 'Pending Confirmation', type: 'virtual', fee: 5000 }]), context);
vm.runInContext('renderClientRequests()', context);
rendered = elements.get('requests-list-container').innerHTML;
assert.equal(rendered.includes('<img src=x onerror='), false, 'Client request fields must be escaped');
assert.equal(rendered.includes('onclick="completeSessionAndReleaseEscrow('), false, 'Booking identifiers must not enter inline handlers');

vm.runInContext('activeChatLawyer = \"Attacker\"; chats = ' + JSON.stringify({ Attacker: [{ sender: 'me', text: attack, attachment: { type: 'file', name: attack } }] }), context);
vm.runInContext('renderChatThread()', context);
rendered = elements.get('direct-chat-thread').innerHTML;
assert.equal(rendered.includes('<svg onload='), false, 'Chat text and attachment labels must be escaped');

vm.runInContext('feedPosts = ' + JSON.stringify([{
  id: 1, author: attack, title: attack, timestamp: attack, category: attack,
  categoryClass: attack, text: attack, comments: [attack], likes: 1, liked: false,
  isAd: false, votes: { for: '<svg onload=alert(1)>', against: 2 },
  media: { type: 'image', url: 'javascript:alert(1)' },
}]), context);
vm.runInContext('renderFeedPosts()', context);
rendered = elements.get('posts-feed-container').innerHTML;
assert.equal(rendered.includes('<img src=x onerror='), false, 'Feed text must not execute HTML');
assert.equal(rendered.includes('src="javascript:'), false, 'Feed media must reject javascript: URLs');
assert.equal(rendered.includes('&lt;svg onload=alert(2)&gt;'), true, 'Attacker text may remain visible only as escaped text');

vm.runInContext(`renderAiMsg('user', ${JSON.stringify(attack)})`, context);
rendered = elements.get('chat-thread').innerHTML;
assert.equal(rendered.includes('<img src=x onerror='), false, 'AI chat user input must be rendered as text');

// Form inputs in legal-document drafts must be escaped before being placed in HTML.
vm.runInContext("localStorage.setItem('user', JSON.stringify({role:'client'}));", context);
document.getElementById('doc-type-select').value = 'police_complaint';
document.getElementById('doc_field_sho_station').value = attack;
document.getElementById('doc_field_incident_details').value = attack;
vm.runInContext('updateLiveDocumentPreview()', context);
rendered = elements.get('preview-screen-wrapper').innerHTML;
assert.equal(rendered.includes('<img src=x onerror='), false, 'Legal document fields must not execute HTML');
assert.equal(rendered.includes('&lt;img src=x onerror='), true, 'Document input should remain visible only as escaped text');

assert.equal(vm.runInContext(`resolveApiBase({ hostname: '127.0.0.1', protocol: 'http:', port: '5500', origin: 'http://127.0.0.1:5500' })`, context), 'http://127.0.0.1:8002', 'Live Server frontend must call the local API');
assert.equal(vm.runInContext(`resolveApiBase({ hostname: '127.0.0.1', protocol: 'http:', port: '8002', origin: 'http://127.0.0.1:8002' })`, context), 'http://127.0.0.1:8002', 'FastAPI-served frontend must use same-origin API');
assert.equal(vm.runInContext(`resolveApiBase({ hostname: 'lawnexa.vercel.app', protocol: 'https:', port: '', origin: 'https://lawnexa.vercel.app' })`, context), 'https://lawnexa.onrender.com', 'Hosted frontend must use deployed API');
assert.equal(vm.runInContext(`safeMediaSource('javascript:alert(1)')`, context), '', 'Unsafe media URL must be rejected');
assert.equal(vm.runInContext(`safeMediaSource('data:image/svg+xml;base64,PHN2Zz4=')`, context), '', 'SVG data URLs must be rejected');
assert.equal(html.includes('Advocate Muhammad Ali'), false, 'Directory must not ship fictitious seeded lawyers');
assert.equal(html.includes('PLD 2023 SC 142'), false, 'Unverified sample citations must not be presented as real law');
assert.equal(html.includes('Fee locked safely in Escrow'), false, 'UI must not claim escrow without a payment implementation');
assert.equal(html.includes('Emergency SOS signal broadcasted'), false, 'UI must not claim fake emergency dispatch');
assert.equal(html.includes("apiRequest('/api/lawyers')"), true, 'Public directory must load real backend lawyer records');
assert.equal(html.includes("apiRequest('/api/appointments'"), true, 'Bookings must use the backend API');
assert.equal(html.includes("apiRequest('/api/profile'"), true, 'Profile updates must use the backend API');
assert.equal(vm.runInContext(`escapeHTML('<script>alert(1)</script>')`, context), '&lt;script&gt;alert(1)&lt;/script&gt;');
console.log('Frontend security regression tests passed.');
