# Imagine de bază
FROM python:3.11-slim

# Nu bufferiza output-ul, să vedem logurile imediat
ENV PYTHONUNBUFFERED=1

# Directorul de lucru în container
WORKDIR /app

# Instalăm dependențele
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copiem restul codului
COPY . /app

# Porturi (doar informativ; docker-compose va face maparea)
EXPOSE 50051
EXPOSE 8000

# Comanda implicită o vom suprascrie din docker-compose
CMD ["bash"]