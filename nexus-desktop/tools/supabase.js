'use strict';

/**
 * Supabase tool layer — CRUD + RPC via the JS client.
 *
 * Env vars:
 *   SUPABASE_URL   — project URL
 *   SUPABASE_KEY   — service role or anon key
 *
 * API (mounted on main Express server):
 *   GET  /db/tables              — list all tables (via information_schema)
 *   POST /db/:table/select       — select rows (filters, order, limit)
 *   POST /db/:table/insert       — insert row(s)
 *   POST /db/:table/update       — update rows (requires match filter)
 *   POST /db/:table/delete       — delete rows (requires match filter)
 *   POST /db/rpc/:fn             — call a Supabase RPC function
 *   POST /db/sql                 — raw SQL via rpc('exec_sql', ...) if configured
 */

const { createClient } = require('@supabase/supabase-js');
const ws = require('ws');

let _client = null;

function getClient() {
  if (_client) return _client;
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_KEY || process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) throw new Error('SUPABASE_URL and SUPABASE_KEY must be set in .env');
  _client = createClient(url, key, {
    realtime: { transport: ws },
  });
  return _client;
}

function handleError(res, error, data) {
  if (error) return res.status(500).json({ ok: false, error: error.message });
  return res.json({ ok: true, data });
}

// ── Route handlers ────────────────────────────────────────────────────────────

async function listTables(req, res) {
  try {
    const db = getClient();
    const { data, error } = await db.rpc('get_tables').catch(() => ({ data: null, error: { message: 'get_tables RPC not available' } }));
    if (error) {
      // Fallback: query information_schema
      const { data: tables, error: e2 } = await db
        .from('information_schema.tables')
        .select('table_name, table_schema')
        .eq('table_schema', 'public');
      return handleError(res, e2, tables);
    }
    return handleError(res, null, data);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

async function selectRows(req, res) {
  try {
    const db = getClient();
    const { columns = '*', filters = {}, order, limit = 100, offset = 0 } = req.body || {};
    let q = db.from(req.params.table).select(columns).range(offset, offset + limit - 1);
    for (const [col, val] of Object.entries(filters)) q = q.eq(col, val);
    if (order) q = q.order(order.column, { ascending: order.ascending ?? true });
    const { data, error } = await q;
    handleError(res, error, data);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

async function insertRows(req, res) {
  try {
    const db = getClient();
    const { rows } = req.body || {};
    if (!rows) return res.status(400).json({ ok: false, error: 'rows required' });
    const { data, error } = await db.from(req.params.table).insert(rows).select();
    handleError(res, error, data);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

async function updateRows(req, res) {
  try {
    const db = getClient();
    const { match, values } = req.body || {};
    if (!match || !values) return res.status(400).json({ ok: false, error: 'match and values required' });
    let q = db.from(req.params.table).update(values);
    for (const [col, val] of Object.entries(match)) q = q.eq(col, val);
    const { data, error } = await q.select();
    handleError(res, error, data);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

async function deleteRows(req, res) {
  try {
    const db = getClient();
    const { match } = req.body || {};
    if (!match) return res.status(400).json({ ok: false, error: 'match required' });
    let q = db.from(req.params.table).delete();
    for (const [col, val] of Object.entries(match)) q = q.eq(col, val);
    const { data, error } = await q.select();
    handleError(res, error, data);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

async function callRpc(req, res) {
  try {
    const db = getClient();
    const { data, error } = await db.rpc(req.params.fn, req.body || {});
    handleError(res, error, data);
  } catch (err) {
    res.status(500).json({ ok: false, error: err.message });
  }
}

function mount(app) {
  app.get('/db/tables',          listTables);
  app.post('/db/:table/select',  selectRows);
  app.post('/db/:table/insert',  insertRows);
  app.post('/db/:table/update',  updateRows);
  app.post('/db/:table/delete',  deleteRows);
  app.post('/db/rpc/:fn',        callRpc);
}

module.exports = { mount };
