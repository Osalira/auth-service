# Use an official Python runtime as a base image
# Using slim version to reduce image size while maintaining compatibility
FROM python:3.10-slim

# Set environment variables
# Prevents Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE 1
# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create directory for logs
RUN mkdir -p /app/logs

# Create a non-root user
RUN adduser --disabled-password --gecos '' appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose the port the app runs on
EXPOSE 5000

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

# Command to run the Flask app
# Using gunicorn as production server
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers ${GUNICORN_WORKERS:-4} --threads ${GUNICORN_THREADS:-8} --worker-class gthread --worker-connections 1000 --timeout ${GUNICORN_TIMEOUT:-600} --keep-alive ${GUNICORN_KEEPALIVE:-5} --max-requests ${GUNICORN_MAX_REQUESTS:-10000} --max-requests-jitter ${GUNICORN_MAX_REQUESTS_JITTER:-1000} --log-level info app:app"] 