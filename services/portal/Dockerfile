# Portal Flask service
# Serves the static frontend (plain HTML/CSS/JS, no build step) and
# proxies API requests to the FastAPI backend

FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Flask app
COPY flask_app.py .

# Copy the static frontend (single source of truth: app/*.html, *.css, *.js, pages/)
COPY app/ ./app/

# Expose port 80
EXPOSE 80

# Run with gunicorn for production
# Using 4 workers for better concurrency
CMD ["gunicorn", "--bind", "0.0.0.0:80", "--workers", "4", "--timeout", "120", "flask_app:app"]
