# !/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Replace the `recon-all` of Freesurfer
# https://deepprep.readthedocs.io/en/latest/usage_local.html
# usage: deepprep-docker [bids_dir] [output_dir] [{participant}] [--bold_task_type '[task1 task2 task3 ...]']
#                        [--fs_license_file PATH] [--participant_label '[001 002 003 ...]']
#                        [--subjects_dir PATH] [--skip_bids_validation]
#                        [--anat_only] [--bold_only] [--bold_sdc] [--bold_confounds] [--bold_skip_frame 0]
#                        [--bold_cifti] [--bold_surface_spaces '[None fsnative fsaverage fsaverage6 ...]']
#                        [--bold_volume_space {None MNI152NLin6Asym MNI152NLin2009cAsym}] [--bold_volume_res {02 03...}]
#                        [--device { {auto 0 1 2...} cpu}]
#                        [--cpus 10] [--memory 20]
#                        [--ignore_error] [--resume]

# $ docker run -it --rm \
#              -v <test_sample_path>:/input \
#              -v <output_dir>:/output \
#              -v <fs_license_file>:/fs_license.txt \
#              pbfslab/deepprep:25.1.0 \
#              /input \
#              /output \
#              participant \
#              --skip_bids_validation \
#              --anat_only \
#              --fs_license_file /fs_license.txt \
#              --device cpu

import argparse
import subprocess


def run_deepprep(input_dir, output_dir, license_file, device):
    docker_command = [
        "docker", "run", "-it", "--rm",
        "-v", f"{input_dir}:/input",
        "-v", f"{output_dir}:/output",
        "-v", f"{license_file}:/fs_license.txt",
        "pbfslab/deepprep:25.1.0.beta.1",
        "/input", "/output", "participant",
        "--skip_bids_validation",
        "--anat_only",
        "--fs_license_file", "/fs_license.txt",
        "--device", device
    ]

    try:
        subprocess.run(docker_command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running Docker command: {e}")
        exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run DeepPrep inside Docker using Nextflow-compatible Python script.")
    parser.add_argument("--input_dir", required=True, help="Path to the input directory containing MEG data.")
    parser.add_argument("--output_dir", required=True, help="Path to the output directory for results.")
    parser.add_argument("--license_file", required=True, help="Path to the FreeSurfer license file.")
    parser.add_argument("--device", default="cpu", help="Specify the computing device (cpu or gpu). Default is cpu.")

    args = parser.parse_args()

    run_deepprep(args.input_dir, args.output_dir, args.license_file, args.device)

