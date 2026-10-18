# 01: Record the "before" snapshot on the processing server

**What to build:** A saved record of what the production pipeline does today on the de-identified test dataset. Ticket 07 compares against it to show the switch to `cate` changed nothing except the agreed rules. This runs on the processing server against a fresh copy of the test dataset, with FreeSurfer and FSL available. It must be done before any production script is changed (tickets 03–05).

Record, for each of the prepare step, register step, quantify step and recon runner:
- the full list of folders and files it creates or modifies, with file sizes;
- the external tool commands it issues (from its logs);
- for the register and quantify steps, which Pair folders they pick up;
- for the quantify step, the SUVR/Centiloid output files themselves, kept for a byte-for-byte comparison later.

Write down the exact commands you ran, so ticket 07 can repeat them identically.

`examples/processed_batch_tree.txt` and `examples/processed_batch_outputs.md` show what a full run produces on a real batch. Note quirk 1 there: the SUVR scripts write every Subject's log lines into the first Subject's log, and leave the others empty. Collect tool commands from all log files of a step together, not per Subject.

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [ ] Ran on a fresh copy of the test dataset with today's production scripts, before any `cate` changes
- [ ] File/folder listing saved for each step
- [ ] Tool commands (from logs) saved for each step
- [ ] Pair folders picked up by register and quantify saved
- [ ] SUVR/Centiloid outputs saved
- [ ] Exact commands used are written down next to the snapshot
