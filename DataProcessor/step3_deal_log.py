"""
处理日志文件，将其变成能够方便读取的形式output.json，step3
"""

import os
import re
import json




def process_log_file(log_file_path, output_file_path):
    # 初始化最终的三重字典
    final_dict = {}

    # 正则表达式模式
    processing_file_pattern = re.compile(r'^Processing file:\s+(.+\.jsonl)$')
    traverse_json_pattern = re.compile(r'^遍历到json\s+(\d+)$')
    api_call_pattern = re.compile(r'^第\s+(\d+)\s+行:\s+(.+)$')

    current_file = None
    current_json = None
    api_to_match = None

    with open(log_file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()

            # 检查是否是Processing file行
            processing_file_match = processing_file_pattern.match(line)
            if processing_file_match:
                # 提取文件名
                filename = processing_file_match.group(1)

                # 提取API名称（假设API名称是文件名最后一个'-'后面的部分，去掉扩展名）
                api_name = filename.split('-')[-1].replace('.jsonl', '')
                api_to_match = f".{api_name}("

                # 初始化该文件的字典
                current_file = filename
                final_dict.setdefault(current_file, {})
                
                # 准备下一步是否有内容的标志
                # 如果下一个Processing file紧跟当前Processing file，则不需要这个key
                # 这里暂时无法预知下一行，所以稍后处理

                continue

            # 检查是否是遍历到json行
            traverse_json_match = traverse_json_pattern.match(line)
            if traverse_json_match and current_file:
                # 提取json号
                json_number = int(traverse_json_match.group(1))
                current_json = json_number
                final_dict[current_file].setdefault(current_json, {})
                continue

            # 检查是否是API调用行
            api_call_match = api_call_pattern.match(line)
            if api_call_match and current_file and current_json:
                line_number = int(api_call_match.group(1))
                api_call_content = api_call_match.group(2)

                # 仅记录包含特定API调用的行
                if api_to_match in api_call_content:
                    final_dict[current_file][current_json][line_number] = api_call_content
                continue

    # 处理没有任何API调用的文件，移除这些文件
    keys_to_remove = []
    for file_key, json_dict in final_dict.items():
        # 检查json_dict是否为空或其内部字典是否为空
        if not json_dict or all(not calls for calls in json_dict.values()):
            keys_to_remove.append(file_key)
    for key in keys_to_remove:
        del final_dict[key]

    # 将最终的字典保存为JSON文件
    with open(output_file_path, 'w', encoding='utf-8') as outfile:
        json.dump(final_dict, outfile, ensure_ascii=False, indent=4)

    print(f"处理完成，结果已保存到 {output_file_path}")



if __name__ == "__main__":
    log_filename = "output.log"       # 输入日志文件名
    output_filename = "output.json"   # 输出JSON文件名

    # 确保日志文件存在
    if not os.path.exists(log_filename):
        print(f"日志文件 {log_filename} 不存在。请确保文件在当前目录下。")
    else:
        process_log_file(log_filename, output_filename)

