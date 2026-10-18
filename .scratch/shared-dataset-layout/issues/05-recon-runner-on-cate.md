# 05: The recon runner uses `cate`

**What to build:** The production recon runner runs recon-all and hippocampal segmentation on exactly one MRI per valid Session, taken from `cate`'s layout. Before, it ran on every `.nii` found under any `anat` folder.

- MRIs to process come from the layout: each valid Session's MRI, whether or not the Session has a PET.
- Problem Sessions are logged and skipped. The recon runner's own `.nii` search is deleted.
- The recon folder location comes from `cate` and is unchanged on disk.
- recon-all and segmentation commands, options, logging location and command-line options are unchanged.

**Blocked by:** 01 (Record the "before" snapshot), 02 (The `cate` package)

**Status:** ready-for-agent

- [ ] The recon runner imports `cate`, and its own `.nii` search is gone
- [ ] One MRI per valid Session is processed; a Session with both T1w and CorMPRAGE is reported as a problem, not processed twice
- [ ] Problem Sessions are logged and skipped
- [ ] Commands issued for valid Sessions are identical to before
