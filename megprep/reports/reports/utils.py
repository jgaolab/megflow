# !/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import mne
import pandas as pd
import numpy as np
def in_docker():
    return os.path.exists('/.dockerenv')


def filter_files_by_keyword(files, keyword):
    """Filter files by keyword (case-insensitive)"""
    if not keyword or keyword.strip() == "":
        return files
    keyword_lower = keyword.strip().lower()
    return [f for f in files if keyword_lower in f.lower()]


def merge_and_deduplicate_annotations(annotations1, annotations2,orig_time):
    """
    Merge two Annotations objects and remove duplicates.

    Parameters:
    annotations1 (mne.Annotations): The first Annotations object.
    annotations2 (mne.Annotations): The second Annotations object.

    Returns:
    mne.Annotations: A new Annotations object that is merged and deduplicated.
    """

    # Merge the data from the two Annotations objects
    merged_onsets = np.concatenate([annotations1.onset, annotations2.onset])
    merged_durations = np.concatenate([annotations1.duration, annotations2.duration])
    merged_descriptions = np.concatenate([annotations1.description.astype(str), annotations2.description.astype(str)])

    # Use a Pandas DataFrame to handle deduplication
    data = pd.DataFrame({
        'onset': merged_onsets,
        'duration': merged_durations,
        'description': merged_descriptions
    })

    # Remove duplicates based on the 'onset' column
    data_unique = data.drop_duplicates(subset=['onset'])

    # Create a new Annotations object from the deduplicated DataFrame
    cleaned_annotations = mne.Annotations(
        onset=data_unique['onset'].tolist(),
        duration=data_unique['duration'].tolist(),
        description=data_unique['description'].tolist(),
        orig_time=orig_time
    )

    return cleaned_annotations