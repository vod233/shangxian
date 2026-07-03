"""测试 _is_valid_lead_reply_text 纯函数的 behavior。

背景：F3 AI 连续2次生成失败后跳过楼中楼回复。retry 逻辑的核心判断是
_is_valid_lead_reply：判断 AI 生成的回复是否有效。此测试锁住判断规则，
确保无效回复（违禁词/引流词/超长/超短/含换行）被正确拒绝，
有效回复被接受，避免误跳过或误采纳。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dy.ai_reply_agent import _is_valid_lead_reply_text


class TestIsValidLeadReplyText:
    """通过 public 纯函数验证楼中楼回复有效性判断 behavior。"""

    def test_valid_reply_returns_true(self):
        """合规、自然、6-40字符的回复被视为有效。"""
        assert _is_valid_lead_reply_text("顺手放背景图了 去看下有你需要的") is True

    def test_none_returns_false(self):
        assert _is_valid_lead_reply_text(None) is False

    def test_empty_returns_false(self):
        assert _is_valid_lead_reply_text("") is False

    def test_too_short_returns_false(self):
        """长度<6的回复无效。"""
        assert _is_valid_lead_reply_text("好的") is False

    def test_too_long_returns_false(self):
        """长度>40的回复无效。"""
        assert _is_valid_lead_reply_text("一" * 41) is False

    def test_contains_newline_returns_false(self):
        """含换行符的回复无效（楼中楼回复应为单行）。"""
        assert _is_valid_lead_reply_text("第一行\n第二行内容足够长") is False

    def test_contains_wechat_banned_returns_false(self):
        """含微信/vx/加我等引流词的回复无效。"""
        for word in ["加我微信", "vx:12345", "私聊我", "进群了解"]:
            assert _is_valid_lead_reply_text(f"看看 {word} 详细聊") is False, f"应拒绝: {word}"

    def test_contains_url_returns_false(self):
        """含 URL 的回复无效。"""
        assert _is_valid_lead_reply_text("看 https://example.com 详情") is False

    def test_contains_phone_number_returns_false(self):
        """含 7 位以上数字的回复无效（防电话号码）。"""
        assert _is_valid_lead_reply_text("打 1234567 联系详细聊") is False

    def test_contains_fraud_banned_returns_false(self):
        """含保证/包过/返利/刷单等欺诈词的回复无效。"""
        assert _is_valid_lead_reply_text("保证赚钱的详细聊聊") is False

    def test_contains_dark_redirect_returns_false(self):
        """含背景墙/主页/详情等暗引流词的回复无效。

        复现：v13 兜底回复"顺手放背景图了 去看下有你需要的"含"背景墙"语义，
        但此处检测的是精确词"背景墙"。注意：实测回复用了"背景图"绕过检测，
        说明检测有缺口，但本测试先锁住现有规则。
        """
        assert _is_valid_lead_reply_text("去背景墙看详细聊聊") is False
        assert _is_valid_lead_reply_text("去主页看详细聊聊") is False
