import { DeleteOutlined } from '@ant-design/icons'
import { Button, Card, Form, Input, InputNumber, Select, Space, Tag, Typography, theme } from 'antd'

import SimpleLoginAccountListEditor from '@/components/settings/SimpleLoginAccountListEditor'
import {
  ADDABLE_ALIAS_GENERATION_SOURCE_TYPES,
  getAliasGenerationSourceTypeLabel,
  type AliasGenerationSourceType,
  type AliasGenerationTestDraftSource,
} from '@/lib/aliasGenerationTest'

type Props = {
  index: number
  source: AliasGenerationTestDraftSource
  onRemove: () => void
  onTypeChange: (nextType: AliasGenerationSourceType) => void
}

const INTERACTIVE_SOURCE_TYPES = new Set<AliasGenerationSourceType>([
  'myalias_pro',
  'secureinseconds',
  'emailshield',
  'simplelogin',
  'alias_email',
])

const SOURCE_TYPE_OPTIONS = ADDABLE_ALIAS_GENERATION_SOURCE_TYPES.map((type) => ({
  label: getAliasGenerationSourceTypeLabel(type),
  value: type,
}))

function renderInteractiveMetaTag(sourceType: AliasGenerationSourceType) {
  if (!INTERACTIVE_SOURCE_TYPES.has(sourceType)) {
    return <Tag>legacy-compatible</Tag>
  }

  if (sourceType === 'simplelogin') {
    return <Tag color="purple">existing-account</Tag>
  }

  return <Tag color="blue">interactive</Tag>
}

export default function AliasGenerationSourceCard({
  index,
  source,
  onRemove,
  onTypeChange,
}: Props) {
  const { token } = theme.useToken()
  const sourceType = String(source.type || '').trim() as AliasGenerationSourceType
  const sourceId = String(source.id || '').trim() || `source-${index + 1}`
  const baseName = ['sources', index] as (string | number)[]
  const isSimpleGenerator = sourceType === 'simple_generator'
  const isSimpleLogin = sourceType === 'simplelogin'
  const isEmailShield = sourceType === 'emailshield'
  const supportsSingleAccountAliasCount = isSimpleLogin || isEmailShield
  const showCommonInteractiveFields = INTERACTIVE_SOURCE_TYPES.has(sourceType)
  const showConfirmationInbox = sourceType === 'myalias_pro'
    || sourceType === 'secureinseconds'
    || sourceType === 'alias_email'

  return (
    <Card
      size="small"
      title={(
        <Space wrap size={[8, 6]}>
          <Typography.Text strong>{sourceId}</Typography.Text>
          <Tag>{getAliasGenerationSourceTypeLabel(sourceType)}</Tag>
          {renderInteractiveMetaTag(sourceType)}
        </Space>
      )}
      extra={(
        <Space wrap size={8}>
          <Select
            size="small"
            style={{ width: 200 }}
            value={sourceType}
            options={SOURCE_TYPE_OPTIONS}
            onChange={(value) => onTypeChange(value as AliasGenerationSourceType)}
          />
          <Button danger icon={<DeleteOutlined />} onClick={onRemove}>
            删除
          </Button>
        </Space>
      )}
      style={{ marginBottom: 12 }}
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Form.Item name={[...baseName, 'type']} hidden>
          <Input />
        </Form.Item>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 12,
          }}
        >
          <Form.Item
            label="Source ID"
            name={[...baseName, 'id']}
            rules={[{ required: true, message: '请填写 Source ID' }]}
            style={{ marginBottom: 0 }}
          >
            <Input placeholder="simplelogin-primary" />
          </Form.Item>

          {showCommonInteractiveFields ? (
            <Form.Item
              label="State Key"
              name={[...baseName, 'state_key']}
              style={{ marginBottom: 0 }}
            >
              <Input placeholder={sourceId} />
            </Form.Item>
          ) : null}

          {showCommonInteractiveFields ? (
            <Form.Item
              label="目标别名数"
              name={[...baseName, 'alias_count']}
              style={{ marginBottom: 0 }}
            >
              <InputNumber min={0} style={{ width: '100%' }} placeholder="3" />
            </Form.Item>
          ) : null}

          <Form.Item
            label="补货水位"
            name={[...baseName, 'low_watermark']}
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={0} style={{ width: '100%' }} placeholder="0" />
          </Form.Item>

          {supportsSingleAccountAliasCount ? (
            <Form.Item
              label="单账号别名上限"
              name={[...baseName, 'single_account_alias_count']}
              style={{ marginBottom: 0 }}
            >
              <InputNumber min={0} style={{ width: '100%' }} placeholder="3" />
            </Form.Item>
          ) : null}
        </div>

        {isSimpleGenerator ? (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: 12,
            }}
          >
            <Form.Item label="前缀" name={[...baseName, 'prefix']} style={{ marginBottom: 0 }}>
              <Input placeholder="msi." />
            </Form.Item>
            <Form.Item label="后缀" name={[...baseName, 'suffix']} style={{ marginBottom: 0 }}>
              <Input placeholder="@example.com" />
            </Form.Item>
            <Form.Item label="总生成数" name={[...baseName, 'count']} style={{ marginBottom: 0 }}>
              <InputNumber min={0} style={{ width: '100%' }} placeholder="3" />
            </Form.Item>
            <Form.Item label="中间段最短长度" name={[...baseName, 'middle_length_min']} style={{ marginBottom: 0 }}>
              <InputNumber min={1} style={{ width: '100%' }} placeholder="3" />
            </Form.Item>
            <Form.Item label="中间段最长长度" name={[...baseName, 'middle_length_max']} style={{ marginBottom: 0 }}>
              <InputNumber min={1} style={{ width: '100%' }} placeholder="6" />
            </Form.Item>
          </div>
        ) : null}

        {sourceType === 'myalias_pro' ? (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
              gap: 12,
            }}
          >
            <Form.Item label="注册页 URL" name={[...baseName, 'provider_config', 'signup_url']} style={{ marginBottom: 0 }}>
              <Input placeholder="https://myalias.pro/signup/" />
            </Form.Item>
            <Form.Item label="登录页 URL" name={[...baseName, 'provider_config', 'login_url']} style={{ marginBottom: 0 }}>
              <Input placeholder="https://myalias.pro/login/" />
            </Form.Item>
          </div>
        ) : null}

        {sourceType === 'secureinseconds' ? (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
              gap: 12,
            }}
          >
            <Form.Item label="注册页 URL" name={[...baseName, 'provider_config', 'register_url']} style={{ marginBottom: 0 }}>
              <Input placeholder="https://alias.secureinseconds.com/auth/register" />
            </Form.Item>
            <Form.Item label="登录页 URL" name={[...baseName, 'provider_config', 'login_url']} style={{ marginBottom: 0 }}>
              <Input placeholder="https://alias.secureinseconds.com/auth/signin" />
            </Form.Item>
          </div>
        ) : null}

        {isEmailShield ? (
          <div
            style={{
              padding: 12,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorBorder}`,
              background: token.colorBgElevated,
            }}
          >
            <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
              EmailShield 已注册账号
            </Typography.Text>
            <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              一行一个邮箱。保存时会自动转换为后端原有的 `accounts: [{'{'} email {'}'}]` 结构。
            </Typography.Text>
            <SimpleLoginAccountListEditor
              name={[...baseName, 'provider_config', 'accounts']}
              providerLabel="EmailShield"
              passwordHint="如果 source JSON 里附带 password 字段，前端会继续保留。"
            />
          </div>
        ) : null}

        {isSimpleLogin ? (
          <>
            <Form.Item label="站点 URL" name={[...baseName, 'provider_config', 'site_url']} style={{ marginBottom: 0 }}>
              <Input placeholder="https://simplelogin.io/" />
            </Form.Item>

            <div
              style={{
                padding: 12,
                borderRadius: token.borderRadius,
                border: `1px solid ${token.colorBorder}`,
                background: token.colorBgElevated,
              }}
            >
              <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
                SimpleLogin 已注册账号
              </Typography.Text>
              <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
                一行一个邮箱。保存时会自动转换为后端原有的 `accounts: [{'{'} email {'}'}]` 结构。
              </Typography.Text>
              <SimpleLoginAccountListEditor name={[...baseName, 'provider_config', 'accounts']} />
            </div>
          </>
        ) : null}

        {sourceType === 'alias_email' ? (
          <>
            <Form.Item label="登录页 URL" name={[...baseName, 'provider_config', 'login_url']} style={{ marginBottom: 0 }}>
              <Input placeholder="https://alias.email/users/login/" />
            </Form.Item>

            <Typography.Text type="secondary">
              alias.email 通过确认邮箱里的 magic link 完成登录，确认邮箱配置在下方设置。
            </Typography.Text>
          </>
        ) : null}

        {showConfirmationInbox ? (
          <div
            style={{
              padding: 12,
              borderRadius: token.borderRadius,
              border: `1px solid ${token.colorBorder}`,
              background: token.colorBgElevated,
            }}
          >
            <Form.Item name={[...baseName, 'confirmation_inbox', 'provider']} hidden>
              <Input />
            </Form.Item>

            <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
              确认邮箱配置
            </Typography.Text>

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                gap: 12,
              }}
            >
              {sourceType === 'alias_email' ? null : (
                <Form.Item label="确认邮箱账号" name={[...baseName, 'confirmation_inbox', 'account_email']} style={{ marginBottom: 0 }}>
                  <Input placeholder="real@example.com" />
                </Form.Item>
              )}

              {sourceType === 'myalias_pro' || sourceType === 'secureinseconds' ? (
                <Form.Item label="确认邮箱密码" name={[...baseName, 'confirmation_inbox', 'account_password']} style={{ marginBottom: 0 }}>
                  <Input.Password placeholder="mail-pass" />
                </Form.Item>
              ) : null}

              <Form.Item label="匹配邮箱" name={[...baseName, 'confirmation_inbox', 'match_email']} style={{ marginBottom: 0 }}>
                <Input placeholder="real@example.com" />
              </Form.Item>
            </div>
          </div>
        ) : null}
      </Space>
    </Card>
  )
}
