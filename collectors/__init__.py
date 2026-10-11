"""数据采集器模块"""

from . import chrome_extensions, github_trending, hackernews, product_hunt
from . import theresanaiforthat, toolify
from .github_trending import fetch_trending_repos
from .product_hunt import fetch_product_hunt_posts
from .hackernews import fetch_hackernews_posts
from .theresanaiforthat import fetch_ai_tools
from .chrome_extensions import fetch_chrome_extensions
from .toolify import fetch_toolify_tools

__all__ = [
    "fetch_trending_repos",
    "fetch_product_hunt_posts",
    "fetch_hackernews_posts",
    "fetch_ai_tools",
    "fetch_chrome_extensions",
    "fetch_toolify_tools",
    "source_status",
]


def source_status():
    """Last error per collector ('' when the last call succeeded).

    Used by the daily report's Source Health section so a broken collector can
    be told apart from a day without opportunities.
    """
    return {
        "product_hunt": getattr(product_hunt, "LAST_ERROR", ""),
        "toolify": getattr(toolify, "LAST_ERROR", ""),
        "ai_tools": getattr(theresanaiforthat, "LAST_ERROR", ""),
        "chrome_extensions": getattr(chrome_extensions, "LAST_ERROR", ""),
        "github": getattr(github_trending, "LAST_ERROR", ""),
        "hackernews": getattr(hackernews, "LAST_ERROR", ""),
    }
