---
name: chemistry-interaction-inventory-of-the-modelled-complex
description: Use at study design, analysis and writing when the result is a modelled or predicted molecular complex — a docked pose, a co-folded assembly, a binding interface — and RMSD, DockQ or lDDT is about to be the whole answer. Covers the reference-versus-prediction contact inventory per interaction class, the pocket-cropped figure with the interactions drawn, and the mechanism sentence.
benchmarks: researchclawbench
stages: 03_study_design, 06_analysis, 07_writing
---

# Interaction inventory of the modelled complex

## What goes wrong

When the deliverable is a modelled molecular complex — a docked pose, a co-folded
assembly, a predicted interface — the report stops at aggregate distances: RMSD,
DockQ, lDDT, "fraction under the accepted cut". Those say how far the partner is
from where it belongs. None of them says whether the model found the right pocket,
reproduced the recognition chemistry, or kept the specific contacts that hold the
complex together. A reader who wants to know what the model got right about the
chemistry finds nothing to read.

Three symptoms:

- **The only structural figure is a whole-complex superposition.** The interface is
  10–15 Å across inside a 60–80 Å frame, so it occupies a few percent of the canvas.
  No residue is labelled and no contact is drawn. The figure shows that two clouds
  overlap.
- **The contact-level number was computed and dropped.** The fraction of native
  contacts is a term inside DockQ, so any run reporting DockQ already has it, and
  burial counts fall out of any interface routine. This is
  `publish-what-the-run-already-computed`'s sweep, applied to the interface.
- **The prose says the partner is "placed correctly but imprecisely".** That is an
  eyeball claim about a picture with no measurement under it.

A figure list generated from your own hypotheses will not contain this slot, because
no hypothesis asks for it. Reserve it at study design as a deliverable of the subject
matter, not of a hypothesis.

## What to produce

**One table.** The same inventory computed twice — on the experimental reference and
on the prediction — with recovered / missed / spurious columns:

| class | in reference | in prediction | recovered | missed | spurious |

One row per interaction class the system actually has. A complex with no aromatic
partner has no stacking row, and saying so explicitly is part of the inventory. The
classes are the standard non-covalent taxonomy every interaction-fingerprint tool
implements, and each is a distance-and-angle computation over heavy atoms:

- **All heavy-atom contacts** across the interface, under the conventional cut. The
  recovered fraction is the native-contact fraction: print it as a published number,
  not only as an input to a composite score.
- **Hydrogen bonds**: donor N/O to acceptor N/O within the conventional heavy-atom
  distance, with a donor–H–acceptor angle criterion where hydrogens exist and a
  donor-antecedent angle criterion where they do not.
- **Hydrophobic contacts**: apolar carbon pairs within the conventional cut, grouped
  by residue pair. Add buried surface area if a SASA routine is available.
- **Aromatic stacking and cation–π**: enumerate rings on both sides from the bond
  graph, then centroid–centroid distance with the interplanar angle separating
  parallel from T-shaped; for cation–π, a charged or quaternary centroid near a ring
  centroid.
- **Salt bridges**: oppositely charged group pairs within the conventional cut.
- **Per-residue**: contact count and deviation for every residue of the partner, so
  you can name which residue lost its contacts.
  `chemistry-ranked-entities-and-property-curves` owns the shape of that list; what
  is added here is that it is computed on both structures and differenced.

List the contacts by residue and atom name at least once. A count is not an inventory.

## The figure

No other figure skill covers this, and it is the part the deliverable turns on.

- **Crop to the pocket, not to the complex.** Centre the view on the centroid of the
  reference contact set and take the extent from the contacting atoms plus a small
  margin. If the partner occupies less than about a third of the panel, the crop is
  wrong.
- **Two panels, identical axes, identical orientation, identical colouring**:
  reference and prediction, each superposed on the receptor in the same frame. A
  third panel overlaying both partners makes the displacement readable directly.
- **Draw the interactions.** A dashed line per hydrogen bond and per salt bridge, a
  centroid connector per stacking pair, a shaded patch for a hydrophobic cluster.
  Colour by class and put the key inside the panel.
- **Label the site residues** with their identifiers from the source structure, and
  the partner's key atoms or fragments with theirs. An unlabelled pocket cannot be
  checked against the literature by the reader who knows the system.
- **Caption**: what was superposed on what, the alignment used, every cut-off, and
  the recovered / missed / spurious counts, so the panel stands without the table.

If no molecular renderer is installed, the figure is still available and still cheap:
draw the **interface contact map** — partner residues on one axis, receptor site
residues on the other, cells shaded for present-in-reference, present-in-prediction,
and both. That is a distance matrix and matplotlib, it carries recovered / missed /
spurious per residue pair, and it beats a whole-complex projection by a wide margin.

## Two or three sentences of mechanism

Name the recognition element the site is built around — the residues that form it, in
the source's own naming — and say whether the model reproduced it, partially
reproduced it, or replaced it with something else. That is the sentence a domain
reader is looking for, and it cannot be written from an RMSD.

## Calibration

A contact either exists or it does not, and the cut-offs decide it.

- State every cut-off and where it came from, in the caption and in the methods.
- Run the inventory on the reference against itself: it must recover everything.
- Where the reference has replicates — an ensemble, several copies in the asymmetric
  unit, more than one deposit of the same complex — run the inventory across them
  first. The recovery a reference achieves against itself is the band your
  prediction should be read against.

## Checklist

- [ ] Contact set computed for reference and prediction; the native-contact fraction
      appears in the report as a number.
- [ ] Every interaction class present in the system has a row; absent classes are
      named as absent.
- [ ] Contacts listed by residue and atom name at least once, not only counted.
- [ ] Per-residue contact counts and deviations exist for the whole partner.
- [ ] The structural figure is cropped to the interface, identically oriented across
      panels, labelled, with contacts drawn — or is a contact map if no renderer exists.
- [ ] Cut-offs stated with a source; reference-against-itself returns full recovery.
- [ ] The report names the recognition element and says what happened to it.
