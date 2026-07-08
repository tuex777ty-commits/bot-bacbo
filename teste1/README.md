# Bac Bo Bot

Bot completo em Python que automatiza a navegação até a mesa de Bac Bo (5gbet/Evolution Gaming), captura a URL de WebSocket dos dados do jogo automaticamente, detecta padrões de aposta, aplica estratégia de Gale, simula uma banca hipotética com progressão de stakes, e envia sinais para um grupo do Telegram em tempo real.

## O que o bot faz

- Faz login e navega automaticamente até a mesa Bac Bo (via [Playwright](https://playwright.dev/))
- Captura a URL do WebSocket de dados do jogo sem precisar de F12 manual
- Renova a conexão automaticamente a cada 20 minutos (ou antes, se cair)
- Detecta padrões configuráveis no histórico de resultados
- Aplica estratégia de Gale (até 2 níveis) nas entradas
- Simula uma banca hipotética com progressão "deixa rolar" (stake cresce a cada vitória)
- Calcula o multiplicador real de TIE por soma dos dados
- Envia sinais, resultados e status da banca para o Telegram
- Aceita comandos `/banca` e `/lucro` diretamente no Telegram

## Requisitos

- Python 3.10+
- Dependências:
  ```bash
  pip install playwright websockets
  playwright install chromium
  ```

## Como rodar

1. Preencha suas credenciais no início do arquivo `bacbo_completo.py` (login, senha, token do Telegram, chat ID)
2. Rode:
   ```bash
   python bacbo_completo.py
   ```
3. No Telegram, configure a banca inicial:
   ```
   /banca 500
   ```
4. Acompanhe o lucro a qualquer momento:
   ```
   /lucro
   ```

## Estrutura do projeto

```
teste1/
├── bacbo_completo.py    # Script principal (navegação + sinais + banca)
├── iniciar.bat           # Atalho pra rodar no Windows
└── README.md
```

## Aviso

Este projeto é para fins pessoais e educacionais (automação de navegador, WebSockets, bots de Telegram). Resultados de jogos de azar são aleatórios e independentes entre rodadas -- nenhuma estratégia aqui garante lucro. Use por sua conta e risco.
