# soul/

`soul.md` and `doctrines.md` are **copies** of the canonical files at:

- `../../safety/identity/soul.md`
- `../../safety/identity/doctrines.md`

The copy lives here so the desktop app is self-contained — it can run on any
machine, and the source can be edited in Lovable / cloud Claude without
needing the full Nexus repo present.

## Sync rule

The canonical source is `safety/identity/`. When `soul.md` changes there,
copy it here too:

```powershell
Copy-Item ..\..\safety\identity\soul.md   .\soul.md   -Force
Copy-Item ..\..\safety\identity\doctrines.md .\doctrines.md -Force
```

(A future job in `scripts/` will automate this — for now, manual sync.)

## How it's used

`bridges/ollama-bridge.js` reads these two files at startup and prepends them
as the system message on every Ollama call. The injection is unconditional —
the chat UI cannot bypass it.
