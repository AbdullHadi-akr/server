# Das Portal kommt ohne Fremdbibliotheken aus - reine Python-Standardbibliothek.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5021 \
    OLLAMA_URL=http://AZEU-DEW-DEVGPU-02:5020 \
    OLLAMA_CONTAINER=ollama

WORKDIR /opt/portal
COPY app/ ./app/

# Als unprivilegierter Nutzer laufen lassen.
RUN useradd --system --create-home --uid 10001 portal
USER portal

EXPOSE 5021

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','5021')+'/healthz',timeout=3)"

CMD ["python", "-m", "app.server"]
