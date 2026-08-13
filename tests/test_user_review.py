"""V1.6.3：复核改级后同步修订对外叙述。

analysis_text 第五段"总体评价"与 HABC 绑定，复核改级后必须随之改写，
否则对销售人员呈现"最终 H 级、全文论证 A 级"的矛盾文本。前四段是事实
陈述，与等级无关，必须逐字保留——这是代码切分（而非让模型照抄）的理由。
"""
from app.workflow.pipeline import CONCLUSION_ANCHOR, _revise_analysis

FOUR = ("一、评论行为与用户身份\n该用户多次在评论中询价。\n"
        "二、购车阶段评估\n处于积极对比阶段。\n"
        "三、目标车型与我方车型匹配度\n目标车型与我方同级且价位接近。\n"
        "四、主页画像与调整结论\n主页画像无支持上调的直接证据。\n")
ANALYSIS = FOUR + CONCLUSION_ANCHOR + "\n综合判定为 A 级线索，建议常规跟进。"
NEW_BODY = "多条评论跨时间印证持续购车关注，判定为 H 级线索，建议最高优先级跟进。"


def test_replace_keeps_first_four_sections_byte_identical():
    """核心承诺：锚点命中时前四段逐字节保留，只有第五段被换掉。"""
    new, revision = _revise_analysis(ANALYSIS, NEW_BODY)
    assert revision == "replaced"
    assert new.startswith(FOUR)
    assert "综合判定为 A 级线索" not in new
    assert new == FOUR + CONCLUSION_ANCHOR + "\n" + NEW_BODY


def test_anchor_missing_falls_back_to_append():
    """锚点缺失时退化为文末追加，原文完整保留，绝不失真也绝不失败。"""
    text = "该用户多次询价，综合判定为 A 级线索。"   # 模型未按格式输出段标题
    new, revision = _revise_analysis(text, NEW_BODY)
    assert revision == "appended"
    assert new.startswith(text)
    assert CONCLUSION_ANCHOR + "（复核修订）" in new
    assert new.endswith(NEW_BODY)


def test_empty_conclusion_leaves_text_untouched():
    """复核未给正文时文本一字不动，等级仍按复核结果改（由调用方负责）。"""
    for empty in (None, "", "   ", "\n"):
        new, revision = _revise_analysis(ANALYSIS, empty)
        assert (new, revision) == (ANALYSIS, "none")


def test_conclusion_carrying_its_own_heading_is_not_duplicated():
    """模型不听话、正文自带段标题时，不得出现重复标题。"""
    new, revision = _revise_analysis(
        ANALYSIS, CONCLUSION_ANCHOR + "\n" + NEW_BODY)
    assert revision == "replaced"
    assert new.count(CONCLUSION_ANCHOR) == 1
    assert new.endswith(NEW_BODY)


def test_duplicate_anchor_uses_last_occurrence():
    """总体评价是末段；前文引用到该标题时必须切在最后一次出现处。"""
    text = ("一、评论行为与用户身份\n详见下文五、总体评价。\n"
            + CONCLUSION_ANCHOR + "\n综合判定为 A 级线索。")
    new, revision = _revise_analysis(text, NEW_BODY)
    assert revision == "replaced"
    assert new == ("一、评论行为与用户身份\n详见下文五、总体评价。\n"
                   + CONCLUSION_ANCHOR + "\n" + NEW_BODY)


def test_empty_analysis_text_appends_without_leading_blank_lines():
    """定级节点未给 analysis_text 时，追加结果不应以空行开头。"""
    new, revision = _revise_analysis("", NEW_BODY)
    assert revision == "appended"
    assert new == CONCLUSION_ANCHOR + "（复核修订）\n" + NEW_BODY
