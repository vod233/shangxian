# -*- coding: utf-8 -*-
r"""评论区意向识别回归测试集（Phase 0.2）

样本规模：30 条（正样本 10 / 负样本-误判 10 / 边界样本 10）
用途：每个 Phase 上线后跑一遍，对比召回率/误判率变化。

运行方式：
    cd d:\CodingTest\111test\111
    python -m dy.test_intent_rules

说明：
    - 本地正则测试不需要 AI 配置，离线可跑
    - AI 路径测试需要配置 .env 中的 AI key（未配置时自动跳过）
    - 真实日志样本待人工补充（见文末 TODO 标注的占位条目）
"""
import logging
import os
import sys
from typing import List, Tuple

# 让脚本可作为模块运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dy.ai_reply_agent import DYReplyAgent

logger = logging.getLogger(__name__)

# ===== 样本定义 =====
# (评论文本, 期望结果, 分类说明)
# 正样本：真意向，应判 True
POSITIVE_SAMPLES: List[Tuple[str, str]] = [
    ("怎么买？多少钱？", "求购买方式+价格"),
    ("求链接", "明确求链接"),
    ("哪里能买到", "明确求购买渠道"),
    ("求推荐一款适合新手的", "求推荐"),
    ("有教程吗", "求教程"),
    ("价格多少", "询问价格"),
    ("想要一份资料", "求资料"),
    ("想了解详细方案", "咨询意愿"),
    ("求带", "求带（口语）"),
    ("还有吗？想入手", "口语意向"),
]

# 负样本-误判：当前正则/逻辑会误判为 True，实际应判 False
NEGATIVE_FALSE_POSITIVE: List[Tuple[str, str]] = [
    ("这是在哪里拍的呀", "询问拍摄地，非购买意向"),
    ("博主今年多少岁", "询问年龄，非价格"),
    ("看了多少遍了还是好看", "询问次数，非价格"),
    ("这方法早过时了", "负面评价含'方法'"),
    ("推荐别人也看看", "分享行为含'推荐'"),
    ("求放过别发了", "调侃含'求'"),
    ("我也了解过确实一般", "已体验负面含'了解'"),
    ("这是哪里的风景", "询问地点含'哪里'"),
    ("推荐算法真是厉害", "技术讨论含'推荐'"),
    ("用了多少次都没效果", "负面含'多少'+'多少次'"),
]

# 边界样本：反讽/消费者互答，应判 False
BOUNDARY_SAMPLES: List[Tuple[str, str]] = [
    ("多少钱能让我死心", "反讽含'多少钱'"),
    ("拼夕夕两块钱包邮吗", "反讽含'包邮'"),
    ("这玩意儿有用吗感觉智商税", "反讽质疑含'有用吗'"),
    ("链接我发你主页了去买吧", "消费者互答含'链接''买'"),
    ("我也想要谁有啊", "消费者互求含'想要'"),
    ("私我了我看看", "消费者互答含'私'"),
    ("靠谱吗这价格水分太大", "质疑含'靠谱吗''价格'"),
    ("教程网上到处都是还用买", "负面含'教程''买'"),
    ("已发你主页了去看看", "消费者互答"),
    ("真的假的这也能赚钱", "质疑含'真的假的'"),
]


def _run_local_regex_tests(agent: DYReplyAgent) -> List[Tuple[str, str, bool]]:
    """离线测试本地正则路径（AI 未启用时的兜底逻辑）。

    返回：[(评论文本, 说明, 是否命中), ...]
    """
    # 临时关闭 AI，强制走本地正则；测试后恢复原配置，避免污染后续 AI 测试
    original_ai_config = agent.ai_config
    agent.ai_config = {"enabled": False}
    try:
        results = []
        for text, desc in POSITIVE_SAMPLES + NEGATIVE_FALSE_POSITIVE + BOUNDARY_SAMPLES:
            hit = agent._local_intent_guess(text, [])
            results.append((text, desc, hit))
        return results
    finally:
        agent.ai_config = original_ai_config


def _run_ai_tests(agent: DYReplyAgent) -> List[Tuple[str, str, bool]]:
    """AI 路径测试（需要 AI 配置）。未启用时返回空列表。"""
    if not agent.is_enabled():
        print("[AI 路径] AI 未启用，跳过")
        return []

    results = []
    for text, desc in POSITIVE_SAMPLES + NEGATIVE_FALSE_POSITIVE + BOUNDARY_SAMPLES:
        hit = agent.is_intent_comment(text, video_title="测试视频", keyword="测试")
        results.append((text, desc, hit))
    return results


def _print_report(title: str, results: List[Tuple[str, str, bool]]):
    """打印测试报告。"""
    pos_total = len(POSITIVE_SAMPLES)
    neg_total = len(NEGATIVE_FALSE_POSITIVE)
    bnd_total = len(BOUNDARY_SAMPLES)

    pos_results = results[:pos_total]
    neg_results = results[pos_total:pos_total + neg_total]
    bnd_results = results[pos_total + neg_total:]

    pos_hit = sum(1 for _, _, h in pos_results if h)
    neg_fp = sum(1 for _, _, h in neg_results if h)
    bnd_fp = sum(1 for _, _, h in bnd_results if h)

    pos_recall = pos_hit / pos_total * 100 if pos_total else 0
    neg_fp_rate = neg_fp / neg_total * 100 if neg_total else 0
    bnd_fp_rate = bnd_fp / bnd_total * 100 if bnd_total else 0

    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")
    print(f"正样本（真意向）召回: {pos_hit}/{pos_total}  ({pos_recall:.0f}%)")
    print(f"负样本-误判率:        {neg_fp}/{neg_total}  ({neg_fp_rate:.0f}%)")
    print(f"边界样本-误判率:       {bnd_fp}/{bnd_total}  ({bnd_fp_rate:.0f}%)")
    print(f"{'-' * 60}")
    print(f"总样本: {len(results)}")
    print(f"{'=' * 60}")

    # 详细列出未命中正样本
    missed_pos = [(t, d) for t, d, h in pos_results if not h]
    if missed_pos:
        print("\n[未命中的正样本]")
        for text, desc in missed_pos:
            print(f"  - {text}  ({desc})")

    # 详细列出误判为 True 的负样本
    fp_neg = [(t, d) for t, d, h in neg_results if h]
    if fp_neg:
        print("\n[误判为 True 的负样本]")
        for text, desc in fp_neg:
            print(f"  - {text}  ({desc})")

    # 详细列出误判为 True 的边界样本
    fp_bnd = [(t, d) for t, d, h in bnd_results if h]
    if fp_bnd:
        print("\n[误判为 True 的边界样本]")
        for text, desc in fp_bnd:
            print(f"  - {text}  ({desc})")


def main():
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    # 加载项目配置
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "user_settings.yaml")
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    agent = DYReplyAgent(config)

    # 1. 本地正则路径测试（离线）
    local_results = _run_local_regex_tests(agent)
    _print_report("本地正则路径测试（AI 未启用兜底）", local_results)

    # 2. AI 路径测试（需配置）
    ai_results = _run_ai_tests(agent)
    if ai_results:
        _print_report("AI 路径测试（AI 启用）", ai_results)

    # 验收标准提示
    print("\n" + "=" * 60)
    print("  验收标准参考")
    print("=" * 60)
    print("Phase 1（漏斗修复）：默认配置下行为与旧逻辑一致")
    print("Phase 2（提示词）：边界样本误判率下降 ≥ 50%，正样本召回不下降")
    print("Phase 3（正则）  ：本地路径召回下降 ≤ 20%，误判下降 ≥ 50%")
    print("=" * 60)


if __name__ == "__main__":
    main()

# ===== TODO: 人工补充真实日志样本 =====
# 当前 30 条样本为基于场景构造的示例。
# 上线后从真实日志（[intent_stats] 标记）抽取以下场景补充：
# 1. 正样本：实际命中并成功转化的评论（补充 5-10 条）
# 2. 负样本：实际误判的评论（从 lead 未回复/投诉中抽取）
# 3. 边界样本：实际反讽/消费者互答案例
# 补充后样本量可达 50+，提升回归测试可信度。
