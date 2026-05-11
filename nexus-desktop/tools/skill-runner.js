'use strict';

/**
 * Local skill runner — loads JS skill modules from skills/ folder.
 *
 * Skill format (skills/my-skill.js):
 *   module.exports = {
 *     name:        'my-skill',
 *     description: 'What it does',
 *     params:      { key: 'description' },   // optional schema hint
 *     async execute(params, context) {
 *       return { result: '...' };
 *     }
 *   };
 *
 * API (mounted on main Express server):
 *   GET  /skills            — list all loaded skills
 *   POST /skill/:name       — run a skill by name
 *   POST /skills/reload     — hot-reload skills from disk
 */

const path = require('path');
const fs   = require('fs');

const SKILLS_DIR = path.join(__dirname, '..', 'skills');

let _registry = {};

function load() {
  _registry = {};
  if (!fs.existsSync(SKILLS_DIR)) {
    fs.mkdirSync(SKILLS_DIR, { recursive: true });
    return 0;
  }

  const files = fs.readdirSync(SKILLS_DIR).filter(f => f.endsWith('.js') && !f.startsWith('_'));
  for (const file of files) {
    const skillPath = path.join(SKILLS_DIR, file);
    try {
      delete require.cache[require.resolve(skillPath)]; // hot-reload support
      const skill = require(skillPath);
      if (!skill.name || typeof skill.execute !== 'function') {
        console.warn(`[skills] ${file}: missing name or execute() — skipping`);
        continue;
      }
      _registry[skill.name] = skill;
      console.log(`[skills] loaded: ${skill.name}`);
    } catch (err) {
      console.error(`[skills] failed to load ${file}:`, err.message);
    }
  }
  return Object.keys(_registry).length;
}

// ── Route handlers ────────────────────────────────────────────────────────────

function listSkills(_req, res) {
  const skills = Object.values(_registry).map(s => ({
    name:        s.name,
    description: s.description || '',
    params:      s.params       || {},
    version:     s.version      || '1.0.0',
  }));
  res.json({ ok: true, count: skills.length, skills });
}

async function runSkill(req, res) {
  const { name } = req.params;
  const skill = _registry[name];
  if (!skill) {
    return res.status(404).json({
      ok: false,
      error: `Skill '${name}' not found`,
      available: Object.keys(_registry),
    });
  }
  try {
    const result = await skill.execute(req.body || {}, { req, res });
    res.json({ ok: true, result });
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

function reloadSkills(_req, res) {
  const count = load();
  res.json({ ok: true, loaded: count, skills: Object.keys(_registry) });
}

function mount(app) {
  load(); // initial load at startup
  app.get('/skills',          listSkills);
  app.post('/skill/:name',    runSkill);
  app.post('/skills/reload',  reloadSkills);
}

module.exports = { mount, load };
