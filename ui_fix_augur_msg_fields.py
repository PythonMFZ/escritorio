# ── Fix: AugurMensagem session_id / user_id ──────────────────────────────────
# _b6v2_fix_augur_mensagem() definiu a nova classe como variável LOCAL dentro
# da função, então globals()['AugurMensagem'] continuou apontando para a classe
# antiga sem session_id. Este arquivo redefine no escopo de exec (= global).

from typing import Optional as _OAM
from sqlmodel import SQLModel as _SMAM, Field as _FAM

class AugurMensagem(_SMAM, table=True):  # noqa: F811
    __tablename__  = "augurmensagem"
    __table_args__ = {"extend_existing": True}
    id:         _OAM[int] = _FAM(default=None, primary_key=True)
    company_id: int        = _FAM(index=True)
    client_id:  int        = _FAM(index=True)
    role:       str        = _FAM(default="user")
    content:    str        = _FAM(default="")
    feedback:   _OAM[int]  = _FAM(default=None)
    created_at: str        = _FAM(default="")
    user_id:    int        = _FAM(default=0, index=True)
    session_id: int        = _FAM(default=0, index=True)

print("[fix_augur_msg_fields] ✅ AugurMensagem redefinida no escopo global com session_id e user_id")
