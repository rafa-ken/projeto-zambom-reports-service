# Etapa de execução
FROM python:3.11-slim


# Definir diretório de trabalho
WORKDIR /app


# Instalar dependências do sistema necessárias para mysqlclient
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivos do projeto
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .

# Expor a porta do Flask
EXPOSE 5002

# Rodar o Flask com Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:5002", "app:app"]