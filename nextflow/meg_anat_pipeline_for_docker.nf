#!/usr/bin/env nextflow
// Run with a project-specific config, for example:
// nextflow run nextflow/meg_anat_pipeline_for_docker.nf -c nextflow/nextflow.config
nextflow.enable.dsl=2

import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import java.security.MessageDigest
// include { deepprep } from '/opt/DeepPrep/deepprep/nextflow/deepprep.nf'

log.info "MEGPrep Anatomy and MEG Preprocessing Pipeline"
log.info "============================="
log.info ""
log.info "Start time: $workflow.start"
log.info ""

workflow.onComplete {
    log.info "Pipeline completed at: $workflow.complete"
    log.info "Execution status: ${ workflow.success ? 'OK' : 'failed' }"
    log.info "Execution duration: $workflow.duration"
}

String fileSha256(def pathValue) {
    def target = new File(pathValue.toString())
    if (!target.exists()) {
        return "missing:${target.absolutePath}"
    }
    if (target.isDirectory()) {
        return "dir:${target.absolutePath}:${target.lastModified()}"
    }
    def digest = MessageDigest.getInstance("SHA-256")
    target.withInputStream { stream ->
        byte[] buffer = new byte[8192]
        int read
        while ((read = stream.read(buffer)) > 0) {
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().collect { String.format("%02x", it & 0xff) }.join()
}

String filesSha256(List paths) {
    return paths.collect { pathValue -> "${pathValue}:${fileSha256(pathValue)}" }.join("|")
}

process generate_cohort_static_html_report {
    tag "cohort-static-html-report"

    input:
    path dataset_markers

    output:
    path "cohort_static_html_report_done.txt", emit: completion_marker

    script:
    report_script = "${params.code_dir}/reports/cohort_static_html_report.py"
    cohort_root = "${params.output_dir}/datasets"
    report_output_dir = "${params.output_dir}/cohort_static_html_report"
    """
    set -euo pipefail
    python "${report_script}" \\
        --cohort_root "${cohort_root}" \\
        --output_dir "${report_output_dir}"

    echo "Cohort static HTML report generated at ${report_output_dir}" > cohort_static_html_report_done.txt
    """
}

process import_MRI_dataset {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), path('imported_t1_data.txt'), emit: imported_t1_data

    script:
    script_name = "${params.code_dir}/mri_import_dataset.py"
    """
    mkdir -p "${preproc_dir}"
    python ${script_name} \\
        --bids_dir "${t1_dir}" \\
        --config "${params.mri_import_config}" \\
        --output_file imported_t1_data.txt
    """
}

process dcm2niix {
    tag "${dataset_name}:${t1_dicom_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(t1_dicom_dir)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), path("converted"), emit: nifti_dirs

    script:
    t1_dicom_basename = file(t1_dicom_dir).getName()
    series_glob = (params.t1_dicom_series_glob ?: '').toString()
    """
    set -euo pipefail
    mkdir -p converted

    input_dir="${t1_dicom_dir}"
    series_glob="${series_glob}"

    echo "Starting DICOM to NIfTI conversion for directory: \${input_dir}"
    if [ -n "\${series_glob}" ]; then
        echo "Filtering DICOM series with relative glob: \${series_glob}"
        mapfile -d '' series_dirs < <(find "\${input_dir}" -type d -path "\${input_dir}/\${series_glob}" -print0 | sort -z)
    else
        series_dirs=("\${input_dir}")
    fi

    if [ "\${#series_dirs[@]}" -eq 0 ]; then
        echo "No DICOM series directories found under \${input_dir}" >&2
        exit 1
    fi

    index=0
    for series_dir in "\${series_dirs[@]}"; do
        index=\$((index + 1))
        safe_name=\$(basename "\${series_dir}" | tr -c 'A-Za-z0-9_.-' '_')
        echo "Converting DICOM series: \${series_dir}"
        dcm2niix -o converted -z y -f "${t1_dicom_basename}_\${index}_\${safe_name}_%p_%s" "\${series_dir}"
    fi

    nifti_count=\$(find converted -maxdepth 1 -type f \\( -name '*.nii' -o -name '*.nii.gz' \\) | wc -l | tr -d ' ')
    if [ "\${nifti_count}" -eq 0 ]; then
        echo "dcm2niix did not produce any NIfTI files for \${input_dir}" >&2
        exit 1
    fi

    find converted -maxdepth 1 -type f \\( -name '*.nii' -o -name '*.nii.gz' \\) -print | sort
    echo "Finished DICOM to NIfTI conversion."
    """
}

process run_freesurfer {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(anat_file), val(subject_name)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val("${fs_subjects_dir}/${subject_name}"), emit: fs_subjects

    script:
    """
    mkdir -p "${fs_subjects_dir}"
    recon-all -sd "${fs_subjects_dir}" -all -i "${anat_file}" -s "${subject_name}"
    recon-all -sd "${fs_subjects_dir}" -all -s "${subject_name}" -3T -openmp 4
    mkheadsurf -sd "${fs_subjects_dir}" -s "${subject_name}" -srcvol T1.mgz -thresh1 30
    """
}

process run_deepprep {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(subject_name)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val("${fs_subjects_dir}/${subject_name}"), emit: fs_subjects

    script:
    output_dir = "${preproc_dir}/deepprep"
    """
    mkdir -p "${fs_subjects_dir}" "${output_dir}"
    /opt/DeepPrep/deepprep/deepprep.sh "${t1_dir}" "${output_dir}" participant \\
        --participant_label "${subject_name}" \\
        --skip_bids_validation \\
        --anat_only \\
        --fs_license_file /fs_license.txt \\
        --device ${params.deepprep_device} \\
        --mri_import_config "${params.mri_import_config}" \\
        --resume

    kill -9 \$(pgrep redis-server) || true
    cp -rf "${output_dir}/Recon/"* "${fs_subjects_dir}/"
    """
}

process run_mkheadsurf {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), emit: fs_subjects

    script:
    """
    mkheadsurf -sd "${fs_subjects_dir}" -s "${subject_name}" -srcvol T1.mgz -thresh1 30
    """
}

process generate_bem {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), emit: bem_subjects

    script:
    script_name = "${params.code_dir}/generate_bem.py"
    subject_basename = file(subject_dir).getBaseName()
    """
    python3 ${script_name} \\
        --subject_dir "${subject_dir}" \\
        --config "${params.bem_config}" \\
        --output_dir "${fs_subjects_dir}/${subject_basename}/bem"
    """
}

process import_MEG_dataset {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir)
    val dataset_format
    val file_suffix

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), path('imported_meg_data.txt'), emit: imported_meg_data

    script:
    script_name = "${params.code_dir}/meg_import_dataset.py"
    """
    mkdir -p "${preproc_dir}"
    python ${script_name} \\
        --dataset_dir "${dataset_dir}" \\
        --dataset_format ${dataset_format} \\
        --file_suffix ${file_suffix} \\
        --output_file imported_meg_data.txt \\
        --exclude_output_dir "${output_dir}" \\
        --exclude_preproc_dir "${preproc_dir}" \\
        --config "${params.meg_import_config}"
    """
}

process meg_preproc_osl {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 6.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val("${preproc_dir}/${raw_subject_basename}/${raw_subject_basename}_preproc-raw.fif"), emit: preproc_subjects

    script:
    script_name = "${params.code_dir}/meg_preproc_osl.py"
    raw_subject_basename = file(orig_raw_path).getBaseName()
    """
    python ${script_name} \\
        --file "${orig_raw_path}" \\
        --preproc_dir "${preproc_dir}" \\
        --seed ${params.osl_random_seed} \\
        --config "${params.preproc_config}"
    """
}

process detect_Artifacts {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path), val("${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_channels.txt"), val("${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_segments.txt"), emit: artifacts

    script:
    script_name = "${params.code_dir}/meg_detect_artifacts.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_parent = file(preproc_raw_path).getParent().getName()
    """
    mkdir -p "${preproc_dir}/artifact_report/${raw_subject_parent}"
    python ${script_name} \\
        --input "${preproc_raw_path}" \\
        --output "${preproc_dir}/artifact_report/${raw_subject_parent}" \\
        --config "${params.artifact_config}"
    """
}

process run_ICA {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 8.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val("${preproc_dir}/${params.ICA_output_dir}/${raw_subject_dir_basename}/ica_sources.fif"), val("${preproc_dir}/${params.ICA_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif"), emit: ica_subjects

    script:
    script_name = "${params.code_dir}/run_ica.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    compute_explained_variance = params.ica_compute_explained_variance ?: false
    """
    python ${script_name} \\
        --raw_file "${preproc_raw_path}" \\
        --output_dir "${preproc_dir}/${params.ICA_output_dir}" \\
        --num_IC ${params.num_IC} \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}" \\
        --seed ${params.ICA_random_seed} \\
        --compute_explained_variance ${compute_explained_variance}
    """
}

process run_IC_label {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(ica_source), val(ica_file_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val("${preproc_dir}/${params.ICA_output_dir}/${raw_subject_dir_basename}/marked_components.txt"), emit: labelled_subjects

    script:
    script_name = "${params.code_dir}/run_ica_label.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    """
    python ${script_name} \\
        --raw_data_path "${preproc_raw_path}" \\
        --ica_file "${ica_file_path}" \\
        --output_dir "${preproc_dir}/${params.ICA_output_dir}" \\
        --config "${params.ic_label_config}"
    """
}

process apply_ICA {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(marked_components), val(marked_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val("${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif"), val("${target_mri_subject_id}"), val("${artifact_hash}|${marked_hash}"), emit: clean_subjects

    script:
    script_name = "${params.code_dir}/apply_ica.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    target_mri_subject_id = raw_subject_basename.split('_')[0] + params.anatomy_select_tag
    """
    python ${script_name} \\
        --raw_file "${preproc_raw_path}" \\
        --ica_file "${preproc_dir}/${params.ICA_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif" \\
        --exclude_file "${marked_components}" \\
        --output_file "${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif" \\
        --output_dir "${preproc_dir}/${params.ICA_output_dir}/${raw_subject_dir_basename}" \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}"
    """
}

process epochs {
    tag "${subject_key[0]}:${subject_key[1]}"

    input:
    tuple val(subject_key), val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(orig_raw_path), val(analysis_raw_path), val(target_mri_subject_id), val(clean_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val("${preproc_dir}/${params.epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif"), val(analysis_raw_path), val(clean_hash), emit: epoch_subjects

    script:
    script_name = "${params.code_dir}/epochs.py"
    raw_subject_basename = file(analysis_raw_path).getBaseName()
    raw_subject_dir_basename = file(analysis_raw_path).getParent().getName()
    filtered_raw_subject_basename = file(orig_raw_path).getBaseName().replace("_meg_preproc-raw_clean_raw", "").replace("_meg_preproc-raw", "")
    events_file = orig_raw_path.toString().replaceAll(/_meg\..*/, '_events.tsv')
    """
    mkdir -p "${preproc_dir}/${params.epoch_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --preproc_raw_file "${analysis_raw_path}" \\
        --events_file "${events_file}" \\
        --output_epoch_file "${raw_subject_basename}-epo.fif" \\
        --output_dir "${preproc_dir}/${params.epoch_output_dir}/${raw_subject_dir_basename}" \\
        --config "${params.epoch_config}"
    """
}

process compute_covariance {
    tag "${subject_key[0]}:${subject_key[1]}"

    input:
    tuple val(subject_key), val(dataset_name), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(raw_subject_path), val(raw_data_file), val(clean_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val("${preproc_dir}/${params.covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif"), val(clean_hash), emit: cov_subjects

    script:
    script_name = "${params.code_dir}/compute_covariance.py"
    raw_subject_dir_basename = file(raw_subject_path).getParent().getName()
    """
    python ${script_name} \\
        --raw_data_file "${raw_data_file}" \\
        --output_dir "${preproc_dir}/${params.covar_output_dir}/${raw_subject_dir_basename}" \\
        --visualize ${params.covar_visualize} \\
        --covar_type ${params.covar_type} \\
        --config "${params.covar_config}"
    """
}

process coregistration {
    tag "${subject_key[0]}:${subject_key[1]}"
    time '1h'

    input:
    tuple val(subject_key), val(dataset_name), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(target_mri_subject_id), val(clean_raw_path), val(clean_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val("${preproc_dir}/${params.trans_output_dir}/${raw_subject_dir_basename}/coreg-trans.fif"), val(clean_hash), emit: trans_subjects

    script:
    script_name = "${params.code_dir}/coregistration.py"
    raw_subject_basename = file(clean_raw_path).getBaseName()
    raw_subject_dir_basename = file(clean_raw_path).getParent().getName()
    mri_subject_id = target_mri_subject_id ?: raw_subject_basename.split('_')[0]
    """
    python ${script_name} \\
        --raw_file "${clean_raw_path}" \\
        --subjects_dir "${fs_subjects_dir}/${mri_subject_id}" \\
        --visualize ${params.meg_visualize} \\
        --output_dir "${preproc_dir}/${params.trans_output_dir}/${raw_subject_dir_basename}" \\
        --config "${params.core_config}"
    """
}

process forward_solution {
    tag "${key[0]}:${key[1]}"

    input:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(trans_path), val(coreg_clean_hash), val(trans_hash), val(epoch_output_dir), val(epoch_preproc_dir), val(epoch_fs_subjects_dir), val(epoch_path), val(clean_raw_path), val(epoch_clean_hash)

    output:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val("${preproc_dir}/${params.fwd_output_dir}/${raw_subject_dir_basename}/${raw_subject_dir_basename}-fwd.fif"), val(epoch_path), val(clean_raw_path), val(trans_hash), val(epoch_clean_hash), emit: fwd_subjects

    script:
    dataset_name = key[0]
    raw_subject_dir_basename = key[1]
    script_name = "${params.code_dir}/forward_solution.py"
    mri_subject_id = raw_subject_dir_basename.split('_')[0]
    mri_subject_dir = "${fs_subjects_dir}/${mri_subject_id}"
    """
    mkdir -p "${preproc_dir}/${params.fwd_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --epoch_file "${epoch_path}" \\
        --epoch_label ${params.fwd_epoch_label}  \\
        --output_dir "${preproc_dir}/${params.fwd_output_dir}/${raw_subject_dir_basename}" \\
        --trans_file "${trans_path}" \\
        --mri_subject_dir "${mri_subject_dir}" \\
        --config "${params.fwd_config}"
    """
}

process source_imaging {
    tag "${key[0]}:${key[1]}"

    input:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(fwd_file), val(epoch_path), val(clean_raw_path), val(trans_hash), val(epoch_clean_hash), val(cov_output_dir), val(cov_preproc_dir), val(bl_cov_file), val(cov_clean_hash)

    output:
    tuple val(key), val(output_dir), val(preproc_dir), val("${preproc_dir}/${params.src_output_dir}/${raw_subject_dir_basename}"), emit: source_subjects

    script:
    dataset_name = key[0]
    raw_subject_dir_basename = key[1]
    raw_subject_path = params.src_type == 'epochs' ? epoch_path : clean_raw_path
    if (!(params.src_type in ['epochs', 'raw'])) {
        error "Invalid src_type: ${params.src_type}. Please specify 'epochs' or 'raw'."
    }
    script_name = "${params.code_dir}/source_localization.py"
    """
    mkdir -p "${preproc_dir}/${params.src_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --data_mode ${params.src_type} \\
        --data_file "${raw_subject_path}"  \\
        --fs_subjects_dir "${fs_subjects_dir}" \\
        --output_dir "${preproc_dir}/${params.src_output_dir}/${raw_subject_dir_basename}" \\
        --forward_dir "${preproc_dir}/${params.fwd_output_dir}" \\
        --visualize ${params.meg_visualize} \\
        --noise_covariance_dir "${preproc_dir}/${params.covar_output_dir}" \\
        --config "${params.src_config}"
    """
}

process generate_static_html_report {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(source_artifacts)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), path("static_html_report_${dataset_name}.done"), emit: dataset_reports

    script:
    report_script = "${params.code_dir}/reports/static_html_report.py"
    manifest_json = JsonOutput.prettyPrint(JsonOutput.toJson([
        manifest_schema_version: 2,
        steps_raw: (params.steps ?: 'meg_all').toString(),
        parsed: parseMegPipelineSteps(params.steps ?: 'meg_all'),
        params_snapshot: [
            dataset_name: dataset_name,
            output_dir: output_dir,
            preproc_dir: preproc_dir,
            code_dir: params.code_dir?.toString(),
            fs_subjects_dir: params.fs_subjects_dir?.toString(),
            dataset_format: params.dataset_format?.toString(),
            covar_type: params.covar_type?.toString(),
            src_type: params.src_type?.toString(),
            is_bids: params.is_bids
        ],
        workflow_meta: [
            session_id: workflow.sessionId?.toString() ?: '',
            run_name: workflow.runName?.toString() ?: '',
            start: workflow.start?.toString() ?: '',
            nextflow_version: workflow.nextflow?.version?.toString() ?: '',
            launch_dir: workflow.launchDir?.toString() ?: '',
            project_dir: workflow.projectDir?.toString() ?: ''
        ]
    ]))
    """
    set -euo pipefail
    mkdir -p "${preproc_dir}/logs"
    cat > "${preproc_dir}/logs/megprep_run_manifest.json" <<'EOF_MANIFEST'
${manifest_json}
EOF_MANIFEST

    python "${report_script}" \\
        --report_root "${preproc_dir}" \\
        --output_dir "${output_dir}/static_html_report" \\
        --bad_channel_threshold ${params.bad_channel_threshold} \\
        --bad_segment_threshold ${params.bad_segment_threshold} \\
        --coreg_mean_threshold ${params.coreg_mean_threshold} \\
        --coreg_max_threshold ${params.coreg_max_threshold} \\
        --epoch_reject_rate_threshold ${params.epoch_reject_rate_threshold} \\
        --artifact_overview_duration ${params.static_artifact_overview_duration} \\
        --task_log_mode "${params.static_task_log_mode}" \\
        --zip_output false

    echo "Static HTML report generated at ${output_dir}/static_html_report" > "static_html_report_${dataset_name}.done"
    """
}

import java.nio.file.Path
class AnatOutput {
    String mri_subject_id
    Path fs_subjects_dir

    // Keep anatomy outputs available for both channel-backed and pre-existing anatomy modes.
    AnatOutput(String mri_subject_id, Path fs_subjects_dir) {
        this.mri_subject_id = mri_subject_id
        this.fs_subjects_dir = fs_subjects_dir
    }
}



/**
 * Parse params.steps into pipeline flags.
 * Primary: report | anatomy | all | meg_all | meg_artifacts | meg_ica | meg_epochs (aliases: meg, artifacts, ica, epochs)
 * Modifiers: skip_ica (meg_epochs only), with_anatomy (meg_* only; not meg_all)
 */
Map parseMegPipelineSteps(String stepsRaw) {
    def parts = stepsRaw.split(',').collect { it.trim().toLowerCase() }.findAll { it.size() > 0 }
    if (!parts) {
        throw new IllegalArgumentException("params.steps is empty")
    }
    def aliases = [meg: 'meg_all', artifacts: 'meg_artifacts', ica: 'meg_ica', epochs: 'meg_epochs']
    def primary = aliases.containsKey(parts[0]) ? aliases[parts[0]] : parts[0]
    def mods = parts.size() > 1 ? parts[1..-1].collect { it.trim().toLowerCase() }.toSet() : [] as Set

    def allowedMods = ['skip_ica', 'with_anatomy'] as Set
    mods.each { m ->
        if (!allowedMods.contains(m)) {
            throw new IllegalArgumentException("Unknown steps modifier: ${m}. Allowed: skip_ica, with_anatomy")
        }
    }

    if (primary == 'meg_all' && mods.contains('with_anatomy')) {
        throw new IllegalArgumentException("steps=meg_all cannot be combined with with_anatomy; use steps=all or meg_*,with_anatomy")
    }

    def skipIca = mods.contains('skip_ica')
    def withAnatomy = mods.contains('with_anatomy')

    int megStage = -1
    boolean runAnatomy = false
    boolean runMeg = false

    switch (primary) {
        case 'report':
            break
        case 'anatomy':
            runAnatomy = true
            break
        case 'all':
            runAnatomy = true
            runMeg = true
            megStage = 3
            break
        case 'meg_all':
            runMeg = true
            megStage = 3
            break
        case 'meg_artifacts':
            runMeg = true
            megStage = 0
            runAnatomy = withAnatomy
            break
        case 'meg_ica':
            runMeg = true
            megStage = 1
            runAnatomy = withAnatomy
            break
        case 'meg_epochs':
            runMeg = true
            megStage = 2
            runAnatomy = withAnatomy
            break
        default:
            throw new IllegalArgumentException("Unknown steps '${primary}'. Use: report, anatomy, all, meg_all, meg_artifacts, meg_ica, meg_epochs (aliases: meg, artifacts, ica, epochs).")
    }

    if (skipIca && megStage != 2) {
        throw new IllegalArgumentException("skip_ica is only supported with meg_epochs (e.g. steps=meg_epochs,skip_ica). Full all/meg_all requires ICA-clean raw for forward/source.")
    }

    return [primary: primary, megStage: megStage, runAnatomy: runAnatomy, runMeg: runMeg, skipIca: skipIca]
}

workflow {
    def cfg = parseMegPipelineSteps(params.steps ?: 'meg_all')

    log.info "Pipeline steps: primary=${cfg.primary}, megStage=${cfg.megStage}, runAnatomy=${cfg.runAnatomy}, runMeg=${cfg.runMeg}, skipIca=${cfg.skipIca}"

    def cohortMode = (params.cohort ?: false).toString().toBoolean()
    def sanitizeDatasetName = { String rawName ->
        rawName.replace(' ', '_').replaceAll(/[^A-Za-z0-9_.-]/, '_')
    }
    if (cohortMode) {
        log.info "Cohort mode enabled: dataset root=${params.dataset_dir}"
    } else {
        log.info "Single-dataset mode enabled: dataset=${params.dataset_dir}"
    }

            native_dataset_ch = cohortMode
                ? Channel
                    .fromPath("${params.dataset_dir}/*", type: 'dir', checkIfExists: true)
                    .map { datasetPath ->
                        def originalName = datasetPath.getName()
                        def datasetName = sanitizeDatasetName(originalName)
                        def outputDir = "${params.output_dir}/datasets/${datasetName}"
                        def preprocDir = "${outputDir}/preprocessed"
                        def fsSubjectsDir = "${params.fs_subjects_dir}/${datasetName}"
                        def t1Root = params.cohort_t1_root?.toString()
                        def t1Dir = t1Root ? (new File(t1Root, originalName).isDirectory() ? new File(t1Root, originalName).toString() : t1Root) : datasetPath.toString()
                        tuple(datasetName, datasetPath.toString(), outputDir, preprocDir, fsSubjectsDir, t1Dir)
                    }
                : Channel.value(tuple(
                    sanitizeDatasetName(new File(params.dataset_dir.toString()).getName() ?: 'dataset'),
                    params.dataset_dir.toString(),
                    params.output_dir.toString(),
                    params.preproc_dir.toString(),
                    params.fs_subjects_dir.toString(),
                    (params.t1_dir ?: params.t1_bids_dir ?: params.dataset_dir).toString()
                ))

            native_dataset_report_row_ch = native_dataset_ch
                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir ->
                    tuple(dataset_name, output_dir, preproc_dir)
                }

            def native_report_input_ch

            if (cfg.primary == 'report') {
                native_report_input_ch = native_dataset_report_row_ch
                    .map { dataset_name, output_dir, preproc_dir ->
                        tuple(dataset_name, output_dir, preproc_dir, true)
                    }
            } else {
                def native_anatomy_subject_ch = null
                if (cfg.runAnatomy) {
                    def native_t1_inputs_ch
                    if (params.is_bids) {
                        native_t1_imported = import_MRI_dataset(native_dataset_ch)
                        native_t1_inputs_ch = native_t1_imported.imported_t1_data
                            .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, imported_file ->
                                imported_file.readLines()
                                    .collect { it.trim() }
                                    .findAll { it }
                                    .collectMany { line ->
                                        def matcher = line =~ /([^:]+):\[(.+?)\]/
                                        if (!matcher) {
                                            return []
                                        }
                                        def subjectName = matcher[0][1].trim()
                                        matcher[0][2]
                                            .split(',')
                                            .collect { it.trim().replaceAll(/'/, '') }
                                            .findAll { it }
                                            .collect { anat_file ->
                                                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, anat_file, subjectName)
                                            }
                                    }
                            }

                        if (params.anatomy_preprocess_method == 'freesurfer') {
                            native_fs = run_freesurfer(native_t1_inputs_ch)
                            native_bem = generate_bem(native_fs.fs_subjects)
                            native_anatomy_subject_ch = native_bem.bem_subjects
                        } else if (params.anatomy_preprocess_method == 'deepprep') {
                            native_t1_subjects_ch = native_t1_inputs_ch
                                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, anat_file, subject_name ->
                                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, subject_name)
                                }
                                .unique { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, subject_name ->
                                    "${dataset_name}:${subject_name}"
                                }
                            native_deep = run_deepprep(native_t1_subjects_ch)
                            native_head = run_mkheadsurf(native_deep.fs_subjects)
                            native_bem = generate_bem(native_head.fs_subjects)
                            native_anatomy_subject_ch = native_bem.bem_subjects
                        } else {
                            error "Unsupported anatomy preprocessing method: ${params.anatomy_preprocess_method}. Supported methods are 'freesurfer' and 'deepprep'."
                        }
                    } else {
                        if (params.t1_input_type == 'dicom') {
                            native_t1_dicom_ch = native_dataset_ch.flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir ->
                                def t1Root = new File(t1_dir.toString())
                                def dirs = t1Root.listFiles()?.findAll { it.isDirectory() } ?: []
                                def dicomRoots = dirs ?: (t1Root.exists() ? [t1Root] : [])
                                dicomRoots.collect { dicom_dir ->
                                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, dicom_dir.toString())
                                }
                            }
                            native_t1_inputs_ch = dcm2niix(native_t1_dicom_ch).nifti_dirs
                                .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, converted_dir ->
                                    def files = new File(converted_dir.toString()).listFiles()?.findAll {
                                        it.isFile() && (it.name.endsWith('.nii') || it.name.endsWith('.nii.gz'))
                                    }?.sort { it.name } ?: []
                                    files.collect { anat_file ->
                                        def subjectName = anat_file.getName().replaceAll(/\.nii(\.gz)?$/, '')
                                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, anat_file.toString(), subjectName)
                                    }
                                }
                        } else if (params.t1_input_type == 'nifti') {
                            native_t1_inputs_ch = native_dataset_ch.flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir ->
                                def files = new File(t1_dir.toString()).listFiles()?.findAll { it.isFile() && (it.name.endsWith('.nii') || it.name.endsWith('.nii.gz')) } ?: []
                                files.collect { anat_file ->
                                    def subjectName = anat_file.getName().replaceAll(/\.nii(\.gz)?$/, '')
                                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, anat_file.toString(), subjectName)
                                }
                            }
                        } else {
                            error "Unsupported t1_input_type: ${params.t1_input_type}. Supported types are 'dicom' and 'nifti'."
                        }

                        native_fs = run_freesurfer(native_t1_inputs_ch)
                        native_bem = generate_bem(native_fs.fs_subjects)
                        native_anatomy_subject_ch = native_bem.bem_subjects
                    }
                }

                def report_wait_token_ch = null

                if (!cfg.runMeg) {
                    report_wait_token_ch = native_anatomy_subject_ch.collect(flat: false).ifEmpty([]).map { true }
                } else {
                native_imported = import_MEG_dataset(native_dataset_ch, params.dataset_format, params.file_suffix)

                native_raw_subject_ch = native_imported.imported_meg_data
                    .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, imported_file ->
                        imported_file.readLines()
                            .collect { it.trim() }
                            .findAll { it }
                            .collect { raw_subject_path ->
                                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, raw_subject_path)
                            }
                    }

                native_preproc = meg_preproc_osl(native_raw_subject_ch)
                native_artifacts = detect_Artifacts(native_preproc.preproc_subjects)
                native_artifacts_with_hash = native_artifacts.artifacts
                    .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, preproc_raw_path, bad_channels, bad_segments ->
                        def artifactHash = filesSha256([bad_channels, bad_segments])
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifactHash)
                    }

                report_wait_token_ch = native_artifacts.artifacts.collect(flat: false).ifEmpty([]).map { true }

                def native_clean_subject_ch = null
                def native_epoch_subject_ch = null

                if (cfg.megStage >= 1 && !cfg.skipIca) {
                    native_ica = run_ICA(native_artifacts_with_hash)
                    native_labels = run_IC_label(native_ica.ica_subjects)
                    native_labelled_with_hash = native_labels.labelled_subjects
                        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, marked_components ->
                            def markedHash = fileSha256(marked_components)
                            tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, marked_components, markedHash)
                        }
                    native_clean = apply_ICA(native_labelled_with_hash)
                    native_clean_subject_ch = native_clean.clean_subjects
                    report_wait_token_ch = native_clean_subject_ch.collect(flat: false).ifEmpty([]).map { true }
                }

                if (cfg.megStage >= 2) {
                    def epoch_input_ch
                    if (cfg.skipIca) {
                        epoch_input_ch = native_preproc.preproc_subjects
                            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, preproc_raw_path ->
                                def subjectKey = [dataset_name, new File(preproc_raw_path.toString()).getParentFile().getName()]
                                tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, preproc_raw_path, '', '')
                            }
                    } else {
                        epoch_input_ch = native_clean_subject_ch
                            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                                def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
                                tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash)
                            }
                    }
                    native_epochs = epochs(epoch_input_ch)
                    native_epoch_subject_ch = native_epochs.epoch_subjects
                    report_wait_token_ch = native_epoch_subject_ch.collect(flat: false).ifEmpty([]).map { true }
                }

                if (cfg.megStage >= 3) {
                    def covariance_inputs_ch
                    if (params.covar_type == 'epochs') {
                        covariance_inputs_ch = native_clean_subject_ch
                            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                                def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
                                tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, clean_raw_path, clean_raw_path.toString(), clean_hash)
                            }
                    } else if (params.covar_type == 'raw') {
                        covariance_inputs_ch = native_clean_subject_ch
                            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                                def clean_path = clean_raw_path.toString()
                                if (clean_path.contains("task-${params.raw_covariance_task_id}")) {
                                    return null
                                }
                                def raw_data_file = clean_path.replaceAll(/task-[^_]+/, "task-${params.raw_covariance_task_id}")
                                def subjectKey = [dataset_name, new File(clean_path).getParentFile().getName()]
                                tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, clean_raw_path, raw_data_file, clean_hash)
                            }
                            .filter { it != null }
                            .filter { subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, clean_raw_path, raw_data_file, clean_hash ->
                                new File(raw_data_file.toString()).exists()
                            }
                    } else {
                        error "Unsupported covar_type: ${params.covar_type}."
                    }

                    native_cov = compute_covariance(covariance_inputs_ch)
                    if (cfg.runAnatomy) {
                        native_coreg_subject_ch = native_clean_subject_ch.map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                            def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
                            tuple([dataset_name, target_mri_subject_id], subjectKey, dataset_name, output_dir, preproc_dir, target_mri_subject_id, clean_raw_path, clean_hash)
                        }
                        native_anatomy_by_subject_ch = native_anatomy_subject_ch.map { dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir ->
                            tuple([dataset_name, subject_name], fs_subjects_dir)
                        }
                        native_coreg_inputs = native_coreg_subject_ch
                            .combine(native_anatomy_by_subject_ch, by: 0)
                            .map { mri_key, subjectKey, dataset_name, output_dir, preproc_dir, target_mri_subject_id, clean_raw_path, clean_hash, fs_subjects_dir ->
                                tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, target_mri_subject_id, clean_raw_path, clean_hash)
                            }
                    } else {
                        native_coreg_inputs = native_clean_subject_ch.map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                            def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
                            tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, target_mri_subject_id, clean_raw_path, clean_hash)
                        }
                    }
                    native_trans = coregistration(native_coreg_inputs)
                    native_trans_with_hash = native_trans.trans_subjects
                        .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, trans_path, clean_hash ->
                            def transHash = fileSha256(trans_path)
                            tuple(subjectKey, output_dir, preproc_dir, fs_subjects_dir, trans_path, clean_hash, transHash)
                        }
                    native_fwd_inputs = native_trans_with_hash.combine(native_epoch_subject_ch, by: 0)
                    native_fwds = forward_solution(native_fwd_inputs)
                    native_source_inputs = native_fwds.fwd_subjects.combine(native_cov.cov_subjects, by: 0)
                    native_source = source_imaging(native_source_inputs)
                    report_wait_token_ch = native_source.source_subjects.collect(flat: false).ifEmpty([]).map { true }
                }
                }

                native_report_input_ch = native_dataset_report_row_ch
                    .combine(report_wait_token_ch)
                    .map { dataset_name, output_dir, preproc_dir, wait_token ->
                        tuple(dataset_name, output_dir, preproc_dir, wait_token)
                    }
            }

            native_reports = generate_static_html_report(native_report_input_ch)
            if (cohortMode) {
                generate_cohort_static_html_report(native_reports.dataset_reports.map { dataset_name, output_dir, preproc_dir, marker -> marker }.collect())
            }
}
