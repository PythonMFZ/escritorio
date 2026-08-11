# ============================================================================
# ui_augur_cliente.py — Enriquece contexto Augur com reuniões recentes
# ============================================================================
# Adiciona resumos das reuniões mais recentes do cliente à cadeia de
# enriquecimento do Augur, complementando BSC e ações já presentes.
# ============================================================================

from sqlmodel import select as _sel_ac2

def _ac2_build_meetings_context(session, company_id: int, client_id: int) -> str:
    try:
        q = (
            _sel_ac2(Meeting)
            .where(Meeting.company_id == company_id)
            .where(Meeting.client_id == client_id)
            .order_by(Meeting.date.desc())
            .limit(5)
        )
        meetings = session.exec(q).all()
        if not meetings:
            return ""
        lines = ["Reuniões recentes:"]
        for m in meetings:
            acoes_q = _sel_ac2(MeetingAcao).where(
                MeetingAcao.meeting_id == m.id,
                MeetingAcao.status.in_(("aberta", "em_andamento")),
            )
            n_acoes = len(session.exec(acoes_q).all())
            resumo = (m.summary or m.transcript or "")[:200].replace("\n", " ").strip()
            entry = f"- {m.date} | {m.title or 'sem título'}"
            if resumo:
                entry += f" — {resumo}…"
            if n_acoes:
                entry += f" [{n_acoes} ações abertas]"
            lines.append(entry)
        return "\n".join(lines)
    except Exception:
        return ""

# Registra na cadeia de enriquecimento
try:
    _prev_enriquecer_ac2 = _enriquecer_client_data

    def _enriquecer_com_reunioes(session, company_id, client_id, client, client_data):
        data = _prev_enriquecer_ac2(session, company_id, client_id, client, client_data)
        try:
            txt = _ac2_build_meetings_context(session, company_id, client_id)
            if txt:
                data["reunioes_recentes"] = txt
        except Exception:
            pass
        return data

    _enriquecer_client_data = _enriquecer_com_reunioes
    print("[augur_cliente] ✅ Contexto de reuniões adicionado ao Augur.")
except Exception as _e_ac2:
    print(f"[augur_cliente] ⚠️ Erro: {_e_ac2}")

print("[augur_cliente] ✅ Módulo augur_cliente carregado.")
