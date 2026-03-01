FROM python:3.11-slim

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY app/requirements.txt ./app/
RUN pip install --no-cache-dir -r app/requirements.txt

# Copy application code
COPY . .

# Expose port (Railway overrides this)
EXPOSE 8000

# Run the application - Use exec form with shell for variable expansion and signal handling
CMD ["sh", "-c", "exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 120"]
