FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH="/app/src:${PYTHONPATH:-}"

# Use the startup script for better error handling
CMD python start.py
