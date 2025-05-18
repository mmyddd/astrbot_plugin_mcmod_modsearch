import aiohttp
import json
import os
import asyncio
import subprocess
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

class PluginConfig:
    """插件配置管理类"""
    def __init__(self, context: Context):
        self.context = context
        self.config = self._load_default_config()
        self._validate_config()

    def _load_default_config(self):
        """加载默认配置"""
        return {
            "api_port": 15001,
            "max_single_results": 20,
            "max_multi_results": 10,
            "api_timeout": 15,
            "enable_all_search": True
        }

    def _validate_config(self):
        """验证并修正配置值"""
        try:
            # 端口范围验证
            self.config["api_port"] = max(1024, min(65535, int(self.config.get("api_port", 15001))))
            # 结果数量验证
            self.config["max_single_results"] = max(1, min(50, int(self.config.get("max_single_results", 20))))
            self.config["max_multi_results"] = max(1, min(20, int(self.config.get("max_multi_results", 10))))
            # 超时时间验证
            self.config["api_timeout"] = max(5, min(30, int(self.config.get("api_timeout", 15))))
            # 布尔值验证
            self.config["enable_all_search"] = bool(self.config.get("enable_all_search", True))
        except Exception as e:
            logger.error(f"配置验证失败: {e}")

    @property
    def api_base_url(self):
        return f"http://localhost:{self.config['api_port']}"

class MCMODSearch:
    """搜索功能核心类"""
    SEARCH_TYPES = {
        "mod": "模组",
        "modpack": "整合包", 
        "item": "物品",
        "post": "教程"
    }

    def __init__(self, config: PluginConfig):
        self.config = config
        self.api_process = None

    async def start_api_server(self):
        """启动API服务器子进程"""
        try:
            api_path = os.path.join(os.path.dirname(__file__), "api", "mcmod_api.py")
            if os.path.exists(api_path):
                logger.info(f"启动API服务，端口: {self.config.config['api_port']}")
                self.api_process = subprocess.Popen(
                    ["python", api_path, str(self.config.config['api_port'])],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.path.dirname(api_path),
                    text=True
                )
                
                def check_process():
                    if self.api_process.poll() is None:
                        asyncio.get_event_loop().call_later(60, check_process)
                    elif self.api_process.returncode == 0:
                        logger.info("API服务启动成功")
                    else:
                        logger.error(f"API服务启动失败: {self.api_process.stderr.read()}")
                
                asyncio.get_event_loop().call_soon(check_process)
        except Exception as e:
            logger.error(f"启动API服务出错: {e}")

    async def search(self, search_type: str, query: str) -> dict:
        """执行搜索请求"""
        try:
            timeout = aiohttp.ClientTimeout(total=self.config.config['api_timeout'])
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self.config.api_base_url}/search?{search_type}={query}"
                ) as response:
                    response.raise_for_status()
                    return await response.json()
        except Exception as e:
            logger.error(f"搜索请求失败: {e}")
            return {"status": "error", "message": str(e)}

    def format_results(self, data: dict, search_type: str) -> str:
        """格式化搜索结果"""
        if data.get("status") != "success":
            return f"搜索失败: {data.get('message', '未知错误')}"
        
        results = data.get("results", [])
        if not results:
            return f"没有找到相关{self.SEARCH_TYPES.get(search_type, '')}结果"
        
        # 确定显示数量限制
        limit = self.config.config['max_multi_results'] if search_type == "all" else self.config.config['max_single_results']
        
        table = "| 类型 | 名称 | 链接 |\n|------|------|------|\n"
        
        if search_type == "all":
            parts = []
            for stype, stype_name in self.SEARCH_TYPES.items():
                if items := results.get(stype, []):
                    part = f"【{stype_name}】\n{table}"
                    for item in items[:limit]:
                        part += f"| {stype_name} | {item.get('name', '未知')[:50]} | {item.get('url', '#')} |\n"
                    if len(items) > limit:
                        part += f"...共{len(items)}条结果\n"
                    parts.append(part)
            return "\n".join(parts) if parts else "没有找到任何结果"
        else:
            for item in results[:limit]:
                table += f"| {self.SEARCH_TYPES.get(search_type, '未知')} | {item.get('name', '未知')[:50]} | {item.get('url', '#')} |\n"
            if len(results) > limit:
                table += f"...共{len(results)}条结果\n"
            return table

@register("MCMOD搜索插件", "mcmod", "MCMOD百科内容搜索", "2.0.0")
class MCMODSearchPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = PluginConfig(context)
        self.searcher = MCMODSearch(self.config)
        asyncio.create_task(self.searcher.start_api_server())

    @filter.command("查mod")
    async def search_mod(self, event: AstrMessageEvent, name: str):
        result = await self.searcher.search("mod", name)
        yield event.chain_result([Plain(self.searcher.format_results(result, "mod"))])

    @filter.command("查整合包")
    async def search_modpack(self, event: AstrMessageEvent, name: str):
        result = await self.searcher.search("modpack", name)
        yield event.chain_result([Plain(self.searcher.format_results(result, "modpack"))])

    @filter.command("查物品")
    async def search_item(self, event: AstrMessageEvent, name: str):
        result = await self.searcher.search("item", name)
        yield event.chain_result([Plain(self.searcher.format_results(result, "item"))])

    @filter.command("查教程")
    async def search_post(self, event: AstrMessageEvent, name: str):
        result = await self.searcher.search("post", name)
        yield event.chain_result([Plain(self.searcher.format_results(result, "post"))])

    @filter.command("mcmod搜索")
    async def search_all(self, event: AstrMessageEvent, name: str):
        if not self.config.config['enable_all_search']:
            yield event.chain_result([Plain("全搜索功能已被禁用")])
            return
            
        result = await self.searcher.search("all", name)
        yield event.chain_result([Plain(self.searcher.format_results(result, "all"))])

    async def terminate(self):
        if self.searcher.api_process:
            try:
                self.searcher.api_process.terminate()
                logger.info("已停止API服务")
            except Exception as e:
                logger.error(f"停止API服务出错: {e}")
