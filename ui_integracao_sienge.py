# ui_integracao_sienge.py
#
# Integração com a API REST do Sienge (ERP construção civil)
# Autenticação: Basic Auth (usuário + senha gerados no painel de Integrações do Sienge)
# URL base: https://api.sienge.com.br/{tenant}/public/api/v1/
#
# MODELOS:
#   SiengeConfig        — credenciais por empresa (tenant + usuário + senha)
#   SiengeEmpreendimento — obras/empreendimentos sincronizados
#   SiengeContratoVenda  — contratos de venda sincronizados
#   SiengeContaPagar     — parcelas de contas a pagar
#   SiengeContaReceber   — títulos de contas a receber
#   SiengeSyncLog        — histórico de sincronizações
#
# ROTAS:
#   GET  /admin/sienge                    — página de configuração e status
#   POST /admin/sienge/config             — salva credenciais
#   POST /admin/sienge/sync               — sync manual (retorna log JSON)
#   GET  /admin/sienge/status             — status JSON da última sync
#   POST /integracoes/sienge/webhook      — receptor de webhooks do Sienge
#
# SCHEDULER:
#   Sync automático diário às 06:00 BRT

import os          as _os_sg
import json        as _json_sg
import base64      as _b64_sg
import threading   as _thread_sg
import time        as _time_sg
from datetime      import datetime, timezone, timedelta
from typing        import Optional, List
from sqlmodel      import Field as _F_sg, SQLModel as _SM_sg, select as _sel_sg, Session as _Ses_sg

# ── Modelos ───────────────────────────────────────────────────────────────────

class SiengeConfig(_SM_sg, table=True):
    __tablename__  = "siengeconfig"
    __table_args__ = {"extend_existing": True}
    id:             Optional[int] = _F_sg(default=None, primary_key=True)
    company_id:     int           = _F_sg(index=True, unique=True)
    tenant:         str           = _F_sg(default="")   # subdomínio: minhaempresa
    api_user:       str           = _F_sg(default="")   # usuário criado em Integrações
    api_password:   str           = _F_sg(default="")   # senha (plain text — mesma política do OAuth no projeto)
    ativo:          bool          = _F_sg(default=True)
    created_at:     datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))
    updated_at:     datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))


class SiengeEmpreendimento(_SM_sg, table=True):
    __tablename__  = "siengeempreendimento"
    __table_args__ = {"extend_existing": True}
    id:             Optional[int] = _F_sg(default=None, primary_key=True)
    company_id:     int           = _F_sg(index=True)
    sienge_id:      int           = _F_sg(index=True)   # id do Sienge
    nome:           str           = _F_sg(default="")
    codigo:         str           = _F_sg(default="")
    situacao:       str           = _F_sg(default="")
    cidade:         str           = _F_sg(default="")
    uf:             str           = _F_sg(default="")
    n_unidades:     int           = _F_sg(default=0)
    raw_json:       str           = _F_sg(default="")   # payload completo
    synced_at:      datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))


class SiengeContratoVenda(_SM_sg, table=True):
    __tablename__  = "siengecontratovenda"
    __table_args__ = {"extend_existing": True}
    id:             Optional[int] = _F_sg(default=None, primary_key=True)
    company_id:     int           = _F_sg(index=True)
    sienge_id:      int           = _F_sg(index=True)
    empreendimento_id: int        = _F_sg(default=0)
    numero:         str           = _F_sg(default="")
    cliente_nome:   str           = _F_sg(default="")
    situacao:       str           = _F_sg(default="")
    valor_total:    float         = _F_sg(default=0.0)
    data_contrato:  str           = _F_sg(default="")
    unidade:        str           = _F_sg(default="")
    raw_json:       str           = _F_sg(default="")
    synced_at:      datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))


class SiengeContaPagar(_SM_sg, table=True):
    __tablename__  = "siengecontapagar"
    __table_args__ = {"extend_existing": True}
    id:                  Optional[int] = _F_sg(default=None, primary_key=True)
    company_id:          int           = _F_sg(index=True)
    sienge_id:           str           = _F_sg(index=True)   # id composto Sienge
    credor_nome:         str           = _F_sg(default="")
    descricao:           str           = _F_sg(default="")
    valor:               float         = _F_sg(default=0.0)
    vencimento:          str           = _F_sg(default="")
    data_realizacao:     str           = _F_sg(default="")   # data do pagamento efetivo (se pago)
    situacao:            str           = _F_sg(default="")
    empreendimento_id:   str           = _F_sg(default="")   # ID do empreendimento no Sienge
    empreendimento_nome: str           = _F_sg(default="")   # Nome resolvido
    centro_custo:        str           = _F_sg(default="")   # centro de custo vindo do Sienge
    empreendimento:      str           = _F_sg(default="")   # campo legado (mantido)
    raw_json:            str           = _F_sg(default="")
    synced_at:           datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))


class SiengeContaReceber(_SM_sg, table=True):
    __tablename__  = "siengecontareceber"
    __table_args__ = {"extend_existing": True}
    id:                  Optional[int] = _F_sg(default=None, primary_key=True)
    company_id:          int           = _F_sg(index=True)
    sienge_id:           str           = _F_sg(index=True)
    devedor_nome:        str           = _F_sg(default="")
    descricao:           str           = _F_sg(default="")
    valor:               float         = _F_sg(default=0.0)
    vencimento:          str           = _F_sg(default="")
    data_realizacao:     str           = _F_sg(default="")   # data do recebimento efetivo
    situacao:            str           = _F_sg(default="")
    empreendimento_id:   str           = _F_sg(default="")
    empreendimento_nome: str           = _F_sg(default="")
    centro_custo:        str           = _F_sg(default="")
    empreendimento:      str           = _F_sg(default="")   # campo legado
    raw_json:            str           = _F_sg(default="")
    synced_at:           datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))


class SiengeSyncLog(_SM_sg, table=True):
    __tablename__  = "siengesynclog"
    __table_args__ = {"extend_existing": True}
    id:             Optional[int] = _F_sg(default=None, primary_key=True)
    company_id:     int           = _F_sg(index=True)
    modulo:         str           = _F_sg(default="")   # empreendimentos|contratos|financeiro|medicoes
    status:         str           = _F_sg(default="")   # ok|erro
    registros:      int           = _F_sg(default=0)
    detalhe:        str           = _F_sg(default="")
    iniciado_em:    datetime      = _F_sg(default_factory=lambda: datetime.now(timezone.utc))
    finalizado_em:  Optional[datetime] = _F_sg(default=None)


# Cria tabelas
for _tbl_sg in [SiengeConfig, SiengeEmpreendimento, SiengeContratoVenda,
                SiengeContaPagar, SiengeContaReceber, SiengeSyncLog]:
    try:
        _SM_sg.metadata.create_all(engine, tables=[_tbl_sg.__table__], checkfirst=True)
    except Exception as _e_sg:
        print(f"[sienge] Tabela {_tbl_sg.__tablename__}: {_e_sg}")

# Migrations: novos campos adicionados
_sg_migrations = [
    ("siengecontapagar",   "data_realizacao",     "VARCHAR DEFAULT ''"),
    ("siengecontapagar",   "empreendimento_id",   "VARCHAR DEFAULT ''"),
    ("siengecontapagar",   "empreendimento_nome", "VARCHAR DEFAULT ''"),
    ("siengecontapagar",   "centro_custo",        "VARCHAR DEFAULT ''"),
    ("siengecontareceber", "data_realizacao",     "VARCHAR DEFAULT ''"),
    ("siengecontareceber", "empreendimento_id",   "VARCHAR DEFAULT ''"),
    ("siengecontareceber", "empreendimento_nome", "VARCHAR DEFAULT ''"),
    ("siengecontareceber", "centro_custo",        "VARCHAR DEFAULT ''"),
]
if DATABASE_URL.startswith("postgres"):
    from sqlalchemy import text as _txt_sg
    for _t_sg, _col_sg, _def_sg in _sg_migrations:
        try:
            with engine.begin() as _c_sg:
                _c_sg.execute(_txt_sg(
                    f"ALTER TABLE {_t_sg} ADD COLUMN IF NOT EXISTS {_col_sg} {_def_sg}"
                ))
        except Exception as _e_mg_sg:
            print(f"[sienge] migration {_t_sg}.{_col_sg}: {_e_mg_sg}")


# ── Cliente HTTP ──────────────────────────────────────────────────────────────

class _SiengeClient:
    """Cliente HTTP para a API REST do Sienge com Basic Auth e paginação automática."""

    _BASE = "https://api.sienge.com.br/{tenant}/public/api/v1"

    def __init__(self, tenant: str, api_user: str, api_password: str):
        self.tenant   = tenant.strip().lower()
        self._base    = self._BASE.format(tenant=self.tenant)
        raw           = f"{api_user}:{api_password}".encode()
        self._auth    = "Basic " + _b64_sg.b64encode(raw).decode()

    def _headers(self) -> dict:
        return {
            "Authorization": self._auth,
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def get(self, path: str, params: dict = None) -> dict:
        try:
            import httpx as _hx
        except ImportError:
            raise RuntimeError("httpx não instalado")
        resp = _hx.get(
            f"{self._base}/{path.lstrip('/')}",
            headers=self._headers(),
            params=params or {},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()

    def get_all(self, path: str, page_size: int = 100, extra_params: dict = None) -> list:
        """Busca todas as páginas automaticamente."""
        result  = []
        offset  = 0
        while True:
            params = {"limit": page_size, "offset": offset}
            if extra_params:
                params.update(extra_params)
            try:
                data = self.get(path, params)
            except Exception as _e:
                print(f"[sienge] get_all {path} offset={offset}: {_e}")
                break
            # Sienge retorna {"results": [...], "resultSetMetadata": {"count": N}}
            items = data.get("results") or data.get("data") or (data if isinstance(data, list) else [])
            result.extend(items)
            total = (data.get("resultSetMetadata") or {}).get("count", len(items))
            offset += page_size
            if offset >= total or not items:
                break
            _time_sg.sleep(0.35)   # respeita ~200 req/min
        return result

    def test_connection(self) -> tuple[bool, str]:
        """Testa conectividade e credenciais."""
        try:
            data = self.get("enterprises", {"limit": 1, "offset": 0})
            return True, f"Conexão OK — tenant '{self.tenant}'"
        except Exception as _e:
            return False, str(_e)


# ── Funções de sincronização ──────────────────────────────────────────────────

def _sg_log(session, company_id: int, modulo: str, status: str,
            registros: int, detalhe: str, inicio: datetime) -> None:
    log = SiengeSyncLog(
        company_id=company_id, modulo=modulo, status=status,
        registros=registros, detalhe=detalhe[:1000], iniciado_em=inicio,
        finalizado_em=datetime.now(timezone.utc),
    )
    session.add(log)
    session.commit()


def _sg_sync_empreendimentos(client: _SiengeClient, company_id: int) -> dict:
    inicio = datetime.now(timezone.utc)
    try:
        items = client.get_all("enterprises")
        with _Ses_sg(engine) as s:
            # Remove anteriores desta empresa para reimportar limpo
            existentes = s.exec(_sel_sg(SiengeEmpreendimento).where(
                SiengeEmpreendimento.company_id == company_id)).all()
            ids_existentes = {e.sienge_id: e for e in existentes}

            count = 0
            for item in items:
                # API /enterprises usa enterpriseId; fallback para id/buildingId
                sid = item.get("enterpriseId") or item.get("id") or item.get("buildingId") or 0
                obj = ids_existentes.get(sid) or SiengeEmpreendimento(
                    company_id=company_id, sienge_id=sid)
                obj.nome       = (item.get("name") or item.get("enterpriseName") or
                                  item.get("buildingName") or "")
                obj.codigo     = str(item.get("code") or item.get("enterpriseCode") or "")
                obj.situacao   = (item.get("status") or item.get("buildingStatus") or
                                  item.get("enterpriseStatus") or "")
                obj.cidade     = (item.get("city") or
                                  (item.get("address") or {}).get("city", "") or "")
                obj.uf         = (item.get("state") or item.get("uf") or
                                  (item.get("address") or {}).get("state", "") or "")
                obj.n_unidades = item.get("numberOfUnits") or item.get("unitsCount") or 0
                obj.raw_json   = _json_sg.dumps(item, ensure_ascii=False)[:4000]
                obj.synced_at  = datetime.now(timezone.utc)
                s.add(obj)
                count += 1
            s.commit()
            _sg_log(s, company_id, "empreendimentos", "ok", count, f"{count} empreendimentos", inicio)
        return {"ok": True, "registros": count}
    except Exception as _e:
        with _Ses_sg(engine) as s:
            _sg_log(s, company_id, "empreendimentos", "erro", 0, str(_e), inicio)
        return {"ok": False, "erro": str(_e)}


def _sg_sync_contratos_venda(client: _SiengeClient, company_id: int) -> dict:
    inicio = datetime.now(timezone.utc)
    try:
        # Endpoint Bulk confirmado via painel de autorização Sienge: /sales
        from datetime import date as _date_sg2
        start_cv = (_date_sg2.today().replace(year=_date_sg2.today().year - 5).isoformat())
        items = _sg_bulk_get_all(client, "sales", extra_params={"startDate": start_cv})
        if not items:
            items = client.get_all("contracts")
        if not items:
            items = client.get_all("sale-contracts")
        with _Ses_sg(engine) as s:
            existentes = s.exec(_sel_sg(SiengeContratoVenda).where(
                SiengeContratoVenda.company_id == company_id)).all()
            ids_existentes = {e.sienge_id: e for e in existentes}

            count = 0
            for item in items:
                sid = (item.get("saleContractId") or item.get("contractId") or
                       item.get("id") or 0)
                obj = ids_existentes.get(sid) or SiengeContratoVenda(
                    company_id=company_id, sienge_id=sid)
                obj.empreendimento_id = (item.get("enterpriseId") or
                                         item.get("buildingId") or 0)
                obj.numero       = str(item.get("contractNumber") or item.get("number") or "")
                obj.cliente_nome = (item.get("customerName") or item.get("clientName") or "")
                obj.situacao     = (item.get("situation") or item.get("contractStatus") or
                                    item.get("status") or "")
                obj.valor_total  = float(item.get("totalValue") or item.get("value") or 0)
                obj.data_contrato = str(item.get("contractDate") or item.get("date") or "")
                obj.unidade      = str(item.get("unitId") or item.get("unit") or
                                       item.get("unitCode") or "")
                obj.raw_json     = _json_sg.dumps(item, ensure_ascii=False)[:4000]
                obj.synced_at    = datetime.now(timezone.utc)
                s.add(obj)
                count += 1
            s.commit()
            _sg_log(s, company_id, "contratos_venda", "ok", count, f"{count} contratos", inicio)
        return {"ok": True, "registros": count}
    except Exception as _e:
        with _Ses_sg(engine) as s:
            _sg_log(s, company_id, "contratos_venda", "erro", 0, str(_e), inicio)
        return {"ok": False, "erro": str(_e)}


_SITUACAO_REALIZADO_PAGAR   = {"pago", "liquidado", "quitado", "pg", "paid"}
_SITUACAO_REALIZADO_RECEBER = {"recebido", "liquidado", "quitado", "baixado", "received"}

def _sg_resolve_emp(emp_map: dict, raw_id) -> tuple[str, str]:
    """Retorna (empreendimento_id, empreendimento_nome) dado um id do Sienge."""
    sid = str(raw_id or "")
    nome = emp_map.get(sid, emp_map.get(raw_id, "")) or ""
    return sid, nome


def _sg_bulk_get_all(client: _SiengeClient, path: str, page_size: int = 500,
                     extra_params: dict = None) -> list:
    """Busca todas as páginas da Bulk Data API do Sienge."""
    try:
        import httpx as _hx_bulk
    except ImportError:
        return []
    bulk_base = f"https://api.sienge.com.br/{client.tenant}/public/api/bulk-data/v1"
    result = []
    offset = 0
    while True:
        try:
            params = {"limit": page_size, "offset": offset}
            if extra_params:
                params.update(extra_params)
            resp = _hx_bulk.get(
                f"{bulk_base}/{path.lstrip('/')}",
                headers=client._headers(),
                params=params,
                timeout=60.0,
            )
            if resp.status_code == 429:
                print(f"[sienge] bulk {path} rate limit — aguardando 65s")
                _time_sg.sleep(65)
                continue
            if resp.status_code != 200:
                print(f"[sienge] bulk {path} HTTP {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            items = data.get("results") or data.get("data") or (data if isinstance(data, list) else [])
            result.extend(items)
            total = (data.get("resultSetMetadata") or {}).get("count", len(items))
            offset += page_size
            if offset >= total or not items:
                break
            _time_sg.sleep(3.5)   # Bulk: 20 req/min → ~3s entre páginas
        except Exception as _e_bulk:
            print(f"[sienge] bulk {path} erro: {_e_bulk}")
            break
    return result


def _sg_sync_contas_pagar(client: _SiengeClient, company_id: int) -> dict:
    """Bulk Data API — endpoint /outcome (Parcelas do contas a pagar)."""
    inicio = datetime.now(timezone.utc)
    try:
        with _Ses_sg(engine) as s:
            emps = s.exec(_sel_sg(SiengeEmpreendimento).where(
                SiengeEmpreendimento.company_id == company_id)).all()
        emp_map = {str(e.sienge_id): e.nome for e in emps}

        # Bulk /outcome exige startDate obrigatório — últimos 24 meses
        from datetime import date as _date_sg
        start = (_date_sg.today().replace(year=_date_sg.today().year - 2)
                 .isoformat())  # 2 anos atrás
        bulk_params = {"startDate": start}
        items = _sg_bulk_get_all(client, "outcome", extra_params=bulk_params)
        if not items:
            items = _sg_bulk_get_all(client, "outcome/by-bills", extra_params=bulk_params)
        if not items:
            items = client.get_all("bill-debts", page_size=200)

        with _Ses_sg(engine) as s:
            existentes = s.exec(_sel_sg(SiengeContaPagar).where(
                SiengeContaPagar.company_id == company_id)).all()
            ids_existentes = {e.sienge_id: e for e in existentes}

            count = 0
            for item in items:
                # bill-debts: id principal é billDebtId ou id; parcela via installmentNumber
                bill_id = str(item.get("billDebtId") or item.get("id") or
                              item.get("installmentId") or item.get("billId") or "")
                inst_num = str(item.get("installmentNumber") or item.get("parcelNumber") or "")
                sid = f"{bill_id}-{inst_num}" if inst_num else bill_id
                if not sid.strip("-"):
                    continue
                obj = ids_existentes.get(sid) or SiengeContaPagar(
                    company_id=company_id, sienge_id=sid)
                # Bulk /outcome usa: creditorName, billValue, dueDate, paymentDate, enterpriseId
                obj.credor_nome  = (item.get("creditorName") or item.get("supplierName") or
                                    item.get("vendorName") or item.get("creditor") or "")
                obj.descricao    = (item.get("description") or item.get("historicDescription") or
                                    item.get("billDescription") or item.get("memo") or "")
                obj.valor        = float(item.get("billValue") or item.get("netValue") or
                                         item.get("value") or item.get("amount") or 0)
                obj.vencimento   = str(item.get("dueDate") or item.get("expirationDate") or "")
                obj.situacao     = str(item.get("situation") or item.get("status") or
                                       item.get("paymentSituation") or "")
                obj.data_realizacao = str(item.get("paymentDate") or item.get("settlementDate") or
                                          item.get("paidDate") or "")
                obj.centro_custo = str(item.get("costCenterName") or item.get("costCenter") or
                                       item.get("costCenterDescription") or "")
                emp_id, emp_nome = _sg_resolve_emp(emp_map,
                    item.get("enterpriseId") or item.get("buildingId") or "")
                obj.empreendimento_id   = emp_id
                obj.empreendimento_nome = emp_nome
                obj.empreendimento      = emp_id   # campo legado
                obj.raw_json     = _json_sg.dumps(item, ensure_ascii=False)[:4000]
                obj.synced_at    = datetime.now(timezone.utc)
                s.add(obj)
                count += 1
            s.commit()
            _sg_log(s, company_id, "contas_pagar", "ok", count, f"{count} parcelas", inicio)
        return {"ok": True, "registros": count}
    except Exception as _e:
        with _Ses_sg(engine) as s:
            _sg_log(s, company_id, "contas_pagar", "erro", 0, str(_e), inicio)
        return {"ok": False, "erro": str(_e)}


def _sg_sync_contas_receber(client: _SiengeClient, company_id: int) -> dict:
    inicio = datetime.now(timezone.utc)
    try:
        with _Ses_sg(engine) as s:
            emps = s.exec(_sel_sg(SiengeEmpreendimento).where(
                SiengeEmpreendimento.company_id == company_id)).all()
        emp_map = {str(e.sienge_id): e.nome for e in emps}

        from datetime import date as _date_sg2
        start2 = (_date_sg2.today().replace(year=_date_sg2.today().year - 2).isoformat())
        bulk_params2 = {"startDate": start2}
        # Bulk parcelas a receber — caminhos confirmados via painel Sienge: /income e /income/by-bills
        items = _sg_bulk_get_all(client, "income", extra_params=bulk_params2)
        if not items:
            items = _sg_bulk_get_all(client, "income/by-bills", extra_params=bulk_params2)
        if not items:
            items = _sg_bulk_get_all(client, "receivable-bills", extra_params=bulk_params2)
        if not items:
            items = client.get_all("accounts-receivable/receivable-bills", page_size=200)
        with _Ses_sg(engine) as s:
            existentes = s.exec(_sel_sg(SiengeContaReceber).where(
                SiengeContaReceber.company_id == company_id)).all()
            ids_existentes = {e.sienge_id: e for e in existentes}

            count = 0
            for item in items:
                sid = str(item.get("receivableBillId") or item.get("billId") or item.get("id") or "")
                if not sid:
                    continue
                obj = ids_existentes.get(sid) or SiengeContaReceber(
                    company_id=company_id, sienge_id=sid)
                obj.devedor_nome = (item.get("customerName") or item.get("clientName") or
                                    item.get("debtorName") or "")
                obj.descricao    = (item.get("description") or item.get("historicDescription") or "")
                obj.valor        = float(item.get("value") or item.get("grossValue") or
                                         item.get("amount") or 0)
                obj.vencimento   = str(item.get("dueDate") or item.get("expirationDate") or "")
                obj.situacao     = str(item.get("situation") or item.get("status") or "")
                obj.data_realizacao = str(item.get("receiptDate") or item.get("settlementDate") or
                                          item.get("receivedDate") or "")
                obj.centro_custo = str(item.get("costCenterName", "") or item.get("costCenter", "") or "")
                emp_id, emp_nome = _sg_resolve_emp(emp_map, item.get("buildingId", ""))
                obj.empreendimento_id   = emp_id
                obj.empreendimento_nome = emp_nome
                obj.empreendimento      = emp_id
                obj.raw_json     = _json_sg.dumps(item, ensure_ascii=False)[:4000]
                obj.synced_at    = datetime.now(timezone.utc)
                s.add(obj)
                count += 1
            s.commit()
            _sg_log(s, company_id, "contas_receber", "ok", count, f"{count} títulos", inicio)
        return {"ok": True, "registros": count}
    except Exception as _e:
        with _Ses_sg(engine) as s:
            _sg_log(s, company_id, "contas_receber", "erro", 0, str(_e), inicio)
        return {"ok": False, "erro": str(_e)}


def _sg_sync_medicoes(client: _SiengeClient, company_id: int) -> dict:
    """Sincroniza medições de contratos de suprimento."""
    inicio = datetime.now(timezone.utc)
    try:
        # supply-contracts/measurements exige enterpriseId — busca por cada empreendimento
        with _Ses_sg(engine) as s_emp:
            emps_med = s_emp.exec(_sel_sg(SiengeEmpreendimento).where(
                SiengeEmpreendimento.company_id == company_id)).all()
        items = []
        for emp in emps_med:
            try:
                r = client.get_all("supply-contracts/measurements",
                                   extra_params={"enterpriseId": emp.sienge_id}, page_size=100)
                items.extend(r)
                if r:
                    _time_sg.sleep(0.5)
            except Exception:
                pass
        # Armazena no log (medições não têm modelo próprio, guardamos só o count por ora)
        count = len(items)
        with _Ses_sg(engine) as s:
            _sg_log(s, company_id, "medicoes", "ok", count, f"{count} medições sincronizadas", inicio)
        return {"ok": True, "registros": count}
    except Exception as _e:
        with _Ses_sg(engine) as s:
            _sg_log(s, company_id, "medicoes", "erro", 0, str(_e), inicio)
        return {"ok": False, "erro": str(_e)}


def _sg_sync_all(company_id: int) -> dict:
    """Executa sync completo para uma empresa. Retorna resultado por módulo."""
    with _Ses_sg(engine) as s:
        cfg = s.exec(_sel_sg(SiengeConfig).where(
            SiengeConfig.company_id == company_id,
            SiengeConfig.ativo == True,
        )).first()
    if not cfg:
        return {"ok": False, "erro": "Integração Sienge não configurada para esta empresa."}

    client = _SiengeClient(cfg.tenant, cfg.api_user, cfg.api_password)
    resultados = {}
    for nome, fn in [
        ("empreendimentos", _sg_sync_empreendimentos),
        ("contratos_venda", _sg_sync_contratos_venda),
        ("contas_pagar",    _sg_sync_contas_pagar),
        ("contas_receber",  _sg_sync_contas_receber),
        ("medicoes",        _sg_sync_medicoes),
    ]:
        print(f"[sienge] Sincronizando {nome} — empresa {company_id}...")
        resultados[nome] = fn(client, company_id)
    return {"ok": True, "resultados": resultados}


# ── Scheduler diário ──────────────────────────────────────────────────────────

_sg_ultimo_sync: dict[int, str] = {}   # company_id → "YYYY-MM-DD"

def _sg_scheduler_loop():
    """Thread daemon: sync diário às 06:00 BRT para todas as empresas configuradas."""
    print("[sienge] Scheduler iniciado — sync diário às 06:00 BRT.")
    _time_sg.sleep(60)
    while True:
        try:
            from datetime import datetime as _dt_sg2
            import pytz as _pytz_sg
        except ImportError:
            _time_sg.sleep(60)
            continue
        try:
            brt  = _pytz_sg.timezone("America/Sao_Paulo")
            agora = _dt_sg2.now(brt)
            hoje  = agora.strftime("%Y-%m-%d")
            if agora.hour == 6:
                with _Ses_sg(engine) as s:
                    cfgs = s.exec(_sel_sg(SiengeConfig).where(SiengeConfig.ativo == True)).all()
                for cfg in cfgs:
                    if _sg_ultimo_sync.get(cfg.company_id) != hoje:
                        _sg_ultimo_sync[cfg.company_id] = hoje
                        _thread_sg.Thread(
                            target=_sg_sync_all,
                            args=(cfg.company_id,),
                            daemon=True,
                            name=f"sienge-sync-{cfg.company_id}",
                        ).start()
        except Exception as _e_sch:
            print(f"[sienge] Scheduler erro: {_e_sch}")
        _time_sg.sleep(55)

_thread_sg.Thread(target=_sg_scheduler_loop, daemon=True, name="sienge-scheduler").start()


# ── Templates HTML ────────────────────────────────────────────────────────────

TEMPLATES["sienge_admin.html"] = r"""
{% extends "base.html" %}
{% block content %}
<style>
  .sg-card{border:1px solid var(--mc-border);border-radius:14px;padding:1.25rem;background:#fff;margin-bottom:1rem;}
  .sg-log{font-family:monospace;font-size:.76rem;background:#f8f8f8;border-radius:8px;padding:1rem;
          max-height:360px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;}
  .sg-badge-ok{background:#d1fae5;color:#065f46;border-radius:6px;padding:2px 8px;font-size:.7rem;font-weight:600;}
  .sg-badge-err{background:#fee2e2;color:#991b1b;border-radius:6px;padding:2px 8px;font-size:.7rem;font-weight:600;}
  .sg-badge-none{background:#f3f4f6;color:#6b7280;border-radius:6px;padding:2px 8px;font-size:.7rem;}
  .sg-modulo{display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;
             border-bottom:1px solid var(--mc-border);}
  .sg-modulo:last-child{border-bottom:none;}
  .sg-num{font-size:1.4rem;font-weight:700;}
  .sg-lbl{font-size:.7rem;color:var(--mc-muted);text-transform:uppercase;letter-spacing:.05em;}
  .tab-btn{background:none;border:none;padding:.4rem 1rem;border-radius:8px;cursor:pointer;font-size:.85rem;color:var(--mc-muted);}
  .tab-btn.active{background:var(--mc-primary);color:#fff;font-weight:600;}
  .tab-pane{display:none;}
  .tab-pane.active{display:block;}
</style>

<div class="d-flex justify-content:space-between align-items-center mb-3">
  <div>
    <h4 class="mb-0">🔗 Integração Sienge</h4>
    <div class="muted small">Sincronização automática de empreendimentos, contratos, financeiro e medições.</div>
  </div>
</div>

{# Tabs #}
<div class="mb-3 d-flex gap-1 flex-wrap">
  <button class="tab-btn active" onclick="showTab('config')">⚙️ Configuração</button>
  <button class="tab-btn" onclick="showTab('status')">📊 Status & Sync</button>
  <button class="tab-btn" onclick="showTab('empreendimentos')">🏗️ Empreendimentos</button>
  <button class="tab-btn" onclick="showTab('financeiro')">💰 Financeiro</button>
  <button class="tab-btn" onclick="showTab('contratos')">📋 Contratos</button>
</div>

{# ── Aba Configuração ── #}
<div id="tab-config" class="tab-pane active">
  <div class="sg-card">
    <div class="fw-semibold mb-1">Credenciais Sienge</div>
    <div class="muted small mb-3">
      Crie um usuário de API no Sienge em <strong>Menu → Integrações → Usuários de APIs</strong>.<br>
      O tenant é o subdomínio da sua conta (ex: se acessa <em>suaempresa.sienge.com.br</em>, o tenant é <strong>suaempresa</strong>).
      Apenas disponível para clientes na nuvem (Data Center).
    </div>
    {% if config %}
    <div class="alert alert-success py-2 small mb-3">
      ✅ Integração configurada — tenant: <strong>{{ config.tenant }}</strong>
      {% if config.ativo %}<span class="sg-badge-ok ms-2">Ativo</span>{% else %}<span class="sg-badge-err ms-2">Inativo</span>{% endif %}
    </div>
    {% endif %}
    <form method="POST" action="/admin/sienge/config">
      <div class="row g-3">
        <div class="col-md-4">
          <label class="form-label small fw-semibold">Tenant (subdomínio)</label>
          <input type="text" name="tenant" class="form-control form-control-sm"
                 placeholder="minhaempresa" value="{{ config.tenant if config else '' }}" required>
          <div class="form-text">Apenas o subdomínio, sem .sienge.com.br</div>
        </div>
        <div class="col-md-4">
          <label class="form-label small fw-semibold">Usuário de API</label>
          <input type="text" name="api_user" class="form-control form-control-sm"
                 placeholder="minhaempresa-apiuser" value="{{ config.api_user if config else '' }}" required>
        </div>
        <div class="col-md-4">
          <label class="form-label small fw-semibold">Senha de API</label>
          <input type="password" name="api_password" class="form-control form-control-sm"
                 placeholder="{{ '••••••••' if config else 'Senha gerada no Sienge' }}">
          <div class="form-text">{% if config %}Deixe em branco para manter a atual{% endif %}</div>
        </div>
      </div>
      <div class="mt-3 d-flex gap-2">
        <button type="submit" class="btn btn-primary btn-sm">💾 Salvar credenciais</button>
        <button type="button" class="btn btn-outline-secondary btn-sm" onclick="testarConexao()">🔌 Testar conexão</button>
      </div>
    </form>
    <div id="testeResult" class="mt-2"></div>
  </div>
</div>

{# ── Aba Status & Sync ── #}
<div id="tab-status" class="tab-pane">
  <div class="sg-card">
    <div class="fw-semibold mb-3">📡 Status da última sincronização</div>
    <div id="statusModulos">
      {% for modulo, info in status_modulos.items() %}
      <div class="sg-modulo">
        <div>
          <div class="fw-semibold small" style="text-transform:capitalize;">{{ modulo.replace('_',' ') }}</div>
          <div class="text-muted" style="font-size:.75rem;">
            {% if info.finalizado_em %}{{ info.finalizado_em.strftime('%d/%m/%Y %H:%M') }}{% else %}Nunca sincronizado{% endif %}
          </div>
        </div>
        <div class="d-flex align-items-center gap-2">
          {% if info.status == 'ok' %}
            <span class="sg-badge-ok">✅ OK</span>
            <span class="text-muted small">{{ info.registros }} registros</span>
          {% elif info.status == 'erro' %}
            <span class="sg-badge-err">❌ Erro</span>
            <span class="text-muted small" title="{{ info.detalhe }}">{{ info.detalhe[:60] }}</span>
          {% else %}
            <span class="sg-badge-none">—</span>
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="d-flex gap-2 mt-3 flex-wrap">
      <button class="btn btn-primary btn-sm" onclick="syncAll()">
        <i class="bi bi-arrow-repeat me-1"></i>Sincronizar tudo agora
      </button>
      <span class="text-muted small align-self-center">Sync automático: diário às 06:00 BRT</span>
    </div>
  </div>

  <div class="sg-card" id="logCard" style="display:none;">
    <div class="fw-semibold mb-2">📋 Log da sincronização</div>
    <div class="sg-log" id="logBox"></div>
  </div>
</div>

{# ── Aba Empreendimentos ── #}
<div id="tab-empreendimentos" class="tab-pane">
  <div class="sg-card">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div class="fw-semibold">🏗️ Empreendimentos ({{ empreendimentos|length }})</div>
      <span class="text-muted small">Última sync: {{ ultima_sync_emp }}</span>
    </div>
    {% if empreendimentos %}
    <div class="table-responsive">
      <table class="table table-sm table-hover">
        <thead><tr>
          <th>Código</th><th>Nome</th><th>Situação</th><th>Cidade/UF</th><th>Unidades</th>
        </tr></thead>
        <tbody>
          {% for e in empreendimentos %}
          <tr>
            <td class="text-muted small">{{ e.codigo }}</td>
            <td class="fw-semibold">{{ e.nome }}</td>
            <td><span class="badge bg-secondary" style="font-size:.65rem;">{{ e.situacao }}</span></td>
            <td class="small">{{ e.cidade }}{% if e.uf %}/{{ e.uf }}{% endif %}</td>
            <td class="text-center">{{ e.n_unidades }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% else %}
    <div class="text-muted small">Nenhum empreendimento sincronizado. Execute a sincronização na aba Status.</div>
    {% endif %}
  </div>
</div>

{# ── Aba Financeiro ── #}
<div id="tab-financeiro" class="tab-pane">
  <div class="row g-3 mb-3">
    <div class="col-md-6">
      <div class="sg-card text-center">
        <div class="sg-lbl">Total a Pagar</div>
        <div class="sg-num text-danger">R$ {{ "{:,.0f}".format(total_pagar).replace(',','.') }}</div>
        <div class="text-muted small">{{ n_pagar }} parcelas</div>
      </div>
    </div>
    <div class="col-md-6">
      <div class="sg-card text-center">
        <div class="sg-lbl">Total a Receber</div>
        <div class="sg-num text-success">R$ {{ "{:,.0f}".format(total_receber).replace(',','.') }}</div>
        <div class="text-muted small">{{ n_receber }} títulos</div>
      </div>
    </div>
  </div>

  <div class="sg-card">
    <div class="fw-semibold mb-2">📤 Contas a Pagar <span class="text-muted small">(vencimento próximo)</span></div>
    {% if contas_pagar %}
    <div class="table-responsive">
      <table class="table table-sm table-hover">
        <thead><tr><th>Credor</th><th>Descrição</th><th>Vencimento</th><th>Valor</th><th>Situação</th></tr></thead>
        <tbody>
          {% for p in contas_pagar[:50] %}
          <tr>
            <td class="small fw-semibold">{{ p.credor_nome[:30] }}</td>
            <td class="text-muted small">{{ p.descricao[:40] }}</td>
            <td class="small">{{ p.vencimento }}</td>
            <td class="small">R$ {{ "{:,.2f}".format(p.valor).replace(',','X').replace('.',',').replace('X','.') }}</td>
            <td><span class="badge bg-secondary" style="font-size:.6rem;">{{ p.situacao }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if contas_pagar|length > 50 %}<div class="text-muted small">Mostrando 50 de {{ contas_pagar|length }}</div>{% endif %}
    {% else %}
    <div class="text-muted small">Nenhuma conta a pagar sincronizada.</div>
    {% endif %}
  </div>

  <div class="sg-card">
    <div class="fw-semibold mb-2">📥 Contas a Receber</div>
    {% if contas_receber %}
    <div class="table-responsive">
      <table class="table table-sm table-hover">
        <thead><tr><th>Devedor</th><th>Descrição</th><th>Vencimento</th><th>Valor</th><th>Situação</th></tr></thead>
        <tbody>
          {% for r in contas_receber[:50] %}
          <tr>
            <td class="small fw-semibold">{{ r.devedor_nome[:30] }}</td>
            <td class="text-muted small">{{ r.descricao[:40] }}</td>
            <td class="small">{{ r.vencimento }}</td>
            <td class="small">R$ {{ "{:,.2f}".format(r.valor).replace(',','X').replace('.',',').replace('X','.') }}</td>
            <td><span class="badge bg-secondary" style="font-size:.6rem;">{{ r.situacao }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if contas_receber|length > 50 %}<div class="text-muted small">Mostrando 50 de {{ contas_receber|length }}</div>{% endif %}
    {% else %}
    <div class="text-muted small">Nenhuma conta a receber sincronizada.</div>
    {% endif %}
  </div>
</div>

{# ── Aba Contratos ── #}
<div id="tab-contratos" class="tab-pane">
  <div class="sg-card">
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div class="fw-semibold">📋 Contratos de Venda ({{ contratos|length }})</div>
    </div>
    {% if contratos %}
    <div class="table-responsive">
      <table class="table table-sm table-hover">
        <thead><tr>
          <th>Número</th><th>Cliente</th><th>Unidade</th><th>Data</th><th>Valor Total</th><th>Situação</th>
        </tr></thead>
        <tbody>
          {% for c in contratos[:100] %}
          <tr>
            <td class="small fw-semibold">{{ c.numero }}</td>
            <td class="small">{{ c.cliente_nome[:35] }}</td>
            <td class="small text-muted">{{ c.unidade }}</td>
            <td class="small">{{ c.data_contrato }}</td>
            <td class="small">R$ {{ "{:,.0f}".format(c.valor_total).replace(',','.') }}</td>
            <td><span class="badge bg-secondary" style="font-size:.6rem;">{{ c.situacao }}</span></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% if contratos|length > 100 %}<div class="text-muted small">Mostrando 100 de {{ contratos|length }}</div>{% endif %}
    {% else %}
    <div class="text-muted small">Nenhum contrato sincronizado. Execute a sincronização na aba Status.</div>
    {% endif %}
  </div>
</div>

<script>
function showTab(name) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}

async function testarConexao() {
  const el = document.getElementById('testeResult');
  el.innerHTML = '<span class="text-muted small">Testando...</span>';
  try {
    const r = await fetch('/admin/sienge/testar', {method: 'POST'});
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('json')) {
      if (r.status === 401 || r.url.includes('/login')) {
        el.innerHTML = '<div class="alert alert-warning py-1 small mt-2">⚠️ Sessão expirada — <a href="/login">faça login novamente</a></div>';
      } else {
        el.innerHTML = `<div class="alert alert-danger py-1 small mt-2">Erro inesperado (${r.status}). Recarregue a página.</div>`;
      }
      return;
    }
    const d = await r.json();
    el.innerHTML = d.ok
      ? `<div class="alert alert-success py-1 small mt-2">✅ ${d.mensagem}</div>`
      : `<div class="alert alert-danger py-1 small mt-2">❌ ${d.erro}</div>`;
  } catch(e) {
    el.innerHTML = `<div class="alert alert-danger py-1 small mt-2">Erro de comunicação: ${e}</div>`;
  }
}

async function syncAll() {
  document.getElementById('logCard').style.display = 'block';
  document.getElementById('logBox').textContent = 'Sincronizando… (pode levar alguns minutos)\n';
  try {
    const r = await fetch('/admin/sienge/sync', {method: 'POST'});
    const ct = r.headers.get('content-type') || '';
    if (!ct.includes('json')) {
      document.getElementById('logBox').textContent = r.url.includes('/login') || r.status === 401
        ? '⚠️ Sessão expirada — recarregue a página e faça login novamente.'
        : `Erro inesperado (${r.status}). Recarregue a página.`;
      return;
    }
    const d = await r.json();
    if (!d.ok) {
      document.getElementById('logBox').textContent = '❌ ' + (d.erro || 'Erro desconhecido');
      return;
    }
    let log = '';
    for (const [mod, res] of Object.entries(d.resultados || {})) {
      const ico = res.ok ? '✅' : '❌';
      const det = res.ok ? `${res.registros} registros` : `Erro: ${res.erro}`;
      log += `${ico} ${mod.padEnd(20)} ${det}\n`;
    }
    document.getElementById('logBox').textContent = log || 'Concluído.';
    setTimeout(() => location.reload(), 1500);
  } catch(e) {
    document.getElementById('logBox').textContent = 'Erro de comunicação: ' + e;
  }
}

carregarStatus();
async function carregarStatus() {}  // status já vem renderizado via Jinja
</script>
{% endblock %}
"""


# ── Rotas ─────────────────────────────────────────────────────────────────────

from fastapi import Depends as _Dep_sg
from fastapi.responses import HTMLResponse as _HTML_sg, JSONResponse as _JSON_sg, RedirectResponse as _Redir_sg
from fastapi import Request as _Req_sg
from sqlmodel import Session as _SesD_sg


@app.get("/admin/sienge", response_class=_HTML_sg)
@require_login
async def sienge_admin_page(request: _Req_sg, session: _SesD_sg = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return _Redir_sg("/", status_code=303)

    cid = ctx.company.id

    cfg = session.exec(_sel_sg(SiengeConfig).where(SiengeConfig.company_id == cid)).first()

    # Status por módulo (último log de cada)
    modulos = ["empreendimentos", "contratos_venda", "contas_pagar", "contas_receber", "medicoes"]
    status_modulos = {}
    for mod in modulos:
        log = session.exec(
            _sel_sg(SiengeSyncLog)
            .where(SiengeSyncLog.company_id == cid, SiengeSyncLog.modulo == mod)
            .order_by(SiengeSyncLog.id.desc())
        ).first()
        status_modulos[mod] = log or SiengeSyncLog(modulo=mod, status="", registros=0, detalhe="")

    empreendimentos = session.exec(
        _sel_sg(SiengeEmpreendimento).where(SiengeEmpreendimento.company_id == cid)
        .order_by(SiengeEmpreendimento.nome)
    ).all()

    contratos = session.exec(
        _sel_sg(SiengeContratoVenda).where(SiengeContratoVenda.company_id == cid)
        .order_by(SiengeContratoVenda.data_contrato.desc())
    ).all()

    contas_pagar = session.exec(
        _sel_sg(SiengeContaPagar).where(SiengeContaPagar.company_id == cid)
        .order_by(SiengeContaPagar.vencimento)
    ).all()

    contas_receber = session.exec(
        _sel_sg(SiengeContaReceber).where(SiengeContaReceber.company_id == cid)
        .order_by(SiengeContaReceber.vencimento)
    ).all()

    total_pagar   = sum(p.valor for p in contas_pagar)
    total_receber = sum(r.valor for r in contas_receber)

    emp_log = status_modulos.get("empreendimentos")
    ultima_sync_emp = emp_log.finalizado_em.strftime("%d/%m/%Y %H:%M") if emp_log and emp_log.finalizado_em else "Nunca"

    return render("sienge_admin.html", request=request, context={
        "config":          cfg,
        "status_modulos":  status_modulos,
        "empreendimentos": empreendimentos,
        "contratos":       contratos,
        "contas_pagar":    contas_pagar,
        "contas_receber":  contas_receber,
        "total_pagar":     total_pagar,
        "total_receber":   total_receber,
        "n_pagar":         len(contas_pagar),
        "n_receber":       len(contas_receber),
        "ultima_sync_emp": ultima_sync_emp,
    })


@app.post("/admin/sienge/config")
@require_login
async def sienge_salvar_config(request: _Req_sg, session: _SesD_sg = Depends(get_session)):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner"):
        return _Redir_sg("/", status_code=303)

    form = await request.form()
    cid  = ctx.company.id

    cfg = session.exec(_sel_sg(SiengeConfig).where(SiengeConfig.company_id == cid)).first()
    if not cfg:
        cfg = SiengeConfig(company_id=cid)

    cfg.tenant   = (form.get("tenant") or "").strip().lower()
    cfg.api_user = (form.get("api_user") or "").strip()
    nova_senha   = (form.get("api_password") or "").strip()
    if nova_senha:
        cfg.api_password = nova_senha
    cfg.ativo      = True
    cfg.updated_at = datetime.now(timezone.utc)

    session.add(cfg)
    session.commit()
    request.session["flash"] = "✅ Credenciais Sienge salvas com sucesso."
    return _Redir_sg("/admin/sienge", status_code=303)


@app.post("/admin/sienge/testar")
async def sienge_testar(request: _Req_sg, session: _SesD_sg = Depends(get_session)):
    if session_user_id(request) is None:
        return _JSON_sg({"ok": False, "erro": "Sessão expirada. Recarregue a página."}, status_code=401)
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return _JSON_sg({"ok": False, "erro": "Sem permissão."})

    cfg = session.exec(_sel_sg(SiengeConfig).where(
        SiengeConfig.company_id == ctx.company.id)).first()
    if not cfg:
        return _JSON_sg({"ok": False, "erro": "Integração não configurada."})

    try:
        client = _SiengeClient(cfg.tenant, cfg.api_user, cfg.api_password)
        ok, msg = client.test_connection()
    except Exception as _e_tst:
        ok, msg = False, str(_e_tst)
    return _JSON_sg({"ok": ok, "mensagem": msg, "erro": msg if not ok else ""})


@app.post("/admin/sienge/sync")
async def sienge_sync_manual(request: _Req_sg, session: _SesD_sg = Depends(get_session)):
    if session_user_id(request) is None:
        return _JSON_sg({"ok": False, "erro": "Sessão expirada. Recarregue a página."}, status_code=401)
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in ("admin", "owner", "equipe"):
        return _JSON_sg({"ok": False, "erro": "Sem permissão."})

    try:
        resultado = _sg_sync_all(ctx.company.id)
    except Exception as _e_sync:
        resultado = {"ok": False, "erro": str(_e_sync)}
    return _JSON_sg(resultado)


@app.post("/integracoes/sienge/webhook")
async def sienge_webhook(request: _Req_sg):
    """Receptor de webhooks do Sienge (eventos de pagamento, parcelas, etc.)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    evento = payload.get("eventType", "") or payload.get("type", "")
    print(f"[sienge] Webhook recebido: {evento} — {_json_sg.dumps(payload)[:200]}")

    # Identifica empresa pelo tenant no header ou body
    tenant = (request.headers.get("X-Sienge-Tenant", "") or
              payload.get("tenant", "")).strip().lower()
    if tenant:
        with _Ses_sg(engine) as s:
            cfg = s.exec(_sel_sg(SiengeConfig).where(
                SiengeConfig.tenant == tenant, SiengeConfig.ativo == True)).first()
            if cfg:
                # Sync incremental do módulo financeiro após evento de pagamento
                if "PAYMENT" in evento.upper() or "RECEIVABLE" in evento.upper():
                    _thread_sg.Thread(
                        target=_sg_sync_contas_pagar,
                        args=(_SiengeClient(cfg.tenant, cfg.api_user, cfg.api_password), cfg.company_id),
                        daemon=True,
                    ).start()

    return _JSON_sg({"ok": True})
