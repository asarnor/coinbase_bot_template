# Dockerfile for Coinbase Trading Bot (Python version)
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY *.py ./

# Set Python to run unbuffered (better for logs)
ENV PYTHONUNBUFFERED=1

# Default command (can be overridden)
# Using multi-symbol bot to trade ETH and BTC simultaneously
# For production: use --execute flag
# For testing: use --sandbox or --test flags
CMD ["python", "main_multi_symbol.py", "--execute"]

