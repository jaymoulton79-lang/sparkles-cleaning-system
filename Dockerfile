FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app
COPY server.py automation.py ./
COPY public ./public
RUN mkdir -p /app/data/uploads && useradd --create-home --uid 10001 sparkles && chown -R sparkles:sparkles /app

USER sparkles
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)"
CMD ["python", "server.py"]
