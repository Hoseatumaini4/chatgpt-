FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_PATH=/data/gateway.db PORT=8000
VOLUME /data
CMD ["sh", "-c", "gunicorn wsgi:app --workers 1 --threads 8 --bind 0.0.0.0:${PORT}"]
