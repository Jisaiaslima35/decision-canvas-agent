# Decision Canvas — Centro de Decisões / Live Meeting Rooms

Sala de reunião e decisão multi-usuário em tempo real, com chat com IA,
canvas executivo dinâmico, editor Monaco com execução via Piston,
vídeo Chitchatter / Daily.co, investigação web com captura de tela,
login com Google e criação de salas Daily.co.

## Arquitetura

- **Backend:** FastAPI em `server.py` — serve o frontend, o WebSocket das
  salas, a API de decisão/cálculo/investigação, o auth e a criação de salas.
- **Frontend:** um único `static/index.html` (Tailwind + Monaco via CDN).
  Não há build: o próprio backend serve a página.
- **Dados locais:** SQLite em `data/decision.db` (usuários, sessões e salas).
  O arquivo nunca entra no repositório.

## Setup local

```bash
cp .env.example .env   # preencha GOOGLE_* e DAILY_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload
```

Abra `http://localhost:8095`.

> Nota: não existe passo `npm install` / `npm run dev` neste projeto —
> o frontend não usa Node nem bundler; ele é servido pelo backend.

## Variáveis de ambiente (`.env`)

| Variável | Uso |
| --- | --- |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Login com Google |
| `GOOGLE_REDIRECT_URI` | Callback OAuth (local: `http://localhost:8095/api/auth/google/callback`) |
| `DAILY_API_KEY` | Criação de salas na API do Daily.co |
| `DAILY_DOMAIN` | Informativo (a URL da sala vem da resposta da API Daily) |
| `STT_API_KEY` | Chave da Groq para transcrição de áudio (endpoint `/api/v1/decision/transcribe`) |
| `NINEROUTER_URL` / `NINEROUTER_API_KEY` | Opcional: gateway de IA compatível com OpenAI |

Sem as chaves do Google, o login devolve 503 com mensagem clara e a sala
anônima por link continua funcionando. Sem a chave da Daily, a criação de
salas devolve 503 e o toggle de vídeo volta ao Chitchatter.
Sem gateway de IA, o chat usa o motor local de fallback.

Para o login funcionar, registre a redirect URI no Google Cloud Console,
no cliente OAuth web correspondente.

## Rotas principais

- `GET /` — a aplicação (sala via `?sala=ID`)
- `GET /api/v1/health` — status + gateway de IA
- `WS /ws/sala/{id}` — sincronização da sala em tempo real
- `POST /api/v1/decision/chat` — chat com IA + canvas executivo
- `POST /api/v1/decision/calc` — execução de código no Piston
- `POST /api/investigar` — dossiê de mercado + print da página
- `POST /api/daily/room` — provisiona sala Daily.co por nome
- `GET /api/auth/me`, `GET /api/auth/google/login`,
  `GET /api/auth/google/callback`, `POST /api/auth/logout`,
  `POST /api/auth/onboarding` — autenticação e cadastro
- `POST /api/rooms` — cria sala Daily.co (autenticado)

## Segurança

`.env`, `*.db`, backups (`.bak*`) e `__pycache__` nunca entram no
repositório (ver `.gitignore`). O `.env.example` contém apenas valores
fictícios.

## Google AI Studio / IDX

Importe este repositório, copie `.env.example` para `.env`, preencha as
chaves e rode o backend com o comando acima.
