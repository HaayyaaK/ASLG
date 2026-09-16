"""The Procedure Rule catalogue — "the brain, as data".

Every rule ships from seed_procedure_rules.sql DISABLED, carrying a legal
citation and a source_tier that is at best 'official_inferred' (from
professional secondary sources), never 'official_verified' at seed time —
see Phase 1 blueprint section 2.3 for exactly why (e.g. the Cassation
appeal deadline: two professional guides disagree, 30 vs 60 days, and
BOTH candidate rules are seeded disabled specifically because of that
conflict). Enabling a rule here is the one action in this entire feature
that asserts a legal fact, so it requires:

  1. `rules_admin` permission at 'full' (Admin, or Lawyer at 'view' only —
     see the matrix in db/migration_procedural_intelligence.sql section 5);
  2. ALSO `role in ('Admin',) or (role == 'Lawyer' and is_owner)` — a
     second, narrower gate on top of the module permission itself, because
     a non-owner Lawyer with 'full' would otherwise be enough (there isn't
     one in the seeded matrix, but a firm could grant one later);
  3. an explicit `confirm: true` in the request body, not merely holding
     the permission — mirrors the pattern this codebase already uses for
     other consequential confirmations (DatabaseResetRequest.confirm_phrase).

is_enabled is NEVER set true anywhere else in this codebase.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..database import get_db
from ..deps import get_current_user, get_permission_level
from ..models import ProcedureRule, User
from ..schemas import ProcedureRuleOut, ProcedureRuleVerifyRequest

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _require_rules_admin(db: Session, user: User, *levels: str) -> str:
    level = get_permission_level(db, user.role_id, "rules_admin")
    if level == "none" or (levels and level not in levels):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to the Procedure Rule catalogue")
    return level


def _assert_may_verify(user: User) -> None:
    if user.role.code == "Admin":
        return
    if user.role.code == "Lawyer" and user.is_owner:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Only Admin or a firm-owner Lawyer may enable a procedure rule")


def _to_out(r: ProcedureRule) -> ProcedureRuleOut:
    return ProcedureRuleOut(
        id=r.id, code=r.code, version=r.version, case_type_id=r.case_type_id,
        court_level_code=r.court_level_code,
        trigger_procedure_type_id=r.trigger_procedure_type_id, trigger_procedure_code=r.trigger_procedure_type.code,
        expected_procedure_type_id=r.expected_procedure_type_id, expected_procedure_code=r.expected_procedure_type.code,
        deadline_days=r.deadline_days, day_basis=r.day_basis, counts_from=r.counts_from,
        responsible_role_code=r.responsible_role_code,
        legal_basis_ar=r.legal_basis_ar, legal_basis_en=r.legal_basis_en, legal_citation=r.legal_citation,
        source_url=r.source_url, source_tier=r.source_tier, is_enabled=r.is_enabled,
        verified_by_user_id=r.verified_by_user_id,
        verified_by_name_ar=r.verifier.name_ar if r.verifier else None,
        verified_by_name_en=r.verifier.name_en if r.verifier else None,
        verified_at=r.verified_at, effective_from=r.effective_from, effective_to=r.effective_to, notes=r.notes,
    )


@router.get("", response_model=list[ProcedureRuleOut])
def list_rules(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_rules_admin(db, user)
    rows = (
        db.query(ProcedureRule)
        .options(joinedload(ProcedureRule.trigger_procedure_type), joinedload(ProcedureRule.expected_procedure_type), joinedload(ProcedureRule.verifier))
        .order_by(ProcedureRule.code, ProcedureRule.version)
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("/{rule_id}/verify", response_model=ProcedureRuleOut)
def verify_rule(
    rule_id: int, payload: ProcedureRuleVerifyRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Enable a rule. This is the ONLY place in the codebase that ever sets
    is_enabled=1 + verified_by_user_id + verified_at together, and it is
    audit-logged unconditionally (never best-effort) — a failed audit write
    here must be visible, unlike the notification engine's own
    best-effort logging."""
    _require_rules_admin(db, user, "full")
    _assert_may_verify(user)
    if not payload.confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirm must be true to enable a procedure rule")

    rule = db.get(ProcedureRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    if rule.source_tier == "unverified":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This rule's source_tier is 'unverified' — confirm the legal citation against the "
            "primary statute text and update source_tier to 'official_verified' before enabling it "
            "(see the rule's own `notes` for what specifically needs checking).",
        )

    rule.is_enabled = True
    rule.verified_by_user_id = user.id
    rule.verified_at = datetime.utcnow()
    if payload.notes:
        rule.notes = payload.notes
    db.commit()
    db.refresh(rule)

    log_activity(
        db, user.id, "procedure_rule_verify", entity_type="procedure_rule", entity_id=rule.id,
        meta={"code": rule.code, "version": rule.version, "legal_citation": rule.legal_citation},
    )
    return _to_out(rule)


@router.post("/{rule_id}/disable", response_model=ProcedureRuleOut)
def disable_rule(rule_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Disabling is deliberately lighter-weight than enabling — reversing a
    mistake should never be harder than making one — but still requires the
    same module permission and role gate as verify, since it is still a
    change to what the firm treats as legally binding guidance."""
    _require_rules_admin(db, user, "full")
    _assert_may_verify(user)
    rule = db.get(ProcedureRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    rule.is_enabled = False
    db.commit()
    db.refresh(rule)
    log_activity(db, user.id, "procedure_rule_disable", entity_type="procedure_rule", entity_id=rule.id,
                 meta={"code": rule.code, "version": rule.version})
    return _to_out(rule)
