import os
import json



def path_search(directory, name_template):
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    file_index = 0
    while True:
        file_name = name_template.format(file_index)
        file_path = os.path.join(directory, file_name)
        
        if not os.path.exists(file_path):
            return file_path
        
        file_index += 1


def jsonl_file_search(directory):
    jsonl_files = []
    for path, names, filenames in os.walk(directory):
        for file in filenames:
            if file.endswith('.jsonl'):
                jsonl_files.append(os.path.join(path, file))
    return jsonl_files


def write2log(l, path):
    content = ''
    for item in l:
        content += f'{item}\n'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def log2list(path):
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    return [line.strip() for line in lines]


def json2list(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def write2jsonl(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        for item in data:
            json_line = json.dumps(item)
            f.write(json_line + '\n')


def write2json(data, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f,  indent=4)
    

def read_jsonl(path):
    data = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            data.append(json.loads(line))
    return data

