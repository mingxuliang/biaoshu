FROM mcr.microsoft.com/playwright/python:v1.49.1-noble

WORKDIR /opt/browser

COPY writer_browser/server.py ./server.py

RUN pip install --no-cache-dir fastapi uvicorn pydantic

EXPOSE 8010

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8010"]
