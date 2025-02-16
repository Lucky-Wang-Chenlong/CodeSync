import yaml
import os
import json
from pathlib import Path


class ConfigDir:
    def __init__(self):
        self.dir = os.path.dirname(os.path.abspath(__file__))
        self.dataset_dir = os.path.join(self.dir, 'configs', 'dataset_config.yml')
        self.eval_dir = os.path.join(self.dir, 'configs', 'evaluation_config.yml')
        self.updating_dir = os.path.join(self.dir, 'configs', 'updating_config.yml')
        self.prompt_dir = os.path.join(self.dir, 'configs', 'prompts.json')

config_dir = ConfigDir()


class Config:
    def __init__(self, config_dict:dict):
        for key, value in config_dict.items():
            setattr(self, key, value)


def get_dataset_config():
    with open(config_dir.dataset_dir, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    config  = Config(config)
    if config.mirror == 'None':
        config.mirror = None
    return config


def get_eval_config():
    with open(config_dir.eval_dir, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    config  = Config(config)
    if config.mirror == 'None':
        config.mirror = None
    return config


def get_prompt_config():
    with open(config_dir.prompt_dir, 'r') as f:
        return json.load(f)

