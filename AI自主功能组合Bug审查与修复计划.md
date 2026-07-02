# AI 自主功能 4 选项组合 Bug 审查与修复计划书

> 审查日期：2026-06-29
> 审查范围：AI 自主功能 4 选项的 15 种排列组合（C(4,1)+C(4,2)+C(4,3)+C(4,4) = 4+6+4+1 = 15）
> 模式：仅审查代码，未执行实机测试，未修改任何代码

---

## 一、4 选项定义与执行顺序

### 1.1 4 个选项（对应前端 checkbox）

| 编号 | 配置键 | 业务含义 | 代码位置 |
|------|--------|----------|----------|
| **L** | `enable_like` | 点赞（B.1） | task_runner.py:657 |
| **F** | `enable_author_follow` | 进入作者主页→粉丝数判断→关注→私信（B.2，含子选项 `enable_private_message`） | task_runner.py:686 |
| **V** | `enable_video_comment` | AI 生成评论并发布（B.3） | task_runner.py:736 |
| **C** | `enable_comment_lead` | 打开评论区→AI 识别意向评论→楼中楼回复（B.4，含子选项 `enable_comment_lead_pm` 触发 B.5） | task_runner.py:786 |

### 1.2 执行顺序（固定，不可配置）

无论开启了哪些选项，执行顺序始终为 **L → F → V → C**，由 task_runner.py:657-827 的顺序 if 块决定。被关闭的选项跳过，但不影响后续选项的执行位置。

### 1.3 15 种组合清单

**4 个单选（用户已测试正常）：**
1. L | 2. F | 3. V | 4. C

**6 个双选：**
5. L+F | 6. L+V | 7. L+C | 8. F+V | 9. F+C | 10. V+C

**4 个三选：**
11. L+F+V | 12. L+F+C | 13. L+V+C | 14. F+V+C

**1 个全选：**
15. L+F+V+C

---

## 二、全链路状态转移分析

### 2.1 每个选项的页面状态变化

| 选项 | 入页状态 | 执行中状态变化 | 出页状态（预期） | 恢复机制 |
|------|----------|----------------|------------------|----------|
| L | video_page | 停留 video_page | video_page | `_run_feature_safely` 前后各一次 `_recover_to_video_page` |
| F | video_page | video_page → **profile_page** →（可选）**chat_page** → video_page | video_page | B.2 内部 `_return_to_video_page`（弱）+ `_run_feature_safely` 外部 `_recover_to_video_page`（强） |
| V | video_page | video_page → **input_or_chat**（打开评论输入框）→ video_page | video_page | `_run_feature_safely` + `_close_comment_input_if_open` |
| C | video_page | video_page → **comment_panel** →（可选 B.5）**profile_page** → **chat_page** → comment_panel → video_page | video_page | `_run_comment_lead_safely` 内部 `_close_comment_section` + 外部 `_recover_to_video_page` |

### 2.2 选项间的状态传递链

```
L 完成 → video_page（稳定）
    ↓
F 完成 → video_page（依赖 B.2 内部返回 + 外部恢复）
    ↓
V 完成 → video_page（依赖 _close_comment_input_if_open 关闭键盘）
    ↓
C 完成 → video_page（依赖 _close_comment_section 关闭评论区 + 外部恢复）
```

**关键发现：每个选项出页时都应回到 video_page，但"回到 video_page"的判定标准不一致：**

| 判定方法 | 来源 | 严格度 | 问题 |
|----------|------|--------|------|
| `_is_video_page_ready()` (B.2 内部) | interaction.py:615 | **弱**：仅检查评论+分享按钮存在 | 个人主页也有分享按钮，可能误判 |
| `_is_video_page_ready()` (task_runner) | task_runner.py:181 | **强**：4 特征评分 ≥3 | 较可靠 |
| `_detect_page_state()` | task_runner.py:213 | **中**：8 种状态特征匹配 | input_or_chat 检测依赖 focused=true |

---

## 三、Bug 根因分析（按严重度排序）

### P0 — 致命级（导致错误页面导航/功能完全失败）

#### BUG-01: B.2 `_is_video_page_ready()` 判定过弱，在作者主页可能误判为视频页

- **文件**: [interaction.py](file:///d:/CodingTest/111test/111/dy/actions/interaction.py#L615-L618)
- **代码**:
  ```python
  def _is_video_page_ready(self):
      comment_nodes = self.d.xpath(L.COMMENT_BTN_DYNAMIC).all()
      share_nodes = self.d.xpath(L.SHARE_BTN_DYNAMIC).all()
      return len(comment_nodes) > 0 and len(share_nodes) > 0
  ```
- **问题**: 抖音作者主页也包含分享按钮（SHARE_BTN_DYNAMIC 可能匹配到），且新版主页 UI 可能存在评论入口。仅凭"分享按钮存在"就判定为视频页，会在作者主页上返回 True，导致 `_return_to_video_page()` 提前停止返回，停留在作者主页。
- **影响组合**: 所有含 F 的组合 → L+F, F+V, F+C, L+F+V, L+F+C, F+V+C, L+F+V+C（共 7 种）
- **后果**: F 执行后停留在作者主页 → V 找不到视频页底部评论输入框 → V 失败 → C 在错误页面打开评论区 → 全链路雪崩

#### BUG-02: B.5 楼中楼私信后返回路径断裂

- **文件**: [task_runner.py](file:///d:/CodingTest/111test/111/dy/task_runner.py#L405-L416) + [commenting.py](file:///d:/CodingTest/111test/111/dy/actions/commenting.py#L523-L536)
- **问题**: B.5 (CommentLeadPmAction) 执行后页面处于**评论者私信聊天页**，但 `_run_comment_lead_safely` 的关闭逻辑调用的是 `action_instance._close_comment_section()`，该方法执行 `press("back")` 最多 3 次并检查评论区面板是否关闭。从聊天页 press back 的路径是：chat → profile → (comment_panel 或 video_page)，与 `_close_comment_section` 期望的 comment_panel → video_page 路径不匹配。
- **影响组合**: C（当 `enable_comment_lead_pm=True` 时）→ C, L+C, F+C, V+C, L+F+C, L+V+C, F+V+C, L+F+V+C
- **后果**: B.5 后无法可靠返回视频页，依赖最后的 `_recover_to_video_page` 兜底，但可能已多按了 back 键退出视频流

#### BUG-03: `_detect_page_state` 的 `input_or_chat` 检测漏判失焦键盘

- **文件**: [task_runner.py](file:///d:/CodingTest/111test/111/dy/task_runner.py#L228)
- **代码**:
  ```python
  if re.search(r'class="android\.widget\.EditText"[^>]*focused="true"', ui_xml):
      return "input_or_chat"
  ```
- **问题**: 仅检测 `focused="true"` 的 EditText。如果键盘已弹出但 EditText 失焦（如 IME 切换、点击空白区域），状态会被误判为 `video_page`，导致 `_recover_to_video_page` 认为已在视频页而跳过关闭键盘的操作。
- **影响组合**: 所有含 V 的组合 → L+V, F+V, V+C, L+F+V, L+V+C, F+V+C, L+F+V+C（共 7 种）
- **后果**: V 执行后键盘残留 → C 打开评论区时键盘遮挡评论区入口 → C 失败

### P1 — 高危级（导致功能静默失败或配额越界）

#### BUG-04: B.4 未检查 `can_do('comment')` 配额

- **文件**: [task_runner.py](file:///d:/CodingTest/111test/111/dy/task_runner.py#L786-L788)
- **代码**:
  ```python
  elif self._interaction_enabled("enable_comment_lead"):
      self._check_stop()
      if self._probability_allows('comment_lead'):  # ← 仅检查概率，未检查配额
          ...
  ```
- **问题**: B.3 (V) 在 line 738 检查了 `self.anti.can_do('comment')`，但 B.4 (C) 只检查概率不检查配额。B.3 和 B.4 共享 `comment` 配额（日 50 次），当 B.3 耗尽配额后 B.4 仍会执行，导致超限。
- **影响组合**: 所有含 C 的组合（当 V 也在同一视频执行时尤甚）→ V+C, L+V+C, F+V+C, L+F+V+C
- **后果**: 评论配额超限，可能触发抖音风控
- **注**: 当前配置 `daily_comment_limit=999999`（已关闭限制），但代码缺陷存在

#### BUG-05: B.4 `lead_comment_node` 节点引用在 B.5 使用时可能已失效

- **文件**: [commenting.py](file:///d:/CodingTest/111test/111/dy/actions/commenting.py#L598-L625)
- **问题**: B.4 的 `ProcessCommentSectionAction` 在 `_interact_with_potential_customer` 中发送楼中楼回复后，调用 `_close_comment_input_if_open`（press back 关闭键盘）。此时评论区 UI 可能已刷新（回复内容上浮、布局重绘），`lead_comment_node` 的 bounds 引用已失效。B.5 用此失效节点反查头像 (`comment_node.parent`) 会失败，兜底全局查找 avatar 可能命中错误用户的头像。
- **影响组合**: C（当 `enable_comment_lead_pm=True`）→ 所有含 C 的组合
- **后果**: B.5 私信发错人，或因找不到头像而静默失败

#### BUG-06: B.2 粉丝数提取失败导致关注+私信全部静默跳过

- **文件**: [interaction.py](file:///d:/CodingTest/111test/111/dy/actions/interaction.py#L122-L129)
- **代码**:
  ```python
  if min_followers > 0:
      if follower_count is None:
          logger.info(f"作者粉丝数未知，已设置关注阈值，跳过关注")
          should_follow = False
      elif follower_count < min_followers:
          should_follow = False
  ```
- **问题**: 当 `min_followers_threshold > 0`（当前配置 0.01 万 = 100 粉丝）且粉丝数提取失败（UI 变更、页面加载慢等常见情况），`follower_count is None` → `should_follow = False` → 关注和私信都被跳过。B.2 返回 `{"followed": False, "returned_to_video": True}`，`stable=True`，后续步骤继续执行，但用户以为 B.2 执行了实际没有。
- **影响组合**: 所有含 F 的组合（共 7 种）
- **后果**: F 频繁静默失效，用户无法察觉

#### BUG-07: B.2 私信后返回路径紧绑（仅 2 次 back）

- **文件**: [interaction.py](file:///d:/CodingTest/111test/111/dy/actions/interaction.py#L620-L635)
- **问题**: 私信发送后页面在聊天页，`_return_to_video_page` 最多 press back 2 次。路径：chat →(back)→ profile →(back)→ video_page。如果中间出现弹窗（如关注成功提示、私信发送动画延迟），2 次 back 不够，会停留在 profile_page。
- **影响组合**: F（当 `enable_private_message=True`）→ 所有含 F 的组合
- **后果**: F 后停留在作者主页，后续步骤在错误页面执行

### P2 — 中危级（时序/状态残留导致偶发失败）

#### BUG-08: V → C 之间无间隔延迟

- **文件**: [task_runner.py](file:///d:/CodingTest/111test/111/dy/task_runner.py#L777-L786)
- **问题**: B.3 块结束（line 777）后直接进入 B.4 块（line 779），中间无 `_interruptible_sleep`。对比 B.1 后有 `random.uniform(0.8, 2.0)`，B.2 后有 `random.uniform(1.0, 2.5)`，B.3 后无任何延迟。虽然 B.4 的 `_run_comment_lead_safely` 内部有 `_recover_to_video_page` 前置恢复，但 UI 可能未完全 settle。
- **影响组合**: V+C, L+V+C, F+V+C, L+F+V+C
- **后果**: B.4 打开评论区时 UI 未就绪，偶发打开失败

#### BUG-09: B.3 `_close_comment_input_if_open` 关闭输入框逻辑不充分

- **文件**: [commenting.py](file:///d:/CodingTest/111test/111/dy/actions/commenting.py#L170-L183)
- **问题**: 该方法仅当 `_find_bottom_edit_text` 找到 EditText 且文本匹配时才 press back。如果评论已发送（EditText 消失），不执行任何操作。但如果 EditText 仍存在但文本已清空（发送成功但输入框未收起），`text and current_text and text not in current_text` 为 False（text 非空但 current_text 为空），会执行 press back。press back 在视频页可能关闭评论面板而非仅关键盘。
- **影响组合**: V+C, L+V+C, F+V+C, L+F+V+C
- **后果**: V 执行后意外关闭了评论面板（如果有的话），或残留键盘状态

#### BUG-10: B.4 `OpenCommentSectionAction` 在 B.3 残留状态下可能失效

- **文件**: [commenting.py](file:///d:/CodingTest/111test/111/dy/actions/commenting.py#L250-L287)
- **问题**: 如果 B.3 留下了未关闭的键盘（BUG-03 场景），B.4 的 `OpenCommentSectionAction.execute()` 点击评论区按钮时，第一次点击可能只是关闭键盘而非打开评论区。`opened` 返回 True（点击成功），但 `_detect_page_state` 不是 `comment_panel`，触发 `_run_comment_lead_safely` 的 "评论区未可靠打开" 分支。
- **影响组合**: V+C, L+V+C, F+V+C, L+F+V+C
- **后果**: C 静默跳过

### P3 — 低危级（设计改进建议）

#### BUG-11: `skip_remaining_features` 级联阻断过于激进

- **文件**: [task_runner.py](file:///d:/CodingTest/111test/111/dy/task_runner.py#L669-L671, L719-L721, L761-L763)
- **问题**: 任一步骤 `not stable` 即设 `skip_remaining_features = True`，后续所有步骤跳过。虽然这是为了页面安全，但 B.1 点赞失败（如已点赞过的视频）不应阻断 B.2/B.3/B.4。
- **影响组合**: 所有多步骤组合
- **建议**: 区分"页面不稳定"和"功能执行失败"，仅前者触发级联跳过

#### BUG-12: 文档描述的 PipelineExecutor 与实际代码不符

- **文件**: `AI员工全功能链路详解.md` 描述了 `dy/pipeline.py:63` 的 PipelineExecutor，但实际不存在该文件。4 个步骤的执行逻辑直接内联在 task_runner.py 的 `_video_loop` 中。
- **影响**: 开发者按文档排查时找不到对应代码

#### BUG-13: B.3 与 B.4 共享 comment 配额但无协调

- **文件**: task_runner.py:738 (B.3 检查配额) vs task_runner.py:786 (B.4 不检查配额)
- **问题**: 两个步骤都调用 `db.update_interaction(video_id, "comment")` 消耗同一配额，但只有 B.3 做前置检查。当配额剩余 1 时，B.3 消耗后 B.4 仍执行。

---

## 四、15 种组合 Bug 影响矩阵

| # | 组合 | 涉及 Bug | 风险等级 | 预期表现 |
|---|------|----------|----------|----------|
| 1 | L | — | ✅ 正常 | 用户已验证 |
| 2 | F | BUG-06, BUG-07 | ⚠️ 偶发 | 粉丝提取失败时静默跳过；PM 后返回偶发卡在主页 |
| 3 | V | — | ✅ 正常 | 用户已验证 |
| 4 | C | BUG-02（B.5启用时）, BUG-04, BUG-05 | ⚠️ 偶发 | B.5 启用时返回路径断裂；配额不检查 |
| 5 | L+F | BUG-01, BUG-06, BUG-07 | 🔴 高 | F 后可能停在作者主页，但无后续步骤，影响下个视频 |
| 6 | L+V | BUG-03 | ⚠️ 偶发 | V 后键盘偶发残留，无后续步骤受影响 |
| 7 | L+C | BUG-04 | ⚠️ 低 | 配额不检查（当前配置已关闭限制） |
| 8 | F+V | BUG-01, BUG-03, BUG-06, BUG-07, BUG-09 | 🔴 高 | F 返回不稳 → V 在错误页面找输入框 → V 失败 |
| 9 | F+C | BUG-01, BUG-02, BUG-04, BUG-05, BUG-06, BUG-07 | 🔴 高 | F 返回不稳 → C 在错误页面打开评论区 |
| 10 | V+C | BUG-02, BUG-03, BUG-04, BUG-08, BUG-09, BUG-10 | 🔴 高 | V 后键盘残留/无延迟 → C 打开评论区失败 |
| 11 | L+F+V | BUG-01, BUG-03, BUG-06, BUG-07, BUG-09 | 🔴 高 | F+V 的所有问题叠加 |
| 12 | L+F+C | BUG-01, BUG-02, BUG-04, BUG-05, BUG-06, BUG-07 | 🔴 高 | F+C 的所有问题叠加 |
| 13 | L+V+C | BUG-02, BUG-03, BUG-04, BUG-08, BUG-09, BUG-10 | 🔴 高 | V+C 的所有问题叠加 |
| 14 | F+V+C | BUG-01~BUG-10（除 BUG-11 外全部） | 🔴 极高 | 三步链路最脆弱的组合，F 返回不稳 + V 键盘残留 + C 打开失败 |
| 15 | L+F+V+C | BUG-01~BUG-10 | 🔴 极高 | 全链路问题叠加 |

---

## 五、修复计划（按优先级分阶段）

### 阶段一：P0 致命级修复（建议立即处理）

#### FIX-01: 统一视频页判定标准（修复 BUG-01）

**目标**: B.2 的 `_is_video_page_ready()` 与 task_runner 的判定对齐

**修改文件**: `dy/actions/interaction.py:615-618`

**方案**: 将 B.2 的 `_is_video_page_ready()` 替换为与 task_runner.py:181 一致的特征评分机制（4 特征 ≥3），或直接复用 task_runner 的方法。同时增加"底部导航栏"特征检查（首页/消息/我），因为作者主页不含底部导航栏。

**验收标准**: 在作者主页调用 `_is_video_page_ready()` 必须返回 False

#### FIX-02: 修复 B.5 返回路径（修复 BUG-02）

**目标**: B.5 私信后可靠返回视频页

**修改文件**: `dy/task_runner.py:405-416`

**方案**: 在 `_run_comment_lead_safely` 中，B.5 执行后不调用 `_close_comment_section`（因此时不在评论区），而是直接调用 `_recover_to_video_page("B.5私信后-恢复")`，由状态机统一处理从 chat → profile → comment_panel → video_page 的多层返回。

**验收标准**: B.5 执行后（无论成功失败）最终页面状态为 video_page

#### FIX-03: 增强 `input_or_chat` 状态检测（修复 BUG-03）

**目标**: 检测失焦的键盘/输入框

**修改文件**: `dy/task_runner.py:228`

**方案**: 将 `focused="true"` 条件放宽为 EditText 可见即可，或增加辅助检测：检测 IME 是否可见（`dumpsys input_method | grep mInputShown`）。

```python
# 原条件：仅 focused=true
if re.search(r'class="android\.widget\.EditText"[^>]*focused="true"', ui_xml):
    return "input_or_chat"
# 建议改为：focused=true 或 存在可见 EditText
if (re.search(r'class="android\.widget\.EditText"[^>]*focused="true"', ui_xml)
    or re.search(r'class="android\.widget\.EditText"[^>]*visible="true"', ui_xml)):
    return "input_or_chat"
```

**验收标准**: 键盘已弹出但 EditText 失焦时，状态正确识别为 `input_or_chat`

### 阶段二：P1 高危级修复

#### FIX-04: B.4 增加 comment 配额前置检查（修复 BUG-04）

**修改文件**: `dy/task_runner.py:786-788`

**方案**: 在 `self._probability_allows('comment_lead')` 前增加 `self.anti.can_do('comment')` 检查。

```python
if self.anti.can_do('comment') and self._probability_allows('comment_lead'):
```

**验收标准**: comment 配额耗尽时 B.4 跳过并记录 `action_event: "跳过截流(comment限额)"`

#### FIX-05: B.5 使用评论文本反查节点而非保留旧引用（修复 BUG-05）

**修改文件**: `dy/actions/commenting.py:598-625`

**方案**: B.4 保存 `lead_comment_text`（已实现），B.5 不依赖 `lead_comment_node` 的 parent 遍历，改为在评论区重新通过文本定位评论节点：`self.d.xpath(f'//*[@text="{lead_comment_text}"]')`，再从新节点反查头像。

**验收标准**: B.5 在 B.4 回复后 UI 已刷新的情况下仍能正确定位评论者头像

#### FIX-06: B.2 粉丝数提取失败时降级执行（修复 BUG-06）

**修改文件**: `dy/actions/interaction.py:122-129`

**方案**: 当 `follower_count is None` 时，不直接跳过，而是按配置决定降级策略：
- `min_followers_threshold == 0`：照常关注（不设阈值）
- `min_followers_threshold > 0`：记录 warning，按"未知粉丝数"处理（可选：跳过或保守关注），并在 DB 记录 `follower_count="unknown"`

**验收标准**: 粉丝数提取失败时行为符合预期，不再静默跳过

#### FIX-07: B.2 返回视频页增加重试次数（修复 BUG-07）

**修改文件**: `dy/actions/interaction.py:620-635`

**方案**: 将 `range(2)` 改为 `range(4)`，与 task_runner 的 `_recover_to_video_page` 默认 `max_back=5` 接近。或在 B.2 内部直接调用更严格的页面检测。

**验收标准**: PM 发送后从聊天页可靠返回视频页（4 次 back 足够覆盖 chat→profile→video 路径）

### 阶段三：P2 中危级修复

#### FIX-08: V → C 之间增加间隔延迟（修复 BUG-08）

**修改文件**: `dy/task_runner.py:777` 之后

**方案**: 在 B.3 块结束后、B.4 块开始前，增加 `self._interruptible_sleep(random.uniform(0.8, 2.0))`，与 B.1/B.2 后的延迟保持一致。

#### FIX-09: 改进 `_close_comment_input_if_open` 逻辑（修复 BUG-09）

**修改文件**: `dy/actions/commenting.py:170-183`

**方案**: 增加键盘状态检测，仅在确认键盘弹出时才 press back；或改为先检测评论区面板是否打开，若面板已打开则不 press back（避免关闭面板）。

#### FIX-10: B.4 打开评论区前强制关闭键盘（修复 BUG-10）

**修改文件**: `dy/task_runner.py` 或 `dy/actions/commenting.py:250`

**方案**: 在 `OpenCommentSectionAction.execute()` 开头增加键盘关闭逻辑：检测 IME 是否可见，若可见则先 press back 关闭键盘，等待 0.5s 后再点击评论区按钮。

### 阶段四：P3 低危级改进（可延后）

#### FIX-11: 细化 `skip_remaining_features` 级联策略（修复 BUG-11）

**方案**: 区分"页面不稳定"(stable=False) 和"功能执行失败"(result=False)，仅前者触发级联跳过。

#### FIX-12: 更新文档或抽取真实 PipelineExecutor（修复 BUG-12）

**方案**: 要么更新 `AI员工全功能链路详解.md` 使其与 task_runner.py 的实际实现一致，要么将 `_video_loop` 中的管道逻辑抽取为独立的 `PipelineExecutor` 类。

#### FIX-13: B.3/B.4 comment 配额协调（修复 BUG-13）

**方案**: 在 B.4 前检查 B.3 是否已消耗本视频的 comment 配额，若已消耗则 B.4 仅扫描不发送（或使用独立配额 `comment_lead`）。

---

## 六、修复优先级建议

| 优先级 | 修复项 | 影响组合数 | 预计复杂度 |
|--------|--------|-----------|-----------|
| 🔴 立即 | FIX-01 (BUG-01) | 7 | 低 |
| 🔴 立即 | FIX-02 (BUG-02) | 8 | 中 |
| 🔴 立即 | FIX-03 (BUG-03) | 7 | 低 |
| 🟡 尽快 | FIX-04 (BUG-04) | 4 | 低 |
| 🟡 尽快 | FIX-07 (BUG-07) | 7 | 低 |
| 🟡 尽快 | FIX-08 (BUG-08) | 4 | 低 |
| 🟢 排期 | FIX-05 (BUG-05) | 8 | 中 |
| 🟢 排期 | FIX-06 (BUG-06) | 7 | 中 |
| 🟢 排期 | FIX-09 (BUG-09) | 4 | 中 |
| 🟢 排期 | FIX-10 (BUG-10) | 4 | 低 |
| ⚪ 延后 | FIX-11~13 | 全部 | 中 |

---

## 七、验证方案建议

修复完成后，建议按以下顺序验证：

1. **单选回归**（4 种）：确认修复未破坏已正常工作的单选功能
2. **高危双选验证**（3 种）：F+V、F+C、V+C — 这 3 种覆盖了所有 P0 Bug
3. **三选验证**（2 种）：F+V+C、L+F+V+C — 验证全链路状态转移
4. **B.5 子选项验证**：在 C 组合下开启 `enable_comment_lead_pm`，验证 B.5 返回路径

每个组合建议至少跑 3 个视频 × 2 个关键词，确认无页面卡死、无静默跳过、无错误页面操作。

---

## 附录：关键代码位置索引

| 功能 | 文件 | 行号 |
|------|------|------|
| 视频循环主入口 | task_runner.py | 561 |
| B.1 点赞 | task_runner.py | 657-678 |
| B.2 关注+私信 | task_runner.py | 680-728 |
| B.3 AI视频评论 | task_runner.py | 730-777 |
| B.4 评论区截流 | task_runner.py | 779-827 |
| B.5 楼中楼私信 | task_runner.py | 331-419 |
| `_run_feature_safely` | task_runner.py | 302-329 |
| `_run_comment_lead_safely` | task_runner.py | 331-419 |
| `_recover_to_video_page` | task_runner.py | 273-300 |
| `_detect_page_state` | task_runner.py | 213-271 |
| B.2 弱判定 `_is_video_page_ready` | interaction.py | 615-618 |
| B.2 返回逻辑 `_return_to_video_page` | interaction.py | 620-635 |
| B.2 粉丝数提取 | interaction.py | 502-577 |
| B.3 评论发送 | commenting.py | 214-248 |
| B.4 打开评论区 | commenting.py | 250-287 |
| B.4 处理评论区 | commenting.py | 289-361 |
| B.5 楼中楼私信 | commenting.py | 539-715 |
| 关闭评论输入 | commenting.py | 170-183 |
| 配额检查 `can_do` | anti_detection.py | 317-330 |
