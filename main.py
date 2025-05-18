import aiohttp
import os
import asyncio
import subprocess
import sys
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

# ===== 固定配置 =====
API_PORT = 15001
API_TIMEOUT = 30  # 固定30秒超时
# ===================

class MCMODSearch:
    """搜索功能核心类"""
    SEARCH_TYPES = {
        "mod": "模组",
        "modpack": "整合包", 
        "item": "物品",
        "post": "教程"
    }

    def __init__(self):
        self.port = API_PORT
        self.api_process = None
        self.api_ready = asyncio.Event()

    @property
    def api_base_url(self):
        return f"http://localhost:{self.port}"

    async def _log_stream(self, stream, log_level):
        """实时记录子进程输出"""
        while True:
            line = await stream.readline()
            if not line:
                break
            logger.log(log_level, f"[API] {line.decode().strip()}")

    async def _check_api_ready(self):
        """检查API是否就绪"""
        timeout = aiohttp.ClientTimeout(total=2)
        for _ in range(10):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{self.api_base_url}/status"):
                        return True
            except Exception as e:
                logger.debug(f"API检查失败: {str(e)}")
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
                sys.executable, api_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.path.dirname(api_path)
            )

            asyncio.create_task(self._log_stream(self.api_process.stdout, "INFO"))
            asyncio.create_task(self._log_stream(self.api_process.stderr, "ERROR"))

            if await self._check_api_ready():
                logger.info(f"API服务启动成功，端口: {self.port}")
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
            finally:
                self.api_process = None

    async def search(self, search_type: str, query: str, page: int = 1) -> dict:
        """执行搜索请求"""
        if not self.api_ready.is_set():
            logger.warning("等待API服务就绪...")
            await self.api_ready.wait()

        try:
            timeout = aiohttp.ClientTimeout(total=API_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    f"{self.api_base_url}/search?{search_type}={query}&page={page}"
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    data["current_page"] = page  # 添加当前页码信息
                    return data
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
        
        current_page = data.get("current_page", 1)
        page_info = f"\n当前第 {current_page} 页"
        navigation = "\n使用【.查物品 扳手 2】查看第2页结果" if search_type == "item" else \
                   f"\n使用【.mcmod搜索 {data['query']} 2】查看第2页结果"
        
        if search_type == "all":
            parts = []
            for stype, stype_name in self.SEARCH_TYPES.items():
                if items := results.get(stype, []):
                    part = f"【{stype_name}】\n| 名称 | 链接 |\n|------|------|\n"
                    for item in items:
                        part += f"| {item.get('name', '未知')} | {item.get('url', '#')} |\n"
                    parts.append(part)
            return "\n".join(parts) + page_info + navigation if parts else "没有找到任何结果"
        else:
            output = "| 名称 | 链接 |\n|------|------|\n"
            for item in results:
                output += f"| {item.get('name', '未知')} | {item.get('url', '#')} |\n"
            return output + page_info + navigation

@register("MCMOD搜索插件", "mcmod", "MCMOD百科内容搜索", "1.0.0")
class MCMODSearchPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.searcher = MCMODSearch()
        asyncio.create_task(self.searcher.start_api_server())

    @filter.command("查mod")
    async def search_mod(self, event: AstrMessageEvent, name: str, page: int = 1):
        """查mod [名称] [页码]"""
        result = await self.searcher.search("mod", name, page)
        yield event.chain_result([Plain(self.searcher.format_results(result, "mod"))])

    @filter.command("查整合包")
    async def search_modpack(self, event: AstrMessageEvent, name: str, page: int = 1):
        """查整合包 [名称] [页码]"""
        result = await self.searcher.search("modpack", name, page)
        yield event.chain_result([Plain(self.searcher.format_results(result, "modpack"))])

    @filter.command("查物品")
    async def search_item(self, event: AstrMessageEvent, name: str, page: int = 1):
        """查物品 [名称] [页码]"""
        result = await self.searcher.search("item", name, page)
        yield event.chain_result([Plain(self.searcher.format_results(result, "item"))])

    @filter.command("查教程")
    async def search_post(self, event: AstrMessageEvent, name: str, page: int = 1):
        """查教程 [名称] [页码]"""
        result = await self.searcher.search("post", name, page)
        yield event.chain_result([Plain(self.searcher.format_results(result, "post"))])

    @filter.command("mcmod搜索")
    async def search_all(self, event: AstrMessageEvent, name: str, page: int = 1):
        """mcmod搜索 [名称] [页码]"""
        result = await self.searcher.search("all", name, page)
        yield event.chain_result([Plain(self.searcher.format_results(result, "all"))])

    async def terminate(self):
        await self.searcher._safe_terminate()
        logger.info("插件已停止")
