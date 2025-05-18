import aiohttp
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
        self.config = self._load_config()
        self._validate_config()

    def _load_config(self):
        """加载并转换配置类型"""
        raw_config = self.context.get_config()
        return {
            "api_port": int(raw_config.get("api_port", 15001)),
            "max_single_results": int(raw_config.get("max_single_results", 20)),
            "max_multi_results": int(raw_config.get("max_multi_results", 10)),
            "api_timeout": int(raw_config.get("api_timeout", 15)),
            "enable_all_search": self._to_bool(raw_config.get("enable_all_search", True))
        }

    def _to_bool(self, value):
        """安全转换为布尔值"""
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes', 't')

    def _validate_config(self):
        """验证并修正配置值"""
        self.config["api_port"] = max(1024, min(65535, self.config["api_port"]))
        self.config["max_single_results"] = max(1, min(50, self.config["max_single_results"]))
        self.config["max_multi_results"] = max(1, min(20, self.config["max_multi_results"]))
        self.config["api_timeout"] = max(5, min(30, self.config["api_timeout"]))

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
        self.api_ready = asyncio.Event()

    async def _log_stream(self, stream, log_level):
        """实时记录子进程输出"""
        while True:
            line = await stream.readline()
            if not line:
                break
            getattr(logger, log_level)(f"[API] {line.strip()}")

    async def _check_api_ready(self):
        """检查API是否就绪"""
        timeout = aiohttp.ClientTimeout(total=2)
        for _ in range(10):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{self.config.api_base_url}/status"):
                        return True
            except:
                await asyncio.sleep(1)
        return False

    async def start_api_server(self):
        """启动API服务器子进程"""
        try:
            api_path = os.path.join(os.path.dirname(__file__), "api", "mcmod_api.py")
            if not os.path.exists(api_path):
                logger.error(f"API脚本不存在: {api_path}")
                return

            self.api_process = await asyncio.create_subprocess_exec(
                "python", api_path, 
                str(self.config.config['api_port']),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=os.path.dirname(api_path)
            )

            asyncio.create_task(self._log_stream(self.api_process.stdout, "info"))
            asyncio.create_task(self._log_stream(self.api_process.stderr, "error"))

            if await self._check_api_ready():
                logger.info("API服务启动成功")
                self.api_ready.set()
            else:
                logger.error("API服务启动超时")
                await self._safe_terminate()

        except Exception as e:
            logger.error(f"启动API服务出错: {e}")
            await self._safe_terminate()

    async def _safe_terminate(self):
        """安全终止子进程"""
        if self.api_process:
            try:
                self.api_process.terminate()
                await asyncio.wait_for(self.api_process.wait(), timeout=3)
            except:
                try:
                    self.api_process.kill()
                except:
                    pass

    async def search(self, search_type: str, query: str) -> dict:
        """执行搜索请求"""
        if not self.api_ready.is_set():
            logger.warning("等待API服务就绪...")
            await self.api_ready.wait()

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
        
        limit = self.config.config['max_multi_results'] if search_type == "all" else self.config.config['max_single_results']
        
        table = "| 类型 | 名称 | 链接 |\n|------|------|------|\n"
        
        if search_type == "all":
            parts = []
            for stype, stype_name in self.SEARCH_TYPES.items():
                if items := results.get(stype, []):
                    part = f"【{stype_name}】\n{table}"
                    for item in items[:limit]:
                        part += f"| {stype_name} | {item.get('name', '未知')} | {item.get('url', '#')} |\n"
                    if len(items) > limit:
                        part += f"...共{len(items)}条结果\n"
                    parts.append(part)
            return "\n".join(parts) if parts else "没有找到任何结果"
        else:
            for item in results[:limit]:
                table += f"| {self.SEARCH_TYPES.get(search_type, '未知')} | {item.get('name', '未知')} | {item.get('url', '#')} |\n"
            if len(results) > limit:
                table += f"...共{len(results)}条结果\n"
            return table

@register("MCMOD搜索插件", "mcmod", "MCMOD百科内容搜索", "1.0.0")
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
        await self.searcher._safe_terminate()
        logger.info("插件已停止")
