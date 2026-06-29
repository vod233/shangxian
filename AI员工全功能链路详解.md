# AI员工全功能链路详解

> 审查日期：2026-06-27  
> 模式：管道编排全开（like + acquisition + video_comment + comment_lead）  
> 概率决策：全部 100% 执行（测试期） | 时间随机：全部固定中点（测试期）  

---

## 流程图（总览）

```
start()
  │
  ├─ [前置] 夜间检查 → 日限额检查
  ├─ [阶段0] launch_app() → 清理设备痕迹 → 网络检查
  │
  └─ for each keyword:
       │
       ├─ [阶段1] EnterSearchAction  — 搜索关键词
       ├─ [阶段2] ApplyFiltersAction — 按时间筛选
       ├─ [阶段3] EnterFirstVideoAction — 点击第一个视频
       │
       └─ [阶段4] _video_loop() — 循环刷视频
            │
            for each video:
            ├─ [4A] _recover_to_video_page — 确认为视频页
            ├─ [4B] GetCurrentVideoLinkAction — 提取分享链接+标题
            ├─ [4C] 防重判断（token/文案去重）
            ├─ [4D] record_video — 入库，已处理则跳过
            ├─ [4E] ★ pipeline.run(PIPELINE_STEPS) ★
            │      │
            │      ├─ Step 1/4: _step_like          — 点赞
            │      ├─ Step 2/4: _step_acquisition   — 私域获客
            │      ├─ Step 3/4: _step_video_comment — AI视频评论
            │      └─ Step 4/4: _step_comment_lead  — 评论区截流
            │
            ├─ [4F] SwipeNextVideoAction — 滑动到下一个视频
            ├─ [4G] 网络检查 → 视频停留等待 → record_action('video')
            └─ loop
```

---

## 阶段0：启动

### 0.1 `start()` — 任务流主入口
**文件**: `dy/task_runner.py:420`
```
TikTokTaskFlow.start()
  ├─ anti.check_night_mode()     → 如果在夜间静默时段，阻塞等待至早上
  ├─ db.get_daily_stats()        → 打印今日已有统计数据
  ├─ 日视频上限检查              → stats['videos'] >= max_daily_videos 则终止
  ├─ anti.daily_limit.check_all_limits() → 所有互动都超限则终止
  ├─ _check_stop()               → 检查用户是否手动停止/暂停
  └─ runner.launch_app()         → 见下方 0.2
```

### 0.2 `launch_app()` — 拉起抖音
**文件**: `dy/main_controller.py:94`
```
ScoutTaskRunner.launch_app()
  ├─ app_mgr.start()             → TikTokManager.start()
  │   └─ 执行 ADB: am start -n com.ss.android.ugc.aweme/...
  ├─ app_mgr.wait_for_foreground() → 轮询检查包名是否在前台(最长30s)
  └─ run_action(EnsureHomeAction)  → 确保回到首页 + 处理青少年弹窗
      └─ 策略: 检查当前页面，若非首页则 press("back") 逐层返回
```

### 0.3 清理设备痕迹 + 网络检查
**文件**: `dy/task_runner.py:451-459`
```
anti.cleanup_device(device)
  ├─ 清理 logcat 缓存 (logcat -c)
  └─ 清理 /data/local/tmp/minicap/minitouch 等工具痕迹

_check_network()
  ├─ anti.check_network_status()  → dumpsys telephony.registry
  │   ├─ 解析信号强度 (dBm值 → 0-4等级)
  │   ├─ 检测网络类型 (4G/5G/WiFi)
  │   └─ level <= 0 时标记不可用
  └─ 弱网 → _interruptible_sleep(11.5s) 等待恢复
```

---

## 阶段1：搜索关键词

### 1.1 `EnterSearchAction.execute(keyword)`
**文件**: `dy/actions/navigation.py`
**调用**: `runner.run_action(EnterSearchAction, keyword)`

```
EnterSearchAction.perform(keyword)
  ├─ check_preconditions()  → 确认 APP 在前台
  └─ execute(keyword)
      ├─ 定位搜索按钮 → device(text="搜索").click()
      ├─ human_sleep('fast')  → 固定 0.5s
      ├─ 定位搜索输入框:
      │   ├─ 尝试1: XPath '//android.widget.EditText'
      │   └─ 尝试2: clickable EditText 节点
      ├─ 输入关键词:
      │   ├─ 方法1: resource-id set_text(keyword)
      │   └─ 方法2: set_fastinput_ime(True) → send_keys(keyword)
      ├─ human_sleep('normal') → 固定 1.4s
      ├─ 点击搜索按钮 → device(text="搜索").click()
      ├─ human_sleep('page_load') → 固定 3.8s
      └─ 返回 True / False
```

**策略应用**:
- `human_sleep`: 确定性固定值（测试期），无随机化
- `human_click`: 坐标 ±8px 抖动（空间随机保留）

---

## 阶段2：筛选

### 2.1 `ApplyFiltersAction.execute(sort_mode)`
**文件**: `dy/actions/navigation.py`
**调用**: `runner.run_action(ApplyFiltersAction, sort_mode='latest')`

```
ApplyFiltersAction.execute(sort_mode)
  ├─ 定位并点击筛选按钮 → content-desc 含"筛选"的节点
  ├─ human_sleep('normal') → 固定 1.4s
  ├─ 切换排序模式:
  │   ├─ sort_mode='latest'  → 点击"最新发布"
  │   └─ sort_mode='popular' → 点击"最多点赞"
  ├─ human_sleep('normal')
  └─ 返回 True / False（失败不阻断，继续用默认结果）
```

---

## 阶段3：进入视频流

### 3.1 `EnterFirstVideoAction.execute()`
**文件**: `dy/actions/navigation.py`

```
EnterFirstVideoAction.execute()
  ├─ 定位搜索结果列表第一个视频:
  │   ├─ 方法1: XPath 含 "封面" 的 ImageView
  │   ├─ 方法2: RecyclerView 第一子项
  │   └─ human_click(x, y)  → 坐标 ±8px 抖动
  ├─ human_sleep('page_load') → 固定 3.8s
  ├─ _recover_to_video_page("进入第一个视频后") → 确认为视频页
  └─ 返回 True / False
```

---

## 阶段4：视频循环（核心）

### 4.0 `_video_loop()` — 循环结构
**文件**: `dy/task_runner.py:561`

```
_video_loop()
  ├─ video_count = 0, max_videos = 配置(默认10)
  ├─ recovery_failures = 0  (连续恢复失败计数，≥3 触发重置)
  │
  └─ while video_count < max_videos:
       ├─ ① 日上限检查: stats['videos'] >= max_daily → _stop()
       ├─ ② video_count++, _dismiss_video_context_menu_if_present()
       ├─ ③ A.提取视频信息 → B.互动管道 → C.滑动下一个视频
       └─ ④ 视频停留等待 → record_action('video')
```

### 4.1 视频信息提取前 — 状态确认
```
_recover_to_video_page("提取视频信息前", max_back=3)
  ├─ 主动 touch.up(0,0) 清理僵尸触控
  ├─ _detect_page_state() 识别页面状态:
  │   └─ 8种状态: context_menu | share_panel | comment_panel | input_or_chat
  │               profile_sheet | video_page | profile_page | home_or_search
  ├─ 非 video_page → press("back") → 重新检测 (最多3次)
  └─ 返回 True(已是视频页) / False(恢复失败)
  
  失败处理: recovery_failures++, ≥3 则 _reset_and_reenter_video_flow()
```

### 4.2 `GetCurrentVideoLinkAction` — 提取视频信息
**文件**: `dy/actions/interaction.py`

```
_run_feature_safely("提取视频信息/分享链接", callback)  ← 安全边界包裹
  ├─ 执行前: _recover_to_video_page("提取视频信息-执行前")
  ├─ callback() → GetCurrentVideoLinkAction.execute()
  │   ├─ 定位分享按钮 → 多种定位策略:
  │   │   ├─ content-desc 正则: r'分享.*按钮'
  │   │   ├─ XPath: @clickable=true 且含"分享"
  │   │   └─ 兜底坐标: (w*0.92, h*0.63)
  │   ├─ human_click → 弹出分享面板
  │   ├─ 点击"复制链接" → 获取剪贴板 URL + share_token
  │   ├─ 读取视频描述 → 提取 description
  │   └─ 返回 (url, share_token, description)
  ├─ _dismiss_video_context_menu_if_present()
  ├─ _recover_to_video_page("提取视频信息-执行后")
  └─ 返回 (stable, result)
```

### 4.3 防重判断 + 标题提取 + 入库
```
is_duplicate:
  ├─ share_token == last_share_token  → 重复, 退出循环
  └─ description == last_description  → 重复, 退出循环

_extract_title_from_description(description):
  ├─ 按行分割, 过滤 URL
  ├─ 保留 6 ≤ len ≤ 60 的行
  └─ 取首行 → 无匹配时用 keyword 兜底

db.record_video(video_id, keyword, url, note_title=video_title):
  ├─ 按天建表 (videos_YYYYMMDD)
  ├─ INSERT OR IGNORE  → 已存在返回 False
  └─ 新视频返回 True → 进入管道互动
```

---

## 阶段5：管道执行（★核心★）

### 5.0 `PipelineExecutor.run()` — 管道引擎
**文件**: `dy/pipeline.py:63`

> ⚠️ FIX-12 更正：`dy/pipeline.py` 实际不存在，文档原描述与代码不符。
> 4 个步骤的管道执行逻辑实际内联在 `dy/task_runner.py` 的 `_video_loop()` 中
> （B.1 见 task_runner.py:671，B.2 见 task_runner.py:695，B.3 见 task_runner.py:745，B.4 见 task_runner.py:798）。
> 下文保留管道逻辑的概念性说明，便于理解步骤间的状态转移与阻断策略。

```
pipeline.run(PIPELINE_STEPS, context)

  预计算: 遍历4个step → 找出所有已启用的step.id → remaining_step_ids

  for step in [like, acquisition, video_comment, comment_lead]:
    
    ① 阻断检查: 如果 blocked=True → 跳过
        
    ② 开关检查:
       per_step_config.get(step.id)           ← 优先 per-step 粒度
       |→ None → _interaction_enabled(key)   ← 回退 mode-level
       |→ False → 跳过
        
    ③ 限额检查: 
       for q in step.quota_keys:
           anti.can_do(q)  ← 内存计数 + 线程锁
           |→ False → 跳过本步
        
    ④ 概率检查:
       _should_interact(probability_key)  ← 测试期全部返回 True
       |→ False → 跳过
        
    ⑤ 执行:
       |─ self_managed=False: _run_feature_safely(label, callback)
       |   ├─ 执行前: _recover_to_video_page("XXX-执行前")
       |   ├─ callback() → step.execute(flow, context)
       |   ├─ _dismiss_video_context_menu_if_present()
       |   └─ 执行后: _recover_to_video_page("XXX-执行后")
       |
       |─ self_managed=True: step.execute(flow, context) 直接调用
        
    ⑥ record_action: 
       _should_record_quota(result)  → 仅实际动作成功时记录
       |→ bool: result 本身
       |→ (bool,bool): 取 result[1]
        
    ⑦ 阻断判断:
       not stable && on_failure=="block_rest" → blocked=True
        
    ⑧ 步骤间间隔: 
       step.id in remaining_step_ids[:-1] → _interruptible_sleep(1.75s)
```

### 5.1 Step 1/4 — 点赞 `_step_like`
**文件**: `dy/pipeline.py:166`
**安全包裹**: `_run_feature_safely("点赞", callback)` → 执行前后各一次视频页确认

```
_step_like(flow, ctx)
  └─ flow.runner.run_action(DoubleClickLikeAction)

DoubleClickLikeAction.execute()   (dy/actions/interaction.py)
  ├─ 定位心形按钮:
  │   ├─ XPath: '//*[@content-desc="点赞"]'
  │   └─ 兜底坐标: (w*0.90, h*0.53)
  ├─ human_double_click(x,y)  → 两次点击
  │   ├─ 坐标: ±10px 抖动
  │   ├─ 间隔: 固定 0.1s (测试期)
  │   └─ 使用 fast_tap(touch.down → sleep(0.045) → touch.up)
  ├─ 验证点赞:
  │   ├─ content-desc 变为 "已点赞" / "你已赞过"
  │   └─ 或按钮变为红色/选中态
  └─ 返回 True / False

_result: (True, liked_bool)
→ liked=True → db.update_interaction(video_id, "like") → record_action("like")
→ on_failure="continue" → 失败不阻断
```

**配额**: `quota_keys=["like"]`, 日限额 80 次  
**阻断策略**: `on_failure="continue"` — 点赞不影响后续  

---

### 5.2 Step 2/4 — 私域获客 `_step_acquisition`
**文件**: `dy/pipeline.py:177`
**安全包裹**: `_run_feature_safely("私域获客", callback)`

```
_step_acquisition(flow, ctx)
  └─ flow.runner.run_action(FollowAuthorAction)

FollowAuthorAction.execute()   (dy/actions/interaction.py)
  
  ① 进作者主页:
     ├─ 点击头像区域 → (w*0.10, h*0.65)
     ├─ human_swipe_curve(w*0.72→w*0.10, h/2)  ← 从右侧边缘左滑返回(0.13s)
     │   └─ 使用贝塞尔曲线 + 起止点 ±10px 抖动
     └─ human_sleep('page_load') → 固定 3.8s

  ② 读取粉丝数:
     ├─ 定位粉丝数字文本 → XPath 含"粉丝"的节点
     └─ _parse_follower_text():
         ├─ "1.2万粉丝" → 1.2
         ├─ "7146粉丝"  → 0.7146
         ├─ "5w"        → 5.0
         └─ 返回 float or None

  ③ 粉丝阈值过滤:
     min_followers = config.get('min_followers_threshold', 0)
     ├─ follower_count < min_followers → 跳过关注
     └─ 跳过时仍记录 db("skip")

  ④ 执行关注:
     ├─ 定位关注按钮 → XPath 含"关注"的 Button/TextView
     ├─ human_click → 坐标 ±8px 抖动
     ├─ 验证: 按钮文本变为"已关注" / "互相关注"
     ├─ human_sleep('normal') → 固定 1.4s
     └─ followed = True/False

  ⑤ 私信 (可选, 依赖 enable_private_message 开关):
     ├─ 粉丝阈值: pm_followers >= pm_followers_threshold
     ├─ 定位"发私信"按钮 → XPath/文本匹配
     ├─ human_click → 进入私信页
     ├─ 输入话术: message_list[0]  (测试期: 固定取第一条)
     │   ├─ _set_text_to_input → 0.22s 等待 → set_text/send_keys
     │   └─ 定位发送按钮 → click → 验证发送
     ├─ _close_comment_input_if_open → press("back")
     └─ private_message_sent = True/False

  ⑥ 返回视频页:
     ├─ press("back") × 2 (退出私信页→退出作者页)
     └─ _recover_to_video_page("关注/私信后")

  返回值: dict {
      "followed": bool,
      "private_message_sent": bool,
      "returned_to_video": bool,
      "follower_count": float
  }

_result:
├─ dict → stable = result["returned_to_video"]
│   followed=True → db.update_interaction("follow")
│   pm_sent=True  → db.update_interaction("private_message")
│
├─ 非dict(旧版兼容) → stable=True, 保守记录 follow
└─ on_failure="block_rest" → stable=False 时阻断后续所有步骤!
```

**配额**: `quota_keys=["follow", "private_message"]`, 日限额 20+15 次  
**阻断策略**: `on_failure="block_rest"` — 失败后 AI视频评论 & 评论区截流 全部跳过  

---

### 5.3 Step 3/4 — AI视频评论 `_step_video_comment`
**文件**: `dy/pipeline.py:205`
**安全包裹**: `_run_feature_safely("AI视频评论", callback)`

```
_step_video_comment(flow, ctx)

  ① AI生成评论文本:
     flow.reply_agent.generate_reply(title, keyword)
     
     DYReplyAgent.generate_reply()   (dy/ai_reply_agent.py:48)
     ├─ _normalize_text(title)  → 去多余空白
     ├─ is_enabled() 检查  → ai_reply.enabled != False
     ├─ 2次尝试:
     │   ├─ _call_model(title, keyword, strict_retry=False)
     │   │   ├─ 云端模式: cloud_ai.post("/ai/generate-video-comment", {keyword, title})
     │   │   └─ 本地模式: ChatOpenAI(DeepSeek) 调用
     │   │       ├─ SystemMessage: → 300字系统指令（语气真诚、10-28汉字、无引流...）
     │   │       ├─ HumanMessage: → 标题+关键词
     │   │       └─ _extract_response_text → 返回字符串
     │   ├─ _sanitize_reply(candidate):
     │   │   ├─ 去"评论:"前缀
     │   │   ├─ 去引号、#@符号
     │   │   ├─ 连续!!→!, ??→?
     │   │   └─ 智能截断: >38字符时找自然断点(。，、…) → 36字符兜底
     │   └─ _is_valid_reply(candidate):
     │       ├─ 长度 6~38 汉字
     │       ├─ 无换行
     │       ├─ 8种违规模式过滤: 微信/QQ/手机号/链接/价格承诺/色情/政治/暴力
     │       └─ !!或??不超过1个
     │
     └─ 全部失败 → _build_safe_fallback(title):
         ├─ 教程/攻略类 → "这个思路很实用，先收藏慢慢看"
         ├─ 测评/对比类 → "对比得很清楚，确实有参考价值"
         ├─ 穿搭/护肤类 → "这条内容很有参考性，思路挺清晰"
         ├─ 旅行/探店类 → "这条分享很有氛围感，信息也挺实用"
         ├─ 健身/运动类 → "内容很清晰，照着做会更容易坚持"
         └─ 通用 → "内容讲得挺清楚，确实有参考价值"

  ② 无可用文本 → 跳过 (不写数据库)

  ③ PostCommentAction.execute(comment_text):
     (dy/actions/commenting.py:212)
     ├─ _find_bottom_edit_text(timeout=1)
     │   └─ 查找可见且 enabled 的 EditText → 取最靠屏幕底部的
     ├─ 未找到 → 点击输入框占位文本:
     │   └─ hint列表: ["善语结善缘","发条评论","说点什么...","有爱评论"]
     ├─ _set_text_to_input(d, edit_text, text):
     │   ├─ edit_text.click() → 0.22s 等待
     │   ├─ 方法1: resource-id set_text(text)
     │   └─ 方法2: fastinput → clear_text → send_keys(text)
     │
     ├─ 发送循环 (最多3次):
     │   ├─ _find_clickable_send_button()  → visible+clickable+enabled 按钮
     │   ├─ _click_node_center() → 点击发送按钮
     │   ├─ 等待 1.15s
     │   ├─ ★三级验证链★:
     │   │   ├─ ① _input_is_cleared(d)     ← 最强: 输入框消失或为空
     │   │   ├─ ② _message_visible(d,text)  ← 次强: 评论出现在页面可见节点
     │   │   └─ ③ not _input_still_contains(d,text) ← 兜底: 文字不在输入框
     │   └─ 验证通过 → 返回 True
     │
     └─ 3次失败 → press("enter") 兜底 → 等待 1.5s → 再次三级验证

_result: (True, posted_bool)
├─ posted=True  → db.update_interaction("comment") → record_action("comment")
│   logger: ✅ 视频评论发送成功
└─ posted=False → logger: ⚠️ 视频评论发送失败
```

**配额**: `quota_keys=["comment"]`（与评论区截流共享日50次）  
**阻断策略**: `on_failure="continue"` — 失败不影响后续截流  

---

### 5.4 Step 4/4 — 评论区截流 `_step_comment_lead`
**文件**: `dy/pipeline.py:237`
**安全包裹**: 无外层包裹（`self_managed=True`），步骤内自行管理全流程

```
_step_comment_lead(flow, ctx)
  └─ flow._run_comment_lead_safely(video_title, keyword)

_run_comment_lead_safely()   (dy/task_runner.py:371)
  
  ① 执行前恢复:
     ├─ _detect_page_state()  → 记录执行前状态
     ├─ _recover_to_video_page("评论区AI截流-执行前") → 确认为视频页
     └─ 失败 → return (False, False)

  ② OpenCommentSectionAction.execute():
     (dy/actions/commenting.py:206)
     ├─ 定位评论区主按钮:
     │   ├─ XPath 动态匹配: content-desc 正则 r'^评论(评论|[\d万].*)，按钮$'
     │   ├─ 候选节点 ≥2 → 取第2个 (避免重复标签)
     │   └─ 候选 <2  → 兜底 XPath + 兜底坐标(w*0.92, h*0.63)
     ├─ human_click → 打开评论区面板
     └─ human_sleep('normal') → 固定 1.4s

  ③ 打开后确认:
     ├─ _dismiss_video_context_menu_if_present()
     ├─ _detect_page_state()
     └─ 状态不是 comment_panel 或 input_or_chat → 打开失败
         → _recover_to_video_page → return (recovered, False)

  ④ ProcessCommentSectionAction.execute():
     (dy/actions/commenting.py:245)
     
     ┌─ 循环扫描评论区 ────────────────────────────┐
     │                                               │
     │  while swipe_count < max_comment_swipes(默认2) │
     │    and reviewed_count < max_ai_comment_reviews(默认20): │
     │                                               │
     │  ① _process_current_screen_comments():       │
     │     ├─ XPath 获取所有可见评论文本节点          │
     │     ├─ 去重 (processed_comments set)          │
     │     ├─ _is_reviewable_comment(text):          │
     │     │   ├─ len(clean) < 3 → 跳过              │
     │     │   └─ 忽略词: 作者/置顶/回复/展开/赞/分享 │
     │     │                                         │
     │     └─ is_intent_comment(text,...):           │
     │         ├─ 本地模式/AI禁用:                    │
     │         │   ├─ 30+默认意向词正则:              │
     │         │   │   "怎么买|哪里买|在哪|求|价格|    │
     │         │   │    多少钱|贵吗|好用吗|靠谱吗|     │
     │         │   │    怎么样|真的吗|有效吗|值得|    │
     │         │   │    上车|蹲|等一个|..."           │
     │         │   └─ 自定义关键词匹配(intent_keywords)│
     │         │                                     │
     │         └─ AI模式:                             │
     │             ├─ 云端AI: /ai/check-intent-comment│
     │             └─ 本地AI: ChatOpenAI(t=0.1)      │
     │                 → System: "判断评论是否表达了  │
     │                   明确需求/咨询意愿/购买兴趣"   │
     │                 → 输出 YES/NO                 │
     │                                               │
     │  ② 发现意向评论:                               │
     │     _interact_with_potential_customer():      │
     │     ├─ generate_lead_reply(comment,title,key): │
     │     │   ├─ AI生成楼中楼回复 (10-32汉字)        │
     │     │   ├─ 规则: "引导看主页, 不出现微信/私信  │
     │     │   │    /电话/二维码/链接/价格承诺"       │
     │     │   └─ 失败 → _build_lead_fallback():     │
     │     │       ├─ 问价类→"我主页有整理，可以先看下"│
     │     │       ├─ 教程类→"主页放了相关整理，可参考"│
     │     │       └─ 通用类→"这个我主页有说，可以看看"│
     │     │                                         │
     │     ├─ comment_node.click()                   │
     │     │   human_sleep('normal') → 1.4s          │
     │     │                                         │
     │     ├─ _focus_reply_input():                  │
     │     │   └─ 点击提示词: "回复"/"回复评论"/      │
     │     │       "善语结善缘"/"发条评论"            │
     │     │                                         │
     │     └─ _send_text_from_focused_input():       │
     │         ├─ 输入文本 → 0.85s → 找发送按钮       │
     │         ├─ 发送 + ★三级验证链★ (同视频评论)    │
     │         ├─ _close_comment_input_if_open()      │
     │         └─ sent=True → self._comment_made=True │
     │                                               │
     │  ③ 无更多评论时:                               │
     │     ├─ 已到底部(无更多评论) → break            │
     │     ├─ 已达AI识别上限 → break                  │
     │     └─ _swipe_up_comments() → 贝塞尔滑动       │
     │         ├─ 容器存在: 区域内曲线滑动             │
     │         └─ 容器不存在: 全屏 70%→30% 曲线滑动   │
     │         swipe_count++, 固定 1.5s 等待          │
     └───────────────────────────────────────────────┘

  ⑤ 关闭评论区:
     _close_comment_section()  (尝试3次)
     ├─ _close_comment_input_if_open()  → 关闭键盘
     ├─ _comment_panel_open() 检查  → 评论区已关→True
     └─ press("back") → human_sleep('fast') → 重试
     → 返回 (closed_ok: bool, comment_made: bool)

  ⑥ 执行后恢复:
     ├─ _detect_page_state()  → 记录执行后状态
     └─ _recover_to_video_page("评论区AI截流-执行后") → 回到视频页

_result: (recovered, comment_made)
├─ comment_made=True  → db.update_interaction("comment") → record_action("comment")
│   logger: ✅ 评论区截流：成功发送楼中楼回复
├─ recovered=False   → logger: ⚠️ 恢复视频页失败 → on_failure="block_rest"
└─ 无意向评论        → logger: 未找到意向评论，未发送回复
```

**配额**: `quota_keys=["comment"]`（与AI视频评论共享日50次）  
**阻断策略**: `on_failure="block_rest"` — 恢复失败时阻断（但因是最后一步，实际无影响）  

---

## 阶段6：滑动到下一个视频

### 6.1 状态恢复 + 滑动
**文件**: `dy/task_runner.py:658-672`

```
  ├─ _recover_to_video_page("滑动下一个视频前", max_back=4)
  ├─ BehaviorRandomizer.maybe_fast_scroll()  ← 测试期返回 False (关闭)
  │   └─ if not False → 执行正常滑动
  │
  └─ SwipeNextVideoAction.execute()
      (dy/actions/navigation.py)
      ├─ 贝塞尔曲线向上滑动: (w/2, h*0.75) → (w/2, h*0.25)
      │   └─ human_swipe_curve → 坐标 ±10px 抖动, duration=0.42s/0.30s
      └─ human_sleep('normal') → 固定 1.4s
```

### 6.2 行为模拟（全部关闭）
```
  ├─ BehaviorRandomizer.maybe_rewind()          ← 返回 False
  ├─ BehaviorRandomizer.maybe_browse_home_feed() ← 返回 False
  └─ BehaviorRandomizer.maybe_pause_and_think()  ← 返回 False
```

### 6.3 视频停留
```
  网络检查 → _check_network()
  
  停留时间:
    min_stay = max(5, config.min_video_stay)
    max_stay = max(min_stay + 3, config.max_video_stay)
    stay_time = (min_stay + max_stay) / 2.0    ← 测试期取中点
  
  _interruptible_sleep(stay_time)
    └─ 每 0.5s 检查一次 _check_stop()(暂停/停止)
  
  anti.record_action('video')  ← 记录本设备视频计数
```

---

## 策略方法汇总

### 页面状态识别 `_detect_page_state()`
识别 8 种抖音页面状态，通过 UI XML dump 特征匹配：

| 状态 | 检测特征 |
|------|---------|
| `context_menu` | "不感兴趣","倍速","清屏播放","识别图片" |
| `share_panel` | "复制链接","分享链接", share_panel_container |
| `comment_panel` | comment_list_container, "暂时没有更多了" |
| `input_or_chat` | EditText focused=true |
| `profile_sheet` | "分享名片","发私信","设置备注","取消关注" |
| `video_page` | 分享按钮 + 评论按钮 + 底部导航栏(首页/消息/我) + 视频容器 → score ≥3 |
| `profile_page` | "粉丝","获赞","作品" |
| `home_or_search` | "首页","搜索" |

### 状态恢复 `_recover_to_video_page()`
- 最多重试 5 次 (max_back可调)
- 每次 back 后重新检测状态
- context_menu 优先用 _dismiss_video_context_menu_if_present()
- 每次重试 0.8s 间隔

### 每日限额管理 `DailyLimitManager`
- 5 类限额: like(80), comment(50), follow(20), pm(15), video(100)
- 内存计数 + 线程锁保护
- can_do(): 检查 + record_action(): 记录

### 三级评论发送验证链
```
点击发送后:
  ① _input_is_cleared()  ← 输入框消失或为空（最强信号）
  ② _message_visible()   ← 评论文本在页面可见（次强）
  ③ not _input_still_contains() ← 文本不在输入框（兜底）
三次重试后 press("enter") 兜底
```

### 阻断链
```
_step_like:          on_failure="continue"    → 不影响
_step_acquisition:   on_failure="block_rest"  → 失败阻断 video_comment + comment_lead
_step_video_comment: on_failure="continue"    → 不影响
_step_comment_lead:  on_failure="block_rest"  → 失败阻断后续 (最后一步，无影响)
```

### 测试期确定性行为
- 所有概率决策 → 100% 执行 (long_watch → 0%)
- 所有时间等待 → 固定中点值
- 话术选择 → 固定取第一条
- 行为模拟 → 全部关闭
- 空间随机 (坐标抖动/贝塞尔曲线) → 保留
