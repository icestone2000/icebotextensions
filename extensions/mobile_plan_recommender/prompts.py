from typing import List, Dict, Any
import json


EXTRACTION_SYSTEM_PROMPT = """
你是一个严谨的信息抽取器。请从运营商套餐网页 HTML 中抽取“手机卡/号卡/流量套餐”条目。
必须输出 JSON 数组，不要输出其他内容，不要 markdown 代码块。
每个元素字段必须包含：
- name: 套餐名称
- description: 简要描述（如月租、流量、通话）
- apply_url: 办理链接
- details: 详细说明（优先来自 itembot 文本）
过滤掉明显非手机套餐项目（如宽带、门锁、路由器、摄像头、纯设备等）。
""".strip()


RECOMMEND_SYSTEM_PROMPT = """
你是套餐推荐助手。根据用户查询条件，从给定套餐列表中挑选最匹配的前 N 个。
必须输出 JSON 数组，不要输出其他内容，不要 markdown 代码块。
每个元素字段：
- name
- description
- apply_url
- details
- reason: 推荐理由（简短）
请理解自然语言中的运营商偏好、预算、流量需求、通话需求、模糊表达（如“50左右”“流量多的”）。
""".strip()


def build_extraction_user_prompt(raw_html: str) -> str:
    # 控制 token，避免过长；网页结构相对固定，截断后通常仍可提取核心条目。
    html_snippet = raw_html[:120000]
    return f"请从以下 HTML 提取套餐列表并返回 JSON 数组：\n\n{html_snippet}"


def build_recommend_user_prompt(query: str, top_k: int, plans: List[Dict[str, Any]]) -> str:
    payload = {
        "query": query,
        "top_k": top_k,
        "plans": plans,
    }
    return (
        "请基于输入数据推荐套餐，返回 JSON 数组，最多 top_k 条。\n"
        + json.dumps(payload, ensure_ascii=False)
    )

