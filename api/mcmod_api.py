import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
from aiohttp import web
import asyncio

class MCMODSearchAPI:
    BASE_URL = "https://search.mcmod.cn/s"
    DOMAIN = "mcmod.cn"
    USER_AGENT = "Mozilla/5.0"
    TIMEOUT = aiohttp.ClientTimeout(total=15)
    
    def __init__(self):
        self.seen_urls = set()
        self.app = web.Application()
        self.app.router.add_get('/search', self.handle_search)
        
    async def handle_search(self, request: web.Request):
        query = request.query.get('mod') or request.query.get('modpack')
        if not query:
            return self.error_response("需要提供mod或modpack参数", 400)
        
        try:
            is_mod_search = 'mod' in request.query
            results = await self.fetch_results(query, is_mod_search)
            return self.success_response(query, results, is_mod_search)
        except aiohttp.ClientError as e:
            return self.error_response(f"请求mcmod百科失败: {str(e)}", 502)
        except Exception as e:
            return self.error_response(f"服务器错误: {str(e)}", 500)

    async def fetch_results(self, keyword, is_mod_search):
        self.seen_urls.clear()
        html = await self.fetch_search_page(keyword)
        return self.parse_results(html, is_mod_search)
    
    async def fetch_search_page(self, keyword):
        async with aiohttp.ClientSession() as session:
            async with session.get(
                self.BASE_URL,
                params={"key": keyword, "filter": 0},
                headers={"User-Agent": self.USER_AGENT},
                timeout=self.TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.text()
    
    def parse_results(self, html, is_mod_search):
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        
        for item in soup.find_all(class_='search-result'):
            for link in item.find_all('a', {'target': '_blank'}):
                if url := self.process_link(link, is_mod_search):
                    results.append(url)
        
        return results
    
    def process_link(self, link, is_mod_search):
        if not (raw_url := link.get('href', '')):
            return None
            
        full_url = self.normalize_url(raw_url)
        if (full_url in self.seen_urls or 
            self.should_filter(full_url) or 
            not self.is_correct_type(full_url, is_mod_search)):
            return None
            
        self.seen_urls.add(full_url)
        return {
            "name": link.text.strip()[:40] or "未命名项目",
            "url": full_url
        }
    
    def normalize_url(self, url):
        return f"https://www.mcmod.cn{url}" if not url.startswith(('http://', 'https://')) else url
    
    def should_filter(self, url):
        parsed = urlparse(url)
        return (
            not parsed.netloc.endswith(self.DOMAIN) or
            re.search(r'mcmod\.cn//.*mcmod\.cn', url) or
            '/class/category/' in url
        )
    
    def is_correct_type(self, url, is_mod_search):
        return ("/class/" in url if is_mod_search else "/modpack/" in url)
    
    def success_response(self, query, results, is_mod_search):
        return web.json_response({
            "status": "success",
            "query": query,
            "type": "mods" if is_mod_search else "modpacks",
            "count": len(results),
            "results": results
        })
    
    def error_response(self, message, status):
        return web.json_response({
            "status": "error",
            "message": message
        }, status=status)
    
    async def run(self, host='0.0.0.0', port=15001):
        print(f"\nmcmod搜索API服务已启动\n")
        print(f"模组搜索: http://{host}:{port}/search?mod=工业")
        print(f"整合包搜索: http://{host}:{port}/search?modpack=科技\n")
        
        runner = web.AppRunner(self.app)
        await runner.setup()
        await web.TCPSite(runner, host, port).start()
        
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(MCMODSearchAPI().run())
    except (ImportError, KeyboardInterrupt) as e:
        print("\n服务器已停止" if isinstance(e, KeyboardInterrupt) else "请安装依赖：pip install aiohttp beautifulsoup4")
