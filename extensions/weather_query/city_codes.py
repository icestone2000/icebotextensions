"""常见城市名 -> itboy 天气 citykey（无需 API Key 的国内接口）。"""
from __future__ import annotations

from typing import Optional

# 来源：公开城市编码表，可按需扩展
CITY_CODE_MAP = {
    "北京": "101010100",
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    "广州": "101280101",
    "深圳": "101280601",
    "杭州": "101210101",
    "南京": "101190101",
    "苏州": "101190401",
    "成都": "101270101",
    "武汉": "101200101",
    "西安": "101110101",
    "郑州": "101180101",
    "长沙": "101250101",
    "青岛": "101120201",
    "大连": "101070201",
    "厦门": "101230201",
    "合肥": "101220101",
    "福州": "101230101",
    "济南": "101120101",
    "沈阳": "101070101",
    "哈尔滨": "101050101",
    "长春": "101060101",
    "石家庄": "101090101",
    "太原": "101100101",
    "南昌": "101240101",
    "昆明": "101290101",
    "贵阳": "101260101",
    "南宁": "101300101",
    "海口": "101310101",
    "兰州": "101160101",
    "银川": "101170101",
    "西宁": "101150101",
    "乌鲁木齐": "101130101",
    "拉萨": "101140101",
    "呼和浩特": "101080101",
    "香港": "101320101",
    "澳门": "101330101",
    "台北": "101340101",
}


def normalize_city_name(name: str) -> str:
    s = (name or "").strip()
    for suffix in ("市", "省", "自治区", "特别行政区"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
    return s.strip()


def resolve_city_code(city: str) -> Optional[str]:
    key = normalize_city_name(city)
    if not key:
        return None
    if key in CITY_CODE_MAP:
        return CITY_CODE_MAP[key]
    # 模糊：用户说「北京市」已 normalize；再试子串匹配
    for name, code in CITY_CODE_MAP.items():
        if name in key or key in name:
            return code
    return None
