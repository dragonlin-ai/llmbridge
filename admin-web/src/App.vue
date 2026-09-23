<template>
  <!-- el-config-provider 让 Element Plus 内置文案（按钮/分页/日期）跟随 i18n 语言 -->
  <el-config-provider :locale="epLocale">
    <router-view />
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import { locale } from './i18n'

const epLocale = computed(() => (locale.value === 'zh' ? zhCn : en))
</script>
