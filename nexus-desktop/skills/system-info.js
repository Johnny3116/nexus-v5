'use strict';
const os = require('os');

module.exports = {
  name: 'system-info',
  description: 'Return detailed WorkstationPrime system info with uptime and memory formatted',
  version: '1.0.0',
  params: {},

  async execute(_params) {
    const uptimeSecs = os.uptime();
    const hours   = Math.floor(uptimeSecs / 3600);
    const minutes = Math.floor((uptimeSecs % 3600) / 60);
    const freeMB  = Math.round(os.freemem()  / 1024 / 1024);
    const totalMB = Math.round(os.totalmem() / 1024 / 1024);
    const usedPct = Math.round(((totalMB - freeMB) / totalMB) * 100);

    return {
      hostname:   os.hostname(),
      platform:   process.platform,
      arch:       os.arch(),
      cpus:       os.cpus().length,
      cpu_model:  os.cpus()[0]?.model || 'unknown',
      memory: {
        free_mb:  freeMB,
        total_mb: totalMB,
        used_pct: usedPct,
      },
      uptime: `${hours}h ${minutes}m`,
      node:   process.version,
    };
  },
};
