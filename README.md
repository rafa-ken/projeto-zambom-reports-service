# 📊 Reports Service

Serviço responsável por **gerar relatórios** a partir dos dados dos outros serviços (Tasks e Notes).

## 🚀 Funcionalidades
- Consultar `tasks-service` e `notes-service`
- Gerar relatórios como:
  - Quantidade de tarefas concluídas
  - Total de anotações criadas

## 🏗 Arquitetura
- Python 3.10
- Flask + Requests (para consumir APIs)
- Testes com Pytest (mockando chamadas externas)
- Autenticação OAuth2 via Auth0 (simulada nesta fase)
- Docker + GitHub Actions

## Como rodar localmente
```bash
pip install -r requirements.txt
python app.py
```

## Como rodar com Docker
```bash
docker build -t your-dockerhub-username/reports-service .
docker run -p 8081:5001 your-dockerhub-username/reports-service
```

## Testes
```bash
pytest -v
```





