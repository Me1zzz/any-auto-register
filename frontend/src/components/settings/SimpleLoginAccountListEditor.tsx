import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Form, Input, Space, Typography } from 'antd'

type Props = {
  name: (string | number)[]
  providerLabel?: string
  passwordHint?: string
}

export default function SimpleLoginAccountListEditor({
  name,
  providerLabel = 'SimpleLogin',
  passwordHint = '后端会自动按“邮箱 = 密码”的约定执行登录。',
}: Props) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {fields.map((field) => (
            <div
              key={field.key}
              style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(220px, 1fr) auto',
                gap: 8,
                alignItems: 'start',
              }}
            >
              <Form.Item
                label="已注册邮箱"
                name={[field.name, 'email']}
                rules={[{ required: true, message: '请输入账号邮箱' }]}
                style={{ marginBottom: 0 }}
              >
                <Input placeholder="jisu@fst.cxwsss.online" />
              </Form.Item>

              <div style={{ display: 'flex', alignItems: 'end', height: '100%' }}>
                <Button danger icon={<MinusCircleOutlined />} onClick={() => remove(field.name)}>
                  删除
                </Button>
              </div>
            </div>
          ))}

          {fields.length === 0 ? (
            <Typography.Text type="secondary">
              还没有配置 {providerLabel} 已注册账号。运行时会直接使用这些邮箱登录。
            </Typography.Text>
          ) : null}

          <Typography.Text type="secondary">
            每个邮箱都必须是已经在 {providerLabel} 完成注册和确认的账号；{passwordHint}
          </Typography.Text>

          <Button
            type="dashed"
            icon={<PlusOutlined />}
            onClick={() => add({ email: '' })}
          >
            添加已注册邮箱
          </Button>
        </Space>
      )}
    </Form.List>
  )
}
