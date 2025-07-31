import ast
import json
import os
import re
import yaml
import importlib
import textwrap
from collections import deque
from datasets import load_dataset
from collections import defaultdict
from multiprocessing import Pool, cpu_count
from tqdm import tqdm
from datetime import datetime

from hparams.get_config import get_dataset_config, Config
from util.path import jsonl_file_search
from util.prompt_prosessor import sample_processor




def get_code_via_node(code, node):
    lines = code.splitlines()
    return textwrap.dedent('\n'.join(lines[node.lineno - 1: node.end_lineno]))


def alias_extractor(lib, tree):
    '''
    Extracts all aliases of a specified library from an AST tree.

    This function scans through an abstract syntax tree (AST) to identify all instances where 
    the specified library (or its submodules) is imported with an alias. 

    Args:
        tree (ast.AST): An AST representing the code snippet to be analyzed.
        lib (str): The name of the library to search for in the imports. It will find both direct 
            imports and submodules, as well as any associated aliases.

    Returns:
        list: A list containing all unique aliases used for the specified library.
        dict: A dictionary mapping each alias to its full module path. For example, if 
            `lib.submodule` is imported as `alias`, the dictionary will contain `{'alias': 'lib.submodule'}`.
    '''
    aliases = set()     # set of aliases for lib
    aliases_dict = {}   # a dict to record the full name of aliases

    for node in ast.walk(tree):
        # processing 'import ... as ...'
        if isinstance(node, ast.Import):
            for alias in node.names:
                # import libA, libB
                # import lib as alias_lib
                # import lib.sub_lib as alias_sub
                if alias.name == lib or alias.name.startswith(lib):
                    alias_name = alias.asname or alias.name.split('.')[-1]
                    aliases.add(alias_name)
                    aliases_dict[alias_name] = alias.name

        # processing 'from ... import'
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0].startswith(lib):
                for alias in node.names:
                    alias_name = alias.asname or alias.name.split('.')[-1]
                    aliases.add(alias_name)
                    aliases_dict[alias_name] = node.module + '.' + alias.name
                    
    if not lib in aliases_dict.keys():
        aliases.add(lib)
        aliases_dict[lib] = lib
    return list(aliases), aliases_dict


def get_full_api_name(node, alias_mapping, root_lib):
    """
    get full name of API from ast node, i.e., torch.nn.functional.softmax
    """
    attrs = []
    current = node
    while isinstance(current, ast.Attribute):
        attrs.insert(0, current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        attrs.insert(0, current.id)
        # 
        first_name = attrs[0]
        if first_name in alias_mapping:
            full_path = alias_mapping[first_name]
            if len(attrs) == 1:
                return full_path
            else:
                return f"{full_path}." + ".".join(attrs[1:])
        elif first_name == root_lib:
            return ".".join(attrs)
    return None


def get_import_statement(code):
    import_parttern = r'^\s*(import\s+\S+(\s+as\s+\S+)?|\s*from\s+\S+\s+import\s+(\S+(\s+as\s+\S+)?)?(\s*,\s*\S+(\s+as\s+\S+)?)*)\s*$'
    matches = list(set(re.findall(import_parttern, code, re.MULTILINE)))
    import_statements = ''
    
    for item in matches:
      import_statements += item[0] + '\n'
    return import_statements


def find_api_calling_functions(root_lib, sample, lib=None, lib_dict=None):
    '''
    Finds and extracts code snippets where specific APIs of a given library are called.

    This function takes the name of a library and a sample of code, identifies functions 
    in the code that call APIs from the specified library, and extracts these code snippets 
    along with relevant metadata. It returns a list of dictionary entries where each entry 
    corresponds to an API call and contains detailed information about the call.
    '''
    code = sample['content']
    # print(code)
    calling_code = []
    try:
        tree = ast.parse(code)
    except Exception as e:
        # print(e)
        return []

    import_statements = get_import_statement(code)
    if lib is None and lib_dict is None:
        lib, lib_dict = alias_extractor(root_lib, tree)
    
    visited_api_name = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub_node in ast.walk(node):
                if isinstance(sub_node, ast.Call):
                    api_name = get_full_api_name(sub_node.func, lib_dict, root_lib)
                    # not from target library
                    if api_name is None:
                        continue
                    base_alias = api_name.split('.')[0]
                    if base_alias not in lib_dict:
                        continue

                    # if base_alias in lib:
                    full_api_name = api_name.replace(base_alias, lib_dict[base_alias], 1)
                    if full_api_name not in visited_api_name:
                        visited_api_name.add(full_api_name)
                    else:
                        continue
                    api_code = get_code_via_node(code, node)
                    item = {
                        'API_path': full_api_name,
                        'start_line_no': sub_node.lineno - node.lineno + 1,
                        'end_line_no': sub_node.end_lineno - node.lineno + 1,
                        'import': import_statements,
                        'code': api_code,
                    }
                    try:
                        _, tgt_seq, api_name, context, imports, suffix = sample_processor(item)
                    except:
                        continue   
                                 
                    calling_code.append({
                        'API_path': full_api_name,
                        'repository': sample['repository'], 
                        'url': sample['url'],
                        'last_updated': sample['last_updated'].strftime("%Y-%m-%d %H:%M:%S"),
                        'stars': sample['stars'],
                        
                        'import': import_statements,
                        'context': context,
                        'target_seq': tgt_seq,
                        'suffix': suffix,
                    })
    
    # process main code
    script_code = ''
    script_nodes = [
        node for node in tree.body
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
    ]
    for node in script_nodes:
        script_code += ast.get_source_segment(code, node) + '\n'
    script_code = 'def main():\n' + textwrap.indent(script_code, ' ' * 4)
    # print(script_code)
    sample['content'] = script_code
    script_codes = find_api_calling_functions(root_lib, sample, lib, lib_dict)
    calling_code += script_codes
            
    return calling_code


def write_to_jsonl(examples, root_dir):
    group_examples = defaultdict(list)
    for item in examples:
        group_examples[item['API_path']].append(item)
    group_examples = dict(group_examples)

    for key, value in group_examples.items():
        # torch.nn.functional.softmax -> torch_nn_functional-softmax.jsonl
        file_path = os.path.join(root_dir, '-'.join(key.split('.'))) + '.jsonl'

        with open(file_path, 'a', encoding='utf-8') as f:
            for item in value:
                f.write(json.dumps(item) + '\n')


def process_sample(info):
    return find_api_calling_functions(info['lib'], info['sample'])


def api_detector(config):
    files = jsonl_file_search(config.raw_data_dir)
    ds = load_dataset('json', data_files=files, split='train')    
    max_cnt = ds.num_rows
    if not os.path.exists(config.data_dir):
        os.mkdir(config.data_dir)

    codes = []
    write_cnt = 0
    with Pool(cpu_count()) as pool:
        for lib in config.lib_names: 
            data_dir = os.path.join(config.data_dir, lib)
            if not os.path.exists(data_dir):
                os.mkdir(data_dir)
            print(f'Detecting {lib} API calling statements currently...')
            print(f'Results will be save to \"{data_dir}\".')
            for batch_start in tqdm(range(0, len(ds), config.batch_size)):
                batch = [{'lib':lib, 'sample':ds[i]} for i in range(batch_start, min(max_cnt, batch_start + config.batch_size))]
                results = pool.map(process_sample, batch)

                for res in results:
                    if res is not None:
                        codes += res

                write_cnt += 1
                if write_cnt % 100 == 0:    
                    if len(codes) != 0:
                        write_to_jsonl(codes, data_dir)
                        codes = []
            write_to_jsonl(codes, data_dir)
            codes = []
            print('-' * 20)
    
    # for lib in config.lib_names: 
    #     data_dir = os.path.join(config.data_dir, lib)
    #     if not os.path.exists(data_dir):
    #         os.mkdir(data_dir)
    #     print(f'Detecting {lib} API calling statements currently...')
    #     print(f'Results will be save to \"{data_dir}\".')
    #     for batch_start in tqdm(range(0, len(ds), config.batch_size)):
    #         batch = [{'lib':lib, 'sample':ds[i]} for i in range(batch_start, min(max_cnt, batch_start + config.batch_size))]
    #         results = []
    #         for item in batch:
    #             results.append(process_sample(item))

    #         for res in results:
    #             if res is not None:
    #                 codes += res

    #         write_cnt += 1
    #         if write_cnt % 100 == 0:    
    #             if len(codes) != 0:
    #                 write_to_jsonl(codes, data_dir)
    #                 codes = []
    #     write_to_jsonl(codes, data_dir)
    #     codes = []
    #     print('-' * 20)



if __name__ == '__main__':
    config = get_dataset_config()
    api_detector(config)
