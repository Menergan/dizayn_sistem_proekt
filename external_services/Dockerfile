FROM python:3.13-slim
WORKDIR /service
RUN pip install --no-cache-dir 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'httpx>=0.27,<1'
COPY app /service/app
COPY external_services /service/external_services
EXPOSE 3629
CMD ["uvicorn", "external_services.main:app", "--host", "0.0.0.0", "--port", "3629"]
