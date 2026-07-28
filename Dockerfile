FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN addgroup --system voice && adduser --system --ingroup voice voice
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .
USER voice
CMD ["python", "-m", "app.main", "start"]

