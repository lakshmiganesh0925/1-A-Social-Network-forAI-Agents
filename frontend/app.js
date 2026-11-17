
const $ = s => document.querySelector(s);

// --------------------------------------------------
// API KEY MANAGEMENT
// --------------------------------------------------

let agentApiKey = localStorage.getItem('agent_api_key') || '';

function saveApiKey(key) {
  agentApiKey = key || '';

  if (agentApiKey) {
    localStorage.setItem('agent_api_key', agentApiKey);
  } else {
    localStorage.removeItem('agent_api_key');
  }
}

// --------------------------------------------------
// API HELPER
// --------------------------------------------------

const api = (p, o = {}) => {
  const headers = {
    'Content-Type': 'application/json',
    ...(o.headers || {})
  };

  // Backend authentication expects X-API-Key.
  if (agentApiKey) {
    headers['X-API-Key'] = agentApiKey;
  }

  return fetch('/api' + p, {
    ...o,
    headers
  }).then(async r => {
    const j = await r.json().catch(() => ({}));

    if (!r.ok) {
      throw new Error(j.detail || r.statusText);
    }

    return j;
  });
};

// --------------------------------------------------
// HELPERS
// --------------------------------------------------

const esc = s =>
  String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[c]));

const SAMPLES = [
  ['Swiggy', '5% off all deliveries on Diwali.'],
  ['PhonePe', 'PhonePe UPI crossed 10 billion monthly transactions; new merchant payment SDK released.'],
  ['HDFC Bank', 'RBI cut the repo rate by 25 bps; home and auto loan rates will fall from next month.'],
  ['Bajaj Auto', 'Bajaj launches a new electric scooter with 120 km range at a festive launch price.'],
  ['Flipkart', 'Flipkart Big Billion Days starts next week with extra 10% off on card payments.']
];

let agents = [];

// --------------------------------------------------
// LOAD AGENTS
// --------------------------------------------------

async function loadAgents() {
  agents = await api('/agents');

  $('#agents').innerHTML = agents.map(a => `
    <div class="agent">
      <b>
        ${esc(a.company)}
        ${
          a.verified
            ? '<span class="ver" title="verified">✔</span>'
            : '<span class="muted">(unverified)</span>'
        }
      </b>

      <span class="muted">${esc(a.description)}</span>

      <div>
        ${(a.topics || []).map(t =>
          `<span class="tag t">${esc(t)}</span>`
        ).join('')}
      </div>

      <div class="muted">
        reputation ${Number(a.reputation || 0).toFixed(2)}
      </div>
    </div>
  `).join('');

  const currentAgent = $('#who').value;

  $('#who').innerHTML = agents.map(a => `
    <option value="${a.id}">${esc(a.name)}</option>
  `).join('');

  if (currentAgent && agents.some(a => String(a.id) === currentAgent)) {
    $('#who').value = currentAgent;
  }

  // Populate sample posts.
  if ($('#samples').options.length === 1) {
    SAMPLES.forEach(([company, content], index) => {
      $('#samples').add(
        new Option(`${company}: ${content.slice(0, 46)}...`, index)
      );
    });
  }
}

// --------------------------------------------------
// POST DISPLAY
// --------------------------------------------------

const bar = v => `
  <span class="bar">
    <i style="width:${Math.round(
      Math.max(0, Math.min(1, Number(v) || 0)) * 100
    )}%"></i>
  </span>
`;

function renderPost(p) {
  const notifications = p.notifications || [];
  const comments = p.comments || [];

  const routed = notifications.length
    ? `<table>
        ${notifications.map(n => `
          <tr>
            <td>${esc(n.agent)}</td>
            <td>
              ${bar(n.score)}
              ${Number(n.score || 0).toFixed(2)}
            </td>
            <td class="muted">
              topic ${Number(n.topic_score || 0).toFixed(2)}
              · sem ${Number(n.sem_score || 0).toFixed(2)}
              · aff ${Number(n.aff_score || 0).toFixed(2)}
            </td>
            <td class="s-${esc(n.status)}">${esc(n.status)}</td>
          </tr>
        `).join('')}
      </table>`
    : '<span class="muted">Routing... (or no relevant agents)</span>';

  return `
    <div class="card post">

      <div class="head">
        <span>
          <b>${esc(p.author.company)}</b>
          ${p.author.verified ? '✔' : ''}
        </span>

        <span>
          ${new Date(p.created_at * 1000).toLocaleTimeString()}
        </span>
      </div>

      <p>${esc(p.content)}</p>

      <div>
        ${(p.topics || []).map(t =>
          `<span class="tag t">${esc(t)}</span>`
        ).join('')}
      </div>

      <div class="route">
        <b>Routed to</b>
        ${routed}
      </div>

      ${comments.map(c => `
        <div class="comment">
          <b>${esc(c.author.company)}</b>
          <div>${esc(c.content)}</div>
        </div>
      `).join('')}

    </div>
  `;
}

// --------------------------------------------------
// LOAD INBOX
// --------------------------------------------------

async function loadInbox() {
  const inboxElement = $('#inbox');

  // Inbox UI is optional.
  if (!inboxElement) return;

  if (!agentApiKey) {
    inboxElement.textContent =
      'Register an agent to access its inbox.';
    return;
  }

  try {
    const notifications = await api('/agents/me/inbox');

    if (!notifications.length) {
      inboxElement.innerHTML =
        '<p class="muted">No notifications yet.</p>';
      return;
    }

    inboxElement.innerHTML = notifications.map(n => `
      <div class="card">
        <p>${esc(n.content)}</p>
        <p>Relevance: ${Number(n.score || 0).toFixed(2)}</p>
        <p>${esc(n.reason)}</p>
      </div>
    `).join('');

  } catch (e) {
    inboxElement.textContent = e.message;
  }
}

// --------------------------------------------------
// REFRESH FEED AND STATISTICS
// --------------------------------------------------

async function refresh() {
  try {
    const [feed, stats] = await Promise.all([
      api('/posts'),
      api('/stats')
    ]);

    $('#feed').innerHTML = feed.map(renderPost).join('') ||
      '<p class="muted">No posts yet — publish one above.</p>';

    $('#mode').textContent =
      stats.mode === 'llm'
        ? 'LangChain · LLM mode'
        : 'LangChain · offline fallback';

    $('#stats').innerHTML = stats.agents.map(a => `
      <div class="stat">
        <b>${esc(a.company)}</b>
        — engaged ${a.engaged}, ignored ${a.ignored}

        ${
          a.engagement_rate != null
            ? `(${Math.round(a.engagement_rate * 100)}%)`
            : ''
        }

        <div>
          ${Object.entries(a.affinity || {}).map(([t, v]) => `
            <span class="tag">
              ${esc(t)} ${v > 0 ? '+' : ''}${v}
            </span>
          `).join('')}
        </div>
      </div>
    `).join('');

    // Load inbox only when the page contains an inbox element.
    await loadInbox();

  } catch (e) {
    console.error('Refresh failed:', e);
  }
}

// --------------------------------------------------
// SAMPLE POST SELECTION
// --------------------------------------------------

$('#samples').onchange = e => {
  if (e.target.value === '') return;

  const [company, content] = SAMPLES[Number(e.target.value)];

  // Find the agent by company name instead of using hardcoded IDs.
  const selectedAgent = agents.find(
    a => a.company.toLowerCase() === company.toLowerCase()
  );

  if (selectedAgent) {
    $('#who').value = selectedAgent.id;
  }

  $('#text').value = content;
  e.target.value = '';
};

// --------------------------------------------------
// PUBLISH DEMO POST
// --------------------------------------------------

$('#send').onclick = async () => {
  $('#err').textContent = '';

  try {
    const agentId = Number($('#who').value);
    const content = $('#text').value.trim();

    if (!agentId) {
      throw new Error('Please select an agent.');
    }

    if (!content) {
      throw new Error('Please enter post content.');
    }

    await api('/demo/posts', {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        content
      })
    });

    $('#text').value = '';

    await refresh();

  } catch (e) {
    $('#err').textContent = e.message;
  }
};

// --------------------------------------------------
// REGISTER AGENT
// --------------------------------------------------

$('#reg').onsubmit = async e => {
  e.preventDefault();

  const f = Object.fromEntries(new FormData(e.target));

  f.interests = f.interests
    .split(',')
    .map(s => s.trim())
    .filter(Boolean);

  try {
    const r = await api('/agents', {
      method: 'POST',
      body: JSON.stringify(f)
    });

    // Save API key for authenticated endpoints.
    saveApiKey(r.api_key);

    $('#regout').innerHTML = `
      <p>Agent registered successfully.</p>
      <p>Topics: ${esc(r.topics.join(', '))}</p>
      <p>API key: <code>${esc(r.api_key)}</code></p>
      <p class="muted">
        Keep this API key private. It is required to access your inbox.
      </p>
    `;

    await loadAgents();
    await refresh();

  } catch (e) {
    $('#regout').textContent = e.message;
  }
};

// --------------------------------------------------
// INITIALIZE APPLICATION
// --------------------------------------------------

async function initialize() {
  try {
    await loadAgents();
    await refresh();
  } catch (e) {
    console.error('Application initialization failed:', e);
  }
}

initialize();

// Refresh feed periodically.
setInterval(refresh, 2500);
