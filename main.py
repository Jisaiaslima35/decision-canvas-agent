# Ponto de entrada alternativo: `uvicorn main:app --reload`
# (o serviço em produção usa `uvicorn server:app`).
from server import app

__all__ = ["app"]
