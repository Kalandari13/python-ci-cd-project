FROM python:3.12-slim
LABEL org.opencontainers.image.source="https://github.com/Kalandari13/python-ci-cd-project"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt
COPY app.py .
COPY database.py social.py security.py gunicorn.conf.py .
COPY templates/ templates/
COPY static/ static/
USER 10001:10001
EXPOSE 5000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
