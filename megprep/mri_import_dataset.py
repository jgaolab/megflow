#! /usr/bin/env python3
import os
import yaml
import argparse
from bids import BIDSLayout
import warnings
warnings.filterwarnings('ignore', category=UserWarning)

def process_bids(bids_dir, output_file, config):
    """Process BIDS directory to retrieve T1w files for specified subject IDs."""
    print("Loading T1w BIDS files...")
    # ignore_dirs = ['derivatives', 'code']
    # layout = BIDSLayout(root=bids_dir,derivatives=False,ignore=ignore_dirs)
    print("config:",config)

    ignore_pattern = [r'(?!sub-).*']
    layout = BIDSLayout(bids_dir, derivatives=False, ignore=ignore_pattern)
    subject_dict = {}

    print("Loading subject IDs...")

    if config is not None:
        filters = {
            'subject': config.get('subject_id'),
            'session': config.get('session_id'),
            'task': config.get('task'),
            'run': config.get('run_id')
        }

        filters = {key: value for key, value in filters.items() if value is not None}
    else:
        filters = {}

    # Fetch T1w files and organize them by subject ID
    for t1w_file in layout.get(return_type='filename',
                               suffix="T1w",
                               extension='nii.gz',
                               **filters
                               ):
        print(t1w_file)
        sub_info = layout.parse_file_entities(t1w_file)
        subject_id = f"sub-{sub_info['subject']}"
        subject_dict.setdefault(subject_id, []).append(t1w_file)
        print("Fetch subject:", subject_id)

    with open(output_file, 'w') as f:
        for subject_id, t1w_files in subject_dict.items():
            # Write the subject ID followed by its T1w file paths, each on a new line
            f.write(f"{subject_id}:{t1w_files}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Read MRI datasets in BIDS or raw format."
    )

    parser.add_argument("--bids_dir", help="directory of BIDS type", required=True)
    parser.add_argument("--output_file", type=str, required=True,
                        help="Output file to save the T1w list of file paths.")
    parser.add_argument('--config', type=str, default="{}", help='YAML configuration parameters')
    args = parser.parse_args()

    # debug
    # args.config = """
    #     # Filter out specific anatomy, only bids support.
    #     subject_id: null
    #     session_id: null
    #     task: null
    #     run_id: null
    # """
    config = yaml.safe_load(args.config)

    # # deepprep: get the parameters
    # try:
    #     redis_manager = RedisGlobalVariableManager()
    #     redis_manager.set_global_variable("MRI_IMPORT_CONFIG", args.config)
    #     my_variable = redis_manager.get_global_variable("MRI_IMPORT_CONFIG")
    # except Exception as e:
    #     print(e)

    process_bids(args.bids_dir, args.output_file, config)