import aiohttp
import re
import json
import shlex
import os
import asyncio
import subprocess
from urllib.parse import urlparse
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image
from astrbot.api import logger

# 在插件加载时尝试运行mcmod_api.py
try:
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    api_path = os.path.join(current_dir, "api", "mcmod_api.py")
    
    # 检查文件是否存在
    if os.path.exists(api_path):
        logger.info(f"正在启动 mcmod_api.py...")
        
        # 使用subprocess运行脚本（非阻塞方式）
        process = subprocess.Popen(
            ["python", api_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.path.dirname(api_path),
            text=True
        )
        
        # 定义检查进程状态的函数
        def check_process():
            return_code = process.poll()
            if return_code is None:
                logger.info("mcmod_api.py 仍在运行中...")
                # 5秒后再次检查
                asyncio.get_event_loop().call_later(5, check_process)
            elif return_code == 0:
                logger.info("mcmod_api.py 成功启动")
            else:
                stderr = process.stderr.read()
                logger.error(f"mcmod_api.py 启动失败 (返回码: {return_code}): {stderr}")
        
        # 首次检查
        asyncio.get_event_loop().call_soon(check_process)
        
    else:
        logger.warning(f"未找到mcmod_api.py文件: {api_path}")
except Exception as e:
    logger.error(f"运行mcmod_api.py时出错: {e}")

# API配置
API_BASE_URL = "http://localhost:15001"  # 修改为您的API服务器地址

# 加载总结提示词
SUMMARY_PROMPT = """
你是一个专业的API响应分析工具，要求包括：
不需要总结，仅按照优质打印格式输出所有mod名称和URL，做好排列
排列格式
| mod/modpack名称                          | URL                                  |
|----------------------------------|--------------------------------------|
| mod/modpack名称 | URL  |
请使用中文回答。
API响应内容:
{content}
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
                    if isinstance(data, dict):
                        kwargs['json'] = data
                    else:
                        kwargs['data'] = data
                
                http_method = getattr(session, method.lower(), None)
                if not http_method:
                    return {"success": False, "message": f"不支持的请求方法: {method}"}
                
                async with http_method(url, **kwargs) as response:
                    response.raise_for_status()
                    
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                        return {
                            "success": False, 
                            "message": f"响应数据过大: {int(content_length)/1024/1024:.2f}MB (最大限制: {MAX_RESPONSE_SIZE/1024/1024}MB)",
                            "status_code": response.status
                        }
                    
                    data = bytearray()
                    chunk_size = 8192
                    async for chunk in response.content.iter_chunked(chunk_size):
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_SIZE:
                            return {
                                "success": False, 
                                "message": f"响应数据超过限制: {MAX_RESPONSE_SIZE/1024/1024}MB",
                                "status_code": response.status
                            }
                    
                    try:
                        result = json.loads(data.decode('utf-8'))
                        return {"success": True, "data": result, "status_code": response.status}
                    except:
                        return {"success": True, "data": data.decode('utf-8'), "status_code": response.status}
        
        except aiohttp.ClientResponseError as http_err:
            return {"success": False, "message": f"HTTP错误: {http_err}", "status_code": http_err.status}
        except (aiohttp.ClientConnectorError, aiohttp.ServerTimeoutError, aiohttp.ClientOSError) as e:
            retries += 1
            last_error = e
            if retries <= MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * retries)
                logger.info(f"重试请求({retries}/{MAX_RETRIES}): {url}")
                continue
            else:
                return {"success": False, "message": f"请求失败(已重试{MAX_RETRIES}次): {str(last_error)}"}
        except Exception as e:
            return {"success": False, "message": f"请求错误: {str(e)}"}

@register("mcmod查询插件", "mmyddd", "基于wayzinx/HTTP请求插件修改", "1.0.0")
class HttpRequestPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.mcmod_process = None  # 存储子进程引用

    async def format_mod_results(self, result):
        """格式化模组/整合包搜索结果"""
        if not result["success"]:
            return f"查询失败: {result['message']}"
        
        data = result["data"]
        if data.get("status") != "success":
            return f"API返回错误: {data.get('message', '未知错误')}"
        
        results = data.get("results", [])
        if not results:
            return "没有找到相关结果"
        
        # 构建表格格式输出
        table = "| 名称 | 链接 |\n|------|------|\n"
        for item in results:
            name = item.get("name", "未知名称")
            url = item.get("url", "#")
            table += f"| {name} | {url} |\n"
        
        return table

    @filter.command("查模组")
    async def search_mod(self, event: AstrMessageEvent, name: str):
        """查询mcmod百科中的模组"""
        url = f"{API_BASE_URL}/search?mod={name}"
        result = await send_request(url)
        response_text = await self.format_mod_results(result)
        yield event.chain_result([Plain(response_text)])

    @filter.command("查整合包")
    async def search_modpack(self, event: AstrMessageEvent, name: str):
        """查询mcmod百科中的整合包"""
        url = f"{API_BASE_URL}/search?modpack={name}"
        result = await send_request(url)
        response_text = await self.format_mod_results(result)
        yield event.chain_result([Plain(response_text)])

    async def summarize_response(self, result, session_id):
        """保留原有的总结功能"""
        if not result["success"]:
            return f"请求失败: {result['message']}"
        
        response_content = str(result["data"])
        
        if len(response_content) < 10:
            return f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{response_content}"
        
        if len(response_content) > 8000:
            response_content = response_content[:8000] + "...(内容过长已截断)"
        
        try:
            prompt = SUMMARY_PROMPT.format(content=response_content)
            llm_response = await self.context.get_using_provider().text_chat(
                prompt=prompt,
                session_id=f"{session_id}_http_summary"
            )
            return f"查询mod/modpack结果:\n{llm_response.completion_text}"
        except Exception as e:
            logger.error(f"总结响应内容时出错: {e}")
            truncated_content = response_content[:1500] + ("...(内容过长已截断)" if len(response_content) > 1500 else "")
            return f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{truncated_content}"

    async def terminate(self):
        """插件终止时清理子进程"""
        if hasattr(self, 'mcmod_process') and self.mcmod_process:
            try:
                self.mcmod_process.terminate()
                logger.info("已终止mcmod_api.py进程")
            except Exception as e:
                logger.error(f"终止mcmod_api.py进程时出错: {e}")
