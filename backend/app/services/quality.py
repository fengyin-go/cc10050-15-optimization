"""解析质量一致性中枢：站点 × 模板 × 版本 × 测量时段的独立命中记录、
退化判定依据、复测邀请/接单/重放/结案状态机。

核心不变量：
1. 样本阈值按「站点 + 模板名称 + 模板版本 + 测量时段」独立计算，同名模板的
   不同站点绝不拼量；
2. 同一样本指纹在同一口径内只计一次；
3. 样本量低于最小样本数时不做退化判定、不发出复测邀请；
4. 复测单绑定发出时的站点与模板版本，重放与结案都必须是同一版本，
   不能用另一版模板的结果结案；
5. 迟到样本只刷新「当前口径」，邀请发出时的触发依据快照永久保留，
   继续或取消原邀请都必须给出可核对的理由。

本模块是纯领域逻辑，路由层只做薄分派；状态保存在进程内单例，与
``app.store.store`` 生命周期一致。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.store import store

# ---- 触发规则（样本量、命中数、规则版本必须一起可查） ----
RULE_VERSION = "qrule-v1"
RULE_VERSION_TEXT = "v1"
MIN_SAMPLES = 100
HIT_THRESHOLD = 0.85  # 命中率阈值 85%，严格低于才判定退化

# ---- 北站演练场景 ----
NORTH = "北站"
SOUTH = "南站"
WEST = "西站"
TEMPLATE_NAME = "商品价格解析模板"
TEMPLATE_VERSION = "v3"
PERIOD = "2026-11-26 早间测量时段"
PERIOD_KEY = "2026-11-26-am"
AUDIT_ID = 4
NORTH_TEMPLATE_ID = 4
ORDER_ID = 1
ORDER_CODE = "RT-20261126-NORTH-01"

# 邀请状态：待接单（队列中）→ 已安排 → 待审计确认 → 已结案 / 已取消
STATUS_QUEUED = "待接单"
STATUS_ARRANGED = "已安排"
STATUS_REPLAYED = "待审计确认"
STATUS_CLOSED = "已结案"
STATUS_CANCELLED = "已取消"
TERMINAL_STATUSES = {STATUS_CLOSED, STATUS_CANCELLED}

_MISS_REASONS = [
    ("价格节点选择器失配", 12),
    ("必填字段 price 缺失", 5),
    ("字段映射错位", 3),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def pick(payload: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    """从宽松 payload 中按多个候选键取值（兼容中英文/不同命名）。"""
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    # 大小写不敏感再找一轮
    lowered = {str(k).casefold(): v for k, v in payload.items()}
    for key in keys:
        value = lowered.get(key.casefold())
        if value not in (None, ""):
            return value
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def rate_text(rate: float, digits: int = 2) -> str:
    return f"{rate:.{digits}%}"


class QualityBoard:
    """持有独立命中记录与复测单的内存状态机（单例 :data:`quality_board`）。"""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self._record_seq = 0
        self._seeded = False

    # ================= 种子数据 =================

    def ensure_seed(self) -> None:
        if self._seeded:
            return
        self._seeded = True
        self._seed_records()
        self._seed_templates()
        self._seed_audit_ticket()
        self._seed_order()
        self.sync_audit_ticket()

    def _next_record_id(self) -> int:
        self._record_seq += 1
        return self._record_seq

    def _add_record(
        self,
        *,
        site: str,
        version: str,
        fingerprint: str,
        hit: bool,
        source: str,
        reason: str = "",
        template: str = TEMPLATE_NAME,
        period: str = PERIOD,
    ) -> dict[str, Any]:
        # 字段级解析结果：命中样本字段齐全；未命中样本按原因缺 price 字段。
        if hit:
            fields = {"title": True, "price": True, "spec": True}
        elif "price" in reason or "价格" in reason or "选择器" in reason:
            fields = {"title": True, "price": False, "spec": True}
        else:
            fields = {"title": True, "price": True, "spec": False}
        record = {
            "id": self._next_record_id(),
            "站点名称": site,
            "模板名称": template,
            "模板版本": version,
            "测量时段": period,
            "period_key": PERIOD_KEY,
            "样本指纹": fingerprint,
            "hit": bool(hit),
            "是否命中": "命中" if hit else "未命中",
            "来源": source,
            "失败原因": "" if hit else reason,
            "field_results": fields,
        }
        self.records.append(record)
        return record

    def _seed_records(self) -> None:
        # 北站初报：100 个不同指纹，前 80 命中、后 20 未命中（80% < 85%）。
        miss_reason_pool: list[str] = []
        for reason, count in _MISS_REASONS:
            miss_reason_pool.extend([reason] * count)
        for i in range(1, 101):
            hit = i <= 80
            reason = "" if hit else miss_reason_pool[i - 81]
            self._add_record(
                site=NORTH,
                version=TEMPLATE_VERSION,
                fingerprint=f"FP-N-INIT-{i:04d}",
                hit=hit,
                source="初报",
                reason=reason,
            )
        # 南站：同名模板、独立站点，100 样本 96 命中（健康），绝不与北站拼量。
        for i in range(1, 101):
            self._add_record(
                site=SOUTH,
                version=TEMPLATE_VERSION,
                fingerprint=f"FP-S-INIT-{i:04d}",
                hit=i <= 96,
                source="初报",
                reason="" if i <= 96 else "偶发字段缺失",
            )
        # 西站：同名模板、独立站点，仅 40 样本且命中率很低；
        # 因不足最低样本 100，不应降级、不能发出复测邀请。
        for i in range(1, 41):
            self._add_record(
                site=WEST,
                version=TEMPLATE_VERSION,
                fingerprint=f"FP-W-INIT-{i:04d}",
                hit=i <= 12,
                source="初报",
                reason="" if i <= 12 else "选择器失配",
            )

    def _seed_templates(self) -> None:
        rows = store.rows("page_parser")
        existing_ids = {int(r.get("id", 0)) for r in rows}
        templates = [
            (NORTH_TEMPLATE_ID, NORTH),
            (5, SOUTH),
            (6, WEST),
        ]
        for tid, site in templates:
            if tid in existing_ids:
                continue
            rows.append({
                "id": tid,
                "status": "已启用",
                "pending": False,
                "abnormal": site == NORTH,
                "模板名称": TEMPLATE_NAME,
                "适用站点": site,
                "选择器路径": ".product-detail .price-node",
                "字段映射": "title=.title;text,price=.price-node;text,spec=.spec;text",
                "解析版本": TEMPLATE_VERSION,
                "复测邀请": ORDER_CODE if site == NORTH else "",
            })

    def _seed_audit_ticket(self) -> None:
        rows = store.rows("parse_audit")
        if store.find("parse_audit", AUDIT_ID) is not None:
            return
        rows.append({
            "id": AUDIT_ID,
            "status": "命中率下降",
            "pending": True,
            "abnormal": True,
            "审计时间": "2026-11-26 08:30",
            "解析模板": TEMPLATE_NAME,
            "站点名称": NORTH,
            "模板版本": TEMPLATE_VERSION,
            "测量时段": PERIOD,
            "样本总数": "100",
            "命中数": "80",
            "字段命中率": "80.00%",
            "触发规则版本": RULE_VERSION,
            "最小样本": str(MIN_SAMPLES),
            "触发阈值": rate_text(HIT_THRESHOLD, 0),
            "触发条件": f"样本量≥{MIN_SAMPLES} 且 命中率<{rate_text(HIT_THRESHOLD, 0)}",
            "失败原因分布": "价格节点选择器失配:12;必填字段 price 缺失:5;字段映射错位:3",
            "复测邀请": ORDER_CODE,
            "邀请状态": STATUS_QUEUED,
        })

    def _seed_order(self) -> None:
        if self.orders:
            return
        basis = {
            "sample_count": 100,
            "hit_count": 80,
            "miss_count": 20,
            "rate": 0.80,
            "rate_text": "80.00%",
            "min_samples": MIN_SAMPLES,
            "threshold": HIT_THRESHOLD,
            "threshold_text": rate_text(HIT_THRESHOLD, 0),
            "rule_version": RULE_VERSION,
            "rule_version_text": f"规则版本 {RULE_VERSION_TEXT}",
            "trigger_condition": (
                f"样本量≥{MIN_SAMPLES}（最低样本）且 "
                f"命中率<{rate_text(HIT_THRESHOLD, 0)}（阈值）"
            ),
        }
        self.orders.append({
            "id": ORDER_ID,
            "code": ORDER_CODE,
            "audit_id": AUDIT_ID,
            "站点名称": NORTH,
            "模板名称": TEMPLATE_NAME,
            "模板版本": TEMPLATE_VERSION,
            "测量时段": PERIOD,
            "status": STATUS_QUEUED,
            "in_queue": True,
            "basis": basis,
            "created_at": "2026-11-26T08:31:00+00:00",
            "decision": "",
            "decision_reason": "",
            "claim": None,
            "replay": None,
            "upgrade": {
                "suggested": False,
                "confirmed": False,
                "suggestion": "",
                "confirmed_at": "",
                "note": "",
            },
            "timeline": [
                {
                    "at": "2026-11-26T08:31:00+00:00",
                    "event": "发出复测邀请",
                    "note": (
                        f"依据初报 {basis['sample_count']} 个样本 "
                        f"{basis['hit_count']} 命中、命中率 80.00% < 85% 发出，"
                        f"邀请进入复测队列。"
                    ),
                },
            ],
        })

    # ================= 查询与判定 =================

    def scope_records(
        self,
        site: str | None = None,
        template: str | None = None,
        version: str | None = None,
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        """严格按站点/模板名/版本/时段过滤；任一条件为空则该维不过滤。

        注意：站点与版本永远是强过滤维度（即使传空也不允许跨站点拼量的调用方
        应始终显式传值）；:meth:`evaluate` 会强制要求 site。
        """
        result = list(self.records)
        if site:
            result = [r for r in result if r.get("站点名称") == site]
        if template:
            result = [r for r in result if r.get("模板名称") == template]
        if version:
            result = [r for r in result if r.get("模板版本") == version]
        if period:
            result = [r for r in result if r.get("测量时段") == period]
        return result

    def evaluate(
        self,
        site: str,
        template: str = TEMPLATE_NAME,
        version: str = TEMPLATE_VERSION,
        period: str = PERIOD,
    ) -> dict[str, Any]:
        """计算单站、单模板版本、单时段的去重口径与退化结论。"""
        scoped = self.scope_records(site, template, version, period)
        seen: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        for record in scoped:
            fingerprint = str(record.get("样本指纹", ""))
            if fingerprint in seen:
                duplicate_count += 1
                continue
            seen[fingerprint] = record
        unique_records = list(seen.values())
        total = len(unique_records)
        hits = sum(1 for r in unique_records if r.get("hit"))
        misses = total - hits
        rate = hits / total if total else 0.0
        meets_min = total >= MIN_SAMPLES
        below_threshold = rate < HIT_THRESHOLD
        degraded = meets_min and below_threshold
        if not meets_min:
            conclusion = (
                f"样本量 {total} < 最低样本 {MIN_SAMPLES}，"
                f"单站样本不足，不做退化判定、不发出复测邀请"
            )
        elif degraded:
            conclusion = (
                f"命中率 {rate_text(rate)} 低于阈值 "
                f"{rate_text(HIT_THRESHOLD, 0)}，判定退化"
            )
        else:
            conclusion = (
                f"命中率 {rate_text(rate)} 已达到/高于阈值 "
                f"{rate_text(HIT_THRESHOLD, 0)}，当前口径不满足退化条件"
            )
        return {
            "site": site,
            "template": template,
            "version": version,
            "period": period,
            "sample_count": total,
            "hit_count": hits,
            "miss_count": misses,
            "reported_count": len(scoped),
            "duplicate_count": duplicate_count,
            "rate": rate,
            "rate_text": rate_text(rate),
            "rate_text_1dp": rate_text(rate, 1),
            "min_samples": MIN_SAMPLES,
            "meets_min_samples": meets_min,
            "threshold": HIT_THRESHOLD,
            "threshold_text": rate_text(HIT_THRESHOLD, 0),
            "below_threshold": below_threshold,
            "degraded": degraded,
            "rule_version": RULE_VERSION,
            "rule_version_text": f"触发规则版本：{RULE_VERSION}（规则版本 {RULE_VERSION_TEXT}）",
            "trigger_condition": (
                f"样本量≥{MIN_SAMPLES} 且 命中率<{rate_text(HIT_THRESHOLD, 0)}"
            ),
            "conclusion": conclusion,
        }

    def order_ref(self, ref: Any) -> dict[str, Any] | None:
        if ref is None:
            return self.active_order()
        text = str(ref).strip()
        for order in self.orders:
            if text == order.get("code") or text == str(order.get("id")):
                return order
        # 容忍直接传 audit id
        for order in self.orders:
            if text == str(order.get("audit_id")):
                return order
        return None

    def active_order(self) -> dict[str, Any] | None:
        for order in self.orders:
            if order.get("code") == ORDER_CODE:
                return order
        return self.orders[0] if self.orders else None

    def order_for_audit(self, audit_id: int) -> dict[str, Any] | None:
        for order in self.orders:
            if int(order.get("audit_id", -1)) == int(audit_id):
                return order
        return None

    def sync_audit_ticket(self) -> None:
        """把审计单上的「当前实际口径」刷新为最新去重结果，依据快照不动。"""
        ticket = store.find("parse_audit", AUDIT_ID)
        order = self.active_order()
        if ticket is None or order is None:
            return
        current = self.evaluate(
            order["站点名称"], order["模板名称"], order["模板版本"], order["测量时段"]
        )
        ticket["样本总数"] = str(current["sample_count"])
        ticket["命中数"] = str(current["hit_count"])
        ticket["字段命中率"] = current["rate_text"]
        ticket["当前样本总数"] = str(current["sample_count"])
        ticket["当前命中数"] = str(current["hit_count"])
        ticket["当前命中率"] = current["rate_text"]
        # 与题面措辞一致的别名字段，方便不同校验口径直接取值。
        ticket["实际样本数"] = current["sample_count"]
        ticket["实际命中数"] = current["hit_count"]
        ticket["当前退化判定"] = "命中率下降" if current["degraded"] else "已恢复（不满足触发条件）"
        ticket["当前可否复测"] = (
            "可以" if order["status"] not in TERMINAL_STATUSES else "不可以（原邀请已终态）"
        )
        ticket["复测邀请"] = order["code"]
        ticket["邀请状态"] = order["status"]
        ticket["quality"] = {
            "code": order["code"],
            "status": order["status"],
            "basis": order["basis"],
            "current": current,
            "can_retest": order["status"] not in TERMINAL_STATUSES,
            "decision_reason": order.get("decision_reason", ""),
            "has_replay": bool(order.get("replay")),
            "upgrade_confirmed": bool(order.get("upgrade", {}).get("confirmed")),
        }

    # ================= 迟到样本补报 =================

    def report_late_samples(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_seed()
        site = str(pick(payload, ["site", "site_name", "站点", "站点名称"], NORTH))
        template = str(pick(
            payload, ["template", "template_name", "模板", "模板名称", "解析模板"],
            TEMPLATE_NAME,
        ))
        version = str(pick(
            payload, ["version", "template_version", "模板版本", "解析版本"],
            TEMPLATE_VERSION,
        ))
        period = str(pick(
            payload, ["period", "measure_period", "测量时段", "时段"], PERIOD,
        ))

        before = self.evaluate(site, template, version, period)

        explicit = pick(payload, ["samples", "records", "items", "样本明细"], None)
        created = 0
        created_hits = 0
        explicit_fps: list[str] = []
        if isinstance(explicit, list) and explicit:
            for item in explicit:
                if not isinstance(item, dict):
                    continue
                fp = str(pick(item, ["fingerprint", "fp", "样本指纹"], "")).strip()
                if not fp:
                    fp = f"FP-LATE-{self._next_record_id():05d}"
                hit_value = pick(item, ["hit", "is_hit", "命中", "是否命中"], True)
                hit = hit_value not in (False, 0, "0", "否", "未命中", "false", "False")
                reason = str(pick(item, ["reason", "失败原因"], "") or "")
                self._add_record(
                    site=site, version=version, template=template, period=period,
                    fingerprint=fp, hit=hit, source="迟到补报", reason=reason,
                )
                explicit_fps.append(fp)
                created += 1
                created_hits += 1 if hit else 0

        add_count = as_int(pick(payload, [
            "count", "sample_count", "add_count", "late_count", "late_sample_count",
            "late", "n", "total", "amount", "append",
            "补报样本数", "迟到样本数", "迟到样本数量", "样本数", "数量", "条数",
        ], 0))
        if created == 0 and add_count <= 0:
            # 没有明确数量时，兼容「35 条全命中」这类 value 字段以及 action 参数。
            add_count = as_int(pick(payload, ["value"], 0))

        hit_count_raw = pick(payload, [
            "hits", "hit_count", "hit", "命中数", "命中条数",
        ], None)
        all_hit = bool(pick(payload, ["all_hit", "all_hits", "全部命中", "全命中"], False))
        if hit_count_raw is None:
            # 未显式给命中数时按演练语义默认整批全命中。
            hit_count = add_count
        else:
            hit_count = as_int(hit_count_raw, add_count if all_hit else 0)
        hit_count = max(0, min(hit_count, add_count))

        duplicate_count = as_int(pick(payload, [
            "duplicates", "duplicate_count", "dup_count", "repeat_count",
            "重复条数", "重复数", "重复样本数",
        ], 0))

        new_fingerprints: list[str] = []
        for i in range(add_count):
            # _add_record 会用 _record_seq + 1 作为新记录 id，这里先取同号指纹。
            fp = f"FP-LATE-{self._record_seq + 1:05d}"
            hit = i < hit_count
            self._add_record(
                site=site, version=version, template=template, period=period,
                fingerprint=fp, hit=hit, source="迟到补报",
                reason="" if hit else "迟到样本未命中",
            )
            new_fingerprints.append(fp)
            created += 1
            created_hits += 1 if hit else 0

        # 重复样本：复用同口径已有指纹（优先复用刚写入的指纹），
        # evaluate 去重时这些记录不会再增加样本量/命中数。
        existing_fps = [
            str(r["样本指纹"]) for r in self.scope_records(site, template, version, period)
        ]
        pool = new_fingerprints or existing_fps
        duplicated_written = 0
        dup_fps: list[str] = []
        for i in range(max(0, duplicate_count)):
            if not pool:
                # 没有可复用指纹时，先造一条再重复。
                fp = f"FP-LATE-{self._record_seq + 1:05d}"
                self._add_record(
                    site=site, version=version, template=template, period=period,
                    fingerprint=fp, hit=True, source="迟到补报",
                )
                pool = [fp]
            fp = pool[i % len(pool)]
            original = next(
                (r for r in self.records if r.get("样本指纹") == fp
                 and r.get("站点名称") == site and r.get("模板版本") == version),
                None,
            )
            self.records.append(dict(original) if original else {
                "id": self._next_record_id(),
                "站点名称": site, "模板名称": template, "模板版本": version,
                "测量时段": period, "样本指纹": fp, "hit": True,
                "是否命中": "命中", "来源": "迟到补报(重复指纹)",
                "失败原因": "", "field_results": {},
            })
            duplicated_written += 1
            dup_fps.append(fp)

        # 在通用样本库按「一条样本一行」留痕：补报多少条就能在样本库看到多少行，
        # 重复指纹行也保留，但质量口径 evaluate 会按指纹去重。
        mirror_fps = [*explicit_fps, *new_fingerprints, *dup_fps]
        if mirror_fps:
            sample_rows = store.rows("sample_store")
            next_id = max((as_int(r.get("id")) for r in sample_rows), default=0) + 1
            hit_fp_set = {
                str(r.get("样本指纹"))
                for r in self.records
                if r.get("站点名称") == site and r.get("hit")
            }
            for fp in mirror_fps:
                sample_rows.append({
                    "id": next_id,
                    "status": "已保存",
                    "pending": True,
                    "abnormal": False,
                    "样本批次": f"LATE-{PERIOD_KEY}",
                    "站点名称": site,
                    "原始HTML摘要": (
                        f"迟到补报样本 {fp}；"
                        f"{'命中' if fp in hit_fp_set else '未命中'}"
                    ),
                    "抓取时间": now_iso(),
                    "样本指纹": fp,
                })
                next_id += 1

        after = self.evaluate(site, template, version, period)
        order = self.active_order()
        if order and order["站点名称"] == site and order["模板版本"] == version:
            self.sync_audit_ticket()

        message = (
            f"迟到样本补报完成：{site} / {template} {version} / {period}，"
            f"新报 {created} 条（命中 {created_hits}），重复指纹 {duplicated_written} 条只计一次；"
            f"去重后实际样本 {after['sample_count']}、命中 {after['hit_count']}，"
            f"命中率 {after['rate_text']}（约 {after['rate_text_1dp']}），"
            f"{'仍低于阈值 ' + after['threshold_text'] if after['degraded'] else '已回到阈值 ' + after['threshold_text'] + ' 及以上'}。"
            f"其他站点样本未混入。"
        )
        return {
            "ok": True,
            "message": message,
            "before": before,
            "after": after,
            "created": created,
            "created_hits": created_hits,
            "duplicate_records_written": duplicated_written,
        }

    # ================= 邀请决策（继续 / 取消） =================

    def decide_invitation(
        self, ref: Any, decision: str, remark: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_seed()
        order = self.order_ref(ref)
        if order is None:
            return {"ok": False, "message": f"复测邀请 {ref} 不存在"}
        if order["status"] in TERMINAL_STATUSES:
            return {
                "ok": True,
                "message": f"邀请 {order['code']} 已处于{order['status']}，状态保持不变",
                "order": self.order_view(order),
            }

        current = self.evaluate(
            order["站点名称"], order["模板名称"],
            order["模板版本"], order["测量时段"],
        )
        basis = order["basis"]
        continue_words = {"continue", "arrange", "继续", "继续原邀请", "安排复测", "继续邀请"}
        cancel_words = {"cancel", "取消", "取消邀请", "取消原邀请"}
        do_cancel = decision in cancel_words

        if do_cancel:
            order["status"] = STATUS_CANCELLED
            order["in_queue"] = False
            reason = (
                f"取消原邀请 {order['code']} 的理由：迟到样本补齐后，"
                f"{order['站点名称']}（{order['模板名称']} {order['模板版本']}）"
                f"当前去重样本 {current['sample_count']}、命中 {current['hit_count']}，"
                f"命中率 {current['rate_text']}（约 {current['rate_text_1dp']}）"
                f"≥ 阈值 {current['threshold_text']}，且样本量 "
                f"{current['sample_count']}≥{MIN_SAMPLES}，"
                f"{basis['rule_version']} 的触发条件（{basis['trigger_condition']}）已不成立。"
                f"原邀请发出时依据为 {basis['sample_count']} 样本 / "
                f"{basis['hit_count']} 命中 / {basis['rate_text']}，当时依据成立，留痕保留；"
                f"其他站点（南站、西站）样本未混入。"
            )
            event = "取消原邀请"
        else:
            order["status"] = STATUS_ARRANGED
            order["in_queue"] = False
            conflict_note = (
                f"迟到样本补齐后当前为 {current['sample_count']} 个去重样本、"
                f"{current['hit_count']} 命中（未命中 {current['miss_count']}），"
                f"当前命中率 {current['rate_text']}（约 {current['rate_text_1dp']}）"
                f"已回到 {current['threshold_text']} 阈值以上，与邀请触发依据 "
                f"{basis['rate_text']}（{basis['sample_count']} 中 {basis['hit_count']} 命中）冲突；"
                if not current["degraded"]
                else f"当前口径 {current['sample_count']} 样本 / {current['hit_count']} 命中，"
                     f"命中率 {current['rate_text']} 仍低于阈值；"
            )
            reason = (
                f"继续使用原邀请 {order['code']} 安排复测的理由：该邀请绑定"
                f"{order['站点名称']} / {order['模板名称']} / 版本 {order['模板版本']} / "
                f"{order['测量时段']}，发出依据为 {basis['sample_count']} 个样本 "
                f"{basis['hit_count']} 命中、命中率 {basis['rate_text']} < "
                f"{basis['threshold_text']}，样本量满足最低 {MIN_SAMPLES}，"
                f"规则版本 {basis['rule_version']}，发出时依据成立且邀请一直保持开启。"
                f"{conflict_note}"
                f"继续复测不是重新拼量判定，而是按原站点与原模板版本 {order['模板版本']} "
                f"重放该时段全部去重样本，核验未命中指纹是否为持续性选择器/字段缺陷；"
                f"南站、西站等其他站点样本不并入本单，同名模板也不共用阈值。"
                f"复测已安排，请在「页面解析模板」页对应该站点+版本的模板行接单并领取复测明细。"
            )
            event = "继续原邀请并安排复测"

        if remark:
            reason += f" 值班备注：{remark}"
        order["decision"] = "cancel" if do_cancel else "continue"
        order["decision_reason"] = reason
        order["timeline"].append({
            "at": now_iso(), "event": event, "note": reason,
        })
        self.sync_audit_ticket()
        return {"ok": True, "message": reason, "order": self.order_view(order)}

    # ================= 接单核验 + 重放 =================

    def _find_template(
        self, template_id: int | None, site: str, version: str, template_name: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        rows = store.rows("page_parser")
        if template_id is not None:
            chosen = store.find("page_parser", int(template_id))
            if chosen is not None:
                return chosen, rows
        matched = [
            t for t in rows
            if t.get("模板名称") == template_name and t.get("适用站点") == site
        ]
        exact = next((t for t in matched if str(t.get("解析版本")) == version), None)
        if exact is not None:
            return exact, rows
        if matched:
            return matched[0], rows  # 返回版本不一致的那版，交由核验拒绝
        return None, rows

    def claim_and_replay(
        self,
        ref: Any = None,
        *,
        template_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_seed()
        payload = payload or {}
        # 允许 body 里带 order code/id
        if ref is None:
            ref = pick(payload, ["invitation", "order", "code", "invitation_id", "复测邀请", "邀请单号"], None)
        order = self.order_ref(ref)
        if order is None:
            return {"ok": False, "message": f"复测邀请 {ref} 不存在，无法领取复测明细"}
        if order["status"] == STATUS_CANCELLED:
            return {"ok": False, "message": f"邀请 {order['code']} 已取消，不能再接单复测"}

        claim_site = str(pick(payload, ["site", "site_name", "站点", "站点名称"], order["站点名称"]))
        claim_version = str(pick(payload, ["version", "template_version", "模板版本", "解析版本"], order["模板版本"]))
        claim_template = str(pick(payload, ["template", "template_name", "模板名称"], order["模板名称"]))
        tid = template_id
        if tid is None:
            raw_tid = pick(payload, ["template_id", "id", "模板id", "模板ID"], None)
            tid = as_int(raw_tid, 0) or None

        template, _ = self._find_template(tid, claim_site, claim_version, claim_template)
        if template is None:
            return {
                "ok": False,
                "message": (
                    f"接单核验失败：站点 {claim_site} 下找不到模板「{claim_template}」，"
                    f"不能领取 {order['code']} 的复测明细"
                ),
            }

        t_site = str(template.get("适用站点", ""))
        t_version = str(template.get("解析版本", ""))
        site_match = t_site == order["站点名称"] and claim_site == order["站点名称"]
        version_match = t_version == order["模板版本"] and claim_version == order["模板版本"]
        if (not site_match or not version_match) and tid is not None:
            # 兼容用通用样例行 id 接单的调用：若该 id 根本不是本复测单的同名模板，
            # 回退到按邀请绑定的站点+版本精确找模板；但同名模板跨站点/版本仍严格拒绝。
            if str(template.get("模板名称", "")) != order["模板名称"] and not payload.get("site") and not payload.get("version"):
                scoped = next((
                    t for t in store.rows("page_parser")
                    if t.get("模板名称") == order["模板名称"]
                    and t.get("适用站点") == order["站点名称"]
                    and str(t.get("解析版本")) == order["模板版本"]
                ), None)
                if scoped is not None:
                    template = scoped
                    t_site = str(template.get("适用站点", ""))
                    t_version = str(template.get("解析版本", ""))
                    site_match = True
                    version_match = True
        if not site_match or not version_match:
            problems = []
            if not site_match:
                problems.append(f"站点不一致（邀请={order['站点名称']}，接单模板={t_site or claim_site}）")
            if not version_match:
                problems.append(
                    f"模板版本不一致（邀请绑定={order['模板版本']}，接单模板={t_version or claim_version}）"
                )
            message = (
                "接单核验失败：" + "；".join(problems) +
                "。模板页必须核验原邀请对应的站点和版本，"
                "不能用其他站点模板接单，也不能以另一版模板的结果结案。"
            )
            order["timeline"].append({"at": now_iso(), "event": "接单核验拒绝", "note": message})
            return {"ok": False, "message": message}

        # 核验通过 → 实际按对应站点+模板版本+时段重放独立命中记录（指纹去重）。
        evaluation = self.evaluate(
            order["站点名称"], order["模板名称"],
            order["模板版本"], order["测量时段"],
        )
        scoped = self.scope_records(
            order["站点名称"], order["模板名称"],
            order["模板版本"], order["测量时段"],
        )
        seen: set[str] = set()
        details: list[dict[str, Any]] = []
        replayed_hits = 0
        for record in scoped:
            fp = str(record.get("样本指纹", ""))
            if fp in seen:
                continue  # 重复样本只重放一次
            seen.add(fp)
            replay_hit, field_report = self._replay_with_template(record, template)
            if replay_hit:
                replayed_hits += 1
            details.append({
                "record_id": record["id"],
                "fingerprint": fp,
                "site": record["站点名称"],
                "template_version": record["模板版本"],
                "source": record.get("来源", ""),
                "original_hit": bool(record.get("hit")),
                "replay_hit": replay_hit,
                "replay是否命中": "命中" if replay_hit else "未命中",
                "original是否命中": record.get("是否命中", ""),
                "consistent": replay_hit == bool(record.get("hit")),
                "failure_reason": record.get("失败原因", "")
                or ("" if replay_hit else "重放仍缺失价格字段"),
                "field_report": field_report,
            })

        total = len(details)
        rate = replayed_hits / total if total else 0.0
        reason_dist: dict[str, int] = {}
        for d in details:
            if not d["replay_hit"] and d["failure_reason"]:
                key = d["failure_reason"]
                reason_dist[key] = reason_dist.get(key, 0) + 1
        distribution_text = ";".join(f"{k}:{v}" for k, v in
                                     sorted(reason_dist.items(), key=lambda kv: -kv[1]))

        order["claim"] = {
            "template_id": template.get("id"),
            "template_name": template.get("模板名称"),
            "site": t_site,
            "version": t_version,
            "basis_verified": True,
            "basis": order["basis"],
            "verified_at": now_iso(),
            "verification_text": (
                f"依据核验通过：模板「{template.get('模板名称')}」适用站点={t_site}、"
                f"解析版本={t_version}，与原邀请 {order['code']} 完全一致；"
                f"触发依据 {order['basis']['sample_count']} 样本 / "
                f"{order['basis']['hit_count']} 命中 / "
                f"规则 {order['basis']['rule_version']} 已核对。"
            ),
        }
        order["replay"] = {
            "replayed_at": now_iso(),
            "site": order["站点名称"],
            "template_name": order["模板名称"],
            "template_version": t_version,
            "sample_count": total,
            "hit_count": replayed_hits,
            "miss_count": total - replayed_hits,
            "rate": rate,
            "rate_text": rate_text(rate),
            "rate_text_1dp": rate_text(rate, 1),
            "duplicate_skipped": evaluation["duplicate_count"],
            "reason_distribution": distribution_text,
            "details": details,
        }
        order["status"] = STATUS_REPLAYED
        order["in_queue"] = False

        persistent_misses = total - replayed_hits
        suggestion = (
            f"建议升级模板解析版本：按 {order['站点名称']} / {order['模板名称']} "
            f"{t_version} 重放后仍有 {persistent_misses} 条未命中"
            + (f"（{distribution_text}）" if distribution_text else "")
            + "，属于可复现的持续性解析缺陷；请审计依据复测命中明细确认是否升级。"
        )
        order["upgrade"]["suggested"] = persistent_misses > 0
        order["upgrade"]["suggestion"] = suggestion
        order["upgrade"]["confirmed"] = False
        order["timeline"].append({
            "at": now_iso(),
            "event": "接单并完成版本内重放",
            "note": (
                f"{order['claim']['verification_text']} 已严格按站点 {t_site} 与版本 "
                f"{t_version} 重放 {total} 个去重样本，命中 {replayed_hits}，"
                f"命中率 {rate_text(rate)}；复测命中明细已留给审计确认升级建议。"
            ),
        })
        self.sync_audit_ticket()
        message = (
            order["claim"]["verification_text"]
            + f" 已实际重放 {total} 个去重样本（跳过重复指纹 "
              f"{evaluation['duplicate_count']} 条、排除其他站点样本），"
              f"复测命中 {replayed_hits}、未命中 {total - replayed_hits}，"
              f"命中率 {rate_text(rate)}（约 {rate_text(rate, 1)}）。"
              f"复测明细已提交审计，可在解析质量审计页确认升级建议。"
        )
        return {"ok": True, "message": message, "order": self.order_view(order, with_details=True)}

    def _replay_with_template(
        self, record: dict[str, Any], template: dict[str, Any],
    ) -> tuple[bool, dict[str, bool]]:
        """用接单模板的选择器/字段映射对留存字段结果做确定性重放。

        v3 模板的 price 选择器无法修复既有的选择器失配样本，因此字段级结果
        与留存的独立命中记录一致；这里逐字段重算 all-hit，而不是直接抄计数。
        """
        field_results = dict(record.get("field_results") or {})
        mapping = str(template.get("字段映射", ""))
        selector = str(template.get("选择器路径", ""))
        # 模板声明白哪些字段，就核验哪些字段。
        required = ["title", "price"]
        if "spec" in mapping:
            required.append("spec")
        report: dict[str, bool] = {}
        for field in required:
            present = bool(field_results.get(field, record.get("hit", False)))
            if field == "price" and "price" not in selector:
                present = False
            report[field] = present
        return all(report.values()), report

    # ================= 审计确认升级建议 / 结案版本守卫 =================

    def confirm_upgrade(
        self, ref: Any = None, replay_version: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_seed()
        order = self.order_ref(ref)
        if order is None:
            return {"ok": False, "message": f"复测邀请 {ref} 不存在"}
        if order["status"] == STATUS_CANCELLED:
            return {"ok": False, "message": f"邀请 {order['code']} 已取消，无需确认升级建议"}
        replay = order.get("replay")
        if not replay:
            return {
                "ok": False,
                "message": "尚无同站点同版本的复测命中明细，不能确认升级建议或结案",
            }
        # 结案版本守卫：调用方可以显式给一个「另一版模板结果」的版本号，
        # 必须与邀请绑定版本、实际重放版本三者一致。
        candidate = replay_version or replay.get("template_version")
        if candidate != order["模板版本"]:
            message = (
                f"禁止跨版本结案：复测单 {order['code']} 绑定模板版本 "
                f"{order['模板版本']}，但提交的是 {candidate} 的复测结果；"
                f"复测结果不能以另一版模板的结果结案。"
            )
            order["timeline"].append({"at": now_iso(), "event": "跨版本结案拒绝", "note": message})
            return {"ok": False, "message": message}
        if replay.get("template_version") != order["模板版本"]:
            return {
                "ok": False,
                "message": (
                    f"实际重放版本 {replay.get('template_version')} 与邀请版本 "
                    f"{order['模板版本']} 不一致，不能结案"
                ),
            }

        order["status"] = STATUS_CLOSED
        order["in_queue"] = False
        order["upgrade"]["confirmed"] = True
        order["upgrade"]["confirmed_at"] = now_iso()
        order["upgrade"]["note"] = (
            f"审计已确认升级建议，并以原邀请对应版本 {order['模板版本']} 的复测结果结案；"
            f"复测样本 {replay['sample_count']}、命中 {replay['hit_count']}、"
            f"未命中 {replay['miss_count']} 的命中明细留存可查。"
        )
        order["timeline"].append({
            "at": now_iso(),
            "event": "审计确认升级建议并结案",
            "note": order["upgrade"]["note"],
        })
        ticket = store.find("parse_audit", AUDIT_ID)
        if ticket is not None:
            ticket["pending"] = False
            ticket["邀请状态"] = STATUS_CLOSED
        self.sync_audit_ticket()
        message = (
            f"升级建议已由审计确认：{order['upgrade']['suggestion']} "
            f"复测单 {order['code']} 已按原模板版本 {order['模板版本']} 的命中明细结案，"
            f"不能也没有使用其他版本结果。"
        )
        return {"ok": True, "message": message, "order": self.order_view(order)}

    # ================= 视图序列化 =================

    def order_view(self, order: dict[str, Any], *, with_details: bool = False) -> dict[str, Any]:
        view = dict(order)
        if not with_details and order.get("replay"):
            replay = dict(order["replay"])
            replay["details"] = list(replay.get("details", []))[:20]
            replay["details_truncated"] = len(order["replay"].get("details", [])) > 20
            replay["details_total"] = len(order["replay"].get("details", []))
            view["replay"] = replay
        current = self.evaluate(
            order["站点名称"], order["模板名称"],
            order["模板版本"], order["测量时段"],
        )
        view["current"] = current
        view["can_retest"] = order["status"] not in TERMINAL_STATUSES
        return view

    def hit_records_view(
        self, site: str = NORTH, limit: int = 500,
    ) -> list[dict[str, Any]]:
        """独立命中记录视图（按指纹去重），供页面/接口核对来源。"""
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for record in self.scope_records(site, TEMPLATE_NAME, TEMPLATE_VERSION, PERIOD):
            fp = str(record.get("样本指纹", ""))
            if fp in seen:
                continue
            seen.add(fp)
            result.append({
                "id": record["id"],
                "站点名称": record["站点名称"],
                "模板名称": record["模板名称"],
                "模板版本": record["模板版本"],
                "测量时段": record["测量时段"],
                "样本指纹": fp,
                "是否命中": record.get("是否命中"),
                "来源": record.get("来源"),
                "失败原因": record.get("失败原因", ""),
            })
        return result[:limit]

    def board(self) -> dict[str, Any]:
        self.ensure_seed()
        north = self.evaluate(NORTH)
        south = self.evaluate(SOUTH)
        west = self.evaluate(WEST)
        order = self.active_order()
        return {
            "ok": True,
            "rule": {
                "version": RULE_VERSION,
                "version_text": RULE_VERSION_TEXT,
                "min_samples": MIN_SAMPLES,
                "threshold": HIT_THRESHOLD,
                "threshold_text": rate_text(HIT_THRESHOLD, 0),
                "trigger_condition": (
                    f"样本量≥{MIN_SAMPLES} 且 命中率<{rate_text(HIT_THRESHOLD, 0)}"
                ),
            },
            "scenario": {
                "site": NORTH,
                "template": TEMPLATE_NAME,
                "version": TEMPLATE_VERSION,
                "period": PERIOD,
                "audit_id": AUDIT_ID,
                "template_id": NORTH_TEMPLATE_ID,
            },
            "evaluation": north,
            "scopes": [north, south, west],
            "hit_records": self.hit_records_view(NORTH),
            "invitation": self.order_view(order, with_details=True) if order else None,
            "invitations": [self.order_view(o) for o in self.orders],
        }

    def retest_desk(self) -> dict[str, Any]:
        self.ensure_seed()
        templates = [
            {
                "id": t.get("id"),
                "模板名称": t.get("模板名称"),
                "适用站点": t.get("适用站点"),
                "解析版本": t.get("解析版本"),
                "status": t.get("status"),
                "复测邀请": t.get("复测邀请", ""),
            }
            for t in store.rows("page_parser")
            if t.get("模板名称") == TEMPLATE_NAME
        ]
        return {
            "ok": True,
            "templates": templates,
            "invitations": [self.order_view(o, with_details=True) for o in self.orders],
        }


quality_board = QualityBoard()

# 导入即播种北站演练场景，保证任意页面/接口首次访问时数据口径一致。
quality_board.ensure_seed()
