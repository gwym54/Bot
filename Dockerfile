FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the bot code
COPY bot.py .

# Data directory for persistent volume (Railway volume should mount here)
RUN mkdir -p /app/data

# Default paths for Railway / Docker
ENV PYTHONUNBUFFERED=1 \
    DB_FILE=/app/data/db.json

# Single process, long-polling
CMD ["python", "bot.py"]
