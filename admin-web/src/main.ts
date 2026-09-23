import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
// Element Plus 深色模式变量表（配合 html.dark 生效）
import 'element-plus/theme-chalk/dark/css-vars.css'
// 项目主题层：设计 token → 基础样式 → Element 覆盖 → 通用组件类
import './styles/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#app')
