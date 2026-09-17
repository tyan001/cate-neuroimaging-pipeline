FROM ubuntu:jammy

# FreeSurfer 7.4.1 + FSL + MATLAB Compiler Runtime, for the CATE neuroimaging pipeline.
#
# Build from the REPOSITORY ROOT, not from this directory:
#     docker build -t fs7-fsl -f docker/Dockerfile .
#
# No FreeSurfer license is baked in. Mount it at runtime:
#     -v /path/to/license.txt:/usr/local/freesurfer/.license:ro
# which is what pipeline/2_freesurfer/processing_container.py does for you.

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_GB.UTF-8 \
    FSLDIR=/usr/local/fsl \
    FSLOUTPUTTYPE=NIFTI_GZ \
    FREESURFER_HOME=/usr/local/freesurfer \
    SUBJECTS_DIR=/usr/local/freesurfer/subjects \
    OS=Linux \
    FSF_OUTPUT_FORMAT=nii.gz

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bc \
        libgomp1 \
        perl \
        tcsh \
        python3 \
        python3-pip \
        libgl1-mesa-glx \
        libxext6 \
        libsm6 \
        libxrender1 \
        libxmu6 \
        file \
        dc \
        procps \
        ca-certificates \
        bzip2 \
        wget \
        tar \
        curl \
        unzip && \
    rm -rf /var/lib/apt/lists/*

# ---------- FSL ----------
# If your network intercepts TLS and this step fails with a certificate error,
# append --skip_ssl_verify to the fslinstaller.py call below.
RUN wget -q https://fsl.fmrib.ox.ac.uk/fsldownloads/fslconda/releases/fslinstaller.py && \
    python3 ./fslinstaller.py -d ${FSLDIR}/ && \
    rm fslinstaller.py && \
    rm -rf ${FSLDIR}/pkgs/* \
           ${FSLDIR}/conda-meta/* \
           ${FSLDIR}/lib/libcuda* \
           ${FSLDIR}/lib/libcudnn* \
           ${FSLDIR}/lib/libnvinfer* \
           ${FSLDIR}/src \
           ${FSLDIR}/doc

# ---------- FreeSurfer ----------
# Same note as above: add --no-check-certificate to wget if TLS verification fails.
RUN wget -q \
        https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer-linux-ubuntu22_amd64-7.4.1.tar.gz \
        -O /tmp/fs.tar.gz && \
    tar --no-same-owner -xzf /tmp/fs.tar.gz -C /tmp && \
    mv /tmp/freesurfer ${FREESURFER_HOME} && \
    rm /tmp/fs.tar.gz

# ---------- FreeSurfer MCR ----------
# Required by segmentHA_T1.sh (hippocampal subfields / amygdala nuclei).
RUN ${FREESURFER_HOME}/bin/fs_install_mcr R2019b && \
    rm -rf /tmp/* /var/tmp/*

# ---------- Python dependencies ----------
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# ---------- Pipeline scripts ----------
# Directory copies (not globs) so data files such as FreesurferLUTR.txt,
# which suvr.py loads from its own directory, actually land in the image.
RUN mkdir -p /workspace
COPY pipeline/2_freesurfer/ /workspace/freesurfer/
COPY pipeline/3_suvr/       /workspace/suvr/
COPY pipeline/4_qc/         /workspace/qc/

# ---------- Environment ----------
ENV FSLTCLSH=$FSLDIR/bin/fsltclsh \
    FSLWISH=$FSLDIR/bin/fslwish \
    PATH=$FREESURFER_HOME/bin:$PATH \
    LD_LIBRARY_PATH=$FREESURFER_HOME/MCRv97/v97/runtime/glnxa64:$FREESURFER_HOME/MCRv97/v97/bin/glnxa64:$FREESURFER_HOME/MCRv97/sys/os/glnxa64

RUN echo 'source $FREESURFER_HOME/SetUpFreeSurfer.sh' >> /etc/bash.bashrc && \
    echo 'source $FSLDIR/etc/fslconf/fsl.sh' >> /etc/bash.bashrc

WORKDIR /workspace

CMD ["/bin/bash"]
