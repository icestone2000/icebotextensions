import json


CALC_SYSTEM_PROMPT = """
你是一个严谨的代练报价计算助手。
请严格按照用户提供的价格表计算报价，必须先拆分每一段并说明每段单价与分段总价，再累计得到最终总价。
你必须只返回 JSON 文本，不要返回 markdown，不要返回额外解释。
JSON 字段必须包含：
- calc_process: 字符串，详细计算过程
- calc_result: 字符串，最终整数结果（仅数字）
""".strip()


def build_calc_user_prompt(price_table_text: str, star_level_input: str) -> str:
    payload = {
        "price_table_text": price_table_text,
        "star_level_input": star_level_input,
    }
    return (
        "严格按照以下价格表计算报价，一定要列出计算过程，先根据价格表找出每一段的单价，"
        "然后列出每一段对应的总价，最后把每一段的总价格累计，算出最后的结果。"
        "结果以 json 文本返回，类似如下：\n"
        "{\n"
        '  "calc_process": "0星到90星的话，分两段算哈：\\n70星到80星是5元/星\\n80星到90星也是5元/星",\n'
        '  "calc_result": "100"\n'
        "}\n\n"
        "输入数据如下：\n"
        + json.dumps(payload, ensure_ascii=False)
    )
