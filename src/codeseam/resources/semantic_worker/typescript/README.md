# Codeseam TypeScript Semantic Worker

This helper is the TypeScript semantic sidecar for Codeseam. It speaks Codeseam's
generic NDJSON semantic-worker protocol over stdio and exits when stdin closes.

The worker does not emit files, install dependencies, or run repository
scripts. It does load the `typescript` package installed in the analysed
repository, which runs that package's code. For this reason Codeseam starts the
worker only when `semantics.trust_project_code = true`. It resolves the
`typescript` package, reads the requested
`tsconfig`, follows local project references, maps requested items to the
nearest owning project config, and enriches selected spans with compact
TypeChecker facts when TypeScript is available.

Logs are written to stderr as single-line JSON records so stdout remains
reserved for protocol responses. Set `CODESEAM_SEMANTIC_WORKER_LOG=debug`,
`info`, `warn`, `error`, or `silent` to control verbosity. The default is
`warn`.

Run manually:

```bash
node src/codeseam/resources/semantic_worker/typescript/src/main.mjs
```

Each input line must be one Codeseam semantic enrichment request. Each output
line is one normalized semantic enrichment response.

Developer formatting:

```bash
npm install
npm run format:check
```
