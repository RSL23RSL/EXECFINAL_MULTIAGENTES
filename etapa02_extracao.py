"""
ETAPA 2 -- Extração estruturada do pedido (15 min) e 🆕 A -- votação em paralelo (OPCIONAL, bônus).

ESQUELETO: implemente as etapas na ordem (troque cada raise NotImplementedError pelo código da etapa).
  ETAPA 2.1 -- complete o modelo Pydantic `Pedido` (campos + Field(description=...))
  ETAPA 2.2 -- criar_extrator(): um Agent com output_type=Pedido
  ETAPA 2.3 -- extrair(): roda UM extrator e devolve um Pedido
  --- daqui para baixo é OPCIONAL (item 🆕 A, vale bônus). Pule se estiver sem tempo: o resto do sistema não depende dele.
  🆕 A.1    -- INSTRUCOES_VOTANTES: 3 instruções ligeiramente diferentes
  🆕 A.2    -- extrair_com_votacao(): os 3 extratores AO MESMO TEMPO (asyncio.gather)
  (PRONTO)  -- votar(): maioria por campo; sem maioria em tipo/datas -> divergencia=True
  (PRONTO)  -- no __main__: o tempo em paralelo x em sequência

REFERÊNCIAS NAS AULAS
  aula2/agente_output.py                   output_type com um BaseModel simples
  aula2/agente_output2.py                  Enum + listas + Field(description=...)          <- o mais parecido
  aula7/exemplos/08_paralelismo/main.py    🆕 A: o CONCEITO de paralelismo (lá: tarefas DIFERENTES para ganhar tempo;
                                           aqui: a MESMA tarefa 3 vezes para ganhar confiabilidade)
  aula3/agente_parada3.py                  Runner.run (assíncrono) dentro de asyncio, como em A.2
  aula3/agente_retry.py                    por que a data de hoje entra nas instruções (já feito abaixo, com texto_hoje())

Rodar:
    python etapa02_extracao.py            # extrai C1, C2, C5 e C11
    python etapa02_extracao.py --votacao  # 🆕 A: C1, C2 e C9 com 3 votos e o tempo medido

Pronto quando: C2 sai com dias_vendidos=10, C11 com tipo_destino="exterior", C5 com matricula=None;
               na votação, C1/C2 unânimes e C9 mostrando os votos.
"""
import asyncio
import sys
import time
from collections import Counter
from enum import Enum

from agents import Agent, Runner
from pydantic import BaseModel, Field

from dados.casos import CASOS
from etapa04_ferramentas import texto_hoje
from provedor import configurar

MODELO = configurar()


class TipoPedido(str, Enum):
    FERIAS = "ferias"
    ABONO = "abono"
    DIARIA = "diaria"
    LICENCA_SAUDE = "licenca_saude"
    OUTRO = "outro"


class TipoDestino(str, Enum):
    CAPITAL = "capital"
    INTERIOR = "interior"
    EXTERIOR = "exterior"


class Pedido(BaseModel):
    # ETAPA 2.1 -- campos do pedido. A description de cada um é a "instrução" que o LLM lê para preenchê-lo.
    tipo: TipoPedido = Field(description=(
        "Tipo do pedido: 'ferias' (descanso anual, pode incluir venda de dias), 'abono' (folga de 1 dia útil), "
        "'diaria' (viagem a serviço), 'licenca_saude' (afastamento por doença) ou 'outro'."))

    matricula: str | None = Field(description=(
        "Matrícula do servidor, com 4 dígitos (ex.: '1002'). "
        "Use null se o servidor NÃO informou a matrícula no texto; nunca invente."))

    data_inicio: str | None = Field(description=(
        "Data de início do pedido no formato AAAA-MM-DD. "
        "Converta datas relativas ('amanhã', 'próxima segunda') usando a data de hoje informada nas instruções. "
        "Use null se nenhuma data foi informada."))

    data_fim: str | None = Field(description=(
        "Data de término do pedido no formato AAAA-MM-DD (último dia, inclusive). "
        "No abono, é igual à data_inicio, pois é um único dia. "
        "Use null se não for possível determinar."))

    dias_vendidos: int = Field(default=0, ge=0, le=10, description=(
        "Quantidade de dias de férias que o servidor quer VENDER (abono pecuniário, regra N2), de 0 a 10. "
        "Preencha só se o servidor pedir explicitamente para vender dias; caso contrário, 0."))

    destino: str | None = Field(description=(
        "Cidade de destino da viagem. Só para pedidos do tipo 'diaria'; nos demais tipos, null."))

    tipo_destino: TipoDestino | None = Field(description=(
        "Classificação do destino da diária: 'capital' (capital do estado), 'interior' (outra cidade do país) "
        "ou 'exterior' (fora do Brasil). Só para 'diaria'; nos demais tipos, null."))

    justificativa: str = Field(description=(
        "Resumo curto, em português, do motivo do pedido. "
        "NÃO inclua dados de saúde (doença, CID, diagnóstico, sintomas); em licença de saúde, escreva apenas "
        "'motivo de saúde'. Se não houver motivo no texto, descreva o pedido em poucas palavras."))


def criar_extrator(instrucoes: str, input_guardrails: list | None = None) -> Agent:
    # ETAPA 2.2 -- agente que devolve um Pedido estruturado (os guardrails só entram na Etapa 3)
    return Agent(
        name="Extrator",
        instructions=instrucoes,
        output_type=Pedido,
        input_guardrails=input_guardrails or [],
        model=MODELO,
    )


INSTRUCOES_EXTRATOR = (
    f"Hoje é {texto_hoje()}. "  # (PRONTO) a data real: o modelo não tem relógio (aula3/agente_retry.py)
    "Você extrai pedidos de servidores para o RH (férias, abono ou diária). "
    "Leia o texto do servidor e preencha os campos do pedido. "
    "Escreva todas as datas no formato AAAA-MM-DD, convertendo datas relativas com base na data de hoje. "
    "Não invente nada que não foi dito: se uma informação não aparece no texto (matrícula, datas, destino), use null. "
    "Preencha dias_vendidos só se o servidor pedir explicitamente para vender dias de férias; caso contrário, 0. "
    "Na justificativa, nunca inclua dados de saúde."
)


def extrair(texto: str) -> Pedido:
    # ETAPA 2.3 -- roda UM extrator; final_output já é um objeto Pedido, não texto
    resultado = Runner.run_sync(criar_extrator(INSTRUCOES_EXTRATOR), texto)
    return resultado.final_output


# ------------------------------------------------------------------ 🆕 A: votação (OPCIONAL, bônus)
# Para ligar no grafo depois de pronto: USAR_VOTACAO = True em etapa07_grafo.py.
# 🆕 A.1 -- três instruções LIGEIRAMENTE diferentes para a MESMA tarefa.
INSTRUCOES_VOTANTES: list[str] = [
    # 1) literal: só o que está escrito
    f"Hoje é {texto_hoje()}. "
    "Você extrai pedidos de servidores para o RH. Seja estritamente literal: registre apenas o que está "
    "escrito no texto, sem deduzir nada. Datas em AAAA-MM-DD; o que não foi dito vai como null. "
    "dias_vendidos só se o servidor pedir explicitamente para vender dias; senão, 0. "
    "Na justificativa, nunca inclua dados de saúde.",

    # 2) confere as datas contra o calendário
    f"Hoje é {texto_hoje()}. "
    "Você extrai pedidos de servidores para o RH. Dê atenção especial às datas: converta expressões relativas "
    "('amanhã', 'semana que vem', 'dia 10') usando a data de hoje, confira o dia da semana e o número de dias "
    "no calendário, e garanta que data_fim não seja anterior a data_inicio. Datas em AAAA-MM-DD; "
    "se não der para determinar uma data com segurança, use null. "
    "dias_vendidos só se pedido explicitamente; senão, 0. Na justificativa, nunca inclua dados de saúde.",

    # 3) pensa como o RH
    f"Hoje é {texto_hoje()}. "
    "Você é um analista experiente de RH registrando o pedido de um servidor. Identifique o tipo de pedido "
    "como o RH classificaria (férias, abono de 1 dia, diária de viagem, licença de saúde ou outro) e "
    "preencha os campos como um formulário oficial. Datas em AAAA-MM-DD; informação ausente vai como null, "
    "sem suposições. Venda de dias (dias_vendidos) só quando o servidor pede explicitamente; senão, 0. "
    "Na justificativa, nunca inclua dados de saúde.",
]


async def extrair_com_votacao(texto: str) -> tuple[Pedido, bool, list[Pedido]]:
    # 🆕 A.2 -- os 3 extratores AO MESMO TEMPO (fan-out), depois a votação (fan-in)
    extratores = [criar_extrator(instrucoes) for instrucoes in INSTRUCOES_VOTANTES]
    resultados = await asyncio.gather(*(Runner.run(e, texto) for e in extratores))
    votos = [r.final_output for r in resultados]
    pedido_final, divergencia = votar(votos)
    return pedido_final, divergencia, votos


def votar(votos: list[Pedido]) -> tuple[Pedido, bool]:
    """(PRONTO) Maioria por campo. Sem maioria (2 de 3) em `tipo` ou nas datas -> divergencia=True: o sistema vai
    pedir esclarecimento em vez de adivinhar. Os campos não votados vêm do primeiro voto."""
    decidido, divergencia = {}, False
    for campo in ("tipo", "matricula", "data_inicio", "data_fim", "dias_vendidos"):
        valor, quantos = Counter(getattr(voto, campo) for voto in votos).most_common(1)[0]
        decidido[campo] = valor
        if quantos < 2 and campo in ("tipo", "data_inicio", "data_fim"):
            divergencia = True
    return votos[0].model_copy(update=decidido), divergencia


def _demo_extracao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C5_sem_matricula", "C11_diaria_exterior"):
        pedido = extrair(CASOS[nome]["pedido"])
        print(f"\n{nome}\n  {pedido.model_dump()}")


def _demo_votacao() -> None:
    for nome in ("C1_abono_simples", "C2_ferias_com_venda", "C9_divergencia"):
        texto = CASOS[nome]["pedido"]
        inicio = time.perf_counter()
        pedido, divergencia, votos = asyncio.run(extrair_com_votacao(texto))
        segundos = time.perf_counter() - inicio
        print(f"\n{nome}  ({segundos:.1f}s, divergencia={divergencia})")
        for i, voto in enumerate(votos, 1):
            print(f"  voto {i}: tipo={voto.tipo.value} {voto.data_inicio}..{voto.data_fim} vende={voto.dias_vendidos}")
        print(f"  decisão: {pedido.model_dump()}")
    # (PRONTO) os mesmos 3 extratores EM SEQUÊNCIA, para comparar: o paralelo fica perto do tempo de UMA chamada?
    texto = CASOS["C2_ferias_com_venda"]["pedido"]
    inicio = time.perf_counter()
    for instrucoes in INSTRUCOES_VOTANTES:
        Runner.run_sync(criar_extrator(instrucoes), texto)
    print(f"\nC2 em sequência: {time.perf_counter() - inicio:.1f}s (compare com o tempo do C2 em paralelo, acima)")


if __name__ == "__main__":
    print(f"[modelo] {MODELO}")
    _demo_votacao() if "--votacao" in sys.argv else _demo_extracao()