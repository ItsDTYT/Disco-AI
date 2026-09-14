FROM python:3.12-slim

WORKDIR /app

# Prevent python from writing pyc files and buffer stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy runtime code
COPY datastore.py .
COPY user_manager.py .
COPY media_utils.py .
COPY discord_mei.py .

CMD ["python", "discord_mei.py"]
