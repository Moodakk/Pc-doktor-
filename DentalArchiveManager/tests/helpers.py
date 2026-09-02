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
) -> str:
    study_uid = study_uid or generate_uid()
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = SecondaryCaptureImageStorage
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
