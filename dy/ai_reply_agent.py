import json
import logging
import os
import re
import threading
from typing import Optional

from dotenv import load_dotenv
from social_license import CloudAIClient, LicenseError

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=True)

logger = logging.getLogger(__name__)
LANGCHAIN_IMPORT_ERROR = None

# API 并发限流信号量，最多同时 2000 个 DeepSeek API 调用（使用 deepseek-v4-flash 模型）
_ai_api_semaphore = threading.Semaphore(2000)

# AI 人格预设 prompt 字典
# 应用于 B.3 视频评论生成 与 B.4 楼中楼回复生成；意向判定器（is_intent_comment）不使用人格
_PERSONA_PROMPTS = {
    "a_zhen": {
        "video_comment": (
            "你是抖音评论区里一位'高情商、有阅历、踩过坑'的资深冲浪路人。"
            "你留言的真实目的是暗示自己手里有避坑经验和实操资料，诱导用户产生'求分享'的渴望，"
            "从而吸引他们点击你的头像进入主页，或主动向你发起咨询（引流）。"
            "遵循'四要四不要'："
            "1. 视角转换：从'评判者'降格为'摸爬滚打过来的同行人'，多用'之前交了学费''瞎琢磨很久''亲测走过弯路'，"
            "严禁出现'这个简单''我最懂''我有更好的'；"
            "2. 利益隐藏：将截流包装成客观提醒，通过'顺手留了实操记录''做了个避坑总结'来抛出资料钩子；"
            "3. 情绪管理：用'纯经验分享'稀释营销感，严禁'扣1送''想要私我''看我主页'等营销高危词；"
            "4. 句式习惯与引流暗示：多用'碰巧、感觉、其实、个人觉得'弱化语气，"
            "结尾可用'多留个心眼少走弯路''碰巧留了记录在粉丝群''顺手挂在左下角了基本都能上手'。"
            "硬约束黑名单：禁止'比他好/更便宜/高性价比/平替'；禁止'我都会/太简单/一眼真/假/我最懂'；"
            "禁止'快来拿/扣1送/免费送'；禁止'口1/寇1'等暗号变体。"
            "标点规则：句子中间用空格代替逗号句号，每句话结尾不带任何符号。"
            "长度 15-28 汉字，只输出评论正文，不要解释。"
            "遇到政治和违法国家法律的一律不要评价，评论区绝对禁止涉及到政治和违法国家法律。"
        ),
        "lead_reply": (
            "你是抖音评论区里一位'高情商、有阅历、踩过坑'的资深冲浪路人。"
            "现在要给一条对你表达过意向或求分享的用户评论做楼中楼回复，必须给出明确的抖音流派引流指令，"
            "引导对方去你的主页查看背景墙、粉丝群、橱窗，或者通过私信获取资料，实现商业转化。"
            "遵循'抖音安全引流规则'（使用抖音安全代称）："
            "1. 引导去主页/粉丝群：可使用'顺手放在左下角了''看我背景墙有说明''粉丝群里有分享''点头像自取'；"
            "2. 引导去私信：可使用'有空滴滴我''戳我发你''直接dd我发你''私我发你'；"
            "3. 严禁违规词：严禁出现微信、电话、二维码、链接、价格承诺、夸大宣传，严禁'看我主页'直白表述。"
            "硬约束黑名单：禁止'比他好/更便宜/高性价比/平替'；禁止'我都会/太简单/我最懂'；"
            "禁止'快来拿/扣1送/免费送'；禁止'口1/寇1'等暗号变体。"
            "标点规则：句子中间用开关代替逗号句号，每句话结尾不带任何符号。"
            "长度 15-32 汉字，只输出回复正文，不要解释。"
            "遇到政治和违法国家法律的一律不要评价，评论区绝对禁止涉及到政治和违法国家法律。"
        ),
    },
    "a_qiang": {
        "video_comment": (
            "你是社交媒体评论区一个'性格直爽、自信自负、利益导向'的同行或营销老手。"
            "目标纯粹——展示实力吸引精准客户，或用极低成本抛出利益钩子截流。"
            "信奉'直白才能筛选出真正想要的人'，说话带极强侵略性、竞争感和炫耀色彩。"
            "1. 姿态展示：以老手自居，'这个简单''我都会搞''这个东西我也用过''这个行业我最懂'；"
            "2. 利益对冲：'没有我这个有性价比''我自己创业开了好多家了''同行不要删'；"
            "3. 结果外露：'一天基本十几单''一天搞1k''跟着你做已经报单了'；"
            "4. 营销拦截：'留言想要我发你''整理出来了 1发''邪修方法 寇1 松'。"
            "暗号变体：'扣1'可变异为'口1''寇1''寇1 松'，防止平台关键词过滤。"
            "标点规则：句子中间用空格代替逗号句号，每句话结尾不带任何符号。"
            "长度 10-28 汉字，只输出评论正文，不要解释。"
            "遇到政治和违法国家法律的一律不要评价，评论区绝对禁止涉及到政治和违法国家法律。"
        ),
        "lead_reply": (
            "你是社交媒体评论区一个'性格直爽、自信自负、利益导向'的同行或营销老手。"
            "现在要给一条对你表达过意向的用户评论做楼中楼回复，直接抛出利益钩子截流。"
            "遵循'四原则'：姿态展示、利益对冲、结果外露、营销拦截，语气更直接，可主动要求扣1/口1。"
            "可提到主页但不得出现微信、电话、二维码、链接、价格承诺。"
            "暗号变体：'扣1'可变异为'口1''寇1''寇1 松'。"
            "标点规则：句子中间用空格代替逗号句号，每句话结尾不带任何符号。"
            "长度 10-32 汉字，只输出回复正文，不要解释。"
            "遇到政治和违法国家法律的一律不要评价，评论区绝对禁止涉及到政治和违法国家法律。"
        ),
    },
}

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except ImportError:
    LANGCHAIN_IMPORT_ERROR = "缺少 `langchain-openai` 或其依赖，请在当前虚拟环境执行 `pip install langchain-openai openai`。"
    HumanMessage = None
    SystemMessage = None
    ChatOpenAI = None


class DYReplyAgent:
    """根据标题生成合规的抖音评论回复。"""

    _BANNED_PATTERNS = [
        re.compile(r"(政治|色情|赌博|毒品|辱骂|仇恨|暴力)"),
    ]

    # 本地意向关键词库（按业务场景分组，便于维护）。
    # 这些词在 AI 不可用时作为兜底判定，也可被自定义关键词覆盖。
    # 注意：只保留具有明确购买/咨询/联系意向的短语，避免单字/泛词导致误召回。
    _INTENT_KEYWORDS = [
        # 价格与费用类
        "多少钱", "价格", "怎么卖", "费用", "报价", "造价", "售价", "学费", "标价",
        "团购价", "代理价", "批发价", "体验价", "内部价", "成本价", "成本", "单价", "总价",
        "预算", "打折", "优惠", "多少米", "几米", "怎么米", "求米", "扣米",
        "大米", "小米", "马内", "Money", "米线", "小钱钱", "几刀", "何价", "多钱",
        "碎银", "刀", "软妹币", "RMB", "米数", "便宜点", "有优惠吗", "能省多少",
        "性价比", "划算吗", "贵不贵", "打几折", "底价", "实惠", "降价", "最低价",
        "超值", "开销", "资费", "收多少", "要花多少", "开销大吗", "花销", "怎么收费",
        "怎么付", "支持分期吗", "微信还是支付宝", "可刷卡吗", "定金", "尾款", "怎么充值",
        "订金", "首付", "全款", "付钱", "购买链接", "链接在哪里付", "买单", "付账",
        "定金怎么交", "交钱", "入会费", "打款", "如何支付", "哪个划算", "套票",
        "买一送一吗", "有代金券吗", "立减", "立省", "包年", "包月", "续费", "差价",
        "原价", "现价", "清仓", "秒杀价", "直销", "一手价", "出厂价", "专柜价", "特价",
        "友情价",
        # 购买渠道与链接类
        "求链接", "上链接", "发链接", "给个链接", "有链接吗", "求link", "Link",
        "直达链接", "购买链接", "哪里可以买", "哪里买", "哪里能买", "哪儿买", "怎么下单", "购买渠道", "下单", "传送门",
        "来个链接", "求入口", "入口", "直通车", "求推", "哪家店", "店铺名", "搜什么",
        "店名叫啥", "淘宝搜什么", "小红书搜什么", "旗舰店", "某宝", "某东", "PDD",
        "拼夕夕", "专柜", "代购", "咸鱼", "小店", "橱窗", "小黄车", "黄车", "网店",
        "实体店", "坐标", "地址", "在哪个城市", "具体位置", "店在哪个区",
        "怎么去", "有分店吗", "同城", "实体店在", "导航", "具体地址", "哪个城市", "面交",
        "自提", "哪个省", "哪个地方", "出没地", "商圈", "门店", "有现货吗", "当天发货吗",
        "顺丰吗", "几天到", "包邮吗", "包邮", "快递", "物流", "发哪个快递", "能发货吗",
        "海外能发吗", "转运", "包退换吗", "几天能收到", "什么时候发", "闪送", "闪送不",
        "发货地", "哪里发货", "邮费", "买哪个", "推荐一款", "求安利", "想入手", "吃下安利",
        "怎么安排", "哪个型号", "求种草", "要一个", "来一个", "上车", "冲了", "准备入手",
        "已加入购物车", "加购", "求推荐", "买这个", "推荐下", "想买", "带一个",
        # 私聊与联系方式类
        "私信", "私我", "私聊", "求私", "已经私信", "查收私信", "私信你了",
        "回私信", "私个", "后台见", "看私信", "滴滴", "dd", "小窗", "私下说",
        "私下聊", "悄悄话", "私密", "微信", "微", "vx", "wechat",
        "加我", "留个联系方式", "联系方式", "怎么联系", "电话", "手机号", "手机",
        "号多少", "加个好友", "绿泡泡", "怎么找你", "留个言", "发个号", "有群吗",
        "求进群", "怎么进群", "粉丝群", "交流群", "组织在哪里", "加入组织", "进群",
        "群链接", "社群", "圈子", "组织", "大本营", "车队", "上车群", "羊毛群", "内部群",
        "讨论群", "群号", "扫码", "等回复", "回我一下", "看看主页", "看我", "回复我",
        "在线吗", "能聊聊吗", "有客服吗", "怎么联络", "联络方式", "接头暗号", "留个微",
        "发一下", "发我", "求联系", "怎么对接", "对接", "找谁", "呼叫", "威信", "薇",
        "威", "维新", "we", "v信", "🛰️", "维", "📳", "📞", "💬", "💌", "📪",
        "私小窗", "密我", "戳我", "点我", "主页见", "企鹅", "扣扣",
        # 业务合作与 B2B 咨询类
        "合作", "怎么合作", "招商", "加盟", "代理", "开分店", "拿货", "一手货源",
        "货源", "供货商", "供应商", "接单", "接商单", "商务", "接推广", "怎么加盟",
        "加盟费", "代理政策", "分成", "分成比例", "批发", "大批量", "采购", "量大",
        "团购", "拿货价", "定制", "定做", "批量", "起订量", "MOQ", "厂价", "出厂",
        "搞批发", "做代工", "OEM", "ODM", "贴牌", "加工", "打包", "能定制吗", "能改吗",
        "方案", "项目", "可以做吗", "接不接", "能做不", "定制款", "出设计", "出方案",
        "规划", "包工包料", "清包", "工期", "多久能好", "能设计吗", "包安装吗", "包售后吗",
        "维保", "售后", "怎么收费", "开户", "代运营", "代做", "代笔", "代劳", "包过",
        "培训", "课程", "一对一", "私教", "陪练", "咨询", "顾问", "诊断", "看盘", "测算",
        "排盘", "算下", "有资质吗", "正规吗", "发票", "能开发票吗", "专票", "普票", "合同",
        "签合同吗", "靠谱吗", "案例", "有案例吗", "有没有作品", "看下作品", "看看案例",
        "成功经验", "老字号", "大厂", "官方", "授权书", "正品吗",
        # 痛点提问与高价值决策类
        "有用吗", "有效吗", "成分", "敏感肌", "起痘吗", "会过敏吗", "副作用", "伤皮肤吗",
        "有没有依赖性", "能祛斑吗", "能减肥吗", "管用不", "谁用过", "效果咋样", "真的假的",
        "亲测", "靠谱不", "智商税", "是不是智商税", "效果", "多大", "尺寸", "多重",
        "容量", "续航", "材质", "纯棉吗", "真皮吗", "几G", "配置", "内存", "多高",
        "长宽", "厚度", "承重", "电压", "功率", "静音吗", "吵不吵", "耗电吗", "小孩能吃吗",
        "孕妇可用吗", "老人能用吗", "适合男生吗", "女生可以吗", "适合新手吗", "新手",
        "小白", "零基础", "考研", "上班族", "宝妈", "学生党", "大码", "胖MM", "高个子",
        "小个子", "户外", "家用", "商用", "保质期", "保修", "保修几年", "质保", "坏了怎么办",
        "退换货", "七天无理由", "有运费险吗", "正品保障", "假一赔几", "售后服务", "客服电话",
        "投诉", "翻新", "二手的吗", "全新吗", "拆封过吗", "原装", "行货", "国行", "区别",
        "有什么区别", "怎么选", "选哪个", "哪个性价比高", "推荐买哪个", "买几号色",
        "买哪个版本", "升级版", "对比", "跟XX一样吗", "平替", "XX的平替", "替代品",
        "升级", "哪个好", "纠结", "救命选哪个",
        # 原有本地兜底关键词（保留兼容）
        "哪里有卖", "哪里买", "哪里能买", "哪儿买", "还有吗", "有货吗", "求推荐",
        "求教程", "求链接", "求价格", "求方案", "求带", "求一个", "整一个", "来一份",
        "想要", "想了解", "想咨询", "能详细说下吗", "价格多少", "费用多少", "能推荐吗",
        "有推荐吗", "有教程吗", "教程哪里看", "有方法吗", "方法是什么", "求方法",
        "链接发下", "有链接吗", "求资料", "资料分享下", "有资料吗", "怎么做", "怎么操作",
        "怎么弄", "真的有用吗",
    ]

    # 否定/反讽/排除词库：命中这些模式时，即使触发意向关键词也应判为无意向。
    # 用于降低"智商税""不想买""别推荐""消费者互答"等场景误召回。
    _NEGATIVE_PATTERNS = [
        re.compile(r"(不|没|别|未|勿|拒绝|抵制|反对|不想|不愿|不要).*?(买|卖|入手|推荐|联系|私|加|微信|链接|合作|加盟|代理|进群)", re.IGNORECASE),
        re.compile(r"(智商税|割韭菜|骗人的|假的|坑|踩坑|踩雷|翻车|后悔|上当|被忽悠|别信|不靠谱|死心|水分太大|两块钱|几块|两元| worthless)", re.IGNORECASE),
        re.compile(r"(求放过|别发了|别再|删了吧|举报|拉黑|屏蔽|不感兴趣|绕道|快跑|散了吧)", re.IGNORECASE),
        re.compile(r"(我也|别人|有人|楼主|作者).*?(买过|入过|合作过|加过|联系过|发过|我发你|发你|我看看|看看|想要|要一个)", re.IGNORECASE),
        re.compile(r"(我发你|我发|主页有|已经发了|已发|谁有|谁要|有没有人要).*?(链接|买|私|看)", re.IGNORECASE),
        re.compile(r"(私我|私信).*?(我看看|看看|我看一下|看一下)", re.IGNORECASE),
        re.compile(r"(没效果|没有效果|效果一般|效果不行|效果差|效果不明显|效果不太|效果不咋)", re.IGNORECASE),
        re.compile(r"(听起来|感觉|好像|像是|就是|貌似|估计).*?(贵|坑|假|不靠谱|不划算|没必要|智商税|一般)", re.IGNORECASE),
    ]

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.ai_config = self.config.get("ai_reply", {})
        self.cloud_ai = CloudAIClient(self.ai_config, platform="douyin")
        # 预编译本地意向正则，避免每次调用重复编译；按长度降序、转义特殊字符。
        self._intent_pattern = self._build_intent_pattern(self._INTENT_KEYWORDS)
        self._custom_pattern = None

    @staticmethod
    def _build_intent_pattern(keywords: list) -> Optional[re.Pattern]:
        """将关键词列表构建成预编译正则。

        规则：
        1. 去重并清洗首尾空白；
        2. 使用 re.escape 转义正则特殊字符；
        3. 按长度降序排列，避免短词提前匹配导致长词漏判；
        4. 使用非捕获组合并为单一正则，提升匹配效率。
        """
        unique = list(dict.fromkeys(k.strip() for k in keywords if str(k).strip()))
        if not unique:
            return None
        # 按长度降序：优先匹配更具体的长词
        unique.sort(key=len, reverse=True)
        escaped = [re.escape(k) for k in unique]
        return re.compile("(?:" + "|".join(escaped) + ")")

    def _is_negative_intent(self, text: str) -> bool:
        """检查文本是否命中否定/反讽/排除模式。"""
        if not text:
            return False
        for pattern in self._NEGATIVE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _update_custom_pattern(self, custom_keywords: list):
        """当自定义关键词变化时，惰性重建预编译正则。"""
        unique = list(dict.fromkeys(k.strip() for k in custom_keywords if str(k).strip()))
        if not unique:
            self._custom_pattern = None
            return
        # 以元组 (长度, 文本) 作为缓存键，避免重复编译
        cache_key = tuple(sorted(unique, key=len, reverse=True))
        if getattr(self, "_custom_pattern_key", None) == cache_key:
            return
        self._custom_pattern = self._build_intent_pattern(unique)
        self._custom_pattern_key = cache_key

    def _get_persona_prompt(self, scene: str) -> str:
        """根据 ai_reply.persona 配置返回对应场景的 system prompt。

        Args:
            scene: 'video_comment'（B.3 视频评论）或 'lead_reply'（B.4 楼中楼回复）
        Returns:
            persona 对应的 prompt 字符串；未识别 persona 时回退到 a_zhen
        """
        persona = self.ai_config.get("persona", "a_zhen")
        persona_block = _PERSONA_PROMPTS.get(persona, _PERSONA_PROMPTS["a_zhen"])
        return persona_block[scene]

    def is_enabled(self) -> bool:
        return bool(self.ai_config.get("enabled", True))

    def generate_reply(self, title: str, keyword: str = "") -> Optional[str]:
        clean_title = self._normalize_text(title)
        if not clean_title:
            logger.warning("标题为空，跳过 AI 回复生成。")
            return None

        if not self.is_enabled():
            logger.info("AI 自动回复已关闭，跳过评论环节。")
            return None

        for attempt in range(2):
            candidate = self._call_model(clean_title, keyword, strict_retry=attempt > 0)
            candidate = self._sanitize_reply(candidate)
            if self._is_valid_reply(candidate):
                return candidate

            if candidate:
                logger.warning("AI 生成内容格式不符合要求，准备重试: %s", candidate)

        logger.warning("AI 连续 2 次生成失败，跳过评论环节。")
        return None

    def is_intent_comment(self, comment_text: str, video_title: str = "", keyword: str = "", custom_keywords: list = None) -> bool:
        clean_comment = self._normalize_text(comment_text)
        if not clean_comment:
            logger.info("[intent_stats] result=False reason=EMPTY comment=%s", clean_comment[:30])
            return False
        # 允许 2 字及以上的评论进入判定；2 字评论中常见高意向口语如"求带""私我""dd"等
        if len(clean_comment) < 2:
            logger.info("[intent_stats] result=False reason=TOO_SHORT comment=%s", clean_comment[:30])
            return False

        custom_keywords = custom_keywords or []
        preview = clean_comment[:30]

        # AI 未启用时回退到本地规则判定
        if not self.is_enabled():
            final = self._local_intent_guess(clean_comment, custom_keywords)
            logger.info("[intent_stats] result=%s reason=AI_DISABLED_LOCAL comment=%s", final, preview)
            return final

        # AI 模型判定
        result = self._call_intent_model(clean_comment, video_title, keyword, custom_keywords)
        if result is None:
            # AI 调用失败，回退到本地规则
            final = self._local_intent_guess(clean_comment, custom_keywords)
            logger.info("[intent_stats] result=%s reason=AI_FAIL_LOCAL comment=%s", final, preview)
            return final

        if result:
            logger.info("[intent_stats] result=True reason=AI_YES comment=%s", preview)
            return True

        # AI 返回 NO：检查是否允许本地规则/自定义关键词复活 AI 判定（默认 True 保持旧行为）
        override = self.config.get("interaction", {}).get("keyword_override_ai", True)
        if override:
            # 先走自定义关键词，再走内置本地规则，确保新增关键词库在 AI 模式下也能生效
            final = self._check_custom_keywords(clean_comment, custom_keywords)
            if final:
                logger.info("[intent_stats] result=True reason=AI_NO_CUSTOM_KEYWORD_OVERRIDE comment=%s", preview)
                return True
            final = self._local_intent_guess(clean_comment, [])
            if final:
                logger.info("[intent_stats] result=True reason=AI_NO_BUILTIN_KEYWORD_OVERRIDE comment=%s", preview)
                return True

        logger.info("[intent_stats] result=False reason=AI_NO_RESPECT comment=%s", preview)
        return False

    def generate_lead_reply(self, comment_text: str, video_title: str = "", keyword: str = "") -> Optional[str]:
        clean_comment = self._normalize_text(comment_text)
        if not clean_comment:
            return None

        if not self.is_enabled():
            logger.info("AI 自动回复已关闭，跳过楼中楼回复生成。")
            return None

        for attempt in range(2):
            candidate = self._call_lead_reply_model(clean_comment, video_title, keyword, strict_retry=attempt > 0)
            candidate = self._sanitize_lead_reply(candidate)
            if self._is_valid_lead_reply(candidate):
                return candidate

        logger.warning("AI 连续 2 次生成失败，跳过楼中楼回复。")
        return None

    def _call_model(self, title: str, keyword: str, strict_retry: bool = False) -> Optional[str]:
        # mode=local 时强制走本地 LangChain，让 persona prompt 真正生效
        if self.ai_config.get("mode", "cloud") == "local":
            base_url = os.environ.get("DEEPSEEK_BASE_URL") or (self.ai_config.get("base_url") or "").strip()
            api_key = os.environ.get("DEEPSEEK_API_KEY") or (self.ai_config.get("api_key") or "").strip()
            model = os.environ.get("DEEPSEEK_MODEL") or (self.ai_config.get("model") or "").strip()

            if not base_url or not api_key or not model:
                logger.warning("AI 回复配置不完整，需要填写 Base URL、API Key 和 Model。")
                return None

            if not all([ChatOpenAI, SystemMessage, HumanMessage]):
                logger.error(f"LangChain 依赖不可用，无法调用 AI 回复接口。{LANGCHAIN_IMPORT_ERROR or ''}")
                return None

            return self._call_langchain(title, keyword, base_url, api_key, model, strict_retry)

        # mode=cloud 走云端 API
        if self.cloud_ai.enabled():
            try:
                data = self.cloud_ai.post("/ai/generate-video-comment", {
                    "keyword": keyword,
                    "title": title,
                    "persona": self.ai_config.get("persona", "a_zhen"),
                    "system_prompt": self._get_persona_prompt("video_comment"),
                })
                return data.get("reply")
            except LicenseError as exc:
                logger.error(f"云端 AI 生成视频评论失败: {exc}")
                return None

        logger.warning("未配置授权码，无法调用云端 AI 生成视频评论。")
        return None

    def _get_model_config(self):
        if self.ai_config.get("mode", "cloud") != "local":
            logger.warning("未配置授权码，无法调用云端 AI。")
            return None

        base_url = os.environ.get("DEEPSEEK_BASE_URL") or (self.ai_config.get("base_url") or "").strip()
        api_key = os.environ.get("DEEPSEEK_API_KEY") or (self.ai_config.get("api_key") or "").strip()
        model = os.environ.get("DEEPSEEK_MODEL") or (self.ai_config.get("model") or "").strip()
        if not base_url or not api_key or not model:
            logger.warning("AI 配置不完整，需要填写 Base URL、API Key 和 Model。")
            return None
        if not all([ChatOpenAI, SystemMessage, HumanMessage]):
            logger.error(f"LangChain 依赖不可用，无法调用 AI 接口。{LANGCHAIN_IMPORT_ERROR or ''}")
            return None
        return base_url, api_key, model

    def _create_llm(self, base_url: str, api_key: str, model: str, temperature: Optional[float] = None, max_tokens: Optional[int] = None):
        return ChatOpenAI(
            base_url=self._normalize_openai_base_url(base_url),
            api_key=api_key,
            model=model,
            temperature=float(self.ai_config.get("temperature", 0.7) if temperature is None else temperature),
            max_tokens=int(self.ai_config.get("max_tokens", 120) if max_tokens is None else max_tokens),
            timeout=int(self.ai_config.get("timeout", 60)),
        )

    def _call_langchain(self, title: str, keyword: str, base_url: str, api_key: str, model: str, strict_retry: bool) -> Optional[str]:
        # 使用信号量限制并发，避免 API 速率限制
        with _ai_api_semaphore:
            try:
                llm = self._create_llm(base_url, api_key, model)
                messages = [
                    SystemMessage(content=self._system_prompt(strict_retry)),
                    HumanMessage(content=self._human_prompt(title, keyword)),
                ]
                response = llm.invoke(messages)
                return self._extract_response_text(response)
            except Exception as exc:
                logger.error(f"LangChain 调用 AI 回复失败: {exc}")
                return None

    def _call_intent_model(self, comment_text: str, video_title: str, keyword: str, custom_keywords: Optional[list] = None) -> Optional[bool]:
        if self.cloud_ai.enabled():
            try:
                data = self.cloud_ai.post("/ai/check-intent-comment", {
                    "keyword": keyword,
                    "title": video_title,
                    "comment_text": comment_text,
                    "custom_keywords": custom_keywords or [],
                })
                return bool(data.get("intent"))
            except LicenseError as exc:
                logger.error(f"云端 AI 判断评论意向失败: {exc}")
                return None

        model_config = self._get_model_config()
        if not model_config:
            return None

        base_url, api_key, model = model_config
        # 使用信号量限制并发，避免 API 速率限制
        with _ai_api_semaphore:
            try:
                # max_tokens=10 足够输出单个数字 0 或 1
                llm = self._create_llm(base_url, api_key, model, temperature=0.1, max_tokens=10)
                messages = [
                    SystemMessage(content=(
                        "# Role\n"
                        "You are a binary lead classifier for Douyin comments. "
                        "Output ONLY the digit 1 or 0. No words, no punctuation, no explanation.\n"
                        "# Output 1 if any of these match:\n"
                        "1. Direct intent: price, link, buy, join, guide, contact, how-to "
                        "(\"多少钱/求带/怎么买/求链接/求教程/私信/微信\")\n"
                        "2. Passive intent: save for later, agreement, waiting "
                        "(\"先收藏/蹲一个/等更新/想要/想入手\")\n"
                        "3. Pain: venting loss, failure, high costs "
                        "(\"亏惨了/割韭菜/踩坑/太难了\")\n"
                        "4. Peer/Tech: corrections, alternative opinions "
                        "(\"步骤不对/参数有问题/核心是XX\")\n"
                        "5. Emotion: awe, jealousy, doubt on revenue "
                        "(\"一天1k真的假的/羡慕/这也行/真的假的\")\n"
                        "# Output 0 ONLY if 100% sure it's NOT a lead:\n"
                        "- Pure memes, spam, repetitive emojis (\"哈哈哈哈/泰裤辣\")\n"
                        "- Generic greetings (\"早安/打卡/路过\")\n"
                        "- Unrelated noise or political content\n"
                        "# CRITICAL: Output ONLY one digit, nothing else."
                    )),
                    HumanMessage(content=(
                        f"视频标题：{video_title or '未提供'}\n"
                        f"搜索关键词：{keyword or '未提供'}\n"
                        f"评论：{comment_text}\n"
                        "输出 1（意向）或 0（非意向）："
                    )),
                ]
                response = llm.invoke(messages)
                text = (self._extract_response_text(response) or "").strip()
                logger.debug("[intent_ai] raw_output=%s", text[:20])
                # 提取第一个数字 0 或 1
                match = re.search(r"[01]", text)
                if match:
                    result = match.group() == "1"
                    logger.debug("[intent_ai] result=%s", result)
                    return result
                logger.warning("[intent_ai] 无法从输出中提取 0/1，原始输出: %s", text[:50])
                return None
            except Exception as exc:
                logger.error(f"AI 判断评论意向失败: {exc}")
                return None

    def _call_lead_reply_model(self, comment_text: str, video_title: str, keyword: str, strict_retry: bool = False) -> Optional[str]:
        # mode=local 时强制走本地 LangChain，让 persona prompt 真正生效
        if self.ai_config.get("mode", "cloud") == "local":
            model_config = self._get_model_config()
            if not model_config:
                return None

            base_url, api_key, model = model_config
            if strict_retry:
                persona = self.ai_config.get("persona", "a_zhen")
                if persona == "a_qiang":
                    retry_line = "上一条太软了，直接抛出利益钩子，用扣1/口1等暗号截流。"
                else:
                    retry_line = "上一条结果太像营销，请改成更克制、更像真人顺手回复。"
            else:
                retry_line = ""
            # 使用信号量限制并发，避免 API 速率限制
            with _ai_api_semaphore:
                try:
                    llm = self._create_llm(base_url, api_key, model, max_tokens=80)
                    messages = [
                        SystemMessage(content=self._get_persona_prompt("lead_reply") + retry_line),
                    HumanMessage(content=(
                            f"视频标题：{video_title or '未提供'}\n"
                            f"搜索关键词：{keyword or '未提供'}\n"
                            f"用户评论：{comment_text}"
                        )),
                    ]
                    response = llm.invoke(messages)
                    return self._extract_response_text(response)
                except Exception as exc:
                    logger.error(f"AI 生成截流回复失败: {exc}")
                    return None

        # mode=cloud 走云端 API
        if self.cloud_ai.enabled():
            try:
                data = self.cloud_ai.post("/ai/generate-lead-reply", {
                    "keyword": keyword,
                    "title": video_title,
                    "comment_text": comment_text,
                    "persona": self.ai_config.get("persona", "a_zhen"),
                    "system_prompt": self._get_persona_prompt("lead_reply"),
                })
                return data.get("reply")
            except LicenseError as exc:
                logger.error(f"云端 AI 生成截流回复失败: {exc}")
                return None

        return None

    def _system_prompt(self, strict_retry: bool) -> str:
        retry_line = "如果第一次结果像营销话术，请改写得更像普通用户自然留言。" if strict_retry else ""
        return self._get_persona_prompt("video_comment") + retry_line

    def _human_prompt(self, title: str, keyword: str) -> str:
        # 仅提供上下文，不附带指令性文字；评论风格完全由 _PERSONA_PROMPTS（阿珍/阿强）主导
        keyword_text = keyword or "未提供"
        return f"标题：{title}\n搜索关键词：{keyword_text}"

    def _normalize_openai_base_url(self, base_url: str) -> str:
        clean_base = base_url.rstrip("/")
        if clean_base.endswith("/chat/completions"):
            clean_base = clean_base[: -len("/chat/completions")]
        return clean_base

    def _extract_response_text(self, response) -> Optional[str]:
        if response is None:
            return None

        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            merged = "".join(parts).strip()
            return merged or None

        return str(content).strip() or None

    def _sanitize_reply(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None

        cleaned = self._normalize_text(text)
        cleaned = re.sub(r"^评论[:：]\s*", "", cleaned)
        cleaned = cleaned.strip("\"' ")
        cleaned = re.sub(r"[#@]", "", cleaned)
        cleaned = re.sub(r"[!！]{2,}", "！", cleaned)
        cleaned = re.sub(r"[?？]{2,}", "？", cleaned)
        cleaned = cleaned.replace("“", "").replace("”", "")
        return cleaned[:38].strip()

    def _is_valid_reply(self, text: Optional[str]) -> bool:
        if not text:
            return False

        if len(text) < 6 or len(text) > 38:
            return False

        if "\n" in text or "\r" in text:
            return False

        for pattern in self._BANNED_PATTERNS:
            if pattern.search(text):
                return False

        if text.count("！") > 1 or text.count("？") > 1:
            return False

        return True

    def _sanitize_lead_reply(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        cleaned = self._normalize_text(text)
        cleaned = re.sub(r"^回复[:：]\s*", "", cleaned)
        cleaned = cleaned.strip("\"' ")
        cleaned = re.sub(r"[#@]", "", cleaned)
        cleaned = re.sub(r"[!！]{2,}", "！", cleaned)
        cleaned = re.sub(r"[?？]{2,}", "？", cleaned)
        return cleaned[:40].strip()

    def _is_valid_lead_reply(self, text: Optional[str]) -> bool:
        if not text:
            return False
        if len(text) < 6 or len(text) > 40:
            return False
        if "\n" in text or "\r" in text:
            return False
        banned_patterns = [
            re.compile(r"(微信|vx|v信|威信|加我|联系我|私信|私聊|进群)", re.IGNORECASE),
            re.compile(r"(http[s]?://|www\.|douyin\.com|v\.douyin\.com)", re.IGNORECASE),
            re.compile(r"(QQ|qq|电话|手机号|微信号|二维码)"),
            re.compile(r"\d{7,}"),
            re.compile(r"(保证|包过|稳赚|返利|刷单)"),
        ]
        return not any(pattern.search(text) for pattern in banned_patterns)

    def _local_intent_guess(self, text: str, custom_keywords: list = None) -> bool:
        """本地规则判定意向：预编译正则 + 否定词过滤 + 自定义关键词。

        判定顺序：
        1. 先检查否定/反讽模式，命中则直接判 False；
        2. 再检查内置 500+ 意向关键词；
        3. 最后检查用户自定义关键词（同样预编译）。
        """
        custom_keywords = custom_keywords or []

        if self._is_negative_intent(text):
            logger.debug("[intent_local] 命中否定模式，判为无意向: %s", text[:30])
            return False

        if self._intent_pattern and self._intent_pattern.search(text):
            logger.info("[intent_local] 命中内置意向关键词: %s", text[:30])
            return True

        return self._check_custom_keywords(text, custom_keywords)

    def _check_custom_keywords(self, text: str, custom_keywords: list) -> bool:
        """检查自定义关键词；使用预编译正则替代线性 in 扫描，提升效率。"""
        if not custom_keywords:
            return False

        self._update_custom_pattern(custom_keywords)
        if self._custom_pattern is None:
            return False

        match = self._custom_pattern.search(text)
        if match:
            logger.info(f"🔍 命中自定义意向关键词: '{match.group()}'")
            return True
        return False

    def _normalize_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", str(text)).strip()
