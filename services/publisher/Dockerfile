FROM python:3.11-slim

WORKDIR /app

COPY services/publisher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/shared/ ./shared/
COPY services/publisher/app/ ./app/

CMD ["python", "-m", "app.main"]
