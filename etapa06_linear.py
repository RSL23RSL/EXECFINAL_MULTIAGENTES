"""
ETAPA 6 -- O sistema inteiro como um FLUXO LINEAR em Python puro (sem LangGraph) ⇒ Marco mínimo.

ESQUELETO:
  ETAPA 6.3 -- analisar(): o Coordenador junta os pareceres (com os limites da Etapa 4.7)
  ETAPA 6.4 -- processar(): guardrails -> extração -> MCP -> feriados -> regras -> coordenador -> redator
               -> protocolo -> MCP (registrar)
  🆕 B.4    -- (OPCIONAL, bônus) testar_governanca(): os dois testes de bloqueio do --governanca

REFERÊNCIAS NAS AULAS
  aula6/exemplos/01_fluxo_linear/main.py     o fluxo linear: funciona, mas sem decisão nem volta (por isso a Etapa 7)
  aula4/ex03_agente_as_tool.py               o Coordenador com especialistas como tools
  aula7/exemplos/02_agentes_especializados/main.py   cada especialista imprime o que fez: dá para saber quem fez o quê

Rodar:
    python etapa06_linear.py                 # C1, C2, C6 e C11
    python etapa06_linear.py --governanca    # 🆕 B (opcional): os dois testes de bloqueio

Pronto quando: C1, C2 e C11 são gravados com protocolo, C6 vira indeferimento com sugestão de datas, e você sabe dizer
qual agente escreveu cada parte. (Opcional) no --governanca: a tool restrita NÃO executa e o C2 para no orçamento.
"""
import json
import os
import sys

from agents import RunHooks, ToolCallItem

import etapa06_agentes as agentes
from etapa05_cliente_mcp import chamar_mcp
from dados.casos import CASOS
from etapa02_extracao import extrair
from etapa04_ferramentas import buscar_feriados, gerar_protocolo, rodar_com_limites_sync
from etapa10_governanca import Governanca, LimiteExcedido
from etapa03_guardrails import encontrar_dado_sensivel, nota_escopo, LIMIAR, MENSAGENS
from provedor import configurar
from etapa06_regras import precisa_chefia, resumo_periodo, violacoes_objetivas

MODELO = configurar()
MODELO = "gpt-4o-mini"
print(f"Usando o modelo: {MODELO}")
# Limites de tempo (Etapa 4.7). Modelos LOCAIS (ex.: llama3.1 no Ollama) são lentos e o Coordenador chama especialistas
# que chamam tools: 90 s não bastam. Com um modelo na nuvem, 90 s costumam sobrar.
TIMEOUT_COORDENADOR = float(os.getenv("TIMEOUT_COORDENADOR", "900"))
TIMEOUT_REDATOR = float(os.getenv("TIMEOUT_REDATOR", "180"))


# ------------------------------------------------------------------ auxiliares
def _json(dado) -> str:
    """Serializa para o texto que vai ao LLM (acentos legíveis)."""
    return json.dumps(dado, ensure_ascii=False)


def _campo(dado: dict, *chaves, padrao=None):
    """Primeira chave existente em `dado` (os nomes podem variar entre as etapas)."""
    for chave in chaves:
        if isinstance(dado, dict) and dado.get(chave) is not None:
            return dado[chave]
    return padrao


def _tools_chamadas(resultado) -> list[str]:
    """Nomes das tools (especialistas) que o agente chamou, na ordem, sem repetir."""
    nomes = []
    for item in resultado.new_items:
        if isinstance(item, ToolCallItem):
            bruto = item.raw_item
            nome = bruto.get("name") if isinstance(bruto, dict) else getattr(bruto, "name", None)
            if nome and nome not in nomes:
                nomes.append(nome)
    return nomes


def _nota(retorno_escopo) -> float:
    """nota_escopo devolve uma TUPLA (a nota vem junto de outra informação): pegamos só o número."""
    if isinstance(retorno_escopo, tuple):
        return next(v for v in retorno_escopo if isinstance(v, (int, float)))
    return retorno_escopo


# ------------------------------------------------------------------ ETAPA 6.3
def _rodar_coordenador(pedido: dict, servidor: dict, periodo: dict, violacoes: list[str],
                       hooks: RunHooks | None = None):
    """Roda o Coordenador e devolve o RunResult inteiro (para saber quais especialistas ele consultou)."""
    entrada = (
        f"PEDIDO (extraído do texto do servidor): {_json(pedido)}\n"
        f"SERVIDOR: matrícula {servidor.get('matricula')}, equipe {servidor.get('equipe')}, "
        f"chefia {servidor.get('chefia')}\n"
        f"PERÍODO (dias úteis/feriados calculados pelo código): {_json(periodo)}\n"
        f"VIOLAÇÕES OBJETIVAS (regras checadas pelo código): {_json(violacoes) if violacoes else 'nenhuma'}\n\n"
        "Consulte os especialistas necessários e emita um parecer consolidado. "
        "Se houver violação, o parecer é pelo indeferimento e deve sugerir alternativa (ex.: outras datas)."
    )
    coordenador = agentes.criar_coordenador(hooks)
    return rodar_com_limites_sync(coordenador, entrada, hooks=hooks, timeout_s=TIMEOUT_COORDENADOR)


def analisar(pedido: dict, servidor: dict, periodo: dict, violacoes: list[str], hooks: RunHooks | None = None) -> str:
    """ETAPA 6.3 -- o Coordenador recebe os FATOS (já verificados pelo código) e junta os pareceres dos especialistas.
    Roda com os limites da Etapa 4.7 (tempo + max_turns) e repassa os hooks (governança, item 🆕 B)."""
    return _rodar_coordenador(pedido, servidor, periodo, violacoes, hooks).final_output


# ------------------------------------------------------------------ ETAPA 6.4
def processar(texto: str, hooks: RunHooks | None = None) -> dict:
    """ETAPA 6.4 -- o fluxo linear completo, em 9 passos, sem decisão nem volta (isso é a Etapa 7)."""
    # 1. Guardrails: nada de dado sensível nem pedido fora do escopo de RH.
    print("[1/9] guardrails")
    if encontrar_dado_sensivel(texto):
        return {"resultado": "bloqueado",
                "mensagem": MENSAGENS.get("dado_sensivel", "O pedido contém dado sensível e foi bloqueado.")}
    if _nota(nota_escopo(texto)) >= LIMIAR:
        return {"resultado": "bloqueado",
                "mensagem": MENSAGENS.get("fora_de_escopo", "O pedido está fora do escopo do RH.")}

    # 2. Extração estruturada (Etapa 2).
    pedido = extrair(texto).model_dump(mode="json")
    matricula, tipo = pedido.get("matricula"), pedido.get("tipo") or ""
    inicio, fim = pedido.get("data_inicio"), pedido.get("data_fim")
    if tipo == "abono" and inicio and not fim:  # regra N6: abono é de 1 dia útil, então o fim é o próprio início
        fim = pedido["data_fim"] = inicio
    print(f"[2/9] extração: {tipo} {matricula} {inicio}..{fim}")
    faltando = [nome for nome, valor in (("matricula", matricula), ("data_inicio", inicio), ("data_fim", fim))
                if not valor]
    if faltando:
        return {"resultado": "pedir_dados", "faltando": faltando}

    # 3. Cadastro do servidor, pelo MCP (nunca lendo o CSV direto).
    servidor = chamar_mcp("consultar_servidor", {"matricula": matricula})
    if not servidor or "erro" in servidor:
        print(f"[3/9] servidor: matrícula {matricula} não encontrada")
        return {"resultado": "pedir_dados", "mensagem": f"Matrícula {matricula} não encontrada."}
    print(f"[3/9] servidor: {servidor.get('nome')} ({servidor.get('equipe')})")

    # 4. Período: dias úteis, feriados, data de retorno (API de feriados, Etapa 4).
    periodo = resumo_periodo(inicio, fim)
    uteis = _campo(periodo, "dias_uteis", "uteis")
    retorno = _campo(periodo, "data_retorno", "retorno")
    fonte = _campo(periodo, "fonte", "fonte_feriados") or buscar_feriados(int(inicio[:4]))[1]  # já está no cache
    rotulo = "dia útil" if uteis == 1 else "dias úteis"
    print(f"[4/9] período: {uteis} {rotulo}, retorno {retorno} (fonte: {fonte})")

    # 5. Escala da equipe (MCP) + regras objetivas, checadas por CÓDIGO e não pelo LLM.
    escala = chamar_mcp("consultar_escala", {"equipe": servidor["equipe"], "inicio": inicio, "fim": fim})
    violacoes = violacoes_objetivas(pedido, servidor, periodo, escala)
    print(f"[5/9] violações: {'; '.join(map(str, violacoes)) if violacoes else 'nenhuma'}")

    # 6. Coordenador consolida os pareceres dos especialistas.
    resultado_coord = _rodar_coordenador(pedido, servidor, periodo, violacoes, hooks)
    parecer = resultado_coord.final_output
    consultados = _tools_chamadas(resultado_coord)
    print(f"[6/9] coordenador: consultou {', '.join(consultados) if consultados else 'nenhum especialista'}")

    # 7. Redator escreve o despacho a partir dos fatos + parecer + violações.
    print("[7/9] redator")
    entrada_redator = (
        f"FATOS: pedido {_json(pedido)}; servidor {servidor.get('matricula')} ({servidor.get('nome')}), "
        f"equipe {servidor.get('equipe')}; período {_json(periodo)}\n"
        f"VIOLAÇÕES: {_json(violacoes) if violacoes else 'nenhuma'}\n"
        f"PARECER DO COORDENADOR:\n{parecer}"
    )
    despacho = rodar_com_limites_sync(agentes.criar_redator(), entrada_redator, hooks=hooks,
                                      timeout_s=TIMEOUT_REDATOR).final_output

    # 8. Protocolo idempotente (Etapa 4.6): o mesmo pedido gera sempre o mesmo protocolo.
    protocolo = gerar_protocolo(matricula, tipo, inicio, fim)
    print(f"[8/9] protocolo {protocolo}")

    # 9. Registro pelo MCP (idempotente, Etapa 5.2). A aprovação real da chefia entra na Etapa 8.
    registro = chamar_mcp("registrar_decisao", {
        "protocolo": protocolo,
        "matricula": matricula,
        "tipo": tipo,
        "inicio": inicio,
        "fim": fim,
        "decisao": "indeferido" if violacoes else "deferido",
        "aprovador": "pendente_chefia" if precisa_chefia(pedido, violacoes) else "sistema",
        "despacho": despacho,
        "token": os.getenv("TOKEN_REGISTRO", ""),
    })
    print(f"[9/9] registrar: {registro}")

    return {"resultado": "registrado" if registro.get("sucesso") else "erro_registro",
            "protocolo": protocolo, "despacho": despacho, "parecer": parecer}


# ------------------------------------------------------------------ 🆕 B.4 (opcional)
def testar_governanca() -> None:
    """🆕 B.4 (opcional) -- dois testes de bloqueio pela Governanca (hooks)."""
    # a) Tool restrita: o coordenador ganha consultar_remuneracao, mas a governança deve barrar ANTES de executar.
    print("\n=============== (a) tool restrita")
    gov = Governanca()
    coordenador = agentes.criar_coordenador(hooks=gov, tools_extras=[agentes.consultar_remuneracao])
    try:
        resposta = rodar_com_limites_sync(coordenador, "Qual o salário da matrícula 1002?", hooks=gov).final_output
        print("NÃO foi barrado (verifique a Governanca):", resposta)
    except LimiteExcedido as erro:
        print("BARRADO:", erro)

    # b) Orçamento de tools: com max_tools=1, o C2 deve parar antes do segundo especialista.
    print("\n=============== (b) orçamento de tools (C2)")
    try:
        resultado = processar(CASOS["C2_ferias_com_venda"]["pedido"], hooks=Governanca(max_tools=1))
        print("NÃO foi barrado (verifique max_tools):", json.dumps(resultado, ensure_ascii=False, indent=2))
    except LimiteExcedido as erro:
        print("BARRADO:", erro)


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    if "--governanca" in sys.argv:
        testar_governanca()
    else:
        for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C6_conflito_de_escala", "C11_diaria_exterior"):
            print(f"\n=============== {nome}")
            print(json.dumps(processar(CASOS[nome]["pedido"]), ensure_ascii=False, indent=2))
