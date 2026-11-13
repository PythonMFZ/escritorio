# Testes

Cada arquivo `test_*.py` roda sozinho, com banco SQLite temporário, a API do Claude simulada
(nenhuma chamada real, nenhum custo) e e-mail/integrações externas trocados por simulações.

```bash
pip install -r requirements.txt
python tests/run_all.py              # todos
python tests/run_all.py automacoes   # só os que têm "automacoes" no nome
python tests/test_predio_nucleo.py   # um arquivo
```

| Arquivo | O que cobre |
|---|---|
| `test_predio_nucleo.py` | Integridade dos agentes (ferramentas existem, orçamento de strict, financeiro só admin), páginas, chamado pela Recepção com ferramenta, custo por chamada, aprovação/rejeição e ação interrompida por reinício |
| `test_automacoes.py` | Pós-reunião (follow-up aos participantes), faturamento do mês, cobrança de atrasos, contas a pagar, briefing antes da reunião, relatório mensal, renovações, lead do site, cliente novo (KYC), boletim de mercado, calendário bimestral, card e agendador |
| `test_imobiliario.py` | 4º andar: estudos e motor de viabilidade (com sensibilidade), mapa de vendas (ritmo, estoque, desconto) e obras por valor agregado |
| `test_rotinas_lider.py` | Rotinas de fundo em um processo só (líder por flock) e troca de líder |

`_base.py` tem o preparo comum (`preparar`, `criar_empresa`, `login`, `esperar_chamado`, `check`, `fim`).
Ao criar uma funcionalidade nova, acrescente um `test_<assunto>.py` seguindo o mesmo formato.
