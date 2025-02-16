import ast
import re
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum, auto




parse_error = 0

class ParameterKind(Enum):
    POSITIONAL_ONLY = auto()
    POSITIONAL_OR_KEYWORD = auto()
    VAR_POSITIONAL = auto()         # *args
    KEYWORD_ONLY = auto()
    VAR_KEYWORD = auto()            # **kwargs


@dataclass
class Parameter:
    name: str
    kind: ParameterKind
    has_default: bool
    default: Optional[ast.AST]


def parse_signature(signature_str: str) -> List[Parameter]:
    """
    parse signature and return parameters list
    """
    def replace_func(code):
        while re.search(r"<[^<>]*>", code):
            code = re.sub(r"<[^<>]*>", "None", code)
        return code
    
    global parse_error
    signature = signature_str.rsplit('->', 1)[0].strip()
    api_name = signature.split('(', 1)[0].strip().replace('.', '_')
    params = signature.split('(', 1)[1]
    signature = f"{api_name}({params}"
    if not signature.startswith("def "):
        signature = "def " + signature
    if not signature.endswith(":"):
        signature += ":"
    signature += "\n    pass"
    signature = replace_func(signature)
    
    try:
        module = ast.parse(signature)
    except SyntaxError as e:
        parse_error += 1
        print(e)
        print(signature)
        return None
    
    func_def = module.body[0]
    if not isinstance(func_def, ast.FunctionDef):
        parse_error += 1
    
    args = func_def.args
    parameters = []
    
    for arg, default in zip(args.posonlyargs, [None]*(len(args.posonlyargs) - len(args.defaults)) + args.defaults):
        parameters.append(Parameter(
            name=arg.arg,
            kind=ParameterKind.POSITIONAL_ONLY,
            has_default=default is not None,
            default=default
        ))
    
    # positional or keyword 
    for arg, default in zip(args.args, [None]*(len(args.args) - len(args.defaults)) + args.defaults):
        parameters.append(Parameter(
            name=arg.arg,
            kind=ParameterKind.POSITIONAL_OR_KEYWORD,
            has_default=default is not None,
            default=default
        ))
    
    # *args
    if args.vararg:
        parameters.append(Parameter(
            name=args.vararg.arg,
            kind=ParameterKind.VAR_POSITIONAL,
            has_default=False,
            default=None
        ))
    
    # keyword-only
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parameters.append(Parameter(
            name=arg.arg,
            kind=ParameterKind.KEYWORD_ONLY,
            has_default=default is not None,
            default=default
        ))
    
    # **kwargs
    if args.kwarg:
        parameters.append(Parameter(
            name=args.kwarg.arg,
            kind=ParameterKind.VAR_KEYWORD,
            has_default=False,
            default=None
        ))
    
    return parameters

def compare_signature(sig1: str, sig2: str) -> bool:
    try:
        params1 = parse_signature(sig1)
        params2 = parse_signature(sig2)
        if params1 is None or params2 is None:
            return 0
    except ValueError as e:
        print(e)
        return 0
    
    def categorize(params: List[Parameter]):
        pos_only = [p for p in params if p.kind == ParameterKind.POSITIONAL_ONLY]
        pos_or_kw = [p for p in params if p.kind == ParameterKind.POSITIONAL_OR_KEYWORD]
        var_pos = [p for p in params if p.kind == ParameterKind.VAR_POSITIONAL]
        kw_only = [p for p in params if p.kind == ParameterKind.KEYWORD_ONLY]
        var_kw = [p for p in params if p.kind == ParameterKind.VAR_KEYWORD]
        def get_name_set(l):
            name_set = set()
            for p in l:
                name_set.add(p.name)
            return name_set
        
        return {
            "pos_only": pos_only,
            "pos_or_kw": pos_or_kw,
            "var_pos": var_pos,
            "kw_only": kw_only,
            "var_kw": var_kw,
            "pos_only_name": get_name_set(pos_only),
            "pos_or_kw_name": get_name_set(pos_or_kw),
            "kw_only_name": get_name_set(kw_only),
        }
    
    cat1 = categorize(params1)
    cat2 = categorize(params2)
    
    # default value judgement
    sig1_param_name = cat1["pos_only_name"] | cat1["pos_or_kw_name"] | cat1["kw_only_name"]
    sig2_param_name = cat2["pos_only_name"] | cat2["pos_or_kw_name"] | cat2["kw_only_name"]
    def get_default(p, name):
        for p_ in p:
            if p_.name == name:
                return p_.has_default
    for name in sig1_param_name & sig2_param_name:
        if get_default(params1, name) != get_default(params2, name):
            return 2
    for name in sig1_param_name - sig2_param_name:
        if not get_default(params1, name):
            return 2
    for name in sig2_param_name - sig1_param_name:
        if not get_default(params2, name):
            return 2
    
    # compare numbers of parameters
    if len(cat1["pos_only"]) != len(cat2["pos_only"]) or len(cat1["pos_or_kw"]) != len(cat2["pos_or_kw"]):
        return 1
    
    # compare position-only parameters, and must keep no change of position
    for p1, p2 in zip(cat1["pos_only"] + cat1["pos_or_kw"], cat2["pos_only"] + cat2["pos_or_kw"]):
        if p1.name != p2.name or p1.kind != p2.kind:
            return 1
    
    # compare keyword-only parameters
    # get all keywords of parameters, and must keep no change of names
    if cat1["kw_only_name"] != cat2["kw_only_name"]:
        return 1
    
    # compare *args & **kwargs
    if len(cat1["var_pos"]) != len(cat2["var_pos"]) or len(cat1["var_kw"]) != len(cat2["var_kw"]):
        return 1
    
    return 0

import json
def read_json(path):
    with open(path, 'r') as f:
        data = json.load(f)
    new_data = []
    for item in data:
        new_data.append(item['signature'])
    return new_data    

def write_log(data, path):
    with open(path, 'w') as f:
        content = ''
        for item in data:
            content += item + '\n'
        f.write(content)

if __name__ == "__main__":
    path1 = "/media/sata7t/wcloong/CodeSync/DataProcessor/API_info_result/result_5/torch/modified-api-A.json"
    path2 = "/media/sata7t/wcloong/CodeSync/DataProcessor/API_info_result/result_5/torch/outdated-api-A.json"
    out_path_1 = "/media/sata7t/wcloong/updated.log"
    out_path_2 = "/media/sata7t/wcloong/outdated.log"
    sigs_1 = read_json(path1)
    sigs_2 = read_json(path2)
    new_sig_1 = []
    new_sig_2 = []
    for sig1, sig2 in zip(sigs_1, sigs_2):
        if compare_signature(sig1, sig2) == 2:
            new_sig_1.append(sig1)
            new_sig_2.append(sig2)
    print(parse_error)
    write_log(new_sig_1, out_path_1)
    write_log(new_sig_2, out_path_2)
     
