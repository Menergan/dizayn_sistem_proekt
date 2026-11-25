FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx 'sqlalchemy[asyncio]' alembic redis asyncpg 'psycopg[binary]' prometheus-client
COPY app /app/app
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
CMD ["uvicorn", "app.lifecycle.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
