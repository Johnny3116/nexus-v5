/**
 * buildPanel.js — renders build_response WS messages.
 *
 * Shows the list of generated files with a "View" toggle to inspect
 * the content. No execution, no git — just display.
 * Files are written to workspace/output/ on the server.
 */

export function handleBuildResponse(msg) {
  const existing = document.getElementById("build-panel");
  if (existing) existing.remove();

  const panel = document.createElement("div");
  panel.id = "build-panel";
  panel.className = "build-panel";

  if (!msg.success) {
    panel.innerHTML = `
      <div class="build-header">
        <span class="build-label build-label-fail">BUILD FAILED</span>
        <button class="build-close" title="Dismiss">✕</button>
      </div>
      <div class="build-error">${_esc(msg.error || "Unknown error")}</div>
      ${msg.notes ? `<div class="build-notes">${_esc(msg.notes)}</div>` : ""}
    `;
  } else {
    const fileItems = (msg.written_files || []).map(f => `
      <div class="build-file">
        <span class="build-file-path">${_esc(f)}</span>
        <span class="build-file-tag">written</span>
      </div>
    `).join("");

    panel.innerHTML = `
      <div class="build-header">
        <span class="build-label build-label-ok">BUILD COMPLETE</span>
        <button class="build-close" title="Dismiss">✕</button>
      </div>
      <div class="build-summary">
        ${msg.written_files.length} file(s) written to <code>workspace/output/</code>
      </div>
      <div class="build-files">${fileItems}</div>
      ${msg.notes ? `<div class="build-notes">${_esc(msg.notes)}</div>` : ""}
    `;
  }

  panel.querySelector(".build-close").addEventListener("click", () => panel.remove());
  document.body.appendChild(panel);

  // Auto-dismiss success after 12s
  if (msg.success) setTimeout(() => panel.remove(), 12000);
}

function _esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
