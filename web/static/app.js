/* ── Toast notifications ─────────────────────────────────────────────────── */
let _toastContainer = null;
function _getToastContainer() {
  if (!_toastContainer) {
    _toastContainer = document.createElement('div');
    _toastContainer.className = 'toast-container';
    document.body.appendChild(_toastContainer);
  }
  return _toastContainer;
}

function showToast(msg, type = 'info') {
  const c = _getToastContainer();
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  c.appendChild(t);
  requestAnimationFrame(() => requestAnimationFrame(() => t.classList.add('show')));
  setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => t.remove(), 300);
  }, 3500);
}

/* ── Confirm dialog ──────────────────────────────────────────────────────── */
function confirmDialog(msg) {
  return new Promise(resolve => {
    const overlay = document.getElementById('confirm-overlay');
    document.getElementById('confirm-msg').textContent = msg;
    overlay.style.display = 'flex';
    const yes = document.getElementById('confirm-yes');
    const no  = document.getElementById('confirm-no');
    const done = val => {
      overlay.style.display = 'none';
      yes.onclick = null;
      no.onclick  = null;
      resolve(val);
    };
    yes.onclick = () => done(true);
    no.onclick  = () => done(false);
  });
}

/* ── Funções globais compartilhadas ─────────────────────────────────────── */

/**
 * Adiciona uma linha colorida ao console.
 * @param {string} logId  - ID do elemento <pre>
 * @param {string} msg    - Mensagem
 * @param {string} level  - INFO | WARNING | ERROR | SUCCESS | DIM
 */
function appendLog(logId, msg, level = 'INFO') {
  const el = document.getElementById(logId);
  if (!el) return;

  const now = new Date();
  const ts  = now.toTimeString().slice(0, 8);
  const line = document.createElement('span');
  line.className = level;
  line.textContent = `${ts}  ${level.padEnd(8)}  ${msg}\n`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

/** Limpa o console. */
function clearLog(logId) {
  const el = document.getElementById(logId);
  if (el) el.innerHTML = '';
}

/** Atualiza o status no rodapé da sidebar. */
function setStatus(text, colorClass) {
  const dot  = document.getElementById('status-dot');
  const lbl  = document.getElementById('status-text');
  if (!dot || !lbl) return;
  dot.className = `dot ${colorClass}`;
  lbl.textContent = text;
}

/* ── Tab switching ──────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      btn.classList.add('active');
      const content = document.getElementById(`tab-${name}`);
      if (content) content.classList.add('active');
    });
  });
});
