"""Object-oriented PET SUVR / Centiloid pipeline (stage 3).

Module map:

    naming.py    ScanFile         -- parsed ``<subj>-<date>_<modality>[_<extra>].nii`` filename
    layout.py    Dataset, Subject -- the ADRC tree on disk
                 PetMriPair       -- a PET scan matched to its closest MRI (what `prepare` builds)
                 PairFolder       -- an existing pair folder (what `register`/`quantify` consume)
    tools.py     FreeSurfer, Flirt -- wrappers around external binaries
    tracer.py    Tracer, TracerPolicy -- Centiloid equations and tracer selection
    quantify.py  RoiTable, VolumeTables, SuvrCalculator, SuvrResult, ResultWriter
    stages.py    Stage and its subclasses PrepareStage, RegisterStage, QuantifyStage
    runner.py    StageRunner      -- fan tasks out over worker processes, summarise
"""
