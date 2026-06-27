"""
声明式动作管道 — 每个视频上的互动步骤由数据驱动编排。

设计原则：
- 每个 PipelineStep 描述一个独立功能单元
- PipelineExecutor 统一提供安全边界（_run_feature_safely）
- self_managed=True 的步骤自己管理页面恢复，Executor 跳过外层包裹
- 不改任何 Action 类，不改防风控引擎
- 加新模式 = 写一个 Step 函数 + 注册到 PIPELINE_STEPS
"""

import random
import logging
from dataclasses import dataclass, field
from typing import List, Callable, Any, Tuple, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineStep:
    """管道中的一个独立功能单元。"""

    id: str
    label: str

    # 开关检查：对应 config.interaction 中的字段名
    enabled_key: str

    # 执行体：(flow, context) -> (stable: bool, result: Any)
    # 不调用 _run_feature_safely，由 PipelineExecutor 统一包装
    execute: Callable[..., Tuple[bool, Any]]

    # 限额：执行前逐个检查 can_do()，执行后逐个 record_action()
    quota_keys: List[str] = field(default_factory=list)

    # 概率：空字符串 = 不检查概率，非空按概率决策
    probability_key: str = ""

    # 失败策略
    on_failure: str = "continue"          # "continue" | "block_rest"
    block_message: str = ""

    # True = 步骤内部自行处理安全边界（打开→操作→关闭→恢复），
    # PipelineExecutor 不再用 _run_feature_safely 包裹，避免双重恢复
    self_managed: bool = False

    # Phase2: 前端的元信息
    description: str = ""                  # 前端显示的描述
    category: str = ""                     # "fixed" | "engagement" | "acquisition" | "content"
    default_enabled: bool = True           # 新用户默认是否开启


class PipelineExecutor:
    """按顺序执行 PipelineStep 列表。
    
    - 普通步骤：前后由 flow._run_feature_safely 兜底
    - self_managed 步骤：步骤内已自行管理状态恢复，直接执行，不额外包裹
    """

    def __init__(self, flow):
        self.flow = flow

    def run(self, steps: List[PipelineStep], context: dict) -> dict:
        """
        -> {"blocked": bool, "executed": [str, ...]}
        """
        executed = []
        blocked = False

        # Phase2: 读取按步骤粒度的开关配置
        per_step_config = context.get("pipeline_steps", {})

        # 预计算：本管道有多少个已启用的步骤（用于步骤间间隔）
        remaining_step_ids = []
        for step in steps:
            sid_enabled = per_step_config.get(step.id)
            if sid_enabled is None:
                sid_enabled = self.flow._interaction_enabled(step.enabled_key)
            if sid_enabled:
                remaining_step_ids.append(step.id)

        for step in steps:
            if blocked:
                logger.info(f"管道已阻断，跳过: {step.label}")
                continue

            # 开关：优先检查 per-step config，其次 mode-level config
            enabled = per_step_config.get(step.id)
            if enabled is None:
                enabled = self.flow._interaction_enabled(step.enabled_key)
            if not enabled:
                continue

            # 限额（任一不足就跳过本步）
            quota_blocked = False
            for q in step.quota_keys:
                if not self.flow.anti.can_do(q):
                    logger.info(f"跳过 {step.label}: {q} 限额已达")
                    quota_blocked = True
                    break
            if quota_blocked:
                continue

            # 概率
            if step.probability_key and not self.flow._should_interact(step.probability_key):
                continue

            # 执行（通知前端当前步骤名称）
            self.flow._report(current_action=f"执行: {step.label}")

            if step.self_managed:
                # self_managed 步骤自己处理页面状态恢复（如 _step_comment_lead 内
                # 调用 _run_comment_lead_safely 已完整管理打开→处理→关闭→恢复全流程）
                stable, result = step.execute(self.flow, context)
            else:
                stable, result = self.flow._run_feature_safely(
                    step.label,
                    lambda s=step: s.execute(self.flow, context),
                )

            # 记录限额 — 仅在实际动作执行成功时记录
            # result 可能是 bool 或 (bool, bool) 元组
            # 对于 _step_video_comment: result = posted (bool)
            # 对于 _step_comment_lead: result = comment_made (bool 或元组第二项)
            should_record = self._should_record_quota(result, step)
            if should_record and step.quota_keys:
                for q in step.quota_keys:
                    self.flow.anti.record_action(q)

            executed.append(step.id)

            # 阻断
            if not stable and step.on_failure == "block_rest":
                blocked = True
                if step.block_message:
                    logger.warning(step.block_message)

            # 步骤间随机间隔 — 仅当还有后续步骤时等待
            if step.id in remaining_step_ids[:-1]:
                self.flow._interruptible_sleep(random.uniform(1.0, 2.5))

        return {"blocked": blocked, "executed": executed}

    @staticmethod
    def _should_record_quota(result, step):
        """判断是否应记录配额。仅在实际动作执行成功时返回 True。
        
        - result 为 bool: result 本身即执行成功标记
        - result 为 (bool, bool) 元组: 第二项为实际动作成功标记
          （如 _step_comment_lead 返回 (recovered, comment_made)）
        - result 为 dict: 不视为有效结果，不记录
        - result 为 None/False/0/空字符串: 不记录
        """
        if isinstance(result, bool):
            return result
        if isinstance(result, (tuple, list)) and len(result) == 2:
            # (recovered, comment_made) — 取第二项判断实际动作是否成功
            return bool(result[1])
        return False


# ============================================================
# 步骤函数 —— 每个对应一个独立功能
# ============================================================

def _step_like(flow, ctx):
    """点赞 — 单次短按心形按钮，不离开视频页。"""
    from .actions.interaction import DoubleClickLikeAction

    liked = flow.runner.run_action(DoubleClickLikeAction)
    if liked:
        flow.db.update_interaction(ctx["video_id"], "like")
        flow._report(executed_action="点赞")
    return True, liked


def _step_acquisition(flow, ctx):
    """模式1-私域获客：进主页→读粉丝→关注→私信→返回视频页。
    
    返回值: (stable: bool, result: Any)
    - stable 仅由 returned_to_video 决定，表示是否可继续执行下一步
    - 旧版返回 True 时 stable 始终为 True（无法区分实际情况）
    """
    from .actions.interaction import FollowAuthorAction

    result = flow.runner.run_action(FollowAuthorAction)
    if isinstance(result, dict):
        if result.get("followed"):
            flow.db.update_interaction(ctx["video_id"], "follow")
            flow._report(executed_action="关注作者")
        if result.get("private_message_sent"):
            flow.db.update_interaction(ctx["video_id"], "private_message")
            flow._report(executed_action="发送私信")
        stable = result.get("returned_to_video", True)
        return stable, result

    # 向后兼容：旧版 FollowAuthorAction 返回非 dict 值
    # 此时无法区分具体执行了哪些操作，保守记录关注
    if result:
        flow.db.update_interaction(ctx["video_id"], "follow")
        flow._report(executed_action="关注作者")
    return True, result


def _step_video_comment(flow, ctx):
    """模式2-A：AI 生成评论 + 发布（视频页快捷输入，不离开页面）。
    
    返回值: (stable: bool, posted: bool)
    - stable: 步骤执行未导致页面偏离（对视频评论始终为 True，因为不离开视频页）
    - posted: 评论是否真正发送成功
    """
    from .actions.commenting import PostCommentAction

    comment_text = flow.reply_agent.generate_reply(
        title=ctx["video_title"],
        keyword=flow.current_keyword or "",
    ) or ""
    if not comment_text:
        logger.info("AI 未生成可用的评论内容，跳过视频评论")
        return True, False

    # 仅在有实际生成文本时才记录到数据库
    flow.db.save_ai_reply(ctx["video_id"], note_title=ctx["video_title"], ai_reply=comment_text)
    if flow.reply_agent.is_enabled():
        logger.info(f"AI 生成回复: {comment_text}")

    posted = flow.runner.run_action(PostCommentAction, comment_text)
    if posted:
        flow.db.update_interaction(ctx["video_id"], "comment")
        flow._report(executed_action="发布视频评论")
        logger.info(f"✅ 视频评论发送成功: {comment_text[:20]}...")
    else:
        logger.warning(f"⚠️ 视频评论发送失败: {comment_text[:20]}...")
    return True, posted


def _step_comment_lead(flow, ctx):
    """模式2-B：评论区截流 — 打开→识别意向→回复→关闭。

    该步骤是 self_managed=True 步骤，内部通过 _run_comment_lead_safely 
    自行管理完整的打开→处理→关闭→恢复流程，PipelineExecutor 不再额外包裹。

    返回值: (recovered: bool, comment_made: bool)
    - recovered: 评论区关闭后是否成功恢复到视频页
    - comment_made: 是否至少成功发送了一条楼中楼回复
    """
    recovered, comment_made = flow._run_comment_lead_safely(
        ctx["video_title"],
        flow.current_keyword or "",
    )
    if comment_made:
        flow.db.update_interaction(ctx["video_id"], "comment")
        flow._report(executed_action="评论区AI截流")
        logger.info("✅ 评论区截流：成功发送楼中楼回复")
    elif recovered:
        logger.info("评论区截流：未找到意向评论，未发送回复")
    else:
        logger.warning("⚠️ 评论区截流：执行后恢复视频页失败")
    return recovered, comment_made


# ============================================================
# 步骤注册表 — 列表顺序即执行顺序
# ============================================================

PIPELINE_STEPS: List[PipelineStep] = [
    PipelineStep(
        id="like",
        label="点赞",
        enabled_key="enable_like",
        execute=_step_like,
        quota_keys=["like"],
        probability_key="like",
        on_failure="continue",
        description="每视频点右侧心形按钮，受概率决策与每日80次限额控制",
        category="fixed",
        default_enabled=True,
    ),
    PipelineStep(
        id="acquisition",
        label="私域获客",
        enabled_key="enable_mode_customer_acquisition",
        execute=_step_acquisition,
        quota_keys=["follow", "private_message"],
        probability_key="follow",
        on_failure="block_rest",
        block_message="模式1异常，跳过后续模式",
        description="进作者主页→读粉丝数→关注→私信，复合动作",
        category="acquisition",
        default_enabled=True,
    ),
    PipelineStep(
        id="video_comment",
        label="AI视频评论",
        enabled_key="enable_mode_content_interaction",
        execute=_step_video_comment,
        quota_keys=["comment"],
        probability_key="comment",
        on_failure="continue",
        description="AI生成评论文本→快捷输入框发布，不离开视频页",
        category="content",
        default_enabled=True,
    ),
    PipelineStep(
        id="comment_lead",
        label="评论区截流",
        enabled_key="enable_mode_content_interaction",
        execute=_step_comment_lead,
        quota_keys=["comment"],
        probability_key="comment_lead",
        on_failure="block_rest",
        block_message="评论区截流异常，跳过后续步骤",
        description="打开评论区→AI扫描识别意向评论→发送楼中楼回复→关闭",
        category="content",
        default_enabled=True,
        self_managed=True,  # 步骤内自行管理打开→操作→关闭→恢复全流程
    ),
]


# Phase2: 前端可用元数据
def get_pipeline_step_info() -> list[dict]:
    """返回步骤元数据列表，供前端渲染复选框。"""
    return [
        {
            "id": s.id,
            "label": s.label,
            "description": s.description,
            "category": s.category,
            "default_enabled": s.default_enabled,
            "quota_keys": s.quota_keys,
            "probability_key": s.probability_key or "",
        }
        for s in PIPELINE_STEPS
    ]
