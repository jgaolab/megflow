import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import mne
import numpy as np
from mne_bids import BIDSPath


MEGFLOW_DIR = Path(__file__).resolve().parents[1] / "megflow"
if str(MEGFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(MEGFLOW_DIR))

from meg_import_dataset import read_meg_dataset


class MegImportDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        (self.root / "dataset_description.json").write_text(
            json.dumps({"Name": "Import regression fixture", "BIDSVersion": "1.7.0"}),
            encoding="utf-8",
        )

    def recording(self, *, root=None, extension=".fif", **entities):
        path = BIDSPath(
            root=root or self.root, datatype="meg", suffix="meg",
            extension=extension, **entities,
        )
        path.directory.mkdir(parents=True, exist_ok=True)
        if extension == ".ds":
            path.fpath.mkdir()
        else:
            path.fpath.touch()
        return path

    def discover(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return read_meg_dataset(self.root, dataset_format="bids", **kwargs)

    def assert_paths(self, actual, expected):
        self.assertEqual([str(path) for path in actual], sorted(str(path) for path in expected))

    def test_acquisitions_without_run_are_distinct_recordings(self):
        paths = [
            self.recording(subject="02", session="sleep", task="r4", acquisition=acq)
            for acq in ("04", "14")
        ]
        actual = self.discover()
        self.assert_paths(actual, paths)
        self.assertEqual([path.acquisition for path in actual], ["04", "14"])

    def test_processing_and_recording_entities_are_preserved(self):
        paths = [
            self.recording(subject="02", task="rest", processing=proc, recording=rec)
            for proc, rec in (("sss", "a"), ("sss", "b"), ("tsss", "a"))
        ]
        self.assert_paths(self.discover(), paths)

    def test_optional_session_and_run_are_not_lost_or_duplicated(self):
        paths = [
            self.recording(subject="01", task="rest"),
            self.recording(subject="02", session="sleep", task="rest"),
            self.recording(subject="02", session="sleep", task="rest", run="01"),
            self.recording(subject="03", session="awake", task="movie", run="02"),
        ]
        self.assert_paths(self.discover(), paths)

    def test_existing_entity_filters_keep_all_matching_acquisitions(self):
        selected = [
            self.recording(subject="02", session="sleep", task="r4", run="01", acquisition=acq)
            for acq in ("04", "14")
        ]
        self.recording(subject="01", task="rest")
        self.recording(subject="03", task="rest")
        self.recording(subject="02", session="sleep", task="r4", run="02")
        self.recording(subject="02", session="awake", task="r4", run="01")
        self.recording(subject="02", session="sleep", task="r5", run="01")
        self.assert_paths(
            self.discover(subjects=["02"], sessions="sleep", tasks=["r4"], runs="01"), selected,
        )
        first = self.discover(subjects="first:2")
        self.assertEqual({path.subject for path in first}, {"01", "02"})

    def test_sidecars_calibration_and_nested_dataset_trees_are_excluded(self):
        selected = self.recording(subject="02", session="sleep", task="r4")
        selected.copy().update(extension=".json").fpath.touch()
        selected.copy().update(suffix="events", extension=".tsv").fpath.touch()
        self.recording(subject="02", session="sleep", acquisition="crosstalk")
        self.recording(subject="02", session="sleep", acquisition="calibration", extension=".dat")
        for tree in ("derivatives", "sourcedata"):
            self.recording(root=self.root / tree / "pipeline", subject="03", task="rest")
        self.assert_paths(self.discover(), [selected])

    def test_ctf_directories_are_discovered_with_full_entities(self):
        paths = [self.recording(subject="01", task="rest", acquisition=acq, extension=".ds")
                 for acq in ("a", "b")]
        for path in paths:
            (path.fpath / f"{path.basename}.meg4").touch()
        self.assert_paths(self.discover(), paths)

    def test_bti_directories_are_discovered_with_full_entities(self):
        paths = []
        for acq in ("a", "b"):
            path = BIDSPath(root=self.root, subject="01", task="rest", acquisition=acq,
                            datatype="meg", suffix="meg", extension=".pdf")
            path.fpath.mkdir(parents=True)
            (path.fpath / "c,rfDC").touch()
            (path.fpath / "config").touch()
            paths.append(path)
        self.assert_paths(self.discover(), paths)

    def test_emptyroom_subject_requires_explicit_selection(self):
        selected = self.recording(subject="01", task="rest")
        emptyroom = self.recording(subject="emptyroom", session="20260924", task="noise")
        self.assert_paths(self.discover(), [selected])
        self.assert_paths(self.discover(subjects="emptyroom"), [emptyroom])

    def test_neuromag_split_continuations_are_not_separate_recordings(self):
        selected = self.recording(subject="02", task="rest", acquisition="04")
        selected.fpath.with_name(selected.fpath.stem + "-1.fif").touch()
        self.assert_paths(self.discover(), [selected])

    def test_bids_split_fif_is_imported_once_per_acquisition(self):
        selected = []
        for acq in ("04", "14"):
            for split in ("01", "02"):
                path = self.recording(subject="02", session="sleep", task="r4", acquisition=acq, split=split)
                if split == "01":
                    selected.append(path)
        self.assert_paths(self.discover(), selected)

    def test_missing_first_split_fails_instead_of_loading_partial_recording(self):
        self.recording(subject="02", task="rest", acquisition="04", split="02")
        with self.assertRaisesRegex(ValueError, "first split.*sub-02_task-rest_acq-04"):
            self.discover()

    def test_no_matching_bids_recordings_is_an_explicit_error(self):
        self.recording(subject="02", task="rest")
        with self.assertRaisesRegex(ValueError, "No BIDS MEG recordings"):
            self.discover(subjects="99")

    def test_cli_exports_both_acquisitions_without_ambiguity(self):
        paths = [self.recording(subject="02", session="sleep", task="r4", acquisition=acq)
                 for acq in ("04", "14")]
        output = self.root / "imported_meg_data.txt"
        result = subprocess.run(
            [sys.executable, str(MEGFLOW_DIR / "meg_import_dataset.py"),
             "--dataset_dir", str(self.root), "--dataset_format", "auto",
             "--output_file", str(output), "--config", '{"subject_id": "02"}'],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("BIDS Parse Error", result.stdout)
        self.assertEqual(output.read_text().splitlines(), sorted(str(path) for path in paths))

    def test_discovered_fif_paths_load_the_correct_acquisition_samples(self):
        for acq, value in (("04", 1e-12), ("14", 2e-12)):
            path = self.recording(subject="02", session="sleep", task="r4", acquisition=acq)
            raw = mne.io.RawArray(np.full((2, 500), value), mne.create_info(2, 100, "mag"), verbose=False)
            raw.save(path.fpath, overwrite=True, verbose=False)
        paths = self.discover()
        self.assertEqual(len(paths), 2)
        for path in paths:
            raw = mne.io.read_raw_fif(path.fpath, preload=True, verbose=False)
            expected = 1e-12 if path.acquisition == "04" else 2e-12
            np.testing.assert_allclose(raw.get_data(), expected, rtol=1e-6, atol=0)

    def test_real_split_fif_loads_all_samples_from_single_import_entry(self):
        path = self.recording(subject="02", task="rest", acquisition="04")
        data = np.random.default_rng(42).standard_normal((4, 100000)) * 1e-12
        raw = mne.io.RawArray(data, mne.create_info(4, 1000, "mag"), verbose=False)
        path.fpath.unlink()
        raw.save(path.fpath, split_naming="bids", split_size="2MB",
                 buffer_size_sec=0.1, verbose=False)
        self.assertGreater(len(list(path.directory.glob("*_split-*_meg.fif"))), 1)
        paths = self.discover()
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].split, "01")
        loaded = mne.io.read_raw_fif(paths[0].fpath, preload=True, verbose=False)
        self.assertEqual(loaded.n_times, raw.n_times)
        np.testing.assert_allclose(loaded.get_data(), data, rtol=1e-6, atol=0)

    def test_raw_discovery_retains_keyword_and_output_exclusions(self):
        keep = self.root / "subject_rest_raw.fif"
        keep.touch()
        (self.root / "subject_emptyroom_raw.fif").touch()
        output = self.root / "output"
        output.mkdir()
        (output / "subject_rest_clean_raw.fif").touch()
        actual = read_meg_dataset(
            self.root, dataset_format="raw", raw_include_keywords=["raw"],
            raw_exclude_keywords=["emptyroom"], raw_exclude_dirs=[output],
        )
        self.assertEqual(actual, [str(keep)])


if __name__ == "__main__":
    unittest.main()
