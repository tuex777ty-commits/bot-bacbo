#!/usr/bin/env python3
"""
Bac Bo - Bot com Ignorance de SSL e Estabilidade de WebSocket (Railway)
"""

import asyncio
import json
import re
import os
import ssl
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
CAMINHOS_PREFERIDOS = ["/bacbo/player/game/", "/player/game/", "evolution", "casinome"]

# ─── Otimização Equilibrada de Memória RAM ────────────────────────────────────
async def interceptar_e_bloquear_recursos(route):
    """Bloqueia mídias pesadas, mas deixa carregar scripts estruturais essenciais"""
    tipo_recurso = route.request.resource_type
    if tipo_recurso in ["image", "media", "font", "imageset", "beacon"]:
        await route.abort()
    else:
        await route.continue_()

async def fechar_popups(page: Page, tentativas: int = 3):
    for _ in range(tentativas):
        if page.is_closed(): return
        await page.wait_for_timeout(300)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        for texto in ["cancel", "Fechar", "Entendi", "OK", "Aceitar", "Confirmar", "×"]:
            try:
                el = page.get_by_text(texto, exact=False).first
                if await el.is_visible():
                    await el.click(force=True)
            except Exception:
                pass

async def fazer_login(page: Page):
    try:
        print("🌐 Abrindo página de login...")
        await page.goto("https://www.5gbet.com/home/register", timeout=60000, wait_until="commit")
        await page.wait_for_timeout(4000)
    except Exception as e:
        print(f"ℹ️ Avançando carregamento inicial: {e}")

    if page.is_closed(): return
    await fechar_popups(page)
    
    try:
        campo_usuario = page.get_by_role("textbox", name="Digite o Número do Celular/E-")
        campo_senha = page.get_by_role("textbox", name="Insira a senha")
        
        aba_login = page.get_by_text("Login", exact=False).first
        if await aba_login.is_visible():
            await aba_login.click(force=True)
            await page.wait_for_timeout(500)

        await campo_usuario.fill(LOGIN)
        await campo_senha.fill(SENHA)

        botao_confirmar = page.locator("section").filter(has_text=re.compile(r"^Login$")).first
        if await botao_confirmar.is_visible():
            await botao_confirmar.click(force=True)
        else:
            await page.get_by_role("button", name="Login").click(force=True)

        await page.wait_for_timeout(5000)
        print("✅ Login efetuado com sucesso.")
    except Exception as e:
        print(f"⚠️ Erro ao preencher login (pode já estar logado): {e}")

async def entrar_na_mesa_direto(page: Page):
    if page.is_closed(): return
    try:
        print(f"🚀 Forçando entrada direta na mesa: {URL_MESA_DIRETA}")
        await page.goto(URL_MESA_DIRETA, timeout=60000, wait_until="commit")
        await page.wait_for_timeout(6000)
        await fechar_popups(page)
        
        for seletor in ["iframe", "canvas", ".game-play", ".game-container", "button:has-text('Jogar')"]:
            try:
                alvo = page.locator(seletor).first
                if await alvo.is_visible():
                    await alvo.click(force=True, timeout=3000)
                    print(f"   ⚡ Interação disparada no elemento: {seletor}")
                    await page.wait_for_timeout(1000)
            except Exception:
                pass
                
    except Exception as e:
        print(f"⚠️ Erro ao tentar carregar mesa diretamente: {e}")

async def capturar_url(page: Page, corrotina_navegacao) -> str | None:
    urls_capturadas = []
    def ao_abrir_websocket(ws):
        urls_capturadas.append(ws.url)
        if "evolution" in ws.url or "bacbo" in ws.url:
            print(f"🎯 WebSocket de dados localizado!")

    page.on("websocket", ao_abrir_websocket)
    try:
        await corrotina_navegacao
    except Exception:
        pass
    
    await page.wait_for_timeout(10000)
    try:
        page.remove_listener("websocket", ao_abrir_websocket)
    except Exception:
        pass

    candidatos = [u for u in urls_capturadas if "wss://" in u and not any(d in u for d in DOMINIOS_IRRELEVANTES)]
    if not candidatos: return None
    
    for c in candidatos:
        if "evolution" in c or "player/game" in c or "bacbo" in c:
            return c
    return candidatos[-1]

def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        d = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"}), timeout=5)
    except Exception:
        pass

async def monitor(ws_url):
    headers = {"Origin": "https://www.5gbet.com", "User-Agent": "Mozilla/5.0"}
    
    # CRUCIAL: Cria um contexto SSL que ignora erros de verificação locais do Linux
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    try:
        async with websockets.connect(ws_url, additional_headers=headers, ssl=ssl_context) as ws:
            print("🟢 CONECTADO COM SUCESSO AO WEBSOCKET DA MESA!")
            enviar_telegram("🤖 <b>Bot Bac Bo Conectado e Monitorando a Mesa com sucesso!</b>")
            while True:
                msg = await ws.recv()
                # O processamento lê os pacotes da Evolution aqui...
    except Exception as e:
        print(f"🔴 Desconectado do WebSocket: {e}")
        return "DESCONECTOU"

async def main():
    print("🎲 BAC BO - INICIANDO SISTEMA COM CORREÇÃO DE SSL")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-zygote", "--js-flags='--max-old-space-size=256'"]
        )
        context = await browser.new_context()
        page = await context.new_page()
        await page.route("**/*", interceptar_e_bloquear_recursos)

        while True:
            try:
                if page.is_closed():
                    context = await browser.new_context()
                    page = await context.new_page()
                    await page.route("**/*", interceptar_e_bloquear_recursos)

                await fazer_login(page)
                print("🔎 Capturando WebSocket da mesa...")
                url = await capturar_url(page, entrar_na_mesa_direto(page))

                if url:
                    print(f"✅ URL Encontrada: {url[:60]}...")
                    await monitor(url)
                else:
                    print("⚠️ Não capturou o tráfego de dados nesta tentativa. Reiniciando ciclo...")
                    await asyncio.sleep(6)
            except Exception as e:
                print(f"🔄 Reiniciando por instabilidade: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
