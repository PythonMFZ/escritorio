# ============================================================================
# MÓDULO — Emissão de NFS-e via Sistema Nacional NFS-e (SNNFSE)
# Rota:  GET /admin/financeiro/cobrancas/{id}/emitir-nf
# Dados: MZ Serviços Administrativos Ltda. — CNPJ 60502955000179 — Brusque-SC
# ============================================================================

import os          as _os_nf
import base64      as _b64_nf
import tempfile    as _tmp_nf
import re          as _re_nf
from datetime      import date as _date_nf, datetime as _dt_nf, timezone as _tz_nf, timedelta as _td_nf
from typing        import Optional as _Opt_nf
import httpx        as _httpx_nf
from fastapi        import Request as _Req_nf, Depends as _Dep_nf
from fastapi.responses import RedirectResponse as _RR_nf, HTMLResponse as _HTML_nf

# ── Constantes da empresa emissora ───────────────────────────────────────────
_NF_CNPJ          = "60502955000179"
_NF_IM            = "1016247"         # Inscrição Municipal Brusque
_NF_IBGE          = "4202909"         # Código IBGE Brusque-SC
_NF_SERIE         = "1"
_NF_RAZAO         = "MZ SERVICOS ADMINISTRATIVOS LTDA"
_NF_EMAIL         = "MERIZIOALINE@GMAIL.COM"
_NF_CTRIB_NAC     = "170303"           # TSCodTribNac — LC 116 item 17.03 sub-subitem 03
_NF_NBS           = "118064000"        # NBS 9 dígitos sem pontos (da NF emitida)
_NF_CNAE          = "8211300"
_NF_PAIS_BR       = "1058"
_NF_NS            = "http://www.sped.fazenda.gov.br/nfse"

# ── Ambiente ──────────────────────────────────────────────────────────────────
_NF_AMB = _os_nf.environ.get("NFSE_AMBIENTE", "homologacao")
_NF_URLS = {
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse",
    "producao":    "https://sefin.nfse.gov.br/SefinNacional/nfse",
}
_NF_tpAmb = "2" if _NF_AMB == "homologacao" else "1"

# ── Migrations ────────────────────────────────────────────────────────────────
try:
    _is_pg_nf = DATABASE_URL.startswith("postgres")
    if _is_pg_nf:
        from sqlalchemy import text as _txt_nf
        with engine.begin() as _c_nf:
            for _col, _typ in [
                ("nf_chave",   "VARCHAR DEFAULT ''"),
                ("nf_url",     "VARCHAR DEFAULT ''"),
                ("nf_numero",  "VARCHAR DEFAULT ''"),
            ]:
                try:
                    _c_nf.execute(_txt_nf(
                        f"ALTER TABLE cobranca_mensal ADD COLUMN IF NOT EXISTS {_col} {_typ}"
                    ))
                except Exception:
                    pass
            # Tabela de controle do contador sequencial de nDPS (por série/CNPJ)
            _c_nf.execute(_txt_nf("""
                CREATE TABLE IF NOT EXISTS nfse_ndps_counter (
                    cnpj    VARCHAR(14) NOT NULL,
                    serie   VARCHAR(5)  NOT NULL,
                    ultimo  INTEGER     NOT NULL DEFAULT 265,
                    PRIMARY KEY (cnpj, serie)
                )
            """))
            _c_nf.execute(_txt_nf("""
                INSERT INTO nfse_ndps_counter (cnpj, serie, ultimo)
                VALUES (:cnpj, :serie, 265)
                ON CONFLICT (cnpj, serie) DO NOTHING
            """), {"cnpj": _NF_CNPJ, "serie": _NF_SERIE})
        print("[nfse] ✅ Migrations OK")
except Exception as _e_nf_mg:
    print(f"[nfse] migration: {_e_nf_mg}")


def _nf_proximo_ndps() -> int:
    """Retorna o próximo nDPS sequencial e atualiza o contador atomicamente."""
    from sqlalchemy import text as _txt_seq
    with engine.begin() as _conn:
        row = _conn.execute(_txt_seq("""
            UPDATE nfse_ndps_counter
               SET ultimo = ultimo + 1
             WHERE cnpj = :cnpj AND serie = :serie
         RETURNING ultimo
        """), {"cnpj": _NF_CNPJ, "serie": _NF_SERIE}).fetchone()
    if row is None:
        raise RuntimeError("Contador nDPS não inicializado")
    return row[0]



# ── Certificado ───────────────────────────────────────────────────────────────

def _nf_load_cert():
    """
    Carrega o certificado PFX e retorna (key_pem_bytes, cert_pem_bytes, chain_pem_bytes).
    Fontes (em ordem de prioridade):
      1. NFSE_CERT_B64 + NFSE_CERT_PASSWORD (env vars — Render)
      2. NFSE_CERT_PATH + NFSE_CERT_PASSWORD (caminho local)
    """
    password_raw = _os_nf.environ.get("NFSE_CERT_PASSWORD", "123456")
    password     = password_raw.encode()

    cert_b64 = _os_nf.environ.get("NFSE_CERT_B64", "")
    if cert_b64:
        pfx_bytes = _b64_nf.b64decode(cert_b64)
    else:
        cert_path = _os_nf.environ.get(
            "NFSE_CERT_PATH",
            "/root/.claude/uploads/c4150aaa-976a-564b-ab79-be7bc01be054/e7ec8ec0-MZ_Servic_os_2026_2027_123456.pfx",
        )
        with open(cert_path, "rb") as fh:
            pfx_bytes = fh.read()

    from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates as _lpfx
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption,
    )
    key, cert, chain = _lpfx(pfx_bytes, password)

    key_pem  = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    cert_pem = cert.public_bytes(Encoding.PEM)
    chain_pem = b"".join(c.public_bytes(Encoding.PEM) for c in (chain or []))

    return key_pem, cert_pem, chain_pem


# ── Montagem do XML DPS ───────────────────────────────────────────────────────

def _nf_chave_acesso(n_dps: int, serie: str = _NF_SERIE) -> str:
    """
    Chave de acesso: cLocEmi(7) + tpInsc(1=CPF/2=CNPJ) + CNPJ/CPF(14) + série(5) + nDPS(15)
    """
    return (
        _NF_IBGE.ljust(7, "0")
        + "2"                                 # tpInsc = CNPJ
        + _NF_CNPJ.ljust(14, "0")
        + str(serie).zfill(5)
        + str(n_dps).zfill(15)
    )


def _nf_limpa_cnpj(doc: str) -> str:
    d = _re_nf.sub(r"\D", "", doc or "")
    # CNPJ deve ter 14 dígitos; CPF 11. Se tiver 15 com zero à esquerda, remove.
    if len(d) == 15 and d.startswith("0"):
        d = d[1:]
    return d


def _nf_limpa_cep(valor: str) -> str:
    return _re_nf.sub(r"\D", "", valor or "")


def _nf_pick_attr(*objs, names: tuple[str, ...], default: str = "") -> str:
    for obj in objs:
        if obj is None:
            continue
        for name in names:
            try:
                value = getattr(obj, name, "")
            except Exception:
                value = ""
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str:
                return value_str
    return default


def _nf_normaliza_texto(valor: str) -> str:
    import unicodedata as _ud_nf

    texto = str(valor or "").strip()
    texto = _ud_nf.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not _ud_nf.combining(ch))
    texto = _re_nf.sub(r"\s+", " ", texto)
    return texto.strip().upper()


def _nf_iter_tomador_sources(contrato, cobranca, session=None):
    vistos = set()

    def _emit(obj):
        if obj is None:
            return
        key = id(obj)
        if key in vistos:
            return
        vistos.add(key)
        yield obj

    for base in (contrato, cobranca):
        yield from _emit(base)

    rel_names = (
        "cliente_plataforma",
        "cliente_empresa",
        "empresa_cliente",
        "cliente",
        "company_cliente",
        "client_company",
        "platform_client",
        "customer_company",
        "customer",
        "empresa",
        "company",
        "client",
    )
    for base in (contrato, cobranca):
        if base is None:
            continue
        for name in rel_names:
            try:
                rel = getattr(base, name, None)
            except Exception:
                rel = None
            yield from _emit(rel)

    if session is not None:
        id_names = (
            "cliente_plataforma_id",
            "cliente_empresa_id",
            "empresa_cliente_id",
            "company_cliente_id",
            "client_company_id",
            "platform_client_id",
            "customer_company_id",
            "customer_id",
            "cliente_id",
            "client_id",
        )
        model_names = (
            "Company",
            "Empresa",
            "Cliente",
            "Client",
            "Organization",
            "TenantCompany",
        )
        for base in (contrato, cobranca):
            if base is None:
                continue
            for id_name in id_names:
                try:
                    raw_id = getattr(base, id_name, None)
                except Exception:
                    raw_id = None
                if raw_id in (None, "", 0, "0"):
                    continue
                try:
                    obj_id = int(raw_id)
                except Exception:
                    continue
                for model_name in model_names:
                    model_cls = globals().get(model_name)
                    if model_cls is None:
                        continue
                    try:
                        rel = session.get(model_cls, obj_id)
                    except Exception:
                        rel = None
                    yield from _emit(rel)


_NF_IBGE_CACHE = {
    ("BRUSQUE", "SC"):    "4202909",
    ("TIJUCAS", "SC"):    "4218004",
    ("FLORIANOPOLIS", "SC"): "4205407",
    ("BLUMENAU", "SC"):   "4202404",
    ("JOINVILLE", "SC"):  "4209102",
    ("ITAJAI", "SC"):     "4208203",
    ("BALNEARIO CAMBORIU", "SC"): "4202008",
    ("SAO JOSE", "SC"):   "4216602",
    ("CHAPECO", "SC"):    "4204202",
}

# CEP padrão por IBGE quando o CEP cadastrado não pertence ao município
_NF_CEP_PADRAO = {
    "4202909": "88352000",  # Brusque-SC
    "4218004": "88200000",  # Tijucas-SC
    "4205407": "88000000",  # Florianópolis-SC
}


def _nf_resolve_ibge_por_cidade_uf(cidade: str, uf: str) -> str:
    cidade_norm = _nf_normaliza_texto(cidade)
    uf_norm = _nf_normaliza_texto(uf)[:2]
    if not cidade_norm or len(uf_norm) != 2:
        return ""

    cached = _NF_IBGE_CACHE.get((cidade_norm, uf_norm))
    if cached:
        return cached

    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_norm}/municipios"
    try:
        with _httpx_nf.Client(timeout=20, verify=True) as client:
            resp = client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        municipios = resp.json()
    except Exception as ex:
        print(f"[nfse] aviso: falha ao consultar IBGE para {cidade_norm}/{uf_norm}: {ex}")
        return ""

    alvo_simples = _re_nf.sub(r"[^A-Z0-9]", "", cidade_norm)
    melhor = ""
    for item in municipios if isinstance(municipios, list) else []:
        nome = _nf_normaliza_texto(item.get("nome", ""))
        codigo = str(item.get("id", "")).strip()
        if len(codigo) != 7:
            continue
        nome_simples = _re_nf.sub(r"[^A-Z0-9]", "", nome)
        if nome == cidade_norm or nome_simples == alvo_simples:
            _NF_IBGE_CACHE[(cidade_norm, uf_norm)] = codigo
            return codigo
        if not melhor and (nome.startswith(cidade_norm) or cidade_norm.startswith(nome)):
            melhor = codigo

    if melhor:
        _NF_IBGE_CACHE[(cidade_norm, uf_norm)] = melhor
        return melhor

    return ""


def _nf_pick_tomador_identificacao(*objs) -> tuple[str, str]:
    doc = _nf_limpa_cnpj(_nf_pick_attr(
        *objs,
        names=(
            "documento_cliente",
            "cnpj_cliente",
            "cpf_cliente",
            "cpf_cnpj_cliente",
            "cpf_cnpj",
            "cnpj_cpf",
            "cpfcnpj",
            "documento",
            "cnpj",
            "cpf",
        ),
    ))
    nome = _nf_pick_attr(
        *objs,
        names=(
            "nome_cliente",
            "razao_social",
            "nome_fantasia",
            "nome",
            "razao",
            "empresa_nome",
            "name",           # Client.name
        ),
        default="NAO INFORMADO",
    )
    return doc, _nf_normaliza_texto(nome)[:150]


def _nf_get_tomador_endereco(contrato, cobranca, session=None) -> dict:
    """
    Lê o endereço do tomador a partir do contrato/cobrança e, se necessário,
    do cadastro da empresa vinculada em "Cliente da plataforma".
    """
    fontes = tuple(_nf_iter_tomador_sources(contrato, cobranca, session=session))

    cep = _nf_limpa_cep(_nf_pick_attr(
        *fontes,
        names=(
            "cep_cliente",
            "cliente_cep",
            "cep_tomador",
            "cep_sacado",
            "cep",
            "endereco_cep",
            "zip_code",       # Client.zip_code
            "zipcode",
            "postal_code",
        ),
    ))
    cmun = _re_nf.sub(r"\D", "", _nf_pick_attr(
        *fontes,
        names=(
            "ibge_cliente",
            "codigo_ibge_cliente",
            "codigo_municipio_cliente",
            "municipio_ibge_cliente",
            "cidade_ibge",
            "cmun_cliente",
            "c_mun_cliente",
            "codigo_ibge",
            "ibge",
            "cmun",
            "c_mun",
        ),
    ))
    cidade = _nf_pick_attr(
        *fontes,
        names=(
            "cidade_cliente",
            "municipio_cliente",
            "cidade",
            "municipio",
            "city",           # Client.city
        ),
    )
    uf = _nf_pick_attr(
        *fontes,
        names=(
            "uf_cliente",
            "estado_cliente",
            "uf",
            "estado",
            "state",          # Client.state
        ),
    )
    x_lgr = _nf_pick_attr(
        *fontes,
        names=(
            "logradouro_cliente",
            "endereco_cliente",
            "rua_cliente",
            "logradouro",
            "endereco",
            "rua",
        ),
        default="NAO INFORMADO",
    ).upper()[:150]
    nro = _nf_pick_attr(
        *fontes,
        names=(
            "numero_cliente",
            "numero_endereco_cliente",
            "numero",
            "endereco_numero",
            "nro",
        ),
        default="S/N",
    ).upper()[:60]
    bairro = _nf_pick_attr(
        *fontes,
        names=(
            "bairro_cliente",
            "endereco_bairro",
            "bairro",
        ),
        default="NAO INFORMADO",
    ).upper()[:60]
    complemento = _nf_pick_attr(
        *fontes,
        names=(
            "complemento_cliente",
            "endereco_complemento",
            "complemento",
        ),
        default="",
    ).upper()[:60]

    if len(cmun) != 7:
        cmun = _nf_resolve_ibge_por_cidade_uf(cidade, uf)

    # Se ainda sem IBGE ou CEP inconsistente, tenta BrasilAPI com CNPJ do tomador
    # (dados da Receita Federal — mesma fonte que o SEFIN usa para validar)
    _doc_toma = _nf_limpa_cnpj(_nf_pick_attr(
        *fontes,
        names=("documento_cliente", "cnpj_cliente", "cpf_cnpj_cliente", "cpf_cnpj", "cnpj", "documento"),
    ))
    if len(_doc_toma) == 14:
        try:
            _rf = _httpx_nf.get(
                f"https://brasilapi.com.br/api/cnpj/v1/{_doc_toma}", timeout=10)
            if _rf.status_code == 200:
                _rf_data = _rf.json()
                _ibge_rf = str(_rf_data.get("codigo_municipio_ibge", "")).strip()
                _cep_rf  = _nf_limpa_cep(str(_rf_data.get("cep", "")))
                if len(_ibge_rf) == 7:
                    print(f"[nfse] BrasilAPI CNPJ {_doc_toma}: ibge={_ibge_rf} cep={_cep_rf}")
                    cmun = _ibge_rf
                    if len(_cep_rf) == 8:
                        cep = _cep_rf
        except Exception as _e_rf:
            print(f"[nfse] aviso: BrasilAPI CNPJ falhou ({_e_rf})")

    # Quando IBGE foi resolvido por nome da cidade, valida se o CEP pertence a esse município.
    # CEP pode estar errado no cadastro (ex: CEP de Brusque para tomador de Canelinha).
    # Se não pertencer, busca um CEP válido para o município via ViaCEP.
    if len(cmun) == 7 and len(cep) == 8:
        try:
            _chk = _httpx_nf.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=8)
            if _chk.status_code == 200 and str(_chk.json().get("ibge", "")) != cmun:
                _uf2 = (uf or "SC")[:2].upper()
                _cid2 = _nf_normaliza_texto(cidade)
                _srch = _httpx_nf.get(
                    f"https://viacep.com.br/ws/{_uf2}/{_cid2}/a/json/", timeout=8)
                if _srch.status_code == 200:
                    _res = _srch.json()
                    if isinstance(_res, list) and _res:
                        _new_cep = _res[0].get("cep", "").replace("-", "")
                        if len(_new_cep) == 8:
                            print(f"[nfse] CEP {cep} não pertence ao município {cmun} — substituindo por {_new_cep} ({cidade})")
                            cep = _new_cep
                # Fallback: CEP padrão do município quando ViaCEP não resolve
                if str(_chk.json().get("ibge", "")) != cmun:
                    _padrao = _NF_CEP_PADRAO.get(cmun)
                    if _padrao:
                        print(f"[nfse] CEP {cep} não pertence ao município {cmun} — usando CEP padrão {_padrao} ({cidade})")
                        cep = _padrao
        except Exception as _e_chk:
            print(f"[nfse] aviso: validação CEP×município falhou ({_e_chk})")

    if len(cmun) != 7 and len(cep) == 8:
        # Último recurso: resolve IBGE pelo CEP via ViaCEP
        try:
            _via_resp = _httpx_nf.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=10)
            if _via_resp.status_code == 200:
                _via = _via_resp.json()
                _ibge_via = str(_via.get("ibge", "")).strip()
                if len(_ibge_via) == 7:
                    cmun = _ibge_via
                    print(f"[nfse] IBGE resolvido via ViaCEP: CEP={cep} → ibge={cmun}")
        except Exception as _e_via:
            print(f"[nfse] aviso: ViaCEP falhou ({_e_via})")

    if len(cmun) != 7:
        print(f"[nfse] aviso: IBGE do tomador não encontrado (cidade={cidade!r}, uf={uf!r}, cep={cep!r}), usando Brusque-SC como fallback")
        cmun = _NF_IBGE
        cep = "88352000"  # CEP de Brusque — mantém consistência cMun × CEP
    if len(cep) != 8:
        print(f"[nfse] aviso: CEP do tomador inválido ({cep!r}), usando CEP padrão Brusque-SC como fallback")
        cep = "88352000"

    print(
        f"[nfse] endereço tomador | cMun={cmun} | CEP={cep} | cidade={cidade!r} | uf={uf!r} | "
        f"logradouro={x_lgr!r} | nro={nro!r} | bairro={bairro!r}"
    )

    return {
        "cMun": cmun,
        "CEP": cep,
        "xLgr": x_lgr or "NAO INFORMADO",
        "nro": nro or "S/N",
        "xBairro": bairro or "NAO INFORMADO",
        "xCpl": complemento,
    }


def _nf_build_dps(cobranca, contrato, n_dps: int, session=None) -> bytes:
    """
    Monta o XML DPS sem assinatura.
    Retorna bytes UTF-8.
    """
    ns   = _NF_NS
    # Competência: usa o campo da cobrança se preenchido; caso contrário usa o mês
    # ANTERIOR ao atual — o SNNFSE valida opSimpNac contra o cadastro SN do mês de
    # competência e a base do mês corrente pode ainda não estar consolidada no SNNFSE.
    # Regra: usa o mês informado na cobrança, mas NUNCA o mês atual — usa o anterior.
    _hoje = _date_nf.today()
    _mes_anterior = (
        f"{_hoje.year - 1}-12" if _hoje.month == 1
        else f"{_hoje.year}-{_hoje.month - 1:02d}"
    )
    dcomp = cobranca.competencia or _mes_anterior
    try:
        dcomp_dt = _dt_nf.strptime(dcomp, "%Y-%m").date()
    except Exception:
        dcomp_dt = _date_nf.today().replace(day=1)
    # Se a competência for o mês atual, recua para o anterior
    if dcomp_dt.year == _hoje.year and dcomp_dt.month == _hoje.month:
        dcomp_dt = (_dt_nf.strptime(_mes_anterior, "%Y-%m")).date()
    dcomp_str = dcomp_dt.strftime("%Y-%m-%d")  # TSData exige YYYY-MM-DD

    # dhEmi — data/hora de emissão com offset BR
    now_br = _dt_nf.now(_tz_nf(offset=_td_nf(hours=-3)))
    dh_emi = now_br.strftime("%Y-%m-%dT%H:%M:%S") + "-03:00"

    valor_str = f"{cobranca.valor_cents / 100:.2f}"
    chave     = _nf_chave_acesso(n_dps)
    inf_id    = "DPS" + chave
    tp_emit   = "1"

    # ── tomador ───────────────────────────────────────────────────────────────
    fontes_tomador = tuple(_nf_iter_tomador_sources(contrato, cobranca, session=session))
    doc_toma, nome_toma = _nf_pick_tomador_identificacao(*fontes_tomador)
    end_toma = _nf_get_tomador_endereco(contrato, cobranca, session=session)

    from lxml import etree as _etloc
    E = _etloc.Element
    root = E(f"{{{ns}}}DPS", versao="1.00", nsmap={None: ns})
    inf  = _etloc.SubElement(root, f"{{{ns}}}infDPS", Id=inf_id)

    def _sub(parent, tag, text=None, **attrs):
        el = _etloc.SubElement(parent, f"{{{ns}}}{tag}", **attrs)
        if text is not None:
            el.text = str(text)
        return el

    # Ordem exata conforme XSD DPS Nacional (infDPS sequence)
    _sub(inf, "tpAmb",    _NF_tpAmb)
    _sub(inf, "dhEmi",    dh_emi)
    _sub(inf, "verAplic", "ERP_1.0")
    _sub(inf, "serie",    _NF_SERIE)
    _sub(inf, "nDPS",     str(n_dps))
    _sub(inf, "dCompet",  dcomp_str)
    _sub(inf, "tpEmit",   tp_emit)   # 1 = prestador
    _sub(inf, "cLocEmi",  _NF_IBGE)

    # ── prestador ─────────────────────────────────────────────────────────────
    prest = _sub(inf, "prest")
    _sub(prest, "CNPJ",    _NF_CNPJ)
    # xNome não deve ser informado quando o emitente da DPS for o próprio prestador (E0121).
    if tp_emit != "1":
        _sub(prest, "xNome", _NF_RAZAO[:150])
    _sub(prest, "email",   _NF_EMAIL)
    regTrib = _sub(prest, "regTrib")
    _sub(regTrib, "opSimpNac", "3")   # optante ME/EPP, se esse for o enquadramento real
    _sub(regTrib, "regApTribSN", "1")  # preencher conforme a apuração correta
    _sub(regTrib, "regEspTrib", "0")
    # ── tomador ───────────────────────────────────────────────────────────────
    tom = _sub(inf, "toma")
    if len(doc_toma) == 14:
        _sub(tom, "CNPJ", doc_toma)
    elif len(doc_toma) == 11:
        _sub(tom, "CPF", doc_toma)
    else:
        # Sem documento válido: omite o elemento (NFS-e nacional aceita tomador sem doc
        # quando o prestador é optante pelo Simples e o valor não exige identificação)
        pass
    _sub(tom, "xNome", nome_toma[:150])
    _end = _sub(tom, "end")
    _endNac = _sub(_end, "endNac")
    _sub(_endNac, "cMun", end_toma["cMun"])
    _sub(_endNac, "CEP",  end_toma["CEP"])
    _sub(_end, "xLgr",    end_toma["xLgr"])
    _sub(_end, "nro",     end_toma["nro"])
    if end_toma["xCpl"]:
        _sub(_end, "xCpl", end_toma["xCpl"])
    _sub(_end, "xBairro", end_toma["xBairro"])

    # ── serviço ───────────────────────────────────────────────────────────────
    desc = (contrato.servicos or contrato.nome_contrato or "Serviços administrativos").strip()
    serv     = _sub(inf, "serv")
    locPrest = _sub(serv, "locPrest")
    _sub(locPrest, "cLocPrestacao", _NF_IBGE)
    cServ = _sub(serv, "cServ")
    _sub(cServ, "cTribNac",  _NF_CTRIB_NAC)
    _sub(cServ, "xDescServ", desc[:2000])

    # ── valores ───────────────────────────────────────────────────────────────
    vals = _sub(inf, "valores")
    vServPrest = _sub(vals, "vServPrest")
    _sub(vServPrest, "vServ", valor_str)
    if tp_emit != "1":
        _sub(vServPrest, "vReceb", valor_str)
    trib = _sub(vals, "trib")
    tribMun = _sub(trib, "tribMun")
    _sub(tribMun, "tribISSQN",  "1")  # 1 = tributada no município
    _sub(tribMun, "tpRetISSQN", "1")  # 1 = não retido
    totTrib = _sub(trib, "totTrib")
    _sub(totTrib, "pTotTribSN", "6.00")

    _dps_bytes = _etloc.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=False)
    print(f"[nfse] DPS XML: {_dps_bytes.decode('utf-8', errors='replace')[:2000]}")
    return _dps_bytes


# ── Assinatura XML ────────────────────────────────────────────────────────────


def _nf_sign_dps(dps_bytes: bytes, key_pem: bytes, cert_pem: bytes) -> bytes:
    """
    Assina infDPS via XMLDSig enveloped — RSA-SHA1 / C14N 1.0 (manual NFS-e v1.01).

    ATENÇÃO — bug do lxml: _et2.tostring(element, method="c14n") em SUBTREE
    adiciona xmlns="" em elementos a partir da profundidade 2, gerando digest/
    assinatura que o SNNFSE rejeita (E0714). Fix: serializar o PARENT completo
    e extrair a seção desejada por índice de string, injetando xmlns.
    """
    import hashlib as _hl
    import base64  as _b64s
    from lxml import etree as _et2
    from cryptography.hazmat.primitives import hashes as _hsh, serialization as _ser
    from cryptography.hazmat.primitives.asymmetric import padding as _pad
    from cryptography.hazmat.primitives.serialization import load_pem_private_key as _lpk
    from cryptography.x509 import load_pem_x509_certificate as _lx509

    DSIG   = "http://www.w3.org/2000/09/xmldsig#"
    C14N   = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
    ENVL   = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
    SHA1D  = "http://www.w3.org/2000/09/xmldsig#sha1"
    RSASHA = "http://www.w3.org/2000/09/xmldsig#rsa-sha1"

    tree = _et2.fromstring(dps_bytes)
    inf = tree.find(f"{{{_NF_NS}}}infDPS")
    if inf is None:
        raise ValueError("XML DPS inválido: tag infDPS não encontrada")

    ref_id = (inf.get("Id") or "").strip()
    if not ref_id:
        raise ValueError("XML DPS inválido: atributo Id de infDPS ausente")

    # 1. Digest SHA-1 do infDPS via C14N inclusivo.
    #    Fix lxml: C14N do tree completo → extrair seção infDPS → injetar xmlns.
    _tree_c14n = _et2.tostring(tree, method="c14n", exclusive=False, with_comments=False)
    _inf_start = _tree_c14n.index(b"<infDPS ")
    _inf_end   = _tree_c14n.index(b"</infDPS>") + len(b"</infDPS>")
    inf_c14n   = _tree_c14n[_inf_start:_inf_end].replace(
        b"<infDPS ", f'<infDPS xmlns="{_NF_NS}" '.encode(), 1
    )
    digest = _b64s.b64encode(_hl.sha1(inf_c14n).digest()).decode()

    # 2. Montar Signature via string XML (garante namespace uniforme, sem xmlns="" nos filhos).
    sig_xml = (
        f'<Signature xmlns="{DSIG}" Id="SIG{ref_id}">'
        f'<SignedInfo>'
        f'<CanonicalizationMethod Algorithm="{C14N}"></CanonicalizationMethod>'
        f'<SignatureMethod Algorithm="{RSASHA}"></SignatureMethod>'
        f'<Reference URI="#{ref_id}">'
        f'<Transforms>'
        f'<Transform Algorithm="{ENVL}"></Transform>'
        f'<Transform Algorithm="{C14N}"></Transform>'
        f'</Transforms>'
        f'<DigestMethod Algorithm="{SHA1D}"></DigestMethod>'
        f'<DigestValue>{digest}</DigestValue>'
        f'</Reference>'
        f'</SignedInfo>'
        f'<SignatureValue></SignatureValue>'
        f'</Signature>'
    )
    sig_el = _et2.fromstring(sig_xml.encode())

    # 3. C14N do SignedInfo — ANTES de anexar ao tree (após append o contexto muda).
    #    Fix lxml: C14N do sig_el completo → extrair SignedInfo → injetar xmlns.
    _sig_full_c14n = _et2.tostring(sig_el, method="c14n", exclusive=False, with_comments=False)
    _si_start = _sig_full_c14n.index(b"<SignedInfo>")
    _si_end   = _sig_full_c14n.index(b"</SignedInfo>") + len(b"</SignedInfo>")
    si_c14n   = _sig_full_c14n[_si_start:_si_end].replace(
        b"<SignedInfo>", f'<SignedInfo xmlns="{DSIG}">'.encode(), 1
    )
    priv_key = _lpk(key_pem, password=None)
    sig_raw  = priv_key.sign(si_c14n, _pad.PKCS1v15(), _hsh.SHA1())
    sig_b64  = _b64s.b64encode(sig_raw).decode()

    # 4. Preencher SignatureValue e KeyInfo, depois annexar ao tree.
    sv = sig_el.find(f"{{{DSIG}}}SignatureValue")
    sv.text = sig_b64
    ki_xml = (
        f'<KeyInfo xmlns="{DSIG}">'
        f'<X509Data><X509Certificate>__CERT__</X509Certificate></X509Data>'
        f'</KeyInfo>'
    )
    cert_obj = _lx509(cert_pem)
    cert_b64 = _b64s.b64encode(cert_obj.public_bytes(_ser.Encoding.DER)).decode()
    ki_el = _et2.fromstring(ki_xml.replace("__CERT__", cert_b64).encode())
    sig_el.append(ki_el)
    tree.append(sig_el)

    signed = _et2.tostring(tree, xml_declaration=True, encoding="UTF-8", pretty_print=False)
    print(f"[nfse] assinatura local OK | ref={ref_id} | digest={digest}")
    return signed


# ── Envio via mTLS ────────────────────────────────────────────────────────────

async def _nf_enviar(xml_bytes: bytes, key_pem: bytes, cert_pem: bytes, chain_pem: bytes = b"") -> dict:
    """
    Envia o XML DPS assinado para a API SNNFSE via mTLS.
    Retorna dict com chave, numero, url ou lança exceção com mensagem de erro.
    """
    url = _NF_URLS[_NF_AMB]
    print(f"[nfse] POST {url} (ambiente={_NF_AMB})")

    # httpx aceita cert como (cert_file, key_file) ou como arquivos temporários
    cert_bundle = cert_pem + (chain_pem or b"")
    with _tmp_nf.NamedTemporaryFile(suffix=".pem", delete=False) as cf:
        cf.write(cert_bundle)
        cert_path = cf.name
    with _tmp_nf.NamedTemporaryFile(suffix=".pem", delete=False) as kf:
        kf.write(key_pem)
        key_path = kf.name

    try:
        import gzip as _gzip_nf
        import json as _json_nf

        # SNNFSE Sefin espera JSON com DPS comprimido em gzip e codificado em base64
        compressed = _gzip_nf.compress(xml_bytes)
        b64_xml = _b64_nf.b64encode(compressed).decode("ascii")
        body_json = _json_nf.dumps({"dpsXmlGZipB64": b64_xml})

        async with _httpx_nf.AsyncClient(
            cert=(cert_path, key_path),
            timeout=60,
            verify=True,
        ) as client:
            resp = await client.post(
                url,
                content=body_json.encode("utf-8"),
                headers={"Content-Type": "application/json; charset=UTF-8"},
            )

        print(f"[nfse] resposta: HTTP {resp.status_code} | headers: {dict(resp.headers)} | body: {resp.text[:500]!r}")
        if resp.status_code not in (200, 201):
            raise ValueError(f"SNNFSE {resp.status_code}: {resp.text[:500]}")

        # Resposta JSON contém nfseXmlGZipB64 com o XML da NFS-e
        resp_data = resp.json()
        print(f"[nfse] resposta JSON keys: {list(resp_data.keys()) if isinstance(resp_data, dict) else type(resp_data)}")

        nfse_b64 = resp_data.get("nfseXmlGZipB64", "")
        chave = resp_data.get("chaveAcesso", "")
        numero = resp_data.get("numeroNFSe", "")
        url_nf = resp_data.get("linkNFSe", "") or resp_data.get("urlNFSe", "")

        # Se o XML da NFS-e estiver embutido, extrair dados adicionais
        if nfse_b64 and (not chave or not numero):
            try:
                from lxml import etree as _etresp
                nfse_xml = _gzip_nf.decompress(_b64_nf.b64decode(nfse_b64))
                resp_tree = _etresp.fromstring(nfse_xml)
                ns = _NF_NS

                def _find(tag):
                    el = resp_tree.find(f".//{{{ns}}}{tag}")
                    if el is None:
                        el = resp_tree.find(f".//{tag}")
                    return el.text.strip() if el is not None and el.text else ""

                chave  = chave  or _find("chNFSe") or _find("chave")
                numero = numero or _find("nNFSe")  or _find("numero")
                url_nf = url_nf or _find("urlNFSe") or _find("linkNFSe") or ""
            except Exception as _ex_parse:
                print(f"[nfse] aviso: não foi possível parsear XML da resposta: {_ex_parse}")

        return {"chave": chave, "numero": numero, "url": url_nf}

    finally:
        _os_nf.unlink(cert_path)
        _os_nf.unlink(key_path)


# ── Rotas ─────────────────────────────────────────────────────────────────────


@app.get("/admin/nfse/probe-codigo")
async def nfse_probe_codigo(request: _Req_nf, cod: str = "170300", cnpj_toma: str = "27012470000121"):
    """Testa TSCodTribNac contra o SNNFSE. ?cod=XXXXXX&cnpj_toma=CNPJ14digitos"""
    from fastapi.responses import JSONResponse as _JR
    import gzip as _gz, json as _jj, base64 as _b64p
    try:
        key_pem, cert_pem, chain_pem = _nf_load_cert()
        from lxml import etree as _etx
        ns = _NF_NS
        _probe_chave = _nf_chave_acesso(998)
        root = _etx.Element(f"{{{ns}}}DPS", versao="1.00", nsmap={None: ns})
        inf = _etx.SubElement(root, f"{{{ns}}}infDPS", Id="DPS" + _probe_chave)
        def sub(p, t, v=None): e = _etx.SubElement(p, f"{{{ns}}}{t}"); e.text = v; return e
        sub(inf, "tpAmb", _NF_tpAmb)
        sub(inf, "dhEmi", "2026-06-14T12:00:00-03:00")
        sub(inf, "verAplic", "ERP_1.0")
        sub(inf, "serie", "1"); sub(inf, "nDPS", "998")
        sub(inf, "dCompet", "2026-06-01"); sub(inf, "tpEmit", "1"); sub(inf, "cLocEmi", _NF_IBGE)
        prest = sub(inf, "prest"); sub(prest, "CNPJ", _NF_CNPJ)
        sub(prest, "email", _NF_EMAIL)
        rtrib = sub(prest, "regTrib")
        sub(rtrib, "opSimpNac", "1"); sub(rtrib, "regApTribSN", "3"); sub(rtrib, "regEspTrib", "6")
        tom = sub(inf, "toma"); sub(tom, "CNPJ", cnpj_toma); sub(tom, "xNome", "TESTE")
        _e = sub(tom, "end"); _en = sub(_e, "endNac")
        sub(_en, "cMun", _NF_IBGE); sub(_en, "CEP", "88350000")
        sub(_e, "xLgr", "NAO INFORMADO"); sub(_e, "nro", "S/N"); sub(_e, "xBairro", "NAO INFORMADO")
        serv = sub(inf, "serv")
        lp = sub(serv, "locPrest"); sub(lp, "cLocPrestacao", _NF_IBGE)
        cs = sub(serv, "cServ"); sub(cs, "cTribNac", cod); sub(cs, "xDescServ", "Planejamento e organizacao administrativa")
        vals = sub(inf, "valores")
        vsp = sub(vals, "vServPrest"); sub(vsp, "vReceb", "100.00"); sub(vsp, "vServ", "100.00")
        trib = sub(vals, "trib")
        tm = sub(trib, "tribMun"); sub(tm, "tribISSQN", "1"); sub(tm, "tpRetISSQN", "1")
        tot = sub(trib, "totTrib"); sub(tot, "pTotTribSN", "6.00")
        dps_bytes = _etx.tostring(root, xml_declaration=True, encoding="UTF-8")
        signed = _nf_sign_dps(dps_bytes, key_pem, cert_pem)
        with _tmp_nf.NamedTemporaryFile(suffix=".pem", delete=False) as cf:
            cf.write(cert_pem + (chain_pem or b"")); cert_path = cf.name
        with _tmp_nf.NamedTemporaryFile(suffix=".pem", delete=False) as kf:
            kf.write(key_pem); key_path = kf.name
        try:
            body = _jj.dumps({"dpsXmlGZipB64": _b64p.b64encode(_gz.compress(signed)).decode()})
            async with _httpx_nf.AsyncClient(cert=(cert_path, key_path), timeout=30, verify=True) as client:
                r = await client.post(_NF_URLS[_NF_AMB], content=body.encode(), headers={"Content-Type": "application/json; charset=UTF-8"})
            try: rj = r.json()
            except: rj = r.text[:500]
            return _JR(content={"cod": cod, "cnpj_toma": cnpj_toma, "status": r.status_code, "body": rj})
        finally:
            _os_nf.unlink(cert_path); _os_nf.unlink(key_path)
    except Exception as e:
        import traceback
        return _JR(content={"cod": cod, "error": str(e), "trace": traceback.format_exc()[-800:]}, status_code=500)



@app.get("/admin/financeiro/cobrancas/{cob_id}/emitir-nf")
async def financeiro_cobrancas_emitir_nf(
    cob_id: int,
    request: _Req_nf,
    session=_Dep_nf(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in {"admin", "equipe"}:
        return _RR_nf("/login", status_code=303)

    cobranca = session.get(CobrancaMensal, cob_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _RR_nf("/admin/financeiro/cobrancas", status_code=302)

    contrato = session.get(ContratoCliente, cobranca.contrato_id)
    if not contrato:
        return _RR_nf(f"/admin/financeiro/contratos/{cobranca.contrato_id}/cobrancas?erro=Contrato+não+encontrado", status_code=302)

    if cobranca.valor_cents <= 0:
        return _RR_nf(
            f"/admin/financeiro/contratos/{cobranca.contrato_id}/cobrancas?erro=Valor+zero%2C+não+é+possível+emitir+NF",
            status_code=302,
        )

    # Offset para evitar colisão com tentativas anteriores onde a DPS foi recebida
    # pelo SNNFSE mas nenhuma NFS-e foi gerada (assinatura inválida nas tentativas iniciais).
    # nDPS: contador sequencial por série, continua a partir do último DPS do sistema antigo (265)
    n_dps = _nf_proximo_ndps()
    try:
        key_pem, cert_pem, chain_pem = _nf_load_cert()
        dps_xml  = _nf_build_dps(cobranca, contrato, n_dps, session=session)
        signed   = _nf_sign_dps(dps_xml, key_pem, cert_pem)
        print(f"[nfse] XML assinado: {signed.decode('utf-8', errors='replace')[:3000]}")
        resultado = await _nf_enviar(signed, key_pem, cert_pem, chain_pem)

        from datetime import datetime as _dtl
        cobranca.nf_numero  = resultado.get("numero", "")
        cobranca.nf_chave   = resultado.get("chave",  "")
        cobranca.nf_url     = resultado.get("url",    "")
        cobranca.updated_at = _dtl.utcnow()
        session.add(cobranca)
        session.commit()

        nr = cobranca.nf_numero or cobranca.nf_chave or "emitida"
        return _RR_nf(
            f"/admin/financeiro/contratos/{cobranca.contrato_id}/cobrancas?ok=NF+{nr}+emitida+com+sucesso",
            status_code=302,
        )

    except Exception as ex:
        msg = str(ex).replace(" ", "+")[:200]
        print(f"[nfse] erro emissão cob {cob_id}: {ex}")
        return _RR_nf(
            f"/admin/financeiro/contratos/{cobranca.contrato_id}/cobrancas?erro=Erro+NF:+{msg}",
            status_code=302,
        )


@app.get("/admin/financeiro/cobrancas/{cob_id}/nf-ver")
async def financeiro_cobrancas_nf_ver(
    cob_id: int,
    request: _Req_nf,
    session=_Dep_nf(get_session),
):
    ctx = get_tenant_context(request, session)
    if not ctx or ctx.membership.role not in {"admin", "equipe"}:
        return _RR_nf("/login", status_code=303)

    cobranca = session.get(CobrancaMensal, cob_id)
    if not cobranca or cobranca.company_id != ctx.company.id:
        return _RR_nf("/admin/financeiro/cobrancas", status_code=302)

    nf_url = getattr(cobranca, "nf_url", "") or ""
    if nf_url and nf_url.startswith("http"):
        return _RR_nf(nf_url, status_code=302)

    chave = getattr(cobranca, "nf_chave", "") or getattr(cobranca, "nf_numero", "") or "sem chave"
    return _HTML_nf(f"<p>NFS-e emitida. Chave de acesso: <code>{chave}</code></p>")

print("[nfse] ✅ Rotas NFS-e registradas com sucesso")
