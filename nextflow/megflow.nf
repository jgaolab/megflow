#!/usr/bin/env nextflow
// Run with a project-specific config, for example:
// nextflow run nextflow/megflow.nf -c nextflow/nextflow.config
nextflow.enable.dsl=2

import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import groovy.io.FileType
import java.security.MessageDigest
// include { deepprep } from '/opt/DeepPrep/deepprep/nextflow/deepprep.nf'

log.info "MEGFlow Anatomy and MEG Preprocessing Pipeline"
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

String artifactReportSha256(def preprocDirValue) {
    def artifactRoot = new File(preprocDirValue.toString(), 'artifact_report')
    if (!artifactRoot.exists()) {
        return "artifact_report:missing:${artifactRoot.absolutePath}"
    }

    def files = []
    artifactRoot.eachFileRecurse(FileType.FILES) { file ->
        if (file.name.endsWith('_bad_channels.txt') || file.name.endsWith('_bad_segments.txt')) {
            files << file
        }
    }

    if (!files) {
        return "artifact_report:empty:${artifactRoot.absolutePath}"
    }

    return files
        .sort { it.absolutePath }
        .collect { file -> "${file.absolutePath}:${fileSha256(file)}" }
        .join("|")
}

String sanitizeDatasetName(String rawName) {
    rawName.replace(' ', '_').replaceAll(/[^A-Za-z0-9_.-]/, '_')
}

String datasetLookupKey(def rawName) {
    sanitizeDatasetName((rawName ?: '').toString()).toLowerCase()
}

def safeParam(def paramsObj, String paramName, def defaultValue = null) {
    if (paramsObj == null) {
        return defaultValue
    }
    try {
        if (paramsObj instanceof Map && paramsObj.containsKey(paramName)) {
            return paramsObj[paramName]
        }
        def value = paramsObj."${paramName}"
        if (value != null) {
            return value
        }
    } catch (ignored) {
    }
    return defaultValue
}

String megflowCodeDir(Map effectiveConfig = [:]) {
    def fromConfig = cfgGet(effectiveConfig, ['code_dir'], null)
    if (fromConfig) {
        return fromConfig.toString()
    }
    def mf = asMap(safeParam(params, 'megflow', [:]))
    def fromMegflow = mf.code_dir ?: safeParam(params, 'code_dir', null)
    if (fromMegflow) {
        return fromMegflow.toString()
    }
    return "${workflow.projectDir}/megflow"
}

String megflowOutputRoot() {
    def mf = asMap(safeParam(params, 'megflow', [:]))
    return (mf.output_dir ?: safeParam(params, 'output_dir', 'megflow_output')).toString()
}

String megflowErrorMode() {
    def mf = asMap(safeParam(params, 'megflow', [:]))
    return (mf.error_mode ?: safeParam(params, 'error_mode', 'lenient')).toString()
}

Map asMap(def value) {
    return value instanceof Map ? new LinkedHashMap(value) : [:]
}

List asList(def value) {
    if (value == null) {
        return []
    }
    if (value instanceof List) {
        return value
    }
    if (value instanceof Collection) {
        return value as List
    }
    return [value]
}

Map deepMerge(Map base, Map override) {
    def out = new LinkedHashMap(base ?: [:])
    (override ?: [:]).each { key, value ->
        if (value == null) {
            out[key] = null
        } else if (out[key] instanceof Map && value instanceof Map) {
            out[key] = deepMerge(out[key] as Map, value as Map)
        } else {
            out[key] = value
        }
    }
    return out
}

def cfgGet(Map config, List keys, def defaultValue = null) {
    def cur = config
    for (key in keys) {
        if (!(cur instanceof Map) || !cur.containsKey(key)) {
            return defaultValue
        }
        cur = cur[key]
    }
    return cur == null ? defaultValue : cur
}

String cfgText(Map config, List keys, def defaultValue = '') {
    def value = cfgGet(config, keys, defaultValue)
    return value == null ? '' : value.toString()
}

boolean cfgBool(Map config, List keys, boolean defaultValue = false) {
    def value = cfgGet(config, keys, defaultValue)
    if (value instanceof Boolean) {
        return value
    }
    return value == null ? defaultValue : value.toString().toBoolean()
}

String configJson(def value) {
    return JsonOutput.toJson(value == null ? [:] : value)
}

String yamlFlowKey(def key) {
    def text = key == null ? '' : key.toString()
    return (text ==~ /[A-Za-z_][A-Za-z0-9_-]*/) ? text : yamlFlowString(text)
}

String yamlFlowString(def value) {
    if (value == null) {
        return 'null'
    }
    if (value instanceof Map) {
        return '{' + value.collect { key, item -> "${yamlFlowKey(key)}: ${yamlFlowString(item)}" }.join(', ') + '}'
    }
    if (value instanceof Collection) {
        return '[' + value.collect { item -> yamlFlowString(item) }.join(', ') + ']'
    }
    if (value instanceof Boolean || value instanceof Number) {
        return value.toString()
    }
    def text = value.toString().replace("'", "''")
    return "'${text}'"
}

Map normalizeModuleConfig(String moduleName, Map moduleConfig) {
    def cfg = asMap(moduleConfig)
    if (moduleName == 'preproc' && cfg.containsKey('steps') && !cfg.containsKey('preproc')) {
        return [preproc: cfg.steps]
    }
    if (moduleName == 'megqc' && cfg.containsKey('preproc_steps') && !cfg.containsKey('preproc')) {
        def out = new LinkedHashMap(cfg)
        out.remove('preproc_steps')
        out.preproc = cfg.preproc_steps
        return out
    }
    return cfg
}

String moduleConfigJson(Map effectiveConfig, String moduleName) {
    def rawConfig = effectiveConfig[moduleName]
    if (rawConfig instanceof CharSequence) {
        return rawConfig.toString()
    }
    return configJson(normalizeModuleConfig(moduleName, asMap(rawConfig)))
}

Map moduleConfig(Map effectiveConfig, String moduleName) {
    return normalizeModuleConfig(moduleName, asMap(effectiveConfig[moduleName]))
}

boolean modulePreprocConfigured(Map effectiveConfig, String moduleName) {
    def value = cfgGet(effectiveConfig, [moduleName, 'preproc'], null)
    if (value instanceof Map) {
        if (value.isEmpty()) {
            return false
        }
        if (value.containsKey('steps')) {
            value = value.steps
        }
    }
    return !asList(value).isEmpty()
}

String matchingDatasetProfileKey(Map datasets, String datasetName) {
    if (!datasets) {
        return null
    }
    if (datasets.containsKey(datasetName)) {
        return datasetName
    }
    def lookup = datasetLookupKey(datasetName)
    for (entry in datasets.entrySet()) {
        if (datasetLookupKey(entry.key) == lookup) {
            return entry.key
        }
    }
    return null
}

boolean datasetNameListed(String datasetName, def patterns) {
    def items = asList(patterns).collect { it.toString() }.findAll { it }
    if (!items) {
        return false
    }
    def lookup = datasetLookupKey(datasetName)
    return items.any { item ->
        item == '*' || datasetLookupKey(item) == lookup || datasetName == item
    }
}

Map parseRecordingMeta(def rawPathValue) {
    def path = new File(rawPathValue.toString())
    def name = path.getName()
    def text = path.toString()
    def subject = ''
    def session = ''
    def task = ''
    def run = ''
    def suffix = ''
    def matcher

    matcher = (text =~ /sub-([A-Za-z0-9]+)/)
    if (matcher.find()) {
        subject = matcher.group(1)
    }
    matcher = (text =~ /ses-([A-Za-z0-9]+)/)
    if (matcher.find()) {
        session = matcher.group(1)
    }
    matcher = (name =~ /task-([^_\/.]+)/)
    if (matcher.find()) {
        task = matcher.group(1)
    }
    matcher = (name =~ /run-([^_\/.]+)/)
    if (matcher.find()) {
        run = matcher.group(1)
    }
    matcher = (name =~ /_([A-Za-z0-9]+)(?:\.[^.]+|$)/)
    if (matcher.find()) {
        suffix = matcher.group(1)
    }

    return [
        subject: subject,
        session: session,
        task: task,
        run: run,
        suffix: suffix,
        filename: name,
        path: text
    ]
}

boolean matchOne(def expected, String actual) {
    if (expected == null) {
        return true
    }
    def values = asList(expected).collect { it.toString() }
    if (!values) {
        return true
    }
    def actualText = actual == null ? '' : actual.toString()
    return values.any { value ->
        value == '*' || value.equalsIgnoreCase(actualText)
    }
}

boolean recordingProfileMatches(Map matchSpec, Map meta) {
    if (!matchSpec) {
        return false
    }
    if (!matchOne(matchSpec.subject, meta.subject)) {
        return false
    }
    if (!matchOne(matchSpec.session, meta.session)) {
        return false
    }
    if (!matchOne(matchSpec.task, meta.task)) {
        return false
    }
    if (!matchOne(matchSpec.run, meta.run)) {
        return false
    }
    if (!matchOne(matchSpec.suffix, meta.suffix)) {
        return false
    }
    if (matchSpec.filename_contains != null) {
        def parts = asList(matchSpec.filename_contains).collect { it.toString().toLowerCase() }
        def filename = (meta.filename ?: '').toString().toLowerCase()
        if (!parts.any { filename.contains(it) }) {
            return false
        }
    }
    return true
}

Map effectiveRecordingConfig(Map datasetConfig, def rawPathValue) {
    def effective = new LinkedHashMap(datasetConfig ?: [:])
    def meta = parseRecordingMeta(rawPathValue)
    def recordings = asMap(effective.recordings)
    def matches = []
    recordings.each { name, profile ->
        def profileMap = asMap(profile)
        if (recordingProfileMatches(asMap(profileMap.match), meta)) {
            matches << [name: name.toString(), profile: profileMap]
        }
    }
    if (matches.size() > 1) {
        throw new IllegalArgumentException("Multiple recording profiles matched ${rawPathValue}: ${matches.collect { it.name }}")
    }
    def recordingProfileName = ''
    if (matches.size() == 1) {
        recordingProfileName = matches[0].name
        def override = new LinkedHashMap(matches[0].profile)
        override.remove('match')
        effective = deepMerge(effective, override)
    }
    effective.remove('recordings')
    effective._recording = [profile_name: recordingProfileName, meta: meta]
    return effective
}

List resolveDatasetProfiles(def megflowRaw) {
    def mf = asMap(megflowRaw)
    if (!mf) {
        throw new IllegalArgumentException("params.megflow is required. MEGFlow profile v2 no longer reads legacy dataset/config parameters.")
    }
    def defaults = asMap(mf.defaults)
    def datasets = asMap(mf.datasets)
    def outputRoot = (mf.output_dir ?: defaults.output_dir ?: 'megflow_output').toString()
    def fsSubjectsRoot = (mf.fs_subjects_root ?: '').toString().trim()
    def corpusRoot = (mf.corpus_root ?: '').toString().trim()
    def candidates = new LinkedHashMap()

    if (corpusRoot) {
        def root = new File(corpusRoot)
        if (!root.isDirectory()) {
            throw new IllegalArgumentException("params.megflow.corpus_root is not a directory: ${corpusRoot}")
        }
        root.listFiles()
            ?.findAll { it.isDirectory() }
            ?.sort { it.name }
            ?.each { dir ->
                if (asList(mf.dataset_include) && !datasetNameListed(dir.name, mf.dataset_include)) {
                    return
                }
                if (datasetNameListed(dir.name, mf.dataset_exclude)) {
                    return
                }
                candidates[dir.name] = [original_name: dir.name, dataset_dir: dir.toString(), explicit: false]
            }
    }

    datasets.each { profileName, profileValue ->
        def profile = asMap(profileValue)
        if (profile.dataset_dir) {
            def key = profileName.toString()
            if (asList(mf.dataset_include) && !datasetNameListed(key, mf.dataset_include)) {
                return
            }
            if (datasetNameListed(key, mf.dataset_exclude)) {
                return
            }
            candidates[key] = [original_name: key, dataset_dir: profile.dataset_dir.toString(), explicit: true]
        }
    }

    if (!candidates) {
        throw new IllegalArgumentException("No datasets were discovered. Set params.megflow.corpus_root or provide params.megflow.datasets entries with dataset_dir.")
    }

    def multipleDatasets = candidates.size() > 1 || corpusRoot
    def resolved = []
    candidates.each { candidateName, candidate ->
        def profileKey = matchingDatasetProfileKey(datasets, candidateName)
        def profile = profileKey == null ? [:] : asMap(datasets[profileKey])
        def effective = deepMerge(defaults, profile)
        def datasetName = sanitizeDatasetName((profile.name ?: candidateName).toString())
        def datasetDir = (profile.dataset_dir ?: candidate.dataset_dir).toString()
        def datasetOutputDir = (profile.output_dir ?: (multipleDatasets ? "${outputRoot}/datasets/${datasetName}" : outputRoot)).toString()
        def preprocDir = (profile.preproc_dir ?: "${datasetOutputDir}/preprocessed").toString()
        def fsSubjectsDir = (
            profile.fs_subjects_dir ?:
            cfgGet(effective, ['anatomy', 'fs_subjects_dir'], null) ?:
            (fsSubjectsRoot ? "${fsSubjectsRoot}/${datasetName}" : "${outputRoot}/smri/${datasetName}")
        ).toString()
        def t1Dir = (
            profile.t1_dir ?:
            cfgGet(effective, ['anatomy', 't1_dir'], null) ?:
            cfgGet(effective, ['anatomy', 't1_bids_dir'], null) ?:
            datasetDir
        ).toString()

        effective.dataset_name = datasetName
        effective.dataset_dir = datasetDir
        effective.output_dir = datasetOutputDir
        effective.preproc_dir = preprocDir
        effective.fs_subjects_dir = fsSubjectsDir
        effective.t1_dir = t1Dir
        effective.profile_name = profileKey ?: candidateName

        resolved << [
            dataset_name: datasetName,
            dataset_dir: datasetDir,
            output_dir: datasetOutputDir,
            preproc_dir: preprocDir,
            fs_subjects_dir: fsSubjectsDir,
            t1_dir: t1Dir,
            effective_config: effective
        ]
    }
    return resolved
}

process generate_corpus_static_html_report {
    tag "corpus-static-html-report"
    cache false

    input:
    path dataset_markers

    output:
    path "corpus_static_html_report_done.txt", emit: completion_marker

    script:
    report_script = "${megflowCodeDir()}/reports/corpus_static_html_report.py"
    corpus_root = "${megflowOutputRoot()}/datasets"
    report_output_dir = "${megflowOutputRoot()}/corpus_static_html_report"
    """
    set -euo pipefail
    python "${report_script}" \\
        --corpus_root "${corpus_root}" \\
        --output_dir "${report_output_dir}"

    echo "Corpus static HTML report generated at ${report_output_dir}" > corpus_static_html_report_done.txt
    """
}

process import_mri_dataset {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), path('imported_t1_data.txt'), emit: imported_t1_data

    script:
    script_name = "${megflowCodeDir(effective_config)}/mri_import_dataset.py"
    mri_import_config = moduleConfigJson(effective_config, 'mri_import')
    """
    mkdir -p "${preproc_dir}"
    python ${script_name} \\
        --bids_dir "${t1_dir}" \\
        --config '${mri_import_config}' \\
        --output_file imported_t1_data.txt
    """
}

process dcm2niix {
    tag "${dataset_name}:${t1_dicom_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(t1_dicom_dir)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), path("converted"), emit: nifti_dirs

    script:
    t1_dicom_basename = file(t1_dicom_dir).getName()
    series_glob = cfgText(effective_config, ['anatomy', 't1_dicom_series_glob'], '')
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

process generate_pseudomri {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(raw_subject_path), val(subject_name)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val("${preproc_dir}/pseudomri/${subject_name}/${subject_name}.nii.gz"), val(subject_name), emit: pseudo_t1_inputs

    script:
    script_name = "${megflowCodeDir(effective_config)}/create_pseudomri.py"
    template_dir = cfgText(effective_config, ['anatomy', 'pseudomri_template_dir'], "${megflowCodeDir(effective_config)}/tools/pseudomri")
    template_subject = cfgText(effective_config, ['anatomy', 'pseudomri_template_subject'], "mni_icbm152_nlin_sym_09a")
    """
    set -euo pipefail
    python ${script_name} \\
        --info_fif "${raw_subject_path}" \\
        --subject "${subject_name}" \\
        --output_dir "${preproc_dir}/pseudomri/${subject_name}" \\
        --template_dir "${template_dir}" \\
        --template_subject "${template_subject}"
    """
}

process run_freesurfer {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(anat_file), val(subject_name)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val("${fs_subjects_dir}/${subject_name}"), val(effective_config), emit: fs_subjects

    script:
    """
    set -euo pipefail
    mkdir -p "${fs_subjects_dir}"
    subject_dir="${fs_subjects_dir}/${subject_name}"

    if [ -f "\${subject_dir}/scripts/recon-all.done" ]; then
        echo "FreeSurfer subject already completed: \${subject_dir}"
    elif [ -d "\${subject_dir}" ] && { [ -f "\${subject_dir}/mri/orig.mgz" ] || [ -f "\${subject_dir}/mri/orig/001.mgz" ]; }; then
        echo "Continuing existing FreeSurfer subject without -i: \${subject_dir}"
        recon-all -sd "${fs_subjects_dir}" -all -s "${subject_name}" -3T -openmp 4
    elif [ -d "\${subject_dir}" ]; then
        echo "Existing FreeSurfer subject directory is incomplete and cannot be resumed: \${subject_dir}" >&2
        echo "Remove the subject directory or use a different subject name before rerunning." >&2
        exit 1
    else
        recon-all -sd "${fs_subjects_dir}" -i "${anat_file}" -s "${subject_name}"
        recon-all -sd "${fs_subjects_dir}" -all -s "${subject_name}" -3T -openmp 4
    fi

    if [ -f "\${subject_dir}/surf/lh.seghead" ]; then
        echo "Head surface already exists: \${subject_dir}/surf/lh.seghead"
    else
        mkheadsurf -sd "${fs_subjects_dir}" -s "${subject_name}" -srcvol T1.mgz -thresh1 30
    fi
    """
}

process run_deepprep {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(subject_name)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val("${fs_subjects_dir}/${subject_name}"), val(effective_config), emit: fs_subjects

    script:
    output_dir = "${preproc_dir}/deepprep/${subject_name}"
    deepprep_device = cfgText(effective_config, ['anatomy', 'deepprep_device'], 'cpu')
    deepprep_backend = cfgText(effective_config, ['anatomy', 'deepprep_backend'], 'auto').toLowerCase()
    deepprep_command = cfgText(effective_config, ['anatomy', 'deepprep_command'], '/opt/DeepPrep/deepprep/deepprep.sh')
    deepprep_container = cfgText(effective_config, ['anatomy', 'deepprep_container'], 'cmrlab/megflow:1.0.0')
    deepprep_sif = cfgText(effective_config, ['anatomy', 'deepprep_sif'], '')
    fs_license_file = cfgText(effective_config, ['anatomy', 'fs_license_file'], '/fs_license.txt')
    anat_get_t1w_script = "${megflowCodeDir(effective_config)}/anat_get_t1w_file_in_bids.py"
    mri_import_subject_id = subject_name.replaceFirst(/^sub-/, '')
    mri_import_config = yamlFlowString(deepMerge(moduleConfig(effective_config, 'mri_import'), [subject_id: [mri_import_subject_id]]))
    """
    set -euo pipefail
    mkdir -p "${fs_subjects_dir}" "${output_dir}"

    deepprep_backend="${deepprep_backend}"
    deepprep_command="${deepprep_command}"
    deepprep_container="${deepprep_container}"
    deepprep_sif="${deepprep_sif}"
    fs_license_file="${fs_license_file}"
    anat_get_t1w_script="${anat_get_t1w_script}"

    run_deepprep_args=(
        "${t1_dir}"
        "${output_dir}"
        participant
        --participant_label "${subject_name}"
        --skip_bids_validation
        --anat_only
        --fs_license_file /fs_license.txt
        --device "${deepprep_device}"
        --mri_import_config "${mri_import_config}"
        --resume
    )

    if { [ "\${deepprep_backend}" = "local" ] || [ "\${deepprep_backend}" = "auto" ]; } && [ -x "\${deepprep_command}" ]; then
        "\${deepprep_command}" "\${run_deepprep_args[@]}"
    elif [ "\${deepprep_backend}" = "docker" ] || [ "\${deepprep_backend}" = "auto" ]; then
        if ! command -v docker >/dev/null 2>&1; then
            echo "Docker is required for DeepPrep backend '\${deepprep_backend}', but docker was not found." >&2
            exit 1
        fi
        if [ ! -f "\${fs_license_file}" ]; then
            echo "FreeSurfer license file not found: \${fs_license_file}" >&2
            exit 1
        fi
        docker run --rm -i \\
            --entrypoint /opt/DeepPrep/deepprep/deepprep.sh \\
            -v /data:/data \\
            -v "\${fs_license_file}:/fs_license.txt:ro" \\
            -v "\${anat_get_t1w_script}:/opt/DeepPrep/deepprep/nextflow/bin/anat_get_t1w_file_in_bids.py:ro" \\
            "\${deepprep_container}" \\
            "\${run_deepprep_args[@]}"
    elif [ "\${deepprep_backend}" = "singularity" ]; then
        if [ -z "\${deepprep_sif}" ] || [ ! -f "\${deepprep_sif}" ]; then
            echo "DeepPrep singularity image not found: \${deepprep_sif}" >&2
            exit 1
        fi
        singularity exec \\
            -B /data:/data \\
            -B "\${fs_license_file}:/fs_license.txt" \\
            -B "\${anat_get_t1w_script}:/opt/DeepPrep/deepprep/nextflow/bin/anat_get_t1w_file_in_bids.py" \\
            "\${deepprep_sif}" \\
            /opt/DeepPrep/deepprep/deepprep.sh \\
            "\${run_deepprep_args[@]}"
    else
        echo "Unsupported DeepPrep backend: \${deepprep_backend}" >&2
        exit 1
    fi

    kill -9 \$(pgrep redis-server) || true
    cp -rf "${output_dir}/Recon/"* "${fs_subjects_dir}/"
    """
}

process run_mkheadsurf {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config), emit: fs_subjects

    script:
    """
    mkheadsurf -sd "${fs_subjects_dir}" -s "${subject_name}" -srcvol T1.mgz -thresh1 30
    """
}

process generate_bem {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config), emit: bem_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/generate_bem.py"
    subject_basename = file(subject_dir).getBaseName()
    bem_config = moduleConfigJson(effective_config, 'bem')
    """
    python3 ${script_name} \\
        --subject_dir "${subject_dir}" \\
        --config '${bem_config}' \\
        --output_dir "${fs_subjects_dir}/${subject_basename}/bem"
    """
}

process import_meg_dataset {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), path('imported_meg_data.txt'), emit: imported_meg_data

    script:
    script_name = "${megflowCodeDir(effective_config)}/meg_import_dataset.py"
    dataset_format = cfgText(effective_config, ['dataset_format'], 'auto')
    file_suffix = cfgText(effective_config, ['file_suffix'], '.fif')
    meg_import_config = moduleConfigJson(effective_config, 'meg_import')
    """
    mkdir -p "${preproc_dir}"
    python ${script_name} \\
        --dataset_dir "${dataset_dir}" \\
        --dataset_format ${dataset_format} \\
        --file_suffix ${file_suffix} \\
        --output_file imported_meg_data.txt \\
        --exclude_output_dir "${output_dir}" \\
        --exclude_preproc_dir "${preproc_dir}" \\
        --config '${meg_import_config}'
    """
}

process score_meg_quality {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 4.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), path("*.summary.json"), path("*.component_scores.csv"), path("*.normative_quality_score.png"), emit: qc_subjects

    script:
    raw_subject_basename = file(orig_raw_path).getBaseName()
    script_name = "${megflowCodeDir(effective_config)}/meg_quality_control.py"
    qc_code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/tools/megqc/score_meg_reference_quota_standalone.py"])
    qc_output_dir = "${preproc_dir}/quality_control/${raw_subject_basename}"
    megqc_config = moduleConfig(effective_config, 'megqc')
    qc_preproc_config = configJson([preproc: cfgGet(megqc_config, ['preproc'], [])])
    qc_meg_vendor = cfgText(megqc_config, ['meg_vendor'], 'auto')
    """
    set -euo pipefail
    mkdir -p "${qc_output_dir}"
    echo "${qc_code_hash}" > megqc_code_hash.txt
    python "${script_name}" \\
        --input "${orig_raw_path}" \\
        --output_dir "${qc_output_dir}" \\
        --model "${cfgText(megqc_config, ['model'], 'lowcost_quota_T4_S2_Stat1_Fr1')}" \\
        --meg_vendor "${qc_meg_vendor}" \\
        --category "${cfgText(megqc_config, ['category'], 'auto')}" \\
        --reference_scope "${cfgText(megqc_config, ['reference_scope'], 'device_category')}" \\
        --min_reference_n ${cfgGet(megqc_config, ['min_reference_n'], 20)} \\
        --min_score ${cfgGet(megqc_config, ['min_score'], 0.0)} \\
        --alarm_score ${cfgGet(megqc_config, ['alarm_score'], 60.0)} \\
        --freq_max_samples ${cfgGet(megqc_config, ['freq_max_samples'], 0)} \\
        --dfa_max_samples ${cfgGet(megqc_config, ['dfa_max_samples'], 20000)} \\
        --dfa_method "${cfgText(megqc_config, ['dfa_method'], 'msqms')}" \\
        --skip_dfa "${cfgBool(megqc_config, ['skip_dfa'], false)}" \\
        --preproc_config '${qc_preproc_config}' \\
        --keep_bad_annotations "${cfgBool(megqc_config, ['keep_bad_annotations'], true)}" \\
        --omit_bad_channels "${cfgBool(megqc_config, ['omit_bad_channels'], false)}" \\
        --n_jobs ${task.cpus} \\
        --seg_length ${cfgGet(megqc_config, ['seg_length'], 100)}
    cp "${qc_output_dir}"/*.summary.json .
    cp "${qc_output_dir}"/*.component_scores.csv .
    cp "${qc_output_dir}"/*.normative_quality_score.png .
    """
}

process meg_basic_preproc {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 6.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val("${preproc_dir}/${raw_subject_basename}/${raw_subject_basename}_preproc-raw.fif"), emit: preproc_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/meg_preproc_osl.py"
    raw_subject_basename = file(orig_raw_path).getBaseName()
    preproc_module_config = normalizeModuleConfig('preproc', asMap(effective_config.preproc))
    preproc_config = configJson(
        preproc_module_config + [
            digitization: asMap(effective_config.digitization)
        ]
    )
    osl_seed = cfgGet(effective_config, ['seeds', 'osl'], 2025)
    """
    python ${script_name} \\
        --file "${orig_raw_path}" \\
        --preproc_dir "${preproc_dir}" \\
        --seed ${osl_seed} \\
        --config '${preproc_config}'
    """
}

process detect_artifacts {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val("${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_channels.txt"), val("${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_segments.txt"), emit: artifacts

    script:
    script_name = "${megflowCodeDir(effective_config)}/meg_detect_artifacts.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_parent = file(preproc_raw_path).getParent().getName()
    artifact_config = moduleConfigJson(effective_config, 'artifacts')
    """
    mkdir -p "${preproc_dir}/artifact_report/${raw_subject_parent}"
    python ${script_name} \\
        --input "${preproc_raw_path}" \\
        --output "${preproc_dir}/artifact_report/${raw_subject_parent}" \\
        --config '${artifact_config}'
    """
}

process run_ica {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 8.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val("${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ica_sources.fif"), val("${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif"), emit: ica_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/run_ica.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    ica_config = moduleConfig(effective_config, 'ica')
    ica_output_dir = cfgText(ica_config, ['output_dir'], 'ica_report')
    num_ic = cfgGet(ica_config, ['num_components'], 60)
    compute_explained_variance = cfgBool(ica_config, ['compute_explained_variance'], false)
    ica_seed = cfgGet(effective_config, ['seeds', 'ica'], 2025)
    """
    python ${script_name} \\
        --raw_file "${preproc_raw_path}" \\
        --output_dir "${preproc_dir}/${ica_output_dir}" \\
        --num_IC ${num_ic} \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}" \\
        --seed ${ica_seed} \\
        --compute_explained_variance ${compute_explained_variance}
    """
}

process run_ic_label {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(ica_source), val(ica_file_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val("${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/marked_components.txt"), emit: labelled_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/run_ica_label.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    ica_output_dir = cfgText(moduleConfig(effective_config, 'ica'), ['output_dir'], 'ica_report')
    ic_label_config = moduleConfigJson(effective_config, 'ic_label')
    """
    python ${script_name} \\
        --raw_data_path "${preproc_raw_path}" \\
        --ica_file "${ica_file_path}" \\
        --output_dir "${preproc_dir}/${ica_output_dir}" \\
        --config '${ic_label_config}'
    """
}

process apply_ica {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(marked_components), val(marked_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val("${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif"), val("${target_mri_subject_id}"), val("${artifact_hash}|${marked_hash}"), emit: clean_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/apply_ica.py"
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    anatomy_select_tag = cfgText(effective_config, ['anatomy', 'select_tag'], '')
    ica_output_dir = cfgText(moduleConfig(effective_config, 'ica'), ['output_dir'], 'ica_report')
    target_mri_subject_id = raw_subject_basename.split('_')[0] + anatomy_select_tag
    """
    python ${script_name} \\
        --raw_file "${preproc_raw_path}" \\
        --ica_file "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif" \\
        --exclude_file "${marked_components}" \\
        --output_file "${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif" \\
        --output_dir "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}" \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}"
    """
}

process epochs {
    tag "${subject_key[0]}:${subject_key[1]}"

    input:
    tuple val(subject_key), val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(analysis_raw_path), val(target_mri_subject_id), val(clean_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val("${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif"), val(epoch_analysis_raw_path), val(clean_hash), emit: epoch_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/epochs.py"
    raw_subject_basename = file(analysis_raw_path).getBaseName()
    raw_subject_dir_basename = file(analysis_raw_path).getParent().getName()
    filtered_raw_subject_basename = file(orig_raw_path).getBaseName().replace("_meg_preproc-raw_clean_raw", "").replace("_meg_preproc-raw", "")
    events_file = orig_raw_path.toString().replaceAll(/_meg\..*/, '_events.tsv')
    epoch_config = moduleConfigJson(effective_config, 'epochs')
    epoch_output_dir = cfgText(moduleConfig(effective_config, 'epochs'), ['output_dir'], 'epochs')
    epoch_analysis_raw_path = modulePreprocConfigured(effective_config, 'epochs') ?
        "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_analysis-raw.fif" :
        analysis_raw_path.toString()
    """
    mkdir -p "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --preproc_raw_file "${analysis_raw_path}" \\
        --events_file "${events_file}" \\
        --output_epoch_file "${raw_subject_basename}-epo.fif" \\
        --output_analysis_raw_file "${epoch_analysis_raw_path}" \\
        --output_dir "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}" \\
        --config '${epoch_config}'
    """
}

process compute_covariance {
    tag "${subject_key[0]}:${subject_key[1]}"

    input:
    tuple val(subject_key), val(dataset_name), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(raw_subject_path), val(raw_data_file), val(events_file), val(clean_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(effective_config), val("${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif"), val(clean_hash), emit: cov_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/compute_covariance.py"
    raw_subject_dir_basename = file(raw_subject_path).getParent().getName()
    covariance_config = new LinkedHashMap(moduleConfig(effective_config, 'covariance'))
    covar_output_dir = cfgText(covariance_config, ['output_dir'], 'covariance')
    covar_visualize = cfgBool(covariance_config, ['visualize'], true)
    covar_type = cfgText(covariance_config, ['type'], 'epochs')
    if (covar_type == 'raw' && modulePreprocConfigured(effective_config, 'epochs')) {
        covariance_config.analysis_preproc = cfgGet(effective_config, ['epochs', 'preproc'], [])
    }
    covar_config = configJson(covariance_config)
    """
    python ${script_name} \\
        --raw_data_file "${raw_data_file}" \\
        --events_file "${events_file}" \\
        --output_dir "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}" \\
        --visualize ${covar_visualize} \\
        --covar_type ${covar_type} \\
        --config '${covar_config}'
    """
}

process coregistration {
    tag "${subject_key[0]}:${subject_key[1]}"
    time '1h'

    input:
    tuple val(subject_key), val(dataset_name), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(target_mri_subject_id), val(clean_raw_path), val(clean_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(target_mri_subject_id), val("${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}/coreg-trans.fif"), val(clean_hash), emit: trans_subjects

    script:
    script_name = "${megflowCodeDir(effective_config)}/coregistration.py"
    raw_subject_basename = file(clean_raw_path).getBaseName()
    raw_subject_dir_basename = file(clean_raw_path).getParent().getName()
    mri_subject_id = target_mri_subject_id ?: raw_subject_basename.split('_')[0]
    core_config = moduleConfig(effective_config, 'coreg')
    trans_output_dir = cfgText(core_config, ['output_dir'], 'trans')
    coreg_visualize = cfgBool(core_config, ['visualize'], cfgBool(effective_config, ['visualize'], true))
    coreg_config = configJson(core_config)
    supplied_trans_file = cfgText(core_config, ['supplied_trans_file'], '')
    supplied_trans_arg = supplied_trans_file ? " --supplied_trans_file \"${supplied_trans_file}\"" : ""
    """
    python ${script_name} \\
        --raw_file "${clean_raw_path}" \\
        --subjects_dir "${fs_subjects_dir}/${mri_subject_id}" \\
        --visualize ${coreg_visualize} \\
        --output_dir "${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}" \\
        --config '${coreg_config}'${supplied_trans_arg}
    """
}

process forward_solution {
    tag "${key[0]}:${key[1]}"

    input:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(target_mri_subject_id), val(trans_path), val(coreg_clean_hash), val(trans_hash), val(epoch_output_dir), val(epoch_preproc_dir), val(epoch_fs_subjects_dir), val(epoch_effective_config), val(epoch_path), val(clean_raw_path), val(epoch_clean_hash)

    output:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val("${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}/${raw_subject_dir_basename}-fwd.fif"), val(epoch_path), val(clean_raw_path), val(trans_hash), val(epoch_clean_hash), emit: fwd_subjects

    script:
    dataset_name = key[0]
    raw_subject_dir_basename = key[1]
    script_name = "${megflowCodeDir(effective_config)}/forward_solution.py"
    mri_subject_id = target_mri_subject_id ?: raw_subject_dir_basename.split('_')[0]
    mri_subject_dir = "${fs_subjects_dir}/${mri_subject_id}"
    forward_config = moduleConfig(effective_config, 'forward')
    fwd_output_dir = cfgText(forward_config, ['output_dir'], 'forward_solution')
    fwd_epoch_label = cfgText(forward_config, ['epoch_label'], '')
    fwd_config = configJson(forward_config)
    """
    mkdir -p "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --epoch_file "${epoch_path}" \\
        --epoch_label ${fwd_epoch_label}  \\
        --output_dir "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}" \\
        --trans_file "${trans_path}" \\
        --mri_subject_dir "${mri_subject_dir}" \\
        --config '${fwd_config}'
    """
}

process source_imaging {
    tag "${key[0]}:${key[1]}"

    input:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(fwd_file), val(epoch_path), val(clean_raw_path), val(trans_hash), val(epoch_clean_hash), val(cov_output_dir), val(cov_preproc_dir), val(cov_effective_config), val(bl_cov_file), val(cov_clean_hash)

    output:
    tuple val(key), val(output_dir), val(preproc_dir), val("${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}"), emit: source_subjects

    script:
    dataset_name = key[0]
    raw_subject_dir_basename = key[1]
    source_config = moduleConfig(effective_config, 'source')
    src_type = cfgText(source_config, ['type'], 'epochs')
    src_output_dir = cfgText(source_config, ['output_dir'], 'source_recon')
    fwd_output_dir = cfgText(moduleConfig(effective_config, 'forward'), ['output_dir'], 'forward_solution')
    covar_output_dir = cfgText(moduleConfig(effective_config, 'covariance'), ['output_dir'], 'covariance')
    source_visualize = cfgBool(source_config, ['visualize'], cfgBool(effective_config, ['visualize'], true))
    src_config = configJson(source_config)
    raw_subject_path = src_type == 'epochs' ? epoch_path : clean_raw_path
    if (!(src_type in ['epochs', 'raw'])) {
        error "Invalid source.type: ${src_type}. Please specify 'epochs' or 'raw'."
    }
    script_name = "${megflowCodeDir(effective_config)}/source_localization.py"
    """
    mkdir -p "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --data_mode ${src_type} \\
        --data_file "${raw_subject_path}"  \\
        --fs_subjects_dir "${fs_subjects_dir}" \\
        --output_dir "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}" \\
        --forward_dir "${preproc_dir}/${fwd_output_dir}" \\
        --visualize ${source_visualize} \\
        --noise_covariance_dir "${preproc_dir}/${covar_output_dir}" \\
        --config '${src_config}'
    """
}

process generate_static_html_report {
    tag "${dataset_name}"
    cache false

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(source_artifacts), val(report_script), val(manifest_json), val(bad_channel_threshold), val(bad_segment_threshold), val(coreg_mean_threshold), val(coreg_max_threshold), val(epoch_reject_rate_threshold), val(megqc_alarm_score), val(static_artifact_overview_duration), val(alert_missing_ecg_components), val(alert_missing_eog_components), val(static_task_log_mode)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), path("static_html_report_${dataset_name}.done"), emit: dataset_reports

    script:
    report_output_dir = "${output_dir}/static_html_report"
    """
    set -euo pipefail
    mkdir -p "${preproc_dir}/logs"
    cat > "${preproc_dir}/logs/megflow_run_manifest.json" <<'EOF_MANIFEST'
${manifest_json}
EOF_MANIFEST

    python "${report_script}" \\
        --report_root "${preproc_dir}" \\
        --output_dir "${report_output_dir}" \\
        --bad_channel_threshold ${bad_channel_threshold} \\
        --bad_segment_threshold ${bad_segment_threshold} \\
        --coreg_mean_threshold ${coreg_mean_threshold} \\
        --coreg_max_threshold ${coreg_max_threshold} \\
        --epoch_reject_rate_threshold ${epoch_reject_rate_threshold} \\
        --megqc_alarm_score ${megqc_alarm_score} \\
        --artifact_overview_duration ${static_artifact_overview_duration} \\
        --alert_missing_ecg_components ${alert_missing_ecg_components} \\
        --alert_missing_eog_components ${alert_missing_eog_components} \\
        --task_log_mode "${static_task_log_mode}" \\
        --zip_output false

    echo "Static HTML report generated at ${report_output_dir}" > "static_html_report_${dataset_name}.done"
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
 * Parse MEGFlow profile steps into pipeline flags.
 * Primary: report | anatomy | all | meg_all | meg_artifacts | meg_ica | meg_epochs (aliases: meg, artifacts, ica, epochs)
 * Modifiers: skip_ica (meg_epochs only), with_anatomy (meg_* only; not meg_all)
 */
Map parseMegPipelineSteps(String stepsRaw) {
    def parts = stepsRaw.split(',').collect { it.trim().toLowerCase() }.findAll { it.size() > 0 }
    if (!parts) {
        throw new IllegalArgumentException("MEGFlow steps is empty")
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

Map attachParsedSteps(Map config) {
    def effective = new LinkedHashMap(config ?: [:])
    effective._steps = parseMegPipelineSteps(cfgText(effective, ['steps'], 'meg_all'))
    return effective
}

Map buildAnatomyProcessPlan(List datasetProfiles) {
    def anatomyConfigs = datasetProfiles
        .collect { profile ->
            attachParsedSteps(asMap(asMap(profile).effective_config))
        }
        .findAll { effective ->
            asMap(effective._steps).runAnatomy
        }
    def methods = anatomyConfigs
        .collect { effective ->
            cfgText(effective, ['anatomy', 'method'], 'freesurfer').toLowerCase()
        }
        .toSet()
    def supportedMethods = ['freesurfer', 'deepprep', 'pseudomri'] as Set
    def unsupportedMethods = methods.findAll { method -> !supportedMethods.contains(method) }
    if (unsupportedMethods) {
        throw new IllegalArgumentException(
            "Unsupported anatomy methods: ${unsupportedMethods.sort()}. Supported methods are freesurfer, deepprep, and pseudomri."
        )
    }

    return [
        enabled: !anatomyConfigs.isEmpty(),
        methods: methods.toList().sort(),
        datasetNames: anatomyConfigs
            .collect { effective -> cfgText(effective, ['dataset_name'], '') }
            .findAll { it },
        runPseudomri: methods.contains('pseudomri'),
        runFreesurfer: methods.any { method -> method in ['freesurfer', 'pseudomri'] },
        runDeepPrep: methods.contains('deepprep'),
        runMriImport: anatomyConfigs.any { effective ->
            def method = cfgText(effective, ['anatomy', 'method'], 'freesurfer').toLowerCase()
            def isBids = cfgBool(effective, ['anatomy', 'is_bids'], cfgBool(effective, ['is_bids'], true))
            method != 'pseudomri' && isBids
        },
        runDcm2niix: anatomyConfigs.any { effective ->
            def method = cfgText(effective, ['anatomy', 'method'], 'freesurfer').toLowerCase()
            def isBids = cfgBool(effective, ['anatomy', 'is_bids'], cfgBool(effective, ['is_bids'], true))
            def inputType = cfgText(effective, ['anatomy', 't1_input_type'], 'nifti').toLowerCase()
            method == 'freesurfer' && !isBids && inputType == 'dicom'
        },
        useNativeNifti: anatomyConfigs.any { effective ->
            def method = cfgText(effective, ['anatomy', 'method'], 'freesurfer').toLowerCase()
            def isBids = cfgBool(effective, ['anatomy', 'is_bids'], cfgBool(effective, ['is_bids'], true))
            def inputType = cfgText(effective, ['anatomy', 't1_input_type'], 'nifti').toLowerCase()
            method == 'freesurfer' && !isBids && inputType == 'nifti'
        }
    ]
}

workflow {
    def datasetProfiles = resolveDatasetProfiles(params.megflow)
    def anatomyPlan = buildAnatomyProcessPlan(datasetProfiles)
    def corpusMode = datasetProfiles.size() > 1 || cfgText(asMap(params.megflow), ['corpus_root'], '')
    log.info "MEGFlow profile datasets: ${datasetProfiles.collect { it.dataset_name }.join(', ')}"
    log.info "Corpus mode: ${corpusMode}"
    log.info "Anatomy process plan: enabled=${anatomyPlan.enabled}, methods=${anatomyPlan.methods ?: 'none'}, datasets=${anatomyPlan.datasetNames ?: 'none'}"

    native_dataset_ch = Channel
        .fromList(datasetProfiles)
        .map { profile ->
            def effective = attachParsedSteps(asMap(profile.effective_config))
            effective.code_dir = cfgText(effective, ['code_dir'], megflowCodeDir(effective))
            tuple(
                profile.dataset_name.toString(),
                profile.dataset_dir.toString(),
                profile.output_dir.toString(),
                profile.preproc_dir.toString(),
                profile.fs_subjects_dir.toString(),
                profile.t1_dir.toString(),
                effective
            )
        }

    native_dataset_report_row_ch = native_dataset_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            def stepConfig = asMap(effective_config._steps)
            stepConfig.runMeg || stepConfig.primary == 'report'
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            def stepConfig = asMap(effective_config._steps)
            def manifest_json = JsonOutput.prettyPrint(JsonOutput.toJson([
                manifest_schema_version: 3,
                profile_name: cfgText(effective_config, ['profile_name'], dataset_name),
                steps_raw: cfgText(effective_config, ['steps'], 'meg_all'),
                parsed: stepConfig,
                params_snapshot: [
                    dataset_name: dataset_name,
                    dataset_dir: dataset_dir,
                    output_dir: output_dir,
                    preproc_dir: preproc_dir,
                    code_dir: megflowCodeDir(effective_config),
                    fs_subjects_dir: fs_subjects_dir,
                    t1_dir: t1_dir,
                    effective_config: effective_config
                ],
                workflow_meta: [
                    nextflow_version: workflow.nextflow?.version?.toString() ?: '',
                    launch_dir: workflow.launchDir?.toString() ?: '',
                    project_dir: workflow.projectDir?.toString() ?: '',
                    volatile_fields: 'session_id, run_name, and start are omitted from the report task signature for stable -resume caching.'
                ]
            ]))
            tuple(
                dataset_name,
                output_dir,
                preproc_dir,
                "${megflowCodeDir(effective_config)}/reports/static_html_report.py",
                manifest_json,
                cfgGet(effective_config, ['report', 'bad_channel_threshold'], 30),
                cfgGet(effective_config, ['report', 'bad_segment_threshold'], 50),
                cfgGet(effective_config, ['report', 'coreg_mean_threshold'], 5.0),
                cfgGet(effective_config, ['report', 'coreg_max_threshold'], 10.0),
                cfgGet(effective_config, ['report', 'epoch_reject_rate_threshold'], 0.30),
                cfgGet(effective_config, ['megqc', 'alarm_score'], 60.0),
                cfgGet(effective_config, ['report', 'static_artifact_overview_duration'], 200.0),
                cfgBool(effective_config, ['report', 'alert_missing_ecg_components'], true),
                cfgBool(effective_config, ['report', 'alert_missing_eog_components'], true),
                cfgText(effective_config, ['report', 'static_task_log_mode'], 'all-command-log')
            )
        }

    dataset_meg_import_ch = native_dataset_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            def stepConfig = asMap(effective_config._steps)
            def anatomyMethod = cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase()
            stepConfig.runMeg || (stepConfig.runAnatomy && anatomyMethod == 'pseudomri')
        }

    native_imported = import_meg_dataset(dataset_meg_import_ch)
    native_raw_subject_ch = native_imported.imported_meg_data
        .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, imported_file ->
            imported_file.readLines()
                .collect { it.trim() }
                .findAll { it }
                .collect { raw_subject_path ->
                    def recordingConfig = attachParsedSteps(effectiveRecordingConfig(asMap(effective_config), raw_subject_path))
                    recordingConfig.code_dir = cfgText(recordingConfig, ['code_dir'], megflowCodeDir(recordingConfig))
                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, recordingConfig, raw_subject_path)
                }
        }

    native_anatomy_subject_ch = Channel.empty()
    if (anatomyPlan.enabled) {
        anatomy_dataset_ch = native_dataset_ch
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                asMap(effective_config._steps).runAnatomy
            }

        pseudo_t1_inputs_ch = Channel.empty()
        if (anatomyPlan.runPseudomri) {
            pseudo_subject_inputs_ch = native_raw_subject_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path ->
                    asMap(effective_config._steps).runAnatomy &&
                        cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'pseudomri'
                }
                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path ->
                    def rawName = new File(raw_subject_path.toString()).getName()
                    def subjectName = rawName.split('_')[0] + cfgText(effective_config, ['anatomy', 'select_tag'], '')
                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path, subjectName)
                }
                .unique { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path, subjectName ->
                    "${dataset_name}:${subjectName}"
                }
            native_pseudo = generate_pseudomri(pseudo_subject_inputs_ch)
            pseudo_t1_inputs_ch = native_pseudo.pseudo_t1_inputs
        }

        native_bids_t1_inputs_ch = Channel.empty()
        if (anatomyPlan.runMriImport) {
            bids_mri_dataset_ch = anatomy_dataset_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() != 'pseudomri' &&
                        cfgBool(effective_config, ['anatomy', 'is_bids'], cfgBool(effective_config, ['is_bids'], true))
                }
            native_t1_imported = import_mri_dataset(bids_mri_dataset_ch)
            native_bids_t1_inputs_ch = native_t1_imported.imported_t1_data
                .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, imported_file ->
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
                                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subjectName)
                                }
                        }
                }
        }

        native_dicom_t1_inputs_ch = Channel.empty()
        if (anatomyPlan.runDcm2niix) {
            native_t1_dicom_ch = anatomy_dataset_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    !cfgBool(effective_config, ['anatomy', 'is_bids'], cfgBool(effective_config, ['is_bids'], true)) &&
                        cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'freesurfer' &&
                        cfgText(effective_config, ['anatomy', 't1_input_type'], 'nifti').toLowerCase() == 'dicom'
                }
                .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    def t1Root = new File(t1_dir.toString())
                    def dirs = t1Root.listFiles()?.findAll { it.isDirectory() } ?: []
                    def dicomRoots = dirs ?: (t1Root.exists() ? [t1Root] : [])
                    dicomRoots.collect { dicom_dir ->
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, dicom_dir.toString())
                    }
                }
            native_dcm2niix = dcm2niix(native_t1_dicom_ch)
            native_dicom_t1_inputs_ch = native_dcm2niix.nifti_dirs
                .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, converted_dir ->
                    def files = new File(converted_dir.toString()).listFiles()?.findAll {
                        it.isFile() && (it.name.endsWith('.nii') || it.name.endsWith('.nii.gz'))
                    }?.sort { it.name } ?: []
                    files.collect { anat_file ->
                        def subjectName = anat_file.getName().replaceAll(/\.nii(\.gz)?$/, '')
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file.toString(), subjectName)
                    }
                }
        }

        native_nifti_t1_inputs_ch = Channel.empty()
        if (anatomyPlan.useNativeNifti) {
            native_nifti_t1_inputs_ch = anatomy_dataset_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    !cfgBool(effective_config, ['anatomy', 'is_bids'], cfgBool(effective_config, ['is_bids'], true)) &&
                        cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'freesurfer' &&
                        cfgText(effective_config, ['anatomy', 't1_input_type'], 'nifti').toLowerCase() == 'nifti'
                }
                .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    def files = new File(t1_dir.toString()).listFiles()?.findAll {
                        it.isFile() && (it.name.endsWith('.nii') || it.name.endsWith('.nii.gz'))
                    } ?: []
                    files.collect { anat_file ->
                        def subjectName = anat_file.getName().replaceAll(/\.nii(\.gz)?$/, '')
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file.toString(), subjectName)
                    }
                }
        }

        native_fs_subjects_ch = Channel.empty()
        if (anatomyPlan.runFreesurfer) {
            native_freesurfer_t1_inputs_ch = pseudo_t1_inputs_ch
                .mix(native_bids_t1_inputs_ch.filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subjectName ->
                    cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'freesurfer'
                })
                .mix(native_dicom_t1_inputs_ch)
                .mix(native_nifti_t1_inputs_ch)
            native_fs = run_freesurfer(native_freesurfer_t1_inputs_ch)
            native_fs_subjects_ch = native_fs.fs_subjects
        }

        native_head_subjects_ch = Channel.empty()
        if (anatomyPlan.runDeepPrep) {
            native_deepprep_subjects_ch = native_bids_t1_inputs_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subject_name ->
                    cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'deepprep'
                }
                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subject_name ->
                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, subject_name)
                }
                .unique { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, subject_name ->
                    "${dataset_name}:${subject_name}"
                }
            native_deep = run_deepprep(native_deepprep_subjects_ch)
            native_head = run_mkheadsurf(native_deep.fs_subjects)
            native_head_subjects_ch = native_head.fs_subjects
        }

        native_bem_inputs_ch = native_fs_subjects_ch.mix(native_head_subjects_ch)
        native_bem = generate_bem(native_bem_inputs_ch)
        native_anatomy_subject_ch = native_bem.bem_subjects
    }

    native_meg_raw_ch = native_raw_subject_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path ->
            asMap(effective_config._steps).runMeg
        }
    native_raw_with_qc_ch = native_meg_raw_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path ->
            cfgBool(effective_config, ['megqc', 'enabled'], true)
        }
    native_raw_without_qc_ch = native_meg_raw_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path ->
            !cfgBool(effective_config, ['megqc', 'enabled'], true)
        }
    native_qc = score_meg_quality(native_raw_with_qc_ch)
    native_qc_passed_ch = native_qc.qc_subjects
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, qc_summary, qc_components, qc_plot ->
            def scorePayload = new JsonSlurper().parse(new File(qc_summary.toString())) as Map
            def scoreValue = scorePayload.score_0_100
            boolean hasScore = scoreValue != null && scoreValue.toString() != '' && scoreValue.toString().toLowerCase() != 'nan'
            double scoreDouble = hasScore ? scoreValue.toString().toDouble() : Double.NaN
            double minScore = cfgGet(effective_config, ['megqc', 'min_score'], 0.0).toString().toDouble()
            boolean passed = hasScore && scoreDouble >= minScore
            if (!passed) {
                log.warn "MEG QC skipped downstream processing: dataset=${dataset_name}, raw=${orig_raw_path}, score=${scoreValue}, threshold=${minScore}"
            }
            return passed ? tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path) : null
        }
        .filter { it != null }
    native_meg_input_ch = native_raw_without_qc_ch.mix(native_qc_passed_ch)

    native_preproc = meg_basic_preproc(native_meg_input_ch)
    native_artifacts = detect_artifacts(native_preproc.preproc_subjects)
    native_artifacts_with_hash = native_artifacts.artifacts
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments ->
            def artifactHash = filesSha256([bad_channels, bad_segments])
            tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifactHash)
        }

    native_ica_inputs_ch = native_artifacts_with_hash
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifactHash ->
            asMap(effective_config._steps).megStage >= 1 && !asMap(effective_config._steps).skipIca
        }
    native_ica = run_ica(native_ica_inputs_ch)
    native_labels = run_ic_label(native_ica.ica_subjects)
    native_labelled_with_hash = native_labels.labelled_subjects
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, marked_components ->
            def markedHash = fileSha256(marked_components)
            tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, marked_components, markedHash)
        }
    native_clean = apply_ica(native_labelled_with_hash)
    native_clean_subject_ch = native_clean.clean_subjects

    native_epoch_from_preproc_ch = native_preproc.preproc_subjects
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path ->
            asMap(effective_config._steps).megStage >= 2 && asMap(effective_config._steps).skipIca
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path ->
            def subjectKey = [dataset_name, new File(preproc_raw_path.toString()).getParentFile().getName()]
            tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, '', '')
        }
    native_epoch_from_clean_ch = native_clean_subject_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            asMap(effective_config._steps).megStage >= 2
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
            tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash)
        }
    native_epoch_input_ch = native_epoch_from_preproc_ch.mix(native_epoch_from_clean_ch)
    native_epochs = epochs(native_epoch_input_ch)
    native_epoch_subject_ch = native_epochs.epoch_subjects

    native_source_clean_ch = native_clean_subject_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            asMap(effective_config._steps).megStage >= 3
        }
    native_cov_epochs_default_inputs_ch = native_source_clean_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            cfgText(effective_config, ['covariance', 'type'], 'epochs') == 'epochs' &&
                !modulePreprocConfigured(effective_config, 'epochs')
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
            def eventsFile = orig_raw_path.toString().replaceAll(/_meg\..*/, '_events.tsv')
            tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, clean_raw_path, clean_raw_path.toString(), eventsFile, clean_hash)
        }
    native_cov_epochs_preproc_inputs_ch = native_epoch_subject_ch
        .filter { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash ->
            asMap(effective_config._steps).megStage >= 3 &&
                cfgText(effective_config, ['covariance', 'type'], 'epochs') == 'epochs' &&
                modulePreprocConfigured(effective_config, 'epochs')
        }
        .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash ->
            def datasetName = subjectKey[0]
            def origRawPath = cfgText(effective_config, ['_recording', 'meta', 'path'], '')
            def eventsFile = origRawPath.replaceAll(/_meg\..*/, '_events.tsv')
            tuple(subjectKey, datasetName, output_dir, preproc_dir, fs_subjects_dir, effective_config, analysis_raw_path, analysis_raw_path.toString(), eventsFile, clean_hash)
        }
    native_cov_epochs_inputs_ch = native_cov_epochs_default_inputs_ch.mix(native_cov_epochs_preproc_inputs_ch)
    native_cov_raw_inputs_ch = native_source_clean_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            cfgText(effective_config, ['covariance', 'type'], 'epochs') == 'raw'
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            def cleanPath = clean_raw_path.toString()
            def rawCovTask = cfgText(effective_config, ['covariance', 'raw_covariance_task_id'], 'emptr')
            if (cleanPath.contains("task-${rawCovTask}")) {
                return null
            }
            def rawDataFile = cleanPath.replaceAll(/task-[^_]+/, "task-${rawCovTask}")
            def subjectKey = [dataset_name, new File(cleanPath).getParentFile().getName()]
            tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, clean_raw_path, rawDataFile, '', clean_hash)
        }
        .filter { it != null }
        .filter { subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, clean_raw_path, raw_data_file, events_file, clean_hash ->
            new File(raw_data_file.toString()).exists()
        }
    native_cov_inputs_ch = native_cov_epochs_inputs_ch.mix(native_cov_raw_inputs_ch)
    native_cov = compute_covariance(native_cov_inputs_ch)

    native_coreg_existing_inputs_ch = native_source_clean_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            !asMap(effective_config._steps).runAnatomy
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
            tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash)
        }
    native_coreg_anatomy_subject_ch = native_source_clean_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            asMap(effective_config._steps).runAnatomy
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
            def subjectKey = [dataset_name, new File(clean_raw_path.toString()).getParentFile().getName()]
            tuple([dataset_name, target_mri_subject_id], subjectKey, dataset_name, output_dir, preproc_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash)
        }
    native_anatomy_by_subject_ch = native_anatomy_subject_ch.map { dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config ->
        tuple([dataset_name, subject_name], fs_subjects_dir)
    }
    native_coreg_from_anatomy_inputs_ch = native_coreg_anatomy_subject_ch
        .combine(native_anatomy_by_subject_ch, by: 0)
        .map { mri_key, subjectKey, dataset_name, output_dir, preproc_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash, fs_subjects_dir ->
            tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash)
        }
    native_coreg_inputs = native_coreg_existing_inputs_ch.mix(native_coreg_from_anatomy_inputs_ch)
    native_trans = coregistration(native_coreg_inputs)
    native_trans_with_hash = native_trans.trans_subjects
        .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, trans_path, clean_hash ->
            def transHash = fileSha256(trans_path)
            tuple(subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, trans_path, clean_hash, transHash)
        }
    native_fwd_inputs = native_trans_with_hash.combine(native_epoch_subject_ch, by: 0)
    native_fwds = forward_solution(native_fwd_inputs)
    native_source_inputs = native_fwds.fwd_subjects.combine(native_cov.cov_subjects, by: 0)
    native_source = source_imaging(native_source_inputs)

    dataset_token_ch = native_dataset_ch
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            tuple(dataset_name, 'dataset')
        }
    report_only_token_ch = native_dataset_ch
        .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            asMap(effective_config._steps).primary == 'report'
        }
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            tuple(dataset_name, 'report')
        }
    anatomy_token_ch = native_anatomy_subject_ch.map { dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config ->
        tuple(dataset_name, 'anatomy')
    }
    artifacts_token_ch = native_artifacts_with_hash.map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifactHash ->
        tuple(dataset_name, 'artifacts')
    }
    clean_token_ch = native_clean_subject_ch.map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
        tuple(dataset_name, 'clean')
    }
    epoch_token_ch = native_epoch_subject_ch.map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash ->
        tuple(subjectKey[0], 'epochs')
    }
    source_token_ch = native_source.source_subjects.map { key, output_dir, preproc_dir, source_dir ->
        tuple(key[0], 'source')
    }
    report_wait_token_ch = dataset_token_ch
        .mix(report_only_token_ch)
        .mix(anatomy_token_ch)
        .mix(artifacts_token_ch)
        .mix(clean_token_ch)
        .mix(epoch_token_ch)
        .mix(source_token_ch)
        .groupTuple()
        .map { dataset_name, tokens ->
            tuple(dataset_name, tokens.collect { it.toString() }.join(','))
        }

    native_report_input_ch = native_dataset_report_row_ch
        .combine(report_wait_token_ch, by: 0)
        .map { dataset_name, output_dir, preproc_dir, report_script, manifest_json, bad_channel_threshold, bad_segment_threshold, coreg_mean_threshold, coreg_max_threshold, epoch_reject_rate_threshold, megqc_alarm_score, static_artifact_overview_duration, alert_missing_ecg_components, alert_missing_eog_components, static_task_log_mode, wait_token ->
            tuple(dataset_name, output_dir, preproc_dir, wait_token, report_script, manifest_json, bad_channel_threshold, bad_segment_threshold, coreg_mean_threshold, coreg_max_threshold, epoch_reject_rate_threshold, megqc_alarm_score, static_artifact_overview_duration, alert_missing_ecg_components, alert_missing_eog_components, static_task_log_mode)
        }

    native_reports = generate_static_html_report(native_report_input_ch)
    if (corpusMode) {
        generate_corpus_static_html_report(native_reports.dataset_reports.map { dataset_name, output_dir, preproc_dir, marker -> marker }.collect())
    }
}
