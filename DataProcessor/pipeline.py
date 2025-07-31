import os
import re
import shutil
import argparse

from DataProcessor.api_update import updating_api_information
from DataProcessor.api_detector import api_detector
from DataProcessor.repo_crawler import repo_crawler
from DataProcessor.synthesis import synthesis_metadata, mcq_construct, cct_construct, ect_construct
from DataProcessor.jsonl_switch import JsonlSwitch, convert

from hparams.get_config import get_dataset_config
from util.path import path_search



switch = JsonlSwitch(convert)
config = get_dataset_config()
NAME_DICT = {
    'added_apis': 'Added_API',
    'deleted_apis': 'Deleted_API',
    'required_args': 'Modified_API_A',
    'optional_args': 'Modified_API_B',
}


def pipeline(crawling=False,                # crawl repos from GitHub
             api_extractor=False,           # extract API calling statements from code
             data_filter=False,             # filter jsonl files of unchanged apis
             update_code=False,             # call llm api to generate updated_code
             construct_benchmark=False,     # call llm api to construct benchmark
             convert_required=False         # if existing dataset has no attribute called 'content', it should be set true
             ):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    result_dir = path_search(os.path.join(current_dir, 'API_info_result'), 'result_{}')
    if not os.path.exists(result_dir):
        os.mkdir(result_dir)
        
    # detect updated APIs
    print('Detecting updated APIs ...')
    modified_functions_dict = {}
    modified_methods_dict = {}
    modified_functions_list = []
    modified_methods_list = []
    updated_apis_info = {}
    outdated_apis_info = {}
    
    for lib, lib_name, versions in zip(config.libs, config.lib_names, config.versions):
        try:
            print('-' * 80) 
            print(f'Processing library: {lib} \nSearching API update pairs ...')
            old_version = versions[0]
            new_version = versions[1]
            deleted_apis, added_apis, modified_apis, outdated_apis = updating_api_information(lib, lib_name, old_version, new_version, result_dir, config.mirror)
                
            modified_functions_dict[lib] = {
                                        'required_args': modified_apis['function']['required_args'], 
                                        'optional_args': modified_apis['function']['optional_args'],
                                        'outdated_apis': outdated_apis['function'],
                                        'added_apis': added_apis['function'], 
                                        'deleted_apis': deleted_apis['function']
                                    }
            modified_methods_dict[lib] = {
                                        'required_args': modified_apis['method']['required_args'], 
                                        'optional_args': modified_apis['method']['optional_args'],
                                        'outdated_apis': outdated_apis['method'],
                                        'added_apis': added_apis['method'], 
                                        'deleted_apis': deleted_apis['method']
                                    }

            def get_sigs(d1, d2):
                return [item['signature'] for item in d1] + [item['signature'] for item in d2]
            def get_info(api_dict):
                for type_ in ['required_args', 'optional_args']:
                    for item in api_dict[type_]:
                        api_name = item['signature'].split('(', 1)[0]
                        updated_apis_info[api_name] = item
                for item in api_dict['outdated_apis']:
                    api_name = item['signature'].split('(', 1)[0]
                    outdated_apis_info[api_name] = item
        
            modified_functions_list += get_sigs(modified_functions_dict['required_args'],
                                                modified_functions_dict['optional_args'])
            modified_methods_list += get_sigs(modified_methods_dict['required_args'],
                                              modified_methods_dict['optional_args'])
            get_info(modified_functions_dict[lib])
            get_info(modified_methods_dict[lib])
            
        except Exception as e:
            print(f'Existing errors while porcessing library {lib}:\n{e}')
    
    # crawl repos from GitHub, save raw data to config.raw_data_dir
    if crawling:
        print('-' * 80 + '\nCrawling API invocations for functions..')
        # repo_crawler(config, modified_functions_list, 'function')
        repo_crawler(
            modified_functions_list, 
            root=os.path.join(config.raw_data_dir, 'function'), 
            config=config
        )
        print('-' * 40 + '\nCrawling API invocations for methods..')
        # repo_crawler(config, modified_methods_list, 'method')
        repo_crawler(
            modified_methods_list, 
            root=os.path.join(config.raw_data_dir, 'method'), 
            config=config
        )
        print('-' * 40 + '\nFinish crawling repo API invocations successfully!')
    else:
        print('-' * 80 + '\nSkip crawling repo step ...')    
    
    # process existing dataset provided by users
    if not crawling and convert_required:
        # if the existing dataset has no attribute called 'content', it should be set true
        print('Converting jsonl files ...')
        switch(config.raw_data_dir, config.raw_data_dir)
        
    if api_extractor:
        print('-' * 80 + '\nLocating API invocation statements and reorganize crawled data...')
        api_detector(config)
        print('-' * 40 + '\nExtract target code snippet successfully!')
    else:
        print('Skip code snippet extracting step ...')

    # filter jsonl files of unchanged apis
    if data_filter or update_code:
        # process each library
        print('-' * 80 + '\nFilter crawled data...')
        for lib, lib_name, versions in zip(config.libs, config.lib_names, config.versions):
            print('-' * 40)
            print(f'Processing library: {lib} \n')
            data_dir = os.path.join(config.data_dir, lib)   # dataset saving path
            if data_filter:
                print('Filter data ...')
                print('-' * 40 + '\nStep 1: Filter Crawled Files ...\n' + '-' * 40)
                
                # process function api
                def process_filter(mode, api_dict):
                    mode_dir = os.path.join(data_dir, mode)
                    for type_ in ["required_args", "optional_args"]:
                        tgt_dir = os.path.join(mode_dir, NAME_DICT[type_])
                        if not os.path.exists(tgt_dir):
                            os.mkdir(tgt_dir)
                            
                        sigs = set([item['signature'].split('(', 1)[0] for item in api_dict[type_]]) 
                        for fname in os.listdir(mode_dir):
                            api_name = fname[:-len('.jsonl')].replace('-', '.')
                            if api_name in sigs:
                                shutil.copy(os.path.join(mode_dir, fname),
                                            os.path.join(tgt_dir, fname))
                        
                    for name in os.listdir(mode_dir):
                        fp = os.path.join(mode_dir, name)
                        if os.path.isfile(fp) and name.endswith('.jsonl'):
                            os.remove(fp)
                    return
                
                process_filter('function', modified_functions_dict)
                process_filter('method', modified_methods_dict)
                    
            else:
                print('No execution for filtering APIs!')
            
            if not update_code:
                print('No execution for constructing Metadata!')
                continue
            
            print('-' * 40 + '\nStep 2: Constructing Metadata ...\n' + '-' * 40)
            synthesis_metadata(data_dir, updated_apis_info, outdated_apis_info)
            
    if construct_benchmark:
        print('-' * 80)
        print('Constructing CCT Benchmark...')
        cct_construct(updated_apis_info, outdated_apis_info)
        print('Constructing ECT Benchmark...')
        ect_construct(updated_apis_info, outdated_apis_info)
        print('Constructing MCQ Benchmark...')
        mcq_construct(updated_apis_info, outdated_apis_info)
        print('Benchmark Constructing Successfully!')




if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--crawling', 
                        type=bool, 
                        default=False, 
                        help='Crawling files from github.')
    parser.add_argument('--filter', 
                        type=bool, 
                        default=False, 
                        help='Filter invocation files of unchanged APIs.')
    parser.add_argument('--synthesis', 
                        type=bool, 
                        default=False, 
                        help='Synthesis updated / outdated invocations.')
    parser.add_argument('--benchmark', 
                        type=bool, 
                        default=False, 
                        help='Construct benchmark from metadata.')
    args = parser.parse_args()
    
    pipeline(crawling=args.crawling,
             api_extractor=args.crawling,
             data_filter=args.filter,
             update_code=args.synthesis,
             construct_benchmark=args.benchmark,
             convert_required=False)


