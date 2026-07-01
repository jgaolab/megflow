#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a pseudo-MRI from MEG digitization points."""

import argparse
import json
from pathlib import Path

import nibabel as nib

from tools.pseudomri import PseudoMRIEngine

DEFAULT_TEMPLATE_SUBJECT = "mni_icbm152_nlin_sym_09a"
TEMPLATE_FILES = {
    "T1": "{subject}-T1.mgz",
    "fiducials": "{subject}-fiducials.fif",
    "outer_skin": "{subject}-outer_skin.surf",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a pseudo-MRI NIfTI from MEG digitization/headshape points."
    )
    parser.add_argument("--info_fif", required=True, help="MEG FIF file containing digitization points.")
    parser.add_argument("--subject", required=True, help="Output pseudo-MRI subject identifier.")
    parser.add_argument("--output_dir", required=True, help="Directory for the generated pseudo-MRI.")
    parser.add_argument(
        "--template_subject",
        default=DEFAULT_TEMPLATE_SUBJECT,
        help="Template name prefix under --template_dir/template.",
    )
    parser.add_argument(
        "--template_dir",
        default=None,
        help="Directory containing the pseudo-MRI template directory. Defaults to MEGFlow's bundled template.",
    )
    parser.add_argument("--mirror_hsps", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dense_surf", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--use_hpi", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--nmax_ctrl", type=int, default=200)
    return parser.parse_args()


def validate_template_files(template_dir: Path, template_subject: str):
    template_root = template_dir / "template"
    missing = [
        str(template_root / pattern.format(subject=template_subject))
        for pattern in TEMPLATE_FILES.values()
        if not (template_root / pattern.format(subject=template_subject)).exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"Pseudo-MRI template is incomplete under {template_root}. Missing: {missing}"
        )


def main():
    args = parse_args()
    info_fif = Path(args.info_fif).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    template_dir = (
        Path(args.template_dir).expanduser().resolve()
        if args.template_dir
        else Path(__file__).resolve().parent / "tools" / "pseudomri"
    )

    if not info_fif.exists():
        raise FileNotFoundError(f"MEG FIF file does not exist: {info_fif}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{args.subject}.nii.gz"
    validate_template_files(template_dir, args.template_subject)

    PseudoMRIEngine(
        fname_info=info_fif,
        pseudo_subj=args.subject,
        dir_anat_pseudo=output_dir,
        template_subj=args.template_subject,
        dir_anat_templ=template_dir,
        mirror_hsps=args.mirror_hsps,
        dense_surf=args.dense_surf,
        use_hpi=args.use_hpi,
        nmax_Ctrl=args.nmax_ctrl,
    )

    if not output_file.exists():
        raise RuntimeError(f"Pseudo-MRI generation did not produce expected file: {output_file}")

    image = nib.load(output_file)
    metadata = {
        "method": "pseudomri",
        "source_fif": str(info_fif),
        "subject": args.subject,
        "template_subject": args.template_subject,
        "template_dir": str(template_dir),
        "output_file": str(output_file),
        "shape": list(image.shape),
        "voxel_sizes": [float(value) for value in image.header.get_zooms()[:3]],
    }
    metadata_file = output_dir / "pseudomri_metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(f"Pseudo-MRI generated: {output_file}")
    print(f"Pseudo-MRI metadata: {metadata_file}")


if __name__ == "__main__":
    main()
