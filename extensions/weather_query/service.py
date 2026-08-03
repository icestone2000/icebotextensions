"""天气查询：优先国内 itboy 接口（免 Key），失败时回退 wttr.in。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from config.logging import app_logger

from .city_codes import normalize_city_name, resolve_city_code

ITBOY_URL = "http://t.weather.itboy.net/api/weather/city/{citykey}"
WTTR_URL = "https://wttr.in/{city}?format=j1&lang=zh"


class WeatherQueryService:
    async def query(self, city: str) -> Dict[str, Any]:
        city_norm = normalize_city_name(city)
        if not city_norm:
            return {"error": "city 不能为空"}

        citykey = resolve_city_code(city_norm)
        if citykey:
            try:
                result = await self._query_itboy(citykey, city_norm)
                if result:
                    return result
            except Exception as exc:
                app_logger.warning("[weather_query] itboy failed: %s", exc)

        try:
            return await self._query_wttr(city_norm)
        except Exception as exc:
            app_logger.exception("[weather_query] wttr failed: %s", exc)
            return {"error": f"查询失败: {exc}"}

    async def _query_itboy(self, citykey: str, city_display: str) -> Optional[Dict[str, Any]]:
        url = ITBOY_URL.format(citykey=citykey)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("status") != 200:
            return None

        data = payload.get("data") or {}
        forecast = data.get("forecast") or []
        today = forecast[0] if forecast else {}

        return {
            "city": (payload.get("cityInfo") or {}).get("city") or city_display,
            "source": "itboy",
            "temperature": data.get("wendu"),
            "humidity": data.get("shidu"),
            "quality": data.get("quality"),
            "weather_type": today.get("type"),
            "high": today.get("high"),
            "low": today.get("low"),
            "wind": f"{today.get('fx', '')} {today.get('fl', '')}".strip(),
            "notice": today.get("notice"),
            "tip": data.get("ganmao"),
            "update_time": (payload.get("cityInfo") or {}).get("updateTime"),
        }

    async def _query_wttr(self, city: str) -> Dict[str, Any]:
        url = WTTR_URL.format(city=city)
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()

        current = (payload.get("current_condition") or [{}])[0]
        today = ((payload.get("weather") or [{}])[0]).get("hourly") or [{}]
        desc = (today[0].get("lang_zh") or [{}])[0].get("value") if today else ""
        if not desc:
            desc = (current.get("lang_zh") or [{}])[0].get("value") if current.get("lang_zh") else ""

        return {
            "city": city,
            "source": "wttr.in",
            "temperature": current.get("temp_C"),
            "humidity": f"{current.get('humidity', '')}%",
            "weather_type": desc or "未知",
            "high": None,
            "low": None,
            "wind": f"风速 {current.get('windspeedKmph', '')} km/h",
            "notice": None,
            "tip": None,
            "update_time": current.get("observation_time"),
        }


def format_weather_message(data: Dict[str, Any]) -> str:
    if data.get("error"):
        return f"天气查询失败：{data['error']}"

    lines = [
        f"【{data.get('city', '未知')}天气】",
        f"天气：{data.get('weather_type') or '—'}",
        f"当前气温：{data.get('temperature')}℃",
    ]
    if data.get("high") or data.get("low"):
        lines.append(f"今日：{data.get('low') or '—'} ~ {data.get('high') or '—'}")
    if data.get("humidity"):
        lines.append(f"湿度：{data.get('humidity')}")
    if data.get("quality"):
        lines.append(f"空气质量：{data.get('quality')}")
    if data.get("wind"):
        lines.append(f"风力：{data.get('wind')}")
    if data.get("tip"):
        lines.append(f"提示：{data.get('tip')}")
    if data.get("notice"):
        lines.append(f"{data.get('notice')}")
    return "\n".join(lines)
