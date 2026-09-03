from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.services.capabilities import cache_size_bytes, probe
from config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/system", response_class=HTMLResponse)
def system_page(request: Request, neu: int = 0):
    return templates.TemplateResponse(request, "system.html",
        {
            "request": request,
            "capabilities": probe(force=bool(neu)),
            "cache_mb": cache_size_bytes() / 1e6,
        },
    )


@router.post("/system/cache/leeren")
def cache_leeren():
    """Der Zwischenspeicher enthält Seitenbilder aus Patientenakten."""
    import shutil

    from begutachtung.cache import CACHE_ROOT

    shutil.rmtree(CACHE_ROOT, ignore_errors=True)
    return RedirectResponse(url="/system", status_code=303)
