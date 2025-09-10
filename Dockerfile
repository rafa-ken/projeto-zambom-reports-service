# Usa uma imagem base leve do Python
FROM python:3.11-slim

# Define diretório de trabalho dentro do container
WORKDIR /app

# Copia dependências para instalar
COPY requirements.txt .

# Instala dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código da aplicação
COPY . .

# Expõe a porta usada pelo Flask
EXPOSE 5001

# Comando para iniciar a aplicação
CMD ["python", "app.py"]