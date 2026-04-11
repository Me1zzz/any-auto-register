import { Radio, Space, Tag, Typography } from 'antd'

import {
  CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
  CHATGPT_REGISTRATION_MODE_CODEX_GUI,
  CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
  type ChatGPTRegistrationMode,
} from '@/lib/chatgptRegistrationMode'

const { Text } = Typography

type ChatGPTRegistrationModeSwitchProps = {
  mode: ChatGPTRegistrationMode
  onChange: (mode: ChatGPTRegistrationMode) => void
}

export function ChatGPTRegistrationModeSwitch({
  mode,
  onChange,
}: ChatGPTRegistrationModeSwitchProps) {
  const modeMeta: Record<
    ChatGPTRegistrationMode,
    {
      tagColor: string
      tagLabel: string
      description: string
    }
  > = {
    [CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN]: {
      tagColor: 'success',
      tagLabel: '默认推荐',
      description:
        '有 RT 方案会走新 PR 链路，产出 Access Token + Refresh Token。',
    },
    [CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY]: {
      tagColor: 'default',
      tagLabel: '兼容旧方案',
      description:
        '无 RT 方案会走当前旧链路，只产出 Access Token / Session，依赖 RT 的能力可能不可用。',
    },
    [CHATGPT_REGISTRATION_MODE_CODEX_GUI]: {
      tagColor: 'processing',
      tagLabel: 'GUI 模式',
      description:
        'GUI 方案会走 Codex GUI 注册流，并自动使用有头浏览器执行。',
    },
  }

  const currentModeMeta = modeMeta[mode]

  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      <Space align="center" wrap>
        <Radio.Group
          optionType="button"
          buttonStyle="solid"
          value={mode}
          onChange={(event) => onChange(event.target.value as ChatGPTRegistrationMode)}
          options={[
            {
              value: CHATGPT_REGISTRATION_MODE_REFRESH_TOKEN,
              label: '有 RT',
            },
            {
              value: CHATGPT_REGISTRATION_MODE_ACCESS_TOKEN_ONLY,
              label: '无 RT',
            },
            {
              value: CHATGPT_REGISTRATION_MODE_CODEX_GUI,
              label: 'GUI',
            },
          ]}
        />
        <Tag color={currentModeMeta.tagColor}>
          {currentModeMeta.tagLabel}
        </Tag>
      </Space>
      <Text type="secondary">
        {currentModeMeta.description}
      </Text>
    </Space>
  )
}
