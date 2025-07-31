"""根据三个文件爬取对应的github源码, step1"""

import os
import re
import time
import base64
import requests
import json
from concurrent.futures import ThreadPoolExecutor



function = True
global_counts = {}
STAR_LIMIT = 0
MOUNT = 500
tokens = []
CUR = 0
def try1():
    """
    尝试目前是否达到了GitHub的爬取上限
    """
    base_url = 'https://api.github.com/search/code'
    headers = {
        "Authorization": f"Bearer {tokens[CUR]}",
        "Accept": "application/vnd.github.v3+json",
    }
    params ={
            "q": '"pandas.core.dtypes.cast.infer_dtype_from_scalar" language:Python',
            "per_page": 100,
            "page": 1,
        }
    while True:
        try: 
            response = requests.get(base_url, headers=headers, params=params)
            break
        except:
            continue
    if response.status_code == 200:
        return True
    

def generate_api_patterns(api_name):
    """
    为给定的API名称生成所有可能的匹配模式
    例如对于 'torch.nn.Linear':
    1. 直接匹配: 'torch.nn.Linear'
    2. import匹配: 'import torch.nn as ' + '*.Linear'  # *代表任意别名
    3. from匹配: 'from torch import nn' + 'nn.Linear'
    """
    patterns = []
    # directly match
    patterns.append(api_name)
    
    # split match
    parts = api_name.split('.')
    
    for i in range(1, len(parts)):
        # 2. import as 
        prefix = '.'.join(parts[:i])
        suffix = '.'.join(parts[i:])
        import_pattern = f'import {prefix} as'  # without alias
        usage_pattern = '.'+suffix  # only the suffix part
        patterns.extend([import_pattern, usage_pattern])
        
        # 3. from import 
        from_prefix = '.'.join(parts[:i])
        from_import = parts[i]
        from_suffix = '.'.join(parts[i+1:]) if i+1 < len(parts) else ''
        from_pattern = f'from {from_prefix} import {from_import}'
        if from_suffix:
            usage_pattern = f'.{from_suffix}'
        else:
            usage_pattern = from_import
        patterns.extend([from_pattern, usage_pattern])
    
    return patterns


def fetch_repository_details(repo_api_url):
    global CUR
    """Fetch repository details such as stars and last updated time."""
    while True:
        while True:
            try:
                response = requests.get(repo_api_url, headers={"Authorization": f"Bearer {tokens[CUR]}"})
                break
            except:
                continue
        if response.status_code == 200:
            break
        else:
            CUR += 1
            CUR %= len(tokens)
            if CUR == 0:
                while True:
                    if try1(): break
                    else: 
                        print("\nwaiting 100s\n")
                        time.sleep(100)
            
    if response.status_code == 200:
        repo_data = response.json()
        stars = repo_data.get("stargazers_count", 0)
        last_updated = repo_data.get("updated_at", "Unknown")
    else:
        stars = 0
        last_updated = "Unknown"
    return stars, last_updated


def fetch_file_content(file_url):
    global CUR
    """Fetch file content from GitHub API."""
    while True:
        while True:
            try:
                response = requests.get(file_url, headers={"Authorization": f"Bearer {tokens[CUR]}"})
                break
            except:
                continue
        if response.status_code == 200:
            break
        else:
            CUR += 1
            CUR %= len(tokens)
            if CUR == 0:
                while True:
                    if try1(): break
                    else: 
                        print("\nwaiting 100s\n")
                        time.sleep(100)
    if response.status_code == 200:
        file_data = response.json()
        encoded_content = file_data.get("content", "")
        try:
            code_content = base64.b64decode(encoded_content).decode("utf-8") if encoded_content else ""
        except Exception as e:
            print(f"Error decoding file content: {e}")
            code_content = ""
    else:
        code_content = ""
    return code_content

def check_api_usage(code_content, patterns):
    """
    检查代码中是否包含API的任何使用模式
    需要检查import语句和实际使用
    支持任意别名的导入匹配
    """
    if not code_content:
        return False
        
    # 将代码分割成行
    lines = code_content.split('\n')
    
    # 将模式分组为不同类型
    import_as_patterns = [p for p in patterns if p.startswith('import') and 'as' in p]
    from_import_patterns = [p for p in patterns if p.startswith('from')]
    usage_patterns = [p for p in patterns if not p.startswith(('import', 'from'))]
    
    # 对于直接匹配模式（第一个模式），只需要找到一个就可以
    found_direct = any(re.search(rf'\b{re.escape(patterns[0])}\b', line) 
                      for line in lines)
    
    if found_direct:
        return True
    
    # 检查 from import 模式
    found_from_import = False
    for from_pattern in from_import_patterns:
        if any(re.search(rf'\b{re.escape(from_pattern)}\b', line) for line in lines):
            found_from_import = True
            break
            
    if found_from_import:
        # 如果找到了from import语句，检查对应的使用模式
        for usage_pattern in usage_patterns:
            if any(re.search(rf'\b{re.escape(usage_pattern)}\b', line) for line in lines):
                return True
    
    # 检查 import as 模式
    # 首先找到所有import as语句
    import_lines = [line for line in lines if any(line.startswith(pattern.split(' as')[0]) 
                   and 'as' in line for pattern in import_as_patterns)]
    
    for import_line in import_lines:
        # 从import语句中提取别名
        match = re.search(r'import\s+(.+)\s+as\s+(\w+)', import_line)
        if match:
            imported_path, alias = match.groups()
            # 检查是否有对应的使用模式
            for usage_pattern in usage_patterns:
                # 构建实际使用模式（使用提取的别名）
                actual_usage = f'{alias}.{usage_pattern}'
                if any(re.search(rf'\b{re.escape(actual_usage)}\b', line) for line in lines):
                    return True
    
    return False


def process_item_for_parse(item, api_patterns):
    """Process a single item to extract repository and file details."""
    repo_name = item["repository"]["full_name"]
    repo_url = item["repository"]["html_url"]
    repo_api_url = item["repository"]["url"]
    file_html_url = repo_url + '/' + item["path"]

    stars, last_updated = fetch_repository_details(repo_api_url)
    # if stars < STAR_LIMIT:
    #     return None

    file_url = item["url"]
    code_content = fetch_file_content(file_url)
    
    if code_content:
        return {
            "code": code_content,
            "repo_link": repo_url,
            "file_url": file_html_url,
            "last_updated": last_updated,
            "stars": stars
        }
    return None


def parse_results(data, api_patterns,m):
    """Parse API response and extract code snippets and metadata."""
    code_results = []
    items = data.get("items", [])

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_item_for_parse, item, api_patterns) 
                  for item in items]

        for future in futures:
            if len(code_results) >= m:
                break

            result = future.result()
            if result:
                code_results.append(result)

    return code_results


def save_code_snippets(api_name, code_snippets, root, api_tail = None):
    """Save code snippets to files in the API-specific directory."""
    if function:
        file_path = os.path.join(root, f"{api_name.replace('.', '-')}-__init__.jsonl")
    else:
        file_path = os.path.join(root, f"{api_name.replace('.', '-')}-{api_tail}.jsonl")
    if len(code_snippets) == 0:
        return
    with open(file_path, "w", encoding="utf-8") as f:
        for snippet in code_snippets:
            json_line = {
                "repository": snippet["repo_link"],
                "url": snippet["file_url"],
                "last_updated": snippet["last_updated"],
                "stars": snippet["stars"],
                "content": snippet["code"]
            }
            f.write(f"{json.dumps(json_line)}\n")


def fetch_code_snippets(api_patterns, page, api_tail = None):
    """
    api_patterns: patterns split from the whole api_path
    page: which page to crawl from github
    api_tail: for method api, it means the last segment of the api_path; and None for initial api
    """
    global CUR, global_counts
    """Fetch code snippets using GitHub API for each pattern individually."""
    base_url = "https://api.github.com/search/code"
    headers = {
        "Authorization": f"Bearer {tokens[CUR]}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # 1. 直接匹配模式
    direct_pattern = api_patterns[0]
    
    # 2. 提取import as模式和对应的使用模式对
    import_as_pairs = []
    import_as_patterns = [api_patterns[i] for i in range(1, len(api_patterns), 2) if api_patterns[i].startswith(('import'))]
    usage_patterns = [api_patterns[i] for i in range(2, len(api_patterns), 2) if api_patterns[i-1].startswith(('import'))]
    for i in range(len(import_as_patterns)):
        import_as_pairs.append((import_as_patterns[i], usage_patterns[i]))
            
    # 3. 提取from import模式和对应的使用模式对
    from_pairs = []
    from_patterns = [api_patterns[i] for i in range(1, len(api_patterns), 2) if api_patterns[i].startswith(('from'))]
    usage_patterns = [api_patterns[i] for i in range(2, len(api_patterns), 2) if api_patterns[i-1].startswith(('from'))]
    for i in range(len(from_patterns)):
        from_pairs.append((from_patterns[i], usage_patterns[i]))
    
    # 所有查询模式
    all_queries = []
    # 添加直接匹配的查询
    if function:
        all_queries.append(f'"{direct_pattern}" language:Python')
    else:
        all_queries.append(f'"{direct_pattern}" ".{api_tail}" language:Python')
    # 添加import as模式的查询
    for import_pattern, usage_pattern in import_as_pairs:
        if function:
            all_queries.append(f'"{import_pattern}" "{usage_pattern}" language:Python')
        else:
            all_queries.append(f'"{import_pattern}" "{usage_pattern}" ".{api_tail}" language:Python')
    
    # 添加from import模式的查询
    for from_pattern, usage_pattern in from_pairs:
        if function:
            all_queries.append(f'"{from_pattern}" "{usage_pattern}" language:Python')
        else:
            all_queries.append(f'"{from_pattern}" "{usage_pattern}" ".{api_tail}" language:Python')
    
    # 对每个查询模式分别进行搜索
    all_results = {'total_count': 0, 'items': []}
    
    for query in all_queries:
        params = {
            "q": query,
            "per_page": 100,
            "page": page,
        }
        
        while True:
            while True:
                try:
                    response = requests.get(base_url, headers=headers, params=params)
                    break
                except:
                    continue
            if response.status_code == 200:
                break
            else:
                CUR += 1
                CUR %= len(tokens)
                if CUR == 0:
                    while True:
                        if try1(): break
                        else: 
                            print("\nwaiting 100s\n")
                            time.sleep(100)
                headers['Authorization'] = f"Bearer {tokens[CUR]}"
        if response.status_code == 200:
            result = response.json()
            # 合并结果
            all_results['total_count'] += result.get('total_count', 0)
            all_results['items'].extend(result.get('items', []))
            if all_results['total_count'] > MOUNT:
                break
        else:
            print(f"Failed to fetch for query {query}: {response.status_code}")

    global_counts.setdefault(api_patterns[0] + (api_tail or ""), 0)
    global_counts[api_patterns[0] + (api_tail or "")] += all_results["total_count"]
    return all_results

def repo_crawler(api_list, root, config, m=5):
    """Main function to crawl and save API usage examples."""
    global tokens
    tokens = config.token
    os.makedirs(root, exist_ok=True)
    
    for api in api_list:
        print(f"Processing API: {api}")
        api_tail = ""
        if not function:# 如果是方法函数，需要提取出构造函数字段
            api_head, api_tail = api.rsplit('.', 1)
            api = api_head  # remove the last part
            # 生成所有可能的匹配模式
        api_patterns = generate_api_patterns(api)
        print(f"Generated {len(api_patterns)//2+1} patterns for matching")
        
        page = 1
        total_snippets = []
        
        while len(total_snippets) < m:
            data = fetch_code_snippets(api_patterns, page, api_tail)
            if not data or len(data['items']) == 0:
                break
                
            snippets = parse_results(data, api_patterns,
                                   min(m - len(total_snippets), len(data['items'])))
            
            # 过滤掉None结果
            snippets = [s for s in snippets if s is not None]
            total_snippets.extend(snippets)
            
            # 如果已经达到目标数量，就退出
            if len(total_snippets) >= m:
                break
                
            page += 1
            
        # 如果收集到的snippets超过了需要的数量，只保留前m个
        total_snippets = total_snippets[:min(m, len(total_snippets))]
        save_code_snippets(api, total_snippets, root, api_tail)
        print(f"Saved {len(total_snippets)} snippets for API: {api}")
        

        
if __name__ == "__main__":
    import re

    file_path = ["method.json", "init.json", "function.json"]
    
    for function, path in enumerate(file_path):
        with open(path, 'r') as file:
            content = json.load(file)
        api_names = []
        for i in content.keys():
            api_names.append(i.split(".__init__")[0])
        roots = ['apis_method', 'apis_init', 'apis_function']
        repo_crawler(api_names, roots[function], m=MOUNT)
        
    with open("global_counts.json", "w", encoding="utf-8") as f:
        json.dump(global_counts, f, ensure_ascii=False, indent=4)