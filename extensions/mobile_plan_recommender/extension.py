from .service import MobilePlanRecommenderService
from .tool import MobilePlanRecommendTool


_service = MobilePlanRecommenderService()
_tool = MobilePlanRecommendTool(_service)


def register(ctx):
    try:
        ctx.tool_registry.register_tool(_tool)
        ctx.logger.info("[mobile_plan_recommender] registered mobile_plan_recommend")
    except Exception as e:
        ctx.logger.warning(f"[mobile_plan_recommender] failed to register mobile_plan_recommend: {e}")


def unregister(ctx):
    ctx.logger.info("[mobile_plan_recommender] unregister called")

