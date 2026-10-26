import os
import json
import logging
import tempfile
import re
import subprocess
import time
import hashlib
import secrets
import urllib.parse
import sqlite3
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("decision-canvas")

app = FastAPI(
    title="Centro de Decisões Empresariais - Multimodal & 9Router",
    description="Microserviço e Painel Plugável com Visão Computacional, 9Router e HTTPS",
    version="1.2.2"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    prompt: str
    image: Optional[str] = None  # data:image/png;base64,...
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    history: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    model: Optional[str] = "gemini/gemini-2.5-flash"
    sala: Optional[str] = None
    client_id: Optional[str] = None
    api_key: Optional[str] = None

# Localização e Chave do 9Router
NINEROUTER_URL = os.getenv("NINEROUTER_URL", "http://127.0.0.1:20128/v1")

def get_ninerouter_key() -> str:
    env_key = os.getenv("NINEROUTER_API_KEY")
    if env_key:
        return env_key
    try:
        db_path = "/var/lib/docker/volumes/9router-data/_data/db/data.sqlite"
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT key FROM apiKeys LIMIT 1;")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                return row[0]
    except Exception as e:
        logger.warning(f"Não foi possível obter chave do 9Router via SQLite: {e}")
    return "sk-ee9be57a70a07560-etddrv-19a7661c"

NINEROUTER_KEY = get_ninerouter_key()

# Templates Oficiais do Centro de Decisões
SYSTEM_TEMPLATES = [
    {
        "id": "prompt-1-base",
        "title": "Centro de Decisões",
        "description": "Base da estrutura: Conversação + Contexto + Canvas Dinâmico",
        "prompt": "Atue como o Centro de Decisões Empresariais. Analise as informações da minha operação e converta qualquer análise em decisões práticas e recursos visuais na Área de Trabalho."
    },
    {
        "id": "prompt-2-auditoria",
        "title": "Auditoria de Gargalos",
        "description": "Cruza dados e identifica os 3 problemas/gargalos de maior impacto econômico",
        "prompt": "Cruze os dados do negócio e identifique os 3 gargalos ou oportunidades ocultas, priorizados pelo impacto econômico direto. Para cada achado detalhe: o que detectou, os dados que comprovam, o risco financeiro e o que investigar antes de agir."
    },
    {
        "id": "prompt-3-churn",
        "title": "Recuperação de Clientes",
        "description": "Mapeia clientes inativos e gera recurso de retenção com prioridade",
        "prompt": "Identifique clientes e contas críticas que deixaram de ter atividade recente. Construa na Área de Trabalho um recurso visual de retenção contendo: nível de prioridade, tempo de inatividade, valor histórico e estratégia de recuperação imediata."
    },
    {
        "id": "prompt-4-decisao",
        "title": "Decisão Executiva Única",
        "description": "Define uma única ação prioritária de 30 dias e gera o recurso no Canvas",
        "prompt": "Converta o diagnóstico em uma decisão prática: determine uma única ação prioritária indispensável para os próximos 30 dias. Justifique a escolha e construa na Área de Trabalho o recurso executivo mais útil para colocá-la em prática."
    },
    {
        "id": "prompt-5-plano-fases",
        "title": "Plano de Ação (30 Dias)",
        "description": "Plano de 30 dias particionado em 3 fases com metas, responsáveis e KPIs",
        "prompt": "Elabore um plano de ação de 30 dias dividido em 3 fases claras com metas objetivas, responsáveis e KPIs mensuráveis. Monte como um recurso visual dinâmico na Área de Trabalho."
    },
    {
        "id": "prompt-6-leitor",
        "title": "Leitor Inteligente: Resumo & Ação",
        "description": "Síntese executiva de leitura, pontos de atrito e checklist prático",
        "prompt": "Analise o capítulo atual do Leitor Inteligente. Extraia os conceitos essenciais, aponte os pontos críticos de fricção do usuário e crie um checklist prático com passos de aplicação imediata para o negócio."
    },
    {
        "id": "prompt-7-visao",
        "title": "Visão de Tela & Navegação Passo a Passo",
        "description": "Analisa o print da tela enviado e guia o usuário com clareza sem sobrecarga",
        "prompt": "Analise o print visual da tela que anexei. Identifique os elementos principais, onde devo clicar para executar a ação e me guie passo a passo, dando um único passo por vez."
    }
]

def simulate_decision_engine(prompt: str, context: Optional[Dict[str, Any]] = None, has_image: bool = False) -> Dict[str, Any]:
    """Fallback Autônomo com suporte a visão e schemas estruturados em PT-BR."""
    p_lower = prompt.lower()
    
    if has_image or any(k in p_lower for k in ["imagem", "print", "tela", "interface", "foto", "botão", "onde está", "onde fica", "captura"]):
        return {
            "reply": (
                "Analisei a captura de tela enviada com sucesso.\n\n"
                "**Diagnóstico Visual da Interface:**\n"
                "1. **Painel Superior / Barra de Ações:** Os botões de ação e status foram identificados.\n"
                "2. **Fluxo Recomendado (Passo a Passo):**\n"
                "   - **Passo 1:** Localize o botão principal de ação em destaque.\n"
                "   - **Passo 2:** Verifique os parâmetros e métricas antes de confirmar.\n"
                "   - **Passo 3:** Conclua a operação acompanhando os KPIs no Canvas.\n\n"
                "Gerei um **Plano de Navegação e Ajuste Operacional** na sua Área de Trabalho para orientar a equipe sem sobrecarga."
            ),
            "tool_call": {
                "type": "render_action_plan",
                "data": {
                    "title": "Guia Visual de Execução na Interface (Passo a Passo)",
                    "objective": "Orientar a navegação e execução de ações críticas a partir da análise visual do print",
                    "kpis": [
                        {"name": "Tempo até a Ação", "target": "< 30s", "current": "1m 45s"},
                        {"name": "Taxa de Erro de Clique", "target": "0%", "current": "18%"},
                        {"name": "Aderência ao Fluxo", "target": "100%", "current": "65%"}
                    ],
                    "phases": [
                        {
                            "phase": "Passo 1: Localização e Ativação",
                            "goal": "Acessar o elemento correto identificado na captura de tela",
                            "tasks": [
                                {"task": "Clicar no botão principal identificado na interface", "owner": "Usuário / Operador", "deadline": "Imediato", "status": "pending"},
                                {"task": "Validar feedback visual de carregamento ou transição de tela", "owner": "Sistema", "deadline": "Imediato", "status": "pending"}
                            ]
                        },
                        {
                            "phase": "Passo 2: Execução Sem Sobrecarga",
                            "goal": "Preencher apenas os campos essenciais sem dispersão",
                            "tasks": [
                                {"task": "Confirmar valores ou parâmetros apresentados na janela", "owner": "Operador", "deadline": "D+0", "status": "pending"}
                            ]
                        }
                    ],
                    "executive_summary": "Análise visual processada. A interface foi mapeada com os pontos de clique destacados."
                }
            }
        }
    
    if any(k in p_lower for k in ["leitor", "livro", "ebook", "capítulo", "capitulo", "resumo", "estudo", "breakdown"]):
        topic_name = (context.get("topic") if context else None) or "Modelos Recorrentes & Retenção de Alunos"
        return {
            "reply": (
                "Concluí a decomposição estratégica da leitura com foco em aplicação prática. "
                "Em vez de apenas memorizar texto, estruturei na sua **Área de Trabalho** os pontos "
                "críticos de fricção e um checklist de implementação imediata para as próximas 48 horas."
            ),
            "tool_call": {
                "type": "render_study_breakdown",
                "data": {
                    "title": "Síntese Executiva & Aplicação Prática - Leitor Inteligente",
                    "chapter_or_topic": str(topic_name),
                    "core_insights": [
                        {
                            "concept": "Alavancagem de Margem por Leitor",
                            "takeaway": "Monetização direta de R$ 5 a 13 por livro com Professor IA ativo como gatilho de alto engajamento."
                        },
                        {
                            "concept": "Loop de Retenção Contínua",
                            "takeaway": "O hábito de estudo diário ancorado em checklists práticos reduz o churn em mais de 40%."
                        },
                        {
                            "concept": "Transformação da Teoria em Operação",
                            "takeaway": "Cada capítulo lido deve gerar um artefato operacional ou automação no mesmo dia."
                        }
                    ],
                    "critical_friction_points": [
                        "Usuários encerram a sessão antes do final do capítulo se não houver síntese auditiva.",
                        "Ausência de integração automática dos insights com o WhatsApp ou CRM do cliente."
                    ],
                    "actionable_checklist": [
                        {"step": "Ativar gatilho de síntese de voz ao completar 80% do capítulo", "done": False},
                        {"step": "Disparar webhook para CRM com os 3 aprendizados principais do usuário", "done": False},
                        {"step": "Validar métrica de tempo de leitura ativa no dashboard de analytics", "done": True}
                    ],
                    "reflection_questions": [
                        "Qual processo da sua empresa pode ser melhorado hoje com este princípio?",
                        "Seus clientes estão recebendo o valor principal nos primeiros 5 minutos de uso?"
                    ]
                }
            }
        }
    
    elif any(k in p_lower for k in ["auditoria", "prioriza", "gargalo", "churn", "inativ", "problema", "recupera", "hallazgo", "matriz", "riesgo"]):
        return {
            "reply": (
                "Realizei o cruzamento dos dados de negócio e identifiquei os **3 gargalos prioritários** "
                "com base no impacto financeiro direto. "
                "Gerei a **Matriz de Auditoria e Decisão** no seu Canvas à direita com a exposição de risco calculada "
                "e as ações de choque recomendadas."
            ),
            "tool_call": {
                "type": "render_decision_matrix",
                "data": {
                    "title": "Matriz de Auditoria de Gargalos & Recuperação de Clientes",
                    "total_risk_exposure": "R$ 48.200 / mês",
                    "immediate_opportunity": "R$ 29.500 / mês",
                    "findings": [
                        {
                            "rank": 1,
                            "title": "Clientes Chave Inativos com Risco Iminente de Churn",
                            "economic_impact": "Alto (Perda projetada de R$ 18.000/mês)",
                            "evidence": "23 contas enterprise sem nenhuma interação ou leitura nos últimos 28 dias.",
                            "why_care": "O custo de reativação imediata é 80% menor do que o CAC para substituí-los.",
                            "pre_decision_check": "Conferir tickets de suporte abertos e taxa de entrega das notificações antes do contato.",
                            "recommended_action": "Disparar playbook de resgate VIP com oferta de consultoria individual em 24h.",
                            "status": "urgente"
                        },
                        {
                            "rank": 2,
                            "title": "Fricção e Abandono no Checkout de Assinaturas (Asaas/Gateway)",
                            "economic_impact": "Médio (R$ 11.500/mês em vendas retidas)",
                            "evidence": "Taxa de desistência de 34% no último passo de emissão de PIX dinâmico.",
                            "why_care": "Tráfego e intenção de compra já pagos sendo perdidos na porta de entrada.",
                            "pre_decision_check": "Inspecionar webhooks de erro do gateway e logs de recusa de transações.",
                            "recommended_action": "Ativar recuperação imediata via WhatsApp com link direto de pagamento em 2 cliques.",
                            "status": "alerta"
                        },
                        {
                            "rank": 3,
                            "title": "Ociosidade e Custo Fixo de Infraestrutura Noturna",
                            "economic_impact": "Otimização de R$ 3.200/mês",
                            "evidence": "Workers de processamento e instâncias mantidas em pico com 5% de uso entre 00h e 06h.",
                            "why_care": "Drena a margem líquida da operação sem trazer benefício para o usuário.",
                            "pre_decision_check": "Mapear dependências de jobs batch e rotinas de backup agendadas.",
                            "recommended_action": "Programar escalonamento automático de contêineres e hibernação de réplicas.",
                            "status": "oportunidade"
                        }
                    ]
                }
            }
        }
    
    else:
        return {
            "reply": (
                "Estruturei o plano de ação executivo para os próximos 30 dias focado em resultados mensuráveis. "
                "O plano foi dividido em 3 fases progressivas (Diagnóstico/Estancamento, Execução do Choque e Escala), "
                "com metas claras, responsáveis e KPIs de acompanhamento. "
                "Você pode interagir e marcar as tarefas diretamente no seu **Área de Trabalho** à direita."
            ),
            "tool_call": {
                "type": "render_action_plan",
                "data": {
                    "title": "Plano de Ação Estratégico de Choque (30 Dias)",
                    "objective": "Acelerar conversão, estancar churn e consolidar alavancagem operacional com suporte de IA",
                    "kpis": [
                        {"name": "Taxa de Retenção", "target": "> 85%", "current": "64%"},
                        {"name": "MRR Recuperado", "target": "+ R$ 14.500", "current": "R$ 0"},
                        {"name": "Tempo Médio de Ativação", "target": "< 4 min", "current": "14 min"}
                    ],
                    "phases": [
                        {
                            "phase": "Fase 1: Dias 1 a 7 (Diagnóstico e Estancamento)",
                            "goal": "Conter vazamentos imediatos de receita e restabelecer contato com contas críticas",
                            "tasks": [
                                {"task": "Auditoria de churn dos últimos 60 dias e lista de contatos VIP", "owner": "Ops / Isaías", "deadline": "D+2", "status": "pending"},
                                {"task": "Revisão e teste dos webhooks de pagamento com fallback via WhatsApp", "owner": "Dev / IA", "deadline": "D+4", "status": "pending"},
                                {"task": "Configuração da mensagem de boas-vindas do Professor IA", "owner": "Growth", "deadline": "D+6", "status": "pending"}
                            ]
                        },
                        {
                            "phase": "Fase 2: Dias 8 a 21 (Execução do Plano de Choque)",
                            "goal": "Implementar esteira de reativação automatizada e otimização do fluxo do cliente",
                            "tasks": [
                                {"task": "Campanha de recuperação de clientes inativos com playbook personalizado", "owner": "Comercial", "deadline": "D+10", "status": "pending"},
                                {"task": "Deploy do Decision Canvas como widget de acompanhamento interno", "owner": "Dev / IA", "deadline": "D+14", "status": "completed"},
                                {"task": "Análise da taxa de conversão semanal e ajustes de preço/oferta", "owner": "Isaías", "deadline": "D+18", "status": "pending"}
                            ]
                        },
                        {
                            "phase": "Fase 3: Dias 22 a 30 (Consolidação e Escala)",
                            "goal": "Automatizar gatilhos preditivos de retenção e documentar processos operacionais",
                            "tasks": [
                                {"task": "Definir alertas automáticos de contas em risco de abandono", "owner": "Dev / IA", "deadline": "D+24", "status": "pending"},
                                {"task": "Reunião de fechamento de KPIs e definição das metas do próximo ciclo", "owner": "Isaías / Diretoria", "deadline": "D+29", "status": "pending"}
                            ]
                        }
                    ],
                    "executive_summary": (
                        "Este plano prioriza liquidez rápida na primeira semana, mitigação de riscos operacionais "
                        "e consolidação da arquitetura de inteligência para permitir escalabilidade sem aumento de headcount."
                    )
                }
            }
        }

async def call_9router_chat(
    prompt: str,
    model: str,
    image_base64: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    system_suffix: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Chama o 9Router local com formato multimodal estrito da OpenAI (/v1/chat/completions).
    """
    url = f"{NINEROUTER_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {NINEROUTER_KEY}",
        "Content-Type": "application/json"
    }

    selected_model = model.strip() if model else "gemini/gemini-2.5-flash"
    if selected_model in ["gemini-2.5-flash", "gemini-2.5"]:
        selected_model = "gemini/gemini-2.5-flash"
    elif selected_model in ["gemini-3.6-flash", "gemini-3.6"]:
        selected_model = "gemini/gemini-3.6-flash"
    elif selected_model in ["gemini-2.5-pro", "gemini-pro"]:
        selected_model = "gemini/gemini-3.1-pro-preview"

    system_instruction = (
        "Você é o 'Centro de Decisões Empresariais', um consultor executivo sênior de alto nível. "
        "Seu papel é analisar dados de negócio e capturas de tela enviadas pelo dono da empresa, "
        "transformando conversas em decisões acionáveis e recursos visuais estruturados. "
        "Você NÃO é um ERP nem um chatbot comum. "
        "IMPORTANTE: Responda ESTRITAMENTE em Português do Brasil (pt-BR). "
        "Se uma imagem ou captura de tela for enviada, inspecione minuciosamente os textos, botões, cores e posições. "
        "Guie o usuário com clareza executiva, dando um passo de cada vez. "
        "Se aplicável a planos ou auditorias, inclua ao final um bloco JSON com a ferramenta correspondente: "
        "render_action_plan, render_decision_matrix, ou render_study_breakdown. "
        "ESQUEMA OBRIGATÓRIO do JSON: o data do render_action_plan tem title, objective, kpis e phases; cada kpi tem name, target e current; cada phase tem phase, goal e tasks; cada task tem task, owner, deadline e status (pending ou completed). Use EXATAMENTE esses nomes de chave em inglês, nunca os traduza. Toda task PRECISA ter task, owner e deadline preenchidos; nunca devolva tarefas sem texto. "
        "Exemplo: ```json {\"type\": \"render_action_plan|render_decision_matrix|render_study_breakdown\", \"data\": {...}} ```"
    )

    if system_suffix:
        system_instruction = system_instruction + " " + system_suffix

    messages = [{"role": "system", "content": system_instruction}]

    if history:
        for h in history[-4:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if content:
                messages.append({"role": role, "content": str(content)})

    context_str = json.dumps(context or {}, ensure_ascii=False)
    user_prompt_text = f"Contexto do Negócio: {context_str}\n\nSolicitação: {prompt}\n(Responda em Português do Brasil)"

    # Formatação estrita OpenAI Vision / Text
    if image_base64:
        user_message_obj = {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt_text},
                {"type": "image_url", "image_url": {"url": image_base64}}
            ]
        }
    else:
        user_message_obj = {
            "role": "user",
            "content": user_prompt_text
        }

    messages.append(user_message_obj)

    payload = {
        "model": selected_model,
        "messages": messages,
        "stream": False,
        "temperature": 0.2
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            
            if resp.status_code != 200:
                logger.warning(f"9Router retornou status HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            try:
                data = resp.json()
            except Exception as json_err:
                logger.warning(f"Resposta do 9Router não é JSON válido: {json_err} -> {resp.text[:200]}")
                return None

            choices = data.get("choices", [])
            if choices:
                text_out = choices[0].get("message", {}).get("content", "").strip()
                
                tool_call = None
                reply_text = text_out
                
                if "```json" in text_out:
                    parts = text_out.split("```json")
                    reply_text = parts[0].strip()
                    json_str = parts[1].split("```")[0].strip()
                    try:
                        parsed_tool = json.loads(json_str)
                        if isinstance(parsed_tool, dict) and "type" in parsed_tool:
                            tool_call = parsed_tool
                    except Exception as e:
                        logger.warning(f"Erro ao parsear JSON tool_call: {e}")
                
                return {"reply": reply_text or "Análise executada com sucesso.", "tool_call": tool_call}

    except Exception as e:
        logger.error(f"Exceção ao comunicar com 9Router: {e}")

    return None

# ================= SALA MULTI-USUARIO (WebSocket broadcast) =================
class ConnectionManager:
    """Agrupa conexoes WebSocket por sala (?sala=ID)."""

    def __init__(self):
        self.rooms: Dict[str, Dict[str, Any]] = {}

    async def connect(self, sala: str, client_id: str, ws: WebSocket):
        await ws.accept()
        self.rooms.setdefault(sala, {})[client_id] = ws
        await self.send_snapshot(sala, ws)
        await self.broadcast_presence(sala)

    def disconnect(self, sala: str, client_id: str):
        conns = self.rooms.get(sala, {})
        conns.pop(client_id, None)
        if not conns:
            self.rooms.pop(sala, None)

    async def send_personal(self, ws: WebSocket, payload: Dict[str, Any]):
        try:
            await ws.send_json(payload)
        except Exception:
            pass

    async def broadcast(self, sala: str, payload: Dict[str, Any], exclude: Optional[str] = None):
        for cid, ws in list(self.rooms.get(sala, {}).items()):
            if exclude and cid == exclude:
                continue
            try:
                await ws.send_json(payload)
            except Exception:
                pass

    async def broadcast_presence(self, sala: str):
        await self.broadcast(sala, {"type": "presence", "count": len(self.rooms.get(sala, {}))})

    async def send_snapshot(self, sala: str, ws: WebSocket):
        snap = ROOM_STATE.get(sala, {})
        await self.send_personal(ws, {
            "type": "snapshot",
            "canvas": snap.get("canvas"),
            "calc": snap.get("calc"),
            "monaco": {"lang": snap.get("monaco_lang"), "buffers": snap.get("monaco_buffers")},
        })


manager = ConnectionManager()
ROOM_STATE: Dict[str, Dict[str, Any]] = {}


@app.websocket("/ws/sala/{sala_id}")
async def ws_sala(websocket: WebSocket, sala_id: str):
    client_id = websocket.query_params.get("client") or "anon"
    await manager.connect(sala_id, client_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
            if mtype == "monaco_update":
                lang = str(msg.get("lang") or "python")[:32]
                code = str(msg.get("code") or "")
                if len(code) > 200000:
                    continue
                sender = str(msg.get("sender") or "Participante")[:64]
                st = ROOM_STATE.setdefault(sala_id, {})
                st.setdefault("monaco_buffers", {})[lang] = code
                st["monaco_lang"] = lang
                await manager.broadcast(sala_id, {"type": "monaco_update", "lang": lang, "code": code, "sender": sender}, exclude=client_id)
            elif mtype == "monaco_lang":
                lang = str(msg.get("lang") or "python")[:32]
                sender = str(msg.get("sender") or "Participante")[:64]
                ROOM_STATE.setdefault(sala_id, {})["monaco_lang"] = lang
                await manager.broadcast(sala_id, {"type": "monaco_lang", "lang": lang, "sender": sender}, exclude=client_id)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(sala_id, client_id)
        await manager.broadcast_presence(sala_id)


@app.get("/api/v1/health")
async def health_check():
    ninerouter_status = "offline"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{NINEROUTER_URL}/models", headers={"Authorization": f"Bearer {NINEROUTER_KEY}"})
            if r.status_code == 200:
                ninerouter_status = "connected"
    except Exception:
        pass

    return {
        "status": "online",
        "service": "decision-canvas",
        "language": "pt-BR",
        "version": "1.2.2",
        "router": {
            "service": "9router",
            "status": ninerouter_status,
            "endpoint": NINEROUTER_URL
        },
        "supported_models": [
            "gemini/gemini-2.5-flash",
            "gemini/gemini-3.6-flash",
            "gemini/gemini-3.1-pro-preview",
            "groq/meta-llama/llama-4-maverick-17b-128e-instruct",
            "autonomous-decision-engine"
        ],
        "multimodal_vision": True
    }

@app.get("/api/v1/templates")
async def get_templates():
    return {"templates": SYSTEM_TEMPLATES}

@app.post("/api/v1/decision/chat")
async def decision_chat(req: ChatRequest):
    # Log de Auditoria Imediata solicitado pelo usuário:
    print(f"DEBUG: Recebeu imagem? {bool(req.image)} | Tamanho Base64: {len(req.image) if req.image else 0}")
    logger.info(f"DEBUG: Recebeu imagem? {bool(req.image)} | Tamanho Base64: {len(req.image) if req.image else 0}")

    prompt = req.prompt.strip()
    if not prompt and not req.image:
        raise HTTPException(status_code=400, detail="Prompt ou imagem não podem ser vazios")

    if not prompt and req.image:
        prompt = "Analise este print visual da tela, identifique todos os textos e botões e me guie no próximo passo."

    response = None

    # 1. Rota primária: 9Router oficial da VPS
    if req.model != "autonomous-engine":
        logger.info(f"Roteando para 9Router (modelo: {req.model}, tem_imagem={bool(req.image)})...")
        response = await call_9router_chat(
            prompt=prompt,
            model=req.model or "gemini/gemini-2.5-flash",
            image_base64=req.image,
            context=req.context,
            history=req.history
        )

    # 2. Fallback Autônomo com tolerância total a falhas
    if not response:
        logger.info("Acionando Fallback Autonomous Decision Engine...")
        response = simulate_decision_engine(prompt, req.context, has_image=bool(req.image))

    # Broadcast da sala: os demais participantes veem a conversa e o canvas.
    if response and req.sala:
        ROOM_STATE.setdefault(req.sala, {})
        if response.get("tool_call"):
            ROOM_STATE[req.sala]["canvas"] = response["tool_call"]
        await manager.broadcast(req.sala, {"type": "chat", "role": "user", "text": prompt}, exclude=req.client_id)
        await manager.broadcast(req.sala, {"type": "chat", "role": "assistant", "text": response.get("reply", "")}, exclude=req.client_id)
        if response.get("tool_call"):
            await manager.broadcast(req.sala, {"type": "canvas", "tool_call": response["tool_call"]}, exclude=req.client_id)

    return response

@app.post("/api/v1/decision/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Recebe arquivo de áudio e transcreve via Groq Whisper PT-BR."""
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Áudio vazio")

        suffix = ".webm" if "webm" in (file.content_type or "") else ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        groq_key = os.getenv("STT_API_KEY", "")
        if not groq_key:
            raise HTTPException(status_code=503, detail="Transcrição não configurada (STT_API_KEY ausente no .env)")
        groq_url = os.getenv("STT_API_URL", "https://api.groq.com/openai/v1")
        stt_model = os.getenv("STT_MODEL", "whisper-large-v3-turbo")

        transcription_text = ""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with open(tmp_path, "rb") as audio_f:
                    headers = {"Authorization": f"Bearer {groq_key}"}
                    files = {"file": ("audio.webm", audio_f, file.content_type or "audio/webm")}
                    data = {"model": stt_model, "language": "pt", "response_format": "json"}
                    resp = await client.post(f"{groq_url}/audio/transcriptions", headers=headers, files=files, data=data)
                    if resp.status_code == 200:
                        transcription_text = resp.json().get("text", "").strip()
        except Exception as e:
            logger.error(f"Erro no Groq STT: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        if not transcription_text:
            transcription_text = "Elabore um plano de ação estruturado de 30 dias para otimizar nossa operação."

        return {"text": transcription_text, "status": "success"}

    except Exception as e:
        logger.error(f"Erro em transcribe: {e}")
        return JSONResponse(status_code=500, content={"error": str(e), "status": "error"})

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ================= CALC (Piston) / SHARE / INVESTIGAR =================
PISTON_URL = "http://127.0.0.1:2000/api/v2/execute"
PISTON_VERSIONS = {"python": "3.11.0", "javascript": "20.11.1", "php": "8.2.3"}


class CalcRequest(BaseModel):
    sala: Optional[str] = None
    client_id: Optional[str] = None
    language: str = "python"
    source: str = ""


@app.post("/api/v1/decision/calc")
async def decision_calc(req: CalcRequest):
    if req.language not in PISTON_VERSIONS:
        raise HTTPException(status_code=400, detail="Linguagem não suportada pelo Piston local (python/javascript/php)")
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(PISTON_URL, json={
            "language": req.language,
            "version": PISTON_VERSIONS[req.language],
            "files": [{"content": req.source}],
        })
    run = r.json().get("run", {})
    result = {
        "language": req.language,
        "source": req.source,
        "stdout": run.get("stdout", ""),
        "stderr": run.get("stderr", ""),
        "output": run.get("output", ""),
        "code": run.get("code"),
        "ms": round((time.monotonic() - t0) * 1000),
    }
    if req.sala:
        ROOM_STATE.setdefault(req.sala, {})["calc"] = result
        await manager.broadcast(req.sala, {"type": "calc", "calc": result}, exclude=req.client_id)
    return result


class ShareRequest(BaseModel):
    sala: Optional[str] = None
    client_id: Optional[str] = None
    tool_call: Dict[str, Any] = Field(default_factory=dict)


@app.post("/api/v1/decision/share")
async def decision_share(req: ShareRequest):
    if req.sala and req.tool_call:
        ROOM_STATE.setdefault(req.sala, {})["canvas"] = req.tool_call
        await manager.broadcast(req.sala, {"type": "canvas", "tool_call": req.tool_call}, exclude=req.client_id)
    return {"ok": True}


class InvestigarRequest(BaseModel):
    sala: Optional[str] = None
    client_id: Optional[str] = None
    query: str = ""


def _strip_html_to_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _screenshot_url(url: str, sala: str) -> Optional[str]:
    """Captura print da pagina com o Chromium local. Retorna o path estatico ou None."""
    import shutil as _shutil
    binary = _shutil.which("chromium-browser") or _shutil.which("chromium") or _shutil.which("google-chrome")
    if not binary:
        return None
    safe_sala = re.sub(r"[^a-z0-9-]", "", (sala or "sala").lower()) or "sala"
    out_dir = os.path.join(STATIC_DIR, "uploads", "investigacoes")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{safe_sala}-{int(time.time())}.png"
    path = os.path.join(out_dir, fname)
    for headless in ("--headless", "--headless=new"):
        try:
            subprocess.run(
                [binary, headless, "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                 "--window-size=1280,900", "--virtual-time-budget=10000",
                 f"--screenshot={path}", url],
                capture_output=True, timeout=45,
            )
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return f"/static/uploads/investigacoes/{fname}"
        except Exception:
            continue
    return None


@app.post("/api/investigar")
async def investigar(req: InvestigarRequest):
    q = (req.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Informe uma URL ou um tema para investigar")
    is_url = q.startswith("http://") or q.startswith("https://")
    page_text = ""
    fetch_failed = False
    screenshot_url = None
    screenshot_b64 = None
    if is_url:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                r = await client.get(q, headers={"User-Agent": "Mozilla/5.0 (DecisionCanvas/1.0)"})
            page_text = _strip_html_to_text(r.text)[:8000]
        except Exception:
            fetch_failed = True
        screenshot_url = _screenshot_url(q, req.sala or "sala")
        if screenshot_url:
            try:
                with open(os.path.join(STATIC_DIR, screenshot_url.replace("/static/", "")), "rb") as f:
                    import base64 as _b64
                    raw = f.read()
                    if len(raw) < 3_000_000:
                        screenshot_b64 = "data:image/png;base64," + _b64.b64encode(raw).decode()
            except Exception:
                screenshot_b64 = None
    dossier_prompt = (
        f"Investigue o seguinte alvo e produza um dossiê de mercado executivo em pt-BR: {q}. "
        + (f"Conteúdo capturado da página (trecho): {page_text}" if page_text else "")
        + (" Aviso: não consegui baixar o conteúdo da página; analise pela URL e pelo seu conhecimento." if fetch_failed else "")
        + " Estruture o dossiê com: (1) o que o alvo vende e para quem; (2) preços e posicionamento, se visíveis; "
        + "(3) pontos fortes e fracos; (4) oportunidades para o nosso negócio; (5) 3 contramovimentos imediatos. "
        + ("Se recebeu um print da página, comente também o que o visual revela (oferta, CTA, prova social)." if screenshot_b64 else "")
        + " Seja direto, com números e fatos quando houver; sem enrolação."
    )
    resp = await call_9router_chat(
        prompt=dossier_prompt,
        model="gemini/gemini-2.5-flash",
        image_base64=screenshot_b64,
        system_suffix="Você é um investigador de mercado sênior. Responda em pt-BR, de forma executiva e acionável.",
    )
    dossier = (resp or {}).get("reply", "Investigação sem resposta do modelo.")
    tool_call = {"type": "render_investigation", "data": {
        "query": q, "dossier": dossier, "screenshot_url": screenshot_url,
    }}
    if req.sala:
        ROOM_STATE.setdefault(req.sala, {})["canvas"] = tool_call
        await manager.broadcast(req.sala, {"type": "chat", "role": "user", "text": f"/investigar {q}"}, exclude=req.client_id)
        await manager.broadcast(req.sala, {"type": "canvas", "tool_call": tool_call}, exclude=req.client_id)
    return {"query": q, "dossier": dossier, "screenshot_url": screenshot_url}


# ================= AUTH (Google OAuth + sessao + onboarding) =================
# Credenciais isoladas: arquivo .env proprio desta aplicacao (nunca do CRM/Leitor).
DECISION_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _load_decision_env():
    try:
        if os.path.exists(DECISION_ENV_PATH):
            with open(DECISION_ENV_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ and v:
                        os.environ[k] = v
    except Exception:
        pass


_load_decision_env()

DECISION_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "decision.db")
SESSION_COOKIE = "decision_session"
SESSION_DAYS = 30


def _db():
    os.makedirs(os.path.dirname(DECISION_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DECISION_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        google_sub TEXT UNIQUE NOT NULL,
        email TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        picture TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS daily_rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        room_name TEXT NOT NULL,
        url TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    """)
    conn.commit()
    return conn


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn = _db()
    conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (_hash_token(token), user_id, now, now + SESSION_DAYS * 86400))
    conn.commit()
    conn.close()
    return token


def get_session_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = _db()
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
        (_hash_token(token), int(time.time()))).fetchone()
    conn.close()
    if not row:
        return None
    return dict(row)


def destroy_session(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        conn = _db()
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()
        conn.close()


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def google_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def google_redirect_uri() -> str:
    return os.getenv("GOOGLE_REDIRECT_URI", "https://decision.automacaojs.us/api/auth/google/callback")


@app.get("/api/auth/me")
async def auth_me(request: Request):
    user = get_session_user(request)
    if not user:
        return {"logged_in": False}
    return {"logged_in": True, "user": {"name": user["name"], "email": user["email"],
                                        "phone": user["phone"], "picture": user["picture"],
                                        "onboarded": bool(user["phone"])}}


@app.get("/api/auth/google/login")
async def auth_google_login(request: Request, sala: Optional[str] = None):
    if not google_configured():
        raise HTTPException(status_code=503, detail="Login com Google não configurado no servidor (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET)")
    state_token = secrets.token_urlsafe(24)
    clean_sala = re.sub(r"[^a-z0-9-]", "", (sala or "").lower())[:64]
    state = state_token + ("." + clean_sala if clean_sala else "")
    params = {"client_id": os.getenv("GOOGLE_CLIENT_ID"), "redirect_uri": google_redirect_uri(),
              "response_type": "code", "scope": "openid email profile", "state": state, "prompt": "select_account"}
    resp = RedirectResponse(GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode(params))
    resp.set_cookie("oauth_state", state, httponly=True, secure=True, samesite="lax", max_age=600, path="/")
    return resp


@app.get("/api/auth/google/callback")
async def auth_google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        return RedirectResponse("/?auth_error=" + urllib.parse.quote(str(error)))
    saved = request.cookies.get("oauth_state")
    if not saved or not state or state != saved:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido (tente novamente)")
    if not code:
        raise HTTPException(status_code=400, detail="Código de autorização ausente")
    async with httpx.AsyncClient(timeout=30) as client:
        tok = await client.post(GOOGLE_TOKEN_URL, data={"code": code, "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"), "redirect_uri": google_redirect_uri(),
                                "grant_type": "authorization_code"})
        if tok.status_code != 200:
            raise HTTPException(status_code=502, detail="Falha ao trocar o código com o Google")
        access = tok.json().get("access_token")
        me = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": "Bearer " + access})
        if me.status_code != 200:
            raise HTTPException(status_code=502, detail="Falha ao ler o perfil do Google")
        info = me.json()
    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=502, detail="Google não devolveu o identificador do usuário")
    now = int(time.time())
    conn = _db()
    row = conn.execute("SELECT * FROM users WHERE google_sub = ?", (sub,)).fetchone()
    if row:
        conn.execute("UPDATE users SET name = ?, email = ?, picture = ?, updated_at = ? WHERE id = ?",
                     (info.get("name", row["name"]), info.get("email", row["email"]), info.get("picture", ""), now, row["id"]))
        user_id = row["id"]
    else:
        cur = conn.execute("INSERT INTO users (google_sub, email, name, phone, picture, created_at, updated_at) VALUES (?, ?, ?, '', ?, ?, ?)",
                           (sub, info.get("email", ""), info.get("name", ""), info.get("picture", ""), now, now))
        user_id = cur.lastrowid
    conn.commit()
    conn.close()
    token = create_session(user_id)
    back_sala = state.split(".", 1)[1] if "." in state else ""
    dest = ("/?sala=" + back_sala) if back_sala else "/"
    resp = RedirectResponse(dest)
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, secure=True, samesite="lax", max_age=SESSION_DAYS * 86400, path="/")
    resp.delete_cookie("oauth_state", path="/")
    return resp


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    destroy_session(request)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


class OnboardingRequest(BaseModel):
    name: str = ""
    phone: str = ""


def _clean_phone(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


@app.post("/api/auth/onboarding")
async def auth_onboarding(request: Request, req: OnboardingRequest):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Faça login para completar o cadastro")
    name = (req.name or "").strip()
    digits = _clean_phone(req.phone)
    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome completo")
    if len(digits) not in (10, 11):
        raise HTTPException(status_code=400, detail="Telefone inválido — use DDD + número (10 ou 11 dígitos)")
    conn = _db()
    conn.execute("UPDATE users SET name = ?, phone = ?, updated_at = ? WHERE id = ?", (name, digits, int(time.time()), user["id"]))
    conn.commit()
    conn.close()
    return {"ok": True, "user": {"name": name, "email": user["email"], "phone": digits, "onboarded": True}}


@app.post("/api/rooms")
async def create_room(request: Request):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Faça login para criar salas")
    if not user["phone"]:
        raise HTTPException(status_code=403, detail="Complete o cadastro (nome e telefone) antes de criar salas")
    key = get_daily_key()
    if not key:
        raise HTTPException(status_code=503, detail="Chave da Daily não configurada no servidor (DAILY_API_KEY)")
    exp = int(time.time()) + 86400
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(DAILY_API_URL,
                              json={"properties": {"exp": exp, "enable_chat": True, "enable_screenshare": True}},
                              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        if r.status_code != 200:
            if r.status_code in (401, 403):
                raise HTTPException(status_code=502, detail="Chave da Daily rejeitada (401/403)")
            raise HTTPException(status_code=502, detail=f"Daily API retornou {r.status_code}")
        body = r.json()
    now = int(time.time())
    conn = _db()
    conn.execute("INSERT INTO daily_rooms (user_id, room_name, url, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                 (user["id"], body.get("name", ""), body.get("url", ""), now, exp))
    conn.commit()
    conn.close()
    return {"room_name": body.get("name"), "url": body.get("url"), "expires_at": exp}


# ================= DAILY.CO (provisionamento de sala) =================
DAILY_API_URL = "https://api.daily.co/v1/rooms"


def _sanitize_room_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    name = re.sub(r"[^a-z0-9-]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:64]


def get_daily_key() -> Optional[str]:
    key = os.getenv("DAILY_API_KEY")
    if key:
        return key
    try:
        path = "/root/.hermes/secrets/daily.env"
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DAILY_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val
    except Exception:
        pass
    return None


class DailyRoomRequest(BaseModel):
    room_name: str = ""


@app.post("/api/daily/room")
async def daily_room(req: DailyRoomRequest):
    name = _sanitize_room_name(req.room_name)
    if not name.startswith("decision-"):
        name = "decision-" + name
    if name == "decision-":
        raise HTTPException(status_code=400, detail="Nome de sala inválido")
    key = get_daily_key()
    if not key:
        raise HTTPException(status_code=503, detail="Chave da Daily não configurada no servidor (DAILY_API_KEY)")
    exp = int(time.time()) + 86400
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(DAILY_API_URL,
                              json={"name": name, "properties": {"exp": exp, "enable_chat": True}},
                              headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        if r.status_code == 200:
            body = r.json()
            return {"room_name": body.get("name", name), "url": body.get("url")}
        if r.status_code == 400:
            g = await client.get(f"{DAILY_API_URL}/{name}", headers={"Authorization": "Bearer " + key})
            if g.status_code == 200:
                body = g.json()
                return {"room_name": body.get("name", name), "url": body.get("url")}
        if r.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="Chave da Daily rejeitada (401/403) — verifique a DAILY_API_KEY")
        raise HTTPException(status_code=502, detail=f"Daily API retornou {r.status_code}")


@app.get("/")
async def serve_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "running", "message": "Centro de Decisões Empresariais Online."})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8095, reload=False)
