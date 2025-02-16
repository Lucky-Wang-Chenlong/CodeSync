import sys
import os
import textwrap

from util.path import jsonl_file_search, read_jsonl, write2jsonl



class JsonlSwitch:
    def __init__(self, convert_func):
        self.convert_func = convert_func

    def __call__(self, dataset_dir, output_dir=None):
        jsonl_file_list = jsonl_file_search(dataset_dir)
        
        if not os.path.exists(output_dir):
            os.mkdir(output_dir)
        if output_dir is None:
            output_dir = dataset_dir
        
        for file_path in jsonl_file_list:
            data = read_jsonl(file_path)
            data = [self.convert_func(item) for item in data]
            
            write2jsonl(data, file_path.replace(dataset_dir, output_dir))
        

def convert(item):
    import ast
    try:
        ast.parse(item['import'])
    except Exception as e:
        if 'trailing comma' in e.msg:
            prefix = '\n'.join(item['import'].split('\n')[:e.lineno-1])
            suffix = '\n'.join(item['import'].split('\n')[e.lineno:])
            new_import = item['import'].split('\n')[e.lineno-1] + 'wrong_package'
            item['import'] = prefix + '\n' + new_import + '\n' + suffix
    item['content'] = item['import'] + '\n' * 4 + textwrap.dedent(item['code'])
    return item

