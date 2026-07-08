#!/usr/bin/env python3
"""
Bac Bo - Bot Otimizado para Baixo Consumo de RAM (Railway 512MB)
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
LOGIN = os.environ.get("LOGIN_5GBET", "Tuex7777")
SENHA = os.environ.get("SENHA_5GBET", "Tuex7777")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8781120274:AAEAG_m4eaL5mLo_LURVZ-rKiuuesJlurlQ")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003948108220")

INTERVALO_RECONEXAO = 1200  # 20 minutos
URL_MESA_DIRETA = "https://www.5gbet.com/home/subgame?gameCategoryId=4&platformId=317"

DOMINIOS_IRRELEVANTES = ["webpush", "engagelab", "push", "analytics", "doubleclick", "sentry", "hotjar", "clarity"]
CAMINHOS_IRRELEVANTES = ["/lobby/", "/chat/", "/video/", "websocketstream"]
CAMINHOS_PREFERIDOS = ["/bacbo/player/game/", "/player/game/"]

# ─── Otimização Extrema de Memória RAM ────────────────────────────────────────
async def interceptar_e_bloquear_recursos(route):
    """Bloqueia imagens, fontes, CSS e mídias para economizar mais de 250MB de RAM"""
    tipo_recurso = route.request.resource_type
    if tipo_recurso in ["image", "media", "font", "stylesheet", "imageset", "beacon"]:
        await route.abort()
    else:
        await route.continue_()

async def clicar_resiliente(locator, timeout: int = 10000):
    try:
        await locator.click(timeout=timeout)
    except Exception:
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
        await page.wait_for_timeout(200)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        for texto in ["cancel", "Fechar", "Entendi", "OK", "Aceitar", "Confirmar"]:
            try:
                el = page.get_by_text(texto, exact=False).first
                if await el.is_visible():
                    await el.click(force=True)
                    fechou_algo = True
                    await page.wait_for_timeout(200)
            except Exception:
                pass
        if not fechou_algo:
            break

async def fechar_sair_do_jogo(page: Page):
    await clicar_se_existir(page.get_by_role("button", name="Sair do jogo"), timeout_espera=500)

async def fazer_login(page: Page, max_tentativas: int = 3, login: str = None, senha: str = None):
    login = login if login is not None else LOGIN
    senha = senha if senha is not None else SENHA

    try:
        await page.goto("https://www.5gbet.com/home/register", timeout=20000)
    except Exception as e:
        print(f"ℹ️ Avançando página ({e}).")
        return

    await fechar_popups(page)
    campo_usuario = page.get_by_role("textbox", name="Digite o Número do Celular/E-")
    campo_senha = page.get_by_role("textbox", name="Insira a senha")

    for tentativa in range(1, max_tentativas + 1):
        try:
            aba_login = page.get_by_text("Login", exact=False).first
            if await aba_login.is_visible():
                await clicar_resiliente(aba_login)
                await page.wait_for_timeout(500)

            await campo_usuario.fill(login)
            await campo_senha.fill(senha)

            botao_confirmar = page.locator("section").filter(has_text=re.compile(r"^Login$"))
            if await botao_confirmar.count() > 0:
                await clicar_resiliente(botao_confirmar.first, timeout=5000)
            else:
                await clicar_resiliente(page.get_by_role("button", name="Login"), timeout=5000)

            await page.wait_for_timeout(3000)
            if not await campo_usuario.is_visible():
                print("✅ Login efetuado com sucesso.")
                break
        except Exception:
            pass
    await fechar_popups(page)

async def buscar_evo(page: Page):
    await clicar_se_existir(page.get_by_text("Pesquisar", exact=False).first)
    campo_busca = page.get_by_role("textbox", name="Insira o conteúdo da pesquisa")
    try:
        await campo_busca.fill("evo")
        await page.wait_for_timeout(500)
        await clicar_resiliente(page.locator("#app svg").nth(4))
    except Exception:
        pass

async def entrar_no_provedor_evo(page: Page):
    await clicar_se_existir(page.get_by_role("heading", name="EVO Jogo Ao Vivo"))
    await fechar_popups(page)

async def entrar_na_mesa_bacbo(page: Page):
    try:
        frame_externo = page.locator('iframe[title="EVO Jogo Ao Vivo"]').content_frame
        frame_meio = frame_externo.locator("iframe").content_frame
        alvo_externo = frame_meio.locator('[id="PorBacBo00000001::top_picks_for_you"]').get_by_text("Bac Bo Ao Vivo")
        await clicar_resiliente(alvo_externo, timeout=8000)
        await page.wait_for_timeout(2000)
    except Exception:
        pass

async def entrar_no_ao_vivo(page: Page):
    await buscar_evo(page)
    await entrar_no_provedor_evo(page)
    await entrar_na_mesa_bacbo(page)

async def reentrar_na_mesa(page: Page):
    try:
        await page.goto(URL_MESA_DIRETA, timeout=20000)
    except Exception:
        pass
    await fechar_popups(page)
    await entrar_no_provedor_evo(page)
    await entrar_na_mesa_bacbo(page)

async def capturar_url(page: Page, corrotina_navegacao, espera_extra=3000) -> str | None:
    urls_capturadas = []
    def ao_abrir_websocket(ws):
        if "wss://" in ws.url:
            urls_capturadas.append(ws.url)
    page.on("websocket", ao_abrir_websocket)
    try:
        await corrotina_navegacao
    finally:
        page.remove_listener("websocket", ao_abrir_websocket)

    await page.wait_for_timeout(espera_extra)
    candidatos = [u for u in urls_capturadas if not any(d in u for d in DOMINIOS_IRRELEVANTES) and not any(c in u for c in CAMINHOS_IRRELEVANTES)]
    if not candidatos: return None
    preferidos = [u for u in candidatos if any(p in u for p in CAMINHOS_PREFERIDOS)]
    return preferidos[-1] if preferidos else candidatos[-1]

def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        d = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"}), timeout=5)
    except Exception:
        pass

class Banca:
    def __init__(self):
        self.inicial = 0.0
        self.saldo = 0.0
        self.proxima_stake = 2.50

class Placar:
    def __init__(self):
        self.wins = 0
        self.losses = 0

async def monitor(ws_url, banca, placar):
    headers = {"Origin": "https://www.5gbet.com", "User-Agent": "Mozilla/5.0"}
    try:
        async with websockets.connect(ws_url, additional_headers=headers) as ws:
            print("✅ Conectado ao WebSocket de Dados!")
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
    except Exception:
        return "DESCONECTOU"

async def main():
    print("🎲 BAC BO - INICIANDO COM OTIMIZAÇÃO DE MEMÓRIA RAM (MAX 512MB)")
    banca = Banca()
    placar = Placar()

    async with async_playwright() as pw:
        # Argumentos Chromium focados em economia brutal de recursos
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", 
                "--disable-setuid-sandbox", 
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--no-zygote",
                "--js-flags='--max-old-space-size=128'"
            ]
        )
        context = await browser.new_context()
        page = await context.new_page()

        # Ativa o interceptador de bloqueio de imagens e CSS para poupar RAM
        await page.route("**/*", interceptar_e_bloquear_recursos)

        await fazer_login(page)
        print("🔎 Capturando WebSocket inicial...")
        url = await capturar_url(page, entrar_no_ao_vivo(page))

        while True:
            if not url:
                await asyncio.sleep(10)
                url = await capturar_url(page, reentrar_na_mesa(page))
                continue
                
            monitor_task = asyncio.create_task(monitor(url, banca, placar))
            timer_task = asyncio.create_task(asyncio.sleep(INTERVALO_RECONEXAO))

            await asyncio.wait({monitor_task, timer_task}, return_when=asyncio.FIRST_COMPLETED)
            url = await capturar_url(page, reentrar_na_mesa(page))

if __name__ == "__main__":
    asyncio.run(main())
