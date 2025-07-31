import inspect
import os
import json
import re
import importlib
from typing import Any, Dict, Optional, List
import argparse



errot = 0

class APIInspector:
    def __init__(self, 
                 library_name,
                 library_module,
                 pyi_paths: Optional[Dict[str, str]] = None):
        self.library_name = library_name
        self.library_module = library_module
        self.signatures = {
            'function': {},
            'method': {}
        }
        self.visited_modules = set()
        self.pyi_paths = pyi_paths or {}
        
    def is_library_function(self, obj: Any) -> bool:
        """
        judge if the obj is a function in library
        """
        # check if the obj is a function, builtin function, or other callable object
        is_func = (inspect.isfunction(obj) or 
                  inspect.isbuiltin(obj) or 
                  type(obj).__name__ == 'builtin_function_or_method' or
                  type(obj).__name__ == 'method_descriptor')
        
        # check if the obj is defined in the library
        has_lib_module = (hasattr(obj, '__module__') and 
                         obj.__module__ and 
                         obj.__module__.startswith(self.library_name))
        
        is_callable = callable(obj)
        
        return is_func and has_lib_module and is_callable

    def is_library_class(self, obj) -> bool:
        is_class = inspect.isclass(obj) 
        has_lib_module = (hasattr(obj, '__module__') and 
                        obj.__module__ and 
                        obj.__module__.startswith(self.library_name))
        return is_class and has_lib_module
    
    def get_signature_from_pyi(self, func: Any) -> Optional[str]:
        if not hasattr(func, '__module__') or not hasattr(func, '__name__'):
            return None
            
        for pyi_path in self.pyi_paths.values():
            if os.path.exists(pyi_path):
                with open(pyi_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    func_name = func.__name__
                    pattern = rf"def {func_name}\((.*?)\).*?:"
                    match = re.search(pattern, content, re.DOTALL)
                    if match:
                        return f"({match.group(1)})"
        return None
    
    def get_function_signature(self, func: Any) -> str:
        """
        get signature of function
        """
        try:
            # for functions implemented in C/C++
            if hasattr(func, '__text_signature__') and func.__text_signature__ is not None:
                return func.__text_signature__
            
            pyi_signature = self.get_signature_from_pyi(func)
            if pyi_signature:
                return pyi_signature
            
            # try to leverage inspect tools
            sig = inspect.signature(func)
            return str(sig)
        except (ValueError, TypeError):
            return None
    
    def get_class_signature(self, class_module, module_path) -> List[str]:
        sigs = {}
        
        methods = inspect.getmembers(class_module)
        for method_name, method in methods:
            if callable(method) and (method_name in ['__init__', '__call__'] 
                                    or not method_name.startswith('_')):
                
                def get_method_signature() -> str:
                    try:
                        sig = inspect.signature(method)
                        return str(sig)
                    except (ValueError, TypeError):
                        if hasattr(method, '__text_signature__') and method.__text_signature__:
                            return method.__text_signature__
                    except:
                        global error
                        error += 1
                        
                sig = get_method_signature()
                if sig:
                    sigs[f'{module_path}.{method_name}'] = {
                        'signature': f'{module_path}.{method_name}{sig}',
                        'doc': inspect.getdoc(method)
                    }
        return sigs
    
    def inspect_module(self, module, module_path=""):
        """
        traverse all modules recursively
        """
        module_id = id(module)
        if module_id in self.visited_modules:
            return
        self.visited_modules.add(module_id)
        
        for name, obj in inspect.getmembers(module):
            # skip private module
            if name.startswith('_'):
                continue
                
            full_path = f"{module_path}.{name}" if module_path else name
            
            try:
                if self.is_library_function(obj):
                    signature = self.get_function_signature(obj)
                    qualified_name = f"{obj.__module__}.{obj.__name__}"
                    if signature:
                        self.signatures['function'][qualified_name] = {
                            'signature': qualified_name + signature,
                            'doc': inspect.getdoc(obj)
                        }
             
                elif self.is_library_class(obj):
                    sigs = self.get_class_signature(obj, full_path)
                    self.signatures['method'].update(sigs)
             
                elif (inspect.ismodule(obj) and 
                      hasattr(obj, '__name__') and 
                      obj.__name__.startswith(self.library_name)):
                    self.inspect_module(obj, full_path)
                    
            except Exception as e:
                print(f"Error while inspecting {full_path}: {str(e)}")
    
    def save_signatures(self, output_dir):
        def save(name):
            file_path = os.path.join(output_dir, f"{name}.json")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.signatures[name], f, indent=4)
        
        save('function')
        save('method')
        print(f"Decect Number of Signatures: {len(self.signatures['function']) + len(self.signatures['method'])}")
        print(f"API signature information saved to: {output_dir}")
    
    def inspect_library(self):
        self.inspect_module(self.library_module, self.library_name)


def create_inspector(library_name):
    try:
        library_module = importlib.import_module(library_name)
        pyi_paths = {}
        
        return APIInspector(library_name, library_module, pyi_paths=pyi_paths)
    except ImportError as e:
        raise ImportError(f"Cannot import {library_name}: {str(e)}")

def main(lib, save_dir):
    inspector = create_inspector(lib)
    inspector.inspect_library()
    inspector.save_signatures(save_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", type=str, required=True)
    parser.add_argument("--save_dir", type=str, required=True)
    
    args = parser.parse_args()
    main(args.lib, args.save_dir)
    