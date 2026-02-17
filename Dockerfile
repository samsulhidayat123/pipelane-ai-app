FROM python:3.10-slim
ENV PYTHONUNBUFFERED=1
# Install ffmpeg untuk proses merging video/audio
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Hugging Face butuh user dengan ID 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"

WORKDIR /app

# Copy dan install requirements
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy sisa project dan buat folder downloads
COPY --chown=user . .
RUN mkdir -p downloads && chmod 777 downloads

# Port default Hugging Face adalah 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "app:app", "--workers", "1", "--threads", "100", "--timeout", "120"]