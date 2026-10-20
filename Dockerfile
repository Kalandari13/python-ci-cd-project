FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Kalandari13/python-ci-cd-project"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY templates/ templates/
COPY static/ static/
EXPOSE 5000
CMD ["python", "app.py"]
