FROM python:3.9-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc
RUN pip install debugpy

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The CMD is now in docker-compose.yml