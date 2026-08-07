import logging
import argparse
import numpy as np
import pandas as pd
import nibabel as nib # type: ignore
from pathlib import Path
from typing import Dict, Tuple, List, Optional
from datetime import datetime


def setup_logging(output_dir: Path, subject_id: str) -> None:
    """Setup logging to write to both console and file in logs folder"""
    # Create logs folder if it doesn't exist
    logs_path = output_dir / 'logs'
    logs_path.mkdir(parents=True, exist_ok=True)

    # Create log filename with timestamp and subject ID
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = logs_path / f'pet_suvr_processing_{subject_id}_{timestamp}.log'

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()  # This will still print to console
        ]
    )
    
    logging.info(f"Log file created at: {log_file}")


def parse_nifti_filename(filename: str) -> Tuple[str, str, str, Optional[str]]:
    """
    Parse the NIfTI filename format: subjID-scandate_modality[_info].nii
    Returns tuple of (subject_id, scan_date, modality, additional_info)
    """
    # Remove .nii extension
    base_name = filename.replace('.nii', '')
    
    try:
        # Split by hyphen to get subjID and the rest
        parts = base_name.split('-', 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid filename format: {filename}. Expected format: subjID-scandate_modality[_info].nii")
        
        subject_id = parts[0]
        
        # Now split the second part by underscore
        remaining_parts = parts[1].split('_')
        
        # First part should be the scan date
        scan_date = remaining_parts[0]
        
        # Second part should be the modality (e.g., PET)
        modality = remaining_parts[1]
        
        # Any additional parts are considered extra info
        additional_info = None
        if len(remaining_parts) > 2:
            additional_info = '_'.join(remaining_parts[2:])
            
        return subject_id, scan_date, modality, additional_info
        
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid filename format: {filename}. Expected format: subjID-scandate_modality[_info].nii")


def determine_compound(scandate: str, manual_compound: Optional[str] = None) -> str:
    """
    Determine the compound based on scan date or manual override.
    
    Args:
        scandate (str): The scan date in format YYYYMMDD
        manual_compound (Optional[str]): Manual override for compound type
        
    Returns:
        str: Either "Neuraceq" or "Amyvid"
    """
    if manual_compound is not None:
        if manual_compound.lower() in ["neuraceq", "amyvid"]:
            return manual_compound.capitalize()
        else:
            logging.warning(f"Invalid manual compound '{manual_compound}', using date-based determination instead")
    
    scan_datetime = datetime.strptime(scandate, "%Y%m%d")
    threshold_date = datetime(2016, 9, 27)
    
    if scan_datetime >= threshold_date:
        return "Neuraceq"
    else:
        return "Amyvid"


def calculate_centiloid(compound: str, global_value: float) -> float:
    """
    Calculate the centiloid value based on compound and global value.
    
    Args:
        compound (str): Either "Neuraceq" or "Amyvid"
        global_value (float): The global value from the CSV
        
    Returns:
        float: The calculated centiloid value
    """
    if compound == "Amyvid":
        return 183.07 * global_value - 177.26
    elif compound == "Neuraceq":
        return 153.4 * global_value - 154.9
    else:
        logging.warning(f"Compound '{compound}' not recognized, setting centiloid to 0")
        return 0


def find_scan_dates_with_suvr(base_path: Path) -> List[Path]:
    """Find all scan date folders that contain a SUVR folder"""
    scan_folders = []
    for item in base_path.iterdir():
        if item.is_dir() and len(item.name) == 8 and item.name.isdigit():
            # Check for SUVR folder
            suvr_folders = list(item.rglob("suvr"))
            if any(folder.is_dir() for folder in suvr_folders):
                scan_folders.append(item)
    return sorted(scan_folders)


def find_pet_folders(scan_folder: Path) -> List[Path]:
    """Find all PET processing folders within the SUVR folder"""
    # Find the SUVR folder
    suvr_folders = list(scan_folder.rglob("suvr"))
    if not suvr_folders:
        return []
    
    suvr_folder = suvr_folders[0]
    
    # Get all folders that end with _PET or _PET_info, excluding 'logs'
    pet_folders = [
        f for f in suvr_folder.iterdir() 
        if f.is_dir() and "-" in f.name and "_PET" in f.name and f.name.lower() != 'logs'
    ]
    
    return sorted(pet_folders)


def find_mri_folders(pet_folder: Path) -> List[Path]:
    """Find all MRI processing folders within a PET folder"""
    # Get all folders that contain pet_ and mri_ in their names, excluding 'logs'
    mri_folders = [
        f for f in pet_folder.iterdir() 
        if f.is_dir() and "_pet_" in f.name.lower() and "_mri_" in f.name.lower() 
        and f.name.lower() != 'logs'
    ]
    
    return sorted(mri_folders)


def load_data(mri_folder: Path, pet_file: Path) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame, Dict[str, pd.DataFrame]]:
    """Load all necessary input data files"""
    try:
        # Load NIfTI files
        pet_data = nib.load(pet_file).get_fdata()
        
        # Look for aparc+aseg file with same prefix as MRI file
        mri_files = list(mri_folder.glob("*_aparc+aseg.nii"))
        if not mri_files:
            raise ValueError("No aparc+aseg file found with expected naming pattern")
        aparc_file = mri_files[0]
        aparc_data = nib.load(aparc_file).get_fdata()
        
        # Load FreeSurfer LUT for ROI names
        # Assuming the LUT is in the same directory as the script
        lut_path = Path(__file__).parent / "FreesurferLUTR.txt"
        if not lut_path.exists():
            raise FileNotFoundError(f"FreeSurfer lookup table not found at {lut_path}")
        
        rois_info = pd.read_csv(lut_path, header=None, names=['ROI', 'Name'])
        
        # Find volume data files based on MRI prefix
        mri_prefix = aparc_file.stem.replace('_aparc+aseg', '')
        
        # Find volume data files
        volume_files = {
            'asegVolume': f"{mri_prefix}_asegVolume.csv",
            'aparcstatsVolumLeft': f"{mri_prefix}_aparcstatsVolumLeft.csv",
            'aparcstatsVolumRight': f"{mri_prefix}_aparcstatsVolumRight.csv"
        }
        
        # Load volume data
        volume_data = {
            'subcortical': pd.read_csv(mri_folder / volume_files['asegVolume']),
            'cortical_left': pd.read_csv(mri_folder / volume_files['aparcstatsVolumLeft']),
            'cortical_right': pd.read_csv(mri_folder / volume_files['aparcstatsVolumRight'])
        }
        
        # Verify data loading
        for name, data in volume_data.items():
            if data.empty:
                raise ValueError(f"Empty data in {name}")
            logging.info(f"Loaded {name} data shape: {data.shape}")
            
        return pet_data, aparc_data, rois_info, volume_data
        
    except Exception as e:
        logging.error(f"Error loading data: {str(e)}")
        raise


def get_volume_for_roi(roi: int, volume_data: Dict, rois_info: pd.DataFrame) -> float:
    """Helper function to get volume for a specific ROI"""
    try:
        # Get ROI name from lookup table
        roi_name = rois_info.loc[rois_info['ROI'] == roi, 'Name'].iloc[0]
        
        if roi < 1000:  # Subcortical
            # Convert FreeSurfer ROI name to volume column name
            vol_name = roi_name.replace(' ', '-')
            subcortical_data = volume_data['subcortical']
            if vol_name in subcortical_data.columns:
                return float(subcortical_data[vol_name].iloc[0])
            
        elif roi < 2000:  # Left cortical
            # Convert ctx-lh-X to lh_X_volume format
            vol_name = f"lh_{roi_name[7:]}_volume"
            left_data = volume_data['cortical_left']
            if vol_name in left_data.columns:
                return float(left_data[vol_name].iloc[0])
            
        else:  # Right cortical
            # Convert ctx-rh-X to rh_X_volume format
            vol_name = f"rh_{roi_name[7:]}_volume"
            right_data = volume_data['cortical_right']
            if vol_name in right_data.columns:
                return float(right_data[vol_name].iloc[0])
                
    except (ValueError, IndexError, KeyError) as e:
        logging.warning(f"Could not find volume for ROI {roi}: {str(e)}")
        
    return 0.0

def calculate_roi_values(pet_data: np.ndarray, aparc_data: np.ndarray, rois_info: pd.DataFrame) -> Tuple[Dict, float, float]:
    """Calculate values for each ROI"""
    values = {str(roi): [] for roi in rois_info['ROI']}
    
    # Use numpy operations for better performance
    mask = aparc_data != 0
    roi_vals = aparc_data[mask]
    pet_vals = pet_data[mask]
    
    # Update min/max
    min_val = np.min(pet_vals)
    max_val = np.max(pet_vals)
    
    # Group values by ROI
    unique_rois = np.unique(roi_vals)
    for roi in unique_rois:
        roi_mask = roi_vals == roi
        values[str(int(roi))] = pet_vals[roi_mask].tolist()
        
    return values, min_val, max_val


def calculate_statistics(roi_values: Dict, rois_info: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calculate median, mean, and sum for each ROI"""
    rois = rois_info['ROI'].values
    suv_med = np.zeros(len(rois))
    suv_avr = np.zeros(len(rois))
    suv_sum = np.zeros(len(rois))
    
    for i, roi in enumerate(rois):
        vals = np.array(roi_values[str(int(roi))])
        if len(vals) > 0:
            suv_med[i] = np.median(vals)
            suv_avr[i] = np.mean(vals)
            suv_sum[i] = np.sum(vals)
            
    return suv_med, suv_avr, suv_sum


def calculate_reference_values(suv_avr: np.ndarray, rois_info: pd.DataFrame, volume_data: Dict) -> Tuple[float, float]:
    """Calculate cerebellum reference values"""
    # Map ROIs to indices
    roi_map = {roi: i for i, roi in enumerate(rois_info['ROI'])}
    
    # Calculate cerebellum (combined white and gray matter)
    cerebellum_rois = {
        'Left-Cerebellum-White-Matter': 7,
        'Left-Cerebellum-Cortex': 8,
        'Right-Cerebellum-White-Matter': 46,
        'Right-Cerebellum-Cortex': 47
    }
    
    total_volume = 0
    weighted_sum = 0
    
    subcortical_data = volume_data['subcortical']
    
    for name, roi in cerebellum_rois.items():
        idx = roi_map[roi]
        vol = float(subcortical_data[name].iloc[0])
        weighted_sum += suv_avr[idx] * vol
        total_volume += vol
    
    suv_cer = weighted_sum / total_volume if total_volume > 0 else 0
    
    # Calculate cerebellum gray matter only
    gm_rois = {'Left-Cerebellum-Cortex': 8, 'Right-Cerebellum-Cortex': 47}
    total_volume_gm = 0
    weighted_sum_gm = 0
    
    for name, roi in gm_rois.items():
        idx = roi_map[roi]
        vol = float(subcortical_data[name].iloc[0])
        weighted_sum_gm += suv_avr[idx] * vol
        total_volume_gm += vol
        
    suv_cer_gm = weighted_sum_gm / total_volume_gm if total_volume_gm > 0 else 0
    
    return suv_cer, suv_cer_gm


def calculate_regional_values(suv_avr: np.ndarray, suv_cer: float, rois_info: pd.DataFrame, 
                             volume_data: Dict) -> Dict[str, float]:
    """
    Calculate regional SUVR values with cerebellum normalization.
    
    Uses volume-weighted pooling for bilateral (combined) regions, Global, and Total
    to match the R implementation:
      - Combined region = (sum_suvr_left + sum_suvr_right) / (vol_left + vol_right)
      - Global = pooled volume-weighted sum across all 5 named regions / total volume
      - Total = pooled volume-weighted sum across ALL cortical ROIs / total volume
    """
    # Convert SUV to SUVR using cerebellum reference
    suvr_avr = suv_avr / suv_cer if suv_cer > 0 else np.zeros_like(suv_avr)
    
    # Define ROI mappings for the 5 named regions
    roi_mappings = {
        'AnteriorCingulate': {'left': [1026, 1002], 'right': [2026, 2002]},
        'PosteriorCingulate': {'left': [1023, 1010], 'right': [2023, 2010]},
        'Frontal': {
            'left': [1003, 1012, 1014, 1018, 1019, 1020, 1027, 1028, 1032],
            'right': [2003, 2012, 2014, 2018, 2019, 2020, 2027, 2028, 2032]
        },
        'Temporal': {'left': [1030, 1015], 'right': [2030, 2015]},
        'Parietal': {'left': [1008, 1025, 1029, 1031], 'right': [2008, 2025, 2029, 2031]}
    }
    
    regional_results = {}
    
    # Accumulators for Global (sum of the 5 named regions only)
    global_left_weighted_sum = 0.0
    global_left_vol = 0.0
    global_right_weighted_sum = 0.0
    global_right_vol = 0.0
    
    # Process each named region
    for region, hemispheres in roi_mappings.items():
        # Accumulators for this region (both hemispheres, for the combined value)
        region_weighted_sum_left = 0.0
        region_vol_left = 0.0
        region_weighted_sum_right = 0.0
        region_vol_right = 0.0
        
        # --- Left hemisphere ---
        for roi in hemispheres['left']:
            idx = np.where(rois_info['ROI'] == roi)[0][0]
            vol = get_volume_for_roi(roi, volume_data, rois_info)
            if np.isfinite(suvr_avr[idx]):
                region_weighted_sum_left += suvr_avr[idx] * vol
                region_vol_left += vol
        
        # --- Right hemisphere ---
        for roi in hemispheres['right']:
            idx = np.where(rois_info['ROI'] == roi)[0][0]
            vol = get_volume_for_roi(roi, volume_data, rois_info)
            if np.isfinite(suvr_avr[idx]):
                region_weighted_sum_right += suvr_avr[idx] * vol
                region_vol_right += vol
        
        # Hemispheric values for this region
        if region_vol_left > 0:
            regional_results[f'{region}Left'] = region_weighted_sum_left / region_vol_left
        else:
            regional_results[f'{region}Left'] = 0.0
            
        if region_vol_right > 0:
            regional_results[f'{region}Right'] = region_weighted_sum_right / region_vol_right
        else:
            regional_results[f'{region}Right'] = 0.0
        
        # FIX: Combined region uses volume-weighted pooling (matches R)
        total_region_vol = region_vol_left + region_vol_right
        if total_region_vol > 0:
            regional_results[region] = (region_weighted_sum_left + region_weighted_sum_right) / total_region_vol
        else:
            regional_results[region] = 0.0
        
        # Accumulate into Global sums
        global_left_weighted_sum += region_weighted_sum_left
        global_left_vol += region_vol_left
        global_right_weighted_sum += region_weighted_sum_right
        global_right_vol += region_vol_right
    
    # FIX: Global = volume-weighted pooling across the 5 named regions (matches R)
    if global_left_vol > 0:
        regional_results['GlobalLeft'] = global_left_weighted_sum / global_left_vol
    else:
        regional_results['GlobalLeft'] = 0.0
        
    if global_right_vol > 0:
        regional_results['GlobalRight'] = global_right_weighted_sum / global_right_vol
    else:
        regional_results['GlobalRight'] = 0.0
    
    total_global_vol = global_left_vol + global_right_vol
    if total_global_vol > 0:
        regional_results['Global'] = (global_left_weighted_sum + global_right_weighted_sum) / total_global_vol
    else:
        regional_results['Global'] = 0.0
    
    # FIX: Total = volume-weighted pooling across ALL cortical ROIs (1001-1035, 2001-2035)
    # This matches R's sum_suvrsTotalL / sum_volTotalL approach
    total_left_weighted_sum = 0.0
    total_left_vol = 0.0
    total_right_weighted_sum = 0.0
    total_right_vol = 0.0
    
    rois_array = rois_info['ROI'].values
    for i, roi in enumerate(rois_array):
        if 1000 < roi < 2000:
            # Left cortical
            if np.isfinite(suvr_avr[i]):
                vol = get_volume_for_roi(roi, volume_data, rois_info)
                total_left_weighted_sum += suvr_avr[i] * vol
                total_left_vol += vol
        elif roi > 2000:
            # Right cortical
            if np.isfinite(suvr_avr[i]):
                vol = get_volume_for_roi(roi, volume_data, rois_info)
                total_right_weighted_sum += suvr_avr[i] * vol
                total_right_vol += vol
    
    if total_left_vol > 0:
        regional_results['TotalLeft'] = total_left_weighted_sum / total_left_vol
    else:
        regional_results['TotalLeft'] = 0.0
        
    if total_right_vol > 0:
        regional_results['TotalRight'] = total_right_weighted_sum / total_right_vol
    else:
        regional_results['TotalRight'] = 0.0
    
    total_all_vol = total_left_vol + total_right_vol
    if total_all_vol > 0:
        regional_results['Total'] = (total_left_weighted_sum + total_right_weighted_sum) / total_all_vol
    else:
        regional_results['Total'] = 0.0
        
    return regional_results


def save_results(output_folder: Path, output_name: str, min_val: float, max_val: float,
                suv_cer: float, suv_cer_gm: float, rois_info: pd.DataFrame, suv_stats: Dict,
                combined_values: Dict[str, float], scan_date: str, manual_compound: Optional[str] = None) -> None:
    """Save all results"""

    output_folder.mkdir(parents=True, exist_ok=True)

    # Get PID from register_scan folder
    register_scan_path = output_folder.parent / 'register_scan'
    nii_files = list(register_scan_path.glob('*.nii'))
    
    if not nii_files:
        logging.warning(f"No PET NIfTI files found in register_scan folder: {register_scan_path}")
        nii_filename = f"{output_name}.nii"  # Use output_name as fallback
    else:
        nii_filename = nii_files[0].name
        
    # Save basic values
    for name, value in [
        ('max', max_val),
        ('min', min_val),
        ('suv_cer', suv_cer),
        ('suv_cer_gm', suv_cer_gm)
    ]:
        with open(output_folder / f"{output_name}_{name}", 'w') as f:
            f.write(str(value))
    
    # Save detailed statistics
    for stat_name, values in [
        ('mean_suv', suv_stats['mean']),
        ('median_suv', suv_stats['median']),
        ('total_suv', suv_stats['sum']),
    ]:
        df = pd.DataFrame({
            'ROI': rois_info['ROI'],
            'Name': rois_info['Name'],
            'Value': values
        })
        df.to_csv(output_folder / f"{output_name}_{stat_name}.csv", index=False)
    
    for stat_name, values in [
        ('suvr_cerebellum', suv_stats['suvr']),
        ('suvr_cerebellum_gm', [v * suv_cer / suv_cer_gm for v in suv_stats['suvr']])
    ]:
        
        df = pd.DataFrame({
            'ROI': rois_info['ROI'],
            'Name': rois_info['Name'],
            'Value': values
        })
        
        df = df.set_index("ROI").T
        df.insert(0, 'PID', ["N/A", nii_filename])  # First column = PID with nii_filename
        df.to_csv(output_folder / f"{output_name}_{stat_name}.csv", index=False)

    # Save combined SUVR results
    regions = [
        "AnteriorCingulateLeft", "AnteriorCingulateRight",
        "PosteriorCingulateLeft", "PosteriorCingulateRight",
        "FrontalLeft", "FrontalRight",
        "TemporalLeft", "TemporalRight",
        "ParietalLeft", "ParietalRight",
        "AnteriorCingulate", "PosteriorCingulate",
        "Frontal", "Temporal", "Parietal",
        "TotalLeft", "TotalRight", "Total",
        "GlobalLeft", "GlobalRight", "Global"
    ]
    
    # Get values for each region
    values = [combined_values.get(region, 0.0) for region in regions]
    
    # Determine the compound based on scan date
    compound = determine_compound(scan_date, manual_compound)
    
    # Prepare the headers with PID and Compound at the beginning
    headers = ["PID", "Compound", "Centiloid"] + regions
    
    # Calculate centiloid value if Global is in regions
    global_idx = regions.index("Global")
    centiloid_value = calculate_centiloid(compound, values[global_idx]) if global_idx >= 0 else 0
    
    # Create the data row with PID and Compound
    data_row = [nii_filename, compound, centiloid_value] + values
    
    # Create combined DataFrame with just two rows
    combined_df = pd.DataFrame([headers, data_row])
    
    # Save to CSV without index or headers
    combined_df.to_csv(
        output_folder / f"{output_name}_suvr_combined_cerebellum.csv",
        index=False, header=False
    )
    
    # Save GM-normalized values
    gm_factor = suv_cer / suv_cer_gm if suv_cer_gm > 0 else 1.0
    gm_values = [v * gm_factor for v in values]
    
    # Calculate centiloid value for GM-normalized data
    gm_centiloid_value = calculate_centiloid(compound, gm_values[global_idx]) if global_idx >= 0 else 0
    
    # Create the data row with PID and Compound for GM data
    gm_data_row = [nii_filename, compound, gm_centiloid_value] + gm_values
    
    # Create combined GM DataFrame with just two rows
    combined_gm_df = pd.DataFrame([headers, gm_data_row])
    
    # Save to CSV without index or headers
    combined_gm_df.to_csv(
        output_folder / f"{output_name}_suvr_combined_cerebellum_gm.csv",
        index=False, header=False
    )
                        

def process_mri_folder(scan_folder: Path, mri_process_folder: Path, manual_compound: Optional[str] = None) -> bool:
    """Process a specific MRI processing folder"""
    try:
        # Find MRI folder with aparc+aseg file
        mri_folder = mri_process_folder / "MRI"
        if not mri_folder.exists():
            logging.error(f"MRI folder not found in {mri_process_folder}")
            return False
        
        # Find PET file in register_scan folder
        register_scan_dir = mri_process_folder / "register_scan"
        if not register_scan_dir.exists():
            register_scan_dir = scan_folder.glob("**/register_scan")
            if not register_scan_dir:
                logging.error(f"No register_scan folder found for {scan_folder}")
                return False
        
        pet_files = list(register_scan_dir.glob("*.nii")) # type: ignore
        pet_files = [f for f in pet_files if not ('aparc' in f.name.lower() or 'aseg' in f.name.lower())]
        if not pet_files:
            logging.error(f"No PET file found in {register_scan_dir}")
            return False

        # Create output folder
        output_folder = mri_process_folder / "res"
        output_folder.mkdir(parents=True, exist_ok=True)

        # Extract scan date from folder name
        try:
            pet_file = pet_files[0]
            _, scan_date, _, _ = parse_nifti_filename(pet_file.name)
        except ValueError:
            # If can't parse from filename, try from folder name
            try:
                scan_date = mri_process_folder.name.split('_')[2]
                if not (len(scan_date) == 8 and scan_date.isdigit()):
                    raise ValueError("Invalid scan date format")
            except (IndexError, ValueError):
                logging.warning(f"Could not extract scan date, using current date")
                scan_date = datetime.now().strftime("%Y%m%d")

        logging.info(f"Processing files:")
        logging.info(f"MRI folder: {mri_folder}")
        logging.info(f"PET file: {pet_files[0]}")
        logging.info(f"Output folder: {output_folder}")
        logging.info(f"Scan date: {scan_date}")
        
        # Load data
        pet_data, aparc_data, rois_info, volume_data = load_data(mri_folder, pet_files[0])
        
        # Calculate ROI values
        roi_values, min_val, max_val = calculate_roi_values(pet_data, aparc_data, rois_info)
        
        # Calculate statistics
        suv_med, suv_avr, suv_sum = calculate_statistics(roi_values, rois_info)
        
        # Calculate reference values
        suv_cer, suv_cer_gm = calculate_reference_values(suv_avr, rois_info, volume_data)
        
        # Calculate SUVR values
        suvr = suv_avr / suv_cer if suv_cer > 0 else np.zeros_like(suv_avr)
        
        # Compile statistics
        suv_stats = {
            "mean": suv_avr,
            "median": suv_med,
            "sum": suv_sum,
            "suvr": suvr
        }
        
        # Calculate combined values
        combined_values = calculate_regional_values(suv_avr, suv_cer, rois_info, volume_data)
        
        # Save results
        save_results(
            output_folder, 
            mri_process_folder.name,
            min_val, 
            max_val,
            suv_cer, 
            suv_cer_gm, 
            rois_info, 
            suv_stats,
            combined_values,
            scan_date,
            manual_compound
        )
        
        logging.info(f"Successfully processed {mri_process_folder.name}")
        return True
        
    except Exception as e:
        logging.error(f"Error processing folder {mri_process_folder.name}: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
        return False


def process_subject(subject_path: Path, manual_compound: Optional[str] = None) -> Dict[str, int]:
    """Process all scan dates for a subject"""
    results = {
        'scan_dates_found': 0,
        'pet_folders_found': 0,
        'mri_folders_found': 0,
        'successful_folders': 0,
        'failed_folders': 0
    }
    
    # Setup logging for the subject
    setup_logging(subject_path, subject_path.name)
    logging.info(f"Processing subject: {subject_path.name}")
    
    # Find all scan dates with SUVR folders
    scan_dates = find_scan_dates_with_suvr(subject_path)
    results['scan_dates_found'] = len(scan_dates)
    
    if not scan_dates:
        logging.warning(f"No scan dates with SUVR folders found for {subject_path.name}")
        return results
    
    logging.info(f"Found {len(scan_dates)} scan dates with SUVR folders")
    
    # Process each scan date
    for scan_date in scan_dates:
        logging.info(f"\nProcessing scan date: {scan_date.name}")
        
        # Find PET folders in this scan date
        pet_folders = find_pet_folders(scan_date)
        results['pet_folders_found'] += len(pet_folders)
        
        if not pet_folders:
            logging.warning(f"No PET folders found for scan date {scan_date.name}")
            continue
        
        logging.info(f"Found {len(pet_folders)} PET folders")
        
        # Process each PET folder
        for pet_folder in pet_folders:
            logging.info(f"\nProcessing PET folder: {pet_folder.name}")
            
            # Find MRI folders in this PET folder
            mri_folders = find_mri_folders(pet_folder)
            results['mri_folders_found'] += len(mri_folders)
            
            if not mri_folders:
                logging.warning(f"No MRI folders found for PET folder {pet_folder.name}")
                continue
            
            logging.info(f"Found {len(mri_folders)} MRI folders")
            
            # Process each MRI folder
            for mri_folder in mri_folders:
                logging.info(f"\nProcessing MRI folder: {mri_folder.name}")
                
                success = process_mri_folder(scan_date, mri_folder, manual_compound)
                if success:
                    results['successful_folders'] += 1
                    logging.info(f"Successfully processed {mri_folder.name}")
                else:
                    results['failed_folders'] += 1
                    logging.error(f"Failed to process {mri_folder.name}")
    
    # Log summary
    logging.info("\nProcessing Summary:")
    logging.info(f"Scan dates processed: {results['scan_dates_found']}")
    logging.info(f"PET folders found: {results['pet_folders_found']}")
    logging.info(f"MRI folders found: {results['mri_folders_found']}")
    logging.info(f"Successfully processed folders: {results['successful_folders']}")
    logging.info(f"Failed folders: {results['failed_folders']}")
    
    return results

def process_all_subjects(base_path: Path, manual_compound: Optional[str] = None) -> Dict[str, int]:
    """Process all subjects in the given base directory."""
    results = {
        'subjects_found': 0,
        'subjects_processed': 0,
        'successful_subjects': 0,
        'failed_subjects': 0,
        'total_scan_dates': 0,
        'total_pet_folders': 0,
        'total_mri_folders': 0,
        'total_successful': 0,
        'total_failed': 0
    }
    
    # Find all subject directories (assuming they are direct subdirectories)
    subject_dirs = [d for d in base_path.iterdir() if d.is_dir()]
    results['subjects_found'] = len(subject_dirs)

    if not subject_dirs:
        print(f"No subject directories found in {base_path}")
        return results

    print(f"Found {len(subject_dirs)} subject directories")
    
    # Process each subject
    for i, subject_dir in enumerate(subject_dirs, 1):
        print(f"\nProcessing subject {i}/{len(subject_dirs)}: {subject_dir.name}")
        
        try:
            subject_results = process_subject(subject_dir, manual_compound)
            
            # Update overall results
            results['subjects_processed'] += 1
            results['total_scan_dates'] += subject_results['scan_dates_found']
            results['total_pet_folders'] += subject_results['pet_folders_found']
            results['total_mri_folders'] += subject_results['mri_folders_found']
            results['total_successful'] += subject_results['successful_folders']
            results['total_failed'] += subject_results['failed_folders']
            
            if subject_results['failed_folders'] == 0 and subject_results['successful_folders'] > 0:
                results['successful_subjects'] += 1
            else:
                results['failed_subjects'] += 1
                
            # Print summary for this subject
            print(f"  Scan dates found: {subject_results['scan_dates_found']}")
            print(f"  PET folders found: {subject_results['pet_folders_found']}")
            print(f"  MRI folders found: {subject_results['mri_folders_found']}")
            print(f"  Successful folders: {subject_results['successful_folders']}")
            print(f"  Failed folders: {subject_results['failed_folders']}")
            
        except Exception as e:
            print(f"Error processing subject {subject_dir.name}: {str(e)}")
            import traceback
            print(traceback.format_exc())
            results['failed_subjects'] += 1
    
    return results


"""

Usage:
-----
# Process all subjects in a directory (default):
python suvr.py /path/to/subjects_directory

# Process a single subject:
python suvr.py /path/to/specific_subject --single-subject

# Override compound type:
python suvr.py /path/to/subjects_directory --compound neuraceq

# Enable verbose output:
python suvr.py /path/to/subjects_directory -v

"""


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Non-interactive PET SUVR Processing")
    parser.add_argument("directory_path", help="Path to the base directory with multiple subjects (or single subject with --single-subject flag)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--compound", choices=["neuraceq", "amyvid"], 
                        help="Manually specify the compound to use (overrides date-based determination)")
    parser.add_argument("--single-subject", action="store_true", 
                        help="Process only a single subject (the directory_path is treated as a subject directory)")
    
    args = parser.parse_args()
    
    path = Path(args.directory_path)
    if not path.exists():
        print(f"Path not found: {path}")
        return 1
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Process a single subject or all subjects
    start_time = datetime.now()
    
    if args.single_subject:
        # Process single subject
        print(f"Starting processing for single subject: {path.name}")
        print(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            results = process_subject(path, args.compound)
            
            # Print summary
            print("\nProcessing Summary:")
            print(f"Scan dates processed: {results['scan_dates_found']}")
            print(f"PET folders found: {results['pet_folders_found']}")
            print(f"MRI folders found: {results['mri_folders_found']}")
            print(f"Successfully processed folders: {results['successful_folders']}")
            print(f"Failed folders: {results['failed_folders']}")
            
            end_time = datetime.now()
            duration = end_time - start_time
            print(f"\nTotal processing time: {duration}")
            
            return 0 if results['failed_folders'] == 0 else 1
        
        except Exception as e:
            print(f"Error processing subject: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return 1
    else:
        # Process all subjects (default behavior)
        print(f"Starting processing for all subjects in: {path}")
        print(f"Start time: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            results = process_all_subjects(path, args.compound)
            
            # Print summary
            print("\nOverall Processing Summary:")
            print(f"Subjects found: {results['subjects_found']}")
            print(f"Subjects processed: {results['subjects_processed']}")
            print(f"Successful subjects: {results['successful_subjects']}")
            print(f"Failed subjects: {results['failed_subjects']}")
            print(f"Total scan dates processed: {results['total_scan_dates']}")
            print(f"Total PET folders found: {results['total_pet_folders']}")
            print(f"Total MRI folders found: {results['total_mri_folders']}")
            print(f"Total successfully processed folders: {results['total_successful']}")
            print(f"Total failed folders: {results['total_failed']}")
            
            end_time = datetime.now()
            duration = end_time - start_time
            print(f"\nTotal processing time: {duration}")
            
            return 0 if results['failed_subjects'] == 0 else 1
            
        except Exception as e:
            print(f"Error processing all subjects: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())