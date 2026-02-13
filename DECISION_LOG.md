# Decision Log

Significant design and architectural decisions, recorded with context for future reference.

### DEC-001: DuckDB over SQLite for storage (pre-v1)
DuckDB supports analytical queries natively and has better columnar storage for the
read-heavy access pattern (scheduling queries, analytics aggregations). SQLite would be
simpler and more portable but requires more manual optimization for analytical workloads.

### DEC-002: FSRS-4.5 for spaced repetition scheduling (pre-v1)
FSRS-4.5 is the current state-of-the-art open-source spaced repetition algorithm,
outperforming SM-2 and Leitner on retention metrics. The implementation follows the
reference algorithm closely. Considered SM-2 (simpler, widely understood) but FSRS
provides better scheduling with fewer reviews needed.

### DEC-003: WoodpeckerSession as standalone, not TrainingSession subclass (v2)
WoodpeckerSession has fundamentally different lifecycle semantics — it cycles through
a fixed bundle rather than drawing from a scheduled queue. Making it a subclass would
require overriding most methods and violate Liskov substitution. Composition over
inheritance applies here.

### DEC-004: Bundle IDs use `bundle:{slug}` format (v3)
Namespaced IDs prevent collisions with exercise IDs in the same storage layer.
The `bundle:` prefix makes bundle references self-documenting in logs and queries.
Slugs restricted to lowercase alphanum + hyphens, 2-64 chars.

### DEC-005: `from __future__ import annotations` + TYPE_CHECKING for circular imports (v2)
The openings module has circular dependencies between `explorer.py` and
`storage.opening_store`. Rather than restructuring the module hierarchy, deferred
annotations + TYPE_CHECKING blocks resolve the import cycle with minimal code change.
This is now a project-wide convention.

### DEC-006: Non-standard package layout with uv_build (v1)
`src/` as the module root with `module-root = ""` in pyproject.toml. This was chosen
to match the existing directory structure. A more conventional `src/chess_trainer/`
layout would be cleaner but would require renaming every import in the codebase.

### DEC-007: DELETE + INSERT instead of INSERT OR REPLACE for DuckDB FK tables (v2)
DuckDB's INSERT OR REPLACE with foreign keys doesn't update all columns reliably.
The workaround is explicit DELETE followed by INSERT. Documented in CLAUDE.md pitfalls.

### DEC-008: Separate auth database from training data (v3.2-B1)
Auth tables (users, invite_codes, sessions) live in `auth.db`, not `trainer.db`. B2 will
give each user their own training DB, but auth must be global — you can't look up which
user DB to open without first authenticating. The `AuthStore` class follows the same
Repository pattern as the main storage layer (lazy connect, context manager, schema init).

### DEC-009: Zero new dependencies for auth (v3.2-B1)
Uses stdlib-only auth: `hashlib.pbkdf2_hmac('sha256')` with 600k iterations for password
hashing, `secrets.token_urlsafe()` for session tokens and invite codes, DB-backed sessions
(token in cookie, looked up in sessions table). No JWT, no signing keys, no third-party
auth libraries. Sessions are revocable by deleting from the DB.

### DEC-010: Auth is optional, disabled by default (v3.2-B1)
`auth.enabled = false` is the default — CLI and local web server work exactly as before.
The `AuthMiddleware` becomes a no-op (sets `request.state.user = None`, passes through).
Only the hosted web deployment enables auth via config. This preserves the single-user
CLI/local experience and ensures existing tests pass without modification.
