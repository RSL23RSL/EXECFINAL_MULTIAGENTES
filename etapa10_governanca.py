"""
🆕 B (OPCIONAL, bônus) -- Hooks para CONTROLAR, não só para observar. E ETAPA 10.1 (obrigatória): o hook que registra.

Sem tempo? Pule os itens 🆕 B: a classe Governanca já funciona como hook "só observador" (conta as chamadas) e a
Etapa 10.1 usa este mesmo arquivo.

Conceito que você já conhece: em aula3/agente_hook2.py e aula3/agente_loop.py os RunHooks só IMPRIMIAM
("turno 2", "chamou a ferramenta X"). Contexto novo: o mesmo gancho roda ANTES de cada tool (on_tool_start) e
ANTES de cada chamada ao modelo (on_llm_start) -- então ele pode BARRAR a execução. Não há exemplo pronto disto.

ESQUELETO:
  🆕 B.1 (opcional) -- PERMISSOES: quais tools cada agente pode chamar
  🆕 B.2 (opcional) -- on_tool_start: tool fora da lista do agente OU orçamento de tools estourado -> LimiteExcedido
  🆕 B.3 (opcional) -- on_llm_start: orçamento de chamadas ao modelo estourado -> LimiteExcedido
  ETAPA 10.1 -- on_tool_end / on_agent_end: registre tool, argumentos, resultado e tokens (o MESMO hook, outro papel)

REFERÊNCIAS NAS AULAS
  aula3/agente_hook2.py, aula3/agente_hook3.py   a assinatura dos métodos de RunHooks (on_llm_start, on_tool_start...)
  aula3/agente_loop.py                           o hook contando turnos e tools do loop do agente
  aula8/exemplos/06_excessive_agency/1_codigo_pronto/main.py   o risco que a lista de permissões evita

Por que funciona: o SDK chama on_tool_start ANTES de executar a tool. Uma exceção levantada ali interrompe o
Runner e a tool NÃO roda. Trate LimiteExcedido em volta do Runner (etapa06_linear.py). Dois detalhes do SDK:
  1. LimiteExcedido herda de AgentsException. Se herdasse de Exception, o SDK a embrulharia num UserError
     ("Error running tool ...") e o seu `except LimiteExcedido` não a pegaria.
  2. Dentro de um especialista chamado via as_tool, o SDK, por padrão, transforma QUALQUER erro em uma mensagem
     de texto para o Coordenador, e a execução continua: o bloqueio seria engolido. Por isso, em
     agentes.criar_coordenador(), as as_tool recebem failure_error_function=None (o erro sobe de verdade).
"""
from agents import AgentsException, RunHooks

TAMANHO_RESULTADO = 300  # ETAPA 10.1: o resultado de uma tool é truncado no registro (não guardamos tudo)


class LimiteExcedido(AgentsException):
    """Levantada pelo hook quando um agente sai do que lhe é permitido."""


# 🆕 B.1 -- agente -> conjunto de nomes de tools permitidas (PRIVILÉGIO MÍNIMO, Etapa 9.1).
#   Os especialistas usam as tools de etapa06_agentes.py; o Coordenador só chama os especialistas (os tool_name das as_tool).
#   O salário (consultar_remuneracao) só pode passar pelo Financeiro.
PERMISSOES: dict[str, set[str]] = {
    "Normas": {"consultar_normas"},
    "Escala": {"consultar_escala"},
    "Financeiro": {"tabela_diarias", "consultar_remuneracao", "cotacao_dolar"},
    "Coordenador": {"parecer_normas", "parecer_escala", "parecer_financeiro"},
}


class Governanca(RunHooks):
    def __init__(self, max_tools: int = 6, max_llm: int = 12, verbose: bool = True):
        self.max_tools, self.max_llm, self.verbose = max_tools, max_llm, verbose
        self.tools_chamadas = 0
        self.chamadas_llm = 0
        self.eventos: list[dict] = []  # ETAPA 10.1: o que aconteceu, para gravar em saidas/metricas.jsonl

    def _log(self, texto: str) -> None:
        if self.verbose:
            print(f"[governança] {texto}")

    async def on_tool_start(self, context, agent, tool) -> None:
        """🆕 B.2 -- roda ANTES da tool: levantar aqui impede a execução."""
        self.tools_chamadas += 1
        permitidas = PERMISSOES.get(agent.name, set())
        if tool.name not in permitidas:
            self._log(f"{agent.name} -> {tool.name}: BLOQUEADO (fora da lista de permissões)")
            self.eventos.append({"evento": "bloqueio", "agente": agent.name, "tool": tool.name,
                                 "motivo": "tool não permitida"})
            raise LimiteExcedido(f"{agent.name} não pode usar {tool.name}")
        if self.tools_chamadas > self.max_tools:
            self._log(f"{agent.name} -> {tool.name}: BLOQUEADO (orçamento {self.tools_chamadas} de {self.max_tools})")
            self.eventos.append({"evento": "bloqueio", "agente": agent.name, "tool": tool.name,
                                 "motivo": "orçamento de tools"})
            raise LimiteExcedido(f"orçamento de tools estourado ({self.tools_chamadas} de {self.max_tools})")
        self._log(f"{agent.name} -> {tool.name}: OK ({self.tools_chamadas}/{self.max_tools})")

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        """🆕 B.3 -- roda ANTES de cada chamada ao modelo."""
        self.chamadas_llm += 1
        if self.chamadas_llm > self.max_llm:
            self.eventos.append({"evento": "bloqueio", "agente": agent.name, "motivo": "orçamento de LLM"})
            raise LimiteExcedido(f"orçamento de chamadas ao modelo estourado ({self.chamadas_llm} de {self.max_llm})")

    async def on_tool_end(self, context, agent, tool, result) -> None:
        """ETAPA 10.1 -- registra a tool executada, os argumentos e o resultado (truncado)."""
        resultado = str(result)
        if len(resultado) > TAMANHO_RESULTADO:
            resultado = resultado[:TAMANHO_RESULTADO] + "..."
        self.eventos.append({
            "evento": "tool",
            "agente": agent.name,
            "tool": tool.name,
            "argumentos": getattr(context, "tool_arguments", None),  # texto JSON quando é uma function_tool
            "resultado": resultado,
        })

    async def on_agent_end(self, context, agent, output) -> None:
        """ETAPA 10.1 -- registra os tokens consumidos até aqui."""
        uso = getattr(context, "usage", None)
        self.eventos.append({
            "evento": "agente_fim",
            "agente": agent.name,
            "tokens": getattr(uso, "total_tokens", None),
            "tokens_entrada": getattr(uso, "input_tokens", None),
            "tokens_saida": getattr(uso, "output_tokens", None),
            "chamadas_llm": self.chamadas_llm,
            "tools_chamadas": self.tools_chamadas,
        })