import subprocess
import json
import os
import tempfile

def grade_pdf(input_pdf: str, pdffigures2_jar: str):
    """
    Process a PDF using pdffigures2 and return extracted figure/table issues.
    """
    if not os.path.exists(input_pdf):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")
    if not os.path.exists(pdffigures2_jar):
        raise FileNotFoundError(f"pdffigures2 JAR not found: {pdffigures2_jar}")

    command = ["java", "-jar", pdffigures2_jar, input_pdf, "-d", "_"]
    print(f"Running pdffigures2 on: {input_pdf}")

    subprocess.run(command, capture_output=True, text=True, check=True)

    output_json_file = "_" + os.path.splitext(os.path.basename(input_pdf))[0] + ".json"
    print(f"Expecting output JSON: {output_json_file}")

    if not os.path.exists(output_json_file):
        raise Exception(f"JSON output file not found: {output_json_file}")

    with open(output_json_file, "r") as f:
        regions = json.load(f)

    # Clean up the output json file
    os.unlink(output_json_file)

    issue_list = []
    for i, region in enumerate(regions):
        issues = {}
        if region["captionBoundary"]["y1"] > region["regionBoundary"]["y1"]:
            region["captionLocation"] = "Below"
        else:
            region["captionLocation"] = "Above"

        if region["captionLocation"] == "Below" and region["figType"] == "Table":
            issues["id"] = f"figure-issue-{i}"
            issues["page_number"] = region["page"] + 1
            issues["caption_coordinate"] = region["captionBoundary"]
            issues["fig_type"] = region["figType"]
            issues["caption_location"] = region["captionLocation"]
            issues["description"] = "Location of the caption for tables must be above the table."
            issue_list.append(issues)

        if region["captionLocation"] == "Above" and region["figType"] == "Figure":
            issues["id"] = f"figure-issue-{i}"
            issues["page_number"] = region["page"] + 1
            issues["caption_coordinate"] = region["captionBoundary"]
            issues["fig_type"] = region["figType"]
            issues["caption_location"] = region["captionLocation"]
            issues["description"] = "Location of the caption for figures must be below the figure."
            issue_list.append(issues)

    return issue_list
