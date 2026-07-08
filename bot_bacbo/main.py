#!/usr/bin/env python3
"""
Bac Bo - Bot API Recetora de Sinais (Ultra Leve para Railway)
"""

import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

# ─── Configurações do Telegram ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8781120274:AAEAG_m4eaL5mLo_LURVZ-rKiuuesJlurlQ")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1003948108220")

# Histórico local para cálculo de padrões e estratégias
HISTORICO_RESULTADOS = []

def enviar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        d = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(url, data=d, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
        print("📤 Alerta enviado para o Telegram.")
    except Exception as e:
        print(f"⚠️ Erro ao enviar Telegram: {e}")

# ─── Lógica de Estratégia e Análise dos Sinais ──────────────────────────────
def processar_resultado_jogo(dados_mesa):
    try:
        vencedor = dados_mesa.get("winner", "").upper() # "PLAYER", "BANKER" ou "TIE"
        p_score = dados_mesa.get("player", "?")
        b_score = dados_mesa.get("banker", "?")
        
        print(f"🎲 Novo Resultado Recebido -> Vencedor: {vencedor} (P: {p_score} | B: {b_score})")
        
        # Salva no histórico para análise futura de padrões (ex: sequência de cores)
        HISTORICO_RESULTADOS.append(vencedor)
        if len(HISTORICO_RESULTADOS) > 20:
            HISTORICO_RESULTADOS.pop(0)

        # --- EXEMPLO DE NOTIFICAÇÃO ---
        msg = f"🎲 <b>Novo Resultado Bac Bo</b>\n\n"
        msg += f"🔵 Jogador: {p_score}\n"
        msg += f"🔴 Banca: {b_score}\n\n"
        msg += f"🏆 Vencedor: <b>{vencedor}</b>"
        
        enviar_telegram(msg)
        
    except Exception as e:
        print(f"⚠️ Erro ao processar estratégia: {e}")

# ─── Servidor Web (API) para Receber os Dados do Tampermonkey ────────────────
class APIHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # Permite requisições Cross-Origin (CORS) vindo do seu navegador local
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            dados_mesa = json.loads(post_data.decode('utf-8'))
            
            # Envia os dados recebidos para a lógica do bot
            processar_resultado_jogo(dados_mesa)
            
            # Resposta bem-sucedida para o Tampermonkey
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "sucesso"}).encode())
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            print(f"⚠️ Erro ao processar POST da API: {e}")

    # Silencia os logs internos padrões do servidor HTTP no console
    def log_message(self, format, *args):
        return

def run(port=8080):
    server_address = ('', port)
    httpd = HTTPServer(server_address, APIHandler)
    print(f"🚀 Servidor API rodando com sucesso na porta {port}...")
    httpd.serve_forever()

if __name__ == '__main__':
    # O Railway passa a porta dinamicamente via variável de ambiente PORT
    porta_railway = int(os.environ.get("PORT", 8080))
    run(port=porta_railway)
