import aiohttp
import re
import json
import shlex
import os
import asyncio
from urllib.parse import urlparse
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image
from astrbot.api import logger


# 加载总结提示词
SUMMARY_PROMPT = """
你是一个专业的API响应分析工具。请对以下API响应内容进行简洁清晰的总结，包括：
返回的主要数据内容

请使用中文回答，保持专业、简洁。

API响应内容:
```
{content}
```
"""

# 配置常量
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB响应限制
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 1  # 初始重试延迟(秒)


async def send_request(url, method="GET", params=None, data=None, headers=None, cookies=None):
    """发送HTTP请求并返回结果，支持自动重试和响应大小限制"""
    retries = 0
    last_error = None
    
    while retries <= MAX_RETRIES:
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                kwargs = {
                    'params': params,
                    'headers': headers,
                    'timeout': aiohttp.ClientTimeout(total=10)
                }
                
                if data:
                    # 如果data是字典，作为json发送，否则作为表单数据发送
                    if isinstance(data, dict):
                        kwargs['json'] = data
                    else:
                        kwargs['data'] = data
                
                # 使用getattr获取对应的HTTP方法函数
                http_method = getattr(session, method.lower(), None)
                if not http_method:
                    return {"success": False, "message": f"不支持的请求方法: {method}"}
                
                async with http_method(url, **kwargs) as response:
                    response.raise_for_status()
                    
                    # 获取内容大小信息
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                        return {
                            "success": False, 
                            "message": f"响应数据过大: {int(content_length)/1024/1024:.2f}MB (最大限制: {MAX_RESPONSE_SIZE/1024/1024}MB)",
                            "status_code": response.status
                        }
                    
                    # 使用流式读取避免一次加载大型响应
                    data = bytearray()
                    chunk_size = 8192  # 8KB chunks
                    async for chunk in response.content.iter_chunked(chunk_size):
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_SIZE:
                            return {
                                "success": False, 
                                "message": f"响应数据超过限制: {MAX_RESPONSE_SIZE/1024/1024}MB",
                                "status_code": response.status
                            }
                    
                    # 尝试解析为JSON
                    try:
                        result = json.loads(data.decode('utf-8'))
                        return {"success": True, "data": result, "status_code": response.status}
                    except:
                        # 如果不是JSON，返回文本内容
                        return {"success": True, "data": data.decode('utf-8'), "status_code": response.status}
        
        except aiohttp.ClientResponseError as http_err:
            # 非网络错误，直接返回
            return {"success": False, "message": f"HTTP错误: {http_err}", "status_code": http_err.status}
        except (aiohttp.ClientConnectorError, aiohttp.ServerTimeoutError, aiohttp.ClientOSError) as e:
            # 网络连接错误或超时，可重试
            retries += 1
            last_error = e
            if retries <= MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * retries)  # 增加重试延迟
                logger.info(f"重试请求({retries}/{MAX_RETRIES}): {url}")
                continue
            else:
                # 达到最大重试次数
                return {"success": False, "message": f"请求失败(已重试{MAX_RETRIES}次): {str(last_error)}"}
        except Exception as e:
            # 其他错误不重试
            return {"success": False, "message": f"请求错误: {str(e)}"}


def parse_curl_command(curl_command):
    """解析类似curl的命令格式，使用更健壮的URL解析"""
    result = {
        'method': 'GET',
        'url': '',
        'headers': {},
        'data': None,
        'cookies': {}
    }
    
    # 清理命令，处理特殊字符 ^ 和 引号
    clean_command = curl_command.replace("^", "").replace('\\\"', '"')
    
    # 提取URL
    url_match = re.search(r'curl\s+["\']?(https?://[^\s"\']+)["\']?', clean_command)
    if url_match:
        url = url_match.group(1)
        # 验证URL格式
        parsed_url = urlparse(url)
        if not (parsed_url.scheme and parsed_url.netloc):
            return None, "无效的URL格式，确保包含协议(http/https)和域名"
        result['url'] = url
    else:
        return None, "无法解析URL，请检查格式"
    
    # 提取方法
    method_match = re.search(r'-X\s+([A-Z]+)', clean_command)
    if method_match:
        result['method'] = method_match.group(1)
    
    # 提取头信息
    headers_matches = re.finditer(r'-H\s+["\']([^:]+):\s*([^"\']+)["\']', clean_command)
    for match in headers_matches:
        header_name = match.group(1).strip()
        header_value = match.group(2).strip()
        result['headers'][header_name] = header_value
    
    # 提取cookies
    cookies_match = re.search(r'-b\s+["\'](.+?)["\']', clean_command)
    if cookies_match:
        cookies_str = cookies_match.group(1)
        for cookie in cookies_str.split(';'):
            if '=' in cookie:
                name, value = cookie.strip().split('=', 1)
                result['cookies'][name] = value
    
    # 提取数据
    data_match = re.search(r'-d\s+["\'](.+?)["\']', clean_command)
    if data_match:
        data_str = data_match.group(1)
        # 尝试解析为JSON
        try:
            result['data'] = json.loads(data_str)
        except json.JSONDecodeError:
            # 如果不是JSON格式，保持原始字符串
            result['data'] = data_str
            
        # 如果指定了数据但没指定方法，默认为POST
        if 'method' not in result:
            result['method'] = 'POST'
    
    return result, None


@register("http_request", "wayzinx", "HTTP请求插件", "1.0.0")
class HttpRequestPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def summarize_response(self, result, session_id):
        """使用LLM总结HTTP响应内容"""
        if not result["success"]:
            return f"请求失败: {result['message']}"
        
        # 获取响应内容
        response_content = str(result["data"])
        
        # 如果内容太少，不需要总结
        if len(response_content) < 100:
            return f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{response_content}"
        
        # 截断过长内容
        if len(response_content) > 8000:
            response_content = response_content[:8000] + "...(内容过长已截断)"
        
        # 调用LLM生成总结内容
        try:
            prompt = SUMMARY_PROMPT.format(content=response_content)
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                session_id=f"{session_id}_http_summary"
            )
            
            # 输出总结内容
            return f"请求成功 (状态码: {result['status_code']})\n\n响应内容总结:\n{llm_response.completion_text}"
        except Exception as e:
            logger.error(f"总结响应内容时出错: {e}")
            # 如果总结失败，返回原始内容(截断)
            truncated_content = response_content[:1500] + ("...(内容过长已截断)" if len(response_content) > 1500 else "")
            return f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{truncated_content}"

    @filter.command("get")
    async def get_request(self, event: AstrMessageEvent, url: str):
        """发送GET请求到指定URL并总结响应内容"""
        # 验证URL格式
        parsed_url = urlparse(url)
        if not (parsed_url.scheme and parsed_url.netloc):
            yield event.chain_result([Plain("无效的URL格式，确保包含协议(http/https)和域名")])
            return
            
        result = await send_request(url, method="GET")
        response_text = await self.summarize_response(result, event.session_id)
        yield event.chain_result([Plain(response_text)])

    @filter.command("post")
    async def post_request(self, event: AstrMessageEvent, url: str, data: str = ""):
        """发送POST请求到指定URL并总结响应内容"""
        # 验证URL格式
        parsed_url = urlparse(url)
        if not (parsed_url.scheme and parsed_url.netloc):
            yield event.chain_result([Plain("无效的URL格式，确保包含协议(http/https)和域名")])
            return
            
        # 尝试解析data参数为JSON
        post_data = None
        try:
            if data:
                post_data = json.loads(data)
        except json.JSONDecodeError:
            yield event.chain_result([Plain("数据格式错误，请使用有效的JSON格式")])
            return

        result = await send_request(url, method="POST", data=post_data)
        response_text = await self.summarize_response(result, event.session_id)
        yield event.chain_result([Plain(response_text)])

    @filter.command("request", "req")
    async def custom_request(self, event: AstrMessageEvent, method: str, url: str, params: str = ""):
        """发送自定义HTTP请求并总结响应内容"""
        # 验证URL格式
        parsed_url = urlparse(url)
        if not (parsed_url.scheme and parsed_url.netloc):
            yield event.chain_result([Plain("无效的URL格式，确保包含协议(http/https)和域名")])
            return
            
        # 解析可能的参数
        try:
            params_dict = json.loads(params) if params else None
        except json.JSONDecodeError:
            yield event.chain_result([Plain("参数格式错误，请使用有效的JSON格式")])
            return
            
        data = headers = None
        if params_dict:
            data = params_dict.get("data")
            headers = params_dict.get("headers")
        
        result = await send_request(url, method=method, data=data, headers=headers)
        response_text = await self.summarize_response(result, event.session_id)
        yield event.chain_result([Plain(response_text)])
    
    @filter.command("请求", "curl")
    async def curl_request(self, event: AstrMessageEvent, *args):
        """使用类似curl的格式发送HTTP请求并总结响应内容"""
        # 将所有参数合并回一个字符串
        curl_command = " ".join(args)
        
        # 如果命令不以curl开头，添加curl前缀
        if not curl_command.lower().startswith("curl "):
            curl_command = "curl " + curl_command
        
        # 解析curl命令
        parsed_command, error = parse_curl_command(curl_command)
        if error:
            yield event.chain_result([Plain(f"解析curl命令失败: {error}")])
            return
        
        # 发送请求
        result = await send_request(
            url=parsed_command['url'],
            method=parsed_command['method'],
            headers=parsed_command['headers'],
            data=parsed_command['data'],
            cookies=parsed_command['cookies']
        )
        
        # 处理响应和总结
        response_text = await self.summarize_response(result, event.session_id)
        yield event.chain_result([Plain(response_text)])

    async def terminate(self):
        pass
    
