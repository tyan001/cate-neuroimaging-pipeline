# 1. Building the FreeSurfer 7 environment

Everything downstream needs FreeSurfer 7.4.1, FSL, the MATLAB Compiler Runtime, and four Python
packages. The supported way to get all of that is the Docker image in [`docker/Dockerfile`](../docker/Dockerfile).

Running natively is possible and is covered at the end.

---

## Prerequisites

**Docker.** Install from the [official docs](https://docs.docker.com/get-started/get-docker/).
Verify with `docker run --rm hello-world`.

**A FreeSurfer license.** Free, but personal and required — `recon-all` refuses to start without it.
Register at <https://surfer.nmr.mgh.harvard.edu/registration.html>. You receive a `license.txt` with
four lines: your email, a numeric ID, and two key lines.

> Save `license.txt` **outside this repository.** It is a credential tied to you.
> `.gitignore` blocks it, and the image never bakes it in — it is bind-mounted at runtime.
> See [`docker/license.txt.example`](../docker/license.txt.example).

**Disk.** The image is roughly 25 GB built (FreeSurfer alone is ~10 GB, the MCR another ~2 GB).
Subject data needs far more — budget ~300 MB per `recon-all` output and ~150 MB per PET–MRI pair.
See [04-data-organization.md](04-data-organization.md#storage-planning).

---

## Build the image

Build **from the repository root**, not from `docker/` — the Dockerfile copies `requirements.txt` and
`pipeline/`, so the build context must be the root:

```bash
cd cate-neuroimaging-pipeline
docker build -t fs7-fsl -f docker/Dockerfile .
```

Expect **30–60 minutes**, mostly downloading FreeSurfer (~5 GB) and the MCR. Confirm it exists:

```bash
docker images | grep fs7-fsl
```

### What goes into the image

| Layer | Contents | Why |
|---|---|---|
| `ubuntu:jammy` | Ubuntu 22.04 base | Matches the `ubuntu22_amd64` FreeSurfer build |
| apt packages | `tcsh`, `perl`, `bc`, `dc`, `libgomp1`, X11 libs | `recon-all` is a csh/perl program and needs these |
| FSL | installed via `fslinstaller.py` into `/usr/local/fsl` | Provides `flirt` for PET→MRI registration |
| FreeSurfer 7.4.1 | `/usr/local/freesurfer` | `recon-all`, `mri_convert`, `*stats2table` |
| MCR R2019b | `$FREESURFER_HOME/MCRv97` | **Required by `segmentHA_T1.sh`** — hippocampal subfield segmentation is a compiled MATLAB program and silently fails without it |
| Python packages | `nibabel`, `numpy`, `pandas`, `tqdm` | The SUVR and aggregation stages |
| Pipeline scripts | `/workspace/`, `/workspace/suvr/`, `/workspace/qc/` | Copied as directories, so `FreesurferLUTR.txt` comes along |

The CUDA/cuDNN/TensorRT libraries and FSL's source and docs are deleted after install to keep the
image from ballooning; nothing in this pipeline uses the GPU.

### If the build fails on TLS certificates

Some institutional networks intercept TLS, which makes `wget` and the FSL installer fail with
certificate errors. Two lines in the Dockerfile carry comments marking the fix: add
`--skip_ssl_verify` to the `fslinstaller.py` call and `--no-check-certificate` to the FreeSurfer
`wget`. Only do this on a network you trust — it disables verification of what you are downloading.

---

## Verify the image

```bash
docker run --rm fs7-fsl bash -lc '
  recon-all --version &&
  flirt -version &&
  python3 -c "import nibabel, numpy, pandas, tqdm; print(\"python deps ok\")" &&
  ls /workspace/suvr/FreesurferLUTR.txt &&
  ls $FREESURFER_HOME/MCRv97 >/dev/null && echo "MCR ok"'
```

All five must pass. In particular:

- **`FreesurferLUTR.txt`** is the ROI label→name table that `suvr.py` loads from its own directory.
  Without it every SUVR run dies with `FileNotFoundError`.
- **`MCRv97`** missing means `segmentHA_T1.sh` will fail at the hippocampus step.

---

## Launch a processing container

[`pipeline/2_freesurfer/processing_container.py`](../pipeline/2_freesurfer/processing_container.py)
wraps `docker run` and sizes the container to the workload:

```bash
python3 pipeline/2_freesurfer/processing_container.py /path/to/batch/ADRC \
    --license /path/to/license.txt
```

| Argument | Default | Meaning |
|---|---|---|
| `directory` | — | Dataset directory to mount at `/workspace/data` |
| `--name` | `fs-fsl` | Container name prefix; becomes `<name>_<dirname>` |
| `--image` | `fs7-fsl` | Image to run |
| `--license` | `./license.txt` | Path to your FreeSurfer license |

It counts `anat/*.nii` files under the directory and allocates
`min(n_scans + 1, host_cpus - 1)` CPUs, passing the count in as `CPU_CORES`. That variable is what
`mri_processing.py` uses to size its process pool — one `recon-all` per core. It also sets
`CONTAINER_NAME`, which names the log file.

There are exactly two bind mounts:

```
<your data dir>  ->  /workspace/data
<license.txt>    ->  /usr/local/freesurfer/.license   (read-only)
```

The container starts detached. Get a shell in it:

```bash
docker ps                              # find the generated name
docker exec -it <container_name> bash
```

FreeSurfer and FSL are sourced automatically by `/etc/bash.bashrc`, so `recon-all` and `flirt` are on
`PATH` immediately. Continue with [02-mri-processing.md](02-mri-processing.md).

---

## Running without Docker

The scripts do not require the container — they only require the tools on `PATH` and the environment
variables set. If you already have FreeSurfer and FSL installed:

```bash
export FREESURFER_HOME=/usr/local/freesurfer     # your install location
source $FREESURFER_HOME/SetUpFreeSurfer.sh
export FSLDIR=/usr/local/fsl
source $FSLDIR/etc/fslconf/fsl.sh

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

`FREESURFER_HOME` and `FSLDIR` are read by `prepare_suvr_folder.py` and `registration.py`
respectively, falling back to `/usr/local/...` when unset. Set `CPU_CORES` yourself, since nothing
else will:

```bash
export CPU_CORES=8
```

Your license goes at `$FREESURFER_HOME/.license` (or `license.txt` in the same directory).

**Version note:** the pipeline writes and reads a directory literally named `freesurfer741`. It works
with other FreeSurfer 7.x versions, but the folder name stays `freesurfer741` unless you edit
`mri_processing.py` and `prepare_suvr_folder.py`. See
[05-troubleshooting.md](05-troubleshooting.md#known-limitations).
