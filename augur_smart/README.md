# Augur Smart

Chat de consultoria de negócios com IA, vendido separadamente como "isca" de
baixo custo para o app completo (Escritório). Projeto independente: app,
banco de dados e deploy próprios — não depende de `app.py`.

## Rodando localmente

```bash
cd augur_smart
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export AUGUR_SMART_ADMIN_EMAILS="seu-email@exemplo.com"
uvicorn app:app --reload --port 8930
```

Acesse `http://localhost:8930`.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|---|---|---|
| `ANTHROPIC_API_KEY` | sim | Chave da API da Anthropic, usada para o chat. |
| `DATABASE_URL_AUGUR_SMART` | não | Padrão: SQLite local (`augur_smart.db`). Em produção, use Postgres. |
| `SECRET_KEY_AUGUR_SMART` | recomendado | Chave para assinatura do cookie de sessão. Se não definida, é gerada aleatoriamente a cada deploy (derruba sessões existentes). |
| `STRIPE_SECRET_KEY` | para cobrança | Chave secreta do Stripe. |
| `STRIPE_WEBHOOK_SECRET` | para cobrança | Secret do endpoint de webhook (`/stripe/webhook`) configurado no Stripe. |
| `AUGUR_SMART_ADMIN_EMAILS` | para admin | Lista separada por vírgula de e-mails com acesso a `/admin/precos`. |

## Deploy no Render (sugestão)

1. Crie um novo Web Service apontando para a pasta `augur_smart/` deste repositório (Root Directory).
2. Build command: `pip install -r requirements.txt`
3. Start command: já definido no `Procfile`.
4. Configure as variáveis de ambiente acima.
5. No Stripe, crie os produtos/preços recorrentes e cole o `price_xxx` em
   `/admin/precos` para cada plano (ou deixe em branco para o app criar o
   preço dinamicamente no checkout).
6. Configure o webhook do Stripe apontando para `https://<seu-dominio>/stripe/webhook`,
   escutando `checkout.session.completed`, `invoice.paid` e `customer.subscription.deleted`.

## Fluxo

1. Usuário cria conta (`/cadastro`) — sem assinatura ativa por padrão.
2. Escolhe um plano em `/` ou `/conta` → vai para o Stripe Checkout (`/assinar/{codigo}`).
3. Webhook do Stripe ativa a assinatura e libera o chat (`/chat`).
4. Cada mensagem é registrada e contabilizada no limite mensal do plano
   (se houver). O ciclo zera quando uma fatura é paga (`invoice.paid`).
5. Admin gerencia preços e limites em `/admin/precos` (defina seu e-mail em
   `AUGUR_SMART_ADMIN_EMAILS`).
