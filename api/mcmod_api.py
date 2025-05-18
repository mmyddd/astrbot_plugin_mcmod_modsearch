import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
from aiohttp import web
import asyncio
from typing import Dict, List, Optional, Literal
import sys

# ===== 配置区域 =====
PORT = 15001  # 在此修改API服务端口
# ===================

class MCMODSearchAPI:
    BASE_URL = "https://search.mcmod.cn/s"
    DOMAIN = "mcmod.cn"
    USER_AGENT = "Mozilla/5.0"
    TIMEOUT = aiohttp.ClientTimeout(total=15)
    
    TYPE_PATTERNS = {
        "mod": "/class/",
        "modpack": "/modpack/",
        "item": "/item/",
        "post": "/post/"
    }
    
    SearchType = Literal["mod", "modpack", "item", "post", "all"]
    
    def __init__(self):
        self.port = PORT
        self.seen_urls = set()
        self.app = web.Application()
        self._setup_routes()
        
    def _setup_routes(self):
        self.app.router.add_get('/search', self.handle_search)
        self.app.router.add_get('/status', self.handle_status)
        
    async def handle_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "running",
            "port": self.port,
            "supported_types": list(self.TYPE_PATTERNS.keys())
        })

    async def handle_search(self, request: web.Request) -> web.Response:
        try:                    
            query, search_type, page = await self._get_query_params(request)
            if not query:
                return self._error_response("需要提供查询参数", 400)
                
            results = await (self._fetch_all_results(query, page) if search_type == "all" \
                     else self._fetch_type_results(query, search_type, page))
            
            return self._success_response(query, results, search_type, page)
            
        except aiohttp.ClientError as e:
            return self._error_response(f"请求失败: {str(e)}", 502)
        except Exception as e:
            return self._error_response(f"服务器错误: {str(e)}", 500)

    async def _get_query_params(self, request: web.Request) -> tuple[str, str, int]:
        try:
            page = int(request.query.get("page", "1"))
        except ValueError:
            page = 1
            
        for param in (*self.TYPE_PATTERNS, "all"):
            if param in request.query:
                return request.query[param], param, page
        return "", "mod", page

    async def _fetch_all_results(self, query: str, page: int = 1) -> Dict[str, List[Dict]]:
        html = await self._fetch_search_page(query, page)
        return self._parse_results(html, group_by_type=True)

    async def _fetch_type_results(self, query: str, search_type: str, page: int = 1) -> List[Dict]:
        html = await self._fetch_search_page(query, page)
        return self._parse_results(html, target_type=search_type)

    async def _fetch_search_page(self, query: str, page: int = 1) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.BASE_URL,
                params={"key": query, "filter": 0, "page": page},
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.text()

    def _parse_results(self, html: str, 
                      group_by_type: bool = False,
                      target_type: Optional[str] = None) -> Dict[str, List[Dict]] | List[Dict]:
        self.seen_urls.clear()
        soup = BeautifulSoup(html, 'html.parser')
        results = {t: [] for t in self.TYPE_PATTERNS} if group_by_type else []
        
        for item in soup.find_all(class_='search-result'):
            for link in item.find_all('a', {'target': '_blank'}):
                if result := self._process_link(link):
                    type_, data = result
                    if group_by_type:
                        results[type_].append(data)
                    elif type_ == target_type:
                        results.append(data)
        
        return results

    def _process_link(self, link) -> Optional[tuple[str, Dict]]:
        if not (url := self._normalize_url(link.get('href', ''))):
            return None
            
        if url in self.seen_urls or self._should_filter(url):
            return None
            
        for type_, pattern in self.TYPE_PATTERNS.items():
            if pattern in url:
                self.seen_urls.add(url)
                name = link.get_text(strip=True)
                return (type_, {
                    "name": name,
                    "url": url
                })
        return None

    def _normalize_url(self, url: str) -> str:
        return f"https://www.mcmod.cn{url}" if url and not url.startswith(('http://', 'https://')) else url

    def _should_filter(self, url: str) -> bool:
        parsed = urlparse(url)
        return (not parsed.netloc.endswith(self.DOMAIN)) or \
                bool(re.search(r'mcmod\.cn//.*mcmod\.cn', url)) or \
                '/class/category/' in url

    def _success_response(self, query: str, results: Dict | List, search_type: str, page: int) -> web.Response:
        data = {
            "status": "success",
            "query": query,
            "type": search_type,
            "page": page,
            "results": results
        }
        
        if search_type == "all":
            data["count"] = sum(len(r) for r in results.values())
        else:
            data["count"] = len(results)
            
        return web.json_response(data)

    def _error_response(self, message: str, status: int) -> web.Response:
        return web.json_response({
            "status": "error",
            "message": message
        }, status=status)

    async def run(self, host: str = '0.0.0.0') -> None:
        print(f"\nMCMOD搜索API服务已启动")
        print(f"端口: {self.port}")
        print(f"访问地址:")
        for t in self.TYPE_PATTERNS:
            print(f"- {t}搜索: http://{host}:{self.port}/search?{t}=名称&page=页码")
        print(f"- 全搜索: http://{host}:{self.port}/search?all=名称&page=页码")
        print(f"- 健康检查: http://{host}:{self.port}/status\n")
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, self.port)
        await site.start()
        
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    if not 1024 <= PORT <= 65535:
        print("错误：端口必须在1024-65535之间")
        sys.exit(1)
    
    try:
        api = MCMODSearchAPI()
        asyncio.run(api.run())
    except KeyboardInterrupt:
        print("\n服务器已停止")
