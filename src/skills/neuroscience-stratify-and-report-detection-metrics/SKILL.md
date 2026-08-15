---
name: neuroscience-stratify-and-report-detection-metrics
description: Use when the research task is in neuroscience — neural recording, decoding and brain-model comparison — at study design, analysis or writing. Report per-group and per-class detection metrics, and sweep the modality's own degradations
---

# Report per-group and per-class detection metrics, and sweep the modality's own degradations

Neuroscience data arrives with grouping factors, and the field reports per group. Before analysing, list every categorical in the design or the file that is not the label - experimental condition, subject or session, region, cell type, acquisition site, artifact class - and make each one a reporting axis. Every headline number is reported per level, with the pooled value as one additional row. A column present in the data but absent from your tables reads as an unreported factor.

Events of interest are usually rare, so use the detection metric family rather than accuracy or AUROC: precision, recall and F1 at a stated operating threshold, a precision-recall curve with average precision, and a confusion matrix - per class and per stratum. AUROC is insensitive to the prevalence regime the science operates in; report it only alongside these.

Robustness means the corruptions the instrument itself produces - motion, drift, channel or electrode loss, line noise, low SNR, downsampling, session-to-session shift - swept one at a time, each as a degradation curve of the same metric, with the comparison methods on the same axes so relative decay rates are visible. Generic added Gaussian noise does not test this.

Open with provenance: source dataset, acquisition modality, physical extent (volume, duration, subjects, cells), how ground-truth labels were obtained, and how it compares in scale and diversity to the field's other benchmark datasets. If your input is a reduced or simulated stand-in, say what it stands for and instantiate the analyses on it anyway.

## Why this is here

Four of four Neuroscience tasks require per-stratum reporting and it is the single most-missed axis: agents stratified by their own methodological axis (evaluation protocol, learner family) rather than the domain column shipped in the data, and where per-stratum precision/recall/F1 was demanded they reported pooled AUROC/AP. One run computed per-degradation-stratum AUROC into a CSV and put no per-stratum table in the report at all. The provenance clause plus 'instantiate the analyses anyway' attacks the dominant proxy-data pivot: all 8 absent criteria sit in the two tasks whose input is a reduced stand-in, where the agent replaced the study with a critique of the stand-in.
