from pydantic import BaseModel, field_validator
from typing import List

class AppConfig(BaseModel):
    """前端传来的配置表单模型"""
    search_keywords: List[str]
    sort_by: str = "latest"
    max_videos_per_keyword: int = 5
    max_daily_videos: int = 100
    # AI 回复与授权配置
    ai_enabled: bool = True
    ai_base_url: str = "https://lcjx.yun/social-ai-credit-api"
    ai_api_key: str = ""
    ai_model: str = "deepseek-v4-flash"
    ai_temperature: float = 0.7
    ai_max_tokens: int = 120
    ai_persona: str = "a_zhen"   # AI 人格预设：a_zhen(阿珍) | a_qiang(阿强)
    license_key: str = ""
    license_server_url: str = "https://lcjx.yun/social-ai-credit-api"
    # 抖音专属
    comments: List[str] = []
    target_keywords: List[str] = []
    reply_texts: List[str] = []
    min_video_stay: int = 3
    max_video_stay: int = 6
    max_comment_swipes: int = 2
    max_ai_comment_reviews: int = 20
    intent_keywords: List[str] = []
    keyword_override_ai: bool = True   # true 保持旧行为（AI 返回 NO 时仍查自定义关键词）；false 时尊重 AI 判定

    @field_validator("intent_keywords", mode="before")
    @classmethod
    def _coerce_intent_keywords(cls, value):
        """前端其他配置页可能把 GET /config 返回的逗号分隔字符串原样回传，
        这里统一转成 list，避免 Pydantic 校验报 422。"""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [k.strip() for k in value.split(",") if k.strip()]
        if isinstance(value, (list, tuple)):
            return [str(k).strip() for k in value if str(k).strip()]
        return [str(value)]
    enable_like: bool = True
    enable_author_follow: bool = True
    enable_video_comment: bool = True
    enable_comment_lead: bool = True
    enable_comment_lead_pm: bool = False
    min_followers_threshold: float = 0
    enable_private_message: bool = True
    pm_followers_threshold: float = 1
    pm_message_list: List[str] = []
    lead_pm_message_list: List[str] = []
    # 夜间静默时段总开关：开启后 23:00-07:00 启动任务会等待到早晨，关闭后任意时段可直接启动
    night_mode_enabled: bool = True
    # 概率决策（防风控）总开关：关闭时每个视频都执行所有已开启功能；开启后按概率随机执行部分互动
    enable_anti_detection_probability: bool = False
    # 极速测试模式（临时调试用）：开启后跳过 HumanSleep/BehaviorRandomizer/InteractionProbability，最高效率跑通功能链路
    turbo_test_mode: bool = False

class DeviceConnectRequest(BaseModel):
    """连接新设备请求"""
    ip_port: str

class DevicePairRequest(BaseModel):
    """配对新设备请求"""
    ip_port: str
    code: str

class TaskStartRequest(BaseModel):
    """启动任务时的请求参数"""
    devices: List[str]  # 用户勾选的要执行任务的设备序列号列表
    platform: str = "douyin"  # 目标平台

class LicenseVerifyRequest(BaseModel):
    """授权码验证请求"""
    license_key: str = ""
    license_server_url: str = "https://lcjx.yun/social-ai-credit-api"
    device_id: str = ""

class AuthRegisterRequest(BaseModel):
    """账号注册请求"""
    email: str
    password: str

class AuthLoginRequest(BaseModel):
    """账号登录请求"""
    email: str
    password: str

class TaskResponse(BaseModel):
    """通用的响应格式"""
    success: bool
    message: str
    data: dict = {}
