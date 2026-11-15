"""Main app."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.middleware.cors import CORSMiddleware

from api.views import admin, clusters, faces, files, geo, health, persons
from common.exceptions import (
    BaseApiException,
    handle_exception_response,
    handle_validation_error_handler,
)
from common.settings import settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """При старте проверяем SCAN_ROOTS/FACES_DIR; при нарушении — завершаемся."""
    settings.validate_paths()
    yield


app = FastAPI(
    lifespan=lifespan, docs_url=settings.SWAGGER_URL, redoc_url=settings.REDOC_URL
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.add_exception_handler(BaseApiException, handle_exception_response)
app.add_exception_handler(RequestValidationError, handle_validation_error_handler)

app.include_router(health.router)
app.include_router(geo.router)
app.include_router(files.router)
app.include_router(faces.router)
app.include_router(clusters.router)
app.include_router(persons.router)
app.include_router(admin.router)


@app.get('/')
async def root() -> dict:
    return {'service': 's_media_analyzer', 'version': settings.APP_VERSION}


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host='localhost', port=8000)
