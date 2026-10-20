"""
ETAPAS 7, 8, 9 e 10 (e o opcional 🆕 C) -- O sistema como GRAFO (LangGraph), com persistência, humanos no fluxo e segurança.

Reaproveite TUDO o que você já fez: cada nó só chama funções e agentes das etapas anteriores e devolve O QUE MUDOU
no estado (mais o próprio nome em "caminho").

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 7.1 -- confira o Estado (o reducer de `violacoes`)
  ETAPA 7.2 -- nós e roteadores da ENTRADA: proteger_entrada, extrair, identificar_servidor, calcular_periodo
  ETAPA 7.3 -- PARALELISMO: normas, escala e financeiro (fan-out) e consolidar (fan-in)
  ETAPA 7.4 -- CICLO: redigir_despacho <-> validar, no máximo 3 tentativas
  ETAPA 7.5 -- registrar (MCP) e construir(): nós, arestas fixas e condicionais
  ETAPA 8.1 -- compilar com o checkpointer SQLite (já está em main(); confira)
  ETAPA 8.2 -- aprovacao_chefia com interrupt()
  ETAPA 8.3 -- rotear_chefia: aprovado / rejeitado (máx. 2) / indeferido_pela_chefia
  ETAPA 8.4 -- retomar() com Command(resume=...) (o listar_pendentes() já vem pronto: leia)
  ETAPA 9.4 -- guardrail de SAÍDA no registrar (despacho sem CPF/CID, N10)
  (ETAPA 9.2/9.3 ficam no etapa05_mcp_rh.py; ETAPA 10 em etapa10_observabilidade.py e etapa10_governanca.py)
  --- OPCIONAIS (bônus): o grafo funciona sem eles. Faça só se sobrar tempo, depois da Etapa 9.
  🆕 A     -- ligue USAR_VOTACAO = True (depois de fazer o 🆕 A em etapa02_extracao.py)
  🆕 C.1   -- proteger_entrada com DUAS faixas (ok / dúvida / bloqueado)
  🆕 C.2   -- triagem_humana com interrupt() e rotear_triagem; depois ligue USAR_TRIAGEM_HUMANA = True

REFERÊNCIAS NAS AULAS
  aula6/exemplos/05_multiplos_nos/main.py          nós devolvem só o que mudou
  aula6/exemplos/06_fluxo_condicional/main.py      add_conditional_edges com roteador                      (7.2)
  aula6/exemplos/07_dag/main.py                    ramifica e converge                                     (7.3)
  aula7/exemplos/08_paralelismo/main.py            fan-out / fan-in por LISTA e o conflito de escrita      (7.3)
  aula6/exemplos/08_fluxo_ciclico/main.py          ciclo com condição de parada + recursion_limit          (7.4)
  aula6/exemplos/11_grafo_real/main.py             nós de LLM, MCP, API de feriados e tool local, num DAG + ciclo
  aula6/desafio2/main.py                           LLM + MCP + API + ciclo, com caminho percorrido         <- o mais parecido (7)
  aula7/exemplos/05_equipe_multiagente/main.py     especialistas como NÓS (aqui não há mais Coordenador)
  aula8/exemplos/10_agentes_e_grafo/1_codigo_pronto/main.py   agente decide, grafo controla
  aula7/exemplos/04_persistencia/main.py           SqliteSaver, thread_id, get_state, retomar em outro processo  (8.1)
  aula7/exemplos/06_human_in_the_loop/main.py      interrupt() e Command(resume=...)                       (8.2/8.4, 🆕 C)
  aula7/exemplos/07_aprovacao_revisao/main.py      rejeição com feedback e limite de tentativas            <- o mais parecido (8.3)
  aula7/desafio2/                                  duas pessoas decidindo no mesmo fluxo                   (🆕 C)
  aula8/exemplos/05_guardrail_saida/1_codigo_pronto/main.py   conferir a saída antes de entregar         (9.4)
  aula6/exemplos/04_langgraph_basico/main.py       app.get_graph().draw_mermaid()

Rodar (a partir de aula10/):
    python etapa07_grafo.py C2_ferias_com_venda           # um caso (o nome do caso é o thread_id)
    python etapa07_grafo.py --todos                       # os 12 casos
    python etapa07_grafo.py --pendentes                   # quem está pausado e onde (pronto)
    python etapa07_grafo.py --retomar C2_ferias_com_venda sim 1010             # a chefia 1010 aprova
    python etapa07_grafo.py --retomar C2_ferias_com_venda "nao:mude as datas" 1010
    python etapa07_grafo.py --retomar C10_zona_cinzenta "sim:tratar como abono" rh   # 🆕 C (opcional): o atendente do RH decide
    python etapa07_grafo.py --sem-guardrail C7_autoaprovacao   # ETAPA 9.5: o server ainda nega?
    python etapa07_grafo.py --mermaid                     # o diagrama
"""
import asyncio
import operator
import os
import re
import sys
from typing import Annotated, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from dados_rh import SAIDAS
from etapa02_extracao import extrair, extrair_com_votacao
from etapa04_ferramentas import gerar_protocolo, rodar_com_limites_sync
from etapa03_guardrails import LIMIAR, MENSAGENS, encontrar_dado_sensivel, nota_escopo
from etapa10_observabilidade import medido
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas

MODELO = configurar()

MAX_TENTATIVAS = 3     # ciclo redigir <-> validar
MAX_REJEICOES = 2      # ciclo chefia -> redigir
USAR_VOTACAO = False          # 🆕 A (opcional): True usa os 3 extratores com votação (etapa02_extracao.py)
USAR_TRIAGEM_HUMANA = False   # 🆕 C (opcional): True liga as duas faixas e o nó triagem_humana
LIMIAR_OK = 0.4        # 🆕 C: abaixo disto, segue direto
LIMIAR_BLOQUEIO = 0.8  # 🆕 C: a partir disto, bloqueia; entre os dois, um humano decide
GUARDRAIL_LIGADO = "--sem-guardrail" not in sys.argv  # ETAPA 9.5
TIMEOUT_AGENTE = float(os.getenv("TIMEOUT_AGENTE", "90"))  # suba (ex.: 300) se usar modelo local, que é lento


# ------------------------------------------------------------------ ETAPA 7.1: o estado
class Estado(TypedDict, total=False):
    thread_id: str
    texto: str
    bloqueado: bool
    motivo_bloqueio: str
    nota_escopo: float
    triagem: dict                 # 🆕 C: {"segue": bool, "orientacao": str, "quem": str}
    pedido: dict                  # Pedido.model_dump(mode="json")
    divergencia: bool             # 🆕 A
    servidor: dict
    periodo: dict
    escala: dict
    parecer_normas: str
    parecer_escala: str
    parecer_financeiro: str
    # ETAPA 7.1 -- com o reducer, escritas no MESMO passo (ramos paralelos) são SOMADAS em vez de darem conflito.
    violacoes: Annotated[list[str], operator.add]
    decisao: str                  # "deferido" | "indeferido" | "indeferido_pela_chefia"
    despacho: str
    tentativas: int
    erro_validacao: str
    rejeicoes: int
    feedback_chefia: str
    aprovador: str
    protocolo: str
    resultado: str                # o desfecho, para a tabela da Etapa 11
    caminho: Annotated[list[str], operator.add]   # cada nó só ACRESCENTA o próprio nome
    # ETAPA 10.2 -- métricas. tokens tem reducer porque os 3 ramos paralelos escrevem no MESMO passo (somam).
    tokens: Annotated[int, operator.add]
    fonte_feriados: str


# ------------------------------------------------------------------ nós PRONTOS
def receber(estado: Estado) -> dict:
    return {"texto": estado["texto"].strip(), "tentativas": 0, "rejeicoes": 0, "violacoes": [],
            "erro_validacao": "", "feedback_chefia": "", "caminho": ["receber"]}


def recusar(estado: Estado) -> dict:
    orientacao = (estado.get("triagem") or {}).get("orientacao")
    return {"resultado": "recusado", "despacho": orientacao or estado.get("motivo_bloqueio", ""), "caminho": ["recusar"]}


def pedir_dados(estado: Estado) -> dict:
    faltam = "a matrícula e as datas exatas (AAAA-MM-DD)"
    if estado.get("divergencia"):
        faltam = "as datas e o tipo do pedido (a leitura do seu texto ficou ambígua)"
    return {"resultado": "pediu_dados", "despacho": f"Para seguir, informe {faltam}.", "caminho": ["pedir_dados"]}


# ------------------------------------------------------------------ ETAPA 7.2: entrada
def _mensagem_dado_sensivel(achado) -> str:
    """encontrar_dado_sensivel devolve o tipo do dado achado (ex.: "cpf" ou "cid"): escolhe a mensagem certa."""
    chave = str(achado).lower()
    if "cid" in chave or "saude" in chave or "saúde" in chave:
        return MENSAGENS["cid"]
    return MENSAGENS["cpf"]


def proteger_entrada(estado: Estado) -> dict:
    """ETAPA 7.2 -- guardrail de ENTRADA: dado sensível (N10) e escopo. --sem-guardrail desliga (teste da 9.5)."""
    if not GUARDRAIL_LIGADO:
        return {"bloqueado": False, "caminho": ["proteger_entrada"]}
    texto = estado["texto"]
    achado = encontrar_dado_sensivel(texto)
    if achado:
        return {"bloqueado": True, "motivo_bloqueio": _mensagem_dado_sensivel(achado), "caminho": ["proteger_entrada"]}
    nota, _motivo = nota_escopo(texto)
    if nota >= LIMIAR:
        return {"bloqueado": True, "motivo_bloqueio": MENSAGENS["fora_do_escopo"], "nota_escopo": nota,
                "caminho": ["proteger_entrada"]}
    return {"bloqueado": False, "nota_escopo": nota, "caminho": ["proteger_entrada"]}


def rotear_entrada(estado: Estado) -> str:
    """ETAPA 7.2 -- "bloqueado" ou "ok"."""
    return "bloqueado" if estado.get("bloqueado") else "ok"


def triagem_humana(estado: Estado) -> dict:
    # 🆕 C.2 (opcional) -- resposta = interrupt({"pergunta": "Este texto deve seguir como pedido ao RH?",
    #                                  "texto": ..., "nota": ..., "quem_decide": "atendente do RH"})
    #   `resposta` é o que o retomar() entregar: {"segue": bool, "orientacao": str, "quem": str}.
    #   Se segue, ANEXE a orientação ao texto (ex.: "[RH: tratar como abono]") para o extrator usar.
    #   Lembre: na retomada este nó roda DE NOVO desde o início -- nada com efeito colateral antes do interrupt().
    #   Conceito: aula7/exemplos/06_human_in_the_loop/main.py (lá o humano aprova a SAÍDA; aqui decide a ENTRADA)
    raise NotImplementedError("🆕 C.2: triagem_humana")


def rotear_triagem(estado: Estado) -> str:
    # 🆕 C.2 -- "segue" ou "recusa"
    raise NotImplementedError("🆕 C.2: rotear_triagem")


def no_extrair(estado: Estado) -> dict:
    """ETAPA 7.2 -- o texto vira um Pedido estruturado (Etapa 2)."""
    divergencia = False
    if USAR_VOTACAO:  # 🆕 A (opcional)
        pedido, divergencia, _votos = asyncio.run(extrair_com_votacao(estado["texto"]))
    else:
        pedido = extrair(estado["texto"])
    pedido = pedido.model_dump(mode="json")
    # N6: abono é de 1 dia útil -- se o extrator trouxe só o início, o fim é o próprio início.
    if pedido.get("tipo") == "abono" and pedido.get("data_inicio") and not pedido.get("data_fim"):
        pedido["data_fim"] = pedido["data_inicio"]
    return {"pedido": pedido, "divergencia": divergencia, "caminho": ["extrair"]}


def rotear_extracao(estado: Estado) -> str:
    """ETAPA 7.2 -- "incompleto" (divergência, faltam dados ou licença de saúde, N9) ou "ok"."""
    pedido = estado.get("pedido") or {}
    tipo = str(pedido.get("tipo") or "").lower()
    if estado.get("divergencia"):
        return "incompleto"
    if not pedido.get("matricula") or not pedido.get("data_inicio") or not pedido.get("data_fim"):
        return "incompleto"
    if "saude" in tipo or "saúde" in tipo or "licenca" in tipo or "licença" in tipo:  # N9: não segue por aqui
        return "incompleto"
    return "ok"


def identificar_servidor(estado: Estado) -> dict:
    """ETAPA 7.2 -- o cadastro vem do MCP (nunca do CSV)."""
    servidor = chamar_mcp("consultar_servidor", {"matricula": estado["pedido"]["matricula"]})
    return {"servidor": servidor, "caminho": ["identificar_servidor"]}


def rotear_servidor(estado: Estado) -> str:
    """ETAPA 7.2 -- "nao_encontrado" se o MCP devolveu {"erro": ...}; senão "ok"."""
    servidor = estado.get("servidor") or {}
    return "nao_encontrado" if (not servidor or "erro" in servidor) else "ok"


def calcular_periodo(estado: Estado) -> dict:
    """ETAPA 7.2 -- datas (API de feriados, Etapa 4) e escala da equipe (MCP)."""
    pedido, servidor = estado["pedido"], estado["servidor"]
    periodo = resumo_periodo(pedido["data_inicio"], pedido["data_fim"])
    escala = chamar_mcp("consultar_escala", {"equipe": servidor["equipe"],
                                             "inicio": pedido["data_inicio"], "fim": pedido["data_fim"]})
    return {"periodo": periodo, "escala": escala, "fonte_feriados": periodo.get("fonte_feriados"),
            "caminho": ["calcular_periodo"]}


# ------------------------------------------------------------------ ETAPA 7.3: paralelismo
def _fatos(estado: Estado) -> str:
    """(PRONTO) O que os especialistas recebem: pedido, servidor (sem salário), período e escala."""
    return (f"PEDIDO: {estado['pedido']}\nSERVIDOR: {estado['servidor']}\n"
            f"PERÍODO: {estado['periodo']}\nESCALA DA EQUIPE: {estado['escala']}")


def _rodar(agente, entrada: str) -> tuple[str, int]:
    """Roda o agente com os limites da Etapa 4.7 e devolve (texto, tokens gastos) -- os tokens vão para a 10.2."""
    resultado = rodar_com_limites_sync(agente, entrada, timeout_s=TIMEOUT_AGENTE)
    # getattr em cadeia: um resultado simulado (ex.: o conferir.py roda "sem LLM") pode não ter context_wrapper.
    uso = getattr(getattr(resultado, "context_wrapper", None), "usage", None)
    return resultado.final_output, getattr(uso, "total_tokens", 0) or 0


def no_normas(estado: Estado) -> dict:
    """ETAPA 7.3 -- ramo paralelo: escreve SÓ o próprio campo."""
    texto, tokens = _rodar(agentes.criar_normas(), _fatos(estado))
    return {"parecer_normas": texto, "tokens": tokens, "caminho": ["normas"]}


def no_escala(estado: Estado) -> dict:
    """ETAPA 7.3 -- ramo paralelo: escreve SÓ o próprio campo."""
    texto, tokens = _rodar(agentes.criar_escala(), _fatos(estado))
    return {"parecer_escala": texto, "tokens": tokens, "caminho": ["escala"]}


def no_financeiro(estado: Estado) -> dict:
    """ETAPA 7.3 -- ramo paralelo. Abono, ou férias sem venda, não têm valor: nem chama o LLM (economiza tokens
    e não expõe o salário à toa)."""
    pedido = estado["pedido"]
    if pedido.get("tipo") == "abono" or (pedido.get("tipo") == "ferias" and not pedido.get("dias_vendidos")):
        return {"parecer_financeiro": "não se aplica (sem valor a calcular)", "tokens": 0, "caminho": ["financeiro"]}
    texto, tokens = _rodar(agentes.criar_financeiro(), _fatos(estado))
    return {"parecer_financeiro": texto, "tokens": tokens, "caminho": ["financeiro"]}


def consolidar(estado: Estado) -> dict:
    """ETAPA 7.3 -- fan-in: só roda depois dos três ramos. Quem DECIDE é a regra objetiva (Python), não o LLM."""
    violacoes = violacoes_objetivas(estado["pedido"], estado["servidor"], estado["periodo"], estado["escala"])
    return {"violacoes": violacoes, "decisao": "indeferido" if violacoes else "deferido", "caminho": ["consolidar"]}


# ------------------------------------------------------------------ ETAPA 7.4: ciclo
def redigir_despacho(estado: Estado) -> dict:
    """ETAPA 7.4 -- o Redator escreve; na volta do ciclo recebe o erro da validação e/ou o feedback da chefia."""
    violacoes = estado.get("violacoes") or []
    entrada = (
        f"{_fatos(estado)}\n"
        f"DECISÃO: {estado.get('decisao')}\n"
        f"VIOLAÇÕES: {'; '.join(violacoes) if violacoes else 'nenhuma'}\n"
        f"PARECER NORMAS: {estado.get('parecer_normas', '')}\n"
        f"PARECER ESCALA: {estado.get('parecer_escala', '')}\n"
        f"PARECER FINANCEIRO: {estado.get('parecer_financeiro', '')}\n"
    )
    if estado.get("erro_validacao"):
        entrada += f"\nFEEDBACK DA VALIDAÇÃO (corrija): {estado['erro_validacao']}"
    if estado.get("feedback_chefia"):
        entrada += f"\nFEEDBACK DA CHEFIA (corrija): {estado['feedback_chefia']}"
    despacho, tokens = _rodar(agentes.criar_redator(), entrada)
    return {"despacho": despacho, "tokens": tokens, "caminho": ["redigir_despacho"]}


def problemas_do_despacho(despacho: str, pedido: dict) -> list[str]:
    """(PRONTO) O que falta ou sobra no despacho: precisa citar a matrícula, o início do período (AAAA-MM-DD ou
    DD/MM/AAAA) e a decisão, e não pode ter CPF nem CID (N10). Lista vazia = despacho válido."""
    problemas, texto = [], despacho.lower()
    if pedido.get("matricula") and pedido["matricula"] not in despacho:
        problemas.append(f"cite a matrícula {pedido['matricula']}")
    inicio = pedido.get("data_inicio") or ""
    if inicio and inicio not in despacho and "/".join(reversed(inicio.split("-"))) not in despacho:
        problemas.append(f"cite o início do período ({inicio})")
    if "deferid" not in texto and "indeferid" not in texto:
        problemas.append("diga a decisão (deferido ou indeferido)")
    if encontrar_dado_sensivel(despacho):
        problemas.append("tire o CPF/CID do despacho (N10)")
    return problemas


def validar(estado: Estado) -> dict:
    """ETAPA 7.4 -- confere o despacho e CONTA a tentativa (é o que faz o ciclo parar)."""
    despacho = estado.get("despacho", "")
    problemas = problemas_do_despacho(despacho, estado["pedido"])
    # O despacho não pode CONTRADIZER a decisão (quem decide é a regra em Python, não o Redator).
    texto = despacho.lower()
    nega = "indefir" in texto or "indeferid" in texto   # "Indefiro" ou "indeferido"
    if estado.get("decisao") == "deferido" and nega:
        problemas.append("a decisão é DEFERIDO: não indefira o pedido nem invente violação")
    if estado.get("decisao") == "indeferido" and not nega:
        problemas.append("a decisão é INDEFERIDO: o despacho precisa indeferir o pedido")
    return {"tentativas": estado.get("tentativas", 0) + 1, "erro_validacao": "; ".join(problemas),
            "caminho": ["validar"]}


def rotear_validacao(estado: Estado) -> str:
    """ETAPA 7.4 -- com erro e tentativas sobrando: volta a redigir. Senão: chefia (N8) ou registrar."""
    if estado.get("erro_validacao") and estado.get("tentativas", 0) < MAX_TENTATIVAS:
        return "redigir"
    if precisa_chefia(estado["pedido"], estado.get("violacoes") or []):
        return "chefia"
    return "registrar"


# ------------------------------------------------------------------ ETAPA 8: a chefia
def aprovacao_chefia(estado: Estado) -> dict:
    """ETAPA 8.2 -- pausa o grafo e espera a chefia. Nada com efeito colateral ANTES do interrupt():
    na retomada, este nó roda de novo desde o começo."""
    servidor = estado["servidor"]
    resposta = interrupt({
        "pergunta": "Aprova o despacho?",
        "chefia": servidor.get("chefia"),
        "resumo": {
            "servidor": f"{servidor.get('matricula')} - {servidor.get('nome')} ({servidor.get('equipe')})",
            "periodo": f"{estado['periodo'].get('inicio')} a {estado['periodo'].get('fim')}",
            "parecer_normas": estado.get("parecer_normas"),
            "parecer_escala": estado.get("parecer_escala"),
            "parecer_financeiro": estado.get("parecer_financeiro"),
            "despacho": estado.get("despacho"),
        },
    })
    if resposta.get("aprovado"):
        return {"aprovador": resposta.get("aprovador", ""), "feedback_chefia": "", "caminho": ["aprovacao_chefia"]}
    return {"rejeicoes": estado.get("rejeicoes", 0) + 1,
            "feedback_chefia": resposta.get("motivo") or "rejeitado pela chefia (sem motivo informado)",
            "aprovador": resposta.get("aprovador", ""),
            "tentativas": 0,  # nova rodada de redação: a validação volta a ter as 3 tentativas
            "caminho": ["aprovacao_chefia"]}


def rotear_chefia(estado: Estado) -> str:
    """ETAPA 8.3 -- aprovado -> registrar; rejeitado -> redigir (até MAX_REJEICOES); depois -> registrar
    (o registrar grava como "indeferido_pela_chefia")."""
    if not estado.get("feedback_chefia"):
        return "registrar"
    if estado.get("rejeicoes", 0) < MAX_REJEICOES:
        return "redigir"
    return "registrar"


# ------------------------------------------------------------------ ETAPA 7.5 / 9.4: registrar
def registrar(estado: Estado) -> dict:
    """ETAPA 7.5 -- grava pelo MCP (idempotente). ETAPA 9.4 -- antes, o guardrail de SAÍDA (N10)."""
    pedido, despacho = estado["pedido"], estado.get("despacho", "")

    # ETAPA 9.4 -- guardrail de SAÍDA: despacho com CPF/CID não é gravado.
    if encontrar_dado_sensivel(despacho):
        return {"resultado": "bloqueado_na_saida", "caminho": ["registrar"]}

    decisao = estado.get("decisao", "deferido")
    if estado.get("rejeicoes", 0) >= MAX_REJEICOES:
        decisao = "indeferido_pela_chefia"
    protocolo = gerar_protocolo(pedido["matricula"], pedido.get("tipo", ""), pedido["data_inicio"], pedido["data_fim"])
    resposta = chamar_mcp("registrar_decisao", {
        "protocolo": protocolo,
        "matricula": pedido["matricula"],
        "tipo": pedido.get("tipo", ""),
        "inicio": pedido["data_inicio"],
        "fim": pedido["data_fim"],
        "decisao": decisao,
        "aprovador": estado.get("aprovador") or "sistema",
        "despacho": despacho,
        "token": os.getenv("TOKEN_REGISTRO", ""),
        "thread_id": estado.get("thread_id", ""),
    })
    resultado = "registrado" if resposta.get("sucesso") else "negado_pelo_server"
    return {"protocolo": protocolo, "decisao": decisao, "resultado": resultado, "caminho": ["registrar"]}


# ------------------------------------------------------------------ ETAPA 7.5: o grafo
def construir(checkpointer=None):
    construtor = StateGraph(Estado)
    nos = {
        "receber": receber, "proteger_entrada": proteger_entrada,
        "recusar": recusar, "extrair": no_extrair, "pedir_dados": pedir_dados,
        "identificar_servidor": identificar_servidor, "calcular_periodo": calcular_periodo,
        "normas": no_normas, "escala": no_escala, "financeiro": no_financeiro, "consolidar": consolidar,
        "redigir_despacho": redigir_despacho, "validar": validar, "aprovacao_chefia": aprovacao_chefia,
        "registrar": registrar,
    }
    if USAR_TRIAGEM_HUMANA:  # 🆕 C (opcional): o nó só entra no grafo quando o item está ligado
        nos["triagem_humana"] = triagem_humana
    for nome, funcao in nos.items():
        construtor.add_node(nome, medido(nome, funcao))  # medido(): ETAPA 10.2 (por enquanto, não muda nada)

    # entrada
    construtor.add_edge(START, "receber")
    construtor.add_edge("receber", "proteger_entrada")
    rotas_entrada = {"bloqueado": "recusar", "ok": "extrair"}
    if USAR_TRIAGEM_HUMANA:  # 🆕 C (opcional)
        rotas_entrada["duvida"] = "triagem_humana"
        construtor.add_conditional_edges("triagem_humana", rotear_triagem, {"segue": "extrair", "recusa": "recusar"})
    construtor.add_conditional_edges("proteger_entrada", rotear_entrada, rotas_entrada)
    construtor.add_conditional_edges("extrair", rotear_extracao,
                                     {"incompleto": "pedir_dados", "ok": "identificar_servidor"})
    construtor.add_conditional_edges("identificar_servidor", rotear_servidor,
                                     {"nao_encontrado": "pedir_dados", "ok": "calcular_periodo"})

    # fan-out (os três no mesmo passo) e fan-in (LISTA: consolidar espera os três)
    for ramo in ("normas", "escala", "financeiro"):
        construtor.add_edge("calcular_periodo", ramo)
    construtor.add_edge(["normas", "escala", "financeiro"], "consolidar")

    # ciclo redigir <-> validar, e a chefia
    construtor.add_edge("consolidar", "redigir_despacho")
    construtor.add_edge("redigir_despacho", "validar")
    construtor.add_conditional_edges("validar", rotear_validacao,
                                     {"redigir": "redigir_despacho", "chefia": "aprovacao_chefia",
                                      "registrar": "registrar"})
    construtor.add_conditional_edges("aprovacao_chefia", rotear_chefia,
                                     {"redigir": "redigir_despacho", "registrar": "registrar"})

    # saídas
    for fim in ("recusar", "pedir_dados", "registrar"):
        construtor.add_edge(fim, END)
    return construtor.compile(checkpointer=checkpointer)


# ------------------------------------------------------------------ execução
def config_de(thread_id: str) -> dict:
    """(PRONTO) thread_id identifica a execução no checkpointer; recursion_limit protege contra ciclo infinito."""
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def mostrar(app, thread_id: str, saida: dict) -> None:
    """(PRONTO) Imprime o caminho, o desfecho e, se pausou, a pergunta feita ao humano."""
    print(f"\n[{thread_id}] caminho: {' -> '.join(saida.get('caminho', []))}")
    if "__interrupt__" in saida:
        pausa = saida["__interrupt__"][0].value
        print(f"[{thread_id}] PAUSADO em {app.get_state(config_de(thread_id)).next}: {pausa.get('pergunta')}")
        print(f"   retome com: python etapa07_grafo.py --retomar {thread_id} sim|\"nao:motivo\" <quem>")
    else:
        print(f"[{thread_id}] resultado: {saida.get('resultado')}  protocolo: {saida.get('protocolo')}")
        print(f"[{thread_id}] despacho: {saida.get('despacho')}")


def executar(app, thread_id: str, texto: str) -> None:
    """(PRONTO) Roda um pedido do começo. Apaga antes os checkpoints desse thread_id: sem isso, rodar o mesmo caso
    de novo CONTINUARIA a execução anterior, e os campos com reducer (caminho, violacoes) acumulariam as duas."""
    if app.checkpointer:
        app.checkpointer.delete_thread(thread_id)
    saida = app.invoke({"thread_id": thread_id, "texto": texto}, config_de(thread_id))
    mostrar(app, thread_id, saida)


def listar_pendentes(app, checkpointer) -> None:
    """(PRONTO) Cada execução (thread_id) que está no checkpointer e onde ela parou. Quem tem `next` não vazio está
    PAUSADO esperando um humano. É o get_state() da aula7/exemplos/04_persistencia/main.py, para todas as execuções."""
    vistos = []
    for checkpoint in checkpointer.list(None):  # todos os checkpoints de todas as execuções
        thread_id = checkpoint.config["configurable"]["thread_id"]
        if thread_id not in vistos:
            vistos.append(thread_id)
    for thread_id in vistos:
        proximo = app.get_state(config_de(thread_id)).next
        print(f"{thread_id}: {'PAUSADO em ' + str(proximo) if proximo else 'concluído'}")


def retomar(app, thread_id: str, resposta: str, quem: str) -> None:
    """ETAPA 8.4 -- entrega a resposta do humano ao interrupt() onde a execução parou."""
    proximo = app.get_state(config_de(thread_id)).next
    if not proximo:  # nada pausado (nunca rodou, já terminou ou já foi retomado): não faz nada
        print(f"[{thread_id}] nada pausado para retomar.")
        return
    texto = resposta.strip()
    segue = texto.lower().startswith("sim")
    complemento = texto.split(":", 1)[1].strip() if ":" in texto else ""
    if "aprovacao_chefia" in proximo:
        valor = {"aprovado": segue, "aprovador": quem, "motivo": "" if segue else complemento}
    elif "triagem_humana" in proximo:  # 🆕 C (opcional)
        valor = {"segue": segue, "orientacao": complemento, "quem": quem}
    else:
        print(f"[{thread_id}] pausado em {proximo}: não sei retomar esse ponto.")
        return
    saida = app.invoke(Command(resume=valor), config_de(thread_id))
    mostrar(app, thread_id, saida)


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--sem-guardrail"]
    # ETAPA 8.1 -- o checkpointer SQLite: é ele que deixa a execução pausada sobreviver ao fim do processo.
    SAIDAS.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(SAIDAS / "checkpoints.db")) as checkpointer:
        app = construir(checkpointer)
        if not args or args[0] == "--mermaid":
            print(app.get_graph().draw_mermaid())
        elif args[0] == "--pendentes":
            listar_pendentes(app, checkpointer)
        elif args[0] == "--retomar":
            retomar(app, args[1], args[2], args[3] if len(args) > 3 else "?")
        elif args[0] == "--todos":
            for nome, caso in CASOS.items():
                executar(app, nome, caso["pedido"])
        else:
            executar(app, args[0], CASOS[args[0]]["pedido"])


if __name__ == "__main__":
    print(f"[modelo] {MODELO}  [guardrail de entrada {'ligado' if GUARDRAIL_LIGADO else 'DESLIGADO'}]")
    main()