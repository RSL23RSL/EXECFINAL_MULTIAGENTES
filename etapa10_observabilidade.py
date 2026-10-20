"""
ETAPA 10 -- Observabilidade (15 min): onde o tempo foi gasto e quanto custou, por nó do grafo.

ESQUELETO:
  ETAPA 10.2 -- medido(): embrulha um nó, mede o tempo e grava uma linha em saidas/metricas.jsonl
  (PRONTO)   -- resumo(): nós percorridos, tempo total, nó mais lento e tokens totais de uma execução
  (ETAPA 10.1 fica em etapa10_governanca.py: o hook do 🆕 B ganha um segundo papel, registrar)

Até você fazer a 10.2, medido() devolve o nó sem mudar nada: o grafo funciona igual.

REFERÊNCIAS NAS AULAS
  aula5/exemplos/11_observabilidade/agente_observavel.py        ler o que aconteceu numa execução (result.new_items)
  aula3/agente_hook2.py, aula3/agente_hook3.py                  RunHooks para enxergar o loop do agente
  aula8/exemplos/03_observabilidade/1_codigo_pronto/passo1_trace.py   trace e spans (o Langfuse do passo 2 é opcional)

Rodar:
    python etapa10_observabilidade.py <thread_id>     # as linhas de métrica da execução e o resumo
"""
import functools
import json
import sys
import threading
import time

from dados_rh import SAIDAS

ARQUIVO_METRICAS = SAIDAS / "metricas.jsonl"

# ------------------------------------------------------------------ contador de tokens por nó
# Alguns nós chamam o LLM por dentro de funções de outras etapas (proteger_entrada -> nota_escopo, extrair -> extrair()),
# que só devolvem o resultado, sem os tokens. Para medir esses nós também, contamos os tokens de TODA execução de
# agente que acontece enquanto o nó roda. O contador é por thread: os ramos paralelos do grafo rodam em threads
# diferentes e não se misturam.
_contador = threading.local()


def _instalar_contador() -> None:
    """Envolve AgentRunner.run (por onde passam Runner.run e Runner.run_sync) para somar os tokens de cada execução."""
    try:
        from agents.run import AgentRunner
    except ImportError:  # versão do SDK sem AgentRunner: os nós ainda podem informar "tokens" por conta própria
        return
    if getattr(AgentRunner.run, "_contando_tokens", False):
        return
    original = AgentRunner.run

    @functools.wraps(original)
    async def run_contando(self, *args, **kwargs):
        resultado = await original(self, *args, **kwargs)
        uso = getattr(getattr(resultado, "context_wrapper", None), "usage", None)
        if uso is not None and hasattr(_contador, "tokens"):
            _contador.tokens += getattr(uso, "total_tokens", 0) or 0
        return resultado

    run_contando._contando_tokens = True
    AgentRunner.run = run_contando


_instalar_contador()


def medido(nome: str, no):
    """ETAPA 10.2 -- embrulha um nó: mede o tempo, grava UMA linha em ARQUIVO_METRICAS e devolve o MESMO dicionário.

    Formato da linha: {"thread_id", "no", "segundos"} + "tokens" (se o nó usou o LLM) + "fonte_feriados" (se informou).
    Se o nó levantar exceção (inclusive o interrupt() da chefia, que pausa o grafo), nada é gravado e a exceção sobe
    intacta: o LangGraph precisa recebê-la para pausar. Na retomada o nó roda de novo e aí, sim, é medido.
    """
    @functools.wraps(no)
    def no_medido(estado):
        _contador.tokens = 0
        inicio = time.perf_counter()
        try:
            saida = no(estado)
        finally:
            segundos = round(time.perf_counter() - inicio, 2)
            tokens = _contador.tokens
            del _contador.tokens

        linha = {"thread_id": estado.get("thread_id"), "no": nome, "segundos": segundos}
        if isinstance(saida, dict):
            tokens = tokens or saida.get("tokens") or 0   # o contador vale mais; o que o nó informou é o plano B
            if tokens:
                linha["tokens"] = tokens
            if saida.get("fonte_feriados"):
                linha["fonte_feriados"] = saida["fonte_feriados"]

        ARQUIVO_METRICAS.parent.mkdir(parents=True, exist_ok=True)
        with ARQUIVO_METRICAS.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(linha, ensure_ascii=False) + "\n")
        return saida

    return no_medido


def linhas_da_execucao(thread_id: str) -> list[dict]:
    """As linhas de ARQUIVO_METRICAS de uma execução, na ordem em que foram gravadas."""
    if not ARQUIVO_METRICAS.exists():
        return []
    linhas = [json.loads(l) for l in ARQUIVO_METRICAS.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [l for l in linhas if l.get("thread_id") == thread_id]


def resumo(thread_id: str) -> dict:
    """(PRONTO) Junta as linhas de ARQUIVO_METRICAS de uma execução. Só funciona depois que o medido() (10.2) grava."""
    if not ARQUIVO_METRICAS.exists():
        return {"erro": "saidas/metricas.jsonl ainda não existe: faça a ETAPA 10.2 e rode o grafo"}
    linhas = [json.loads(l) for l in ARQUIVO_METRICAS.read_text(encoding="utf-8").splitlines() if l.strip()]
    linhas = [l for l in linhas if l.get("thread_id") == thread_id]
    if not linhas:
        return {"erro": f"nenhuma métrica com thread_id={thread_id!r}"}
    lento = max(linhas, key=lambda l: l.get("segundos", 0))
    return {"nos": [l.get("no") for l in linhas],
            "segundos_total": round(sum(l.get("segundos", 0) for l in linhas), 2),
            "mais_lento": (lento.get("no"), lento.get("segundos")),
            "tokens_total": sum(l.get("tokens", 0) or 0 for l in linhas)}


if __name__ == "__main__":
    for linha in linhas_da_execucao(sys.argv[1]):
        print(json.dumps(linha, ensure_ascii=False))
    print()
    print(json.dumps(resumo(sys.argv[1]), ensure_ascii=False, indent=2))