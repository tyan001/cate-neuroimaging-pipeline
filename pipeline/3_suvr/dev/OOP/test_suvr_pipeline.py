"""Unit tests for suvr_pipeline that need no imaging data or external tools.

    python3 -m unittest test_suvr_pipeline -v     # from pipeline/3_suvr/OOP
"""
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from suvr_pipeline.layout import Dataset, PairFolder, PetMriPair, closest_mri
from suvr_pipeline.naming import ScanFile
from suvr_pipeline.quantify import CEREBELLUM_WHOLE, CorticalRegion, RoiTable, SuvrCalculator, VolumeTables
from suvr_pipeline.stages import PrepareStage, QuantifyStage, RegisterStage, Status
from suvr_pipeline.tracer import AMYVID, NEURACEQ, TracerPolicy


def setUpModule():
    logging.disable(logging.WARNING)  # expected warnings from edge-case inputs


def tearDownModule():
    logging.disable(logging.NOTSET)


def scan(name, parent="/data/900001/20240809/pet"):
    return ScanFile.parse(Path(parent) / name)


class ScanFileTest(unittest.TestCase):
    def test_plain(self):
        s = scan("900004-20150527_PET.nii")
        self.assertEqual((s.subject_id, s.date, s.modality, s.extra), ("900004", "20150527", "PET", None))

    def test_extra(self):
        self.assertEqual(scan("900001-20240809_PET_256.nii").extra, "256")
        self.assertEqual(scan("110015-20150527_PET_128a.nii").extra, "128a")

    def test_invalid(self):
        for bad in ("nodash_PET.nii", "900004-20150527.nii"):
            with self.assertRaises(ValueError):
                scan(bad)
        self.assertIsNone(ScanFile.try_parse(Path("junk.nii")))


class PairNamingTest(unittest.TestCase):
    def test_folder_names(self):
        pet = scan("900001-20240809_PET_256.nii", "/r/900001/20240809/pet")
        mri = scan("900001-20240828_T1w.nii", "/r/900001/20240828/anat")
        pair = PetMriPair(pet, mri)
        self.assertEqual(pair.folder.path, Path(
            "/r/900001/20240809/suvr/900001-20240809_PET_256/900001_pet_20240809_256_mri_20240828"))
        self.assertEqual(pair.freesurfer_subject_dir,
                         Path("/r/900001/20240828/freesurfer741/900001-20240828_T1w"))
        self.assertEqual(pair.folder.subject_dir, Path("/r/900001"))

    def test_cormprage(self):
        pet = scan("900041-20160408_PET.nii")
        mri = scan("900041-20200224_CorMPRAGE.nii", "/r/900041/20200224/anat")
        self.assertEqual(PetMriPair(pet, mri).pair_dir_name, "900041_pet_20160408_mri_20200224_CorMPRAGE")

    def test_registration_output_name(self):
        name = RegisterStage.output_name(scan("110015-20150527_PET_128.nii"), scan("110015-20150601_T1w.nii"))
        self.assertEqual(name, "110015-20150527_128_reg_110015-20150601_T1w.nii")


class ClosestMriTest(unittest.TestCase):
    def test_nearest_and_tie(self):
        pet = scan("1-20200110_PET.nii")
        mris = [scan(n) for n in ("1-20200101_T1w.nii", "1-20200119_T1w.nii", "1-20190101_T1w.nii")]
        self.assertEqual(closest_mri(pet, mris).date, "20200101")  # 9 days each way -> first wins

    def test_unparseable_dates(self):
        self.assertIsNone(closest_mri(scan("1-2020_PET.nii"), [scan("1-20200101_T1w.nii")]))
        self.assertEqual(closest_mri(scan("1-20200101_PET.nii"), [scan("1-bad_T1w.nii"), scan("1-20210101_T1w.nii")]).date,
                         "20210101")


class TracerTest(unittest.TestCase):
    def test_cutoff(self):
        policy = TracerPolicy()
        self.assertIs(policy.for_date("20160926"), AMYVID)
        self.assertIs(policy.for_date("20160927"), NEURACEQ)
        self.assertIs(TracerPolicy.from_name("amyvid").for_date("20240101"), AMYVID)

    def test_centiloid(self):
        self.assertAlmostEqual(NEURACEQ.centiloid(1.0), -1.5)
        self.assertAlmostEqual(AMYVID.centiloid(1.0), 5.81)


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ("900001/20240809/pet/900001-20240809_PET_256.nii",
                    "900001/20170920/pet/900001-20170920_PET.nii",
                    "900001/20170920/pet/notes.nii",
                    "900001/20171013/anat/900001-20171013_T1w.nii",
                    "900001/20240828/anat/900001-20240828_T1w.nii"):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).touch()

    def tearDown(self):
        self.tmp.cleanup()

    def test_pairs_one_per_pet(self):
        subject, = Dataset(self.root).subjects()
        pairs = {p.pet.date: p.mri.date for p in subject.pairs()}
        self.assertEqual(pairs, {"20170920": "20171013", "20240809": "20240828"})

    def test_pair_folders_skip_logs_and_partials(self):
        base = self.root / "900001/20170920/suvr"
        pair = base / "900001-20170920_PET/900001_pet_20170920_mri_20171013"
        (pair / "register_scan").mkdir(parents=True)
        (base / "logs").mkdir()
        (base / "900001-20170920_PET/logs").mkdir()
        (pair / "register_scan/x.partial.nii").touch()
        subject, = Dataset(self.root).subjects()
        self.assertEqual([f.path for f in subject.pair_folders()], [pair])
        self.assertEqual(PairFolder(pair).registered_pets(), [])
        self.assertEqual(PairFolder(pair).scan_date(), "20170920")

    def test_missing_subject(self):
        with self.assertRaises(FileNotFoundError):
            Dataset(self.root).subjects(["999999"])

    def test_prepare_resumes_per_file(self):
        """A folder left half-built by an interrupted run is completed, not skipped."""
        subject, = Dataset(self.root).subjects()
        pair = next(p for p in subject.pairs() if p.pet.date == "20170920")
        (pair.freesurfer_subject_dir / "mri").mkdir(parents=True)
        stats = pair.freesurfer_subject_dir / "stats"
        stats.mkdir()
        for name in ("aparcstatsVolumLeft", "aparcstatsVolumRight", "asegVolume"):
            (stats / f"{name}.csv").write_text("a\tb\n1\t2\n")
        pair.folder.mri_dir.mkdir(parents=True)
        (pair.folder.mri_dir / pair.mri.name).touch()  # T1 done, aparc+aseg not

        fs = mock.Mock()
        fs.convert.side_effect = lambda src, dst, log: dst.touch()
        stage = PrepareStage(freesurfer=fs)
        log = logging.getLogger("test")
        self.assertIs(stage.process(pair, log), Status.DONE)
        self.assertEqual([c.args[0].name for c in fs.convert.call_args_list], ["aparc+aseg.mgz"])
        self.assertEqual((pair.folder.mri_dir / "900001-20171013_T1w_asegVolume.csv").read_text(), "a,b\n1,2\n")
        self.assertIs(stage.process(pair, log), Status.SKIPPED)

    def test_prepare_fails_without_recon_all(self):
        subject, = Dataset(self.root).subjects()
        outcome = PrepareStage().run(next(subject.pairs()))
        self.assertIs(outcome.status, Status.FAILED)
        self.assertIn("recon-all", outcome.message)


class CalculatorTest(unittest.TestCase):
    """Tiny synthetic volume: cerebellum = 2.0 everywhere, frontal parcels = 3.0."""

    def setUp(self):
        self.rois = RoiTable(pd.DataFrame({
            "ROI": [7, 8, 46, 47, 1003, 2003, 1002, 2002],
            "Name": ["Left-Cerebellum-White-Matter", "Left-Cerebellum-Cortex",
                     "Right-Cerebellum-White-Matter", "Right-Cerebellum-Cortex",
                     "ctx-lh-caudalmiddlefrontal", "ctx-rh-caudalmiddlefrontal",
                     "ctx-lh-caudalanteriorcingulate", "ctx-rh-caudalanteriorcingulate"],
        }))
        # 1002/2002 have no voxels and no volume column.
        self.calc = SuvrCalculator(self.rois, regions=[
            CorticalRegion("Frontal", (1003,), (2003,)),
            CorticalRegion("AnteriorCingulate", (1002,), (2002,)),
        ])
        self.volumes = VolumeTables(
            pd.DataFrame({c: [10.0] for c in CEREBELLUM_WHOLE}),
            pd.DataFrame({"lh_caudalmiddlefrontal_volume": [5.0]}),
            pd.DataFrame({"rh_caudalmiddlefrontal_volume": [15.0]}),
        )
        self.aparc = np.array([7, 8, 46, 47, 1003, 1003, 2003, 0], dtype=float)
        self.pet = np.array([2, 2, 2, 2, 3, 3, 3, 99], dtype=float)

    def test_suvr(self):
        r = self.calc.compute(self.pet, self.aparc, self.volumes)
        self.assertEqual((r.suv_cer, r.suv_cer_gm, r.max), (2.0, 2.0, 3.0))  # label-0 voxel ignored
        self.assertEqual(r.regional["FrontalLeft"], 1.5)
        self.assertEqual(r.regional["Global"], 1.5)
        self.assertEqual(r.regional["AnteriorCingulate"], 0.0)  # parcels absent -> 0, not NaN
        self.assertEqual(r.regional["Total"], 1.5)
        self.assertEqual(list(r.suv_sum[4:]), [6.0, 3.0, 0.0, 0.0])

    def test_nonpositive_reference_fails_quantify(self):
        stage = QuantifyStage()
        folder = mock.Mock(spec=PairFolder)
        folder.registered_pets.return_value = [Path("1-20200101_reg_1-20200101_T1w.nii")]
        folder.aparc_aseg.return_value = Path("x_aparc+aseg.nii")
        folder.scan_date.return_value = "20200101"
        folder.name, folder.label = "pair", "pair"
        bad = self.calc.compute(-self.pet, self.aparc, self.volumes)
        with mock.patch("suvr_pipeline.stages.VolumeTables.load"), \
             mock.patch("suvr_pipeline.stages.SuvrCalculator.compute_files", return_value=bad), \
             mock.patch("suvr_pipeline.stages.ResultWriter.write") as write, \
             mock.patch.object(QuantifyStage, "rois", self.rois):
            with self.assertRaisesRegex(Exception, "reference SUV"):
                stage.process(folder, logging.getLogger("test"))
        write.assert_called_once()  # outputs still written, as suvr.py did


if __name__ == "__main__":
    unittest.main()
