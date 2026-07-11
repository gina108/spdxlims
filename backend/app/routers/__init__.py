from fastapi import APIRouter

from app.routers import auth, billing, inventory, lab_profile, month_close, operations, orders, outsourced, panels, patients, providers, reports, results, statistics, stock, tests

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(patients.router, prefix="/patients", tags=["patients"])
api_router.include_router(tests.router, prefix="/tests", tags=["tests"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(panels.router, prefix="/panels", tags=["panels"])
api_router.include_router(results.router, prefix="/results", tags=["results"])
api_router.include_router(lab_profile.router, prefix="/lab-profile", tags=["lab-profile"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(month_close.router, prefix="/month-close", tags=["month-close"])
api_router.include_router(operations.router, prefix="/operations", tags=["operations"])
api_router.include_router(outsourced.router, prefix="/outsourced", tags=["outsourced"])
api_router.include_router(statistics.router, prefix="/statistics", tags=["statistics"])
api_router.include_router(stock.router, prefix="/stock", tags=["stock"])


