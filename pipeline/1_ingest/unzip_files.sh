#!/bin/bash

# Check if the user provided a path as an argument
if [ $# -eq 0 ]; then
  echo "Usage: $0 /path/to/zip/files"
  exit 1
fi

# Assign the provided path to a variable
zip_folder="$1"

# Check if the provided path exists and is a directory
if [ ! -d "$zip_folder" ]; then
  echo "Error: $zip_folder is not a valid directory."
  exit 1
fi

# Loop through all .zip files in the specified directory
for file in "$zip_folder"/*.zip; do
  # Check if there are any .zip files
  if [ ! -e "$file" ]; then
    echo "No .zip files found in $zip_folder."
    exit 1
  fi

  # Remove the .zip extension to create the folder name
  dirname="${file%.zip}"
  dirname="${dirname##*/}"  # Extract the base name of the file

  # Create a folder with the same name as the zip file
  mkdir -p "$zip_folder/$dirname"

  # Extract the zip file into the folder
  unzip -q "$file" -d "$zip_folder/$dirname"

  echo "Extracted $file into $zip_folder/$dirname/"
done

echo "All .zip files have been processed!"