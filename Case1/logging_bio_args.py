__doc__ = """This script is to train or run a policy for the arm following randomly moving target. 
Case 1 in CoRL 2020 paper."""
import os
import numpy as np
import sys

import argparse
import matplotlib
import matplotlib.pyplot as plt

# Import stable baseline
from stable_baselines3.common.monitor import Monitor, load_results
from stable_baselines3 import DDPG, PPO, TD3, SAC
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines3.common.results_plotter import ts2xy, plot_results
from stable_baselines3.common import results_plotter

# Import simulation environment
from set_environment import Environment
import gymnasium as gym


def get_valid_filename(s):
    import re

    s = str(s).strip().replace(" ", "_")
    return re.sub(r"(?u)[^-\w.]", "", s)


def moving_average(values, window):
    """
    Smooth values by doing a moving average
    :param values: (numpy array)
    :param window: (int)
    :return: (numpy array)
    """
    weights = np.repeat(1.0, window) / window
    return np.convolve(values, weights, "valid")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()

    ########### training and data info ###########
    parser.add_argument(
        "--total_timesteps", type=float, default=1e6,
    )

    parser.add_argument(
        "--SEED", type=int, default=0,
    )

    parser.add_argument(
        "--timesteps_per_batch", type=int, default=8000,
    )

    parser.add_argument(
        "--algo_name", type=str, default="TRPO",
    )

    args = parser.parse_args()

    if args.algo_name == "TRPO":
        MLP = "MlpPolicy"
        algo = TRPO
        batchsize = "timesteps_per_batch"
        offpolicy = False
    elif args.algo_name == "PPO":
        MLP = "MlpPolicy"
        algo = PPO
        batchsize = "n_steps"
        offpolicy = False
    elif args.algo_name == "DDPG":
        MLP = "MlpPolicy"
        algo = DDPG
        batchsize = "nb_rollout_steps"
        offpolicy = True
    elif args.algo_name == "TD3":
        MLP = "MlpPolicy"
        algo = TD3
        batchsize = "train_freq"
        offpolicy = True
    elif args.algo_name == "SAC":
        MLP = "MlpPolicy"
        algo = SAC
        batchsize = "train_freq"
        offpolicy = True

    # Mode 4 corresponds to randomly moving target
    args.mode = 4

    # Set simulation final time
    final_time = 10
    # Number of control points
    number_of_control_points = 6
    # target position
    target_position = [-0.4, 0.6, 0.2]
    # learning step skip
    num_steps_per_update = 7
    # alpha and beta spline scaling factors in normal/binormal and tangent directions respectively
    args.alpha = 75
    args.beta = 75

    sim_dt = 2.0e-4

    max_rate_of_change_of_activation = np.infty
    print("rate of change", max_rate_of_change_of_activation)

    # If True, train. Otherwise run trained policy
    args.TRAIN = True

    name = str(args.algo_name) + "_3d-tracking_id"
    identifer = name + "-" + str(args.timesteps_per_batch) + "_" + str(args.SEED)

    if args.TRAIN:
        log_dir = "./log_" + identifer + "/"
        os.makedirs(log_dir, exist_ok=True)

    from typing import Callable
    def make_env(rank: int, seed: int = 0) -> Callable:
        def _init() -> gym.Env:
            env = Environment(
                final_time=final_time,
                num_steps_per_update=num_steps_per_update,
                number_of_control_points=number_of_control_points,
                alpha=args.alpha,
                beta=args.beta,
                COLLECT_DATA_FOR_POSTPROCESSING=not args.TRAIN,
                mode=args.mode,
                target_position=target_position,
                target_v=0.5,
                boundary=[-0.6, 0.6, 0.3, 0.9, -0.6, 0.6],
                E=1e7,
                sim_dt=sim_dt,
                n_elem=20,
                NU=30/20.,
                num_obstacles=0,
                dim=3.0,
                max_rate_of_change_of_activation=max_rate_of_change_of_activation,
            )
            env = Monitor(env,log_dir+'/'+str(rank)+'_monitor.csv')
            env.reset(seed=1000*seed+rank)
            return env
        return _init

    #import psutil
    ##num_cpu = psutil.cpu_count(logical=False)
    #num_cpu = 32  # Number of processes to use
    #import os
    #os.environ["MP_NUM_THREAD"] =str(num_cpu)
    #os.environ["NUMBA_NUM_THREADS"]=str(num_cpu)
    #vec_env = SubprocVecEnv([make_env(i,args.SEED) for i in range(num_cpu)])
    vec_env = make_env(args.SEED)()


    if args.TRAIN:
        if offpolicy:
            if args.algo_name == "TD3":
                items = {
                    "policy": MLP,
                    "buffer_size": int(args.timesteps_per_batch),
                    "learning_starts": int(50e3),
                }
            else:
                items = {"policy": MLP, "buffer_size": int(args.timesteps_per_batch)}
        else:
            items = {
                "policy": MLP,
                batchsize: args.timesteps_per_batch,
            }

        #model = algo(env=vec_env, verbose=2, **items)
        #model.set_env(env)
        try:
            print("Trying to load policy")
            model = algo.load("bio_policy",env=vec_env, verbose=2, **items)
            print("Success")
        except Exception as ex:
            print(ex)
            model = algo(env=vec_env, verbose=2, **items)
        model.learn(total_timesteps=int(args.total_timesteps))
        model.save("bio_policy")
        # library helper
        plot_results(
            [log_dir],
            int(args.total_timesteps),
            results_plotter.X_TIMESTEPS,
            " muscle" + identifer,
        )
        plt.savefig("convergence_plot" + identifer + ".png")
        model.save("policy-" + identifer)

    else:
        # Use trained policy for the simulation.
        model = PPO.load("policy-" + identifer)
        
        env = make_env(args.SEED*1000)()
        obs, info_ = env.reset()

        done = False
        score = 0
        while not done:
            action, _states = model.predict(obs)
            obs, rewards, done, info = vec_env.step(action)
            score += rewards
            if info["ctime"] > final_time:
                break
        print("Final Score:", score)
        env.post_processing(
            filename_video="video-" + identifer + ".mp4", SAVE_DATA=True,
        )
