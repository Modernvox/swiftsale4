# Use Python 3.11 base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy source code
COPY . /app

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (Render auto-detects via PORT env)
EXPOSE 10000

# Start the app
CMD ["python", "flask_server_qt.py"]
