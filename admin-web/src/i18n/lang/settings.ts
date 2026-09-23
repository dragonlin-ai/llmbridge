/** 系统设置页（当前仅判定器一节）：判定器 5 项配置的界面文案。 */
export default {
  zh: {
    'settings.page.title': '系统设置',
    'settings.page.desc': '运行期配置：判定器接入。读取顺序：数据库 > .env > 代码默认；保存后免重启即时生效。',

    'settings.status.active': '当前生效',
    'settings.status.mismatch': '配置为 jev 但密钥缺失，实际回退 mock',

    'settings.action.refresh': '刷新',
    'settings.action.save': '保存',
    'settings.action.test': '测试连通性',
    'settings.action.clearKey': '清除密钥',
    'settings.readonly.tip': '只读账号无写权限',

    'settings.field.judge': '判定器',
    'settings.field.apiKey': 'Jev API Key',
    'settings.field.baseUrl': 'Jev Base URL',
    'settings.field.timeout': '判定超时（毫秒）',
    'settings.field.threshold': 'T2 置信度阈值',

    'settings.option.mock': 'Mock — 本地规则判定',
    'settings.option.jev': 'Jev — TypeSafe AI',
    'settings.hint.judge.mock': '本地规则判定，零外呼',
    'settings.hint.judge.jev': 'TypeSafe AI 官方判定，单次约 0.4~1.2 秒',
    'settings.hint.apiKey': '明文提交、AES-256-GCM 加密落库，界面只回显掩码；留空不修改。',
    'settings.hint.baseUrl': '仅允许 https（开发环境允许 localhost）；内网地址会被拒绝',
    'settings.hint.timeout': '单次判定超时 100~60000 毫秒；超时按判定不可用降级 L3',
    'settings.hint.threshold': 'L2 置信度低于该值时改走 L3 兜底，取值 0~1',

    'settings.key.configured': '已配置',
    'settings.key.none': '未配置',
    'settings.key.placeholder': '当前 {mask} · 留空不修改',

    'settings.source.db': '数据库',
    'settings.source.env': '.env / 默认',

    'settings.test.hint': '测试针对已保存的生效配置——修改后请先保存。',
    'settings.test.ok': '连通正常（{ms} ms）',
    'settings.test.fail': '不通：{reason}',
    'settings.msg.saved': '已保存，立即生效',
    'settings.confirm.clearKey': '确认清除库中的 Jev 密钥？清除后回落 .env 配置。',

    'settings.deciderName.jev': 'Jev（TypeSafe AI）',
    'settings.deciderName.mock': 'Mock（本地规则）',
  },
  en: {
    'settings.page.title': 'System settings',
    'settings.page.desc': 'Runtime configuration: decider integration. Read order: database > .env > code defaults; changes take effect immediately without restart.',

    'settings.status.active': 'Active',
    'settings.status.mismatch': 'Configured as jev but the key is missing — falling back to mock',

    'settings.action.refresh': 'Refresh',
    'settings.action.save': 'Save',
    'settings.action.test': 'Test connectivity',
    'settings.action.clearKey': 'Clear key',
    'settings.readonly.tip': 'Read-only account: no write access',

    'settings.field.judge': 'Decider',
    'settings.field.apiKey': 'Jev API Key',
    'settings.field.baseUrl': 'Jev Base URL',
    'settings.field.timeout': 'Timeout (ms)',
    'settings.field.threshold': 'T2 confidence threshold',

    'settings.option.mock': 'Mock — local rules',
    'settings.option.jev': 'Jev — TypeSafe AI',
    'settings.hint.judge.mock': 'Local rule-based judgment, no external calls',
    'settings.hint.judge.jev': 'TypeSafe AI official judgment, about 0.4–1.2s per call',
    'settings.hint.apiKey': 'Submitted in plaintext, stored AES-256-GCM encrypted; only a mask is shown. Leave empty to keep the current key.',
    'settings.hint.baseUrl': 'HTTPS only (localhost allowed in dev); private-network addresses are rejected',
    'settings.hint.timeout': 'Per-judgment timeout 100–60000 ms; on timeout the router falls back to L3',
    'settings.hint.threshold': 'When L2 confidence falls below this value the router falls back to L3; 0–1',

    'settings.key.configured': 'Configured',
    'settings.key.none': 'not configured',
    'settings.key.placeholder': 'Current {mask} · leave empty to keep',

    'settings.source.db': 'Database',
    'settings.source.env': '.env / default',

    'settings.test.hint': 'Tests the saved configuration — save changes first.',
    'settings.test.ok': 'Connected ({ms} ms)',
    'settings.test.fail': 'Unreachable: {reason}',
    'settings.msg.saved': 'Saved — effective immediately',
    'settings.confirm.clearKey': 'Remove the Jev API key from the database? It will fall back to the .env value.',

    'settings.deciderName.jev': 'Jev (TypeSafe AI)',
    'settings.deciderName.mock': 'Mock (local rules)',
  },
}
