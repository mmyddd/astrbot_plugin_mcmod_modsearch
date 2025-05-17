import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
from flask import Flask, jsonify, request
import threading

class MCMODSearchAPI:
    def __init__(self):
        self.seen_urls = set()
        self.app = Flask(__name__)
        self._setup_routes()
        
    def _setup_routes(self):
        @self.app.route('/search')
        def api_search():
            # 获取查询参数
            mod_query = request.args.get('mod')
            modpack_query = request.args.get('modpack')
            
            # 参数验证
            if not mod_query and not modpack_query:
                return jsonify({
                    "status": "error",
                    "message": "需要提供mod或modpack参数，例如: /search?mod=工业 或 /search?modpack=科技"
                }), 400
            
            try:
                # 根据参数类型进行搜索
                if mod_query:
                    result_type = "mods"
                    result_data = self._fetch_search_results(mod_query, search_mods=True)
                else:
                    result_type = "modpacks"
                    result_data = self._fetch_search_results(modpack_query, search_mods=False)
                
                return jsonify({
                    "status": "success",
                    "query": mod_query if mod_query else modpack_query,
                    "type": result_type,
                    "count": len(result_data),
                    "results": result_data
                })
                
            except requests.exceptions.RequestException as e:
                return jsonify({
                    "status": "error",
                    "message": f"请求mcmod百科失败: {str(e)}"
                }), 502
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "message": f"服务器错误: {str(e)}"
                }), 500

    def _fetch_search_results(self, keyword, search_mods=True):
        """获取并处理搜索结果
        :param search_mods: True搜索模组，False搜索整合包
        """
        self.seen_urls.clear()
        results = []
        
        response = requests.get(
            url="https://search.mcmod.cn/s",
            params={"key": keyword, "filter": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        for item in soup.find_all(class_='search-result'):
            for link in item.find_all('a', {'target': '_blank'}):
                raw_url = link.get('href', '')
                if not raw_url: continue
                
                full_url = self._normalize_url(raw_url)
                if full_url in self.seen_urls or self._need_filter(full_url):
                    continue
                
                # 根据搜索类型过滤结果
                if search_mods and "/class/" not in full_url:
                    continue
                if not search_mods and "/modpack/" not in full_url:
                    continue
                
                self.seen_urls.add(full_url)
                title = link.text.strip()[:40] or "未命名项目"
                results.append({
                    "name": title,
                    "url": full_url
                })
        
        return results

    def _normalize_url(self, url):
        """规范化URL"""
        if not url.startswith(('http://', 'https://')):
            return f"https://www.mcmod.cn{url}"
        return url

    def _need_filter(self, url):
        """检查URL是否需要过滤"""
        parsed = urlparse(url)
        if not parsed.netloc.endswith('mcmod.cn'):
            return True
        if re.search(r'mcmod\.cn//.*mcmod\.cn', url):
            return True
        if '/class/category/' in url:
            return True
        return False

    def run(self, host='0.0.0.0', port=15001):
        """启动API服务器"""
        print(f"\nmcmod搜索API服务已启动\n")
        print(f"模组搜索: http://{host}:{port}/search?mod=工业")
        print(f"整合包搜索: http://{host}:{port}/search?modpack=科技\n")
        self.app.run(host=host, port=port)

if __name__ == "__main__":
    try:
        from flask import Flask, jsonify, request
    except ImportError:
        print("请安装依赖：pip install flask requests beautifulsoup4")
        exit(1)
    
    api = MCMODSearchAPI()
    api.run()
