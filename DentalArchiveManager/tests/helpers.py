from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid


def write_test_dicom(
    path: Path,
    *,
    modality: str,
    study_uid: str | None = None,
    patient_name: str = "Test^Patient",
    patient_id: str = "P-001",
    study_date: str = "20260806",
    sop_class_uid: str | None = None,
) -> str:
    study_uid = study_uid or generate_uid()
    storage_class = sop_class_uid or SecondaryCaptureImageStorage
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = storage_class
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = storage_class
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = generate_uid()
    dataset.PatientName = patient_name
    dataset.PatientID = patient_id
    dataset.StudyDate = study_date
    dataset.Modality = modality
    dataset.StudyDescription = "Dental test"
    dataset.save_as(path, enforce_file_format=True)
    return study_uid
