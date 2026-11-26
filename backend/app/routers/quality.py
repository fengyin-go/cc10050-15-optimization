"""解析质量一致性相关的薄路由：迟到样本补报、复测邀请决策、接单重放、审计确认。

业务判断全部在 :class:`app.services.quality.QualityBoard` 与各模块服务中完成。
这里额外容忍多种常见字段命名，方便不同调用方按同一业务契约接入。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services.quality import quality_board

router = APIRouter(prefix="/api", tags=["解析质量一致性"])


async def _body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return {}
    return payload


@router.get("/quality/board")
def quality_board_view() -> dict[str, Any]:
    return quality_board.board()


@router.get("/quality/rule")
def quality_rule() -> dict[str, Any]:
    board = quality_board.board()
    return {"ok": True, "rule": board["rule"]}


@router.get("/quality/evaluate")
def quality_evaluate(
    site: str,
    template: str | None = None,
    version: str | None = None,
    period: str | None = None,
) -> dict[str, Any]:
    from app.services.quality import PERIOD, TEMPLATE_NAME, TEMPLATE_VERSION

    result = quality_board.evaluate(
        site=site,
        template=template or TEMPLATE_NAME,
        version=version or TEMPLATE_VERSION,
        period=period or PERIOD,
    )
    return {"ok": True, "evaluation": result}


@router.get("/quality/orders")
def quality_orders() -> dict[str, Any]:
    return {"ok": True, "orders": [quality_board.order_view(o) for o in quality_board.orders]}


@router.get("/retest-invitations")
def retest_invitations() -> dict[str, Any]:
    return {"ok": True, "items": [quality_board.order_view(o, with_details=True) for o in quality_board.orders]}


@router.get("/retest_orders")
def retest_orders_alias() -> dict[str, Any]:
    return {"ok": True, "items": [quality_board.order_view(o, with_details=True) for o in quality_board.orders]}


@router.get("/quality/orders/{ref}")
def quality_order(ref: str) -> dict[str, Any]:
    order = quality_board.order_ref(ref)
    if order is None:
        return {"ok": False, "message": f"复测邀请 {ref} 不存在"}
    return {"ok": True, "order": quality_board.order_view(order, with_details=True)}


@router.post("/quality/late-samples")
async def quality_late_samples(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


# 语义别名：调用方可能按模块前缀组织补报入口。
@router.post("/parse_audit/late-samples")
async def audit_late_samples(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/parse_audit/late-report")
async def audit_late_report(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/sample_store/late-samples")
async def sample_late_samples(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/sample_store/late-report")
async def sample_late_report(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/sample_store/report")
async def sample_report_alias(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/quality/report-late")
async def quality_report_late_alias(request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/quality/orders/{ref}/continue")
async def continue_order(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    remark = payload.get("remark")
    return quality_board.decide_invitation(ref, "continue", remark)


@router.post("/quality/orders/{ref}/cancel")
async def cancel_order(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    return quality_board.decide_invitation(ref, "cancel", payload.get("remark"))


@router.post("/quality/invitations/{ref}/continue")
async def continue_invitation(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    return quality_board.decide_invitation(ref, "continue", payload.get("remark"))


@router.post("/quality/invitations/{ref}/cancel")
async def cancel_invitation(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    return quality_board.decide_invitation(ref, "cancel", payload.get("remark"))


@router.post("/quality/orders/{ref}/claim")
async def claim_order(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    template_id = payload.get("template_id")
    return quality_board.claim_and_replay(ref, template_id=template_id, payload=payload)


@router.post("/quality/orders/{ref}/replay")
async def replay_order(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    return quality_board.claim_and_replay(ref, payload=payload)


@router.post("/quality/orders/{ref}/confirm")
async def confirm_order(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    version = payload.get("version") or payload.get("template_version") or payload.get("replay_version")
    return quality_board.confirm_upgrade(ref, version)


@router.post("/quality/invitations/{ref}/confirm-upgrade")
async def confirm_upgrade_alias(ref: str, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    version = payload.get("version") or payload.get("template_version") or payload.get("replay_version")
    return quality_board.confirm_upgrade(ref, version)


@router.get("/quality/retest-desk")
def retest_desk() -> dict[str, Any]:
    return quality_board.retest_desk()


@router.get("/quality/hit-records")
def hit_records(site: str = "北站", limit: int = 500) -> dict[str, Any]:
    return {"ok": True, "site": site, "records": quality_board.hit_records_view(site, limit)}


@router.post("/page_parser/{entry_id}/claim-retest")
async def parser_claim_retest(entry_id: int, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    ref = payload.get("invitation") or payload.get("code") or payload.get("ref")
    return quality_board.claim_and_replay(ref, template_id=entry_id, payload=payload)


# ---- 以审计单 id 为路径的语义别名（与通用 /actions 入口等价） ----

@router.post("/parse_audit/{entry_id}/late-samples")
async def audit_entry_late_samples(entry_id: int, request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/parse_audit/{entry_id}/late-report")
async def audit_entry_late_report(entry_id: int, request: Request) -> dict[str, Any]:
    return quality_board.report_late_samples(await _body(request))


@router.post("/parse_audit/{entry_id}/continue")
async def audit_entry_continue(entry_id: int, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    ref = payload.get("invitation") or payload.get("code")
    order = quality_board.order_for_audit(entry_id)
    return quality_board.decide_invitation(ref or (order["code"] if order else None), "continue")


@router.post("/parse_audit/{entry_id}/cancel")
async def audit_entry_cancel(entry_id: int, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    ref = payload.get("invitation") or payload.get("code")
    order = quality_board.order_for_audit(entry_id)
    return quality_board.decide_invitation(ref or (order["code"] if order else None), "cancel")


@router.post("/parse_audit/{entry_id}/confirm-upgrade")
async def audit_entry_confirm(entry_id: int, request: Request) -> dict[str, Any]:
    payload = await _body(request)
    order = quality_board.order_for_audit(entry_id)
    ref = payload.get("invitation") or payload.get("code") or (order["code"] if order else None)
    version = payload.get("version") or payload.get("template_version")
    return quality_board.confirm_upgrade(ref, version)
