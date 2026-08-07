import argparse
import subprocess
from pathlib import Path
import os

def count_nii_paths(root_dir):
    root_path = Path(root_dir)
    nii_files = []
    
    for path in root_path.rglob('anat/*.nii'):
        nii_files.append(str(path))
    
    print(f"Number of NIfTI files: {len(nii_files)}")
    
    return len(nii_files)

def run_docker_container(cpu_count, directory, container_name, image, license_path):
    directory = Path(directory).resolve()
    

    # Configure container with our combined fs-fsl image
    docker_command = [
        'docker', 'run', '-d', '-it',
        '--cpus', str(cpu_count),
        '--name', f'{container_name}_{directory.name}',
        '-e', f'CPU_CORES={cpu_count}',
        '-e', f'CONTAINER_NAME={directory.name}',
        '-v', f'{directory}:/workspace/data',
        '-v', f'{license_path}:/usr/local/freesurfer/.license:ro',
        f'{image}',
        "sh"
    ]
    print(f"Running Docker command: {' '.join(docker_command)}")

    subprocess.run(docker_command, check=True)

def check_license(custom_license_path=None):
    if custom_license_path:
        license_path = Path(custom_license_path)
    else:
        # Get the directory where the script is located
        script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        license_path = script_dir / 'license.txt'

    print(f'Checking license file: {license_path}')

    # Check if the license file exists
    if not license_path.exists():
        raise FileNotFoundError(f"License file not found at {license_path}")
    # Check if the license file is blank
    if license_path.stat().st_size == 0:
        raise ValueError(f"License file is empty: {license_path}")
    
    return license_path

if __name__ == "__main__":
    # Example:
    #   python3 pipeline/2_freesurfer/processing_container.py /data/batch12/ADRC \
    #       --license /path/to/license.txt
    parser = argparse.ArgumentParser(description="Run FreeSurfer-FSL Docker container with CPU count based on NIfTI files.")
    parser.add_argument('directory', type=str, help="Directory path containing NIfTI files")
    parser.add_argument('--name', type=str, default='fs-fsl', help="Name of the Docker container (default: fs-fsl_<directory_name>)")
    parser.add_argument('--image', type=str, default='fs7-fsl', help="Docker image to use (default: fs-fsl:latest)")
    parser.add_argument('--license', type=str, help="Custom path to the license file")
    args = parser.parse_args()

    license_path = check_license(args.license)
    
    directory = args.directory
    cpu_count = count_nii_paths(directory) + 1
    max_cpu_cores = os.cpu_count() or 1
    print(f"Max CPU cores available: {max_cpu_cores}")
    cpu_count = min(cpu_count, max_cpu_cores-1)
    print(f"Using {cpu_count} CPU cores for Docker container")

    run_docker_container(cpu_count, directory, args.name, args.image, license_path)