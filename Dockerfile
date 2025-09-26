FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN --mount=type=cache,id=s/${RAILWAY_SERVICE_ID}-pip,target=/root/.cache/pip \
    pip install -r requirements.txt

COPY . .

ENV PYTHONPATH="/app/src:${PYTHONPATH:-}"

# Use the startup script for better error handling
CMD python start.py
