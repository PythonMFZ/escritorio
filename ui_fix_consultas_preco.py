# ============================================================================
# PATCH — Fix preços /consultas usando ProdutoPreco
# ============================================================================
# Salve como ui_fix_consultas_preco.py

import math as _math_fix

def _price_cents_v2(cost_cents: int, markup_pct: int,
                    product_code: str = "", company_id: int = 0) -> int:
    """Prioriza ProdutoPreco; fallback para cálculo cost+markup."""
    if product_code and company_id:
        try:
            from sqlmodel import Session as _SPC2
            with _SPC2(engine) as _s2:
                _pp = _s2.exec(
                    select(ProdutoPreco)
                    .where(ProdutoPreco.company_id == company_id,
                           ProdutoPreco.codigo == f"compliance_{product_code}",
                           ProdutoPreco.ativo == True)
                ).first()
                if _pp and _pp.creditos > 0:
                    return _pp.creditos * 100
        except Exception:
            pass
    markup = max(50, int(markup_pct or 50))
    return int(_math_fix.ceil(cost_cents * (1.0 + markup / 100.0)))

# Sobrescreve a função global
_price_cents = _price_cents_v2
print("[fix] _price_cents atualizado para usar ProdutoPreco")
