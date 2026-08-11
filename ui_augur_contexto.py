# ============================================================================
# ui_augur_contexto.py — Augur: contexto BSC + Ações Corretivas + Orçamento
# ============================================================================
# Injeta no client_data:
#   bsc_context          — perspectivas / objetivos / KPIs com semáforo atual
#   acoes_corretivas     — ações abertas/em andamento com prazo e prioridade
#   (orcamento_resumo já coberto por ui_orcamento.py)
# ============================================================================

from datetime import datetime as _dt_ac
from sqlmodel import select as _sel_ac

# ── helpers internos ──────────────────────────────────────────────────────────

def _ac_semaforo(realizado, meta, polaridade, tol_am, tol_vm):
    """Retorna 'verde'|'amarelo'|'vermelho'."""
    if realizado is None or meta is None or meta == 0:
        return "cinza"
    pct = (realizado / meta) * 100 if polaridade == "maior" else (2 - realizado / meta) * 100
    if pct >= 100 - tol_am:
        return "verde"
    if pct >= 100 - tol_vm:
        return "amarelo"
    return "vermelho"


def _ac_build_bsc_context(session, company_id: int, client_id: int) -> str:
    """Monta texto descritivo do BSC para o Augur."""
    from sqlmodel import select as _s
    try:
        perspectivas = session.exec(
            _s(BSCPerspectiva)
            .where(BSCPerspectiva.company_id == company_id,
                   BSCPerspectiva.client_id == client_id)
            .order_by(BSCPerspectiva.ordem)
        ).all()
    except Exception:
        return ""

    if not perspectivas:
        return ""

    lines = ["=== BSC — BALANCED SCORECARD ==="]
    hoje = _dt_ac.utcnow()
    periodo_atual = hoje.strftime("%Y-%m")

    for p in perspectivas:
        lines.append(f"\n[{p.icone or ''} {p.nome}]")
        try:
            objetivos = session.exec(
                _s(BSCObjetivo)
                .where(BSCObjetivo.perspectiva_id == p.id,
                       BSCObjetivo.company_id == company_id)
            ).all()
        except Exception:
            continue

        for obj in objetivos:
            lines.append(f"  Objetivo: {obj.titulo}")
            try:
                indicadores = session.exec(
                    _s(BSCIndicador)
                    .where(BSCIndicador.objetivo_id == obj.id,
                           BSCIndicador.company_id == company_id)
                ).all()
            except Exception:
                continue

            for ind in indicadores:
                # Busca último lançamento (período atual ou anterior)
                try:
                    lanc = session.exec(
                        _s(BSCLancamento)
                        .where(BSCLancamento.indicador_id == ind.id,
                               BSCLancamento.company_id == company_id)
                        .order_by(BSCLancamento.periodo.desc())
                        .limit(1)
                    ).first()
                except Exception:
                    lanc = None

                realizado = float(lanc.valor) if lanc and lanc.valor is not None else None
                meta = float(ind.meta_valor) if ind.meta_valor is not None else None
                sem = _ac_semaforo(
                    realizado, meta,
                    ind.polaridade or "maior",
                    float(ind.tol_amarelo or 10),
                    float(ind.tol_vermelho or 25)
                )
                sem_emoji = {"verde": "🟢", "amarelo": "🟡", "vermelho": "🔴"}.get(sem, "⚪")
                valor_str = f"{realizado:,.2f}" if realizado is not None else "—"
                meta_str = f"{meta:,.2f}" if meta is not None else "—"
                periodo_str = f" ({lanc.periodo})" if lanc else " (sem dados)"
                lines.append(
                    f"    {sem_emoji} {ind.nome}: {valor_str} {ind.unidade or ''}"
                    f" / meta {meta_str}{periodo_str}"
                )

    return "\n".join(lines)


def _ac_build_acoes_context(session, company_id: int, client_id: int) -> str:
    """Monta texto com ações corretivas abertas/em andamento."""
    try:
        acoes = session.exec(
            _sel_ac(MeetingAcao)
            .where(
                MeetingAcao.company_id == company_id,
                MeetingAcao.client_id == client_id,
                MeetingAcao.status.in_(["aberta", "em_andamento"])
            )
            .order_by(MeetingAcao.prazo)
        ).all()
    except Exception:
        return ""

    if not acoes:
        return ""

    hoje = _dt_ac.utcnow().date()
    lines = [f"=== AÇÕES CORRETIVAS EM ABERTO ({len(acoes)}) ==="]
    for a in acoes:
        pri_emoji = {"alta": "🔴", "media": "🟡", "baixa": "🟢"}.get(a.prioridade or "", "⚪")
        status_label = "Aberta" if a.status == "aberta" else "Em andamento"
        prazo_str = ""
        if a.prazo:
            try:
                prazo_d = _dt_ac.strptime(str(a.prazo)[:10], "%Y-%m-%d").date()
                delta = (prazo_d - hoje).days
                if delta < 0:
                    prazo_str = f" ⚠️ ATRASADA {-delta}d"
                elif delta == 0:
                    prazo_str = " ⚠️ VENCE HOJE"
                else:
                    prazo_str = f" (prazo: {prazo_d.strftime('%d/%m/%Y')})"
            except Exception:
                prazo_str = f" (prazo: {a.prazo})"
        owner_str = f" | resp: {a.owner}" if a.owner else ""
        lines.append(
            f"  {pri_emoji} [{status_label}] {a.descricao[:120]}{prazo_str}{owner_str}"
        )

    return "\n".join(lines)


# ── Wrapper que injeta os novos contextos no chain ────────────────────────────

_prev_enriquecer_ac = _enriquecer_client_data  # type: ignore[name-defined]


def _enriquecer_com_augur_contexto(session, company_id: int, client_id: int, client, client_data: dict) -> dict:
    data = _prev_enriquecer_ac(session, company_id, client_id, client, client_data)

    # BSC das novas tabelas — sobrescreve qualquer bsc_context anterior
    try:
        bsc_txt = _ac_build_bsc_context(session, company_id, client_id)
        if bsc_txt:
            data["bsc_context"] = bsc_txt
    except Exception:
        pass

    # Ações corretivas abertas
    try:
        ac_txt = _ac_build_acoes_context(session, company_id, client_id)
        if ac_txt:
            data["acoes_corretivas"] = ac_txt
    except Exception:
        pass

    return data


_enriquecer_client_data = _enriquecer_com_augur_contexto  # type: ignore[assignment]

print("[augur_contexto] ✅ Contexto BSC + Ações Corretivas registrado no Augur.")
