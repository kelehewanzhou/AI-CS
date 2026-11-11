FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS builder
WORKDIR /build
RUN python -m venv /opt/venv
COPY backend/requirements.lock .
RUN /opt/venv/bin/python -m pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app/backend
COPY backend/ /app/backend/
COPY database/ /app/database/
RUN useradd --create-home --uid 1000 appuser && mkdir -p /app/backend/tmp && chown appuser:appuser /app/backend/tmp
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
