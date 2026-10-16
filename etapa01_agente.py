"""
ETAPA 1 -- Primeiro agente com tool local (15 min).

ESQUELETO: implemente as etapas na ordem. Cada uma está marcada com um comentário e um
raise NotImplementedError: troque esse raise pelo código da etapa e rode o arquivo.
  ETAPA 1.1 -- a tool consultar_servidor (SEM o salário)
  ETAPA 1.2 -- o agente AtendenteRH com a tool
  ETAPA 1.3 -- duas perguntas: uma que precisa da tool e uma que não precisa

REFERÊNCIAS NAS AULAS
  aula1/segundo_agente.py                            Agent + @function_tool + Runner.run_sync (o básico)
  exercicios_resolvidos/aula4/ex10_function_tool.py  tool que consulta uma TABELA e devolve JSON  <- o mais parecido
  aula8/exemplos/02_agente_tool/main.py              o agente decide quando chamar a tool (e quando não)

Rodar (a partir de aula10/):
    python etapa01_agente.py

Pronto quando: a tool é chamada só na primeira pergunta (o print dentro dela prova).
"""
import json

from agents import Agent, Runner, function_tool

from dados_rh import servidor_publico
from provedor import configurar

MODELO = configurar()  # LLM REAL: PROVEDOR no .env (openai ou ollama)
#MODELO = 'llama3.2'

# ETAPA 1.1 -- a tool
@function_tool
def consultar_servidor(matricula: str) -> str:
    """Consulta o cadastro de UM servidor público pela matrícula.

    Use esta tool sempre que a pergunta for sobre os dados de um servidor específico,
    como nome, cargo, lotação, situação funcional ou saldo de férias. Ela NÃO devolve
    o salário, que é um dado restrito.

    Não use para perguntas gerais sobre regras de RH (por exemplo, "o que é abono
    pecuniário?"), que não dependem de um servidor específico.

    Args:
        matricula: número de matrícula do servidor, como texto (ex.: "1002").

    Returns:
        JSON com os dados públicos do servidor, ou uma mensagem de erro se a
        matrícula não existir.
    """
    print("[tool] consultar_servidor", matricula)
    return json.dumps(servidor_publico(matricula), ensure_ascii=False)


def criar_atendente() -> Agent:
    # ETAPA 1.2 -- o agente
    return Agent(
        name="AtendenteRH",
        instructions=(
            "Você é o atendente de RH que atende servidores públicos. "
            "Responda sempre em português e de forma breve. "
            "Quando a pergunta for sobre os dados de UM servidor (férias, cargo, lotação etc.), "
            "use a tool consultar_servidor com a matrícula informada e responda com base no que ela devolver. "
            "Nunca invente saldo de férias ou qualquer dado de servidor de cabeça: se não tiver a matrícula, peça. "
            "Se a matrícula não existir, diga isso ao usuário. "
            "Perguntas gerais sobre regras e conceitos de RH você responde SEM CHAMAR A TOOLS."
        ),
        tools=[consultar_servidor],
        model=MODELO,
    )


def main() -> None:
    # ETAPA 1.3 -- duas perguntas: uma precisa da tool, a outra não
    atendente = criar_atendente()

    perguntas = [
        "Quantos dias de férias a matrícula 1002 ainda tem?",  # precisa da tool
        "O que é abono pecuniário?",                           # não precisa
    ]

    for pergunta in perguntas:
        print(f"\n[pergunta] {pergunta}")
        resultado = Runner.run_sync(atendente, pergunta)
        print(f"[resposta] {resultado.final_output}")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    main()