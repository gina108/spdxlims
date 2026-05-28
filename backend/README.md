# SPDX LIMS Backend

FastAPI + PostgreSQL scaffold with:
- JWT authentication + role-based access
- Providers and provider pricing
- Inventory items/lots/transactions + low-stock/expiry alerts
- Billing drafts/invoices (manual issue)
- Manual month-end close workflow + checklist + snapshots
- Static admin UI

## Quick start

1. `cd C:\SPDXLIMS\backend`
2. `docker compose -f docker-compose.backend.yml up -d`
3. `python -m venv .venv`
4. `.venv\\Scripts\\activate`
5. `pip install -r requirements.txt`
6. `Copy-Item .env.example .env`
7. `alembic upgrade head`
8. `python scripts\\seed.py`
9. `uvicorn app.main:app --reload --port 8001`

## Import existing desktop data

After the backend schema is migrated, you can import the current local desktop SQLite data:

1. `cd C:\SPDXLIMS\backend`
2. `alembic upgrade head`
3. `python scripts\\import_sqlite.py --sqlite ..\\data\\spdxlims.db`

What the importer brings over:
- lab profile and shared report branding assets
- patients
- doctors and clients as backend providers
- tests and reference ranges
- panels and panel items
- orders, results, and saved report snapshots

The importer is upsert-oriented for master data and replaces matching orders by `order_number`, so it is safe to rerun during setup if you need to refresh the initial migration.

## Access

- Swagger: `http://localhost:8001/docs`
- Admin UI: `http://localhost:8001/admin`
- Development seed admin credentials: `admin@spdxlims.local / Admin#12345`

## Notes

- Change JWT secret and seed passwords before production.
- Set `CORS_ORIGINS` to the exact workstation/admin UI origins allowed to call the API.
- Billing is intentionally manual (draft -> issue -> paid); no auto month-end posting.

## Production safety

When `APP_ENV` is `prod` or `production`, the backend refuses to start with the default JWT secret. Set `JWT_SECRET_KEY` to a strong random value before deployment.

Use `backend\.env.production.example` as the production environment template and `docs\PRODUCTION_DEPLOYMENT.md` as the deployment runbook.

## Integration tests

The normal test suite skips live database integration tests. To run the API happy-path test against a disposable PostgreSQL database:

```powershell
$env:RUN_BACKEND_INTEGRATION = "1"
$env:TEST_DATABASE_URL = "postgresql+psycopg://lims_user:lims_password@localhost:5432/lims_test_db"
python -m pytest backend/tests/test_api_integration.py
```

The test drops and recreates all tables in `TEST_DATABASE_URL`, so never point it at production or shared development data.
