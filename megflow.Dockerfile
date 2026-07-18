FROM pbfslab/deepprep:25.1.0
# v3:MEGFlow Environments + DeepPrep Environments
LABEL liaopan='liaopanblog@gmail.com'

ENV TZ=Asia/Shanghai \
    RUN_DIR=/program

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        python3 python3-pip python3-dev \
        libatlas-base-dev \
        libavcodec-dev \
        libavformat-dev \
        libglib2.0-dev \
        libhdf5-dev \
        libjpeg-dev \
        libpng-dev \
        libssl-dev \
        zlib1g-dev \
        libcurl4-openssl-dev \
        libfreetype6-dev \
        libglib2.0-dev \
        libtiff-dev \
        libvorbis-dev \
        libgmp-dev \
        libopenblas-base \
        libx11-dev \
        libxext-dev \
        libxrender-dev \
        libpng-dev \
        libjpeg-dev \
        libgl1-mesa-dev \
        libgl1-mesa-glx \
        libgl1-mesa-dri \
        libglx-mesa0 \
        libxcb1 \
        curl \
        gosu \
        wget \
        ca-certificates \
        software-properties-common \
        vim \
        supervisor \
        xvfb \
        libx11-xcb1 \
        libglu1-mesa \
        libx11-6 \
        libxext6 \
        libxkbcommon-x11-0 \
        libxcb-xinerama0 \
        libxinerama1 \
        libxcursor1  \
        libxrender1 \
        libxi6 \
        openjdk-17-jdk && \
    rm -rf /var/lib/apt/lists/* && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    mkdir -p /input /output /smri ${RUN_DIR}/nextflow ${RUN_DIR}/megflow/


COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir -r requirements.txt && \
	apt-get clean && \
	rm -rf /root/.cache && apt-get autoclean && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/* /var/lib/apt/* /var/cache/* /var/log/* /tmp/* ~/*


COPY nextflow/megflow.nf ${RUN_DIR}/nextflow/megflow.nf
COPY nextflow/nextflow_for_docker.config ${RUN_DIR}/nextflow/nextflow.config
COPY nextflow/run_for_docker.sh ${RUN_DIR}/nextflow/run.sh
COPY megflow ${RUN_DIR}/megflow/
COPY softwares/mkheadsurf /opt/freesurfer/bin/mkheadsurf
COPY softwares/tksurfer /opt/freesurfer/bin/tksurfer
COPY softwares/tktools /opt/freesurfer/lib/tktools
COPY softwares/fsfast /opt/freesurfer/fsfast
COPY softwares/mri_mc /opt/freesurfer/bin/mri_mc
COPY softwares/mri_seghead /opt/freesurfer/bin/mri_seghead
COPY softwares/dcm2niix /usr/local/bin/dcm2niix
COPY megflow/anat_get_t1w_file_in_bids.py /opt/DeepPrep/deepprep/nextflow/bin/anat_get_t1w_file_in_bids.py
COPY nextflow/deepprep.nf /opt/DeepPrep/deepprep/nextflow/deepprep.nf
COPY nextflow/deepprep.common.config /opt/DeepPrep/deepprep/nextflow/deepprep.common.config

RUN chmod +x ${RUN_DIR}/nextflow/run.sh && \
    cd ${RUN_DIR}/megflow/tools/osl-ephys && pip install --no-deps -e .
RUN \
    echo "export DISPLAY=:99" >> ~/.bashrc && \
    echo "export QT_QPA_PLATFORM=xcb" >> ~/.bashrc && \
    echo "export MESA_GLSL_VERSION_OVERRIDE=150" >> ~/.bashrc && \
    echo "export MESA_GL_VERSION_OVERRIDE=3.2" >> ~/.bashrc && \
    echo "export NUMBA_CACHE_DIR=/tmp/NUMBA_CACHE_DIR" >> ~/.bashrc && \
    echo "export MPLCONFIGDIR=/tmp/MPLCONFIGDIR/" >> ~/.bashrc && \
    chmod -R 777 ${RUN_DIR}/nextflow ${RUN_DIR}/megflow/ && \
    chmod -R 777 ${RUN_DIR} && \
    chmod -R 777 /usr/local/lib/python3.10 && \
    chmod -R 755 /opt/DeepPrep/deepprep/nextflow/bin/anat_get_t1w_file_in_bids.py && \
    chown deepprep:deepprep /opt/DeepPrep/deepprep/nextflow/bin/anat_get_t1w_file_in_bids.py  && \
    chmod -R 755 /opt/DeepPrep/deepprep/nextflow/deepprep.nf && \
    chmod -R 755 /opt/DeepPrep/deepprep/nextflow/deepprep.common.config && \
    chown deepprep:deepprep /opt/DeepPrep/deepprep/nextflow/deepprep.common.config  && \
    chown deepprep:deepprep /opt/DeepPrep/deepprep/nextflow/deepprep.nf  && \
    chmod 755 /opt/freesurfer/bin/mkheadsurf /opt/freesurfer/bin/tksurfer /opt/freesurfer/bin/mri_mc /opt/freesurfer/bin/mri_seghead /usr/local/bin/dcm2niix && \
    chmod -R 755 /opt/freesurfer/fsfast /opt/freesurfer/lib/tktools && \
    mkdir -m 777 /tmp/NUMBA_CACHE_DIR /tmp/MPLCONFIGDIR && \
    # mne-bids bug fixed. \
    sed -i 's|search_str = op.join(search_str, f"{basename}\*")|search_str = op.join(search_str, f"{basename}[!0-9]*")|g' /opt/conda/envs/deepprep/lib/python3.10/site-packages/mne_bids/path.py && \
    mkdir -p /var/log/supervisor && chmod 777 /var/log/supervisor && \
    # deepprep optimized. \
    sed -i '/anat_summary/s/^/\/\//' /opt/DeepPrep/deepprep/nextflow/deepprep.nf
#    sed -i 's|\${script_py} --bids-dir \${bids_dir} --subject-ids \${subjects}|\${script_py} --bids-dir \${bids_dir} --subject-ids \${subjects} --config "\${params.mri_import_config}"|g' /opt/DeepPrep/deepprep/nextflow/deepprep.nf && \
#    sed -i '/bids_dir/i \    mri_import_config = """"""' /opt/DeepPrep/deepprep/nextflow/deepprep.common.config && \
#    sed -i 's/layout = bids\.BIDSLayout(args\.bids_dir, derivatives=False)/layout = bids.BIDSLayout(args.bids_dir, derivatives=False, ignore=[r'\''(?!sub-).*'\''])/' /opt/DeepPrep/deepprep/nextflow/bin/anat_get_t1w_file_in_bids.py


#    sed -i '$ a\
## Check the exit status of Nextflow\n\
#if [ \$? -ne 0 ]; then\n\
#    echo "Nextflow script execution failed! Please check the error message."\n\
#    # Exit the script with status 1 (indicating an error)\n\
#    exit 1\n\
#else\n\
#    echo "Nextflow script executed successfully!"\n\
#    # Exit the script with status 0 (indicating success)\n\
#    exit 0\n\
#fi' /opt/DeepPrep/deepprep/deepprep.sh && \
#    sed -i '2i\
#set -e' /opt/DeepPrep/deepprep/deepprep.sh && \
#    echo "umask 0001" >> /etc/profile
#    sed -i '$a exit $?' /opt/DeepPrep/deepprep/deepprep.sh

RUN mkdir -p /tmp/megflow_home /tmp/megflow_cache /tmp/megflow_nextflow /tmp/NUMBA_CACHE_DIR /tmp/MPLCONFIGDIR /output && \
    if [ -d /home/deepprep/.nextflow ]; then cp -a /home/deepprep/.nextflow/. /tmp/megflow_nextflow/; fi && \
    chmod -R 777 /tmp/megflow_home /tmp/megflow_cache /tmp/megflow_nextflow /tmp/NUMBA_CACHE_DIR /tmp/MPLCONFIGDIR /output

WORKDIR /output
ENV HOME=/tmp/megflow_home \
    XDG_CACHE_HOME=/tmp/megflow_cache \
    JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    NXF_JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    NXF_HOME=/tmp/megflow_nextflow \
    NUMBA_CACHE_DIR=/tmp/NUMBA_CACHE_DIR \
    MPLCONFIGDIR=/tmp/MPLCONFIGDIR \
    NXF_OFFLINE='true' \
    NXF_SYNTAX_PARSER='v1'
EXPOSE 8501
ENTRYPOINT ["/program/nextflow/run.sh"]

