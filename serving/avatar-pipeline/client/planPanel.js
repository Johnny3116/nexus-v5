/**
 * planPanel.js — renders plan_response WS messages as a UI card.
 *
 * Shows the plan summary, implementation steps, risks, and
 * approve / reject buttons. Approve/reject sends a plan_decision
 * message back over the existing WS connection.
 *
 * Milestone 3: no execution on approval — just queues the decision.
 */

let _ws = null;

export function setPlanPanelSocket(ws) {
  _ws = ws;
}

export function handlePlanResponse(msg) {
  const existing = document.getElementById("plan-panel");
  if (existing) existing.remove();

  const plan = msg.plan;
  const planId = msg.plan_id;

  if (!plan || !planId) {
    // Planner failed — show compact error notice
    if (msg.planner_error) {
      _showNotice(`Plan generation failed: ${msg.planner_error}`, "error");
    }
    return;
  }

  const panel = document.createElement("div");
  panel.id = "plan-panel";
  panel.className = "plan-panel";

  panel.innerHTML = `
    <div class="plan-header">
      <span class="plan-label">PLAN</span>
      <button class="plan-close" title="Dismiss">✕</button>
    </div>
    <div class="plan-summary">${_esc(plan.summary)}</div>

    <div class="plan-section">
      <div class="plan-section-title">Steps</div>
      <ol class="plan-list">
        ${plan.implementation_steps.map(s => `<li>${_esc(s)}</li>`).join("")}
      </ol>
    </div>

    ${plan.target_files.length ? `
    <div class="plan-section">
      <div class="plan-section-title">Files</div>
      <ul class="plan-list">
        ${plan.target_files.map(f => `<li><code>${_esc(f)}</code></li>`).join("")}
      </ul>
    </div>` : ""}

    ${plan.risks.length ? `
    <div class="plan-section">
      <div class="plan-section-title">Risks</div>
      <ul class="plan-list plan-risks">
        ${plan.risks.map(r => `<li>${_esc(r)}</li>`).join("")}
      </ul>
    </div>` : ""}

    <div class="plan-section">
      <div class="plan-section-title">Rollback</div>
      <div class="plan-rollback">${_esc(plan.rollback_plan)}</div>
    </div>

    <div class="plan-actions">
      <button class="plan-btn plan-approve" data-plan-id="${_esc(planId)}">Approve</button>
      <button class="plan-btn plan-reject"  data-plan-id="${_esc(planId)}">Reject</button>
    </div>
  `;

  panel.querySelector(".plan-close").addEventListener("click", () => panel.remove());

  panel.querySelector(".plan-approve").addEventListener("click", () => {
    _decide(planId, "approve");
    panel.remove();
    _showNotice("Plan approved — queued for builder.", "ok");
  });

  panel.querySelector(".plan-reject").addEventListener("click", () => {
    _decide(planId, "reject");
    panel.remove();
    _showNotice("Plan rejected.", "info");
  });

  document.body.appendChild(panel);
}

function _decide(planId, decision) {
  if (!_ws || _ws.readyState !== WebSocket.OPEN) {
    console.warn("planPanel: WS not open, cannot send plan_decision");
    return;
  }
  _ws.send(JSON.stringify({ type: "plan_decision", plan_id: planId, decision }));
}

function _showNotice(text, kind = "info") {
  const n = document.createElement("div");
  n.className = `plan-notice plan-notice-${kind}`;
  n.textContent = text;
  document.body.appendChild(n);
  setTimeout(() => n.remove(), 4000);
}

function _esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
