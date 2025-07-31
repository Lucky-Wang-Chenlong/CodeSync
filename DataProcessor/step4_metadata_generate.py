"""利用之前生成的各种文件生成初步metadata，不包含lagacy-update"""
import os
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast


# sig_dict = None




def extract_blocks(code):
    """把整个代码文件按照作用域分成多个块"""
    tree = ast.parse(code)
    import_statements = []
    function_blocks = []
    
    # 记录所有行的索引，初始化为全局
    total_lines = code.splitlines()
    total_line_count = len(total_lines)
    occupied = [False] * (total_line_count + 1)  # 1-based indexing

    # 收集所有导入语句
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno
            end = getattr(node, 'end_lineno', node.lineno)
            import_statements.append((start, end))
            for i in range(start, end + 1):
                occupied[i] = True

    # 定义一个递归函数来遍历所有函数，包括类中的方法
    def visit_functions(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                start = child.lineno
                end = getattr(child, 'end_lineno', child.lineno)
                function_blocks.append({'code': '', 'start_line': start, 'end_line': end})
                for i in range(start, end + 1):
                    occupied[i] = True
            elif isinstance(child, ast.ClassDef):
                visit_functions(child)  # 递归遍历类中的函数
            else:
                visit_functions(child)  # 递归遍历其他节点

    visit_functions(tree)

    # 提取导入语句的代码
    imports_code = []
    for start, end in import_statements:
        imports_code.extend(total_lines[start - 1:end])
    imports_code_str = '\n'.join(imports_code)

    # 提取每个函数的代码
    functions = []
    for func in function_blocks:
        start = func['start_line']
        end = func['end_line']
        func_code = '\n'.join(total_lines[start - 1:end])
        functions.append({
            'type': 'function',
            'code': func_code,
            'start_line': start,
            'end_line': end
        })

    # 提取全局代码（不属于导入或函数的部分）
    global_code_lines = [line for idx, line in enumerate(total_lines, 1) if not occupied[idx]]
    global_code_str = '\n'.join(global_code_lines)

    # 构建结果列表
    blocks = []
    
    if imports_code_str.strip():
        blocks.append({
            'type': 'imports',
            'code': imports_code_str
        })
    
    blocks.extend(functions)
    
    if global_code_str.strip():
        blocks.append({
            'type': 'global',
            'code': global_code_str
        })
    
    return blocks


def load_output_json(output_json_path):
    with open(output_json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_ans_json(ans_json_path):
    with open(ans_json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_api_path(api_filename):
    return api_filename.replace('-', '.').replace('.jsonl', '')

def read_combined_methods_file(api_filename, combined_methods_dir):
    file_path = os.path.join(combined_methods_dir, api_filename)
    if not os.path.exists(file_path):
        print(f"文件 {file_path} 不存在。跳过。")
        return []
    
    json_objects = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    json_obj = json.loads(line)
                    json_objects.append(json_obj)
                except json.JSONDecodeError:
                    print(f"无法解析 JSON 行 {line_num} in {file_path}: {line}")
    return json_objects

def find_json_object(json_objects, code_number):
    if 1 <= code_number <= len(json_objects):
        return json_objects[code_number - 1]
    else:
        print(f"代码编号 {code_number} 超出范围。")
        return None

def find_block(blocks, line_number):
    for block in blocks:
        if block['type'] == 'function':
            if 'start_line' in block and 'end_line' in block:
                if block['start_line'] <= line_number <= block['end_line']:
                    return block
        elif block['type'] == 'global':
            # 假设全局代码块覆盖所有未被函数块覆盖的行
            return block
    return None

def extract_api_call_parts(block_code, api_call_content):
    """
    从代码块中提取 context, target_seq, suffix
    """
    # 找到 api_call_content 在代码块中的位置
    match = re.search(re.escape(api_call_content), block_code)
    if not match:
        print(f"未找到 API 调用内容: {api_call_content} 在代码块中。")
        return None, None, None
    
    start_idx = match.start()
    end_idx = match.end()
    x = block_code[start_idx: end_idx]
    # context 是 '(' 前的部分
    context_match = block_code[:end_idx-1]
    context = context_match

    # 现在提取 target_seq，即从 '(' 开始到匹配的 ')' 结束
    stack = []
    target_seq = ""
    suffix = ""
    i = end_idx - 1  # 从 '(' 位置开始
    while i < len(block_code):
        char = block_code[i]
        if char == '(':
            stack.append('(')
            target_seq += char
        elif char == ')':
            if stack:
                stack.pop()
                target_seq += char
                if not stack:
                    i += 1
                    break
            else:
                # 多余的右括号，结束
                break
        else:
            target_seq += char
        i += 1

    # suffix 是 ')' 后的部分
    suffix = block_code[i:].strip()

    return context.strip(), target_seq.strip(), suffix

def process_single_entry(api_filename, code_number, output_json, combined_methods_dir):
    metadata_entries = []
    
    # 读取 combined_methods 目录下对应的文件
    json_objects = read_combined_methods_file(api_filename, combined_methods_dir)
    if not json_objects:
        return metadata_entries
    
    # 获取 API_path
    api_path = get_api_path(api_filename)
    
    # 获取 API 调用行号信息
    api_calls = output_json.get(api_filename, {}).get(str(code_number), {})
    if not api_calls:
        return metadata_entries
    
    # 获取父 JSON 对象
    parent_json = find_json_object(json_objects, code_number)
    if not parent_json:
        return metadata_entries
    
    content = parent_json.get('content', '')
    if not content:
        return metadata_entries
    
    # 分块
    blocks = extract_blocks(content)
    
    # 获取必要的父字段
    repository = parent_json.get('repository', '')
    url = parent_json.get('url', '')
    last_updated = parent_json.get('last_updated', '')
    stars = parent_json.get('stars', 0)
    
    # 提取 import 代码
    imports = ""
    for blk in blocks:
        if blk['type'] == 'imports':
            imports = blk.get('code', '')
            break
    
    # 跟踪已经使用过的块，避免重复使用
    used_blocks = set()
    
    for line_number_str, api_call_content in api_calls.items():
        try:
            line_number = int(line_number_str)
        except ValueError:
            print(f"无效的行号: {line_number_str}")
            continue
        
        block = find_block(blocks, line_number)
        if not block:
            print(f"未找到行号 {line_number} 所在的代码块。")
            continue
        
        block_id = id(block)
        if block_id in used_blocks:
            # 这个块已经被使用过，跳过
            continue
        
        block_code = block.get('code', '')
        context, target_seq, suffix = extract_api_call_parts(block_code, api_call_content)
        
        if context is None:
            continue  # 无法提取，跳过
        
        metadata = {
            "API_path": api_path,
            "repository": repository,
            "url": url,
            "last_updated": last_updated,
            "stars": stars,
            "import": imports,
            "context": context,
            "target_seq": target_seq,
            "suffix": suffix,
            # "outdated_signature": sig_dict[api_path]["outdated_signature"],
            # "updated_signature": sig_dict[api_path]["updated_signature"]
        }
        
        metadata_entries.append(metadata)
        used_blocks.add(block_id)
    print(api_filename + " done.")
    return metadata_entries

def process_metadata_multithreaded(output_json, ans_json, combined_methods_dir, output_metadata_path, max_workers=8):
    metadata_list = []
    tasks = []
    
    # 使用 ThreadPoolExecutor 进行多线程处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for api_filename, code_numbers in ans_json.items():
            # if not (get_api_path(api_filename) in sig_dict.keys()):
            #     continue
            for code_number in code_numbers:
                futures.append(
                    executor.submit(
                        process_single_entry,
                        api_filename,
                        code_number,
                        output_json,
                        combined_methods_dir
                    )
                )
        
        for future in as_completed(futures):
            try:
                result = future.result()
                metadata_list.extend(result)
            except Exception as e:
                print(f"处理任务时出错: {e}")
    
    # 写入 JSONL 文件
    with open(output_metadata_path, 'w', encoding='utf-8') as outfile:
        for metadata in metadata_list:
            json_line = json.dumps(metadata, ensure_ascii=False)
            outfile.write(json_line + '\n')
    
    print(f"元数据处理完成，已保存到 {output_metadata_path}")

def step_4(
    output_json_path='output.json',     # step3输出文件
    ans_json_path='method_invoke_info.json',    # step2输出的文件
    combined_methods_dir='apis_method',     # step1输出的目录
    output_metadata_path='method_before_metadata.jsonl',    # 没有生成lagacy-update对
    # sig_dict_path='method_lagacy_update_signature.json',
):
    # global sig_dict
    # 文件路径配置
    # output_json_path = 'output.json'# step3输出文件
    # ans_json_path = 'method_invoke_info.json'# step2输出的文件
    # combined_methods_dir = 'apis_method'# step1输出的目录
    # output_metadata_path = 'method_before_metadata.jsonl'# 没有生成lagacy-update对
    # # 读取本目录下的method_lagacy_update_signature.json
    # sig_dict_path = 'method_lagacy_update_signature.json'
    # if not os.path.exists(sig_dict_path):
    #     print(f"文件 {sig_dict_path} 不存在。请确保文件在当前目录下。")
    #     exit(1)
    
    # with open(sig_dict_path, 'r', encoding='utf-8') as f:
    #     sig_dict = json.load(f)

    # 检查文件和目录是否存在
    if not os.path.exists(output_json_path):
        print(f"文件 {output_json_path} 不存在。请确保文件在当前目录下。")
        exit(1)
    if not os.path.exists(ans_json_path):
        print(f"文件 {ans_json_path} 不存在。请确保文件在当前目录下。")
        exit(1)
    if not os.path.isdir(combined_methods_dir):
        print(f"目录 {combined_methods_dir} 不存在。请确保目录在当前目录下。")
        exit(1)
    
    # 加载 JSON 文件
    output_json = load_output_json(output_json_path)
    ans_json = load_ans_json(ans_json_path)
    
    # 处理元数据（多线程）
    process_metadata_multithreaded(
        output_json, ans_json, combined_methods_dir, 
        output_metadata_path, max_workers=1)

if __name__ == "__main__":
    step_4()
