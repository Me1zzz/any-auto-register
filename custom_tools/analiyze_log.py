import re
from collections import defaultdict

# 读取日志内容
with open('../.log/aaa.txt', 'r', encoding='utf-8') as f:
    content = f.read()

# 分析每个账号的注册情况
# 模式1: 开始注册第 X/200 个账号
# 模式2: [OK] 注册成功: email
# 模式3: [FAIL] 注册失败: reason
# 模式4: RuntimeError: reason

accounts = []

# 找到所有账号开始的位置
start_pattern = r'开始注册第 (\d+)/5 个账号'
starts = list(re.finditer(start_pattern, content))

for i, match in enumerate(starts):
    account_num = int(match.group(1))
    start_pos = match.start()

    # 确定这个账号的日志结束位置
    if i + 1 < len(starts):
        end_pos = starts[i + 1].start()
    else:
        end_pos = len(content)

    account_log = content[start_pos:end_pos]

    # 提取邮箱
    email_match = re.search(r'邮箱[:：]\s*(\S+@\S+)', account_log)
    email = email_match.group(1) if email_match else "未知"

    # 检查成功或失败
    ok_match = re.search(r'\[OK\] 注册成功[:：]\s*(\S+)', account_log)
    fail_match = re.search(r'\[FAIL\] 注册失败[:：]\s*(.+?)(?:\n|$)', account_log)
    runtime_error = re.search(r'RuntimeError[:：]\s*(.+?)(?:\n|$)', account_log)

    if ok_match:
        status = "成功"
        reason = ""
        email = ok_match.group(1)
    elif fail_match:
        status = "失败"
        reason = fail_match.group(1).strip()
        # 如果有RuntimeError，提取更详细的信息
        if runtime_error:
            reason = runtime_error.group(1).strip()
    elif runtime_error:
        status = "失败"
        reason = runtime_error.group(1).strip()
    else:
        status = "未知"
        reason = "日志不完整或无法判断"

    accounts.append({
        'num': account_num,
        'email': email,
        'status': status,
        'reason': reason
    })

# 打印结果
print("=" * 80)
print("账号注册结果分析")
print("=" * 80)
print(f"\n总共分析了 {len(accounts)} 个账号:\n")

success_count = 0
fail_count = 0

for acc in accounts:
    print(f"【账号 {acc['num']}】")
    print(f"  邮箱: {acc['email']}")
    print(f"  状态: {acc['status']}")
    if acc['reason']:
        print(f"  原因: {acc['reason']}")
    print()

    if acc['status'] == '成功':
        success_count += 1
    elif acc['status'] == '失败':
        fail_count += 1

print("=" * 80)
print(f"统计: 成功 {success_count} 个, 失败 {fail_count} 个, 未知 {len(accounts) - success_count - fail_count} 个")
print("=" * 80)
