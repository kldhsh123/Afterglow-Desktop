"""QQ Bot 最小实现：REST API + WebSocket Gateway。

仅覆盖 C2C（私聊）场景的核心能力：
- 鉴权：获取 / 自动续期 access_token
- 接收：op=10 Hello → op=2 Identify → op=1 心跳 → op=0 Dispatch
- 发送：文本消息、本地图片（Base64 上传 + 媒体消息）
"""

from .api import QQBotAPI, MediaFileType
from .gateway import QQBotGateway, C2CMessage

__all__ = ["QQBotAPI", "MediaFileType", "QQBotGateway", "C2CMessage"]
