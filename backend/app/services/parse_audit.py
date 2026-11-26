"""解析质量审计领域服务：审计解析模板的字段命中率与失败分布，负责命中率劣化告警与沉淀。

数据链路位置：质量审计层，消费页面解析模板上报的命中数据与失败隔离区的
失败原因分布，产出的审计结论供模板版本升级决策。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.quality import quality_board
from app.store import store

# 解析质量一致性扩展动作（复测邀请状态机）。
_CONTINUE_ACTIONS = {
    "继续原邀请", "继续邀请", "继续", "安排复测", "继续原邀请并安排复测",
}
_CANCEL_ACTIONS = {"取消邀请", "取消原邀请", "取消"}
_CONFIRM_ACTIONS = {"确认升级建议", "确认升级", "确认升级建议并结案", "审计确认升级建议"}
_LATE_ACTIONS = {"迟到样本补报", "补报迟到样本", "迟到补报"}
_ISSUE_ACTIONS = {"发出复测邀请", "发起复测", "安排复测邀请"}


class ParseAuditService(BaseModuleService):
    MODULE = "parse_audit"
    ENTITY = "审计明细"
    OPERATION_TERM = "解析"
    LIST_FIELDS = [
        "审计时间", "解析模板", "样本总数", "字段命中率", "失败原因分布",
        "站点名称", "模板版本", "命中数", "触发规则版本",
    ]
    REQUIRED_FIELDS = ["审计时间", "解析模板", "样本总数"]
    STATUS_ORDER = ["正常", "命中率下降", "解析异常"]
    ACTION_RULES = {"查看详情": "命中率下降", "忽略告警": "解析异常"}
    NEGATIVE_ACTIONS = ["忽略告警"]

    # ---- 复测一致性：读取前同步当前实际口径 ----

    def list_entries(self, **kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        quality_board.ensure_seed()
        quality_board.sync_audit_ticket()
        return super().list_entries(**kwargs)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        quality_board.ensure_seed()
        quality_board.sync_audit_ticket()
        return super().get_entry(entry_id)

    def run_action(
        self, entry_id: int, action: str, params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        params = params or {}
        quality_board.ensure_seed()

        if action in _LATE_ACTIONS:
            result = quality_board.report_late_samples(params)
            ticket = quality_board.order_for_audit(entry_id)
            row = store.find(self.MODULE, entry_id) or store.find(self.MODULE, 4)
            return row, result["message"]

        if action in _ISSUE_ACTIONS:
            # 严格按该审计单的站点/版本口径判定，样本不足或已恢复都不发邀请。
            row = store.find(self.MODULE, entry_id)
            site = str(params.get("site") or (row or {}).get("站点名称") or "北站")
            evaluation = quality_board.evaluate(site)
            if not evaluation["meets_min_samples"]:
                return None, (
                    f"{site} 站当前仅 {evaluation['sample_count']} 个去重样本，"
                    f"不足最低样本 {evaluation['min_samples']}，不应降级，也不能拼量发出复测"
                )
            if not evaluation["degraded"]:
                return None, (
                    f"{site} 站当前命中率 {evaluation['rate_text']} 已不低于阈值 "
                    f"{evaluation['threshold_text']}，触发条件不成立，不新发复测邀请；"
                    f"若存在原邀请请继续原邀请或取消"
                )
            return row, "该口径已存在生效中的复测邀请，请在原邀请上继续或取消"

        if action in _CONTINUE_ACTIONS or action in _CANCEL_ACTIONS or action in _CONFIRM_ACTIONS:
            order = (
                quality_board.order_for_audit(entry_id)
                or quality_board.order_ref(params.get("invitation") or params.get("code"))
                or quality_board.active_order()
            )
            ref = order["code"] if order else params.get("invitation")
            if action in _CONTINUE_ACTIONS:
                result = quality_board.decide_invitation(ref, "continue", params.get("remark"))
            elif action in _CANCEL_ACTIONS:
                result = quality_board.decide_invitation(ref, "cancel", params.get("remark"))
            else:
                version = params.get("version") or params.get("template_version")
                result = quality_board.confirm_upgrade(ref, version)
            row = store.find(self.MODULE, entry_id) or store.find(self.MODULE, 4)
            if not result.get("ok"):
                return None, result["message"]
            return row, result["message"]

        return super().run_action(entry_id, action, params)

    # ---- 业务扩展：命中率审计与劣化告警 ----

    def record_hit_rate(self, template: str, total: int, hit: int) -> dict[str, Any]:
        """记录一次模板命中率审计明细。"""
        if total <= 0:
            return {"ok": False, "message": "样本总数必须为正数"}
        rate = hit / total
        rows = store.rows(self.MODULE)
        aid = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        status = "正常" if rate >= 0.9 else ("命中率下降" if rate >= 0.6 else "解析异常")
        rows.append({
            "id": aid,
            "审计时间": datetime.now(timezone.utc).isoformat(),
            "解析模板": template,
            "样本总数": str(total),
            "字段命中率": f"{rate:.2%}",
            "失败原因分布": "" if rate >= 0.9 else "选择器失配/字段缺失",
            "status": status,
            "pending": status != "正常",
            "abnormal": status == "解析异常",
        })
        return {"ok": True, "message": "审计明细已记录", "audit_id": aid, "rate": f"{rate:.2%}"}

    def detect_degradation(self, entry_id: int) -> dict[str, Any]:
        """对比历史审计检测模板命中率劣化趋势。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "审计明细不存在"}
        template = entry.get("解析模板", "")
        history = [
            r for r in store.rows(self.MODULE)
            if r.get("解析模板") == template and r.get("id") != entry.get("id")
        ]
        current = float(str(entry.get("字段命中率", "0%")).rstrip("%") or 0)
        worst = max(
            (float(str(r.get("字段命中率", "0%")).rstrip("%") or 0) for r in history),
            default=current,
        )
        degraded = worst - current >= 0.15
        if degraded:
            entry["status"] = "命中率下降"
            entry["pending"] = True
        return {
            "ok": True,
            "message": "劣化检测完成",
            "degraded": degraded,
            "current": f"{current:.2%}",
            "best_before": f"{worst:.2%}",
        }

    def summarize_failures(self, entry_id: int) -> dict[str, Any]:
        """汇总失败隔离区中该模板的失败原因分布。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "审计明细不存在"}
        reasons: dict[str, int] = {}
        for q in store.rows("failure_quarantine"):
            if q.get("失败阶段") == "解析":
                reason = str(q.get("失败原因", "") or "未知")
                reasons[reason] = reasons.get(reason, 0) + 1
        top = sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:3]
        entry["失败原因分布"] = ";".join(f"{k}:{v}" for k, v in top)
        return {"ok": True, "message": "失败分布已汇总", "distribution": top}

    def recommend_template_upgrade(self, entry_id: int) -> dict[str, Any]:
        """命中率持续下降时建议模板升级版本。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "审计明细不存在"}
        if entry.get("status") == "正常":
            return {"ok": True, "message": "模板健康，无需升级", "upgrade": False}
        template = next(
            (t for t in store.rows("page_parser")
             if t.get("模板名称") == entry.get("解析模板", "")), None
        )
        if template is None:
            return {"ok": False, "message": "关联模板不存在"}
        return {
            "ok": True,
            "message": "建议升级模板解析版本",
            "upgrade": True,
            "template": template.get("模板名称", ""),
            "current_version": template.get("解析版本", ""),
        }

    def publish_metrics(self, entry_id: int) -> dict[str, Any]:
        """把审计结论发布到采集量指标作为解析量口径。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "审计明细不存在"}
        metrics = store.rows("collect_metrics")
        row = next((m for m in metrics if m.get("站点名称") == entry.get("解析模板", "")), None)
        if row is None:
            mid = max((int(m.get("id", 0)) for m in metrics), default=0) + 1
            metrics.append({
                "id": mid,
                "统计时间": datetime.now(timezone.utc).isoformat(),
                "站点名称": entry.get("解析模板", ""),
                "抓取量": entry.get("样本总数", "0"),
                "解析量": entry.get("样本总数", "0"),
                "产出量": "0",
                "status": entry.get("status", "正常"),
                "pending": True,
                "abnormal": entry.get("status") == "解析异常",
            })
        else:
            row["解析量"] = entry.get("样本总数", "0")
            row["统计时间"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "message": "审计结论已发布指标"}

    def audit_health(self, days: int = 1) -> dict[str, Any]:
        """输出审计批次健康度统计。"""
        rows = store.rows(self.MODULE)
        abnormal = sum(1 for r in rows if r.get("status") == "解析异常")
        degraded = sum(1 for r in rows if r.get("status") == "命中率下降")
        return {
            "ok": True,
            "message": "审计健康度统计完成",
            "total": len(rows),
            "abnormal": abnormal,
            "degraded": degraded,
        }
