# Docker

Cheat sheet. Full explanation in [docs/01-environment.md](../docs/01-environment.md).

## Build

From the **repository root** — the Dockerfile copies `requirements.txt` and `pipeline/`, so the build
context must be the root:

```bash
docker build -t fs7-fsl -f docker/Dockerfile .
```

~30–60 minutes, ~25 GB image.

## Verify

```bash
docker run --rm fs7-fsl bash -lc '
  recon-all --version &&
  flirt -version &&
  python3 -c "import nibabel, numpy, pandas, tqdm; print(\"python deps ok\")" &&
  ls /workspace/suvr/FreesurferLUTR.txt &&
  ls $FREESURFER_HOME/MCRv97 >/dev/null && echo "MCR ok"'
```

## Run

```bash
python3 ../pipeline/2_freesurfer/processing_container.py /path/to/ADRC --license ~/license.txt
docker exec -it <container_name> bash
```

Or by hand:

```bash
docker run -d -it --name fs7 \
  -e CPU_CORES=8 \
  -v /path/to/ADRC:/workspace/data \
  -v ~/license.txt:/usr/local/freesurfer/.license:ro \
  fs7-fsl
```

## Contents

| | |
|---|---|
| Base | `ubuntu:jammy` (22.04) |
| FSL | `/usr/local/fsl` — `flirt` |
| FreeSurfer | 7.4.1 at `/usr/local/freesurfer` |
| MCR | R2019b — **required** by `segmentHA_T1.sh` |
| Python | `nibabel`, `numpy`, `pandas`, `tqdm` |
| Scripts | `/workspace/` (FS7), `/workspace/suvr/`, `/workspace/qc/` |
| Data mount | `/workspace/data` |

FreeSurfer and FSL are sourced by `/etc/bash.bashrc`, so use `bash -lc` (or an interactive shell) —
`docker run --rm fs7-fsl recon-all --version` will not find the binary.

## License

Never baked into the image. Bind-mount it read-only at `/usr/local/freesurfer/.license`.
`license.txt` is in `.gitignore`; [`license.txt.example`](license.txt.example) shows the format and
where to register.

## Build failing on certificates

Institutional TLS interception breaks the two download steps. Add `--skip_ssl_verify` to the
`fslinstaller.py` call and `--no-check-certificate` to the FreeSurfer `wget` — both lines carry
comments marking the spot. Only on a network you trust.
