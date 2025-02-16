import os
import re
import json
from tqdm import tqdm
from openai import OpenAI
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

from hparams.get_config import get_prompt_config, get_dataset_config




MAX_RETRIES = 5

config = get_dataset_config()
prompt_dict = get_prompt_config()

input_prompt_template = """
Latest API Signature: {}
Oudated API Signature: {}
---\nContext:\n{}
---\nCalling Statement:\n{}
---\nSuffix:\n{}
---\nLatest API Docstring: {}
---\nOutdated API Docstring: {}
"""


def get_updated_code(item, updated_api, outdated_api):
    client = OpenAI(api_key=config.llm_api, base_url=config.llm_url)
        
    messages = [
        {"role": "system", "content": prompt_dict['invocation_synthesis']['system']},
        {"role": "user", "content": prompt_dict['invocation_synthesis']['user'] + input_prompt_template.format(
            updated_api['signature'],
            outdated_api['signature'],
            item['context'],
            item['target_seq'],
            item['suffix'],
            updated_api['doc'],
            outdated_api['doc'])
        }
    ]
    response = client.chat.completions.create(
        model=config.llm_name,  
        messages=messages,
        stream=False,
        temperature=0.7,
        max_tokens=500
    )
    answer = response.choices[0].message.content
    pattern_updated = r'Latest answer:\n```python\n([\s\S]+?)\n```'
    pattern_outdated = r'Outdated answer:\n```python\n([\s\S]+?)\n```'
    try:
        code = {
            'updated': re.findall(pattern_updated, answer, re.DOTALL)[0],
            'outdated': re.findall(pattern_outdated, answer, re.DOTALL)[0]
        }
    except:
        code = get_updated_code(item, updated_api, outdated_api)
    return code


def process_meta_item(item, updated_api, outdated_api):
    code = get_updated_code(item, updated_api, outdated_api)
    item['updated_code'] = code['updated']
    item['outdated_code'] = code['outdated']
    del item['target_seq']
    return item


def process_meta_file(filename, updated_apis_dict, outdated_apis_dict):
    with open(filename, 'r', encoding='utf-8') as f:
        items = [json.loads(line) for line in f]
    
    api_name = item[0]['API_path'].split('(')[0]
    updated_api = updated_apis_dict[api_name]
    outdated_api = outdated_apis_dict[api_name]
    
    new_items = []
    with ThreadPoolExecutor(max_workers=config.work_nums) as executor:
        futures = [executor.submit(process_meta_item, 
                                   item,
                                   updated_api,
                                   outdated_api) for item in items]
        for future in as_completed(futures):
            new_item = future.result()
            new_items.append(new_item)
    
    temp_filename = f"{filename}.tmp"
    with open(temp_filename, 'w', encoding='utf-8') as f:
        for item in new_items:
            f.write(json.dumps(item) + '\n')
    os.replace(temp_filename, filename)


def synthesis_metadata(data_dir,               
                       updated_apis_dict,       
                       outdated_apis_dict
                       ):
    file_list = []
    for root, _, fnames in os.walk(data_dir):
        for fname in fnames:
            file_list.append(os.path.join(root, fname))
            
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        executor.map(process_meta_file, file_list, updated_apis_dict, outdated_apis_dict)


def cct_construct(updated_apis_dict, outdated_apis_dict):
    file_list = []
    for root, _, fnames in os.walk(config.data_dir):
        for fname in fnames:
            file_list.append(os.path.join(root, fname))
            
    for fp in tqdm(file_list):
        with open(fp, 'r') as f:
            items = [json.loads(l) for l in f]
        new_items = []
        for item in items:
            new_item = {
                'API_path': item['API_path'],
                'question': item['context'],
                'answer': item['updated_code'],
                'updated_signature': updated_apis_dict[item['API_path']]['signature'],
                'outdated_signature': outdated_apis_dict[item['API_path']]['signature'],
                
                'repository': item['respository'],
                'url': item['url'],
                'last_updated': item['last_updated'],
                'stars': item['stars']
            }
            new_items.append(new_item)
        
        tmp_file = fp.replace(config.data_dir, config.benchmark_dir)
        with open(tmp_file, 'w') as f:
            for item in new_items:
                f.write(json.dumps(item) + '\n')
        os.replace(tmp_file, fp)
        
    print('CCT Benchmark Constructing Successfully!')
    

def ect_construct(updated_apis_dict, outdated_apis_dict):
    file_list = []
    for root, _, fnames in os.walk(config.data_dir):
        for fname in fnames:
            file_list.append(os.path.join(root, fname))
            
    for fp in tqdm(file_list):
        with open(fp, 'r') as f:
            items = [json.loads(l) for l in f]
        new_items = []
        for item in items:
            new_item = {
                'API_path': item['API_path'],
                'question': item['context'] + '\n' + item['outdated_code'],
                'answer': item['updated_code'],
                'updated_signature': updated_apis_dict[item['API_path']]['signature'],
                'outdated_signature': outdated_apis_dict[item['API_path']]['signature'],
                
                'repository': item['respository'],
                'url': item['url'],
                'last_updated': item['last_updated'],
                'stars': item['stars']
            }
            new_items.append(new_item)
        
        tmp_file = fp.replace(config.data_dir, config.benchmark_dir)
        with open(tmp_file, 'w') as f:
            for item in new_items:
                f.write(json.dumps(item) + '\n')
    
    print('ECT Benchmark Constructing Successfully!')    


def mcq_construct(updated_apis_dict, outdated_apis_dict):
    
    print('MCQ Benchmark Constructing Successfully!')    


