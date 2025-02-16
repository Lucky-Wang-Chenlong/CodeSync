import torch
import json
from transformers import GPT2TokenizerFast
from torch.utils.data import Dataset, DataLoader
from torch.nn.functional import *

from hparams.get_config import Config



    
def sample_processor(prompt_dict):
    ctx = '\n'.join(prompt_dict['code'].split('\n')[:prompt_dict['start_line_no']-1])
    imports = prompt_dict['import']
    calling = '\n'.join(prompt_dict['code'].split('\n')[prompt_dict['start_line_no']-1: prompt_dict['end_line_no']])
    suffix = '\n'.join(prompt_dict['code'].split('\n')[prompt_dict['end_line_no']:])

    # find full name of api in code snippet
    api_name_list = prompt_dict['API_path'].split('.')
    for i in range(len(api_name_list)):
        api_name = '.'.join(api_name_list[i:])
        calling_list = calling.split(api_name)
        if len(calling_list) == 2:
            break
    prompt = imports + ctx + '\n' + calling_list[0] + api_name
    tgt_seq = calling_list[1]
    return prompt, tgt_seq, api_name, ctx + '\n' + calling_list[0] + api_name, imports, suffix


def prompt_template(
        X: list,
        Y: list,
        tok: GPT2TokenizerFast,
        config: Config
):  
    Y_tokens = [tok(y, return_tensors='pt').input_ids.to(config.device) for y in Y]

    tok.truncation_side = 'left'
    tok.padding_side = 'left'
    tok.pad_token = tok.eos_token

    complete_prompt = []
    for x in X:
        complete_prompt.append(x)
    # X_tokens = tok(complete_prompt,
    #                return_tensors='pt',
    #                max_length=config.max_seq_len,
    #                truncation=True,
    #                padding='max_length').input_ids.to(config.device)
    X_tokens = tok(complete_prompt, return_tensors='pt').input_ids.to(config.device)
    if X_tokens.size()[-1] > config.max_seq_len:
        X_tokens = X_tokens[:, -config.max_seq_len:]    # truncation
    
    return X_tokens, Y_tokens


def prompt_from_json(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        batch = []
        for line in lines:
            prompt_dict = json.loads(line)
            try:
                x, y, z, code, imports = sample_processor(prompt_dict)
            except:
                continue
            batch.append({'prompt': x, 'targets': y, 'API_path': z, 'code': code, 'imports': imports})
        return batch
    except:
        return None



class ListDataset(Dataset):
    def __init__(self, 
                 data_list
                 ):
        self.data = data_list

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        return self.data[idx]



class DatasetLoader:
    def __init__(self, data_list, batch_size=1, shuffle=False):
        self.dataset = ListDataset(data_list)
        self.loader = DataLoader(self.dataset, batch_size=batch_size, shuffle=shuffle)
    
    def __iter__(self):
        return iter(self.loader)
    
    def __len__(self):
        return len(self.loader)
    
    def __getitem__(self, idx):
        if idx < 0 or idx >= len(self.loader):
            return None
        
        return self.loader.dataset[idx]

