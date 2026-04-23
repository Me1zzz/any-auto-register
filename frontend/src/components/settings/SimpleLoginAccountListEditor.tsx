import { Form, Input, Space, Typography } from 'antd'

type Props = {
  name: (string | number)[]
  providerLabel?: string
  passwordHint?: string
}

export default function SimpleLoginAccountListEditor({
  name,
  providerLabel = 'SimpleLogin',
  passwordHint = 'Backend signs in with the provider-specific default password rule.',
}: Props) {
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <Typography.Text type="secondary">
        Leave this empty if you do not want to preload any registered {providerLabel} accounts.
      </Typography.Text>

      <Form.Item
        label="Registered Emails"
        name={name}
        extra="One email per line."
        style={{ marginBottom: 0 }}
      >
        <Input.TextArea
          rows={5}
          placeholder={'jisu@fst.cxwsss.online\nlogon@fst.cxwsss.online'}
        />
      </Form.Item>

      <Typography.Text type="secondary">
        Each email must already be a verified {providerLabel} account. {passwordHint}
      </Typography.Text>
    </Space>
  )
}
