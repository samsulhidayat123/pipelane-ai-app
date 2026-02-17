FROM python:3.9
WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Membuat folder downloads agar fitur PDF tidak error
RUN mkdir -p downloads && chmod 777 downloads
CMD ["python", "app.py"]