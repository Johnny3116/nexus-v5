// PM2 manifest for NexusBody.
//
// Clean break from V4 — no nexus-core / nexus-chat / nexus-coding / nexus-tools
// / nexus-vtube entries. Only services whose code actually exists today.
//
// Usage:
//   pm2 start orchestration/deployments/ecosystem.config.js
//   pm2 save
//
// NOTE: `args` binds to the NexusBody Tailscale IP. Update to the real IP
// (see orchestration/service_discovery/tailscale_ips.yaml) before first
// start. Do NOT bind to 0.0.0.0 — doctrine 1.

module.exports = {
  apps: [
    {
      name: "nexus-gateway",
      script: "uvicorn",
      args: "api_gateway.main:app --host 100.84.78.77 --port 8000",
      cwd: "C:\\Users\\Nexus\\Nexus",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      min_uptime: "10s",
      env: {
        PYTHONPATH: "C:\\Users\\Nexus\\Nexus",
        PYTHONUNBUFFERED: "1",
      },
    },
    // Placeholders — uncomment as folders/services come online:
    //
    // {
    //   name: "nexus-skills",        // phase 5 — serving/skills/ + orchestration/autonomy/
    //   script: "uvicorn",
    //   args: "serving.skills.main:app --host <tailscale-ip> --port 8040",
    //   cwd: "C:\\Users\\Nexus\\Nexus",
    //   interpreter: "none",
    //   autorestart: true,
    //   env: { PYTHONPATH: "C:\\Users\\Nexus\\Nexus" },
    // },
  ],
};
