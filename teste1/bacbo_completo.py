#!/usr/bin/env python3
"""
Bac Bo - Bot completo e unificado
Login + navegação automática (Playwright) + captura de WebSocket +
estratégias de padrão/Gale + banca hipotética + sinais no Telegram,
tudo num processo só.

Fluxo: login -> fecha popups -> busca "evo" -> entra na provedora Evolution
-> entra na mesa Bac Bo Ao Vivo -> monitora resultados e manda sinais pro
Telegram -> a cada 20 minutos (ou se desconectar antes), volta ao lobby e
entra de novo pra pegar uma URL de WebSocket fresca, sem interromper o
placar/banca acumulados.
"""

import asyncio
import json
import re
import urllib.request
import urllib.error
import websockets
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext

# ─── Credenciais ────────────────────────────────────────────────────────────
LOGIN = "Tuex7777"
SENHA = "Tuex7777"

# Intervalo de renovação da URL (o pedido foi a cada 20 minutos)
INTERVALO_RECONEXAO = 1200  # 20 minutos

# Navegar direto pra essa URL força uma nova conexão de WebSocket na mesa
URL_MESA_DIRETA = "https://www.5gbet.com/home/subgame?gameCategoryId=4&platformId=317"

DOMINIOS_IRRELEVANTES = [
    "webpush", "engagelab", "push", "analytics",
    "doubleclick", "sentry", "hotjar", "clarity",
]

# Caminhos que sabemos NÃO ser o socket de dados do jogo
CAMINHOS_IRRELEVANTES = ["/lobby/", "/chat/", "/video/", "websocketstream"]

# Caminho que sabemos SER o socket de dados do jogo (prioridade máxima)
CAMINHOS_PREFERIDOS = ["/bacbo/player/game/", "/player/game/"]


# ─── Utilidades ───────────────────────────────────────────────────────────────
async def clicar_resiliente(locator, timeout: int = 10000):
    """Clique normal; se travar por instabilidade, tenta force=True."""
    try:
        await locator.click(timeout=timeout)
    except Exception as e:
        print(f"⚠️ Clique normal falhou ({type(e).__name__}), tentando clique forçado...")
        await locator.click(force=True, timeout=5000)


async def clicar_se_existir(locator, timeout_espera: int = 1000, descricao: str = "") -> bool:
    """Clica no elemento SÓ SE ele estiver visível. Nunca lança erro."""
    try:
        await asyncio.sleep(timeout_espera / 1000)
        if await locator.is_visible():
            await clicar_resiliente(locator)
            if descricao:
                print(f"   ✓ {descricao}")
            return True
    except Exception:
        pass
    return False


async def fechar_popups(page: Page, tentativas: int = 4):
    """
    Fecha diálogos/avisos de forma genérica -- o popup que aparece muda a
    cada execução (depende de sessão, promoções ativas etc.), então em vez
    de confiar só em classes específicas, tenta várias abordagens em loop.
    """
    for _ in range(tentativas):
        fechou_algo = False
        await page.wait_for_timeout(400)

        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        # Qualquer diálogo com role="dialog"
        try:
            dialogs = page.locator('[role="dialog"], [role="alertdialog"]')
            count = await dialogs.count()
            for i in range(count):
                dialog = dialogs.nth(i)
                if not await dialog.is_visible():
                    continue
                for seletor_fechar in [
                    '[aria-label="Close" i]', '[aria-label="Fechar" i]',
                    'button:has-text("×")', '.close', '[class*="close"]',
                ]:
                    try:
                        botao = dialog.locator(seletor_fechar).first
                        if await botao.is_visible():
                            await botao.click(force=True)
                            fechou_algo = True
                            break
                    except Exception:
                        pass
        except Exception:
            pass

        # Qualquer ícone de fechar do padrão .ui-dialog-close-box__icon,
        # não importa qual classe hash pai ele tenha (pode mudar a cada build)
        try:
            icones = page.locator(".ui-dialog-close-box__icon svg")
            count = await icones.count()
            for i in range(min(count, 6)):
                el = icones.nth(i)
                if await el.is_visible():
                    await el.click(force=True)
                    fechou_algo = True
                    await page.wait_for_timeout(300)
        except Exception:
            pass

        for texto in ["cancel", "Fechar", "Entendi", "OK", "Aceitar", "Confirmar"]:
            try:
                el = page.get_by_text(texto, exact=False).first
                if await el.is_visible():
                    await el.click(force=True)
                    fechou_algo = True
                    await page.wait_for_timeout(300)
            except Exception:
                pass

        if not fechou_algo:
            break


async def fechar_sair_do_jogo(page: Page):
    await clicar_se_existir(
        page.get_by_role("button", name="Sair do jogo"),
        timeout_espera=1000,
        descricao="Fechei o aviso 'Sair do jogo' (sessão anterior ainda ativa)",
    )


# ─── Login ──────────────────────────────────────────────────────────────────
async def fazer_login(page: Page, max_tentativas: int = 3, login: str = None, senha: str = None):
    login = login if login is not None else LOGIN
    senha = senha if senha is not None else SENHA

    try:
        await page.goto("https://www.5gbet.com/home/register", timeout=15000)
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"ℹ️ Não consegui abrir a página de login ({e}). Seguindo em frente.")
        return

    await fechar_popups(page)

    campo_usuario = page.get_by_role("textbox", name="Digite o Número do Celular/E-")
    campo_senha = page.get_by_role("textbox", name="Insira a senha")

    for tentativa in range(1, max_tentativas + 1):
        try:
            aba_login = page.get_by_text("Login", exact=False).first
            await page.wait_for_timeout(500)
            if await aba_login.is_visible():
                await clicar_resiliente(aba_login)
                await page.wait_for_timeout(800)

            await clicar_resiliente(campo_usuario, timeout=5000)
            await page.wait_for_timeout(400)
            await campo_usuario.fill(login)
            await page.wait_for_timeout(600)

            await clicar_resiliente(campo_senha, timeout=5000)
            await page.wait_for_timeout(400)
            await campo_senha.fill(senha)
            await page.wait_for_timeout(600)

            # Botão de confirmar login -- tenta pela seção com texto exato
            # "Login" primeiro (mais confiável nesse site), cai pro role de
            # botão se não encontrar.
            botao_confirmar = page.locator("section").filter(has_text=re.compile(r"^Login$"))
            if await botao_confirmar.count() > 0:
                await clicar_resiliente(botao_confirmar.first, timeout=10000)
            else:
                await clicar_resiliente(page.get_by_role("button", name="Login"), timeout=10000)

            print(f"⏳ Tentativa {tentativa}/{max_tentativas} de login enviada, aguardando resposta...")
            await page.wait_for_timeout(3000)

            ainda_na_tela_de_login = await campo_usuario.is_visible()
            if not ainda_na_tela_de_login:
                print("✅ Login realizado.")
                break

            print(f"⚠️ Login não confirmado na tentativa {tentativa}. Tentando de novo...")
            await page.wait_for_timeout(1500)

        except Exception as e:
            print(f"ℹ️ Campo de login não encontrado (tentativa {tentativa}): {e}")
            return
    else:
        print("⚠️ Não confirmei o login após todas as tentativas. Seguindo mesmo assim.")

    await fechar_popups(page)
    await fechar_sair_do_jogo(page)
    await fechar_popups(page)


# ─── Monitoramento de saldo real (contas de clientes) ──────────────────────────
async def ler_saldo(page: Page) -> float | None:
    """
    Lê o saldo real da conta logada. AINDA NÃO CONFIRMADO -- preciso que
    você me mostre (print ou 'Inspecionar elemento') onde o saldo aparece
    na tela depois do login pra eu ajustar esse seletor certinho.

    Por enquanto tenta alguns padrões comuns (texto com "R$" perto do
    topo/perfil), mas pode não encontrar nada até ser ajustado.
    """
    tentativas = [
        '[class*="balance"]',
        '[class*="saldo"]',
        '[data-role*="balance"]',
        'header:has-text("R$")',
    ]
    for seletor in tentativas:
        try:
            el = page.locator(seletor).first
            if await el.is_visible():
                texto = await el.inner_text()
                numero = re.sub(r"[^\d,\.]", "", texto).replace(".", "").replace(",", ".")
                if numero:
                    return float(numero)
        except Exception:
            pass
    return None


async def monitorar_conta_privada(browser, chat_id: str, login: str, senha: str, intervalo: int = 60):
    """
    Sessão isolada (context próprio) pra uma conta de cliente. Só loga e
    lê o saldo periodicamente -- nunca aposta, nunca mexe na mesa. Manda
    atualizações de saldo/lucro só pro chat_id privado dessa pessoa.
    """
    context = await browser.new_context()
    page = await context.new_page()

    try:
        await fazer_login(page, login=login, senha=senha)
    except Exception as e:
        enviar_telegram(f"⚠️ Não consegui fazer login na sua conta: {e}", chat_id=chat_id)
        await context.close()
        return

    saldo_anterior = None
    while True:
        saldo_atual = await ler_saldo(page)

        if saldo_atual is None:
            if saldo_anterior is None:
                enviar_telegram(
                    "⚠️ Login feito, mas ainda não consegui ler seu saldo na tela "
                    "(o desenvolvedor precisa ajustar esse detalhe). Vou continuar tentando.",
                    chat_id=chat_id,
                )
        else:
            if saldo_anterior is None:
                enviar_telegram(f"✅ Monitoramento iniciado!\n💰 Saldo atual: R${saldo_atual:.2f}", chat_id=chat_id)
            elif saldo_atual != saldo_anterior:
                lucro = saldo_atual - saldo_anterior
                sinal = "+" if lucro >= 0 else ""
                enviar_telegram(
                    f"💰 Saldo: R${saldo_atual:.2f}\n"
                    f"Variação: {sinal}R${lucro:.2f} (desde a última checagem)",
                    chat_id=chat_id,
                )
            saldo_anterior = saldo_atual

        await asyncio.sleep(intervalo)



async def buscar_evo(page: Page):
    """Usa a lupa de pesquisa pra buscar 'evo' e entrar na provedora Evolution."""
    await clicar_se_existir(page.get_by_text("Pesquisar", exact=False).first, descricao="Abri a busca")
    await page.wait_for_timeout(500)

    campo_busca = page.get_by_role("textbox", name="Insira o conteúdo da pesquisa")
    try:
        await clicar_resiliente(campo_busca, timeout=5000)
        await campo_busca.fill("evo")
        await page.wait_for_timeout(1000)
        print("   ✓ Busquei 'evo'")
    except Exception as e:
        print(f"⚠️ Não consegui usar a busca: {e}")
        return

    # Clica no resultado da busca que leva à provedora Evolution
    try:
        await clicar_resiliente(page.locator("#app svg").nth(4), timeout=5000)
        print("   ✓ Cliquei no resultado da busca (Evolution)")
    except Exception as e:
        print(f"⚠️ Não consegui clicar no resultado da busca: {e}")


async def entrar_no_provedor_evo(page: Page):
    """Clica no cabeçalho 'EVO Jogo Ao Vivo', tratando o 'Sair do jogo' que pode aparecer no meio."""
    await clicar_se_existir(
        page.get_by_role("heading", name="EVO Jogo Ao Vivo"),
        descricao="Cliquei no cabeçalho 'EVO Jogo Ao Vivo'",
    )
    await fechar_popups(page)
    await fechar_sair_do_jogo(page)

    # Depois de fechar o 'Sair do jogo', o clique no cabeçalho pode precisar
    # ser repetido (o popup costuma "engolir" o primeiro clique)
    await clicar_se_existir(
        page.get_by_role("heading", name="EVO Jogo Ao Vivo"),
        descricao="Cliquei no cabeçalho de novo (confirmação)",
    )
    await fechar_popups(page)


async def entrar_na_mesa_bacbo(page: Page):
    """
    Entra na mesa Bac Bo em duas camadas: primeiro o clique 'externo' (que
    abre o jogo dentro do iframe principal), depois um segundo clique
    'interno' no #inGameLobby, que efetivamente lança a mesa.
    """
    try:
        frame_externo = page.locator('iframe[title="EVO Jogo Ao Vivo"]').content_frame
        frame_meio = frame_externo.locator("iframe").content_frame

        alvo_externo = frame_meio.locator('[id="PorBacBo00000001::top_picks_for_you"]').get_by_text("Bac Bo Ao Vivo")
        await clicar_resiliente(alvo_externo, timeout=8000)
        print("   ✓ Cliquei em 'Bac Bo Ao Vivo' (camada externa)")

        await fechar_popups(page)
        await page.wait_for_timeout(1500)

        # Segunda camada -- dentro do #inGameLobby
        try:
            frame_interno = frame_meio.locator("#inGameLobby").content_frame
            alvo_interno = frame_interno.locator('[id="PorBacBo00000001::top_picks_for_you"]').get_by_text("Bac Bo Ao Vivo")
            await clicar_resiliente(alvo_interno, timeout=8000)
            print("✅ Mesa Bac Bo aberta (camada interna confirmada).")
        except Exception:
            print("✅ Mesa Bac Bo aberta (camada interna não apareceu -- pode já estar aberta).")

        await fechar_popups(page)
        await page.wait_for_timeout(4000)  # tempo pro vídeo/stream carregar de vez

    except Exception as e:
        print(f"⚠️ Não consegui entrar na mesa via iframe: {e}")
        try:
            caminho_print = "debug_falha_mesa.png"
            await page.screenshot(path=caminho_print, full_page=True)
            print(f"📸 Print salvo em: {caminho_print} — me manda esse arquivo se continuar falhando")
            print("🖼️ Frames presentes na página no momento da falha:")
            for f in page.frames:
                print(f"   - {f.url[:100]}")
        except Exception as e2:
            print(f"   (não consegui nem tirar o print: {e2})")


async def entrar_no_ao_vivo(page: Page):
    """Fluxo completo, do zero: busca 'evo' -> provedor -> mesa Bac Bo."""
    await buscar_evo(page)
    await entrar_no_provedor_evo(page)
    await entrar_na_mesa_bacbo(page)


async def obter_frames_do_jogo(page: Page):
    """
    Retorna a lista de frames onde elementos do jogo (como o botão
    'ATUALIZAR') costumam aparecer, do mais externo pro mais interno --
    o player da Evolution fica dentro de iframes aninhados, não direto
    na página principal do 5gbet.
    """
    frames = [page]
    try:
        frame_externo = page.locator('iframe[title="EVO Jogo Ao Vivo"]').content_frame
        frames.append(frame_externo)
        try:
            frame_meio = frame_externo.locator("iframe").content_frame
            frames.append(frame_meio)
            try:
                frame_interno = frame_meio.locator("#inGameLobby").content_frame
                frames.append(frame_interno)
            except Exception:
                pass
        except Exception:
            pass
    except Exception:
        pass
    return frames


async def reentrar_na_mesa(page: Page):
    """
    Ciclo de renovação: navega DIRETO pra URL da página da mesa Bac Bo
    (confirmado que isso força uma URL de WebSocket nova de forma
    confiável), em vez de depender do botão ATUALIZAR ou de refazer a
    busca inteira.
    """
    try:
        await page.goto(URL_MESA_DIRETA, timeout=15000)
        print(f"   ✓ Naveguei direto pra {URL_MESA_DIRETA}")
    except Exception as e:
        print(f"⚠️ Não consegui navegar direto pra URL da mesa: {e}")

    await page.wait_for_timeout(2000)
    await fechar_popups(page)
    await fechar_sair_do_jogo(page)
    await fechar_popups(page)

    await entrar_no_provedor_evo(page)
    await entrar_na_mesa_bacbo(page)



# ─── Captura de WebSocket ───────────────────────────────────────────────────
async def capturar_url(page: Page, corrotina_navegacao, espera_extra=3000) -> str | None:
    urls_capturadas = []

    def ao_abrir_websocket(ws):
        if "wss://" in ws.url:
            urls_capturadas.append(ws.url)
            print(f"   📡 WebSocket visto ({len(urls_capturadas)}): {ws.url[:80]}...")

    page.on("websocket", ao_abrir_websocket)
    try:
        await corrotina_navegacao
    finally:
        page.remove_listener("websocket", ao_abrir_websocket)

    await page.wait_for_timeout(espera_extra)

    if not urls_capturadas:
        print("⚠️ Nenhum WebSocket capturado.")
        return None

    # 1) Remove domínios/caminhos claramente irrelevantes (push, lobby, chat, vídeo)
    candidatos = [
        u for u in urls_capturadas
        if not any(d in u for d in DOMINIOS_IRRELEVANTES)
        and not any(c in u for c in CAMINHOS_IRRELEVANTES)
    ]
    if not candidatos:
        print("⚠️ Só sobraram WebSockets irrelevantes (push/lobby/chat/vídeo). Nenhum candidato válido.")
        return None

    # 2) Entre os que sobraram, prioriza o que tem o caminho do socket de
    #    DADOS do jogo (ex: /bacbo/player/game/) -- é esse que carrega os
    #    resultados, não o de chat nem o de vídeo.
    preferidos = [u for u in candidatos if any(p in u for p in CAMINHOS_PREFERIDOS)]
    url_final = preferidos[-1] if preferidos else candidatos[-1]

    if len(urls_capturadas) > 1:
        print(f"ℹ️ {len(urls_capturadas)} WebSockets vistos ({len(candidatos)} relevantes, "
              f"{len(preferidos)} com padrão de dados do jogo), usando: {url_final[:80]}...")
    return url_final


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
            return "💰 Banca não configurada. Use /banca 500 no Telegram."
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


async def escutar_comandos(banca, browser):
    """
    Roda em paralelo ao monitor. Mensagens no GRUPO PRINCIPAL continuam
    tratando /banca e /lucro normalmente (sinal hipotético, como já era).
    Mensagens em conversa PRIVADA (qualquer chat_id diferente do grupo)
    seguem um fluxo de cadastro: pergunta login -> pergunta senha -> inicia
    monitoramento de saldo real só naquele chat.
    """
    offset = 0
    sessoes_privadas = {}  # chat_id (str) -> {"estado": ..., "login": ...}

    while True:
        updates = await asyncio.to_thread(telegram_get_updates, offset)
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message", {})
            texto = msg.get("text", "").strip()
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))

            # ── Mensagens no grupo principal: comandos de sempre ──────────
            if chat_id == str(TELEGRAM_CHAT_ID):
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

                continue  # não passa pro fluxo privado

            # ── Conversa privada: fluxo de cadastro pro saldo real ────────
            sessao = sessoes_privadas.get(chat_id)

            if texto == "/start" or sessao is None:
                sessoes_privadas[chat_id] = {"estado": "aguardando_login"}
                enviar_telegram(
                    "👋 Olá! Pra eu acompanhar seu saldo real, preciso do seu login e senha "
                    "da conta (uso só pra consultar seu saldo -- nunca aposto por você).\n\n"
                    "Qual é o seu login?",
                    chat_id=chat_id,
                )
                continue

            if sessao["estado"] == "aguardando_login":
                sessao["login"] = texto
                sessao["estado"] = "aguardando_senha"
                enviar_telegram("Certo! E qual é a sua senha?", chat_id=chat_id)
                continue

            if sessao["estado"] == "aguardando_senha":
                sessao["senha"] = texto
                sessao["estado"] = "monitorando"
                enviar_telegram(
                    "✅ Recebido! Iniciando o monitoramento do seu saldo real agora...",
                    chat_id=chat_id,
                )
                asyncio.create_task(
                    monitorar_conta_privada(browser, chat_id, sessao["login"], sessao["senha"])
                )
                continue

            if sessao["estado"] == "monitorando":
                enviar_telegram("✅ Seu monitoramento já está ativo! Aguarde as atualizações de saldo.", chat_id=chat_id)

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
def enviar_telegram(msg, chat_id=None):
    chat_id = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        d = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"}),
            timeout=5,
        )
        print(f"  📤 Telegram ({chat_id}): {msg[:60]}...")
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode(errors="replace")
        print(f"  ⚠️ Erro Telegram ({e.code}): {detalhe}")
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
async def monitor(ws_url, banca, placar):
    headers = {
        "Origin": "https://www.5gbet.com",
        "User-Agent": "Mozilla/5.0",
    }

    historico_letras = []   # Lista de 'P', 'B', 'T'
    ultimo_resultado  = None
    soma_tie_pendente = None  # soma dos dados do último TIE (se conseguimos extrair)
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

    except (websockets.exceptions.ConnectionClosed, websockets.exceptions.WebSocketException) as e:
        print(f"\n{T}⚠️  WebSocket desconectou/rejeitou a conexão: {e}{RST}")
        return "DESCONECTOU"
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        return "ERRO"




# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    print(f"\n{G}{'═' * 60}")
    print(f"  🎲 BAC BO - BOT COMPLETO (navegação + sinais)")
    print(f"{'═' * 60}{RST}\n")

    print(f"{G}Estratégias ativas:{RST}")
    for s in STRATEGIES:
        print(f"  {' '.join(s['pattern'])} → aposta {EMOJI[s['bet']]} {NOME[s['bet']]}")
    print(f"\n  Gale máximo: {MAX_GALES}x")
    print(f"  Renovação automática da URL a cada {INTERVALO_RECONEXAO}s\n")

    print(f"{G}💰 Dica: mande /banca 500 no Telegram pra configurar sua banca inicial")
    print(f"   (começa em R${STAKE_MINIMA:.2f} e cresce sozinha a cada vitória), ou")
    print(f"   /banca 500 10 pra já começar apostando R$10 em vez do mínimo.{RST}\n")

    banca = Banca()
    placar = Placar()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        asyncio.create_task(escutar_comandos(banca, browser))

        await fazer_login(page)

        print(f"{G}🔎 Entrando na mesa Bac Bo pela primeira vez...{RST}\n")
        url = await capturar_url(page, entrar_no_ao_vivo(page))

        while not url:
            print(f"{T}⚠️ Não consegui capturar a URL inicial. Tentando de novo em 10s...{RST}")
            await asyncio.sleep(10)
            url = await capturar_url(page, reentrar_na_mesa(page))

        print(f"{G}✅ URL inicial capturada. Iniciando monitor...{RST}\n")

        while True:
            monitor_task = asyncio.create_task(monitor(url, banca, placar))
            timer_task = asyncio.create_task(asyncio.sleep(INTERVALO_RECONEXAO))

            done, _ = await asyncio.wait(
                {monitor_task, timer_task}, return_when=asyncio.FIRST_COMPLETED
            )

            if monitor_task in done:
                # O monitor encerrou sozinho (desconexão/erro) antes do timer
                timer_task.cancel()
                resultado = monitor_task.result()
                print(f"\n{T}⚠️ Monitor encerrou ({resultado}). Capturando URL nova...{RST}\n")
            else:
                # Renovação preventiva: o timer de 3 min bateu primeiro
                print(f"\n{T}🔄 {INTERVALO_RECONEXAO}s atingidos. Renovando a URL preventivamente...{RST}\n")
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

            nova_url = await capturar_url(page, reentrar_na_mesa(page))
            while not nova_url:
                print(f"{T}⚠️ Falhou em capturar URL nova. Tentando de novo em 10s...{RST}")
                await asyncio.sleep(10)
                nova_url = await capturar_url(page, reentrar_na_mesa(page))

            url = nova_url
            print(f"{G}✅ Reconectando com a nova URL...{RST}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{G}Bot finalizado.{RST}")
