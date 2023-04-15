import copy
import os
import subprocess
import functools
import pickle
import warnings
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable, List, Optional, Union
from types import CodeType
from dataclasses import dataclass, field

import omegaconf
from omegaconf import OmegaConf, DictConfig, open_dict, read_write
from omegaconf import MISSING
from omegaconf.errors import OmegaConfBaseException
from enum import Enum

from hydra import version
from hydra._internal.deprecation_warning import deprecation_warning
from hydra._internal.utils import _run_hydra, get_args_parser
from hydra.core.hydra_config import HydraConfig
from hydra.types import TaskFunction


from experimentalist.utils import _flatten_dict, config_to_instance
from experimentalist.data_structures.schemas import Metadata
from experimentalist.data_structures.config_dict import convert_dict, ConfigDict

import sys

_UNSPECIFIED_: Any = object()


hydra_defaults_dict = {
    "hydra": {
        "mode": "MULTIRUN",
        "output_subdir": "null",
        "run": {"dir": "."},
        "sweep": {"dir": ".", "subdir": "."},
    },
    "hydra/job_logging": "disabled",
    "hydra/hydra_logging": "disabled",
}

class Status(Enum):
    """
        Status of a run. 

        The status can take the following values:

        - STARTING: The metadata for the run have been created.

        - RUNNING: The experiment is currently running. 
        
        - COMPLETE: The run is  complete and did not through any error.
        
        - FAILED: The run stoped due to an error.
    """


    STARTING = "STARTING"
    COMPLETE = "COMPLETE"
    RUNNING = "RUNNING"
    FAILED = "FAILED"



def launch(
    config_path: Optional[str] = _UNSPECIFIED_,
    config_name: Optional[str] = None,
    seeding_function: Union[Callable[Any, None],None] = None
) -> Callable[[TaskFunction], Any]:
    """Decorator of the main function to be executed.  

    This function allows three main functionalities: 
        - Composing configurations from multiple files using hydra (see hydra-core package). 
        This behavior is similar to the decorator hydra.main provided in the hydra-core package:
        https://github.com/facebookresearch/hydra/blob/main/hydra/main.py. 
        The configs are contained in a yaml file 'config_name' 
        within the directory 'config_path' passed as argument to this function. 
        Unlike hydra.main which decorates functions taking an OmegaConf object, 
        this decorator acts on functions with the following signature: main(logger: Logger).
        The logger object, can then be used to log outputs of the current run.
        Just like in hydra, it is also possible to override the configs from the command line and 
        to sweep over multiple values of a given configuration when executing python code.   
        See: https://hydra.cc/docs/intro/ for complete documentation on how to use Hydra.
    
        - Submitting jobs the a scheduler's queue in a cluster. 
        This is achieved by setting the config value scheduler.name to the name of the scheduler instead of None. 
        Two job schedulers are currently supported by default: ['OARScheduler', 'SLURMScheduler' ]. 
        It is possible to support other schedulers by 
        defining a subclass of the abstract class Scheduler.

        - Creating a 'safe' working directory when submitting jobs to a cluster. 
        This functionality sets the working directory to a new location 
        created by making a copy of the code based on the latest commit 
        to a separate destination, if it doesn't exist already. Executing code 
        from this copy allows separting development code from code deployed in a cluster. 
        It also allows recovering exactly the code used for a given run.
        This behavior can be modified by using a different working directory manager WDManager (default LastGitCommitWD). 
        
        .. note:: Currently, this functionality expects 
        the executed python file to part of the git repository. 

    :param config_path: The config path, a directory relative
                        to the declaring python file.
                        If config_path is None no directory is added
                        to the Config search path.
    :param config_name: The name of the config
                        (usually the file name without the .yaml extension)
    
    :type config_path: str
    :type config_name: str (default "None")
    """

    version_base= None # by default set the version base for hydra to None.
    version.setbase(version_base)

    if config_path is _UNSPECIFIED_:
        if version.base_at_least("1.2"):
            config_path = None
        elif version_base is _UNSPECIFIED_:
            url = "https://hydra.cc/docs/upgrades/\
                    1.0_to_1.1/changes_to_hydra_main_config_path"
            deprecation_warning(
                message=dedent(
                    f"""
                config_path is not specified in @hydra.main().
                See {url} for more information."""
                ),
                stacklevel=2,
            )
            config_path = "."
        else:
            config_path = "."
    
    os.makedirs(config_path, exist_ok=True)
    custom_config_file = os.path.join(config_path,config_name)
    if not os.path.exists(custom_config_file):
        custom_config = {'user_config':MISSING}
        omegaconf.OmegaConf.save(config=custom_config, f=custom_config_file)



    def hydra_decorator(task_function: TaskFunction) -> Callable[[], None]:
        # task_function = launch(task_function)
        @functools.wraps(task_function)
        def decorated_main(cfg_passthrough: Optional[DictConfig] = None) -> Any:
            if cfg_passthrough is not None:
                return task_function(cfg_passthrough)
            else:
                args_parser = get_args_parser()
                args = args_parser.parse_args()

                ### Setting hydra defaults 
                flattened_hydra_default_dict = _flatten_dict(hydra_defaults_dict)
                hydra_defaults = [
                    key + "=" + value
                    for key, value in flattened_hydra_default_dict.items()
                ]
                overrides = args.overrides + hydra_defaults
                setattr(args, "overrides", overrides)

                _run_hydra(
                    args=args,
                    args_parser=args_parser,
                    task_function=task_function,
                    config_path=config_path,
                    config_name=config_name,
                )

        return decorated_main

    def launcher_decorator(task_function):
        @functools.wraps(task_function)
        def decorated_task(cfg):
            cfg = _build_config(cfg, config_path, config_name)

            cfg.update_dict({'run_info': {'cmd':task_function.__code__.co_filename,
                                        'app': os.environ["_"]}})
            
            cfg.update_dict({'run_info':{'status':Status.STARTING.name}})

            if cfg.base_config.use_version_manager:
                version_manager = config_to_instance(config_module_name="name", **cfg.base_config.version_manager)
                work_dir = version_manager.make_working_directory()
                cfg.update_dict({'base_config':version_manager.get_configs()})
            else:
                work_dir = os.getcwd()

            if cfg.base_config.use_logger:
                logger = config_to_instance(config_module_name="name", **cfg.base_config.logger)
                log_id = logger.log_id
                log_dir = logger.log_dir
                parent_log_dir = logger.parent_log_dir
                cfg.update_dict({'run_info':{'log_id':log_id, 'log_dir':log_dir}})
            else:
                logger = None
            
            if cfg.base_config.use_scheduler:
                try:
                    assert logger
                except AssertionError:
                    raise Exception("To use the scheduler, you must also use a logger, otherwise results might not be stored!")
                scheduler = config_to_instance(config_module_name="name", **cfg.base_config.scheduler) 

                cmd = _make_job_command(scheduler,
                                        cfg.run_info,
                                        work_dir,
                                        parent_log_dir,
                                        log_dir,
                                        log_id)
                print(cmd)

                job_path = _save_job_command(cmd, log_dir)
                process_output = scheduler.submit_job(job_path)
                scheduler_job_id = scheduler.get_job_id(process_output) 

                cfg.update({'base_config':{'scheduler':{'scheduler_job_id':scheduler_job_id}}})


                logger._log_configs(cfg)
                
            else:
                ## Setting up the working directory
                os.chdir(work_dir)
                sys.path.insert(0, work_dir)
                cfg.update_dict({'run_info': {'work_dir':work_dir}})

                if logger:
                    
                    cfg.update_dict(
                        _get_scheduler_configs(log_dir,
                                                logger.config_file_name)) # Checks if a metadata file exists and loads the scheduler configs
                try:
                    
                    cfg.update_dict({'run_info':{'status':Status.RUNNING.name}})
                    if logger:
                        logger._log_configs(cfg)
                    if seeding_function:
                        try:
                            assert 'seed' in cfg.user_config.keys()
                        except AssertionError:
                            msg = "Missing field: The 'user_config' must contain a field 'seed'\n"
                            msg+= "provided as argument to the function 'seeding_function' "
                            raise Exception(msg)
                        seeding_function(cfg.user_config.seed)
                    task_function(cfg,logger)
                    cfg.update_dict({'run_info':{'status':Status.COMPLETE.name}})
                    
                    if logger:
                        logger._log_configs(cfg)
                    
                    return None
                except Exception:
                    cfg.update_dict({'run_info':{'status':Status.FAILED.name}})

                    if logger:
                        logger._log_configs(cfg)
                    raise

        _set_co_filename(decorated_task, task_function.__code__.co_filename)

        return decorated_task

    def composed_decorator(task_function: TaskFunction) -> Callable[[], None]:
        decorated_task = launcher_decorator(task_function)
        task_function = hydra_decorator(decorated_task)
        sweep_dir = hydra_defaults_dict["hydra"]["sweep"]["dir"]
        try:
            os.remove(os.path.join(sweep_dir, "multirun.yaml"))
        except FileNotFoundError:
            pass

        return task_function

    return composed_decorator


def _set_co_filename(func, co_filename):
    fn_code = func.__code__
    func.__code__ = CodeType(
        fn_code.co_argcount,
        fn_code.co_posonlyargcount,
        fn_code.co_kwonlyargcount,
        fn_code.co_nlocals,
        fn_code.co_stacksize,
        fn_code.co_flags,
        fn_code.co_code,
        fn_code.co_consts,
        fn_code.co_names,
        fn_code.co_varnames,
        co_filename,
        fn_code.co_name,
        fn_code.co_firstlineno,
        fn_code.co_lnotab,
        fn_code.co_freevars,
        fn_code.co_cellvars,
    )


def _get_scheduler_configs(log_dir, config_file_name):
    abs_name = os.path.join(log_dir, config_file_name +".yaml")
    scheduler_configs = {}
    import yaml
    if os.path.isfile(abs_name):
        with open(abs_name, "r") as file:
            configs = yaml.safe_load(file)
            scheduler_configs = {'base_config':{'scheduler':configs['base_config']['scheduler']}}
    return  scheduler_configs


def _make_job_command(scheduler,
                  run_info, 
                  work_dir,
                  parent_log_dir,
                  log_dir,
                  job_id,
                  ):
    ## Writing job command
    job_command = [_job_command(run_info,parent_log_dir, work_dir, job_id)]

    ## Setting shell   
    shell_cmd = [f"#!{scheduler.shell_path}\n"]
    
    ## Setting scheduler options
    sheduler_option_command = [scheduler.option_command(log_dir)]
    
    ## Setting environment
    env_cmds = [f"{scheduler.shell_config_cmd}\n", 
                f"{scheduler.cleanup_cmd}\n"]
    try:
        env_cmds += [f"{scheduler.env_cmd}\n"]
    except OmegaConfBaseException:
        pass

    cmd = "".join(shell_cmd + sheduler_option_command + env_cmds + job_command)

    return cmd


def _configure_experimentalist():
    raise NotImplementedError


def _build_config(cfg, config_path, config_name):
    default_config = OmegaConf.structured(Metadata)
    conf_dict = OmegaConf.to_container(default_config, resolve=True)
    default_config = OmegaConf.create(conf_dict)
    
    os.makedirs(config_path, exist_ok=True)
    base_config_file = os.path.join(config_path,"base_config.yaml")

    if os.path.exists(base_config_file):
        import yaml
        with open(base_config_file, "r") as file:
            base_config = OmegaConf.create({'base_config':yaml.safe_load(file)})
        valid_keys = ['logger','version_manager','scheduler',
                        'use_version_manager',
                        'use_logger',
                        'use_scheduler']
        for key in base_config['base_config'].keys():
            try: 
                assert key in valid_keys 
            except AssertionError:
                msg =f'In the file {base_config_file},'
                msg += f'the following field is invalid: {key}\n'
                msg += f'Valid fields are {valid_keys}\n'
                raise AssertionError(msg)

        default_config = OmegaConf.merge(default_config, base_config)
    
    else:
        #_configure_experimentalist(default_config)        
        base_config = OmegaConf.create(default_config['base_config'])

        omegaconf.OmegaConf.save(config=base_config, f=base_config_file)

    # for key in cfg.keys():
    #     try: 
    #         assert key in  default_config.keys()
    #     except AssertionError:
    #         msg = f'The following field is invalid: {key}\n'
    #         msg += f'Valid fields are {default_config.keys()}\n'
    #         msg += "Consider using 'user_config' field for user defined options"
    #         raise AssertionError(msg)

    cfg = OmegaConf.merge(default_config, cfg)

    cfg = convert_dict(cfg, 
                        src_class=omegaconf.dictconfig.DictConfig, 
                        dst_class=ConfigDict)
    cfg.set_starting_run_info()
    return cfg

def _save_job_command(cmd_string, log_dir):
    job_path = os.path.join(log_dir, "script.sh")
    with open(job_path, "w") as f:
        f.write(cmd_string)
    return job_path



def _job_command(run_info, parent_log_dir, work_dir, job_id):
    #exec_file = run_info.cmd
    exec_file = os.path.relpath(run_info.cmd, os.getcwd())
    

    args = _get_overrides()
    values = [
        f"cd {work_dir}",
        f"{run_info.app} {exec_file} {args} \
            ++base_config.logger.forced_log_id={job_id}\
            ++base_config.logger.parent_log_dir={parent_log_dir} \
            ++base_config.use_scheduler={False}\
            ++base_config.use_version_manager={False}"
    ]

    values = [f"{val}\n" for val in values]
    return "".join(values)

def _get_overrides():
    hydra_cfg = HydraConfig.get()
    overrides = hydra_cfg.overrides.task
    def filter_fn(x):
        return ("scheduler" not in x) and ("logger.parent_log_dir" not in x)
    filtered_args = list(filter(filter_fn, overrides))
    args = " ".join(filtered_args)
    return args
