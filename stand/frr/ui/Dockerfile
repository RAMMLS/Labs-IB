FROM python:3.14-alpine

RUN apk add --no-cache docker-cli

WORKDIR /app
COPY ui/server.py /app/server.py
COPY ui/engine.py /app/engine.py
COPY ui/static /app/static
COPY nodes /app/node-images

EXPOSE 8080
CMD ["python", "/app/server.py"]
