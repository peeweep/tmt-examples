#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pandas",
#     "openpyxl",
#     "requests",
#     "pyyaml",
# ]
# ///
"""
This script downloads GitHub Actions artifacts for a given Run ID and parses the `results.yaml` 
from tmt tests, exporting the data to an Excel format.

You can run this script directly with uv:
uv run export_tmt_results.py --help
"""

import os
import sys
import yaml
import zipfile
import argparse
import requests
import pandas as pd
from io import BytesIO

def get_artifacts_list(repo, run_id, token):
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get("artifacts", [])

def get_jobs_list(repo, run_id, token):
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"
    jobs = []

    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        jobs.extend(data.get("jobs", []))
        url = response.links.get("next", {}).get("url")

    return jobs

def download_and_extract_artifact(url, token, extract_to):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    response = requests.get(url, headers=headers, stream=True)
    response.raise_for_status()
    
    with zipfile.ZipFile(BytesIO(response.content)) as zip_ref:
        zip_ref.extractall(extract_to)

def parse_tmt_results(base_dir, artifact_to_job_url, fallback_run_link):
    all_results = []
    
    for root, dirs, files in os.walk(base_dir):
        if "results.yaml" in files:
            file_path = os.path.join(root, "results.yaml")
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if not data:
                        continue
                    
                    # Extract the artifact folder name (the top level folder inside download_dir)
                    rel_dir = os.path.relpath(root, base_dir)
                    artifact_name = rel_dir.split(os.sep)[0]
                    
                    job_link = artifact_to_job_url.get(artifact_name, fallback_run_link)

                    for item in data:
                        all_results.append({
                            "Artifact": artifact_name,
                            "Job Link": job_link,
                            "Test Name": item.get("name", "N/A"),
                            "Result": item.get("result", "N/A"),
                            "Duration": item.get("duration", "N/A"),
                            "Log Path": ", ".join(item.get("log", [])),
                        })
            except Exception as e:
                print(f"Error parsing {file_path}: {e}")
                
    return all_results

def main():
    parser = argparse.ArgumentParser(description="Download GitHub Actions tmt artifacts and export to Excel.")
    parser.add_argument("--repo", required=True, help="Repository in format owner/repo (e.g., username/tmt-examples)")
    parser.add_argument("--run-id", required=True, help="GitHub Actions Run ID (from the workflow run URL)")
    parser.add_argument("--token", help="GitHub Personal Access Token (can also be set via GITHUB_TOKEN env var)")
    parser.add_argument("--output", default="tmt_test_results.xlsx", help="Output Excel file name")
    parser.add_argument("--download-dir", default="tmt_artifacts", help="Directory to extract artifacts")
    
    args = parser.parse_args()
    
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Warning: No GitHub Token provided. If the repository is private or has token limits, downloading will fail.")
        print("You can pass a token via --token or set the GITHUB_TOKEN environment variable.\n")
        
    print(f"Fetching artifacts for {args.repo} run {args.run_id}...")
    try:
        artifacts = get_artifacts_list(args.repo, args.run_id, token)
    except Exception as e:
        print(f"Failed to fetch artifacts: {e}")
        sys.exit(1)

    print(f"Fetching jobs mapping for {args.repo} run {args.run_id}...")
    try:
        jobs = get_jobs_list(args.repo, args.run_id, token)
        artifact_to_job_url = {}
        for job in jobs:
            job_name = job.get("name", "")
            if job_name:
                safe_name = job_name.replace("/", "-")
                expected_artifact = f"tmt-results-{safe_name}"
                artifact_to_job_url[expected_artifact] = job.get("html_url")
    except Exception as e:
        print(f"Failed to fetch jobs (Job links will default to run URL): {e}")
        artifact_to_job_url = {}
        
    if not artifacts:
        print("No artifacts found for this run.")
        sys.exit(0)
        
    print(f"Found {len(artifacts)} artifacts. Downloading and extracting to {args.download_dir}/ ...")
    os.makedirs(args.download_dir, exist_ok=True)
    
    for arg in artifacts:
        name = arg["name"]
        download_url = arg["archive_download_url"]
        print(f"  Downloading artifact: {name} ...")
        
        extract_path = os.path.join(args.download_dir, name)
        os.makedirs(extract_path, exist_ok=True)
        
        try:
            download_and_extract_artifact(download_url, token, extract_path)
        except Exception as e:
            print(f"  Failed to download {name}: {e}")
            
    print("\nParsing tmt results.yaml files...")
    fallback_run_link = f"https://github.com/{args.repo}/actions/runs/{args.run_id}"
    results = parse_tmt_results(args.download_dir, artifact_to_job_url, fallback_run_link)
    
    if not results:
        print("No test results found in the artifacts.")
        sys.exit(0)
        
    print(f"Found {len(results)} test results. Exporting to {args.output}...")
    try:
        df = pd.DataFrame(results)
        df.to_excel(args.output, index=False)
        print(f"✅ Successfully exported test results to {args.output}")
    except ImportError as e:
        print(f"Export failed: {e}")
        print("Make sure you have pandas and openpyxl installed: pip install pandas openpyxl")
        sys.exit(1)

if __name__ == "__main__":
    main()
