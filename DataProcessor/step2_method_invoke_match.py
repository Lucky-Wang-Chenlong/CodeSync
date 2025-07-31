"""
对生成的api_method文件夹进行处理，对其中的所有可能调用了目标method api的代码进行精准静态匹配
并将匹配结果保存至文件output.log，以及具体匹配到的代码编号以及调用行号保存到文件method_invoke_info.json文件
step 2
"""

import ast
import os
import json
import warnings

from typing import List, Dict, Tuple, Any, Optional

from step3_deal_log import process_log_file
from step4_metadata_generate import step_4



class ClassUsageFinder(ast.NodeVisitor):
    """
    通过遍历 AST，找到目标类的构造调用，以及该类实例对特定方法的调用。
    同时，识别在函数参数和变量声明(AnnAssign)中的类型注释是否为目标类，
    并在后续代码中跟踪这些变量是否调用了目标方法。
    """

    def __init__(self, full_class_name: str, method_name: str):
        """
        :param full_class_name: 目标类的全名，如 "torch.nn.Linear"
        :param method_name: 要查找的目标方法名，如 "forward"
        """
        self.full_class_name = full_class_name
        self.method_name = method_name

        # 收集导入别名映射，如 "nn" -> "torch.nn"
        self.alias_map: Dict[str, str] = {}

        # 记录某个变量对应的完整类名，例如 "layer" -> "torch.nn.Linear"
        self.var_to_class: Dict[str, str] = {}

        # 保存分析结果：哪一行初始化（构造）了这个类
        self.constructor_calls: List[Tuple[int, str]] = []  # (line_number, var_name)

        # 保存分析结果：哪一行调用了目标方法
        self.method_calls: List[Tuple[int, str]] = []      # (line_number, var_name)

        # 函数内局部作用域：用于记录局部变量（包括函数参数）的类型。
        # 每遇到一个函数定义，就会暂存/恢复这个字典。
        self.local_var_stack: List[Dict[str, str]] = []

        # 当前所在的函数局部变量映射（最上层）
        self.current_local_vars: Dict[str, str] = {}

    # =========== 处理导入语句，建立别名映射 ===========

    def visit_Import(self, node: ast.Import):
        """
        处理 import 语句，如: import torch.nn as nn
        将别名信息存储到 alias_map 中。
        """
        for alias in node.names:
            if alias.asname:
                # 如果 import torch.nn as nn，则记录 nn -> torch.nn
                self.alias_map[alias.asname] = alias.name
            else:
                # 如果 import torch.nn，则记录 torch.nn -> torch.nn
                self.alias_map[alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        """
        处理 from ... import ... 语句，如:
            from torch import nn
            from torch.nn import Linear
        """
        if node.module is not None:
            for alias in node.names:
                full_name = node.module + '.' + alias.name
                if alias.asname:
                    self.alias_map[alias.asname] = full_name
                else:
                    self.alias_map[alias.name] = full_name
        self.generic_visit(node)

    # =========== 工具函数 ===========

    def get_full_name_from_alias(self, name_or_alias: str) -> str:
        """
        给定别名(如 'nn')，返回其在 alias_map 中对应的完整模块名(如 'torch.nn')。
        如果在 alias_map 中找不到，则原样返回。
        """
        return self.alias_map.get(name_or_alias, name_or_alias)

    def _is_target_class_name(self, raw_name: str) -> bool:
        """
        判断一个字符串（可能是别名展开后）是否是我们的目标类名。
        例如目标类为 'torch.nn.Linear'，那么展开后若正好为 'torch.nn.Linear' 即匹配。
        """
        return (raw_name == self.full_class_name)

    def _matches_target_class_constructor(self, call_node: ast.Call) -> bool:
        """
        判断当前调用是否是目标类的构造函数调用。
        比如 target_class = "torch.nn.Linear"，
        遇到 nn.Linear(...) 或者 Linear(...) 等情况，需要通过别名映射展开后对比。
        """
        # call_node.func 可能是 ast.Name 或 ast.Attribute
        if isinstance(call_node.func, ast.Name):
            # 形如 Linear(...)
            full_called_name = self.get_full_name_from_alias(call_node.func.id)
            return self._is_target_class_name(full_called_name)

        elif isinstance(call_node.func, ast.Attribute):
            # 形如 nn.Linear(...)
            # 需要把 Attribute 链解析为 ['nn', 'Linear'] -> ['torch.nn', 'Linear'] -> 'torch.nn.Linear'
            parts = []
            cur = call_node.func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(self.get_full_name_from_alias(cur.id))
            parts.reverse()  # 原来顺序是 [attr, attr, base]，反转后成为 [base, attr, attr]
            full_called_name = '.'.join(parts)
            return self._is_target_class_name(full_called_name)

        return False

    def _mark_var_as_target_class(self, var_name: str):
        """
        将变量标记为目标类实例。
        """
        self.var_to_class[var_name] = self.full_class_name
        # 若处于函数内，则也在当前局部变量映射中标记
        if self.current_local_vars is not None:
            self.current_local_vars[var_name] = self.full_class_name

    def _get_var_class(self, var_name: str) -> Optional[str]:
        """
        获取某个变量当前被标记的类名（如果有）。
        优先查看局部变量映射，否则查看全局。
        """
        # 优先查局部
        if var_name in self.current_local_vars:
            return self.current_local_vars[var_name]
        # 然后查全局
        return self.var_to_class.get(var_name, None)

    # =========== 处理函数定义(关注参数类型注释) ===========

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """
        遇到一个函数定义时：
          - 建立新的局部变量映射
          - 查找函数参数的类型注释，如果是目标类则标记这个参数
        """
        # 1) 先保存之前的局部映射
        self.local_var_stack.append(self.current_local_vars)
        # 2) 建立一个新的局部映射
        self.current_local_vars = {}

        # 3) 处理函数参数
        for arg in node.args.args:
            if arg.annotation:
                # 可能是 ast.Name / ast.Attribute / ast.Subscript 等
                anno_name = self._get_full_annotation_name(arg.annotation)
                if anno_name == self.full_class_name:
                    # 这个参数就是我们的目标类
                    self.current_local_vars[arg.arg] = self.full_class_name

        # 继续遍历函数体
        self.generic_visit(node)

        # 4) 函数遍历结束，恢复之前的局部映射
        self.current_local_vars = self.local_var_stack.pop()

    def _get_full_annotation_name(self, annotation: ast.AST) -> str:
        """
        从类型注解节点中提取完整名称（若可能），并进行别名展开。
        比如 'nn.Linear' -> 'torch.nn.Linear'
        """
        # case1: ast.Name(id="Linear")
        if isinstance(annotation, ast.Name):
            return self.get_full_name_from_alias(annotation.id)
        # case2: ast.Attribute(value=..., attr=...)
        elif isinstance(annotation, ast.Attribute):
            parts = []
            cur = annotation
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(self.get_full_name_from_alias(cur.id))
            parts.reverse()
            return '.'.join(parts)
        # case3: ast.Subscript, e.g. List[MyClass]
        elif isinstance(annotation, ast.Subscript):
            # 只取最外层的 value，忽略其内部泛型参数
            return self._get_full_annotation_name(annotation.value)
        # 其他情况暂不处理
        return ""

    # =========== 处理带类型注解的变量赋值 (AnnAssign) ===========

    def visit_AnnAssign(self, node: ast.AnnAssign):
        """
        形如: x: SomeType = ...
        如果 SomeType 是目标类，则将 x 标记为目标类实例。
        """
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            # 解析注解
            anno_name = ""
            if node.annotation:
                anno_name = self._get_full_annotation_name(node.annotation)
            if anno_name == self.full_class_name:
                # 将该变量标记为目标类
                self._mark_var_as_target_class(var_name)

        self.generic_visit(node)

    # =========== 处理普通赋值 (不带类型注解) ===========

    def visit_Assign(self, node: ast.Assign):
        """
        处理类似 x = nn.Linear(...) 的赋值，如果右侧是目标类构造函数，就记录。
        """
        # 只有当 value 是 Call 才可能是调用构造函数
        if isinstance(node.value, ast.Call) and self._matches_target_class_constructor(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    self._mark_var_as_target_class(var_name)
                    self.constructor_calls.append((node.lineno, var_name))

        self.generic_visit(node)

    # =========== 处理 Expr 用于捕获无赋值的构造调用 ===========

    def visit_Expr(self, node: ast.Expr):
        """
        处理类似 nn.Linear(...) 但没有赋值的情况 (虽然你提到这种可以不做重点处理)。
        """
        if isinstance(node.value, ast.Call):
            if self._matches_target_class_constructor(node.value):
                self.constructor_calls.append((node.lineno, "<no_assignment>"))
        self.generic_visit(node)

    # =========== 检测目标方法的调用 ===========

    def visit_Call(self, node: ast.Call):
        """
        如 layer.forward(...)。
        """
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name == self.method_name:
                # 看看调用对象是谁
                if isinstance(node.func.value, ast.Name):
                    var_name = node.func.value.id
                    # 判断这个变量是否是目标类实例
                    var_class = self._get_var_class(var_name)
                    if var_class == self.full_class_name:
                        self.method_calls.append((node.lineno, var_name))
        self.generic_visit(node)




def find_class_method_usage(
    code_str: str,
    class_full_name: str,
    method_name: str
) -> Tuple[List[Tuple[int, str]], List[Tuple[int, str]]]:
    """
    在给定的 Python 代码字符串中，查找 `class_full_name` 类的构造调用和对其指定方法 `method_name` 的调用。
    
    :return:
       (constructor_calls, method_calls)
       constructor_calls: List[(lineno, var_name)]
       method_calls:      List[(lineno, var_name)]
    """
    tree = ast.parse(code_str)
    finder = ClassUsageFinder(class_full_name, method_name)
    finder.visit(tree)
    return finder.constructor_calls, finder.method_calls



# if __name__ == "__main__":

def method_api_detector(config):

    apis_dir = os.path.join(config.raw_data_dir, 'method')
    if not os.path.exists(config.temp_dir):
        os.makedirs(config.temp_dir)
    log_path = os.path.join(config.temp_dir, "output.log")

    f = open(log_path, 'w')
    ans = {}
    for fname in os.listdir(apis_dir):
        lists = []
        if not fname.endswith(".jsonl"):
            continue
        base_name = fname[:-6].replace("-", ".")
        parts = base_name.split(".")
        if parts[-1] == "__init__":
            continue
        target_method = parts[-1]
        target_class = ".".join(parts[:-1])
        f.write(f"Processing file: {fname}\n")
        with open(os.path.join(apis_dir, fname), "r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                data = json.loads(line)
                sample_code = data.get("content", "")
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", SyntaxWarning)
                        constructors, method_usages = find_class_method_usage(sample_code, target_class, target_method)
                    if len(method_usages) != 0: 
                        f.write(f"遍历到json {i}\n")
                        lists.append(i)
                    else: continue
                    for lineno, var_name in constructors:
                        f.write(f"  第 {lineno} 行: {var_name} = {target_class}(...)\n")
                    for lineno, var_name in method_usages:
                        f.write(f"  第 {lineno} 行: {var_name}.{target_method}(...)\n")
                except:
                    continue
        if len(lists):
            ans[fname] = lists
    
    method_invoke_info_fpath = os.path.join(config.temp_dir, "method_invoke_info.json")
    with open(method_invoke_info_fpath, "w", encoding="utf-8") as f:
        json.dump(ans, f, ensure_ascii=False, indent=4)


    output_path = os.path.join(config.temp_dir, "output.json")
    process_log_file(log_path, output_path)

    step_4(
        output_json_path=output_path,
        ans_json_path=method_invoke_info_fpath,
        combined_methods_dir=apis_dir,
        output_metadata_path="method_before_metadata.jsonl",
    )
