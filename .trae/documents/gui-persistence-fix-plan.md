# GUI 窗口持久化运行修复计划

## 摘要

用户反馈"GUI 窗口一直不能持久化运行显示"，经全项目 review 发现 **3 个高风险根因** 和 **2 个中风险问题**。最关键的根因是 P9 修复（QThread 信号重命名 `finished`→`result_ready`）在 `auth_dialog.py` 登录流程中**漏改了一处**，导致登录后 `_on_login_done` 槽函数因缺少参数抛 `TypeError`，登录对话框永不 accept，用户无法进入主窗口。

## 当前状态分析

### 调用链与崩溃点

```
用户运行 python dev_run.py
  → dev_run.py:190  run_pyside_with_auth
  → auth_dialog.py:341  require_login
  → auth_dialog.py:356  check_logged_in() → False（首次登录）
  → auth_dialog.py:365  LoginDialog.exec()
  → 用户输入账号密码点击"登录"
  → auth_dialog.py:291  _on_login 创建 _AuthWorker
  → auth_dialog.py:292  self._worker.finished.connect(self._on_login_done)  ← BUG
  → _AuthWorker.run() 发射 result_ready（无人监听）+ finished（连到 _on_login_done）
  → _on_login_done(self, data: dict) 收到 finished 信号（无参数）→ TypeError
  → PySide6 静默吞掉异常，self.accept() 永不执行
  → 登录对话框卡死，用户无法进入主窗口
```

### 根因详情

#### H1（高）：登录流程信号连接错误 — auth_dialog.py:292

```python
# 当前错误代码（第 291-293 行）
self._worker = _AuthWorker("POST", "/auth/login", {"email": email, "password": password})
self._worker.finished.connect(self._on_login_done)  # ← 连到内置 finished（无参数）
self._worker.start()

# 对比：注册流程已正确修复（第 317-319 行）
self._worker = _AuthWorker("POST", "/auth/register", {...})
self._worker.result_ready.connect(self._on_register_done)  # ← 正确
self._worker.start()
```

**影响**：`_AuthWorker` 的 `result_ready` 信号（携带登录结果 dict）无监听者；`_on_login_done(self, data: dict)` 连到内置 `finished`（无参数），触发 `TypeError`。登录结果丢失，`self.accept()` 永不执行，登录对话框卡死。

#### H2（高）：setQuitOnLastWindowClosed(False) 导致关窗后僵尸进程 — gui_main.py:185

```python
# gui_main.py 第 184-185 行
app.setQuitOnLastWindowClosed(False)  # ← 关窗后 app.exec() 永不返回
```

**影响**：用户点标题栏关闭按钮 → `closeEvent` 执行 `event.accept()` → 窗口销毁 → 但 `app.exec()` 因 `setQuitOnLastWindowClosed(False)` 永不返回 → 进程僵尸化。后台 QThread/定时器仍在运行，访问已销毁 widget 可能二次崩溃。

#### H3（高）：closeEvent 清理不完整 — gui_main.py:161-168

```python
# 第 161 行：清理列表遗漏 _delete_worker
for attr in ("_action_worker", "_status_worker", "_worker", "_auth_worker"):
    # ← 缺少 "_delete_worker"（dashboard_page.py:281 使用）

# 第 167-168 行：quit() 对重写 run() 的 QThread 无效，wait(3000) 不足以覆盖 15s HTTP timeout
worker.quit()       # ← no-op（ApiWorker 重写了 run()，无事件循环）
worker.wait(3000)   # ← HTTP timeout=15s，3 秒等不完
```

**影响**：关窗时若有进行中的 HTTP 请求（尤其 dashboard 的 DELETE /stats），线程未被等待，进程退出时 C++ QThread 对象被强制销毁 → segfault。

#### M2（中）：无全局 sys.excepthook — dev_run.py

`faulthandler` 只捕获 C 级 segfault，不捕获 Python 异常。H1 的 `TypeError` 被 PySide6 静默吞掉，开发者无法从日志定位。

#### 诊断代码残留 — gui_main.py:146-152, process_page.py:152-177

上一轮调试加的 `traceback.print_stack()` 和 `print("debug: ...")` 应在修复后清理。

## 修复方案

### 修复 1（H1）：auth_dialog.py 登录信号连接

**文件**：`d:\CodingTest\111test\111\gui\auth_dialog.py`
**行号**：292
**改动**：
```python
# 旧
self._worker.finished.connect(self._on_login_done)
# 新
self._worker.result_ready.connect(self._on_login_done)
```
**原因**：`_AuthWorker` 的自定义信号已改名为 `result_ready`（P9 修复），登录流程漏改。

### 修复 2（H2）：gui_main.py 关窗即退进程

**文件**：`d:\CodingTest\111test\111\gui_main.py`
**行号**：184-185, 173
**改动**：
1. 移除 `app.setQuitOnLastWindowClosed(False)`（恢复默认 True），让关窗即退进程
2. 在 `closeEvent` 的 `event.accept()` 后追加 `QApplication.quit()`，确保 app.exec() 返回

**原因**：`setQuitOnLastWindowClosed(False)` 本意防误关，但导致关窗后僵尸进程。改回默认行为，关窗即退出整个应用，避免后台线程访问已销毁 widget。

### 修复 3（H3）：gui_main.py closeEvent 清理完善

**文件**：`d:\CodingTest\111test\111\gui_main.py`
**行号**：161, 167-168
**改动**：
1. 清理列表追加 `"_delete_worker"`
2. 移除无效的 `worker.quit()`（对重写 run() 的 QThread 无效）
3. `wait(3000)` 提升到 `wait(15000)` 覆盖 HTTP timeout
4. 超时后调 `worker.terminate()` 兜底

### 修复 4（M2）：dev_run.py 添加全局异常钩子

**文件**：`d:\CodingTest\111test\111\dev_run.py`
**改动**：在 `faulthandler.enable()` 后安装 `sys.excepthook`，将 Python 未捕获异常写入 `crash_trace.log`，便于定位槽函数异常。

### 修复 5：清理诊断代码

**文件**：`d:\CodingTest\111test\111\gui_main.py`（146-152 行）、`d:\CodingTest\111test\111\gui\pages\process_page.py`（152-177 行的 debug print）
**改动**：移除上一轮调试加的 `traceback.print_stack()` 和 `print("debug: ...")` 语句。

## 假设与决策

1. **假设用户需要登录**：如果用户首次运行或 auth.json 失效，H1 会直接阻塞登录流程。即使 auth.json 有效（跳过登录），H2/H3 仍会在关窗时触发问题。因此三个高风险修复都需要执行。
2. **决策：移除 setQuitOnLastWindowClosed(False)**：原设计为防误关，但副作用（僵尸进程）比误关更严重。改回默认 True，关窗即退出整个应用。
3. **决策：不修改 settings.json 路径逻辑**（M3）：dev_run.py 已正确 `os.chdir(PROJECT_ROOT)`，当前环境下不会触发 FileNotFoundError。打包路径问题留待后续处理。
4. **决策：不修改 font() 每次读盘**（M4）：性能影响可接受，非崩溃根因。

## 验证步骤

1. **登录流程验证**：
   - 删除 `config/auth.json`（强制重新登录）
   - 运行 `python dev_run.py`
   - 输入账号密码点击登录
   - 预期：成功进入主窗口，不再卡死

2. **主窗口持久化验证**：
   - 进入主窗口后等待 60+ 秒
   - 切换到"流程控制"页，选择设备，点击"开始任务"
   - 预期：窗口持续显示不闪退，状态更新正常

3. **关窗清理验证**：
   - 在"数据看板"页点击"删除今日数据"（触发 _delete_worker）
   - 删除请求进行中关闭窗口
   - 预期：进程在 15 秒内干净退出，无僵尸进程，无 segfault

4. **异常可观测性验证**：
   - 检查 `crash_trace.log` 是否记录 Python 异常（如有）

## 修改文件清单

| 文件 | 修复项 | 行号 |
|------|--------|------|
| gui/auth_dialog.py | H1: finished→result_ready | 292 |
| gui_main.py | H2: 移除 setQuitOnLastWindowClosed(False) | 184-185 |
| gui_main.py | H2: closeEvent 末尾加 QApplication.quit() | 173 |
| gui_main.py | H3: 清理列表加 _delete_worker | 161 |
| gui_main.py | H3: 移除 quit()，wait 提升到 15000，加 terminate() | 167-168 |
| gui_main.py | 清理诊断代码 | 146-152 |
| gui/pages/process_page.py | 清理 debug print | 152-177 |
| dev_run.py | M2: 添加 sys.excepthook | 32 后 |
