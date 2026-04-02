from wcferry import Wcf

# 初始化 Wcf，这会自动向本地微信注入 dll
wcf = Wcf()

# 检查是否登录成功
if wcf.is_login():
    print("微信登录成功！")
    # 尝试给“文件传输助手”发送一条测试消息
    ret = wcf.send_text("Hello from wcferry! 接入测试", "filehelper")
    if ret == 0:
        print("发送成功，请检查文件传输助手。")
    else:
        print("发送失败。")
else:
    print("微信未登录或注入失败。")