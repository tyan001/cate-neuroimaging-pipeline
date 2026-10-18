# CATE Neuroimaging

Turns raw MRI and amyloid-PET deliveries from ADRC sites into FreeSurfer volumes, SUVR and Centiloid values per subject and visit.

## Language

**Delivery**:
One raw folder of scans for one subject and one visit, as a site sends it (`MRI_<subj>[-<token>]_<MMDDYYYY>`, `PET_...`).
_Avoid_: dropbox folder, raw folder, batch (a batch is many deliveries)

**Session**:
One subject's visit, identified by its scan date (`YYYYMMDD`). The scan date alone identifies the session, so old deliveries without a session token and new deliveries with one fit the same model. A subject never has two scans of the same kind (MRI or PET) on one day, so a Session holds at most one MRI Delivery and one PET Delivery.
_Avoid_: visit folder, timepoint

**Pair**:
A PET scan matched with the same subject's closest-dated MRI from any Session, used for SUVR. The MRI must be within one year of the PET. A PET with no MRI in that window has no Pair and is not used for SUVR unless someone explicitly approves it. Two MRIs are never the same distance from one PET.
_Avoid_: combo, combination, registration (that is one step of processing a Pair)

**Session token**:
The site's own label for a visit inside a delivery name (`01`, `D1`, `C1`). Older deliveries have none. It is kept as metadata only and is never part of a Session's identity.
_Avoid_: session ID, session number
