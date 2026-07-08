#!/usr/bin/env python3
"""
Monitor Bac Bo - Estratégias de padrão + Gale + Sinais Telegram
Baseado no bacbo_final.py (WebSocket) + sistema de sinais do BacBo-Telegram-Signals
"""

import asyncio
import json
import urllib.request
import websockets
from datetime import datetime
import sys

TELEGRAM_TOKEN   = "8781120274:AAEAG_m4eaL5mLo_LURVZ-rKiuuesJlurlQ"
TELEGRAM_CHAT_ID = "-1003948108220"

# ─── Cores do terminal ────────────────────────────────────────────────────────
P   = "\033[94m"
B   = "\033[91m"
T   = "\033[93m"
G   = "\033[92m"
RST = "\033[0m"

# ─── Configurações ────────────────────────────────────────────────────────────
MAX_GALES = 2          # Quantas tentativas de gale antes de declarar derrota
STAKE_MINIMA = 2.50    # Valor mínimo de qualquer entrada (também o valor de reset após loss)

# ─── TIE: multiplicador oficial do Bac Bo por soma dos dados ─────────────────
TIE_MULTIPLICADORES = {
    2: 88, 12: 88,
    3: 25, 11: 25,
    4: 10, 10: 10,
    5: 6,  9: 6,
    6: 4,  7: 4, 8: 4,
}
TIE_MULTIPLICADOR_PADRAO = 4   # fallback conservador se não conseguir ler a soma no JSON
TIE_SIDE_BET_RATIO = 0.10      # 10% do stake principal vai de "seguro" pro TIE
TIE_MIN_BET = 0.50             # aposta mínima de mesa pro TIE — abaixo disso, pula
TIE_PROTECAO_PERDA = 0.10      # se sair TIE e você tinha apostado em P/B, perde 10% (regra real)


def multiplicador_tie(soma):
    """Retorna o multiplicador oficial do TIE para uma soma de dados (2-12)."""
    if soma is None:
        return TIE_MULTIPLICADOR_PADRAO
    return TIE_MULTIPLICADORES.get(soma, TIE_MULTIPLICADOR_PADRAO)


def extrair_soma_tie(args):
    """
    Tenta descobrir a soma dos dados (2-12) num resultado de TIE, testando os
    nomes de campo mais comuns que casas costumam usar no JSON. Se não achar,
    retorna None (o bot usa o multiplicador padrão como fallback).
    """
    for campo in ('total', 'sum', 'tieTotal', 'value'):
        if campo in args:
            try:
                return int(args[campo])
            except (TypeError, ValueError):
                pass

    for c1, c2 in (('playerDice1', 'playerDice2'), ('player1', 'player2'), ('dice1', 'dice2')):
        if c1 in args and c2 in args:
            try:
                return int(args[c1]) + int(args[c2])
            except (TypeError, ValueError):
                pass

    for campo in ('playerTotal', 'playerScore', 'playerSum'):
        if campo in args:
            try:
                return int(args[campo])
            except (TypeError, ValueError):
                pass

    return None


# ─── Banca (lucro hipotético seguindo os sinais) ──────────────────────────────
class Banca:
    """
    Simula o saldo de quem seguiu TODAS as entradas sugeridas pelo bot.

    Progressão "deixa rolar": toda entrada nova começa em STAKE_MINIMA.
    Se ganhar, a PRÓXIMA entrada usa stake + lucro daquela rodada (cresce).
    Se perder (ou tomar um TIE sem proteção viável), a próxima entrada
    volta pro mínimo.
    """
    def __init__(self, inicial=None):
        self.inicial = inicial if inicial is not None else 0.0
        self.saldo = self.inicial
        self.proxima_stake = STAKE_MINIMA
        self.configurada = inicial is not None

    def configurar(self, inicial):
        self.inicial = inicial
        self.saldo = inicial
        self.proxima_stake = STAKE_MINIMA
        self.configurada = True

    def registrar_resultado(self, lucro_rodada, resetar):
        self.saldo += lucro_rodada
        if resetar:
            self.proxima_stake = STAKE_MINIMA
        else:
            self.proxima_stake = max(round(self.proxima_stake + lucro_rodada, 2), STAKE_MINIMA)

    def lucro(self):
        return round(self.saldo - self.inicial, 2)

    def mensagem(self):
        if not self.configurada:
            return "💰 Banca não configurada. Use /banca <valor> no Telegram."
        sinal = "+" if self.lucro() >= 0 else ""
        return (
            f"💰 <b>BANCA (hipotética)</b>\n"
            f"Inicial: R${self.inicial:.2f}\n"
            f"Atual: R${self.saldo:.2f}\n"
            f"Lucro: {sinal}R${self.lucro():.2f}\n"
            f"Próxima entrada: R${self.proxima_stake:.2f}"
        )


# ─── Comandos via Telegram (long polling) ─────────────────────────────────────
def telegram_get_updates(offset):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?timeout=25&offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read()).get("result", [])
    except Exception as e:
        print(f"  ⚠️ Erro ao buscar comandos do Telegram: {e}")
        return []


async def escutar_comandos(banca):
    """Roda em paralelo ao monitor, escutando /banca e /lucro no Telegram."""
    offset = 0
    while True:
        updates = await asyncio.to_thread(telegram_get_updates, offset)
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message", {})
            texto = msg.get("text", "").strip()

            if texto.startswith("/banca"):
                partes = texto.split()
                try:
                    valor_banca = float(partes[1])
                    banca.configurar(valor_banca)

                    if len(partes) > 2:
                        stake_desejada = float(partes[2])
                        if stake_desejada < STAKE_MINIMA:
                            enviar_telegram(
                                f"⚠️ Stake mínima é R${STAKE_MINIMA:.2f}. "
                                f"Usando R${STAKE_MINIMA:.2f} em vez de R${stake_desejada:.2f}."
                            )
                            banca.proxima_stake = STAKE_MINIMA
                        else:
                            banca.proxima_stake = stake_desejada

                    enviar_telegram(
                        f"✅ Banca configurada!\n"
                        f"Inicial: R${banca.inicial:.2f}\n"
                        f"Próxima entrada: R${banca.proxima_stake:.2f}"
                    )
                except (IndexError, ValueError):
                    enviar_telegram(
                        "⚠️ Uso: <code>/banca 500</code> ou <code>/banca 500 10</code>\n"
                        f"(500 = banca inicial, 10 = valor de partida da stake — opcional, "
                        f"mínimo R${STAKE_MINIMA:.2f})"
                    )

            elif texto.startswith("/lucro"):
                enviar_telegram(banca.mensagem())

        await asyncio.sleep(0.5)

# Estratégias de padrão: se os últimos resultados baterem com 'pattern', aposta em 'bet'
# 'P' = Player, 'B' = Banker, 'T' = Tie
STRATEGIES = [
    {'pattern': ['P', 'P', 'P'], 'bet': 'B'},
    {'pattern': ['B', 'B', 'B'], 'bet': 'P'},
    {'pattern': ['B', 'B', 'P'], 'bet': 'P'},
    {'pattern': ['P', 'P', 'B'], 'bet': 'B'},
]

# Emojis
EMOJI = {'P': '🔵', 'B': '🔴', 'T': '🟡'}
NOME  = {'P': 'PLAYER', 'B': 'BANKER', 'T': 'TIE'}


# ─── Telegram ─────────────────────────────────────────────────────────────────
def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        d = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"}),
            timeout=5,
        )
        print(f"  📤 Telegram: {msg[:60]}...")
    except Exception as e:
        print(f"  ⚠️ Erro Telegram: {e}")


# ─── Placar ───────────────────────────────────────────────────────────────────
class Placar:
    def __init__(self):
        self.wins = 0
        self.losses = 0
        self.sequencia = 0
        self.total = 0

    def win(self):
        self.wins += 1
        self.sequencia += 1
        self.total += 1

    def loss(self):
        self.losses += 1
        self.sequencia = 0
        self.total += 1

    def taxa(self):
        if self.total == 0:
            return 0.0
        return round((self.wins / self.total) * 100, 1)

    def mensagem(self):
        return (
            f"📊 <b>PLACAR</b>\n"
            f"✅ Wins: {self.wins}  ❌ Losses: {self.losses}\n"
            f"🔥 Sequência: {self.sequencia}\n"
            f"🎯 Assertividade: {self.taxa()}%"
        )


# ─── Estratégia ───────────────────────────────────────────────────────────────
class Estrategia:
    def __init__(self):
        self.reset()

    def reset(self, aguardar=False):
        self.ativa = False           # Tem aposta em andamento?
        self.aposta = None           # 'P' ou 'B'
        self.gales = 0               # Gales usados
        self.stake_atual = None      # valor apostado nessa rodada (definido na entrada)
        self.aguardar = aguardar     # Pula 1 rodada após resultado
        self.preparando = False      # Mandou mensagem de "prepare-se"?

    def verificar_prepare(self, historico):
        """Retorna (mensagem_prepare, aposta_confirmada) ou (None, None)"""
        for s in STRATEGIES:
            pat = s['pattern']
            bet = s['bet']
            # Penúltimo passo do padrão (avisa que pode entrar)
            if historico[-(len(pat)-1):] == pat[:len(pat)-1]:
                if not self.preparando:
                    return ('prepare', bet)
            # Padrão completo → entrada confirmada
            if historico[-len(pat):] == pat:
                return ('entrada', bet)
        return (None, None)

    def processar_resultado(self, resultado, placar, banca=None, soma_tie=None):
        """
        Recebe o resultado da rodada ('P', 'B' ou 'T').
        Retorna (status, info) onde status é: 'win', 'tie_win', 'tie_protegido',
        'gale', 'loss', ou (None, None) se não havia entrada ativa.
        """
        if not self.ativa:
            return None, None

        stake = self.stake_atual

        if resultado == 'T':
            return self._processar_tie(stake, placar, banca, soma_tie)

        if resultado == self.aposta:
            lucro = stake  # paga 1:1
            placar.win()
            if banca:
                banca.registrar_resultado(lucro, resetar=False)
            self.reset(aguardar=True)
            return 'win', {'lucro': lucro}

        # Errou o lado apostado
        if banca:
            banca.registrar_resultado(-stake, resetar=False)  # ainda pode ter mais gale
        self.gales += 1
        if self.gales >= MAX_GALES:
            placar.loss()
            if banca:
                banca.proxima_stake = STAKE_MINIMA  # loss confirmado -> reseta progressão
            self.reset(aguardar=True)
            return 'loss', {'perda': stake}

        self.stake_atual = stake * 2  # dobra pro próximo gale
        return 'gale', {'proxima_stake': self.stake_atual}

    def _processar_tie(self, stake, placar, banca, soma_tie):
        """
        TIE encerra a rodada de qualquer forma (não continua esperando gale).
        Se a aposta de proteção (10% do stake) for viável (>= aposta mínima
        de mesa), aplica o multiplicador real do TIE. Se não for viável
        (banca baixa), só aplica a perda de 10% da regra padrão do Bac Bo.
        """
        tie_stake = round(stake * TIE_SIDE_BET_RATIO, 2)

        if tie_stake >= TIE_MIN_BET:
            mult = multiplicador_tie(soma_tie)
            ganho_tie = round(tie_stake * (mult - 1), 2)
            perda_protecao = round(stake * TIE_PROTECAO_PERDA, 2)
            lucro = round(ganho_tie - perda_protecao, 2)
            placar.win()
            if banca:
                banca.registrar_resultado(lucro, resetar=False)
            self.reset(aguardar=True)
            return 'tie_win', {
                'lucro': lucro, 'mult': mult, 'soma': soma_tie,
                'tie_stake': tie_stake,
            }
        else:
            perda_protecao = round(stake * TIE_PROTECAO_PERDA, 2)
            placar.loss()
            if banca:
                banca.registrar_resultado(-perda_protecao, resetar=True)
            self.reset(aguardar=True)
            return 'tie_protegido', {'perda': perda_protecao, 'tie_stake': tie_stake}


# ─── Conversão de winner para letra ───────────────────────────────────────────
def winner_para_letra(winner):
    if winner == 'Player':
        return 'P'
    elif winner == 'Banker':
        return 'B'
    else:
        return 'T'


# ─── Monitor principal ────────────────────────────────────────────────────────
async def monitor(ws_url, banca):
    headers = {
        "Origin": "https://www.5gbet.com",
        "User-Agent": "Mozilla/5.0",
    }

    historico_letras = []   # Lista de 'P', 'B', 'T'
    ultimo_resultado  = None
    soma_tie_pendente = None  # soma dos dados do último TIE (se conseguimos extrair)
    placar     = Placar()
    estrategia = Estrategia()

    try:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            print(f"{G}✅ Conectado ao WebSocket!{RST}\n")
            enviar_telegram("✅ <b>Monitor Bac Bo iniciado!</b>\nAguardando padrões...")

            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    tipo = data.get("type", "")

                    # ── Carrega histórico inicial ──────────────────────────────
                    if tipo == "bacbo.road":
                        hist = data["args"].get("history", [])
                        historico_letras = [winner_para_letra(r['winner']) for r in hist]
                        s = data["args"].get("stats", {})
                        print(
                            f"📊 Histórico carregado: {len(historico_letras)} rodadas | "
                            f"P:{s.get('playerWins',0)} B:{s.get('bankerWins',0)} T:{s.get('ties',0)}"
                        )
                        print(f"   Últimas 10: {' '.join(historico_letras[-10:])}\n")

                    # ── Nova rodada ────────────────────────────────────────────
                    elif tipo == "bacbo.playerState":
                        g = data.get("args", {}).get("game", {})

                        if g.get("stage") == "WaitingForBets" and len(historico_letras) > 0:
                            r = historico_letras[-1] if historico_letras else None
                            chave = f"{r}{len(historico_letras)}"

                            if chave == ultimo_resultado:
                                continue
                            ultimo_resultado = chave

                            h = datetime.now().strftime("%H:%M:%S")
                            ultimo = historico_letras[-1]
                            print(f"[{h}] {EMOJI[ultimo]} {ultimo}  |  Histórico: {' '.join(historico_letras[-8:])}")

                            # ── Aguardando após resultado (skip 1 rodada) ──────
                            if estrategia.aguardar:
                                estrategia.aguardar = False
                                print(f"  ⏭️  Pulando rodada de descanso\n")
                                continue

                            # ── Processa resultado se havia aposta ativa ───────
                            if estrategia.ativa:
                                status, info = estrategia.processar_resultado(
                                    ultimo, placar, banca,
                                    soma_tie=soma_tie_pendente if ultimo == 'T' else None
                                )
                                if ultimo == 'T':
                                    soma_tie_pendente = None  # consumido

                                if status == 'win':
                                    msg_win = (
                                        f"✅ <b>GREEN!</b> {EMOJI[ultimo]}\n"
                                        f"💵 Lucro: +R${info['lucro']:.2f}\n"
                                        f"🕐 {h}\n\n"
                                        f"{placar.mensagem()}\n\n"
                                        f"{banca.mensagem()}"
                                    )
                                    print(f"  {G}✅ WIN! +R${info['lucro']:.2f}{RST}")
                                    enviar_telegram(msg_win)

                                elif status == 'tie_win':
                                    soma_txt = info['soma'] if info['soma'] is not None else "?"
                                    msg_tie = (
                                        f"🟡 <b>TIE!</b> Proteção pagou!\n"
                                        f"🎲 Soma: {soma_txt} → {info['mult']}x\n"
                                        f"💵 Lucro: +R${info['lucro']:.2f}\n"
                                        f"🕐 {h}\n\n"
                                        f"{placar.mensagem()}\n\n"
                                        f"{banca.mensagem()}"
                                    )
                                    print(f"  {T}🟡 TIE-WIN! Soma {soma_txt} ({info['mult']}x) → +R${info['lucro']:.2f}{RST}")
                                    enviar_telegram(msg_tie)

                                elif status == 'tie_protegido':
                                    msg_tie_prot = (
                                        f"🟡 <b>TIE</b> (proteção pulada — stake baixo)\n"
                                        f"💵 Perda: -R${info['perda']:.2f} (10% padrão)\n"
                                        f"🕐 {h}\n\n"
                                        f"{placar.mensagem()}\n\n"
                                        f"{banca.mensagem()}"
                                    )
                                    print(f"  {T}🟡 TIE sem proteção viável. -R${info['perda']:.2f}{RST}")
                                    enviar_telegram(msg_tie_prot)

                                elif status == 'loss':
                                    msg_loss = (
                                        f"❌ <b>RED!</b> {EMOJI[ultimo]}\n"
                                        f"💵 Perda: -R${info['perda']:.2f}\n"
                                        f"🕐 {h}\n\n"
                                        f"{placar.mensagem()}\n\n"
                                        f"{banca.mensagem()}"
                                    )
                                    print(f"  {B}❌ LOSS! -R${info['perda']:.2f}{RST}")
                                    enviar_telegram(msg_loss)

                                elif status == 'gale':
                                    aposta_atual = estrategia.aposta
                                    msg_gale = (
                                        f"📉 <b>GALE {estrategia.gales}</b>\n"
                                        f"Continua apostando em {EMOJI[aposta_atual]} {NOME[aposta_atual]}\n"
                                        f"💵 Próxima stake: R${info['proxima_stake']:.2f}\n"
                                        f"🕐 {h}"
                                    )
                                    print(f"  ⚠️  GALE {estrategia.gales} | stake R${info['proxima_stake']:.2f}")
                                    enviar_telegram(msg_gale)
                                continue

                            # ── Verifica padrões para nova entrada ─────────────
                            acao, bet = estrategia.verificar_prepare(historico_letras)

                            if acao == 'entrada':
                                estrategia.ativa  = True
                                estrategia.aposta = bet
                                estrategia.gales  = 0
                                estrategia.stake_atual = banca.proxima_stake
                                estrategia.preparando = False

                                msg_entrada = (
                                    f"🚨 <b>ENTRADA CONFIRMADA!</b>\n"
                                    f"➡️ Aposte em {EMOJI[bet]} <b>{NOME[bet]}</b>\n"
                                    f"💵 Stake: R${estrategia.stake_atual:.2f}\n"
                                    f"🛡️ Proteção no TIE {EMOJI['T']}\n"
                                    f"🕐 {h}"
                                )
                                print(f"\n  🚨 ENTRADA! Aposta: {EMOJI[bet]} {bet} | Stake: R${estrategia.stake_atual:.2f}\n")
                                enviar_telegram(msg_entrada)

                            elif acao == 'prepare' and not estrategia.preparando:
                                estrategia.preparando = True
                                msg_prepare = (
                                    f"🚠 <b>PREPARE-SE!</b>\n"
                                    f"Padrão se formando...\n"
                                    f"Fique de olho! {EMOJI[bet]}\n"
                                    f"🕐 {h}"
                                )
                                print(f"  ⚠️  PREPARE-SE! Possível entrada em {EMOJI[bet]}")
                                enviar_telegram(msg_prepare)
                            else:
                                estrategia.preparando = False

                        # ── Atualiza histórico quando nova rodada termina ──────
                        elif g.get("stage") == "NoMoreBets":
                            pass  # aguarda o resultado

                    # ── Resultado da rodada chegou ─────────────────────────────
                    elif tipo == "bacbo.gameResult":
                        args = data.get("args", {})
                        winner = args.get("winner", "")
                        if winner:
                            letra = winner_para_letra(winner)
                            if letra == 'T':
                                soma_tie_pendente = extrair_soma_tie(args)
                                if soma_tie_pendente is None:
                                    print(f"  {T}⚠️  Não achei a soma dos dados no TIE. "
                                          f"Args recebidos: {args}{RST}")
                                    print(f"  {T}   (me manda esse JSON pra eu ajustar a extração){RST}")
                            historico_letras.append(letra)
                            # Mantém histórico em no máximo 100 entradas
                            if len(historico_letras) > 100:
                                historico_letras = historico_letras[-100:]

                except asyncio.TimeoutError:
                    pass

    except websockets.exceptions.ConnectionClosed:
        print(f"\n{T}⚠️  WebSocket desconectou!{RST}")
        return "DESCONECTOU"
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        return "ERRO"


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n{G}{'═' * 60}")
    print(f"  🎲 MONITOR BAC BO - SINAIS + GALE")
    print(f"{'═' * 60}{RST}\n")

    print(f"{G}Estratégias ativas:{RST}")
    for s in STRATEGIES:
        print(f"  {' '.join(s['pattern'])} → aposta {EMOJI[s['bet']]} {NOME[s['bet']]}")
    print(f"\n  Gale máximo: {MAX_GALES}x\n")

    print(f"{G}INSTRUÇÕES:{RST}")
    print("1. Abra o 5gbet no navegador")
    print("2. Entre na mesa Bac Bo")
    print("3. F12 → Network → WS → clica na conexão → Copy URL")
    print("4. Cole abaixo\n")
    print(f"{G}💰 Dica: mande /banca 500 no Telegram pra configurar sua banca inicial")
    print(f"   (começa em R${STAKE_MINIMA:.2f} e cresce sozinha a cada vitória), ou")
    print(f"   /banca 500 10 pra já começar apostando R$10 em vez do mínimo.{RST}\n")

    banca = Banca()
    asyncio.create_task(escutar_comandos(banca))

    while True:
        ws_url = input(f"{G}Cole a URL do WebSocket: {RST}").strip()

        if not ws_url or "wss://" not in ws_url:
            print(f"\n❌ URL inválida! Deve começar com wss://\n")
            continue

        print(f"\n{G}✅ Conectando...{RST}\n")

        while True:
            resultado = await monitor(ws_url, banca)

            if resultado == "DESCONECTOU":
                print(f"\n{T}Cole a nova URL do WebSocket:{RST}\n")
                ws_url = input(f"{G}Nova URL: {RST}").strip()
                if not ws_url or "wss://" not in ws_url:
                    print(f"❌ URL inválida!\n")
                    continue
                print(f"{G}✅ Reconectando...{RST}\n")
            else:
                print(f"\n❌ Erro. Tente novamente.\n")
                break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{G}Monitor finalizado.{RST}")
        sys.exit(0)
