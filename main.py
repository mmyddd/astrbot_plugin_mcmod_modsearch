import aiohttp
import re
import json
import shlex
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image


async def send_request(url, method="GET", params=None, data=None, headers=None, cookies=None):
    """发送HTTP请求并返回结果"""
    try:
        async with aiohttp.ClientSession(cookies=cookies) as session:
            kwargs = {
                'params': params,
                'headers': headers,
                'timeout': aiohttp.ClientTimeout(total=10)
            }
            
            if data:
                # 如果data是字典，保持不变，否则尝试解析为JSON
                if isinstance(data, dict):
                    kwargs['json'] = data
                else:
                    try:
                        kwargs['data'] = data
                    except:
                        kwargs['data'] = data
            
            # 使用getattr获取对应的HTTP方法函数
            http_method = getattr(session, method.lower(), None)
            if not http_method:
                return {"success": False, "message": f"不支持的请求方法: {method}"}
            
            async with http_method(url, **kwargs) as response:
                response.raise_for_status()
                
                # 尝试返回JSON响应
                try:
                    result = await response.json()
                    return {"success": True, "data": result, "status_code": response.status}
                except:
                    # 如果不是JSON，返回文本内容
                    text = await response.text()
                    return {"success": True, "data": text, "status_code": response.status}
    
    except aiohttp.ClientResponseError as http_err:
        return {"success": False, "message": f"HTTP错误: {http_err}", "status_code": http_err.status}
    except aiohttp.ClientConnectorError:
        return {"success": False, "message": "连接错误: 无法连接到服务器"}
    except aiohttp.ClientTimeout:
        return {"success": False, "message": "请求超时: 服务器响应时间过长"}
    except aiohttp.ClientError as e:
        return {"success": False, "message": f"请求错误: {str(e)}"}


def parse_curl_command(curl_command):
    """解析类似curl的命令格式"""
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
    url_match = re.search(r'curl\s+["\']?(https?://[^"\'\s]+)["\']?', clean_command)
    if url_match:
        result['url'] = url_match.group(1)
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
        result['data'] = data_match.group(1)
        # 如果指定了数据但没指定方法，默认为POST
        if 'method' not in result:
            result['method'] = 'POST'
    
    return result, None


@register("http_request", "wayzinx", "HTTP请求插件", "1.0.0")
class HttpRequestPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("get")
    async def get_request(self, event: AstrMessageEvent, url: str):
        """发送GET请求到指定URL"""
        result = await send_request(url, method="GET")
        if result["success"]:
            response_text = f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{str(result['data'])[:1500]}"
            if len(str(result['data'])) > 1500:
                response_text += "\n...(内容过长已截断)"
        else:
            response_text = f"请求失败: {result['message']}"
        
        yield event.chain_result([Plain(response_text)])

    @filter.command("post")
    async def post_request(self, event: AstrMessageEvent, url: str, data: str = ""):
        """发送POST请求到指定URL，可选添加数据参数"""
        # 尝试解析data参数为JSON
        post_data = None
        try:
            if data:
                post_data = eval(data)  # 注意: 生产环境应当避免使用eval
        except:
            yield event.chain_result([Plain("数据格式错误，请使用有效的Python字典格式")])
            return

        result = await send_request(url, method="POST", data=post_data)
        if result["success"]:
            response_text = f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{str(result['data'])[:1500]}"
            if len(str(result['data'])) > 1500:
                response_text += "\n...(内容过长已截断)"
        else:
            response_text = f"请求失败: {result['message']}"
        
        yield event.chain_result([Plain(response_text)])

    @filter.command("request", "req")
    async def custom_request(self, event: AstrMessageEvent, method: str, url: str, params: str = ""):
        """发送自定义HTTP请求"""
        # 解析可能的参数
        try:
            params_dict = eval(params) if params else None
        except:
            yield event.chain_result([Plain("参数格式错误，请使用有效的Python字典格式")])
            return
            
        data = headers = None
        if params_dict:
            data = params_dict.get("data")
            headers = params_dict.get("headers")
        
        result = await send_request(url, method=method, data=data, headers=headers)
        if result["success"]:
            response_text = f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{str(result['data'])[:1500]}"
            if len(str(result['data'])) > 1500:
                response_text += "\n...(内容过长已截断)"
        else:
            response_text = f"请求失败: {result['message']}"
        
        yield event.chain_result([Plain(response_text)])
    
    @filter.command("请求", "curl")
    async def curl_request(self, event: AstrMessageEvent, *args):
        """使用类似curl的格式发送HTTP请求"""
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
        
        # 处理响应
        if result["success"]:
            response_text = f"请求成功 (状态码: {result['status_code']})\n响应内容:\n{str(result['data'])[:1500]}"
            if len(str(result['data'])) > 1500:
                response_text += "\n...(内容过长已截断)"
        else:
            response_text = f"请求失败: {result['message']}"
        
        yield event.chain_result([Plain(response_text)])

    async def terminate(self):
        pass
    
