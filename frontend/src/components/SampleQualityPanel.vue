<template>
  <section class="quality-panel sample-panel" data-testid="sample-quality-panel">
    <div class="qp-head">
      <h3>迟到样本补报 · 单站命中口径</h3>
      <button class="btn" type="button" data-testid="refresh-sample-quality" @click="reload">
        刷新口径
      </button>
    </div>
    <p class="muted small">
      迟到样本属于原测量时段，按「站点 + 模板 + 版本 + 时段」归并；同指纹重复样本只计一次，
      其他站点样本不能混入北站口径拼量。补报后请回到「解析质量审计」页继续原邀请或取消。
    </p>

    <LateReportForm @reported="reload" />

    <div v-if="board" class="scope-box" data-testid="sample-scopes">
      <h4>各站点当前口径（最低样本 {{ board.rule.min_samples }} / 阈值 {{ board.rule.threshold_text }} / 规则 {{ board.rule.version }}）</h4>
      <table class="mini-table">
        <thead>
          <tr>
            <th>站点</th><th>模板版本</th><th>实际样本数</th><th>命中数</th>
            <th>命中率</th><th>重复条数</th><th>判定</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="scope in board.scopes"
            :key="scope.site"
            :data-testid="`sample-scope-${scope.site}`"
          >
            <td>{{ scope.site }}</td>
            <td>{{ scope.version }}</td>
            <td data-testid="sample-scope-count">{{ scope.sample_count }}</td>
            <td>{{ scope.hit_count }}</td>
            <td>{{ scope.rate_text }}（约 {{ scope.rate_text_1dp }}）</td>
            <td>{{ scope.duplicate_count }}</td>
            <td :class="scope.degraded ? 'bad-text' : 'ok-text'">{{ scope.conclusion }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import LateReportForm from '@/components/LateReportForm.vue'
import { fetchBoard, type QualityBoard } from '@/api/quality'

const board = ref<QualityBoard | null>(null)

async function reload() {
  try {
    board.value = await fetchBoard()
  } catch {
    // 保留旧数据
  }
}

onMounted(reload)
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
  margin-bottom: 6px;
}
.qp-head h3 {
  margin: 0;
  font-size: 16px;
}
.muted {
  color: var(--muted);
}
.small {
  font-size: 12px;
  line-height: 1.7;
}
.scope-box {
  margin-top: 14px;
}
.scope-box h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.mini-table {
  width: 100%;
  border-collapse: collapse;
}
.mini-table th,
.mini-table td {
  border: 1px solid var(--border);
  padding: 6px 8px;
  font-size: 12px;
  text-align: left;
}
.ok-text {
  color: #067647;
}
.bad-text {
  color: #b42318;
}
</style>
