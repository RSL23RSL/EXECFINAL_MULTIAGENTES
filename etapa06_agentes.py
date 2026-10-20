"""
ETAPA 6 -- Os especialistas, cada um com UMA responsabilidade e SÓ as tools de que precisa.

ESQUELETO:
  ETAPA 6.1 -- criar_normas(), criar_escala(), criar_financeiro(), criar_redator()
  ETAPA 6.2 -- criar_coordenador(): usa Normas, Escala e Financeiro como TOOLS (as_tool)

As tools abaixo (PRONTAS) só repassam a chamada ao MCP Server do RH (cliente_mcp.chamar_mcp_async). Dar a cada agente
só as tools dele é o PRIVILÉGIO MÍNIMO (Etapa 9.1); o hook do 🆕 B (etapa10_governanca.py) confere isso em tempo de execução.

REFERÊNCIAS NAS AULAS
  aula4/ex03_agente_as_tool.py                         Coordenador que chama especialistas como tools    <- o mais parecido
  aula2/agente_handoff2.py                             as_tool com tool_name e tool_description
  aula4/ex02_handoff_roteamento.py                     handoff: compare (quem responde no fim?)
  aula7/exemplos/02_agentes_especializados/main.py     uma responsabilidade por agente
  aula7/agentes.py                                     ModelSettings(temperature=0) para respostas mais estáveis
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o problema de dar tools DEMAIS a um agente
"""
import json

from agents import Agent, ModelSettings, RunHooks, function_tool

from etapa05_cliente_mcp import chamar_mcp_async
from etapa04_ferramentas import cotacao_usd_brl

CONFIG = ModelSettings(temperature=0)


# ------------------------------------------------------------------ tools (PRONTAS)
@function_tool
async def consultar_normas(tema: str) -> str:
    """Regras da norma interna sobre um tema: férias, prazos, escala, abono, diária, aprovação, saúde ou dados."""
    return json.dumps(await chamar_mcp_async("consultar_normas", {"tema": tema}), ensure_ascii=False)


@function_tool
async def consultar_escala(equipe: str, inicio: str, fim: str) -> str:
    """Afastamentos da equipe que se sobrepõem ao período (AAAA-MM-DD) e o limite de afastados da regra N5."""
    return json.dumps(await chamar_mcp_async("consultar_escala", {"equipe": equipe, "inicio": inicio, "fim": fim}),
                      ensure_ascii=False)


@function_tool
async def tabela_diarias(tipo_destino: str) -> str:
    """Moeda e valor da diária para o tipo de destino: capital, interior ou exterior."""
    return json.dumps(await chamar_mcp_async("tabela_diarias", {"tipo_destino": tipo_destino}), ensure_ascii=False)


@function_tool
async def consultar_remuneracao(matricula: str) -> str:
    """[RESTRITA] Salário-base de um servidor. Só para calcular a venda de férias (N2)."""
    print(f"[tool] consultar_remuneracao({matricula}) EXECUTOU")  # o 🆕 B prova que, barrada, ela NÃO executa
    return json.dumps(await chamar_mcp_async("consultar_remuneracao", {"matricula": matricula}), ensure_ascii=False)


@function_tool
def cotacao_dolar() -> str:
    """Cotação atual do dólar em reais (USD->BRL). Devolve 'indisponível' se a API falhar: nunca invente o câmbio."""
    cotacao = cotacao_usd_brl()
    return f"{cotacao:.4f}" if cotacao else "indisponível"


# ------------------------------------------------------------------ ETAPA 6.1: especialistas
def criar_normas() -> Agent:
    """ETAPA 6.1 -- diz QUAIS regras se aplicam e as explica. Não calcula valores, não consulta a escala."""
    return Agent(
        name="Normas",
        instructions=(
            "Você é o especialista em NORMAS de RH. Sua única responsabilidade é dizer quais regras da norma interna "
            "se aplicam ao pedido e explicá-las em linguagem simples.\n"
            "- Use a tool consultar_normas com o tema do pedido (ex.: 'férias', 'abono', 'diária', 'prazos', "
            "'aprovação'). Consulte mais de um tema se necessário.\n"
            "- Cite cada regra pelo código (ex.: N2, N5, N6) e diga se o pedido a cumpre ou não.\n"
            "- Se receber VIOLAÇÕES OBJETIVAS, explique cada uma citando a regra correspondente. "
            "Não conteste violações: elas foram verificadas pelo código.\n"
            "- NÃO calcule valores e NÃO consulte a escala da equipe: isso é de outros especialistas.\n"
            "- Nunca invente regras: use só o que a tool devolver. Responda em português, de forma curta."
        ),
        tools=[consultar_normas],
        model_settings=CONFIG,
    )


def criar_escala() -> Agent:
    """ETAPA 6.1 -- confere a regra N5 e, havendo conflito, sugere outro período."""
    return Agent(
        name="Escala",
        instructions=(
            "Você é o especialista em ESCALA. Sua única responsabilidade é conferir a regra N5 "
            "(limite de afastados simultâneos na equipe).\n"
            "- Use a tool consultar_escala com a equipe e o período do pedido (datas AAAA-MM-DD).\n"
            "- Compare o número de afastamentos que se sobrepõem ao período com limite_afastados. Se já estiver "
            "no limite, há CONFLITO: informe quem está afastado (matrícula e datas).\n"
            "- Havendo conflito, SUGIRA outro período com o MESMO número de dias, começando num dia útil "
            "(segunda a quarta, nunca nos 2 dias antes de feriado ou fim de semana, regra N3) e que não se "
            "sobreponha aos afastamentos existentes. Se precisar, consulte a escala do período sugerido para confirmar.\n"
            "- Sem conflito, diga apenas que a escala comporta o afastamento.\n"
            "- NÃO trate de valores nem de outras normas. Responda em português, de forma curta."
        ),
        tools=[consultar_escala],
        model_settings=CONFIG,
    )


def criar_financeiro() -> Agent:
    """ETAPA 6.1 -- calcula venda de férias (N2) e diárias (N7). É o ÚNICO agente que vê o salário."""
    return Agent(
        name="Financeiro",
        instructions=(
            "Você é o especialista FINANCEIRO. Sua única responsabilidade é calcular valores, sempre mostrando a conta.\n"
            "- VENDA DE FÉRIAS (N2): use consultar_remuneracao para obter o salario_base e calcule "
            "dias_vendidos x salario_base / 30. Ex.: 10 x 9500 / 30 = R$ 3.166,67.\n"
            "- DIÁRIAS (N7): uma diária por pernoite + meia diária no dia do retorno. Use tabela_diarias com o "
            "tipo de destino (capital, interior ou exterior). Ex.: 3 pernoites = 3,5 diárias.\n"
            "- No EXTERIOR, o valor é em USD: calcule em dólares (ex.: 3,5 x USD 320 = USD 1.120,00) e converta para "
            "reais com cotacao_dolar. Se a cotação vier 'indisponível', escreva o valor em reais como 'a calcular': "
            "NUNCA invente o câmbio.\n"
            "- O salário é dado restrito: use-o só na conta, sem comentá-lo além do necessário.\n"
            "- Valores em reais no formato R$ 1.234,56. Responda em português, de forma curta."
        ),
        tools=[tabela_diarias, consultar_remuneracao, cotacao_dolar],
        model_settings=CONFIG,
    )


def criar_redator() -> Agent:
    """ETAPA 6.1 -- escreve o DESPACHO usando só os fatos recebidos. Sem tools."""
    return Agent(
        name="Redator",
        instructions=(
            "Você é o REDATOR de despachos de RH. Escreva UM despacho formal, curto, em português, usando SOMENTE "
            "os fatos recebidos (pedido, servidor, período, violações e parecer do coordenador). Não invente nada.\n"
            "- Se receber uma DECISÃO, ela é FINAL (veio das regras em código): siga-a e não a contradiga, mesmo que "
            "algum parecer sugira outra coisa. Só cite violações que estejam na lista de VIOLAÇÕES.\n"
            "- Sem violações: comece com 'Defiro' (ex.: 'Defiro o abono de 1 (um) dia útil em 09/04/2027 à servidora "
            "de matrícula 1001...').\n"
            "- Com violações: comece com 'Indefiro', cite a(s) regra(s) violada(s) (ex.: N5) e inclua a SUGESTÃO de "
            "novo período que veio no parecer.\n"
            "- Termine SEMPRE com a frase 'Pedido deferido.' ou 'Pedido indeferido.' (a validação procura a palavra "
            "'deferido' ou 'indeferido'; 'Defiro'/'Indefiro' sozinhos não bastam).\n"
            "- Inclua: matrícula, tipo do pedido, período (datas no formato DD/MM/AAAA), dias úteis, data de retorno "
            "quando houver, regras citadas e valores calculados (venda de férias, diárias) com a conta.\n"
            "- NUNCA escreva CPF, dado de saúde (regra N10) nem o salário-base do servidor.\n"
            "- Se receber um FEEDBACK (da validação ou da chefia), corrija o despacho conforme o feedback.\n"
            "- Devolva apenas o texto do despacho, sem comentários."
        ),
        model_settings=CONFIG,
    )


# ------------------------------------------------------------------ ETAPA 6.2: coordenador
def criar_coordenador(hooks: RunHooks | None = None, tools_extras: list | None = None) -> Agent:
    """ETAPA 6.2 -- decide QUAIS especialistas consultar (como tools) e junta os pareceres.

    hooks=hooks nas as_tool: o hook do 🆕 B enxerga também as tools DENTRO de cada especialista.
    failure_error_function=None: um erro dentro do especialista (inclusive o bloqueio do 🆕 B) INTERROMPE a execução,
    em vez de virar um texto de erro que o Coordenador ignoraria.
    """
    especialistas = [
        criar_normas().as_tool(
            tool_name="parecer_normas",
            tool_description="Especialista em NORMAS: diz quais regras se aplicam ao pedido e explica as violações. "
                             "Envie o pedido completo (tipo, matrícula, datas) e as violações objetivas.",
            hooks=hooks, failure_error_function=None),
        criar_escala().as_tool(
            tool_name="parecer_escala",
            tool_description="Especialista em ESCALA: confere a regra N5 (limite de afastados da equipe) e, havendo "
                             "conflito, sugere outro período. Envie a equipe e as datas (AAAA-MM-DD).",
            hooks=hooks, failure_error_function=None),
        criar_financeiro().as_tool(
            tool_name="parecer_financeiro",
            tool_description="Especialista FINANCEIRO: calcula a venda de férias (N2) e as diárias (N7, com câmbio no "
                             "exterior). Envie a matrícula, os dias vendidos ou o destino e o número de pernoites.",
            hooks=hooks, failure_error_function=None),
    ]
    return Agent(
        name="Coordenador",
        instructions=(
            "Você é o COORDENADOR de pedidos de RH. Você NÃO responde sozinho: consulta os especialistas (tools) "
            "e junta os pareceres num parecer consolidado.\n"
            "Escolha os especialistas conforme o tipo do pedido:\n"
            "- abono: parecer_normas e parecer_escala (abono NÃO precisa do Financeiro);\n"
            "- férias: parecer_normas e parecer_escala; se houver venda de dias, também parecer_financeiro;\n"
            "- diária: parecer_normas e parecer_financeiro.\n"
            "Ao chamar cada especialista, envie TODOS os fatos de que ele precisa (tipo, matrícula, equipe, datas "
            "AAAA-MM-DD, dias vendidos, destino, violações objetivas): ele não vê a conversa.\n"
            "No parecer consolidado: diga a conclusão (deferir ou indeferir), as regras citadas, os valores calculados "
            "e, se houver conflito ou violação, a sugestão de novo período. As VIOLAÇÕES OBJETIVAS recebidas são "
            "fatos verificados pelo código: se houver alguma, a conclusão é indeferir. "
            "Nunca inclua CPF, dado de saúde nem o salário-base. Responda em português."
        ),
        tools=[*especialistas, *(tools_extras or [])],
        # Um especialista por vez: em modelo LOCAL (Ollama), chamadas em paralelo ficam na fila do servidor e estouram
        # o timeout HTTP. Em série, cada chamada só começa quando a anterior termina.
        model_settings=ModelSettings(temperature=0, parallel_tool_calls=False),
    )