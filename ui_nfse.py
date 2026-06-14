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
_NF_CTRIB_NAC     = "170200"           # TSCodTribNac — LC 116 subitem 17.02 (apoio administrativo)
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
        print("[nfse] ✅ Migrations OK")
except Exception as _e_nf_mg:
    print(f"[nfse] migration: {_e_nf_mg}")



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
    return _re_nf.sub(r"\D", "", doc or "")


def _nf_build_dps(cobranca, contrato, n_dps: int) -> bytes:
    """
    Monta o XML DPS sem assinatura.
    Retorna bytes UTF-8.
    """
    ns   = _NF_NS
    dcomp = cobranca.competencia or _date_nf.today().strftime("%Y-%m")
    # competência no formato YYYY-MM → usar primeiro dia do mês
    try:
        dcomp_dt = _dt_nf.strptime(dcomp, "%Y-%m").date()
    except Exception:
        dcomp_dt = _date_nf.today()
    dcomp_str = dcomp_dt.strftime("%Y-%m-%d")  # TSData exige YYYY-MM-DD

    # dhEmi — data/hora de emissão com offset BR
    now_br = _dt_nf.now(_tz_nf(offset=_td_nf(hours=-3)))
    dh_emi = now_br.strftime("%Y-%m-%dT%H:%M:%S") + "-03:00"

    valor_str = f"{cobranca.valor_cents / 100:.2f}"
    chave     = _nf_chave_acesso(n_dps)
    inf_id    = "DPS" + chave

    # ── tomador ───────────────────────────────────────────────────────────────
    doc_toma = _nf_limpa_cnpj(
        getattr(contrato, "documento_cliente", "")
        or getattr(cobranca,  "documento_cliente", "")
        or ""
    )
    nome_toma = (contrato.nome_cliente or "NÃO INFORMADO").upper()

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
    _sub(inf, "tpEmit",   "1")       # 1 = prestador
    _sub(inf, "cLocEmi",  _NF_IBGE)

    # ── prestador ─────────────────────────────────────────────────────────────
    prest = _sub(inf, "prest")
    _sub(prest, "CNPJ",    _NF_CNPJ)
    _sub(prest, "IM",      _NF_IM)
    _sub(prest, "xNome",   _NF_RAZAO[:150])
    _sub(prest, "email",   _NF_EMAIL)
    regTrib = _sub(prest, "regTrib")
    _sub(regTrib, "opSimpNac",   "1")  # 1 = optante Simples Nacional
    _sub(regTrib, "regApTribSN", "3")  # 3 = ME/EPP tributada pelo Simples Nacional
    _sub(regTrib, "regEspTrib",  "6")  # 6 = ME/EPP – Simples Nacional

    # ── tomador ───────────────────────────────────────────────────────────────
    toma = _sub(inf, "toma")
    if len(doc_toma) == 14:
        _sub(toma, "CNPJ", doc_toma)
    elif len(doc_toma) == 11:
        _sub(toma, "CPF", doc_toma)
    else:
        # sem documento — usa NI (não identificado) com CNPJ zerado
        _sub(toma, "CNPJ", "00000000000000")
    _sub(toma, "xNome", nome_toma[:150])

    # ── serviço ───────────────────────────────────────────────────────────────
    serv     = _sub(inf, "serv")
    locPrest = _sub(serv, "locPrest")
    _sub(locPrest, "cLocPrestacao", _NF_IBGE)

    desc  = (contrato.servicos or contrato.nome_contrato or "Serviços administrativos").strip()
    cServ = _sub(serv, "cServ")
    _sub(cServ, "cTribNac",  _NF_CTRIB_NAC)
    _sub(cServ, "xDescServ", desc[:2000])

    # ── valores ───────────────────────────────────────────────────────────────
    vals  = _sub(inf, "valores")
    vServPrest = _sub(vals, "vServPrest")
    _sub(vServPrest, "vReceb", valor_str)
    _sub(vServPrest, "vServ",  valor_str)

    # tribMun deve estar dentro do grupo obrigatório "trib"
    trib = _sub(vals, "trib")
    tribMun = _sub(trib, "tribMun")
    _sub(tribMun, "tribISSQN",  "3")  # 3 = Simples Nacional
    _sub(tribMun, "tpRetISSQN", "1")  # 1 = Não retido
    totTrib = _sub(trib, "totTrib")
    _sub(totTrib, "pTotTribSN", "6.00")  # alíquota Simples Nacional

    return _etloc.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=False)


# ── Assinatura XML ────────────────────────────────────────────────────────────

def _nf_sign_dps(dps_bytes: bytes, key_pem: bytes, cert_pem: bytes) -> bytes:
    """
    Assina digitalmente o XML DPS usando enveloped signature (XMLDSig).
    Retorna o XML assinado como bytes.
    """
    from lxml import etree as _etloc2
    from signxml import XMLSigner, methods
    tree   = _etloc2.fromstring(dps_bytes)
    signer = XMLSigner(
        method=methods.enveloped,
        digest_algorithm="sha256",
        signature_algorithm="rsa-sha256",
    )
    signed = signer.sign(
        tree,
        key=key_pem,
        cert=cert_pem,
        reference_uri="#" + tree.find(f"{{{_NF_NS}}}infDPS").get("Id"),
    )
    import re as _re_sign
    signed_bytes = _etloc2.tostring(signed, xml_declaration=True, encoding="UTF-8")

    # SNNFSE rejeita qualquer prefixo de namespace (E1228).
    # O signxml adiciona ds:Signature; convertemos para namespace padrão.
    # Isso é seguro: a Signature é excluída do digest pela transform enveloped-signature.
    _xmldsig_ns = b"http://www.w3.org/2000/09/xmldsig#"
    _m = _re_sign.search(rb'xmlns:(\w+)="http://www\.w3\.org/2000/09/xmldsig#"', signed_bytes)
    if _m:
        _pfx = _m.group(1)  # e.g. b"ds"
        signed_bytes = signed_bytes.replace(
            b'xmlns:' + _pfx + b'="http://www.w3.org/2000/09/xmldsig#"',
            b'xmlns="http://www.w3.org/2000/09/xmldsig#"',
        )
        signed_bytes = _re_sign.sub(b'<' + _pfx + b':', b'<', signed_bytes)
        signed_bytes = _re_sign.sub(b'</' + _pfx + b':', b'</', signed_bytes)

    # Também remove qualquer prefixo residual do namespace NFS-e (ns0: etc.)
    _nfse_ns_b = _NF_NS.encode()
    _m2 = _re_sign.search(rb'xmlns:(\w+)="' + _re_sign.escape(_nfse_ns_b) + rb'"', signed_bytes)
    if _m2:
        _pfx2 = _m2.group(1)
        signed_bytes = signed_bytes.replace(
            b'xmlns:' + _pfx2 + b'="' + _nfse_ns_b + b'"',
            b'xmlns="' + _nfse_ns_b + b'"',
        )
        signed_bytes = _re_sign.sub(b'<' + _pfx2 + b':', b'<', signed_bytes)
        signed_bytes = _re_sign.sub(b'</' + _pfx2 + b':', b'</', signed_bytes)

    return signed_bytes


# ── Envio via mTLS ────────────────────────────────────────────────────────────

async def _nf_enviar(xml_bytes: bytes, key_pem: bytes, cert_pem: bytes) -> dict:
    """
    Envia o XML DPS assinado para a API SNNFSE via mTLS.
    Retorna dict com chave, numero, url ou lança exceção com mensagem de erro.
    """
    url = _NF_URLS[_NF_AMB]
    print(f"[nfse] POST {url} (ambiente={_NF_AMB})")

    # httpx aceita cert como (cert_file, key_file) ou como arquivos temporários
    with _tmp_nf.NamedTemporaryFile(suffix=".pem", delete=False) as cf:
        cf.write(cert_pem)
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

    n_dps = cobranca.id
    try:
        key_pem, cert_pem, _chain = _nf_load_cert()
        dps_xml  = _nf_build_dps(cobranca, contrato, n_dps)
        signed   = _nf_sign_dps(dps_xml, key_pem, cert_pem)
        resultado = await _nf_enviar(signed, key_pem, cert_pem)

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
