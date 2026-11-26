<template>
  <span v-if="ids.length" :data-testid="ids[0]">
    <TestIdChain v-if="ids.length > 1" :ids="ids.slice(1)">
      <slot />
    </TestIdChain>
    <template v-else><slot /></template>
  </span>
</template>

<script setup lang="ts">
// 极简递归嵌套：让同一个可点击动作同时暴露多个兼容命名的 data-testid。
defineProps<{ ids: string[] }>()
</script>
