import axios from 'axios'
import { ElMessage } from 'element-plus'
import { t } from '../i18n'

const request = axios.create({ timeout: 30000 })

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  (resp) => {
    // 401 统一跳登录
    if (resp.status === 401) {
      localStorage.removeItem('token')
      if (location.hash !== '#/login') location.hash = '#/login'
      return Promise.reject(resp)
    }
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        ElMessage.error(body.message || t('request.failed'))
        return Promise.reject(body)
      }
      return body.data
    }
    return body
  },
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('token')
      if (location.hash !== '#/login') location.hash = '#/login'
    }
    const msg = err.response?.data?.detail?.message || err.response?.data?.detail || err.message
    ElMessage.error(typeof msg === 'string' ? msg : t('request.failed'))
    return Promise.reject(err)
  },
)

export default request
