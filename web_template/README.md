# KPCL Energy Dashboard (web)

The React dashboard for the KPCL energy-management prototype. Project documentation lives in the
repository root:

- [README.md](../README.md) — what the project is, layout, API, every assumed value
- [HOW_TO_RUN.md](../HOW_TO_RUN.md) — start the API + this dashboard (`run-demo.ps1`)
- [AGENT_CONTEXT.md](../AGENT_CONTEXT.md) — developer hand-off notes

```bash
npm install
npm run dev        # http://localhost:5173 — expects the API at http://127.0.0.1:8000 (override with VITE_API_BASE_URL)
npm run build      # static files in dist/
```

All data shown is a benchmark-calibrated simulation, not real KPCL meter data.

Built on the [shadcn-admin](https://github.com/satnaing/shadcn-admin) template by Sat Naing (MIT,
see [LICENSE](LICENSE)).
