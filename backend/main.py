"""FastAPI application entry point for task 1."""

import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.routers import auth, exercise, graph, health, learning, qa
from common.config import settings
from common.errors import (
    AppException,
    app_exception_handler,
    database_exception_handler,
    generic_exception_handler,
    get_request_id,
    http_exception_handler,
    validation_exception_handler,
)


app = FastAPI(title="AI跨课程知识图谱学习系统")
access_logger = logging.getLogger("uvicorn.error")

allowed_origins = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(SQLAlchemyError, database_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = get_request_id(request)
    started = perf_counter()
    try:
        response = await call_next(request)
    except SQLAlchemyError as exc:
        response = await database_exception_handler(request, exc)
    except Exception as exc:
        # ServerErrorMiddleware otherwise re-raises after rendering a response,
        # causing Uvicorn to print the original traceback and SQL/body values.
        response = await generic_exception_handler(request, exc)
    response.headers["X-Request-ID"] = request_id
    # Route templates exclude user-supplied path parameters and query strings.
    route = getattr(request.scope.get("route"), "path", "unmatched")
    access_logger.info("request_id=%s method=%s route=%s status=%d seconds=%.3f", request_id, request.method, route, response.status_code, perf_counter() - started)
    return response


app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(graph.router, tags=["graph"])
app.include_router(exercise.router, tags=["exercise"])
app.include_router(learning.router, tags=["learning"])
app.include_router(qa.router, tags=["qa"])
