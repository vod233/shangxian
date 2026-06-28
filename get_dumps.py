import os
import subprocess
import sys

# 定义资料输出目录
TARGET_DIR = r"D:\CodingTest\111test\111"

def pull_ui_xml(output_filename):
    try:
        if not os.path.exists(TARGET_DIR):
            os.makedirs(TARGET_DIR)
            print(f"[*] 已创建目标目录: {TARGET_DIR}")

        local_path = os.path.join(TARGET_DIR, output_filename)
        phone_tmp_path = "/data/local/tmp/uidump.xml"
        
        print(f"\n[+] 正在检查 ADB 连接...")
        # 检查是否有设备连接
        check_device = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
        print(check_device.stdout)
        
        lines = [line for line in check_device.stdout.split('\n') if line.strip()]
        if len(lines) <= 1:
            print("[X] 错误：未检测到任何安卓设备！请检查手机 USB 调试是否开启，数据线是否插紧。")
            return

        print(f"[+] 正在捕获当前页面布局...")
        cmd_dump = f"adb shell uiautomator dump --compressed {phone_tmp_path}"
        res = subprocess.run(cmd_dump, shell=True, capture_output=True, text=True)
        
        if "UI hierchary dumped to" not in res.stdout and "dumped to" not in res.stderr:
            cmd_dump = f"adb shell uiautomator dump {phone_tmp_path}"
            res = subprocess.run(cmd_dump, shell=True, capture_output=True, text=True)
            
        print(f"[+] 正在将 XML 拉取到电脑...")
        cmd_pull = f'adb pull {phone_tmp_path} "{local_path}"'
        subprocess.run(cmd_pull, shell=True, capture_output=True)
        
        subprocess.run(f"adb shell rm {phone_tmp_path}", shell=True)
        
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            print(f"[√] 成功导出资料至: {local_path}")
        else:
            print(f"[X] 导出失败，可能抖音限制了 uidump，或者权限不足。")
            
    except Exception as e:
        print(f"\n[X] 脚本运行发生异常: {e}")

if __name__ == "__main__":
    try:
        print("=" * 50)
        print(" 抖音 UI XML 资料自动化抓取工具 (防闪退版) ")
        print("=" * 50)
        print("1 : 资料 1 - 评论区面板 (dump_评论区.xml)")
        print("2 : 资料 2 - 评论者个人主页 (dump_评论者主页.xml)")
        print("3 : 资料 3 (未聚焦) - 评论者私信聊天页 (dump_评论者私信页_未聚焦.xml)")
        print("4 : 资料 3 (已聚焦) - 评论者私信聊天页 (dump_评论者私信页_聚焦.xml)")
        print("5 : 资料 4 (可选) - 陌生人私信限制弹窗 (dump_私信限制弹窗.xml)")
        print("=" * 50)
        
        choice = input("请选择序号并回车: ").strip()
        
        mapping = {
            "1": "dump_评论区.xml",
            "2": "dump_评论者主页.xml",
            "3": "dump_评论者私信页_未聚焦.xml",
            "4": "dump_评论者私信页_聚焦.xml",
            "5": "dump_私信限制弹窗.xml"
        }
        
        if choice in mapping:
            pull_ui_xml(mapping[choice])
        else:
            print("[-] 输入错误。")
            
    except Exception as e:
        print(f"主程序崩溃: {e}")
        
    finally:
        print("\n" + "=" * 50)
        input("程序运行结束，按[回车键]退出窗口...")