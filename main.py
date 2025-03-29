import requests
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image


def synthesize_emojis(emoji_one, emoji_two):
    url = "https://xiaobapi.top/api/xb/api/emoji_synthesis.php"
    data = {
        "emoji_one": emoji_one,
        "emoji_two": emoji_two
    }
    try:
        response = requests.post(url, data=data, verify=False)
        response.raise_for_status()
        result = response.json()
        print("API 返回结果:", result)
        return result
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP 错误发生: {http_err}，状态码: {response.status_code}")
    except requests.exceptions.RequestException as req_err:
        print(f"请求发生异常: {req_err}")
    except ValueError:
        print("无法解析返回的 JSON 数据，请检查 API 响应格式。")
    return None


@register("emoji_merge", "hello七七", "Emoji 合成插件", "1.0.0")
class EmojiPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("合成")
    async def merge(self, event: AstrMessageEvent, emoji1: str, emoji2: str):
        result = synthesize_emojis(emoji1, emoji2)
        if result and result.get("code") == 1:
            image_url = result["url"]["url"]
            try:
                yield event.chain_result([Image(file=image_url)])
            except Exception as e:
                print(f"发送图片时出错: {e}")
                yield event.chain_result([Plain(f"发送合成图片失败😢：{str(e)}")])
        else:
            error_msg = result.get("message", "合成失败") if result else "服务不可用"
            yield event.chain_result([Plain(f"合成失败😢：{error_msg}")])

    async def terminate(self):
        pass
    
