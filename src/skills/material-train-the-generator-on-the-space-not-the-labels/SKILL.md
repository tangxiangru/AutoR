---
name: material-train-the-generator-on-the-space-not-the-labels
description: Use at literature survey, study design and implementation when a generative model is to be built over objects assembled from interchangeable components and the only file you were handed is a small labelled table. Covers splitting the corpus between the unsupervised and supervised halves of the model, recovering the component pools from the columns you already have, and classifying a release's files as apparatus or as answer key before you refuse them.
benchmarks: researchclawbench
applies_when: \b(?:vitrimer\w*|graph variational autoencoder)\b
stages: 01_literature_survey, 03_study_design, 04_implementation
---

# Two corpora, one model: the space trains the generator, the labels train the head

A generative model over assembled objects has two halves that want different data. The encoder and decoder learn the grammar of the components — what a valid molecule, alloy, sequence or lattice looks like, and how to move between them — and they learn it from *unlabelled* examples, of which there are as many as you care to enumerate. Only the property head needs labels, and it needs a few thousand.

The mistake is to size both halves against the labelled table because that is the file you were given. It is the cheapest way to obtain a decoder that emits nothing usable, and the damage is not confined to the decoder: everything downstream that needs a valid sample — latent search, novelty, the interpolation figure — is then unavailable, and the run reports a verdict on the architecture that is really a verdict on the corpus. Write the two corpora into the design as two named datasets with their sizes, and state which loss terms see which.

## The pools are in the columns you already have

Before deciding what is available, count the distinct values in each component column of the supplied table and multiply. This task's `data/tg_vitrimer_MD.csv` holds 8,424 rows built from 7,729 distinct acids and 7,667 distinct epoxides: 59,258,243 combinations, of which the labelled rows are 0.014 %. That enumeration needs no download, no external database and no permission, and it is a corpus three or four orders of magnitude larger than the file it came out of.

Then a consistency check on your own run: if any arm of it enumerates that product space to screen candidates, the corpus exists and you have already built it. A run cannot draw 25,000 candidates per target from a 59-million-combination catalogue and, in another stage, record that the unlabelled corpus "is not shipped". Grep your own notes for sentences claiming a resource is unavailable and re-read each one against what your code is already constructing.

## Classify the release before you refuse it

Freezing yourself against the authors' released *results* is right. Their predictions, metric tables, calibrated labels and optimiser outputs are answer keys; reading one before your own equivalent is computed and hashed turns a measurement into agreement. Their *inputs* are not answers, and the test is simple: **would this file have existed before the study's experiments ran?** Source code, hyperparameters, featurisation, vocabularies, split definitions, filters and candidate pools would. They are apparatus, and refusing them does not make the study more independent — it silently makes it a study of a smaller design space.

So classify every path in the release listing, with a one-line reason each, and keep the classification where the later stages will read it. A register that names only the files you were tempted by has audited the temptation and not the tree; the largest file in a repository is far more likely to be a corpus than an answer key, and a directory named after a chemical database is an input. If you would rather download nothing at all, that is defensible — and then you enumerate the product of the supplied columns and say so. What is not defensible is concluding that the corpus does not exist.

## Report the corpus beside the source's

Pairs or structures presented, epochs, batches, wall clock, against the source's corpus size and compute. A generative metric with no corpus size beside it cannot be read, and a low validity or reconstruction figure reported without one will be taken as the architecture failing.

`material-draw-the-framework-and-rebuild-its-corpus` gives the rebuild procedure and the provenance record, and this does not repeat them. What is here and not there: which half of the model each corpus feeds, the pools recoverable from the supplied columns with no external fetch at all, and the classification decision that is usually what stops the rebuild from happening.

## Why this is here

Measured on Material_003. The run trained its graph VAE on the 7,424-row labelled split and reported, at its own declared denominators, **5 valid decodes of 1,000 draws (0.5 %)** and **0.0 % reconstruction** over 808 held-out pairs. Its study design states "decisively the 999,000-pair corpus **is not shipped**: only the 8,424 labelled pairs exist here", while its own `outputs/inverse_design.json` records `n_acids 7729, n_epoxides 7667, n_recombinations 59258243` and screens 25,000 candidates per target from exactly that space. Its Stage 01 `repo_tree.json` lists `ZINC/all.csv` (92 MB), `ZINC/acid_all.csv` and `ZINC/epoxide_all.csv`; the withheld-artifact register it wrote classifies eleven result tables, never mentions those three, and the string `ZINC` appears in none of the seven stage summaries. A bare agent cloned the same repository six minutes into its run, trained the unsupervised half on the 999,000-pair unlabelled split, and reached 85.9 % reconstruction and 59.3 % validity. The criterion about latent-space design scored 3.3 against 43.3, and the experimental-validation criterion, which needs a delivered candidate to compare against, scored 0.0 against 42.7.
