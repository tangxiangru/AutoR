#!/bin/bash
#SBATCH --job-name=sklfive
#SBATCH --partition=eval
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=320G
#SBATCH --time=40:00:00
#SBATCH --output=/home/robtang_google_com/rcb_results/slurm/sklfive-%A.out
#SBATCH --error=/home/robtang_google_com/rcb_results/slurm/sklfive-%A.out
#
# The five tasks whose launcher (autorsklA) ended while they were mid-stage. Each had
# 5-6 of 7 stages approved and 9-15 figures published, and a zero-byte report.md -- the
# work was done and the write had not happened, so there is nothing to salvage and the
# rerun is from scratch. Two siblings that had already written their report were marked
# completed in place instead.
#
# 4 cores, not 40. Measured inside a node carrying five of these: cgroup memory.peak
# 260 GB, load average 1.6-1.9, summed process CPU 0.1 cores. The memory request is what
# keeps one element to a node; using a CPU number for that held 36 cores per element on a
# 656-core partition that the job never touched.
set -u
export RCB_MAX_CONCURRENT=5
exec python3 /home/robtang_google_com/rcb_tools/run_arm.py autor_skills \
  Astronomy_000 Chemistry_000 Information_000 Information_001 Information_003
