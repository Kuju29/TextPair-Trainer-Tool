import requests, time, csv
import numpy as np
import os

API_URL = "http://localhost:5000"

def upload_and_get_ocr_result(image_path, api_url=API_URL):
    with open(image_path, 'rb') as f:
        files = {'image': f}
        response = requests.post(f"{api_url}/ocr", files=files)
        data = response.json()
        job_id = data["job_id"]
    print(f"Uploaded {image_path}, job_id: {job_id}")
    while True:
        res = requests.get(f"{api_url}/ocr/result/{job_id}").json()
        if res.get("status") == "done":
            return res["result"]
        elif res.get("status") == "error":
            raise Exception(res.get("error"))
        time.sleep(1)

def compute_center_y(annotation):
    vertices = annotation.get("boundingPoly", {}).get("vertices", [])
    if not vertices or len(vertices) != 4:
        return None
    ys = [v.get("y", 0) for v in vertices]
    return sum(ys) / len(ys)

def group_annotations_by_line(annotations, threshold_y=10):
    groups = {}
    for ann in annotations:
        line_idx = ann.get("data_line_index")
        if line_idx is not None:
            groups.setdefault(line_idx, []).append(ann)
        else:
            cy = compute_center_y(ann)
            if cy is None:
                continue
            group_key = str(int(cy // threshold_y))
            groups.setdefault(group_key, []).append(ann)
    sorted_groups = [groups[key] for key in sorted(groups, key=lambda x: float(x))]
    return sorted_groups

def merge_group_text(group):
    sorted_group = sorted(group, key=lambda ann: ann.get("boundingPoly", {}).get("vertices", [{}])[0].get("x", 0))
    texts = [ann["description"] for ann in sorted_group]
    return " ".join(texts)

def pair_groups(eng_groups, thai_groups):
    min_len = min(len(eng_groups), len(thai_groups))
    pairs = []
    for i in range(min_len):
        eng_text = merge_group_text(eng_groups[i])
        thai_text = merge_group_text(thai_groups[i])
        pairs.append((eng_text, thai_text))
    if len(eng_groups) != len(thai_groups):
        print(f"Warning: Group counts differ (eng={len(eng_groups)}, thai={len(thai_groups)}); using {min_len} pairs.")
    return pairs

def export_pairs_to_csv(pairs, csv_file):
    file_exists = os.path.exists(csv_file)
    with open(csv_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists or os.path.getsize(csv_file) == 0:
            writer.writerow(["prompt", "completion"])
        for eng_text, thai_text in pairs:
            writer.writerow([eng_text, thai_text])
    print(f"CSV exported to {csv_file}")
