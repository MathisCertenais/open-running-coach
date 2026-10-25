# SQLite via the standard library

User state — notes, goals, profile, weights, shoes, RPE, plans — lives in a
single `coach.db` SQLite file accessed through Python's stdlib `sqlite3`, with no
ORM and no database server. The app is single-user and local, so an embedded
file gives ACID writes, ad-hoc querying and trivial backup (copy one file) at
zero operational cost, while an ORM or a server would add a dependency and a
process for no benefit.

## Consequences

- Schema changes are applied in `Store` as idempotent `CREATE TABLE IF NOT
  EXISTS` / `ALTER TABLE` migrations; there is no migration framework.
- Queries are hand-written SQL and must be parameterised — never string
  concatenation with user input.
- `coach.db` is gitignored and must never be committed or exported with sample
  data.
