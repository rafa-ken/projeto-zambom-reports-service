# Etapa de execução
FROM python:3.11-slim


# Definir diretório de trabalho
WORKDIR /app

# Copiar arquivos do projeto
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY . .

# Expor a porta do Flask (será definida pela variável PORT)
EXPOSE 5001

# Rodar o Flask com Gunicorn (usa variável de ambiente PORT)
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-5001} app:app"]