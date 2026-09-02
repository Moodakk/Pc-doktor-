from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid


def make_dicom(path: Path, modality: str, study_uid: str, instance: int) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = generate_uid()
    dataset.PatientName = "DEMO^PATIENT"
    dataset.PatientID = "DEMO-001"
    dataset.StudyDate = "20260806"
    dataset.StudyDescription = "Synthetic dental demo"
    dataset.SeriesDescription = f"Demo series {instance}"
    dataset.Modality = modality
    dataset.InstanceNumber = instance
    dataset.save_as(path, enforce_file_format=True)


def make_image(path: Path, title: str, color: str) -> None:
    image = Image.new("RGB", (900, 600), color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 25, 875, 575), outline="white", width=5)
    draw.text((60, 70), title, fill="white")
    draw.text((60, 120), "SYNTHETIC DATA — NOT A REAL PATIENT", fill="white")
    image.save(path)


def main() -> None:
    root = Path(__file__).with_name("DEMO_DENTAL_DATA")
    ct = root / "Demo Patient" / "CBCT_2026-08-06"
    xray = root / "Demo Patient" / "RTG_RVG"
    photos = root / "Demo Patient" / "Photos_Before_After"
    models = root / "Demo Patient" / "IOS_STL"
    junk = root / "Downloads_Temp"
    for directory in (ct, xray, photos, models, junk):
        directory.mkdir(parents=True, exist_ok=True)

    study_uid = generate_uid()
    for number in range(1, 6):
        make_dicom(ct / f"slice_{number:03}.dcm", "CT", study_uid, number)
    make_image(xray / "bitewing_rvg_16_17.png", "DEMO BITEWING", "#263238")
    make_image(photos / "smile_before.jpg", "DEMO PHOTO BEFORE", "#006d73")
    make_image(photos / "smile_after.jpg", "DEMO PHOTO AFTER", "#008f95")
    model = "solid demo\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid demo\n"
    (models / "upper_scan.stl").write_text(model, encoding="utf-8")
    (models / "upper_scan_copy.stl").write_text(model, encoding="utf-8")
    (junk / "unfinished.crdownload").write_bytes(b"partial")
    (junk / "empty.tmp").write_bytes(b"")
    print(f"Demo data created: {root}")


if __name__ == "__main__":
    main()
