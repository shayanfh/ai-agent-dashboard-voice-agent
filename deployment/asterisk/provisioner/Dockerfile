FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd --system --uid 10001 provisioner \
    && mkdir -p /var/lib/asterisk-provisioner /etc/asterisk/ai-agent-generated \
    && chown -R provisioner:provisioner /var/lib/asterisk-provisioner /etc/asterisk/ai-agent-generated \
    && chmod -R a+rX /app
USER provisioner

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9443"]
