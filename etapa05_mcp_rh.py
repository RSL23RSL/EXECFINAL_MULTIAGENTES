"""
ETAPA 5 -- MCP Server do RH (30 min). Volta aqui na ETAPA 9 (token, regra N8 e auditoria).

Os dados saem de dentro do agente e passam a morar num PROCESSO SEPARADO, que fala MCP. O agente (Etapa 5.3) e os
nós do grafo (Etapa 7, via cliente_mcp.chamar_mcp) só enxergam as tools abaixo: nunca os CSVs.

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 5.1 -- as 5 tools de LEITURA: declare cada uma com @mcp.tool(), escreva a DOCSTRING (é o "schema" que o LLM
               lê) e devolva o resultado da consulta pronta de dados_rh.py. Toda tool devolve UM dict.
  ETAPA 5.2 -- a tool de ESCRITA registrar_decisao, IDEMPOTENTE (protocolo repetido não duplica)
  ETAPA 9.2 -- autorização NO SERVER: token + regra N8 (chefia certa, nunca o próprio servidor) + decisão num enum
  ETAPA 9.3 -- auditoria: toda tentativa de escrita (ALLOW ou DENY) vira uma linha em saidas/auditoria.jsonl

REFERÊNCIAS NAS AULAS
  aula6/desafio2/mcp_unidades.py               MCP Server que lê um CSV                          <- o mais parecido (5.1)
  aula5/exemplos/03_mcp_parametros/server.py   tool com parâmetros opcionais
  aula5/exemplos/05_multiplas_tools/server.py  várias tools no mesmo server, tool de "descoberta"
  aula3/agente_retry3.py                       idempotência (5.2)
  aula5/exemplos/10_seguranca/server_seguro.py token, enum fechado e auditoria NO SERVER        <- o mais parecido (9.2/9.3)

Testar sem agente (MCP Inspector, precisa de Node.js):
    npx @modelcontextprotocol/inspector python etapa05_mcp_rh.py

Pronto quando: o Inspector lista as 6 tools; registrar C1 duas vezes gera um único registro.
"""
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from dados_rh import PASTA, SAIDAS, carregar_servidores, diaria, escala_da_equipe, normas, remuneracao, servidor_publico

# O server roda como SUBPROCESSO: ele não herda o ambiente de quem o chamou. Por isso carrega o .env sozinho
# (mesmo cuidado de aula5/exemplos/02_mcp_basico/database.py).
load_dotenv(PASTA / ".env")

mcp = MCPServer("rh-mcp")

ARQUIVO_REGISTROS = SAIDAS / "registros.json"
ARQUIVO_AUDITORIA = SAIDAS / "auditoria.jsonl"
TOKEN_REGISTRO = os.getenv("TOKEN_REGISTRO", "")
DECISOES_VALIDAS = {"deferido", "indeferido", "indeferido_pela_chefia"}
TIPOS_COM_CHEFIA = {"ferias", "diaria"}  # regra N8


def _ler_registros() -> dict:
    """(PRONTO) {protocolo: registro} gravados até agora."""
    if ARQUIVO_REGISTROS.exists():
        return json.loads(ARQUIVO_REGISTROS.read_text(encoding="utf-8"))
    return {}


def _gravar_registros(registros: dict) -> None:
    """(PRONTO)"""
    ARQUIVO_REGISTROS.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


# ------------------------------------------------------------------ ETAPA 5.1: leitura
# ------------------------------------------------------------------ ETAPA 5.1: leitura
@mcp.tool()
def consultar_servidor(matricula: str) -> dict:
    """Consulta o cadastro de UM servidor pela matrícula (ex.: "1002").

    Devolve os dados funcionais (nome, cargo, equipe, chefia etc.), SEM o salário.
    Se a matrícula não existir, devolve um dict indicando o erro.
    Use para saber a equipe e a chefia imediata de quem fez o pedido.
    """
    return servidor_publico(matricula)


@mcp.tool()
def consultar_escala(equipe: str, inicio: str, fim: str) -> dict:
    """Consulta a escala de uma equipe num período, para checar a regra N5 (limite de afastados simultâneos).

    Args:
        equipe: nome da equipe, como aparece no cadastro do servidor.
        inicio: data inicial do período, no formato AAAA-MM-DD.
        fim: data final do período, no formato AAAA-MM-DD.

    Devolve o tamanho da equipe, o limite de afastados permitido e a lista de
    afastamentos já existentes que se sobrepõem ao período informado.
    """
    return escala_da_equipe(equipe, inicio, fim)


@mcp.tool()
def consultar_normas(tema: str) -> dict:
    """Consulta as normas de RH sobre um tema.

    Temas disponíveis: férias, prazos, escala, abono, diária, aprovação.
    Devolve {"tema": tema, "regras": [lista de regras aplicáveis]}.
    Use antes de decidir um pedido, para citar a regra correta no despacho.
    """
    return {"tema": tema, "regras": normas(tema)}


@mcp.tool()
def tabela_diarias(tipo_destino: str) -> dict:
    """Consulta o valor da diária de viagem conforme o tipo de destino.

    Args:
        tipo_destino: "capital", "interior" ou "exterior".

    Devolve a moeda (BRL ou USD) e o valor da diária para esse destino.
    """
    return diaria(tipo_destino)


@mcp.tool()
def consultar_remuneracao(matricula: str) -> dict:
    """[RESTRITA -- uso exclusivo do Financeiro] Consulta o salário-base de um servidor pela matrícula.

    Contém dado sensível: só deve ser usada para cálculos financeiros
    (ex.: valor de férias ou diárias), nunca para responder ao servidor.
    """
    return remuneracao(matricula)
# ------------------------------------------------------------------ ETAPA 5.2 / 9.2 / 9.3: escrita
def _auditar(protocolo: str, decisao_acesso: str, motivo: str, parametros: dict) -> None:
    # ETAPA 9.3 -- acrescente UMA linha JSON em ARQUIVO_AUDITORIA com: quando (datetime.now().isoformat()),
    #   thread_id, quem pediu (aprovador), tool ("registrar_decisao"), protocolo, decisao_acesso ("ALLOW"/"DENY"),
    #   motivo e os parâmetros (SEM o token e SEM o despacho inteiro).
    #   Referência: aula5/exemplos/10_seguranca/server_seguro.py (_registrar_auditoria), aqui em JSON Lines.
    #   Até fazer a 9.3, este pass deixa a escrita funcionar sem auditoria.
    pass


@mcp.tool()
@mcp.tool()
def registrar_decisao(protocolo: str, matricula: str, tipo: str, inicio: str, fim: str, decisao: str,
                      aprovador: str, despacho: str, token: str, thread_id: str = "") -> dict:
    """[ESCRITA -- requer autorização] Registra a decisão final sobre um pedido de RH.

    É IDEMPOTENTE: se o protocolo já foi registrado, não grava de novo e devolve "duplicado": True.

    Args:
        protocolo: protocolo idempotente do pedido (ferramentas.gerar_protocolo).
        matricula: matrícula do servidor que fez o pedido (ex.: "1001").
        tipo: tipo do pedido: "ferias", "abono" ou "diaria".
        inicio: data de início, no formato AAAA-MM-DD.
        fim: data de fim, no formato AAAA-MM-DD.
        decisao: "deferido", "indeferido" ou "indeferido_pela_chefia".
        aprovador: matrícula de quem aprova (a chefia), ou "sistema".
        despacho: texto do despacho que justifica a decisão.
        token: token de registro. Sem ele, a gravação é negada.
        thread_id: identificador da execução do grafo (opcional), para rastreio.

    Devolve {"sucesso": True, "protocolo": ..., "duplicado": bool} ou {"sucesso": False, "erro": "..."}.
    """
    parametros = {"matricula": matricula, "tipo": tipo, "inicio": inicio, "fim": fim, "decisao": decisao,
                  "aprovador": aprovador, "thread_id": thread_id}

    # ETAPA 9.2 -- (fica para depois) validações de token, enum e regra N8 entram AQUI, antes de gravar.

    # ETAPA 5.2 -- gravação idempotente
    registros = _ler_registros()
    if protocolo in registros:
        _auditar(protocolo, "ALLOW", "protocolo já registrado (duplicado)", parametros)
        return {"sucesso": True, "duplicado": True, "protocolo": protocolo,
                "registro": registros[protocolo]}

    registros[protocolo] = {**parametros, "despacho": despacho,
                            "registrado_em": datetime.now().isoformat(timespec="seconds")}
    ARQUIVO_REGISTROS.parent.mkdir(parents=True, exist_ok=True)   # garante que a pasta saidas/ existe
    _gravar_registros(registros)
    _auditar(protocolo, "ALLOW", "registrado", parametros)
    return {"sucesso": True, "duplicado": False, "protocolo": protocolo}


if __name__ == "__main__":
    mcp.run(transport="stdio")
