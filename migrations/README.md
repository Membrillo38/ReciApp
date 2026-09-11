# ReciApp PostgreSQL Migrations

Apply the bootstrap schema to a fresh self-hosted PostgreSQL database:

```sh
psql "$DATABASE_URL" -f migrations/001_init.sql
```

Apply in order:

```sh
psql "$DATABASE_URL" -f migrations/001_init.sql
psql "$DATABASE_URL" -f migrations/002_row_level_security.sql
psql "$DATABASE_URL" -f migrations/003_free_yearly_limit.sql
```

`001_init.sql` is the bootstrap schema. `002_row_level_security.sql` forces RLS on app tables. The API sets `app.actor` and `app.user_id` per transaction.
