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

String fileStatFingerprint(def pathValue) {
    def target = new File(pathValue.toString())
    if (!target.exists()) {
        return "missing:${target.absolutePath}"
    }

    def rows = []
    if (target.isDirectory()) {
        target.eachFileRecurse(FileType.FILES) { file ->
            rows << "${target.toPath().relativize(file.toPath())}:${file.length()}:${file.lastModified()}"
        }
        rows = rows.sort()
    } else {
        rows << "${target.name}:${target.length()}:${target.lastModified()}"
    }

    def digest = MessageDigest.getInstance("SHA-256")
    digest.update(rows.join("\n").getBytes("UTF-8"))
    return "stat:${target.absolutePath}:${digest.digest().collect { String.format('%02x', it & 0xff) }.join()}"
}

String codeTreeStatFingerprint(def pathValue) {
    def target = new File(pathValue.toString())
    if (!target.exists()) {
        return "missing:${target.absolutePath}"
    }
    def rows = []
    target.eachFileRecurse(FileType.FILES) { file ->
        def relative = target.toPath().relativize(file.toPath()).toString()
        def normalized = relative.replace('\\', '/')
        if (normalized.split('/').contains('__pycache__') ||
            normalized.endsWith('.pyc') || normalized.endsWith('.pyo') ||
            normalized.endsWith('.DS_Store')) {
            return
        }
        def isTextImplementationFile = normalized ==~ /.*[.](py|json|ya?ml|toml|cfg|ini)$/
        rows << (isTextImplementationFile ?
            "${normalized}:${fileSha256(file)}" :
            "${normalized}:${file.length()}:${file.lastModified()}")
    }
    def digest = MessageDigest.getInstance("SHA-256")
    digest.update(rows.sort().join("\n").getBytes("UTF-8"))
    return "code-tree:${target.absolutePath}:${digest.digest().collect { String.format('%02x', it & 0xff) }.join()}"
}

String anatomyModelFingerprint(def fsSubjectsDirValue, String subjectName) {
    def subjectDir = new File(fsSubjectsDirValue.toString(), subjectName)
    def inputs = [
        new File(subjectDir, 'bem'),
        new File(subjectDir, 'mri/T1.mgz'),
        new File(subjectDir, 'surf/lh.white'),
        new File(subjectDir, 'surf/rh.white'),
        new File(subjectDir, 'surf/lh.pial'),
        new File(subjectDir, 'surf/rh.pial'),
        new File(subjectDir, 'surf/lh.seghead')
    ]
    return inputs.collect { input -> fileStatFingerprint(input) }.join('|')
}

String anatomyReconstructionFingerprint(def fsSubjectsDirValue, String subjectName) {
    def subjectDir = new File(fsSubjectsDirValue.toString(), subjectName)
    def inputs = [
        new File(subjectDir, 'mri/T1.mgz'),
        new File(subjectDir, 'surf/lh.white'),
        new File(subjectDir, 'surf/rh.white'),
        new File(subjectDir, 'surf/lh.pial'),
        new File(subjectDir, 'surf/rh.pial'),
        new File(subjectDir, 'surf/lh.seghead')
    ]
    return inputs.collect { input -> fileStatFingerprint(input) }.join('|')
}

boolean filesystemPathsOverlap(def firstValue, def secondValue) {
    def first = new File(firstValue.toString()).absoluteFile.toPath().normalize()
    def second = new File(secondValue.toString()).absoluteFile.toPath().normalize()
    return first.startsWith(second) || second.startsWith(first)
}

String selectedInputInventoryFingerprint(
    def rootValue,
    def suffixValues,
    List excludedPathValues = [],
    String filenameToken = ''
) {
    def root = new File(rootValue.toString())
    if (!root.isDirectory()) {
        return "missing:${root.absolutePath}"
    }
    def suffixes = asList(suffixValues)
        .collect { it.toString().trim().toLowerCase() }
        .findAll { it }
    def excludedPaths = excludedPathValues
        .findAll { it != null && it.toString().trim() }
        .collect { new File(it.toString()).absoluteFile.toPath().normalize() }
    def token = filenameToken.toLowerCase()
    def rows = []

    def pendingDirectories = [root]
    def visitedDirectories = [] as Set
    while (pendingDirectories) {
        def current = pendingDirectories.remove(pendingDirectories.size() - 1)
        def currentPath = current.canonicalFile.toPath().normalize().toString()
        if (!visitedDirectories.add(currentPath)) {
            continue
        }
        (current.listFiles() ?: []).sort { it.name }.each { candidate ->
            def candidatePath = candidate.absoluteFile.toPath().normalize()
            if (excludedPaths.any { excluded -> candidatePath.startsWith(excluded) }) {
                return
            }
            def lowerName = candidate.name.toLowerCase()
            def suffixMatches = suffixes.any { suffix -> lowerName.endsWith(suffix) }
            def tokenMatches = !token || lowerName.contains(token)
            if (candidate.isDirectory()) {
                if (suffixMatches && tokenMatches) {
                    def relative = root.toPath().relativize(candidate.toPath()).toString()
                    rows << "${relative}:${fileStatFingerprint(candidate)}"
                } else {
                    pendingDirectories << candidate
                }
            } else if (suffixMatches && tokenMatches) {
                def relative = root.toPath().relativize(candidate.toPath()).toString()
                rows << "${relative}:${candidate.length()}:${candidate.lastModified()}"
            }
        }
    }

    def digest = MessageDigest.getInstance("SHA-256")
    digest.update(rows.sort().join("\n").getBytes("UTF-8"))
    return "inventory:${root.absolutePath}:${digest.digest().collect { String.format('%02x', it & 0xff) }.join()}"
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

String megInputStem(def pathValue) {
    def name = new File(pathValue.toString()).name
    if (name.toLowerCase().endsWith('.fif.gz')) {
        return name.substring(0, name.length() - '.fif.gz'.length())
    }
    def dotIndex = name.lastIndexOf('.')
    return dotIndex > 0 ? name.substring(0, dotIndex) : name
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

String megflowImplementationFingerprint(def codeDirValue) {
    def codeDir = new File(codeDirValue.toString())
    def topLevelScripts = [
        'anat_get_t1w_file_in_bids.py', 'apply_ica.py', 'compute_covariance.py',
        'coregistration.py', 'create_pseudomri.py', 'epochs.py',
        'epochs_preproc.py', 'forward_solution.py', 'generate_bem.py',
        'meg_detect_artifacts.py', 'meg_import_dataset.py',
        'meg_preproc_osl.py', 'meg_quality_control.py', 'mri_import_dataset.py',
        'run_ica.py', 'run_ica_label.py', 'source_localization.py', 'utils.py'
    ].collect { name -> new File(codeDir, name) }
    def toolTrees = [
        'tools/Repairbads', 'tools/deepreject', 'tools/ica_classify',
        'tools/megqc', 'tools/mne-faster', 'tools/mne-icalabel/mne_icalabel',
        'tools/osl', 'tools/osl-ephys/osl_ephys/preprocessing',
        'tools/pseudomri', 'tools/pyprep'
    ].collect { name -> new File(codeDir, name) }
    return filesSha256(topLevelScripts) + '|' +
        toolTrees.collect { tree -> codeTreeStatFingerprint(tree) }.join('|')
}

String icaLabelImplementationFingerprint(def codeDirValue) {
    def codeDir = new File(codeDirValue.toString())
    return filesSha256([
        new File(codeDir, 'run_ica_label.py'),
        new File(codeDir, 'utils.py'),
        new File(codeDir, 'tools/megnet_retrained/__init__.py'),
        new File(codeDir, 'tools/megnet_retrained/inference.py'),
        new File(codeDir, 'tools/megnet_retrained/runtime/__init__.py'),
        new File(codeDir, 'tools/megnet_retrained/runtime/preprocessing.py'),
        new File(codeDir, 'tools/megnet_retrained/model.onnx')
    ]) + '|' + codeTreeStatFingerprint(
        new File(codeDir, 'tools/ica_classify')
    )
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

String stubFailureCommand(Map effectiveConfig, String processName) {
    def requested = cfgText(effectiveConfig, ['test_stub_fail_process'], '')
        .split(',')
        .collect { it.trim().toLowerCase() }
        .findAll { it }
    if (!requested.contains(processName.toLowerCase())) {
        return ':'
    }
    return "echo 'Injected stub failure: ${processName}' >&2; exit 1"
}

boolean sourceUsesLcmv(Map effectiveConfig) {
    return asList(cfgGet(effectiveConfig, ['source', 'source_methods'], []))
        .any { method -> method != null && method.toString().equalsIgnoreCase('LCMV') }
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
    if (moduleName == 'preproc' && cfg.containsKey('steps')) {
        def out = new LinkedHashMap(cfg)
        def steps = out.remove('steps')
        if (!out.containsKey('preproc')) {
            out.preproc = steps
        }
        return out
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

Map fixedProcessOutputDirs() {
    return [
        ica: 'ica_report',
        epochs: 'epochs',
        coreg: 'trans',
        covariance: 'covariance',
        forward: 'forward_solution',
        source: 'source_recon'
    ]
}

String processOutputDir(String moduleName) {
    def outputDir = fixedProcessOutputDirs()[moduleName]
    if (outputDir == null) {
        throw new IllegalArgumentException("Unknown process output directory module: ${moduleName}")
    }
    return outputDir
}

void validateFixedProcessOutputDirs(Map config, String context) {
    fixedProcessOutputDirs().each { moduleName, expectedDir ->
        def moduleValue = config[moduleName]
        if (!(moduleValue instanceof Map) || !moduleValue.containsKey('output_dir')) {
            return
        }
        def configuredDir = moduleValue.output_dir == null ? '' : moduleValue.output_dir.toString()
        if (configuredDir != expectedDir) {
            throw new IllegalArgumentException(
                "${context}.${moduleName}.output_dir is internal and fixed to '${expectedDir}'. " +
                "Remove this field; change params.megflow.output_dir or the dataset-level output_dir instead."
            )
        }
    }
}

void validateReportConfig(Map config, String context) {
    def taskLogMode = cfgText(
        config,
        ['report', 'static_task_log_mode'],
        'all-command-log'
    ).trim().toLowerCase()
    def allowedTaskLogModes = ['failed', 'all-command-log', 'none'] as Set
    if (!allowedTaskLogModes.contains(taskLogMode)) {
        throw new IllegalArgumentException(
            "${context}.report.static_task_log_mode must be one of " +
            "${allowedTaskLogModes.sort()}; received '${taskLogMode}'."
        )
    }

    def durationValue = cfgGet(
        config,
        ['report', 'static_artifact_overview_duration'],
        200.0
    )
    BigDecimal duration
    try {
        duration = new BigDecimal(durationValue.toString())
    } catch (NumberFormatException ignored) {
        duration = null
    }
    if (duration == null || duration <= 0) {
        throw new IllegalArgumentException(
            "${context}.report.static_artifact_overview_duration must be a positive number; " +
            "received '${durationValue}'."
        )
    }
}

void validateAnatomyInputConfig(Map config, String context) {
    def inputType = cfgText(config, ['anatomy', 't1_input_type'], 'nifti')
        .trim()
        .toLowerCase()
    if (!(inputType in ['nifti', 'dicom'])) {
        throw new IllegalArgumentException(
            "${context}.anatomy.t1_input_type must be nifti or dicom; received '${inputType}'."
        )
    }

    def dicomSeriesGlob = cfgText(
        config,
        ['anatomy', 't1_dicom_series_glob'],
        ''
    ).trim()
    def windowsAbsolute = dicomSeriesGlob ==~ /^[A-Za-z]:[\\\/].*/
    if (dicomSeriesGlob && (new File(dicomSeriesGlob).isAbsolute() || windowsAbsolute)) {
        throw new IllegalArgumentException(
            "${context}.anatomy.t1_dicom_series_glob must be relative to the T1 DICOM root; " +
            "received '${dicomSeriesGlob}'."
        )
    }
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

    matcher = (name =~ /(?:^|_)sub-([A-Za-z0-9]+)/)
    if (matcher.find()) {
        subject = matcher.group(1)
    } else {
        matcher = (text =~ /(?:^|[\\\/])sub-([A-Za-z0-9]+)/)
        while (matcher.find()) {
            subject = matcher.group(1)
        }
    }
    matcher = (name =~ /(?:^|_)ses-([A-Za-z0-9]+)/)
    if (matcher.find()) {
        session = matcher.group(1)
    } else {
        matcher = (text =~ /(?:^|[\\\/])ses-([A-Za-z0-9]+)/)
        while (matcher.find()) {
            session = matcher.group(1)
        }
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

String recordingOutputId(def rawPathValue) {
    def name = new File(rawPathValue.toString()).getName()
    def outputId = name.replaceFirst(/\.[^.]+$/, '')
    if (!outputId) {
        throw new IllegalArgumentException("Could not derive a recording output id from: ${rawPathValue}")
    }
    return outputId
}

List recordingKey(String datasetName, def rawPathValue) {
    return [datasetName, recordingOutputId(rawPathValue)]
}

String replaceRecordingTaskEntity(def rawPathValue, String taskId) {
    def rawPath = new File(rawPathValue.toString())
    def name = rawPath.getName()
    def normalizedTaskId = taskId == null ? '' : taskId.trim()
    if (!(normalizedTaskId ==~ /[A-Za-z0-9-]+/)) {
        throw new IllegalArgumentException(
            "covariance.raw_covariance_task_id must contain only letters, numbers, or hyphens: ${taskId}"
        )
    }
    if (!(name =~ /task-[^_\/.]+/)) {
        throw new IllegalArgumentException(
            "Raw covariance pairing requires a task- entity in the recording filename: ${rawPathValue}"
        )
    }
    def pairedName = name.replaceFirst(/task-[^_\/.]+/, "task-${normalizedTaskId}")
    return new File(rawPath.getParentFile(), pairedName).toString()
}

boolean isRawCovarianceReferenceKey(def referenceKeys, String datasetName, def rawPathValue) {
    def keys = referenceKeys instanceof Map ? referenceKeys.recording_keys : referenceKeys
    return (keys ?: []).contains(recordingKey(datasetName, rawPathValue))
}

boolean hasMeaningfulMatchValue(def value) {
    if (value == null) {
        return false
    }
    if (value instanceof Collection) {
        return value.any { item -> item != null && item.toString().trim() }
    }
    return value.toString().trim().size() > 0
}

void validateRecordingProfiles(Map effectiveConfig, String context) {
    validateFixedProcessOutputDirs(effectiveConfig, context)
    if (!effectiveConfig.containsKey('recordings')) {
        return
    }
    if (!(effectiveConfig.recordings instanceof Map)) {
        throw new IllegalArgumentException("${context}.recordings must be a map")
    }

    def allowedMatchKeys = ['subject', 'session', 'task', 'run', 'suffix', 'filename_contains'] as Set
    def forbiddenOverrideKeys = [
        'name', 'dataset_dir', 'output_dir', 'preproc_dir', 'fs_subjects_dir', 't1_dir',
        'dataset_format', 'file_suffix', 'is_bids', 'code_dir', 'meg_import', 'mri_import',
        'anatomy', 'bem', 'report', 'recordings', 'profile_name', '_steps', '_recording'
    ] as Set

    asMap(effectiveConfig.recordings).each { profileName, profileValue ->
        if (!(profileValue instanceof Map)) {
            throw new IllegalArgumentException("${context}.recordings.${profileName} must be a map")
        }
        def profile = asMap(profileValue)
        validateFixedProcessOutputDirs(
            profile,
            "${context}.recordings.${profileName}"
        )
        if (!(profile.match instanceof Map) || asMap(profile.match).isEmpty()) {
            throw new IllegalArgumentException(
                "${context}.recordings.${profileName}.match must be a non-empty map"
            )
        }
        def matchSpec = asMap(profile.match)
        def unknownMatchKeys = matchSpec.keySet().collect { it.toString() }.findAll {
            !allowedMatchKeys.contains(it)
        }
        if (unknownMatchKeys) {
            throw new IllegalArgumentException(
                "Unknown match fields in ${context}.recordings.${profileName}: ${unknownMatchKeys.sort()}. " +
                "Allowed fields: ${allowedMatchKeys.sort()}"
            )
        }
        if (!matchSpec.values().any { value -> hasMeaningfulMatchValue(value) }) {
            throw new IllegalArgumentException(
                "${context}.recordings.${profileName}.match must contain at least one non-empty selector"
            )
        }
        def forbidden = profile.keySet().collect { it.toString() }.findAll {
            forbiddenOverrideKeys.contains(it)
        }
        if (forbidden) {
            throw new IllegalArgumentException(
                "Recording profile ${context}.recordings.${profileName} contains dataset-only fields: ${forbidden.sort()}"
            )
        }
    }
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
    def overrideKeys = []
    if (matches.size() == 1) {
        recordingProfileName = matches[0].name
        def override = new LinkedHashMap(matches[0].profile)
        override.remove('match')
        overrideKeys = override.keySet().collect { it.toString() }
        effective = deepMerge(effective, override)
    }
    effective.remove('recordings')
    effective._recording = [profile_name: recordingProfileName, meta: meta, override_keys: overrideKeys]
    return effective
}

List resolveDatasetProfiles(def megflowRaw) {
    if (!(megflowRaw instanceof Map)) {
        throw new IllegalArgumentException("params.megflow must be a map")
    }
    def mf = asMap(megflowRaw)
    if (!mf) {
        throw new IllegalArgumentException("params.megflow is required. MEGFlow profile v2 no longer reads legacy dataset/config parameters.")
    }
    if (mf.defaults != null && !(mf.defaults instanceof Map)) {
        throw new IllegalArgumentException("params.megflow.defaults must be a map")
    }
    if (mf.datasets != null && !(mf.datasets instanceof Map)) {
        throw new IllegalArgumentException("params.megflow.datasets must be a map")
    }
    def defaults = asMap(mf.defaults)
    def datasets = asMap(mf.datasets)
    datasets.each { profileName, profileValue ->
        if (!(profileValue instanceof Map)) {
            throw new IllegalArgumentException("params.megflow.datasets.${profileName} must be a map")
        }
    }
    def normalizedProfileNames = datasets.keySet().groupBy { key -> datasetLookupKey(key) }
    def ambiguousProfileNames = normalizedProfileNames.findAll { lookup, names -> names.size() > 1 }
    if (ambiguousProfileNames) {
        throw new IllegalArgumentException(
            "Dataset profile names collide after normalization: ${ambiguousProfileNames}"
        )
    }
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
        def profileContext = "params.megflow.datasets.${profileKey ?: candidateName}"
        validateReportConfig(effective, profileContext)
        validateAnatomyInputConfig(effective, profileContext)
        validateRecordingProfiles(effective, profileContext)
        def datasetName = sanitizeDatasetName((profile.name ?: candidateName).toString())
        def datasetDir = (profile.dataset_dir ?: candidate.dataset_dir).toString()
        if (!new File(datasetDir).isDirectory()) {
            throw new IllegalArgumentException("Dataset directory is not a directory: ${datasetDir}")
        }
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

    def duplicateDatasetNames = resolved.groupBy { datasetLookupKey(it.dataset_name) }.findAll { key, values -> values.size() > 1 }
    if (duplicateDatasetNames) {
        throw new IllegalArgumentException("Resolved dataset names are not unique: ${duplicateDatasetNames.keySet()}")
    }
    ['output_dir', 'preproc_dir'].each { field ->
        def duplicatePaths = resolved.groupBy { profile ->
            new File(profile[field].toString()).absoluteFile.toPath().normalize().toString()
        }.findAll { path, values -> values.size() > 1 }
        if (duplicatePaths) {
            throw new IllegalArgumentException(
                "Resolved datasets share ${field} paths: ${duplicatePaths.collectEntries { path, values -> [path, values*.dataset_name] }}"
            )
        }
        for (int firstIndex = 0; firstIndex < resolved.size(); firstIndex++) {
            for (int secondIndex = firstIndex + 1; secondIndex < resolved.size(); secondIndex++) {
                def first = resolved[firstIndex]
                def second = resolved[secondIndex]
                if (filesystemPathsOverlap(first[field], second[field])) {
                    throw new IllegalArgumentException(
                        "Resolved datasets have overlapping ${field} paths: " +
                        "${first.dataset_name}=${first[field]}, ${second.dataset_name}=${second[field]}"
                    )
                }
            }
        }
    }
    for (int firstIndex = 0; firstIndex < resolved.size(); firstIndex++) {
        for (int secondIndex = firstIndex + 1; secondIndex < resolved.size(); secondIndex++) {
            def first = resolved[firstIndex]
            def second = resolved[secondIndex]
            if (filesystemPathsOverlap(first.output_dir, second.preproc_dir) ||
                filesystemPathsOverlap(second.output_dir, first.preproc_dir)) {
                throw new IllegalArgumentException(
                    "Resolved datasets have cross-overlapping output/preproc paths: " +
                    "${first.dataset_name} output=${first.output_dir}, preproc=${first.preproc_dir}; " +
                    "${second.dataset_name} output=${second.output_dir}, preproc=${second.preproc_dir}"
                )
            }
        }
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

    stub:
    """
    touch corpus_static_html_report_done.txt
    """
}

process import_mri_dataset {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(t1_inventory_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), path('imported_t1_data.txt'), emit: imported_t1_data

    script:
    script_name = "${megflowCodeDir(effective_config)}/mri_import_dataset.py"
    code_hash = fileSha256(script_name)
    mri_import_config = moduleConfigJson(effective_config, 'mri_import')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_T1_INVENTORY=${t1_inventory_hash}
    mkdir -p "${preproc_dir}"
    python ${script_name} \\
        --bids_dir "${t1_dir}" \\
        --config '${mri_import_config}' \\
        --output_file imported_t1_data.txt
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/mri_import_dataset.py"
    code_hash = fileSha256(script_name)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_T1_INVENTORY=${t1_inventory_hash}
    set -euo pipefail
    : > imported_t1_data.txt
    find "${t1_dir}" -type f | grep -E 'T1w[.]nii([.]gz)?' | sort | while read -r anat_file; do
        subject_name=\$(basename "\${anat_file}" | grep -oE 'sub-[A-Za-z0-9]+' | head -n 1)
        [ -n "\${subject_name}" ] || continue
        printf "%s:['%s']\n" "\${subject_name}" "\${anat_file}" >> imported_t1_data.txt
    done
    """
}

process dcm2niix {
    tag "${dataset_name}:${t1_dicom_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(t1_dicom_dir), val(t1_dicom_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), path("converted"), emit: nifti_dirs

    script:
    t1_dicom_basename = file(t1_dicom_dir).getName()
    series_glob = cfgText(effective_config, ['anatomy', 't1_dicom_series_glob'], '')
    """
    # MEGFLOW_DICOM_INPUT=${t1_dicom_hash}
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

    stub:
    t1_dicom_basename = file(t1_dicom_dir).getName()
    """
    # MEGFLOW_DICOM_INPUT=${t1_dicom_hash}
    mkdir -p converted
    touch "converted/${t1_dicom_basename}_stub.nii.gz"
    """
}

process generate_pseudomri {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(raw_subject_path), val(subject_name)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val("${preproc_dir}/pseudomri/${subject_name}/${subject_name}.nii.gz"), val(subject_name), emit: pseudo_t1_inputs
    path "pseudomri-output.guard", emit: pseudomri_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/create_pseudomri.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_input_hash = fileStatFingerprint(raw_subject_path)
    template_dir = cfgText(effective_config, ['anatomy', 'pseudomri_template_dir'], "${megflowCodeDir(effective_config)}/tools/pseudomri")
    template_subject = cfgText(effective_config, ['anatomy', 'pseudomri_template_subject'], "mni_icbm152_nlin_sym_09a")
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RAW_INPUT=${raw_input_hash}
    set -euo pipefail
    python ${script_name} \\
        --info_fif "${raw_subject_path}" \\
        --subject "${subject_name}" \\
        --output_dir "${preproc_dir}/pseudomri/${subject_name}" \\
        --template_dir "${template_dir}" \\
        --template_subject "${template_subject}"
    ln -s "${preproc_dir}/pseudomri/${subject_name}/${subject_name}.nii.gz" pseudomri-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/create_pseudomri.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_input_hash = fileStatFingerprint(raw_subject_path)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RAW_INPUT=${raw_input_hash}
    mkdir -p "${preproc_dir}/pseudomri/${subject_name}"
    touch "${preproc_dir}/pseudomri/${subject_name}/${subject_name}.nii.gz"
    ln -s "${preproc_dir}/pseudomri/${subject_name}/${subject_name}.nii.gz" pseudomri-output.guard
    """
}

process run_freesurfer {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(anat_file), val(subject_name), val(t1_input_hash)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val("${fs_subjects_dir}/${subject_name}"), val(effective_config), emit: fs_subjects
    path "freesurfer-reconstruction.guard", emit: freesurfer_reconstruction_cache_guard
    path "freesurfer-head-surface.guard", emit: freesurfer_head_surface_cache_guard

    script:
    """
    # MEGFLOW_T1_INPUT=${t1_input_hash}
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
    ln -s "${fs_subjects_dir}/${subject_name}/scripts/recon-all.done" freesurfer-reconstruction.guard
    ln -s "${fs_subjects_dir}/${subject_name}/surf/lh.seghead" freesurfer-head-surface.guard
    """

    stub:
    """
    # MEGFLOW_T1_INPUT=${t1_input_hash}
    mkdir -p "${fs_subjects_dir}/${subject_name}/scripts" "${fs_subjects_dir}/${subject_name}/surf" "${fs_subjects_dir}/${subject_name}/bem"
    touch "${fs_subjects_dir}/${subject_name}/scripts/recon-all.done"
    touch "${fs_subjects_dir}/${subject_name}/surf/lh.seghead"
    ln -s "${fs_subjects_dir}/${subject_name}/scripts/recon-all.done" freesurfer-reconstruction.guard
    ln -s "${fs_subjects_dir}/${subject_name}/surf/lh.seghead" freesurfer-head-surface.guard
    """
}

process run_deepprep {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(subject_name), val(t1_input_hash)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val("${fs_subjects_dir}/${subject_name}"), val(effective_config), val(t1_input_hash), emit: fs_subjects
    path "deepprep-reconstruction.guard", emit: deepprep_reconstruction_cache_guard

    script:
    output_dir = "${preproc_dir}/deepprep/${subject_name}"
    deepprep_device = cfgText(effective_config, ['anatomy', 'deepprep_device'], 'cpu')
    fs_license_file = cfgText(effective_config, ['anatomy', 'fs_license_file'], '/fs_license.txt')
    mri_import_subject_id = subject_name.replaceFirst(/^sub-/, '')
    mri_import_config = yamlFlowString(deepMerge(moduleConfig(effective_config, 'mri_import'), [subject_id: [mri_import_subject_id]]))
    """
    # MEGFLOW_T1_INPUT=${t1_input_hash}
    set -euo pipefail
    mkdir -p "${fs_subjects_dir}" "${output_dir}"

    deepprep_command="/opt/DeepPrep/deepprep/deepprep.sh"
    fs_license_file="${fs_license_file}"

    if [ ! -x "\${deepprep_command}" ]; then
        echo "DeepPrep is not available in this runtime: \${deepprep_command}" >&2
        echo "Run MEGFlow in cplmeg/megflow:1.0.0 or use the Nextflow docker/singularity execution profile." >&2
        exit 1
    fi
    if [ ! -f "\${fs_license_file}" ]; then
        echo "FreeSurfer license file not found: \${fs_license_file}" >&2
        exit 1
    fi

    run_deepprep_args=(
        "${t1_dir}"
        "${output_dir}"
        participant
        --participant_label "${subject_name}"
        --skip_bids_validation
        --anat_only
        --fs_license_file "\${fs_license_file}"
        --device "${deepprep_device}"
        --mri_import_config "${mri_import_config}"
        --resume
    )

    "\${deepprep_command}" "\${run_deepprep_args[@]}"

    kill -9 \$(pgrep redis-server) || true
    cp -rf "${output_dir}/Recon/"* "${fs_subjects_dir}/"
    ln -s "${fs_subjects_dir}/${subject_name}/scripts/recon-all.done" deepprep-reconstruction.guard
    """

    stub:
    """
    # MEGFLOW_T1_INPUT=${t1_input_hash}
    mkdir -p "${fs_subjects_dir}/${subject_name}/scripts" "${fs_subjects_dir}/${subject_name}/surf" "${fs_subjects_dir}/${subject_name}/bem"
    touch "${fs_subjects_dir}/${subject_name}/scripts/recon-all.done"
    ln -s "${fs_subjects_dir}/${subject_name}/scripts/recon-all.done" deepprep-reconstruction.guard
    """
}

process run_mkheadsurf {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config), val(reconstruction_input_hash)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config), val(reconstruction_input_hash), emit: fs_subjects
    path "mkheadsurf-output.guard", emit: mkheadsurf_cache_guard

    script:
    """
    # MEGFLOW_RECONSTRUCTION_INPUT=${reconstruction_input_hash}
    mkheadsurf -sd "${fs_subjects_dir}" -s "${subject_name}" -srcvol T1.mgz -thresh1 30
    ln -s "${subject_dir}/surf/lh.seghead" mkheadsurf-output.guard
    """

    stub:
    """
    # MEGFLOW_RECONSTRUCTION_INPUT=${reconstruction_input_hash}
    mkdir -p "${subject_dir}/surf"
    touch "${subject_dir}/surf/lh.seghead"
    ln -s "${subject_dir}/surf/lh.seghead" mkheadsurf-output.guard
    """
}

process generate_bem {
    tag "${dataset_name}:${subject_name}"

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config), val(reconstruction_hash)

    output:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(subject_name), val(fs_subjects_dir), val(subject_dir), val(effective_config), emit: bem_subjects
    path "bem-surfaces-output.guard", emit: bem_surfaces_cache_guard
    path "bem-solution-output.guard", emit: bem_solution_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/generate_bem.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    subject_basename = file(subject_dir).getBaseName()
    bem_ico = cfgGet(effective_config, ['bem', 'ico'], 4)
    bem_config = moduleConfigJson(effective_config, 'bem')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RECONSTRUCTION_INPUT=${reconstruction_hash}
    python3 ${script_name} \\
        --subject_dir "${subject_dir}" \\
        --config '${bem_config}' \\
        --output_dir "${fs_subjects_dir}/${subject_basename}/bem"
    ln -s "${fs_subjects_dir}/${subject_basename}/bem/${subject_basename}_ico${bem_ico}_watershed_bem.fif" bem-surfaces-output.guard
    ln -s "${fs_subjects_dir}/${subject_basename}/bem/${subject_basename}_ico${bem_ico}_watershed_bem-sol.fif" bem-solution-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/generate_bem.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    subject_basename = file(subject_dir).getBaseName()
    bem_ico = cfgGet(effective_config, ['bem', 'ico'], 4)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RECONSTRUCTION_INPUT=${reconstruction_hash}
    mkdir -p "${subject_dir}/bem"
    touch "${subject_dir}/bem/stub-bem.done"
    touch "${subject_dir}/bem/${subject_basename}_ico${bem_ico}_watershed_bem.fif"
    touch "${subject_dir}/bem/${subject_basename}_ico${bem_ico}_watershed_bem-sol.fif"
    ln -s "${subject_dir}/bem/${subject_basename}_ico${bem_ico}_watershed_bem.fif" bem-surfaces-output.guard
    ln -s "${subject_dir}/bem/${subject_basename}_ico${bem_ico}_watershed_bem-sol.fif" bem-solution-output.guard
    """
}

process import_meg_dataset {
    tag "${dataset_name}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(raw_inventory_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), path('imported_meg_data.txt'), emit: imported_meg_data

    script:
    script_name = "${megflowCodeDir(effective_config)}/meg_import_dataset.py"
    code_hash = fileSha256(script_name)
    dataset_format = cfgText(effective_config, ['dataset_format'], 'auto')
    file_suffix = cfgText(effective_config, ['file_suffix'], '.fif')
    meg_import_config = moduleConfigJson(effective_config, 'meg_import')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RAW_INVENTORY=${raw_inventory_hash}
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

    stub:
    script_name = "${megflowCodeDir(effective_config)}/meg_import_dataset.py"
    code_hash = fileSha256(script_name)
    file_suffix = cfgText(effective_config, ['file_suffix'], '.fif')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RAW_INVENTORY=${raw_inventory_hash}
    set -euo pipefail
    : > imported_meg_data.txt
    find "${dataset_dir}" -name "*${file_suffix}" | sort > imported_meg_data.txt
    """
}

process score_meg_quality {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 4.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), path("*.summary.json"), path("*.component_scores.csv"), path("*.normative_quality_score.png"), emit: qc_subjects
    path "qc-summary-output.guard", emit: qc_summary_cache_guard
    path "qc-components-output.guard", emit: qc_components_cache_guard
    path "qc-plot-output.guard", emit: qc_plot_cache_guard

    script:
    raw_subject_basename = file(orig_raw_path).getBaseName()
    script_name = "${megflowCodeDir(effective_config)}/meg_quality_control.py"
    qc_code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/tools/megqc/score_meg_reference_quota_standalone.py"])
    raw_input_hash = fileStatFingerprint(orig_raw_path)
    qc_output_dir = "${preproc_dir}/quality_control/${raw_subject_basename}"
    qc_output_stem = megInputStem(orig_raw_path)
    megqc_config = moduleConfig(effective_config, 'megqc')
    qc_preproc_config = configJson([preproc: cfgGet(megqc_config, ['preproc'], [])])
    qc_meg_vendor = cfgText(megqc_config, ['meg_vendor'], 'auto')
    """
    set -euo pipefail
    # MEGFLOW_RAW_INPUT=${raw_input_hash}
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
    cp "${qc_output_dir}/${qc_output_stem}.summary.json" .
    cp "${qc_output_dir}/${qc_output_stem}.component_scores.csv" .
    cp "${qc_output_dir}/${qc_output_stem}.normative_quality_score.png" .
    ln -s "${qc_output_dir}/${qc_output_stem}.summary.json" qc-summary-output.guard
    ln -s "${qc_output_dir}/${qc_output_stem}.component_scores.csv" qc-components-output.guard
    ln -s "${qc_output_dir}/${qc_output_stem}.normative_quality_score.png" qc-plot-output.guard
    """

    stub:
    raw_subject_basename = file(orig_raw_path).getBaseName()
    script_name = "${megflowCodeDir(effective_config)}/meg_quality_control.py"
    qc_code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/tools/megqc/score_meg_reference_quota_standalone.py"])
    raw_input_hash = fileStatFingerprint(orig_raw_path)
    qc_output_dir = "${preproc_dir}/quality_control/${raw_subject_basename}"
    qc_output_stem = megInputStem(orig_raw_path)
    qc_stub_score = cfgGet(effective_config, ['test_stub_qc_score'], 100.0)
    """
    # MEGFLOW_CODE_SHA256=${qc_code_hash}
    # MEGFLOW_RAW_INPUT=${raw_input_hash}
    ${stubFailureCommand(effective_config, 'score_meg_quality')}
    mkdir -p "${qc_output_dir}"
    printf '{"score_0_100": %s}\n' "${qc_stub_score}" > "${qc_output_stem}.summary.json"
    printf 'metric,score\nstub,100\n' > "${qc_output_stem}.component_scores.csv"
    touch "${qc_output_stem}.normative_quality_score.png"
    cp "${qc_output_stem}.summary.json" "${qc_output_dir}/"
    cp "${qc_output_stem}.component_scores.csv" "${qc_output_dir}/"
    cp "${qc_output_stem}.normative_quality_score.png" "${qc_output_dir}/"
    ln -s "${qc_output_dir}/${qc_output_stem}.summary.json" qc-summary-output.guard
    ln -s "${qc_output_dir}/${qc_output_stem}.component_scores.csv" qc-components-output.guard
    ln -s "${qc_output_dir}/${qc_output_stem}.normative_quality_score.png" qc-plot-output.guard
    """
}

process meg_basic_preproc {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 6.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val("${preproc_dir}/${raw_subject_basename}/${raw_subject_basename}_preproc-raw.fif"), emit: preproc_subjects
    path "preproc-output.guard", emit: preproc_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/meg_preproc_osl.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_input_hash = fileStatFingerprint(orig_raw_path)
    raw_subject_basename = file(orig_raw_path).getBaseName()
    preproc_module_config = normalizeModuleConfig('preproc', asMap(effective_config.preproc))
    preproc_config = configJson(
        preproc_module_config + [
            digitization: asMap(effective_config.digitization)
        ]
    )
    osl_seed = cfgGet(effective_config, ['seeds', 'osl'], 2025)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RAW_INPUT=${raw_input_hash}
    python ${script_name} \\
        --file "${orig_raw_path}" \\
        --preproc_dir "${preproc_dir}" \\
        --seed ${osl_seed} \\
        --config '${preproc_config}'
    ln -s "${preproc_dir}/${raw_subject_basename}/${raw_subject_basename}_preproc-raw.fif" preproc-output.guard
    """

    stub:
    raw_subject_basename = file(orig_raw_path).getBaseName()
    script_name = "${megflowCodeDir(effective_config)}/meg_preproc_osl.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_input_hash = fileStatFingerprint(orig_raw_path)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_RAW_INPUT=${raw_input_hash}
    ${stubFailureCommand(effective_config, 'meg_basic_preproc')}
    mkdir -p "${preproc_dir}/${raw_subject_basename}"
    printf 'stub preproc %s\n' "${orig_raw_path}" > "${preproc_dir}/${raw_subject_basename}/${raw_subject_basename}_preproc-raw.fif"
    ln -s "${preproc_dir}/${raw_subject_basename}/${raw_subject_basename}_preproc-raw.fif" preproc-output.guard
    """
}

process detect_artifacts {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(preproc_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(preproc_hash), val("${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_channels.txt"), val("${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_segments.txt"), emit: artifacts
    path "bad-channels-output.guard", emit: bad_channels_cache_guard
    path "bad-segments-output.guard", emit: bad_segments_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/meg_detect_artifacts.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py", "${megflowCodeDir(effective_config)}/tools/deepreject/preprocessing.py"])
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_parent = file(preproc_raw_path).getParent().getName()
    artifact_config = new LinkedHashMap(moduleConfig(effective_config, 'artifacts'))
    artifact_config.runtime_cpus = task.cpus
    artifact_config_json = configJson(artifact_config)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_PREPROC_INPUT=${preproc_hash}
    mkdir -p "${preproc_dir}/artifact_report/${raw_subject_parent}"
    python ${script_name} \\
        --input "${preproc_raw_path}" \\
        --output "${preproc_dir}/artifact_report/${raw_subject_parent}" \\
        --config '${artifact_config_json}'
    ln -s "${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_channels.txt" bad-channels-output.guard
    ln -s "${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_segments.txt" bad-segments-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/meg_detect_artifacts.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py", "${megflowCodeDir(effective_config)}/tools/deepreject/preprocessing.py"])
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_parent = file(preproc_raw_path).getParent().getName()
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_PREPROC_INPUT=${preproc_hash}
    ${stubFailureCommand(effective_config, 'detect_artifacts')}
    mkdir -p "${preproc_dir}/artifact_report/${raw_subject_parent}"
    : > "${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_channels.txt"
    : > "${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_segments.txt"
    ln -s "${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_channels.txt" bad-channels-output.guard
    ln -s "${preproc_dir}/artifact_report/${raw_subject_parent}/${raw_subject_basename}_bad_segments.txt" bad-segments-output.guard
    """
}

process run_ica {
    tag "${dataset_name}:${raw_subject_basename}"
    memory { 8.GB * task.attempt }

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val("${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ica_sources.fif"), val("${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif"), emit: ica_subjects
    path "ica-sources-output.guard", emit: ica_sources_cache_guard
    path "ica-decomposition-output.guard", emit: ica_decomposition_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/run_ica.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    ica_config = moduleConfig(effective_config, 'ica')
    ica_output_dir = processOutputDir('ica')
    num_ic = cfgGet(ica_config, ['num_components'], 0.9999)
    compute_explained_variance = cfgBool(ica_config, ['compute_explained_variance'], false)
    ica_seed = cfgGet(effective_config, ['seeds', 'ica'], 2025)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    python ${script_name} \\
        --raw_file "${preproc_raw_path}" \\
        --output_dir "${preproc_dir}/${ica_output_dir}" \\
        --num_IC ${num_ic} \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}" \\
        --seed ${ica_seed} \\
        --compute_explained_variance ${compute_explained_variance}
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ica_sources.fif" ica-sources-output.guard
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif" ica-decomposition-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/run_ica.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    ica_output_dir = processOutputDir('ica')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    ${stubFailureCommand(effective_config, 'run_ica')}
    mkdir -p "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}"
    printf 'stub sources\n' > "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ica_sources.fif"
    printf 'stub ica\n' > "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif"
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ica_sources.fif" ica-sources-output.guard
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif" ica-decomposition-output.guard
    """
}

process run_ic_label {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(ica_source), val(ica_file_path), val(ica_hash), val(ica_label_code_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(ica_hash), val("${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/marked_components.txt"), emit: labelled_subjects
    path "ica-label-output.guard", emit: ica_label_cache_guard
    path "ica-label-scores-output.guard", emit: ica_label_scores_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/run_ica_label.py"
    code_hash = ica_label_code_hash
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    ica_output_dir = processOutputDir('ica')
    ic_label_config = moduleConfigJson(effective_config, 'ic_label')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_ICA_INPUT=${ica_hash}
    python ${script_name} \\
        --raw_data_path "${preproc_raw_path}" \\
        --ica_file "${ica_file_path}" \\
        --ica_sources_file "${ica_source}" \\
        --output_dir "${preproc_dir}/${ica_output_dir}" \\
        --refresh-existing \\
        --config '${ic_label_config}'
    test -f "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/marked_components.txt"
    test -f "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ecg_eog_scores.json"
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/marked_components.txt" ica-label-output.guard
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ecg_eog_scores.json" ica-label-scores-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/run_ica_label.py"
    code_hash = ica_label_code_hash
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    ica_output_dir = processOutputDir('ica')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_ICA_INPUT=${ica_hash}
    ${stubFailureCommand(effective_config, 'run_ic_label')}
    mkdir -p "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}"
    : > "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/marked_components.txt"
    printf '{"methods": {}}\n' > "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ecg_eog_scores.json"
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/marked_components.txt" ica-label-output.guard
    ln -s "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/ecg_eog_scores.json" ica-label-scores-output.guard
    """
}

process apply_ica {
    tag "${dataset_name}:${raw_subject_basename}"

    input:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(preproc_raw_path), val(bad_channels), val(bad_segments), val(artifact_hash), val(ica_hash), val(marked_components), val(marked_hash)

    output:
    tuple val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val("${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif"), val("${target_mri_subject_id}"), val("${artifact_hash}|${ica_hash}|${marked_hash}"), emit: clean_subjects
    path "clean-raw-output.guard", emit: clean_raw_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/apply_ica.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    anatomy_select_tag = cfgText(effective_config, ['anatomy', 'select_tag'], '')
    ica_output_dir = processOutputDir('ica')
    target_mri_subject_id = raw_subject_basename.split('_')[0] + anatomy_select_tag
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    python ${script_name} \\
        --raw_file "${preproc_raw_path}" \\
        --ica_file "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_ica.fif" \\
        --exclude_file "${marked_components}" \\
        --output_file "${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif" \\
        --output_dir "${preproc_dir}/${ica_output_dir}/${raw_subject_dir_basename}" \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}"
    ln -s "${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif" clean-raw-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/apply_ica.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(preproc_raw_path).getBaseName()
    raw_subject_dir_basename = file(preproc_raw_path).getParent().getName()
    anatomy_select_tag = cfgText(effective_config, ['anatomy', 'select_tag'], '')
    target_mri_subject_id = raw_subject_basename.split('_')[0] + anatomy_select_tag
    stub_delay_sec = cfgGet(effective_config, ['test_stub_delay_sec'], 0)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    ${stubFailureCommand(effective_config, 'apply_ica')}
    sleep ${stub_delay_sec}
    mkdir -p "${preproc_dir}/${raw_subject_dir_basename}"
    printf 'stub clean %s\n' "${orig_raw_path}" > "${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif"
    ln -s "${preproc_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_clean_raw.fif" clean-raw-output.guard
    """
}

process epochs {
    tag "${subject_key[0]}:${subject_key[1]}"

    input:
    tuple val(subject_key), val(dataset_name), val(dataset_dir), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(t1_dir), val(effective_config), val(orig_raw_path), val(analysis_raw_path), val(target_mri_subject_id), val(clean_hash), val(bad_channels), val(bad_segments), val(events_file), val(events_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val("${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif"), val(epoch_analysis_raw_path), val(clean_hash), val(events_hash), emit: epoch_subjects
    path "epoch-output.guard", emit: epoch_cache_guard
    path "epoch-analysis-output.guard", emit: epoch_analysis_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/epochs.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/epochs_preproc.py", "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(analysis_raw_path).getBaseName()
    raw_subject_dir_basename = file(analysis_raw_path).getParent().getName()
    filtered_raw_subject_basename = file(orig_raw_path).getBaseName().replace("_meg_preproc-raw_clean_raw", "").replace("_meg_preproc-raw", "")
    epoch_config = moduleConfigJson(effective_config, 'epochs')
    epoch_output_dir = processOutputDir('epochs')
    epoch_analysis_raw_path = modulePreprocConfigured(effective_config, 'epochs') ?
        "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_analysis-raw.fif" :
        analysis_raw_path.toString()
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_EVENTS_INPUT=${events_hash}
    mkdir -p "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --preproc_raw_file "${analysis_raw_path}" \\
        --fname_bad_channels "${bad_channels}" \\
        --fname_bad_segments "${bad_segments}" \\
        --events_file "${events_file}" \\
        --output_epoch_file "${raw_subject_basename}-epo.fif" \\
        --output_analysis_raw_file "${epoch_analysis_raw_path}" \\
        --output_dir "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}" \\
        --config '${epoch_config}'
    ln -s "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif" epoch-output.guard
    if [ "${epoch_analysis_raw_path}" != "${analysis_raw_path}" ]; then
        ln -s "${epoch_analysis_raw_path}" epoch-analysis-output.guard
    else
        ln -s "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif" epoch-analysis-output.guard
    fi
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/epochs.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/epochs_preproc.py", "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(analysis_raw_path).getBaseName()
    raw_subject_dir_basename = file(analysis_raw_path).getParent().getName()
    epoch_output_dir = processOutputDir('epochs')
    epoch_analysis_raw_path = modulePreprocConfigured(effective_config, 'epochs') ?
        "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}_analysis-raw.fif" :
        analysis_raw_path.toString()
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_EVENTS_INPUT=${events_hash}
    ${stubFailureCommand(effective_config, 'epochs')}
    mkdir -p "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}"
    printf 'stub epochs %s\n' "${analysis_raw_path}" > "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif"
    if [ "${epoch_analysis_raw_path}" != "${analysis_raw_path}" ]; then
        printf 'stub analysis raw %s\n' "${analysis_raw_path}" > "${epoch_analysis_raw_path}"
    fi
    ln -s "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif" epoch-output.guard
    if [ "${epoch_analysis_raw_path}" != "${analysis_raw_path}" ]; then
        ln -s "${epoch_analysis_raw_path}" epoch-analysis-output.guard
    else
        ln -s "${preproc_dir}/${epoch_output_dir}/${raw_subject_dir_basename}/${raw_subject_basename}-epo.fif" epoch-analysis-output.guard
    fi
    """
}

process compute_covariance {
    tag "${subject_key[0]}:${subject_key[1]}"

    input:
    tuple val(subject_key), val(dataset_name), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(source_data_file), val(source_data_mode), val(source_data_hash), val(noise_key), val(noise_data_file), val(noise_input_hash), val(events_file), val(events_hash), val(clean_hash), val(needs_lcmv)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(effective_config), val("${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif"), val("${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/lcmv-data-cov.fif"), val("${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/resolved-rank.json"), val(needs_lcmv), val(clean_hash), val(source_data_hash), val(noise_key), val(covariance_input_hash), emit: cov_subjects
    path "noise-covariance-output.guard", emit: noise_covariance_cache_guard
    path "data-covariance-output.guard", emit: data_covariance_cache_guard
    path "resolved-rank-output.guard", emit: resolved_rank_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/compute_covariance.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/epochs.py", "${megflowCodeDir(effective_config)}/epochs_preproc.py", "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_dir_basename = subject_key[1]
    covariance_config = new LinkedHashMap(moduleConfig(effective_config, 'covariance'))
    covariance_config.rank_policy = cfgGet(effective_config, ['rank_policy'], 'auto')
    source_config = new LinkedHashMap(moduleConfig(effective_config, 'source'))
    source_config.rank_policy = cfgGet(effective_config, ['rank_policy'], 'auto')
    covar_output_dir = processOutputDir('covariance')
    covar_visualize = cfgBool(covariance_config, ['visualize'], true)
    covar_type = cfgText(covariance_config, ['type'], 'epochs')
    if (covar_type == 'raw' && modulePreprocConfigured(effective_config, 'epochs')) {
        covariance_config.analysis_preproc = cfgGet(effective_config, ['epochs', 'preproc'], [])
    }
    covar_config = configJson(covariance_config)
    src_config = configJson(source_config)
    covariance_input_hash = "noise:${noise_input_hash}|events:${events_hash}|source:${source_data_hash}"
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_EVENTS_INPUT=${events_hash}
    # MEGFLOW_COVARIANCE_INPUT=${covariance_input_hash}
    set -euo pipefail
    mkdir -p "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --noise_data_file "${noise_data_file}" \\
        --noise_recording_id "${noise_key[0]}:${noise_key[1]}" \\
        --source_data_file "${source_data_file}" \\
        --source_data_mode ${source_data_mode} \\
        --events_file "${events_file}" \\
        --output_dir "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}" \\
        --visualize ${covar_visualize} \\
        --covar_type ${covar_type} \\
        --config '${covar_config}' \\
        --source_config '${src_config}'
    if [[ ! -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif" ]]; then
        echo "Noise covariance output is missing or empty" >&2
        exit 2
    fi
    if [[ ! -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/resolved-rank.json" ]]; then
        echo "Resolved-rank output is missing or empty" >&2
        exit 2
    fi
    if [[ "${needs_lcmv}" == "true" && ! -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/lcmv-data-cov.fif" ]]; then
        echo "LCMV data covariance output is missing or empty" >&2
        exit 2
    fi
    ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif" noise-covariance-output.guard
    ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/resolved-rank.json" resolved-rank-output.guard
    if [[ "${needs_lcmv}" == "true" ]]; then
        ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/lcmv-data-cov.fif" data-covariance-output.guard
    else
        ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif" data-covariance-output.guard
    fi
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/compute_covariance.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/epochs.py", "${megflowCodeDir(effective_config)}/epochs_preproc.py", "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_dir_basename = subject_key[1]
    covar_output_dir = processOutputDir('covariance')
    covariance_input_hash = "noise:${noise_input_hash}|events:${events_hash}|source:${source_data_hash}"
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_EVENTS_INPUT=${events_hash}
    # MEGFLOW_COVARIANCE_INPUT=${covariance_input_hash}
    set -euo pipefail
    ${stubFailureCommand(effective_config, 'compute_covariance')}
    mkdir -p "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}"
    printf 'stub noise covariance %s\n' "${noise_data_file}" > "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif"
    printf '{"rank":{"meg":1},"channels":[],"source_data_mode":"%s"}\n' "${source_data_mode}" > "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/resolved-rank.json"
    if [[ "${needs_lcmv}" == "true" ]]; then
        printf 'stub LCMV data covariance %s\n' "${source_data_file}" > "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/lcmv-data-cov.fif"
    else
        rm -f "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/lcmv-data-cov.fif"
    fi
    ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif" noise-covariance-output.guard
    ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/resolved-rank.json" resolved-rank-output.guard
    if [[ "${needs_lcmv}" == "true" ]]; then
        ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/lcmv-data-cov.fif" data-covariance-output.guard
    else
        ln -s "${preproc_dir}/${covar_output_dir}/${raw_subject_dir_basename}/bl-cov.fif" data-covariance-output.guard
    fi
    """
}

process coregistration {
    tag "${subject_key[0]}:${subject_key[1]}"
    time '1h'

    input:
    tuple val(subject_key), val(dataset_name), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(target_mri_subject_id), val(clean_raw_path), val(clean_hash), val(anatomy_hash)

    output:
    tuple val(subject_key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(target_mri_subject_id), val("${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}/coreg-trans.fif"), val(clean_hash), val(anatomy_hash), emit: trans_subjects
    path "coregistration-output.guard", emit: coregistration_cache_guard

    script:
    script_name = "${megflowCodeDir(effective_config)}/coregistration.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_basename = file(clean_raw_path).getBaseName()
    raw_subject_dir_basename = file(clean_raw_path).getParent().getName()
    mri_subject_id = target_mri_subject_id ?: raw_subject_basename.split('_')[0]
    core_config = moduleConfig(effective_config, 'coreg')
    trans_output_dir = processOutputDir('coreg')
    coreg_visualize = cfgBool(core_config, ['visualize'], cfgBool(effective_config, ['visualize'], true))
    coreg_config = configJson(core_config)
    supplied_trans_file = cfgText(core_config, ['supplied_trans_file'], '')
    supplied_trans_arg = supplied_trans_file ? " --supplied_trans_file \"${supplied_trans_file}\"" : ""
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_ANATOMY_INPUT=${anatomy_hash}
    python ${script_name} \\
        --raw_file "${clean_raw_path}" \\
        --subjects_dir "${fs_subjects_dir}/${mri_subject_id}" \\
        --visualize ${coreg_visualize} \\
        --output_dir "${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}" \\
        --config '${coreg_config}'${supplied_trans_arg}
    ln -s "${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}/coreg-trans.fif" coregistration-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/coregistration.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_dir_basename = file(clean_raw_path).getParent().getName()
    trans_output_dir = processOutputDir('coreg')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_ANATOMY_INPUT=${anatomy_hash}
    ${stubFailureCommand(effective_config, 'coregistration')}
    mkdir -p "${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}"
    printf 'stub trans %s\n' "${clean_raw_path}" > "${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}/coreg-trans.fif"
    ln -s "${preproc_dir}/${trans_output_dir}/${raw_subject_dir_basename}/coreg-trans.fif" coregistration-output.guard
    """
}

process forward_solution {
    tag "${key[0]}:${key[1]}"

    input:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(target_mri_subject_id), val(trans_path), val(coreg_clean_hash), val(trans_hash), val(anatomy_hash), val(epoch_output_dir), val(epoch_preproc_dir), val(epoch_fs_subjects_dir), val(epoch_effective_config), val(epoch_path), val(analysis_raw_path), val(epoch_clean_hash), val(epoch_events_hash), val(epoch_hash), val(analysis_hash)

    output:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val("${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}/${fwd_epoch_label}_${fwd_spacing}-fwd.fif"), val(epoch_path), val(analysis_raw_path), val(trans_hash), val(epoch_clean_hash), val(anatomy_hash), val(epoch_events_hash), val(epoch_hash), val(analysis_hash), emit: fwd_subjects
    path "forward-solution-output.guard", emit: forward_solution_cache_guard

    script:
    dataset_name = key[0]
    raw_subject_dir_basename = key[1]
    script_name = "${megflowCodeDir(effective_config)}/forward_solution.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    mri_subject_id = target_mri_subject_id ?: raw_subject_dir_basename.split('_')[0]
    mri_subject_dir = "${fs_subjects_dir}/${mri_subject_id}"
    forward_config = moduleConfig(effective_config, 'forward')
    fwd_output_dir = processOutputDir('forward')
    fwd_epoch_label = cfgText(forward_config, ['epoch_label'], '')
    fwd_spacing = cfgText(forward_config, ['spacing'], 'ico4')
    fwd_config = configJson(forward_config)
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_ANATOMY_INPUT=${anatomy_hash}
    # MEGFLOW_EPOCH_INPUT=${epoch_events_hash}|${epoch_hash}|${analysis_hash}
    mkdir -p "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --epoch_file "${epoch_path}" \\
        --epoch_label "${fwd_epoch_label}" \\
        --output_dir "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}" \\
        --trans_file "${trans_path}" \\
        --mri_subject_dir "${mri_subject_dir}" \\
        --config '${fwd_config}'
    ln -s "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}/${fwd_epoch_label}_${fwd_spacing}-fwd.fif" forward-solution-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/forward_solution.py"
    code_hash = filesSha256([script_name, "${megflowCodeDir(effective_config)}/utils.py"])
    raw_subject_dir_basename = key[1]
    forward_config = moduleConfig(effective_config, 'forward')
    fwd_output_dir = processOutputDir('forward')
    fwd_epoch_label = cfgText(forward_config, ['epoch_label'], '')
    fwd_spacing = cfgText(forward_config, ['spacing'], 'ico4')
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_ANATOMY_INPUT=${anatomy_hash}
    # MEGFLOW_EPOCH_INPUT=${epoch_events_hash}|${epoch_hash}|${analysis_hash}
    ${stubFailureCommand(effective_config, 'forward_solution')}
    mkdir -p "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}"
    printf 'stub forward %s %s\n' "${epoch_path}" "${trans_path}" > "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}/${fwd_epoch_label}_${fwd_spacing}-fwd.fif"
    ln -s "${preproc_dir}/${fwd_output_dir}/${raw_subject_dir_basename}/${fwd_epoch_label}_${fwd_spacing}-fwd.fif" forward-solution-output.guard
    """
}

process source_imaging {
    tag "${key[0]}:${key[1]}"

    input:
    tuple val(key), val(output_dir), val(preproc_dir), val(fs_subjects_dir), val(effective_config), val(fwd_file), val(epoch_path), val(analysis_raw_path), val(fwd_hash), val(epoch_clean_hash), val(anatomy_hash), val(epoch_events_hash), val(epoch_hash), val(analysis_hash), val(bl_cov_file), val(lcmv_data_cov_file), val(resolved_rank_file), val(needs_lcmv), val(covariance_hash), val(data_covariance_hash), val(resolved_rank_hash), val(covariance_source_hash), val(noise_key), val(covariance_input_hash)

    output:
    tuple val(key), val(output_dir), val(preproc_dir), val("${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}"), emit: source_subjects
    path "source-imaging-output.guard", emit: source_imaging_cache_guard

    script:
    dataset_name = key[0]
    raw_subject_dir_basename = key[1]
    source_config = new LinkedHashMap(moduleConfig(effective_config, 'source'))
    source_config.rank_policy = cfgGet(effective_config, ['rank_policy'], 'auto')
    src_type = cfgText(source_config, ['type'], 'epochs').toLowerCase()
    src_output_dir = processOutputDir('source')
    source_visualize = cfgBool(source_config, ['visualize'], cfgBool(effective_config, ['visualize'], true))
    src_config = configJson(source_config)
    raw_subject_path = src_type == 'epochs' ? epoch_path : analysis_raw_path
    if (!(src_type in ['epochs', 'raw'])) {
        error "Invalid source.type: ${src_type}. Please specify 'epochs' or 'raw'."
    }
    script_name = "${megflowCodeDir(effective_config)}/source_localization.py"
    code_hash = filesSha256([
        script_name,
        "${megflowCodeDir(effective_config)}/source_visualization.py",
        "${megflowCodeDir(effective_config)}/utils.py"
    ])
    data_covariance_arg = needs_lcmv ? "--data_covariance_file \"${lcmv_data_cov_file}\"" : ''
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    # MEGFLOW_FORWARD_INPUT=${fwd_hash}
    # MEGFLOW_ANATOMY_INPUT=${anatomy_hash}
    # MEGFLOW_EPOCH_INPUT=${epoch_events_hash}|${epoch_hash}|${analysis_hash}
    # MEGFLOW_COVARIANCE_INPUT=${covariance_hash}|${data_covariance_hash}|${resolved_rank_hash}|${covariance_input_hash}
    set -euo pipefail
    if [[ ! -s "${raw_subject_path}" || ! -s "${fwd_file}" || ! -s "${bl_cov_file}" || ! -s "${resolved_rank_file}" ]]; then
        echo "Source input, forward solution, noise covariance, or resolved rank is missing or empty" >&2
        exit 2
    fi
    if [[ "${needs_lcmv}" == "true" && ! -s "${lcmv_data_cov_file}" ]]; then
        echo "LCMV data covariance is missing or empty" >&2
        exit 2
    fi
    mkdir -p "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}"
    python ${script_name} \\
        --data_mode ${src_type} \\
        --data_file "${raw_subject_path}"  \\
        --fs_subjects_dir "${fs_subjects_dir}" \\
        --output_dir "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}" \\
        --forward_file "${fwd_file}" \\
        --visualize ${source_visualize} \\
        --noise_covariance_file "${bl_cov_file}" \\
        --resolved_rank_file "${resolved_rank_file}" \\
        --config '${src_config}' ${data_covariance_arg}
    ln -s "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}" source-imaging-output.guard
    """

    stub:
    script_name = "${megflowCodeDir(effective_config)}/source_localization.py"
    code_hash = filesSha256([
        script_name,
        "${megflowCodeDir(effective_config)}/source_visualization.py",
        "${megflowCodeDir(effective_config)}/utils.py"
    ])
    raw_subject_dir_basename = key[1]
    source_config = moduleConfig(effective_config, 'source')
    preproc_config = normalizeModuleConfig('preproc', asMap(effective_config.preproc))
    epochs_config = moduleConfig(effective_config, 'epochs')
    covariance_config = moduleConfig(effective_config, 'covariance')
    src_output_dir = processOutputDir('source')
    src_type = cfgText(source_config, ['type'], 'epochs').toLowerCase()
    source_input_file = src_type == 'epochs' ? epoch_path : analysis_raw_path
    routing_json = JsonOutput.prettyPrint(JsonOutput.toJson([
        key: key,
        recording_profile: cfgText(effective_config, ['_recording', 'profile_name'], ''),
        config_marker: cfgText(effective_config, ['preproc', 'test_marker'], ''),
        preproc_config: preproc_config,
        epochs_config: epochs_config,
        covariance_config: covariance_config,
        source_config: source_config,
        epoch_label: cfgText(source_config, ['epoch_label'], ''),
        covariance_type: cfgText(effective_config, ['covariance', 'type'], 'epochs'),
        epochs_output_dir: processOutputDir('epochs'),
        covariance_output_dir: processOutputDir('covariance'),
        forward_output_dir: processOutputDir('forward'),
        source_output_dir: src_output_dir,
        source_type: src_type,
        source_input_file: source_input_file.toString(),
        epoch_file: epoch_path.toString(),
        analysis_raw_file: analysis_raw_path.toString(),
        clean_file: analysis_raw_path.toString(),
        forward_file: fwd_file.toString(),
        covariance_file: bl_cov_file.toString(),
        data_covariance_file: needs_lcmv ? lcmv_data_cov_file.toString() : '',
        resolved_rank_file: resolved_rank_file.toString(),
        lcmv_required: needs_lcmv,
        noise_recording_key: noise_key,
        forward_hash: fwd_hash,
        anatomy_hash: anatomy_hash,
        events_hash: epoch_events_hash,
        epoch_hash: epoch_hash,
        analysis_hash: analysis_hash,
        covariance_hash: covariance_hash,
        data_covariance_hash: data_covariance_hash,
        resolved_rank_hash: resolved_rank_hash,
        covariance_source_hash: covariance_source_hash,
        covariance_input_hash: covariance_input_hash
    ]))
    """
    # MEGFLOW_CODE_SHA256=${code_hash}
    set -euo pipefail
    ${stubFailureCommand(effective_config, 'source_imaging')}
    test -f "${epoch_path}"
    test -f "${source_input_file}"
    test -f "${fwd_file}"
    test -f "${bl_cov_file}"
    test -f "${resolved_rank_file}"
    if [[ "${needs_lcmv}" == "true" ]]; then
        test -f "${lcmv_data_cov_file}"
    fi
    mkdir -p "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}"
    cat > "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}/routing.json" <<'EOF_ROUTING'
${routing_json}
EOF_ROUTING
    ln -s "${preproc_dir}/${src_output_dir}/${raw_subject_dir_basename}" source-imaging-output.guard
    """
}

process generate_static_html_report {
    tag "${dataset_name}"
    cache false

    input:
    tuple val(dataset_name), val(output_dir), val(preproc_dir), val(report_script), val(manifest_json), val(bad_channel_threshold), val(bad_segment_threshold), val(coreg_mean_threshold), val(coreg_max_threshold), val(epoch_reject_rate_threshold), val(megqc_alarm_score), val(static_artifact_overview_duration), val(alert_missing_ecg_components), val(alert_missing_eog_components), val(static_task_log_mode)
    val completion_tokens

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

    stub:
    """
    touch "static_html_report_${dataset_name}.done"
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

    if (withAnatomy && !(primary in ['meg_artifacts', 'meg_ica', 'meg_epochs'])) {
        throw new IllegalArgumentException(
            "with_anatomy is only supported with meg_artifacts, meg_ica, or meg_epochs"
        )
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

Map attachRecordingSteps(Map datasetConfig, Map recordingConfig, def rawPathValue) {
    def effective = attachParsedSteps(recordingConfig)
    def datasetSteps = asMap(datasetConfig._steps)
    def recordingSteps = asMap(effective._steps)
    def overrideKeys = asList(cfgGet(effective, ['_recording', 'override_keys'], []))

    if (overrideKeys.contains('steps')) {
        if (recordingSteps.runMeg && !datasetSteps.runMeg) {
            throw new IllegalArgumentException(
                "Recording-level steps cannot enable MEG import for dataset-level steps=${datasetSteps.primary}: ${rawPathValue}"
            )
        }
        if (recordingSteps.megStage > datasetSteps.megStage) {
            throw new IllegalArgumentException(
                "Recording-level steps cannot exceed the dataset MEG stage (${datasetSteps.primary}): ${rawPathValue}"
            )
        }
        if (recordingSteps.runAnatomy && !datasetSteps.runAnatomy) {
            throw new IllegalArgumentException(
                "Recording-level steps cannot create a dataset anatomy plan: ${rawPathValue}"
            )
        }
        if (recordingSteps.primary == 'anatomy') {
            throw new IllegalArgumentException(
                "Recording-level steps cannot select anatomy-only processing: ${rawPathValue}"
            )
        }
    }

    // Anatomy is planned per dataset before MEG records are imported. Preserve
    // that dependency even when a recording lowers only its MEG milestone.
    recordingSteps.runAnatomy = datasetSteps.runAnatomy
    effective._steps = recordingSteps
    return effective
}

Map buildMegProcessPlan(List datasetProfiles) {
    def stepCandidates = []
    def datasetSteps = []
    datasetProfiles.each { profile ->
        def effective = attachParsedSteps(asMap(asMap(profile).effective_config))
        def resolvedDatasetSteps = asMap(effective._steps)
        datasetSteps << resolvedDatasetSteps
        stepCandidates << resolvedDatasetSteps
        asMap(effective.recordings).each { profileName, profileValue ->
            def recordingProfile = asMap(profileValue)
            if (recordingProfile.containsKey('steps')) {
                stepCandidates << parseMegPipelineSteps(
                    cfgText(recordingProfile, ['steps'], 'meg_all')
                )
            }
        }
    }

    def megSteps = stepCandidates.findAll { steps -> cfgBool(steps, ['runMeg'], false) }
    return [
        enabled: !megSteps.isEmpty(),
        runIca: megSteps.any { steps ->
            cfgGet(steps, ['megStage'], -1).toString().toInteger() >= 1 &&
                !cfgBool(steps, ['skipIca'], false)
        },
        runEpochs: megSteps.any { steps ->
            cfgGet(steps, ['megStage'], -1).toString().toInteger() >= 2
        },
        runSource: megSteps.any { steps ->
            cfgGet(steps, ['megStage'], -1).toString().toInteger() >= 3
        },
        runReports: datasetSteps.any { steps ->
            cfgBool(steps, ['runMeg'], false) || cfgText(steps, ['primary'], '') == 'report'
        },
        maxStage: megSteps
            ? megSteps.collect { steps -> cfgGet(steps, ['megStage'], -1).toString().toInteger() }.max()
            : -1
    ]
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
    def megPlan = buildMegProcessPlan(datasetProfiles)
    def megflowParams = asMap(params.megflow)
    def corpusMode = datasetProfiles.size() > 1 || cfgText(megflowParams, ['corpus_root'], '')
    def expectedReportScope = corpusMode ? 'corpus' : 'dataset'
    def reportScopeConfigured = megflowParams.containsKey('report_scope')
    def reportScope = cfgText(megflowParams, ['report_scope'], expectedReportScope).trim().toLowerCase()
    if (!(reportScope in ['dataset', 'corpus'])) {
        throw new IllegalArgumentException("params.megflow.report_scope must be dataset or corpus")
    }
    if (reportScopeConfigured && reportScope != expectedReportScope) {
        throw new IllegalArgumentException(
            "params.megflow.report_scope=${reportScope} does not match the resolved ${expectedReportScope} run. " +
            "Use report_scope=corpus for corpus_root or multi-dataset runs."
        )
    }
    def implementationFingerprints = [:]
    def icaLabelFingerprints = [:]
    log.info "MEGFlow profile datasets: ${datasetProfiles.collect { it.dataset_name }.join(', ')}"
    log.info "Corpus mode: ${corpusMode}"
    log.info "Anatomy process plan: enabled=${anatomyPlan.enabled}, methods=${anatomyPlan.methods ?: 'none'}, datasets=${anatomyPlan.datasetNames ?: 'none'}"
    log.info "MEG process plan: enabled=${megPlan.enabled}, max_stage=${megPlan.maxStage}, ica=${megPlan.runIca}, epochs=${megPlan.runEpochs}, source=${megPlan.runSource}, reports=${megPlan.runReports}"

    native_dataset_ch = Channel
        .fromList(datasetProfiles)
        .map { profile ->
            def effective = attachParsedSteps(asMap(profile.effective_config))
            effective.code_dir = cfgText(effective, ['code_dir'], megflowCodeDir(effective))
            synchronized (implementationFingerprints) {
                if (!implementationFingerprints.containsKey(effective.code_dir)) {
                    implementationFingerprints[effective.code_dir] = megflowImplementationFingerprint(effective.code_dir)
                }
                effective._implementation_fingerprint = implementationFingerprints[effective.code_dir]
            }
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
                    report_cache_policy: 'disabled; static reports are regenerated on every run.'
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
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
            def fileSuffix = cfgText(effective_config, ['file_suffix'], '.fif')
            def rawInventoryHash = selectedInputInventoryFingerprint(
                dataset_dir, [fileSuffix], [output_dir, preproc_dir]
            )
            tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, rawInventoryHash)
        }

    native_raw_subject_ch = Channel.empty()
    if (megPlan.enabled || anatomyPlan.runPseudomri) {
        native_imported = import_meg_dataset(dataset_meg_import_ch)
        native_raw_subject_ch = native_imported.imported_meg_data
            .flatMap { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, imported_file ->
                def rawPaths = imported_file.readLines()
                    .collect { it.trim() }
                    .findAll { it }
                def duplicateOutputIds = rawPaths.groupBy { rawPath -> recordingOutputId(rawPath) }
                    .findAll { outputId, paths -> paths.size() > 1 }
                if (duplicateOutputIds) {
                    throw new IllegalArgumentException(
                        "Imported recordings in dataset ${dataset_name} share output identifiers: ${duplicateOutputIds}"
                    )
                }
                rawPaths.collect { raw_subject_path ->
                        def recordingConfig = attachRecordingSteps(
                            asMap(effective_config),
                            effectiveRecordingConfig(asMap(effective_config), raw_subject_path),
                            raw_subject_path
                        )
                        recordingConfig.code_dir = cfgText(recordingConfig, ['code_dir'], megflowCodeDir(recordingConfig))
                        recordingConfig._recording.raw_input_fingerprint = fileStatFingerprint(raw_subject_path)
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, recordingConfig, raw_subject_path)
                    }
            }
    }

    native_raw_cov_reference_keys_v = native_raw_subject_ch
        .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, raw_subject_path ->
            def steps = asMap(effective_config._steps)
            if (!(steps.runMeg && steps.megStage >= 3 &&
                cfgText(effective_config, ['covariance', 'type'], 'epochs').equalsIgnoreCase('raw'))) {
                return [recording_key: null]
            }
            def rawCovTask = cfgText(effective_config, ['covariance', 'raw_covariance_task_id'], 'emptr')
            def pairedRawPath = replaceRecordingTaskEntity(raw_subject_path, rawCovTask)
            return [recording_key: recordingKey(dataset_name, pairedRawPath)]
        }
        .collect()
        .map { rows ->
            [recording_keys: rows.collect { row -> row.recording_key }.findAll { it != null }.toSet()]
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
                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subject_name ->
                    def t1InputHash = fileStatFingerprint(anat_file)
                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subject_name, t1InputHash)
                }
        }

        native_bids_t1_inputs_ch = Channel.empty()
        if (anatomyPlan.runMriImport) {
            bids_mri_dataset_ch = anatomy_dataset_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() != 'pseudomri' &&
                        cfgBool(effective_config, ['anatomy', 'is_bids'], cfgBool(effective_config, ['is_bids'], true))
                }
                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config ->
                    def t1InventoryHash = selectedInputInventoryFingerprint(
                        t1_dir, ['.nii', '.nii.gz'], [output_dir, preproc_dir, fs_subjects_dir], 't1'
                    )
                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, t1InventoryHash)
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
                            def anatFiles = matcher[0][2]
                                .split(',')
                                .collect { it.trim().replaceAll(/'/, '') }
                                .findAll { it }
                            def anatomyMethod = cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase()
                            if (anatomyMethod == 'freesurfer' && anatFiles.size() > 1) {
                                throw new IllegalArgumentException(
                                    "Multiple T1 files matched ${dataset_name}:${subjectName}: ${anatFiles}. " +
                                    "Narrow mri_import so FreeSurfer receives exactly one T1 input."
                                )
                            }
                            anatFiles.collect { anat_file ->
                                def t1InputHash = fileStatFingerprint(anat_file)
                                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subjectName, t1InputHash)
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
                        def dicomHash = fileStatFingerprint(dicom_dir)
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, dicom_dir.toString(), dicomHash)
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
                        def t1InputHash = fileStatFingerprint(anat_file)
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file.toString(), subjectName, t1InputHash)
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
                        def t1InputHash = fileStatFingerprint(anat_file)
                        tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file.toString(), subjectName, t1InputHash)
                    }
                }
        }

        native_fs_subjects_ch = Channel.empty()
        if (anatomyPlan.runFreesurfer) {
            native_freesurfer_t1_inputs_ch = pseudo_t1_inputs_ch
                .mix(native_bids_t1_inputs_ch.filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subjectName, t1InputHash ->
                    cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'freesurfer'
                })
                .mix(native_dicom_t1_inputs_ch)
                .mix(native_nifti_t1_inputs_ch)
            native_fs = run_freesurfer(native_freesurfer_t1_inputs_ch)
            native_fs_subjects_ch = native_fs.fs_subjects
                .map { dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config ->
                    def reconstructionHash = anatomyReconstructionFingerprint(fs_subjects_dir, subject_name)
                    tuple(dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config, reconstructionHash)
                }
        }

        native_head_subjects_ch = Channel.empty()
        if (anatomyPlan.runDeepPrep) {
            native_deepprep_subjects_ch = native_bids_t1_inputs_ch
                .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subject_name, t1_input_hash ->
                    cfgText(effective_config, ['anatomy', 'method'], 'freesurfer').toLowerCase() == 'deepprep'
                }
                .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, anat_file, subject_name, t1_input_hash ->
                    tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, subject_name, t1_input_hash)
                }
                .unique { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, subject_name, t1InputHash ->
                    "${dataset_name}:${subject_name}"
                }
            native_deep = run_deepprep(native_deepprep_subjects_ch)
            native_head = run_mkheadsurf(native_deep.fs_subjects)
            native_head_subjects_ch = native_head.fs_subjects
                .map { dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config, reconstruction_input_hash ->
                    def reconstructionHash = anatomyReconstructionFingerprint(fs_subjects_dir, subject_name)
                    tuple(dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config, reconstructionHash)
                }
        }

        native_bem_inputs_ch = native_fs_subjects_ch.mix(native_head_subjects_ch)
        native_bem = generate_bem(native_bem_inputs_ch)
        native_anatomy_subject_ch = native_bem.bem_subjects
    }

    native_preproc_with_hash_ch = Channel.empty()
    native_artifacts_with_hash = Channel.empty()
    if (megPlan.enabled) {
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
        native_preproc_with_hash_ch = native_preproc.preproc_subjects
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path ->
                def preprocHash = fileStatFingerprint(preproc_raw_path)
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, preprocHash)
            }
        native_artifacts = detect_artifacts(native_preproc_with_hash_ch)
        native_artifacts_with_hash = native_artifacts.artifacts
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, preproc_hash, bad_channels, bad_segments ->
                def artifactHash = "${preproc_hash}|${filesSha256([bad_channels, bad_segments])}"
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifactHash)
            }
    }

    native_clean_subject_ch = Channel.empty()
    if (megPlan.runIca) {
        native_ica_inputs_ch = native_artifacts_with_hash
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifactHash ->
                asMap(effective_config._steps).megStage >= 1 && !asMap(effective_config._steps).skipIca
            }
        native_ica = run_ica(native_ica_inputs_ch)
        native_ica_with_hash_ch = native_ica.ica_subjects
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, ica_source, ica_file_path ->
                def icaHash = fileStatFingerprint(ica_file_path)
                def icaLabelCodeHash
                synchronized (icaLabelFingerprints) {
                    if (!icaLabelFingerprints.containsKey(effective_config.code_dir)) {
                        icaLabelFingerprints[effective_config.code_dir] =
                            icaLabelImplementationFingerprint(effective_config.code_dir)
                    }
                    icaLabelCodeHash = icaLabelFingerprints[effective_config.code_dir]
                }
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, ica_source, ica_file_path, icaHash, icaLabelCodeHash)
            }
        native_labels = run_ic_label(native_ica_with_hash_ch)
        native_labelled_with_hash = native_labels.labelled_subjects
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, ica_hash, marked_components ->
                def markedHash = fileSha256(marked_components)
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, ica_hash, marked_components, markedHash)
            }
        native_clean = apply_ica(native_labelled_with_hash)
        native_clean_subject_ch = native_clean.clean_subjects
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, logical_clean_hash ->
                def cleanFileHash = fileStatFingerprint(clean_raw_path)
                def cleanHash = "${logical_clean_hash}|file:${cleanFileHash}"
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, cleanHash)
            }
    }

    native_non_reference_clean_subject_ch = Channel.empty()
    native_epoch_with_hash_ch = Channel.empty()
    if (megPlan.runEpochs) {
        native_non_reference_artifacts_with_hash_ch = native_artifacts_with_hash
            .combine(native_raw_cov_reference_keys_v)
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, reference_keys ->
                !isRawCovarianceReferenceKey(reference_keys, dataset_name, orig_raw_path)
            }
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash, reference_keys ->
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash)
            }
        native_non_reference_clean_subject_ch = native_clean_subject_ch
            .combine(native_raw_cov_reference_keys_v)
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash, reference_keys ->
                !isRawCovarianceReferenceKey(reference_keys, dataset_name, orig_raw_path)
            }
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash, reference_keys ->
                tuple(dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash)
            }

        native_epoch_from_preproc_ch = native_non_reference_artifacts_with_hash_ch
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash ->
                asMap(effective_config._steps).megStage >= 2 && asMap(effective_config._steps).skipIca
            }
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, bad_channels, bad_segments, artifact_hash ->
                def subjectKey = recordingKey(dataset_name, orig_raw_path)
                tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, preproc_raw_path, '', artifact_hash, bad_channels, bad_segments)
            }
        native_epoch_from_clean_ch = native_non_reference_clean_subject_ch
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                asMap(effective_config._steps).megStage >= 2
            }
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                def subjectKey = recordingKey(dataset_name, orig_raw_path)
                tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash, '', '')
            }
        native_epoch_input_ch = native_epoch_from_preproc_ch
            .mix(native_epoch_from_clean_ch)
            .map { subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, analysis_raw_path, target_mri_subject_id, clean_hash, bad_channels, bad_segments ->
                def eventsFile = orig_raw_path.toString().replaceAll(/_meg\..*/, '_events.tsv')
                def eventsHash = fileSha256(eventsFile)
                tuple(subjectKey, dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, analysis_raw_path, target_mri_subject_id, clean_hash, bad_channels, bad_segments, eventsFile, eventsHash)
            }
        native_epochs = epochs(native_epoch_input_ch)
        native_epoch_subject_ch = native_epochs.epoch_subjects
        native_epoch_with_hash_ch = native_epoch_subject_ch
            .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash ->
                def epochHash = fileStatFingerprint(epoch_path)
                def analysisHash = fileStatFingerprint(analysis_raw_path)
                tuple(subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epochHash, analysisHash)
            }
    }

    native_source_subject_ch = Channel.empty()
    if (megPlan.runSource) {
        native_source_clean_ch = native_non_reference_clean_subject_ch
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                asMap(effective_config._steps).megStage >= 3
            }
        native_cov_epochs_inputs_ch = native_epoch_with_hash_ch
            .filter { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epoch_hash, analysis_hash ->
                asMap(effective_config._steps).megStage >= 3 &&
                    cfgText(effective_config, ['covariance', 'type'], 'epochs').equalsIgnoreCase('epochs')
            }
            .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epoch_hash, analysis_hash ->
                def datasetName = subjectKey[0]
                def sourceMode = cfgText(effective_config, ['source', 'type'], 'epochs').toLowerCase()
                if (!(sourceMode in ['epochs', 'raw'])) {
                    throw new IllegalArgumentException("Invalid source.type for ${subjectKey}: ${sourceMode}")
                }
                def sourceDataFile = sourceMode == 'epochs' ? epoch_path : analysis_raw_path
                def sourceDataHash = sourceMode == 'epochs' ? epoch_hash : analysis_hash
                def origRawPath = cfgText(effective_config, ['_recording', 'meta', 'path'], '')
                def eventsFile = origRawPath.replaceAll(/_meg\..*/, '_events.tsv')
                tuple(subjectKey, datasetName, output_dir, preproc_dir, fs_subjects_dir, effective_config, sourceDataFile, sourceMode, sourceDataHash, subjectKey, analysis_raw_path, analysis_hash, eventsFile, events_hash, clean_hash, sourceUsesLcmv(effective_config))
            }
        native_cov_raw_requests_ch = native_epoch_with_hash_ch
            .filter { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epoch_hash, analysis_hash ->
                asMap(effective_config._steps).megStage >= 3 &&
                    cfgText(effective_config, ['covariance', 'type'], 'epochs').equalsIgnoreCase('raw')
            }
            .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epoch_hash, analysis_hash ->
                def datasetName = subjectKey[0]
                def sourceMode = cfgText(effective_config, ['source', 'type'], 'epochs').toLowerCase()
                if (!(sourceMode in ['epochs', 'raw'])) {
                    throw new IllegalArgumentException("Invalid source.type for ${subjectKey}: ${sourceMode}")
                }
                def sourceDataFile = sourceMode == 'epochs' ? epoch_path : analysis_raw_path
                def sourceDataHash = sourceMode == 'epochs' ? epoch_hash : analysis_hash
                def origRawPath = cfgText(effective_config, ['_recording', 'meta', 'path'], '')
                def rawCovTask = cfgText(effective_config, ['covariance', 'raw_covariance_task_id'], 'emptr')
                def pairedRawPath = replaceRecordingTaskEntity(origRawPath, rawCovTask)
                def pairingKey = recordingKey(datasetName, pairedRawPath)
                tuple(pairingKey, subjectKey, datasetName, output_dir, preproc_dir, fs_subjects_dir, effective_config, sourceDataFile, sourceMode, sourceDataHash, clean_hash)
            }
        native_cov_raw_candidates_ch = native_clean_subject_ch
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                tuple(recordingKey(dataset_name, orig_raw_path), clean_raw_path, clean_hash, cfgText(effective_config, ['_recording', 'profile_name'], ''))
            }
        native_cov_raw_inputs_ch = native_cov_raw_requests_ch
            .combine(native_cov_raw_candidates_ch, by: 0)
            .map { pairingKey, subjectKey, datasetName, output_dir, preproc_dir, fs_subjects_dir, effective_config, sourceDataFile, sourceMode, sourceDataHash, cleanHash, noiseDataFile, noiseInputHash, noiseProfile ->
                log.info "Raw covariance pairing: target=${subjectKey}, noise=${pairingKey}, noise_profile=${noiseProfile ?: '<default>'}"
                tuple(subjectKey, datasetName, output_dir, preproc_dir, fs_subjects_dir, effective_config, sourceDataFile, sourceMode, sourceDataHash, pairingKey, noiseDataFile, noiseInputHash, '', 'not-used', cleanHash, sourceUsesLcmv(effective_config))
            }
        native_cov_inputs_ch = native_cov_epochs_inputs_ch.mix(native_cov_raw_inputs_ch)
        native_cov = compute_covariance(native_cov_inputs_ch)

        native_coreg_existing_inputs_ch = native_source_clean_ch
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                !asMap(effective_config._steps).runAnatomy
            }
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                def subjectKey = recordingKey(dataset_name, orig_raw_path)
                def anatomyHash = anatomyModelFingerprint(fs_subjects_dir, target_mri_subject_id)
                tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash, anatomyHash)
            }
        native_coreg_anatomy_subject_ch = native_source_clean_ch
            .filter { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                asMap(effective_config._steps).runAnatomy
            }
            .map { dataset_name, dataset_dir, output_dir, preproc_dir, fs_subjects_dir, t1_dir, effective_config, orig_raw_path, clean_raw_path, target_mri_subject_id, clean_hash ->
                def subjectKey = recordingKey(dataset_name, orig_raw_path)
                tuple([dataset_name, target_mri_subject_id], subjectKey, dataset_name, output_dir, preproc_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash)
            }
        native_anatomy_by_subject_ch = native_anatomy_subject_ch.map { dataset_name, output_dir, preproc_dir, subject_name, fs_subjects_dir, subject_dir, effective_config ->
            def anatomyHash = anatomyModelFingerprint(fs_subjects_dir, subject_name)
            tuple([dataset_name, subject_name], fs_subjects_dir, anatomyHash)
        }.unique { mriKey, fsSubjectsDir, anatomyHash -> mriKey }
        native_coreg_from_anatomy_inputs_ch = native_coreg_anatomy_subject_ch
            .combine(native_anatomy_by_subject_ch, by: 0)
            .map { mri_key, subjectKey, dataset_name, output_dir, preproc_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash, fs_subjects_dir, anatomyHash ->
                tuple(subjectKey, dataset_name, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, clean_raw_path, clean_hash, anatomyHash)
            }
        native_coreg_inputs = native_coreg_existing_inputs_ch.mix(native_coreg_from_anatomy_inputs_ch)
        native_trans = coregistration(native_coreg_inputs)
        native_trans_with_hash = native_trans.trans_subjects
            .map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, trans_path, clean_hash, anatomy_hash ->
                def transHash = fileSha256(trans_path)
                tuple(subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, trans_path, clean_hash, transHash, anatomy_hash)
            }
        native_source_epoch_subject_ch = native_epoch_with_hash_ch
            .filter { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epoch_hash, analysis_hash ->
                asMap(effective_config._steps).megStage >= 3
            }
        native_fwd_inputs = native_trans_with_hash
            .join(
                native_source_epoch_subject_ch,
                by: 0,
                failOnDuplicate: true,
                failOnMismatch: megflowErrorMode().equalsIgnoreCase('strict')
            )
            .map { key, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, trans_path, coreg_clean_hash, trans_hash, anatomy_hash, epoch_output_dir, epoch_preproc_dir, epoch_fs_subjects_dir, epoch_effective_config, epoch_path, analysis_raw_path, epoch_clean_hash, epoch_events_hash, epoch_hash, analysis_hash ->
                if (output_dir != epoch_output_dir || preproc_dir != epoch_preproc_dir || fs_subjects_dir != epoch_fs_subjects_dir) {
                    throw new IllegalStateException("Forward routing path mismatch for ${key}")
                }
                if (configJson(effective_config) != configJson(epoch_effective_config)) {
                    throw new IllegalStateException("Forward routing config mismatch for ${key}")
                }
                if (coreg_clean_hash != epoch_clean_hash) {
                    throw new IllegalStateException("Forward routing clean lineage mismatch for ${key}")
                }
                tuple(key, output_dir, preproc_dir, fs_subjects_dir, effective_config, target_mri_subject_id, trans_path, coreg_clean_hash, trans_hash, anatomy_hash, epoch_output_dir, epoch_preproc_dir, epoch_fs_subjects_dir, epoch_effective_config, epoch_path, analysis_raw_path, epoch_clean_hash, epoch_events_hash, epoch_hash, analysis_hash)
            }
        native_fwds = forward_solution(native_fwd_inputs)
        native_fwds_with_hash_ch = native_fwds.fwd_subjects
            .map { key, output_dir, preproc_dir, fs_subjects_dir, effective_config, fwd_file, epoch_path, analysis_raw_path, trans_hash, epoch_clean_hash, anatomy_hash, epoch_events_hash, epoch_hash, analysis_hash ->
                def fwdHash = fileStatFingerprint(fwd_file)
                tuple(key, output_dir, preproc_dir, fs_subjects_dir, effective_config, fwd_file, epoch_path, analysis_raw_path, trans_hash, epoch_clean_hash, anatomy_hash, epoch_events_hash, epoch_hash, analysis_hash, fwdHash)
            }
        native_cov_with_hash_ch = native_cov.cov_subjects
            .map { key, output_dir, preproc_dir, effective_config, bl_cov_file, lcmv_data_cov_file, resolved_rank_file, needs_lcmv, clean_hash, source_data_hash, noise_key, covariance_input_hash ->
                def covarianceHash = fileStatFingerprint(bl_cov_file)
                def dataCovarianceHash = needs_lcmv ? fileStatFingerprint(lcmv_data_cov_file) : 'not-required'
                def resolvedRankHash = fileSha256(resolved_rank_file)
                tuple(key, output_dir, preproc_dir, effective_config, bl_cov_file, lcmv_data_cov_file, resolved_rank_file, needs_lcmv, clean_hash, source_data_hash, noise_key, covariance_input_hash, covarianceHash, dataCovarianceHash, resolvedRankHash)
            }
        native_source_inputs = native_fwds_with_hash_ch
            .join(
                native_cov_with_hash_ch,
                by: 0,
                failOnDuplicate: true,
                failOnMismatch: megflowErrorMode().equalsIgnoreCase('strict')
            )
            .map { key, output_dir, preproc_dir, fs_subjects_dir, effective_config, fwd_file, epoch_path, analysis_raw_path, trans_hash, epoch_clean_hash, anatomy_hash, epoch_events_hash, epoch_hash, analysis_hash, fwd_hash, cov_output_dir, cov_preproc_dir, cov_effective_config, bl_cov_file, lcmv_data_cov_file, resolved_rank_file, needs_lcmv, cov_clean_hash, covariance_source_hash, noise_key, covariance_input_hash, covariance_hash, data_covariance_hash, resolved_rank_hash ->
                if (output_dir != cov_output_dir || preproc_dir != cov_preproc_dir) {
                    throw new IllegalStateException("Source routing path mismatch for ${key}")
                }
                if (configJson(effective_config) != configJson(cov_effective_config)) {
                    throw new IllegalStateException("Source routing config mismatch for ${key}")
                }
                if (epoch_clean_hash != cov_clean_hash) {
                    throw new IllegalStateException("Source routing clean lineage mismatch for ${key}")
                }
                def sourceType = cfgText(effective_config, ['source', 'type'], 'epochs').toLowerCase()
                def expectedSourceHash = sourceType == 'epochs' ? epoch_hash : analysis_hash
                if (covariance_source_hash != expectedSourceHash) {
                    throw new IllegalStateException("Covariance/source input lineage mismatch for ${key}")
                }
                def expectedLcmv = sourceUsesLcmv(effective_config)
                if (needs_lcmv != expectedLcmv) {
                    throw new IllegalStateException("LCMV covariance requirement mismatch for ${key}")
                }
                if (expectedLcmv && !lcmv_data_cov_file) {
                    throw new IllegalStateException("LCMV data covariance was not routed for ${key}")
                }
                if (!resolved_rank_file) {
                    throw new IllegalStateException("Resolved target rank was not routed for ${key}")
                }
                tuple(key, output_dir, preproc_dir, fs_subjects_dir, effective_config, fwd_file, epoch_path, analysis_raw_path, fwd_hash, epoch_clean_hash, anatomy_hash, epoch_events_hash, epoch_hash, analysis_hash, bl_cov_file, lcmv_data_cov_file, resolved_rank_file, needs_lcmv, covariance_hash, data_covariance_hash, resolved_rank_hash, covariance_source_hash, noise_key, covariance_input_hash)
            }
        native_source = source_imaging(native_source_inputs)
        native_source_subject_ch = native_source.source_subjects
    }

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
    epoch_token_ch = native_epoch_with_hash_ch.map { subjectKey, output_dir, preproc_dir, fs_subjects_dir, effective_config, epoch_path, analysis_raw_path, clean_hash, events_hash, epoch_hash, analysis_hash ->
        tuple(subjectKey[0], 'epochs')
    }
    source_token_ch = native_source_subject_ch.map { key, output_dir, preproc_dir, source_dir ->
        tuple(key[0], 'source')
    }
    // collect() yields a value channel that keeps the session alive while all
    // optional or ignored branches close, before report tasks are submitted.
    report_completion_tokens = dataset_token_ch
        .mix(report_only_token_ch)
        .mix(anatomy_token_ch)
        .mix(artifacts_token_ch)
        .mix(clean_token_ch)
        .mix(epoch_token_ch)
        .mix(source_token_ch)
        .collect()

    if (megPlan.runReports) {
        native_reports = generate_static_html_report(
            native_dataset_report_row_ch,
            report_completion_tokens
        )
        if (corpusMode) {
            generate_corpus_static_html_report(native_reports.dataset_reports.map { dataset_name, output_dir, preproc_dir, marker -> marker }.collect())
        }
    }
}
