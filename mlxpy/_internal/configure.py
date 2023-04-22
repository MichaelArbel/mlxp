import omegaconf
from omegaconf import OmegaConf
from mlxpy.scheduler import DefaultSchedulers, Scheduler
from mlxpy.data_structures.schemas import Metadata
from mlxpy.data_structures.config_dict import convert_dict, ConfigDict
from mlxpy.utils import bcolors
import yaml
import os



def _configure_scheduler(mlxpy_config):
    while True:
        print(f"{bcolors.OKBLUE}You can either choose one of the job schedulers available by default {bcolors.ENDC},")
        
        print(f"{bcolors.OKBLUE}or define a custom one by inheriting from the abstract class {Scheduler} (see documentation)  {bcolors.ENDC}")
        
        print(f"{bcolors.OKCYAN}For a default scheduler, you can choose one from this list:")
        print(f"{bcolors.FAIL}{[member.value for member in DefaultSchedulers]}{bcolors.ENDC}")
        print(f"For a custom scheduler, you must provide the full name of the user-defined Scheduler subclass (ex. my_app.CustomScheduler):")
        files_input = input(f"{bcolors.OKCYAN} Please enter your choice (or hit Enter to skip): {bcolors.ENDC}")
         

        if files_input:
            names = files_input.strip().rsplit('.', 1)
            is_valid=True 
            for name in names:
                if not name.isidentifier():
                    is_valid=False
            if is_valid:
                omegaconf.OmegaConf.set_struct(mlxpy_config, True)
                with omegaconf.open_dict(mlxpy_config):
                    mlxpy_config.mlxpy.scheduler.name = files_input
                omegaconf.OmegaConf.set_struct(mlxpy_config, False)
                print(f"{bcolors.OKBLUE} Setting Scheduler to {files_input} {bcolors.ENDC}")
                break
            else:
                print(f"{bcolors.OKBLUE} {files_input} is not a valid class identifier. Please try again  {bcolors.ENDC}")
        else:
            break


def _ask_configure_scheduler(mlxpy_config,mlxpy_file):
    while True:
        
        print(f"{bcolors.OKGREEN} Would you like to select a default job scheduler now ? {bcolors.ENDC} {bcolors.OKGREEN}(y/n){bcolors.ENDC}:")
        print(f"{bcolors.OKGREEN}y{bcolors.ENDC}: The job scheduler configs will be stored in the file {mlxpy_file}")
        print(f"{bcolors.OKGREEN}n{bcolors.ENDC}: No scheduler will be selected by default.")
        choice = input(f"{bcolors.OKGREEN}Please enter your answer (y/n):{bcolors.ENDC}")


        if choice=='y':
            _configure_scheduler(mlxpy_config)
            break
        elif choice=='n':

            print(f"{bcolors.OKBLUE}No scheduler will be selected by default.{bcolors.ENDC}")
            print(f"{bcolors.OKBLUE}To use a scheduler, you will need to select one later.{bcolors.ENDC}")
            break
        else:
            print(f"{bcolors.OKBLUE}Invalid choice. Please try again. (y/n){bcolors.ENDC}")



def _build_config(overrides, config_path):

    cfg = _get_default_config(config_path,overrides)

    if 'mlxpy' in overrides:
        overrides_mlxpy = OmegaConf.create({'mlxpy':overrides['mlxpy']})
        cfg = OmegaConf.merge(cfg, overrides_mlxpy)
    overrides = convert_dict(overrides, 
                        src_class=omegaconf.dictconfig.DictConfig, 
                        dst_class=dict)
    if 'mlxpy' in overrides:
        overrides.pop('mlxpy')
    overrides = convert_dict(overrides, 
                        src_class=dict,
                        dst_class=omegaconf.dictconfig.DictConfig)

    config = OmegaConf.create({'config':overrides})
    cfg = OmegaConf.merge(cfg, config)

    cfg = convert_dict(cfg, 
                        src_class=omegaconf.dictconfig.DictConfig, 
                        dst_class=ConfigDict)

    return cfg



def _get_default_config(config_path,overrides):
    default_config = OmegaConf.structured(Metadata)
    conf_dict = OmegaConf.to_container(default_config, resolve=True)
    default_config = OmegaConf.create(conf_dict)
    
    os.makedirs(config_path, exist_ok=True)
    mlxpy_file = os.path.join(config_path,"mlxpy.yaml")

    if os.path.exists(mlxpy_file):
        with open(mlxpy_file, "r") as file:
            mlxpy = OmegaConf.create({'mlxpy':yaml.safe_load(file)})
        valid_keys = list(default_config['mlxpy'].keys())
        for key in mlxpy['mlxpy'].keys():
            try: 
                assert key in valid_keys 
            except AssertionError:
                msg =f'In the file {mlxpy_file},'
                msg += f'the following field is invalid: {key}\n'
                msg += f'Valid fields are {valid_keys}\n'
                raise AssertionError(msg)

        default_config = OmegaConf.merge(default_config, mlxpy)
    
    using_scheduler = default_config.mlxpy.use_scheduler
    scheduler_name_default = default_config.mlxpy.scheduler.name
    scheduler_name = scheduler_name_default
    interactive_mode = default_config.mlxpy.interactive_mode
    if 'mlxpy' in overrides:
        if 'use_scheduler' in overrides['mlxpy']:
            using_scheduler = overrides['mlxpy']['use_scheduler']
        if 'scheduler' in overrides['mlxpy']:
            if 'name' in overrides['mlxpy']['scheduler']:
                scheduler_name = overrides['mlxpy']['scheduler']
        if 'interactive_mode' in overrides['mlxpy']:
            interactive_mode = overrides['mlxpy']['interactive_mode']

    using_invalid_scheduler = scheduler_name=="NoScheduler" and using_scheduler
    update_default_conifg = False
    if scheduler_name=="NoScheduler":
        if using_scheduler or not os.path.exists(mlxpy_file):
            print(f"{bcolors.OKBLUE}No scheduler is configured by default {bcolors.ENDC}")
            if interactive_mode:
                print(f"{bcolors.OKBLUE}Entering interactive mode {bcolors.ENDC}")
                _ask_configure_scheduler(default_config,mlxpy_file)
                print(f"{bcolors.OKBLUE}Leaving interactive mode {bcolors.ENDC}")
                update_default_conifg = True
            else: 
                pass

    else:
        omegaconf.OmegaConf.set_struct(default_config, True)
        with omegaconf.open_dict(default_config):
            default_config.mlxpy.scheduler.name = scheduler_name
        omegaconf.OmegaConf.set_struct(default_config, False)
        if scheduler_name_default=="NoScheduler":
            update_default_conifg = True
            print(f"{bcolors.OKBLUE}Setting Scheduler to: {scheduler_name} {bcolors.ENDC}")

    if not os.path.exists(mlxpy_file) or update_default_conifg:
        print(f"{bcolors.OKBLUE}Default settings for mlxpy will be created in {mlxpy_file} {bcolors.ENDC}") 
        mlxpy = OmegaConf.create(default_config['mlxpy'])
        omegaconf.OmegaConf.save(config=mlxpy, f=mlxpy_file)

    return default_config


