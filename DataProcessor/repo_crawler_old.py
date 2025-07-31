import os
import re
import time
import base64
import requests
import json
from concurrent.futures import ThreadPoolExecutor

from hparams.get_config import get_dataset_config




def fetch_repository_details(repo_api_url, token):
    """Fetch repository details such as stars and last updated time."""
    response = requests.get(repo_api_url, headers={"Authorization": f"Bearer {token}"})
    if response.status_code == 200:
        repo_data = response.json()
        stars = repo_data.get("stargazers_count", 0)
        last_updated = repo_data.get("updated_at", "Unknown")
    else:
        stars = 0
        last_updated = "Unknown"
    return stars, last_updated


def fetch_file_content(file_url, token):
    """Fetch file content from GitHub API."""
    response = requests.get(file_url, headers={"Authorization": f"Bearer {token}"})
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


def process_item_for_parse(item, stars_limit, time_limit):
    """Process a single item to extract repository and file details."""
    repo_name = item["repository"]["full_name"]
    repo_url = item["repository"]["html_url"]
    repo_api_url = item["repository"]["url"]  # API URL for repository details
    apifile_html_url = repo_url + '/' + item["path"]

    stars, last_updated = fetch_repository_details(repo_api_url, config.token[1])
    if not stars_limit == 'None' and stars < stars_limit:
        return None
    if not time_limit == 'None' and last_updated != "Unknown" and last_updated > time_limit:
        return None
    file_url = item["url"]
    code_content = fetch_file_content(file_url, config.token[2])

    if code_content:
        return {
            "code": code_content,
            "repo_link": repo_url,
            "file_url": apifile_html_url,
            "last_updated": last_updated,
            "stars": stars
        }
    return None


def parse_results(data, m):
    """Parse API response and extract code snippets and metadata."""
    code_results = []
    items = data.get("items", [])

    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_item_for_parse, item, config.stars_limit, config.time_limit) for item in items]

        for future in futures:
            if len(code_results) >= m:
                break

            result = future.result()
            if result:
                code_results.append(result)

    return code_results


def save_code_snippets(api_name, code_snippets, root_dir):
    """Save code snippets to files in the API-specific directory."""
    file_path = os.path.join(root_dir, f"{api_name}.jsonl")
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
 

def fetch_code_snippets(api, page, token):
    """Fetch code snippets using GitHub API."""
    base_url = "https://api.github.com/search/code"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    params = {
        "q": f"{api} language:Python",
        "per_page": 200,
        "page": page,
    }
    response = requests.get(base_url, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to fetch page {page} for API {api}: {response.status_code}")
        return None
    
             
def repo_crawler(config, api_list, mode):
    # token, m
    """Main function to crawl and save API usage examples."""
    for api in api_list:
        print(f"Processing API: {api}")
        if not os.path.exists(api):
            os.makedirs(api)
        page = 1
        total_snippets = []
        while len(total_snippets) < config.max_repos:
            data = fetch_code_snippets(api, page, config.token[0])
            if not data:
                break
            snippets = parse_results(data, config.max_repos - len(total_snippets))
            total_snippets.extend(snippets)
            page += 1
            time.sleep(1)  # Avoid hitting rate limits
        save_code_snippets(api, total_snippets, os.path.join(config.raw_data_dir, mode))
        print(f"Saved {len(total_snippets)} snippets for API: {api}")




if __name__ == "__main__":
    
    api_list = [
        "torch.autograd.gradcheck",
        "torch.optim.Adadelta",
        "torch.optim.Adagrad",
        "torch.optim.RMSprop",
        "torch.optim.SGD"
    ]
    
    config = get_dataset_config()
    repo_crawler(api_list, config)
