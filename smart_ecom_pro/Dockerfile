FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /data
COPY . .
ENV ECOM_DB=/data/shop.db PYTHONUNBUFFERED=1
EXPOSE 8000
# --preload: app (DB seed + model training) runs once before workers fork
CMD ["gunicorn", "--preload", "-w", "1", "--threads", "4", "-b", "0.0.0.0:8000", "--timeout", "120", "app:app"]
