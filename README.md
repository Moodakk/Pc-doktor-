# Pc-doktor-

For cleaning and searching.

## Dental Archive Manager

An offline Windows app (in [`DentalArchiveManager/`](DentalArchiveManager/)) that scans selected folders, groups dental clinic data and lets you decide with checkboxes what to keep, copy, move, quarantine or send to the Recycle Bin. Ukrainian documentation: [`DentalArchiveManager/README_UA.md`](DentalArchiveManager/README_UA.md).

### What it recognises

- CT / CBCT studies from DICOM metadata (one row per study, not hundreds of slices);
- dental X-rays (`DX`, `CR`, `IO`, `PX`, …), ultrasound and MRI as other DICOM;
- DICOM-wrapped documents (Structured Reports, encapsulated PDF) and `DICOMDIR` indexes attached to their study;
- non-DICOM volume exports: NIfTI (`.nii`, `.nii.gz`), NRRD, MetaImage, VTK;
- videos (own `09_VIDEO` archive folder), patient photos, 3D models (STL/OBJ/PLY/3MF), documents, archives;
- junk (empty/temp/incomplete files) and exact SHA-256 duplicates;
- real file type by content signature — wrong or missing extensions are detected and explained.

### Key features

- Ukrainian and English interface with a language switcher (choice is remembered);
- multi-threaded scanning with a two-stage duplicate finder (size → prefix hash → full SHA-256);
- verified copies (SHA-256 before any source cleanup), JSON + CSV operation logs;
- CSV export of scan results and a self-contained HTML statistics report;
- **archive verification**: re-hashes files listed in the logs and reports OK / mismatch / missing;
- nothing is auto-deleted; direct Recycle-Bin cleanup requires a typed confirmation.

### Quick start

1. Double-click `DentalArchiveManager/START_APP.bat` (installs Python dependencies into `.venv` on first run).
2. Add source folders, pick a destination drive, press **Scan**.
3. Review categories, tick items, assign actions, press **Execute plan**.

Try it safely first: `CREATE_DEMO_DATA.bat` generates a synthetic demo dataset (no real patient data).

### Tests and releases

```bash
cd DentalArchiveManager
python -m unittest discover -v
```

GitHub Actions runs the test suite on Windows and Linux (Python 3.11–3.13) for every push and pull request. Pushing a `v*` tag builds the Windows EXE with PyInstaller and attaches it to the GitHub Release.
