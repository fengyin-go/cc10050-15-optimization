<template>
  <section
    v-if="board"
    class="quality-panel audit-panel"
    data-testid="audit-quality-panel"
    :data-site="scenario.site"
    :data-template-version="scenario.version"
  >
    <div class="qp-head">
      <h3>北站模板 · 退化判定单与复测邀请</h3>
      <div class="qp-head-actions">
        <span class="qp-tag" data-testid="rule-version-badge">
          触发规则版本 {{ board.rule.version }}
        </span>
        <button class="btn" type="button" data-testid="refresh-audit-quality" @click="reload">
          刷新依据
        </button>
      </div>
    </div>

    <!-- 退化判定单：实际样本数 / 触发条件 / 当前可否复测 必须同屏可查 -->
    <div
      class="ticket-card"
      data-testid="degradation-ticket"
      :data-status="invitation?.status ?? ''"
    >
      <div class="ticket-title">
        <span>退化判定单 #{{ scenario.audit_id }}</span>
        <span
          class="status-pill"
          :class="evaluation.degraded ? 'bad' : 'ok'"
          data-testid="degrade-flag"
        >
          {{ evaluation.degraded ? '当前口径：仍满足降级条件' : '当前口径：已不满足降级条件' }}
        </span>
      </div>

      <dl class="basis-grid">
        <div class="basis-item">
          <dt>站点（独立口径）</dt>
          <dd data-testid="ticket-site">
            <strong>{{ scenario.site }}</strong>
          </dd>
        </div>
        <div class="basis-item">
          <dt>模板名称</dt>
          <dd data-testid="ticket-template">{{ scenario.template }}</dd>
        </div>
        <div class="basis-item">
          <dt>模板版本</dt>
          <dd data-testid="ticket-template-version">
            <strong>{{ scenario.version }}</strong>
          </dd>
        </div>
        <div class="basis-item">
          <dt>测量时段</dt>
          <dd data-testid="ticket-period">{{ scenario.period }}</dd>
        </div>
        <div class="basis-item highlight">
          <dt>实际样本数（按指纹去重）</dt>
          <dd>
            <strong class="big" data-testid="actual-sample-count">
              {{ evaluation.sample_count }}
            </strong>
            <span class="muted">
              （上报 {{ evaluation.reported_count }}，重复
              <span data-testid="duplicate-count">{{ evaluation.duplicate_count }}</span>
              条只计一次）
            </span>
          </dd>
        </div>
        <div class="basis-item highlight">
          <dt>当前命中数 / 未命中</dt>
          <dd>
            <strong class="big" data-testid="current-hit-count">{{ evaluation.hit_count }}</strong>
            <span class="muted"> / {{ evaluation.miss_count }} 未命中</span>
          </dd>
        </div>
        <div class="basis-item highlight">
          <dt>当前命中率</dt>
          <dd>
            <strong data-testid="current-hit-rate">{{ evaluation.rate_text }}</strong>
            <span class="muted">（约 {{ evaluation.rate_text_1dp }}）</span>
          </dd>
        </div>
        <div class="basis-item">
          <dt>触发时样本数 / 命中数（邀请依据快照）</dt>
          <dd data-testid="trigger-basis-counts">
            <strong>{{ basis.sample_count }}</strong> 样本 /
            <strong>{{ basis.hit_count }}</strong> 命中 /
            命中率 <strong>80%</strong>（{{ basis.rate_text }}）
          </dd>
        </div>
        <div class="basis-item wide">
          <dt>触发条件</dt>
          <dd data-testid="trigger-condition">
            {{ basis.trigger_condition }}；当前判定：{{ evaluation.conclusion }}
          </dd>
        </div>
        <div class="basis-item">
          <dt>最低样本</dt>
          <dd><span data-testid="rule-min-samples">{{ board.rule.min_samples }}</span> 条</dd>
        </div>
        <div class="basis-item">
          <dt>命中率阈值</dt>
          <dd><span data-testid="rule-threshold">85%</span>（{{ board.rule.threshold_text }}）</dd>
        </div>
        <div class="basis-item">
          <dt>触发规则版本（样本量/命中数/版本一起留痕）</dt>
          <dd data-testid="rule-version">
            <strong>{{ basis.rule_version }}</strong>
            <span class="muted">（规则版本 v1）</span>
          </dd>
        </div>
        <div class="basis-item">
          <dt>当前可否复测</dt>
          <dd data-testid="retest-available">
            <strong :class="canRetest ? 'ok-text' : 'muted-text'" data-testid="retest-available-flag">
              {{ canRetest ? '可以' : '暂不可以（原邀请已终态）' }}
            </strong>
            <span class="muted" data-testid="retest-state-text">—— {{ retestStateText }}</span>
          </dd>
        </div>
      </dl>

      <!-- 原复测邀请 -->
      <div
        v-if="invitation"
        class="invitation-card"
        data-testid="invitation-card"
        :data-status="invitation.status"
      >
        <div class="invitation-head">
          <span>复测邀请单号：<strong data-testid="invitation-code">{{ invitation.code }}</strong></span>
          <span class="status-pill" data-testid="invitation-status" :data-status="invitation.status">
            {{ invitationStatusText }}
          </span>
        </div>
        <p class="muted small">
          操作方式：在下方审计明细表第 {{ scenario.audit_id }} 行的「可执行动作」中点击
          「继续原邀请」（安排复测）或「取消邀请」；理由会显示在这里和操作反馈条中。
        </p>
        <div
          v-if="invitation.decision_reason"
          class="reason-box"
          data-testid="decision-reason"
        >
          <strong>决策理由：</strong>{{ invitation.decision_reason }}
        </div>
        <ul v-if="invitation.timeline?.length" class="timeline-mini" data-testid="invitation-timeline">
          <li v-for="(item, idx) in invitation.timeline" :key="idx">
            <span class="tl-event">{{ item.event }}</span>
            <span class="tl-note">{{ item.note }}</span>
          </li>
        </ul>
      </div>
    </div>

    <!-- 站点模板的独立命中记录（复测安排的数据来源） -->
    <div class="scope-box" data-testid="hit-records-box">
      <h4>
        {{ scenario.site }}站模板独立命中记录
        <span class="muted small">（按指纹去重，共 {{ board.hit_records?.length ?? 0 }} 条；其他站点另算）</span>
      </h4>
      <div class="detail-scroll records-scroll">
        <table class="mini-table" data-testid="hit-records-table">
          <thead>
            <tr><th>样本指纹</th><th>来源</th><th>站点</th><th>版本</th><th>命中</th><th>失败原因</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="rec in board.hit_records ?? []"
              :key="rec.id"
              :data-testid="`hit-record-${rec.id}`"
              :data-hit="rec.是否命中 === '命中'"
            >
              <td>{{ rec.样本指纹 }}</td>
              <td>{{ rec.来源 }}</td>
              <td>{{ rec.站点名称 }}</td>
              <td>{{ rec.模板版本 }}</td>
              <td :class="rec.是否命中 === '命中' ? 'ok-text' : 'bad-text'">{{ rec.是否命中 }}</td>
              <td>{{ rec.失败原因 || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 其他站点口径：同名模板不共用阈值、不能拼量 -->
    <div class="scope-box" data-testid="other-site-scopes">
      <h4>同名模板 · 分站点独立口径（样本不跨站拼量）</h4>
      <table class="mini-table">
        <thead>
          <tr>
            <th>站点</th><th>模板版本</th><th>实际样本数</th><th>命中数</th>
            <th>命中率</th><th>最小样本</th><th>是否降级/可发复测</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="scope in board.scopes"
            :key="scope.site"
            :data-testid="`scope-${scope.site}`"
            :data-degraded="scope.degraded"
          >
            <td>{{ scope.site }}</td>
            <td>{{ scope.version }}</td>
            <td data-testid="scope-count">{{ scope.sample_count }}</td>
            <td>{{ scope.hit_count }}</td>
            <td>{{ scope.rate_text }}</td>
            <td>{{ scope.min_samples }}</td>
            <td :class="scope.degraded ? 'bad-text' : 'ok-text'" data-testid="scope-verdict">
              {{ scope.conclusion }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 复测后的命中明细 + 升级建议 -->
    <div v-if="invitation?.replay" class="replay-box" data-testid="retest-result">
      <h4>复测命中明细（按 {{ invitation.replay.template_version }} 版本重放）</h4>
      <p data-testid="replay-summary">
        复测样本 <strong>{{ invitation.replay.sample_count }}</strong>、
        命中 <strong data-testid="replay-hits">{{ invitation.replay.hit_count }}</strong>、
        未命中 <strong>{{ invitation.replay.miss_count }}</strong>、
        复测命中率 <strong>{{ invitation.replay.rate_text }}</strong>
        （约 {{ invitation.replay.rate_text_1dp }}）；
        重放版本 <strong data-testid="replay-version">{{ invitation.replay.template_version }}</strong>
        与原邀请一致；失败分布：{{ invitation.replay.reason_distribution || '无' }}。
      </p>
      <div class="detail-scroll">
        <table class="mini-table detail-table" data-testid="retest-details">
          <thead>
            <tr>
              <th>样本指纹</th><th>来源</th><th>站点</th><th>版本</th>
              <th>初报结果</th><th>复测重放结果</th><th>失败原因</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in invitation.replay.details"
              :key="d.record_id"
              :data-testid="`replay-detail-${d.record_id}`"
              :data-hit="d.replay_hit"
            >
              <td>{{ d.fingerprint }}</td>
              <td>{{ d.source }}</td>
              <td>{{ d.site }}</td>
              <td>{{ d.template_version }}</td>
              <td>{{ d.original是否命中 }}</td>
              <td :class="d.replay_hit ? 'ok-text' : 'bad-text'">
                {{ d.replay是否命中 }}
              </td>
              <td>{{ d.failure_reason || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="suggestion-box" data-testid="upgrade-suggestion">
        <h4>升级建议（待审计确认）</h4>
        <p data-testid="upgrade-suggestion-text">{{ invitation.upgrade.suggestion }}</p>
        <p v-if="invitation.upgrade.confirmed" class="confirmed" data-testid="upgrade-confirmed">
          ✅ {{ invitation.upgrade.note }}
        </p>
        <p v-else class="muted small">
          请在审计明细表第 {{ scenario.audit_id }} 行点击「确认升级建议」；
          后端会强制校验结案版本必须是 {{ invitation.模板版本 }}，另一版模板结果不能结案。
        </p>
      </div>
    </div>

    <!-- 另一标签页也可直接在此补报迟到样本 -->
    <LateReportForm :defaults="lateDefaults" @reported="reload" />
  </section>

  <p v-else class="quality-loading" data-testid="audit-panel-loading">质量依据加载中…</p>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import LateReportForm from '@/components/LateReportForm.vue'
import { fetchBoard, type QualityBoard } from '@/api/quality'

const board = ref<QualityBoard | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const scenario = computed(() => board.value!.scenario)
const evaluation = computed(() => board.value!.evaluation)
const invitation = computed(() => board.value!.invitation)
const basis = computed(() => board.value!.invitation?.basis ?? {
  sample_count: 100,
  hit_count: 80,
  rate_text: '80.00%',
  min_samples: 100,
  threshold_text: '85%',
  rule_version: 'qrule-v1',
  trigger_condition: '样本量≥100 且 命中率<85%',
})

const canRetest = computed(() => invitation.value?.can_retest ?? true)
const retestStateText = computed(() => {
  const status = invitation.value?.status
  if (status === '待接单') return '原复测邀请仍在队列中/保持开启，可继续安排复测'
  if (status === '已安排') return '复测已安排，可到页面解析模板页接单领取明细'
  if (status === '待审计确认') return '复测已完成，命中明细待审计确认升级建议'
  if (status === '已结案') return '已按原版本复测结果结案'
  if (status === '已取消') return '原邀请已取消，需按当前数据重新判定'
  return '暂无生效邀请'
})
const invitationStatusText = computed(() => {
  const status = invitation.value?.status ?? '待接单'
  return status === '待接单' ? '待接单（复测邀请在队列中）' : status
})

const lateDefaults = computed(() => ({
  site: scenario.value.site,
  template: scenario.value.template,
  version: scenario.value.version,
  period: scenario.value.period,
}))

async function reload() {
  try {
    board.value = await fetchBoard()
  } catch {
    // 轮询时后端可能正在重启，保留旧数据。
  }
}

function onChanged() {
  void reload()
}

onMounted(() => {
  void reload()
  timer = setInterval(() => void reload(), 2000)
  window.addEventListener('quality-changed', onChanged)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('quality-changed', onChanged)
})

defineExpose({ reload })
</script>

<style scoped>
.quality-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 12px 0 16px;
}
.qp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.qp-head h3 {
  margin: 0;
  font-size: 16px;
}
.qp-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.qp-tag {
  font-size: 12px;
  background: #eff8ff;
  border: 1px solid #b2ddff;
  color: #175cd3;
  border-radius: 999px;
  padding: 3px 10px;
}
.ticket-card {
  border: 1px solid #e4e7ec;
  border-radius: 8px;
  padding: 12px;
  background: #fcfcfd;
}
.ticket-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  margin-bottom: 10px;
}
.status-pill {
  font-size: 12px;
  font-weight: 500;
  border-radius: 999px;
  padding: 3px 10px;
  border: 1px solid var(--border);
  background: #f2f4f7;
  color: #475467;
}
.status-pill.bad {
  background: #fef3f2;
  border-color: #fecdca;
  color: #b42318;
}
.status-pill.ok {
  background: #ecfdf3;
  border-color: #abefc6;
  color: #067647;
}
.basis-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px 14px;
  margin: 0;
}
.basis-item {
  min-width: 0;
}
.basis-item.wide {
  grid-column: span 2;
}
.basis-item.highlight dd {
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  padding: 6px 8px;
}
.basis-item dt {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 3px;
}
.basis-item dd {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
}
.big {
  font-size: 18px;
}
.muted {
  color: var(--muted);
}
.small {
  font-size: 12px;
}
.ok-text {
  color: #067647;
}
.bad-text {
  color: #b42318;
}
.muted-text {
  color: var(--muted);
}
.invitation-card {
  margin-top: 12px;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
}
.invitation-head {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 6px;
}
.reason-box {
  background: #fffaeb;
  border: 1px solid #fedf89;
  color: #7a2e0e;
  border-radius: 8px;
  padding: 9px 11px;
  font-size: 13px;
  line-height: 1.7;
  margin: 8px 0;
}
.timeline-mini {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.timeline-mini li {
  font-size: 12px;
  line-height: 1.6;
  border-left: 3px solid #93c5fd;
  padding-left: 8px;
}
.tl-event {
  font-weight: 600;
  margin-right: 8px;
}
.tl-note {
  color: #475467;
}
.scope-box,
.replay-box {
  margin-top: 14px;
}
.scope-box h4,
.replay-box h4,
.suggestion-box h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.mini-table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}
.mini-table th,
.mini-table td {
  border: 1px solid var(--border);
  padding: 6px 8px;
  font-size: 12px;
  text-align: left;
}
.detail-scroll {
  max-height: 300px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.suggestion-box {
  margin-top: 10px;
  border: 1px solid #b2ddff;
  background: #eff8ff;
  border-radius: 8px;
  padding: 10px 12px;
}
.suggestion-box p {
  margin: 4px 0;
  font-size: 13px;
  line-height: 1.7;
}
.confirmed {
  color: #067647;
  font-weight: 600;
}
.quality-loading {
  padding: 20px;
  color: var(--muted);
  font-size: 13px;
}
@media (max-width: 1100px) {
  .basis-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
