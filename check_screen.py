import uiautomator2 as u2
import time

d = u2.connect()
print(f"设备连接成功")
print(f"屏幕分辨率: {d.window_size()}")
print(f"当前包名: {d.app_current()}")

# Check current screen
xml = d.dump_hierarchy()
if '美食' in xml:
    print("当前屏幕包含'美食'关键词")
else:
    print("当前屏幕不包含'美食'关键词")

if '筛选' in xml:
    print("当前屏幕包含'筛选'")
else:
    print("当前屏幕不包含'筛选'")

# Check top tabs
for tab in ['综合', '视频', '用户', '商品']:
    node = d.xpath(f'//*[@text="{tab}"]')
    if node.exists:
        info = node.get().info
        sel = info.get('selected', 'false')
        print(f"Tab '{tab}': selected={sel}")
