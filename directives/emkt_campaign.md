# Diretiva: Campanha E-MKT — Torre de Controle Sigaway

## Objetivo
Capturar screenshots da Torre de Controle da plataforma Sigaway para cada cliente
da lista e enviar por e-mail via Outlook, automatizando o processo de disparo mensal.

## Entradas
- `AÇÃO E-MKT.xlsx` — planilha com colunas: REPRESENTANTE, CLIENTE, EMAIL
- Credenciais Sigaway no `.env` (SIGAWAY_URL, SIGAWAY_USER, SIGAWAY_PASS)
- Assunto e CC configurados na interface ou no `.env`

## Ferramentas / Scripts
| Responsabilidade     | Arquivo                        |
|----------------------|--------------------------------|
| Interface gráfica    | `ui/app.py`                    |
| Leitura do Excel     | `execution/excel_reader.py`    |
| Captura de screenshot| `execution/screenshot.py`      |
| Envio de e-mail      | `execution/email_sender.py`    |
| Ponto de entrada     | `main.py`                      |

## Saídas
- Screenshots PNG temporários em `.tmp/`
- E-mails enviados via Outlook desktop para cada cliente com e-mail válido

## Fluxo de Execução
1. Carregar `AÇÃO E-MKT.xlsx` e extrair lista de destinatários
2. Para cada cliente com e-mail preenchido:
   a. Autenticar no Sigaway via Playwright (headless)
   b. Aguardar carregamento completo dos gráficos circulares de pontuação
   c. Capturar screenshot full-page e salvar em `.tmp/`
   d. Criar e-mail HTML via win32com.client com screenshot anexado
   e. Enviar via Outlook desktop
3. Logar resultado (OK / ERRO) no console da interface
4. Exibir progresso e contadores em tempo real

## Edge Cases e Tratamentos

### Excel bloqueado
- `PermissionError` capturado com mensagem orientando fechar o arquivo

### Sessão expirada / login falho
- Playwright tenta múltiplos seletores de login
- Captura screenshot de erro em `.tmp/` para diagnóstico
- Erro é logado por cliente sem interromper os demais

### Gráficos lentos
- `wait_for_selector` com timeout de 30s para gráficos circulares
- Se timeout: captura o estado atual e continua

### Cliente sem e-mail
- Linha ignorada com aviso no console
- Contador de erros incrementado

### Outlook não disponível
- `RuntimeError` com mensagem clara sobre instalação/configuração

## Aprendizados (preencher conforme uso)
- [ ] Seletores CSS dos gráficos do Sigaway (atualizar em `screenshot.py`)
- [ ] URL da Torre de Controle por cliente (verificar se há parâmetro de filtro na URL)
- [ ] Tempo médio de carregamento dos gráficos

## Pré-requisitos
```bash
pip install -r requirements.txt
playwright install chromium
```
Copiar `.env.example` para `.env` e preencher credenciais.
Adicionar coluna `EMAIL` na planilha `AÇÃO E-MKT.xlsx`.
