#!/usr/bin/env python3
"""
Bac Bo - Bot completo e unificado (Versão Otimizada para Railway)
"""

import asyncio
import json
import re
import os
import urllib.request
import urllib.error
import websockets
from datetime import datetime
from playwright.async_api import async_playwright, Page, BrowserContext

# ─── Credenciais e Configurações (Via Variáveis de Ambiente) ──────────────────
# Configure essas variáveis no painel do Railway (Aba Variables)
LOGIN = os.environ.get("LOGIN_5GBET", "Tuex7777")
SENHA = os.environ.get("SENHA_5GBET", "Tuex7777")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8781120274:AAEAG_m4eaL5mLo_LURVZ-rKiuuesJlurlQ")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003948108220")

# Intervalo de renovação da URL
INTERVALO_RECONEXAO = 1200  # 20 minutos

URL_MESA_DIRETA = "https://www.5gbet.com/home/subgame?gameCategoryId=4&platformId=317"

DOMINIOS_IRRELEVANTES = [
    "webpush", "engagelab", "push", "analytics",
    "doubleclick", "sentry", "hotjar", "clarity",
]

CAMINHOS_IRRELEVANTES = ["/lobby/", "/chat/", "/video/", "websocketstream"]
CAMINHOS_PREFERIDOS = ["/bacbo/player/game/", "/player/game/"]


# ─── Utilidades ───────────────────────────────────────────────────────────────
async def clicar_resiliente(locator, timeout: int = 10000):
    try:
        await locator.click(timeout=timeout)
    except Exception as e:
        print(f"⚠️ Clique normal falhou ({type(e).__name__}), tentando clique forçado...")
        await locator.click(force=True, timeout=5000)


async def clicar_se_existir(locator, timeout_espera: int = 1000, descricao: str = "") -> bool:
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
    for _ in range(tentativas):
        fechou_algo = False
        await page.wait_for_timeout(400)

        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

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
                    "⚠️ Login feito, mas ainda não consegui ler seu saldo na tela. Vou continuar tentando.",
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

    try:
        await clicar_resiliente(page.locator("#app svg").nth(4), timeout=5000)
        print("   ✓ Cliquei no resultado da busca (Evolution)")
    except Exception as e:
        print(f"⚠️ Não consegui clicar no resultado da busca: {e}")


async def entrar_no_provedor_evo(page: Page):
    await clicar_se_existir(
        page.get_by_role("heading", name="EVO Jogo Ao Vivo"),
        descricao="Cliquei no cabeçalho 'EVO Jogo Ao Vivo'",
    )
    await fechar_popups(page)
    await fechar_sair_do_jogo(page)

    await clicar_se_existir(
        page.get_by_role("heading", name="EVO Jogo Ao Vivo"),
        descricao="Cliquei no cabeçalho de novo (confirmação)",
    )
    await fechar_popups(page)


async def entrar_na_mesa_bacbo(page: Page):
    try:
        frame_externo = page.locator('iframe[title="EVO Jogo Ao Vivo"]').content_frame
        frame_meio = frame_externo.locator("iframe").content_frame

        alvo_externo = frame_meio.locator('[id="PorBacBo00000001::top_picks_for_you"]').get_by_text("Bac Bo Ao Vivo")
        await clicar_resiliente(alvo_externo, timeout=8000)
        print("   ✓ Cliquei em 'Bac Bo Ao Vivo' (camada externa)")

        await fechar_popups(page)
        await page.wait_for_timeout(1500)

        try:
            frame_interno = frame_meio.locator("#inGameLobby").content_frame
            alvo_interno = frame_interno.locator('[id="PorBacBo00000001::top_picks_for_you"]').get_by_text("Bac Bo Ao Vivo")
            await clicar_resiliente(alvo_interno, timeout=8000)
            print("✅ Mesa Bac Bo aberta (camada interna confirmada).")
        except Exception:
            print("✅ Mesa Bac Bo aberta (camada interna não apareceu -- pode já estar aberta).")

        await fechar_popups(page)
        await page.wait_for_timeout(4000)

    except Exception as e:
        print(f"⚠️ Não consegui entrar na mesa via iframe: {e}")


async def entrar_no_ao_vivo(page: Page):
    await buscar_evo(page)
    await entrar_no_provedor_evo(page)
    await entrar_na_mesa_bacbo(page)


async def reentrar_na_mesa(page: Page):
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

    candidatos = [
        u for u in urls_capturadas
        if not any(d in u for d in DOMINIOS_IRRELEVANTES)
        and not any(c in u for c in CAMINHOS_IRRELEVANTES)
    ]
    if not candidatos:
        print("⚠️ Só sobraram WebSockets irrelevantes. Nenhum candidato válido.")
        return None

    preferidos = [u for u in candidatos if any(p in u for p in CAMINHOS_PREFERIDOS)]
    url_final = preferidos[-1] if preferidos else candidatos[-1]

    return url_final


# ─── Cores do terminal ────────────────────────────────────────────────────────
P   = "\033[94m"
B   = "\033[91m"
T   = "\033[93m"
G   = "\033[92m"
RST = "\033[0m"

MAX_GALES = 2          
STAKE_MINIMA = 2.50    

TIE_MULTIPLICADORES = {
    2: 88, 12: 88, 3: 25, 11: 25, 4: 10, 10: 10, 5: 6,  9: 6, 6: 4,  7: 4, 8: 4,
}
TIE_MULTIPLICADOR_PADRAO = 4   
TIE_SIDE_BET_RATIO = 0.10      
TIE_MIN_BET = 0.50             
TIE_PROTECAO_PERDA = 0.10      


def multiplicador_tie(soma):
    if soma is None:
        return TIE_MULTIPLICADOR_PADRAO
    return TIE_MULTIPLICADORES.get(soma, TIE_MULTIPLICADOR_PADRAO)


def extrair_soma_tie(args):
    for campo in ('total', 'sum', 'tieTotal', 'value'):
        if campo in args:
            try:
                return int(args[campo])
            except (TypeError, ValueError):
                pass
    return None


class Banca:
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

    def message(self):
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


# ─── Comandos via Telegram ────────────────────────────────────────────────────
def telegram_get_updates(offset):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?timeout=25&offset={offset}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read()).get("result", [])
    except Exception as e:
        print(f"  ⚠️ Erro ao buscar comandos do Telegram: {e}")
        return []


async def escutar_comandos(banca, browser):
    offset = 0
    sessoes_privadas = {}  

    while True:
        updates = await asyncio.to_thread(telegram_get_updates, offset)
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message", {})
            texto = msg.get("text", "").strip()
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))

            if chat_id == str(TELEGRAM_CHAT_ID):
                if texto.startswith("/banca"):
                    partes = texto.split()
                    try:
                        valor_banca = float(partes[1])
                        banca.configurar(valor_banca)
                        enviar_telegram(f"✅ Banca configurada!\nInicial: R${banca.inicial:.2f}")
                    except (IndexError, ValueError):
                        enviar_telegram("⚠️ Uso: <code>/banca 500</code>")
                continue  

            sessao = sessoes_privadas.get(chat_id)
            if texto == "/start" or sessao is None:
                sessoes_privadas[chat_id] = {"estado": "aguardando_login"}
                enviar_telegram("Qual é o seu login?", chat_id=chat_id)
                continue

        await asyncio.sleep(0.5)


STRATEGIES = [
    {'pattern': ['P', 'P', 'P'], 'bet': 'B'},
    {'pattern': ['B', 'B', 'B'], 'bet': 'P'},
]
EMOJI = {'P': '🔵', 'B': '🔴', 'T': '🟡'}
NOME  = {'P': 'PLAYER', 'B': 'BANKER', 'T': 'TIE'}


def enviar_telegram(msg, chat_id=None):
    chat_id = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        d = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(
            urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"}),
            timeout=5,
        )
    except Exception as e:
        print(f"  ⚠️ Erro Telegram: {e}")


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


class Estrategia:
    def __init__(self):
        self.reset()

    def reset(self, aguardar=False):
        self.ativa = False           
        self.aposta = None           
        self.gales = 0               
        self.stake_atual = None      
        self.aguardar = aguardar     
        self.preparando = False      

    def verificar_prepare(self, historico):
        for s in STRATEGIES:
            pat = s['pattern']
            bet = s['bet']
            if historico[-len(pat):] == pat:
                return ('entrada', bet)
        return (None, None)

    def processar_resultado(self, resultado, placar, banca=None, soma_tie=None):
        if not self.ativa:
            return None, None
        return None, None


def winner_para_letra(winner):
    if winner == 'Player': return 'P'
    if winner == 'Banker': return 'B'
    return 'T'


async def monitor(ws_url, banca, placar):
    headers = {"Origin": "https://www.5gbet.com", "User-Agent": "Mozilla/5.0"}
    historico_letras = []
    estrategia = Estrategia()

    try:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            print(f"{G}✅ Conectado ao WebSocket!{RST}\n")
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                # O restante do processamento do socket continua aqui...
    except Exception as e:
        return "DESCONECTOU"


# ─── Main Modificado para Railway ─────────────────────────────────────────────
async def main():
    print(f"\n{G}🎲 BAC BO - INICIANDO BOT NO RAILWAY{RST}\n")

    banca = Banca()
    placar = Placar()

    async with async_playwright() as pw:
        # ATENÇÃO: Configuração essencial para servidores de nuvem (Headless e Argumentos Linux)
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", 
                "--disable-setuid-sandbox", 
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = await browser.new_context()
        page = await context.new_page()

        asyncio.create_task(escutar_comandos(banca, browser))
        await fazer_login(page)

        print(f"{G}🔎 Capturando WebSocket inicial...{RST}\n")
        url = await capturar_url(page, entrar_no_ao_vivo(page))

        while True:
            if not url:
                await asyncio.sleep(10)
                url = await capturar_url(page, reentrar_na_mesa(page))
                continue
                
            monitor_task = asyncio.create_task(monitor(url, banca, placar))
            timer_task = asyncio.create_task(asyncio.sleep(INTERVALO_RECONEXAO))

            done, _ = await asyncio.wait(
                {monitor_task, timer_task}, return_when=asyncio.FIRST_COMPLETED
            )

            url = await capturar_url(page, reentrar_na_mesa(page))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\nBot finalizado.")