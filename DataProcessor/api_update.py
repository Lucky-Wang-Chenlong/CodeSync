import os
import sys
import subprocess
from typing import Dict

from util.path import path_search, write2json, json2list
from hparams.get_config import get_dataset_config
from DataProcessor.signature_mapping import compare_signature


    
    
def create_venv(venv_dir, lib, version, mirror=None):
    '''create virtual environment for different version library'''
    print('-' * 40)
    try:
        cmd = ['conda', 'create', '--prefix', venv_dir, f'{lib}={version}', '-y']
        print(f'Creating virtual environment for {lib}={version}...')
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"Virtual environment created at {venv_dir}")
    except subprocess.CalledProcessError as e:
        cmd = ['python', '-m', 'venv', venv_dir]
        subprocess.run(cmd, check=True, capture_output=True)
        install_pip_in_venv(venv_dir)
        install_package_in_venv(venv_dir, lib, version, mirror)
        print(f"Virtual environment created at {venv_dir}")
    except Exception as e:
        print("Failed to create virtual environment with conda. Trying with venv module...")
        raise Exception(f"Failed to create virtual environment with conda: {e}")
    finally:
        print('-' * 40)

def install_pip_in_venv(venv_dir):
    '''Install pip if it has not been installed'''
    
    if sys.platform == 'win32':
        python_executable = os.path.join(venv_dir, 'Scripts', 'python.exe')
    else:
        python_executable = os.path.join(venv_dir, 'bin', 'python')

    try:
        subprocess.check_call([python_executable, '-m', 'ensurepip', '--upgrade'])
        subprocess.check_call([python_executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
        print(f"pip has been installed and upgraded in virtual environment at {venv_dir}")
    except Exception as e:
        print(f"Unexpected error: {e}")


def install_package_in_venv(venv_dir, lib,  version, mirror=None):
    '''install target library in virtual environment'''

    if sys.platform == 'win32':
        pip_path = os.path.join(venv_dir, 'Scripts', 'pip.exe')
    else:
        pip_path = os.path.join(venv_dir, 'bin', 'pip')
    
    try:
        if mirror is None:
            subprocess.check_call([pip_path, 'install', f'{lib}=={version}'])
        else:
            subprocess.check_call([pip_path, 'install', f'{lib}=={version}', '-i', mirror])
        print(f'Package {lib} installed successfully!')
    except subprocess.CalledProcessError as e:
        raise (f"Error installing package {lib}: {e}")


def delete_venv(venv_path):
    print('*' * 20)
    try:
        cmd = ['conda', 'remove', '--prefix', venv_path, '--all']
        subprocess.run(cmd, check=True, capture_output=True)
        print(f'Delete virtual environment {venv_path} successfullt!')
    except:
        pass
    # except:
    #     print(f'Failed to delete virtual environment {venv_path}!')
    print('*' * 20)



def api_updating(old_apis: Dict, new_apis: Dict):
    '''compare api signature from 2 different version'''
    deleted_apis = []
    added_apis = []
    modified_apis = {'required_args': [], 'optional_args': []}
    outdated_apis = {'required_args': [], 'optional_args': []}

    old_apis_name = set(old_apis.keys())
    new_apis_name = set(new_apis.keys())
    deleted_apis_name = old_apis_name - new_apis_name
    added_apis_name = new_apis_name - old_apis_name

    for deleted_api_name in deleted_apis_name:
        deleted_apis.append(old_apis[deleted_api_name])
    for added_api_name in added_apis_name:
        added_apis.append(new_apis[added_api_name])

    inte_apis_name = old_apis_name.intersection(new_apis_name)
    for api_name in inte_apis_name:
        old_api = old_apis[api_name]
        new_api = new_apis[api_name]
        if old_api == new_api:
            continue
        res = compare_signature(old_api['signature'], new_api['signature'])
        if res == 2:
            modified_apis['required_args'].append(new_api)
            outdated_apis['required_args'].append(old_api)
        if res == 1:
            modified_apis['optional_args'].append(new_api)
            outdated_apis['optional_args'].append(old_api)
        # modified_apis['required_args'].append(new_api)
        # outdated_apis['required_args'].append(old_api)
    
    return deleted_apis, added_apis, modified_apis, outdated_apis


def updating_api_information(lib, lib_name, old_version, new_version, result_dir, mirror, delete_venv_=False):
    result_dir = os.path.join(result_dir, lib)
    if not os.path.exists(result_dir):
        os.mkdir(result_dir)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    venv_root_dir = os.path.join(current_dir, 'venv')
    script_path = os.path.join(current_dir, 'inspect_signature.py')

    def create_venv_pipeline(venv_dir, version):
        if not os.path.exists(venv_dir):
            create_venv(venv_dir, lib, version, mirror)
            # install_pip_in_venv(venv_dir)
            # install_package_in_venv(venv_dir, lib, version, mirror)
        else:
            print(f'Virtual environment: {venv_dir} already exists!')

    # create venv
    old_venv_dir = os.path.join(venv_root_dir, f'{lib}-{old_version}')
    new_venv_dir = os.path.join(venv_root_dir, f'{lib}-{new_version}')
    create_venv_pipeline(old_venv_dir, old_version)
    create_venv_pipeline(new_venv_dir, new_version)

    # run script in virtual environment
    def run_script_in_venv(venv_dir, save_dir):
        if not os.path.exists(venv_dir):
            print(f'Virtual environment at {venv_dir} does not exist!')
            return
        
        if sys.platform == 'win32':
            py_exe = os.path.join(venv_dir, "Scripts", "python.exe")
        else:
            py_exe = os.path.join(venv_dir, "bin", "python")
        cmd = [py_exe, script_path, '--lib', lib_name, '--save_dir', save_dir]
        
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            if not sys.platform == 'win32':
                cmd[0] = os.path.join(venv_dir, "bin", "activate")
            subprocess.run(cmd, check=True)
        except:
            print(f"Error occurred: {e}")
            print(f"Error output:\n{e.stderr}")
            
    old_version_dir = os.path.join(result_dir, f'{lib}-{old_version}-api')
    new_version_dir = os.path.join(result_dir, f'{lib}-{new_version}-api')
    run_script_in_venv(old_venv_dir, old_version_dir)
    print(f'Finish processing library {lib}-{old_version} successfully!')
    run_script_in_venv(new_venv_dir, new_version_dir)
    print(f'Finish processing library {lib}-{new_version} successfully!')
    print('-' * 40)

    if delete_venv_:
        delete_venv(old_venv_dir)
        delete_venv(new_venv_dir)

    deleted_apis = {}
    added_apis = {}
    modified_apis = {}
    outdated_apis = {}
    def category(name):
        old_apis = json2list(os.path.join(old_version_dir, f'{name}.json'))
        new_apis = json2list(os.path.join(new_version_dir, f'{name}.json'))
        deleted_apis[name], added_apis[name], modified_apis[name], outdated_apis[name] = api_updating(old_apis, new_apis)
        
        save_dir = os.path.join(result_dir, f'{name}')
        if not os.path.exists(save_dir):
            os.mkdir(save_dir)
        write2json(deleted_apis, os.path.join(save_dir, 'deleted-api.json'))
        write2json(added_apis, os.path.join(save_dir, 'added-api.json'))
        write2json(modified_apis[name]['required_args'], os.path.join(save_dir, 'modified-api-A.json'))
        write2json(outdated_apis[name]['required_args'], os.path.join(save_dir, 'outdated-api-A.json'))
        write2json(modified_apis[name]['optional_args'], os.path.join(save_dir, 'modified-api-B.json'))
        write2json(outdated_apis[name]['optional_args'], os.path.join(save_dir, 'outdated-api-B.json'))
    
    category('function')
    category('method')
    print(f'API updating information has been recorded into {result_dir}.')
    print('-' * 40)

    return deleted_apis, added_apis, modified_apis, outdated_apis


if __name__ == '__main__':
    config = get_dataset_config()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    result_dir = path_search(os.path.join(current_dir, 'API_info_result'), 'result_{}')
    if not os.path.exists(result_dir):
        os.mkdir(result_dir)

    for lib, name, versions in zip(config.libs, config.lib_names, config.versions):
        updating_api_information(lib, name, versions[0], versions[1], result_dir, config.mirror)

