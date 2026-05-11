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
